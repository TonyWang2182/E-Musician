"""Bounded local-analysis tools, scopes and review plans.

The LLM sees identities and small summaries, never local filenames or PCM. A
candidate is immutable; only the host may turn it into authoritative music.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re
from .selection import ScopeError, assert_scope_unchanged
from audio_analysis.common import PARAMETERS as ANALYSIS_PARAMETERS

KINDS = {"separate": "音源分离", "transcribe": "分轨转 MIDI", "chords": "和弦识别"}
COMMANDS = {"get_analysis_capabilities", "start_analysis", "get_analysis_job",
            "get_analysis_result", "cancel_analysis_job", "accept_analysis_result"}
TERMINAL = {"ready", "applied", "failed", "cancelled", "stale"}
SOURCE_FIELDS = {"project_id", "clip_id", "asset_id", "track_id", "clip_timeline_start",
                 "clip_source_offset", "clip_duration", "bpm", "range_start_seconds",
                 "duration_seconds", "timeline_start", "sample_rate", "source_sha256", "input_role"}
ITEM_FIELDS = {"name", "sample_rate", "channels", "duration_seconds", "sha256", "pitch",
               "start_seconds", "end_seconds", "velocity", "channel", "label", "score", "uncertain"}

def _tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
                       "additionalProperties": False}}}

ANALYSIS_TOOLS = [
    _tool("start_audio_analysis", "对真实音频片段启动本机分析。不会修改工程，不上传音频。工具在本地等候任务，不要反复调用开始；完成后读取候选并提出导入方案。separate=四轨，transcribe=有音高乐器音符(不是鼓)，chords=24种大/小三和弦及无和弦基线。时间以片段内秒计，省略范围时采用当前允许选区。",
          {"clip_id": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
           "start_seconds": {"type": "number", "minimum": 0},
           "duration_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 600},
           "parameters": {"type": "object", "description": "按分析类型选择参数；transcribe用 onset_threshold/frame_threshold/minimum_note_ms/min_pitch/max_pitch，chords用sensitivity/min_region_seconds，separate用segment_seconds。省略保持默认。",
               "properties": {key: {"type": "integer" if key in {"min_pitch", "max_pitch"} else "number", "minimum": bounds[0], "maximum": bounds[1]}
                              for parameters in ANALYSIS_PARAMETERS.values() for key, bounds in parameters.items()}, "additionalProperties": False}}, ["clip_id", "kind"]),
    _tool("read_audio_analysis", "读取真实分析任务状态和最多100项候选。传 job_id 或 result_id 中一个；offset用于结果分页。ready只代表候选完成，applied才表示已写入工程。", {
        "job_id": {"type": "string"}, "result_id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
    _tool("cancel_audio_analysis", "取消尚在运行的本机分析任务。只影响分析，不删除原音频和工程。", {"job_id": {"type": "string"}}, ["job_id"]),
    _tool("propose_analysis_import", "提出一份待用户确认的候选导入方案，单独调用。仅引用已经完成的真实result_id，不提供任意路径或音符数组。不覆盖原音频；分离创建音频轨，转录创建MIDI轨，和弦创建标签区间。", {
        "result_id": {"type": "string"}, "summary": {"type": "string", "maxLength": 500}}, ["result_id", "summary"]),
    _tool("read_chord_regions", "读取工程中已经导入的和弦标签，最多100项。clip_id按真实分析来源筛选；selection范围必须指定已选音频的clip_id，只有project范围可以省略。候选未导入时使用read_audio_analysis。", {
        "clip_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
    _tool("propose_chord_edit", "单独提出一个已有和弦标签的修改方案，待界面确认。时间是工程绝对秒。label只接受N或C/C#/D/D#/E/F/F#/G/G#/A/A#/B加:maj或:min。不生成MIDI。selection范围必须给出来源clip_id，先read_chord_regions获得真实region_id。", {
        "region_id": {"type": "string"}, "clip_id": {"type": "string"}, "label": {"type": "string"},
        "start_seconds": {"type": "number", "minimum": 0}, "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "summary": {"type": "string", "maxLength": 500}}, ["region_id", "summary"]),
]

def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 200 or value.startswith("@") or any(ord(c) < 32 for c in value) or "/" in value or "\\" in value:
        raise ValueError("分析对象 ID 无效。")
    return value

def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("分析时间范围无效。")
    return float(value)

def safe_text(value, maximum=300):
    value = str(value or "")[:maximum]
    # Paths may occur in runtime errors. Neither providers nor the web page need
    # environment locations; the local worker log retains the precise detail.
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "[本机路径]", value)
    value = re.sub(r"(?:\\\\|/home/|/Users/|/tmp/)[^\s]*", "[本机路径]", value)
    return value

def safe_capabilities(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), list):
        return {"providers": [], "available": False}
    providers = []
    for item in raw["providers"]:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        providers.append({"kind": item["kind"], "available": item.get("available") is True,
            "model_id": safe_text(item.get("model_id"), 100), "version": safe_text(item.get("version"), 80),
            "detail": safe_text(item.get("detail")), "experimental": item.get("experimental", True) is True})
    return {"providers": providers, "available": any(p["available"] for p in providers),
            "max_duration_seconds": min(600, number(raw.get("max_duration_seconds", 600), 1, 172800))}

def safe_job(raw):
    if not isinstance(raw, dict):
        raise ValueError("分析任务回执无效。")
    result = {key: deepcopy(raw[key]) for key in ("job_id", "id", "result_id", "clip_id", "kind", "status", "progress", "receipt") if key in raw}
    for field in ("phase", "detail", "error", "summary"):
        if field in raw:
            result[field] = safe_text(raw[field], 500)
    if isinstance(result.get("receipt"), dict):
        result["receipt"] = {k: deepcopy(result["receipt"][k]) for k in ("result_id", "applied", "track_ids", "clip_ids", "chord_ids", "revision") if k in result["receipt"]}
    if isinstance(raw.get("source"), dict):
        result["source"] = {k: deepcopy(v) for k, v in raw["source"].items() if k in SOURCE_FIELDS}
    if isinstance(raw.get("summary"), dict):
        result["summary"] = {k: deepcopy(v) for k, v in raw["summary"].items() if k in {"kind", "total"}}
    return result

def safe_result(raw):
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        raise ValueError("分析候选类型无效。")
    result = {key: deepcopy(raw[key]) for key in ("result_id", "kind", "total", "offset", "result_hash", "applied", "present_in_project", "score_kind", "stale") if key in raw}
    identifier(result.get("result_id"))
    if type(result.get("total")) is not int or not 0 <= result["total"] <= 100000:
        raise ValueError("分析候选数量无效或超过工程预算。")
    result["source"] = {k: deepcopy(v) for k, v in (raw.get("source") or {}).items() if k in SOURCE_FIELDS}
    result["model"] = {k: safe_text(v, 150) for k, v in (raw.get("model") or {}).items()
                       if k in {"id", "model_id", "version", "weight_sha256", "provider", "license_status"}}
    items = raw.get("items", [])
    if not isinstance(items, list) or len(items) > 100 or any(not isinstance(i, dict) for i in items):
        raise ValueError("分析候选分页超出预算。")
    result["items"] = [{k: safe_text(v, 100) if k in {"name", "label"} else deepcopy(v) for k, v in item.items() if k in ITEM_FIELDS} for item in items]
    result["notes_only"] = result["kind"] == "transcribe"
    result["parameters"] = validate_parameters(result["kind"], raw.get("parameters", {}))
    return result

def validate_parameters(kind, parameters):
    if not isinstance(parameters, dict) or set(parameters)-set(ANALYSIS_PARAMETERS[kind]):
        raise ValueError("该分析类型不支持这些参数。")
    values = {}
    for key, value in parameters.items():
        bounds = ANALYSIS_PARAMETERS[kind][key]
        values[key] = number(value, bounds[0], bounds[1])
        if key in {"min_pitch", "max_pitch"}:
            if value != int(value): raise ValueError("音域边界必须是 MIDI 整数。")
            values[key] = int(value)
    if kind == "transcribe" and values.get("min_pitch", 21) > values.get("max_pitch", 108):
        raise ValueError("最低音不能高于最高音。")
    return values

def authorize_start(context, frozen, args):
    """Resolve omitted range to intersection of source clip and frozen scope."""
    assert_scope_unchanged(frozen, context)
    if not isinstance(args, dict) or set(args) - {"clip_id", "kind", "start_seconds", "duration_seconds", "parameters"} or not {"clip_id", "kind"} <= set(args):
        raise ValueError("分析参数无效；只接受已选片段、类型和时间范围。")
    cid = identifier(args["clip_id"])
    kind = args["kind"]
    if kind not in KINDS:
        raise ValueError("不支持这种分析。鼓组转录尚未提供。")
    owner, clip = next(((t, c) for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("id") == cid), (None, None))
    if not clip or clip.get("kind") != "audio":
        raise ScopeError("请选择真实音频片段；MIDI 片段不能作为音频分析输入。")
    if kind == "transcribe" and clip.get("analysis_role") in {"drums", "other"}:
        raise ScopeError("鼓和混合 other 分轨不适用音高转录；请选人声、贝斯或其他独立有音高乐器。")
    clip_start = number(clip.get("start_seconds"), 0, 172800)
    clip_length = number(clip.get("duration_seconds"), 0.000001, 172800)
    lower, upper = 0.0, clip_length
    if frozen["mode"] != "project":
        selection = frozen["selection"]
        if selection.get("focus") == "piano_roll":
            raise ScopeError("音符选择不能授权分析音频，请先选择音频片段。")
        if frozen["mode"] == "clip":
            allowed = cid == selection.get("active_clip_id")
        else:
            chosen = selection.get("clip_ids", [])
            tracks = selection.get("track_ids", [])
            if not tracks and selection.get("focus") == "track":
                tracks = [selection.get("active_track_id")]
            allowed = cid in chosen or (not chosen and owner["id"] in tracks)
            timed = selection.get("time_range") or {}
            if timed.get("active"):
                lower = max(0, timed["start_seconds"] - clip_start)
                upper = min(clip_length, timed["end_seconds"] - clip_start)
        if not allowed or upper <= lower:
            raise ScopeError("音频分析目标不在当前允许的选择范围内。")
    start = number(args.get("start_seconds", lower), 0, 172800)
    length = number(args.get("duration_seconds", upper-start), 0.000001, 600)
    if start < lower - 1e-9 or start + length > upper + 1e-9:
        raise ScopeError("分析范围超出片段或已确认的时间选区。")
    request = {"clip_id": cid, "kind": kind, "start_seconds": start, "duration_seconds": length}
    if "parameters" in args: request["parameters"] = validate_parameters(kind, args["parameters"])
    return request

def authorize_result(context, frozen, result):
    source = result.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("候选来自其他工程，不能导入。")
    request = {"clip_id": source.get("clip_id"), "kind": result["kind"],
               "start_seconds": source.get("range_start_seconds"), "duration_seconds": source.get("duration_seconds")}
    authorize_start(context, frozen, request)
    clip = next(c for t in context["tracks"] for c in t.get("clips", []) if c["id"] == source["clip_id"])
    for a, b in ((context.get("bpm"), source.get("bpm")), (clip.get("start_seconds"), source.get("clip_timeline_start")),
                 (clip.get("duration_seconds"), source.get("clip_duration"))):
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > 1e-8:
            raise ScopeError("候选来源位置、长度或速度已改变，请在 DAW 重新分析。")
    if "asset_id" in clip and clip["asset_id"] != source.get("asset_id"):
        raise ScopeError("候选源素材已替换，请重新分析。")
    if "source_offset" in clip and abs(number(clip["source_offset"], 0, 172800) - number(source.get("clip_source_offset"), 0, 172800)) > 1e-8:
        raise ScopeError("候选源裁剪已改变，请重新分析。")

def authorize_cancel(context, frozen, job):
    """GUI and Agent jobs share scope, but completed/import operations do not."""
    assert_scope_unchanged(frozen, context)
    if not isinstance(job, dict) or job.get("kind") not in KINDS or job.get("status") not in {"queued", "preparing", "running", "validating"} or job.get("operation") == "import":
        raise ValueError("任务已经结束或进入导入阶段，不能再作为分析任务取消。")
    source = job.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("该分析任务不属于当前工程。")
    if frozen["mode"] != "project":
        authorize_start(context, frozen, {"clip_id": source.get("clip_id"), "kind": job["kind"],
            "start_seconds": source.get("range_start_seconds"), "duration_seconds": source.get("duration_seconds")})
    return identifier(job.get("job_id", job.get("id")))

def compile_import(result, context, frozen, summary):
    authorize_result(context, frozen, result)
    if result.get("stale"):
        raise ValueError("候选来源已改变，请在 DAW 重新分析。")
    if result.get("applied"):
        raise ValueError("这份候选已导入；需要还原时使用撤销/重做，不要再次导入。")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("请提供简短的导入说明。")
    kind, total = result["kind"], result["total"]
    if not total:
        raise ValueError("候选为空，没有可导入内容。")
    if kind == "separate" and total != 4:
        raise ValueError("四轨分离候选不完整。")
    new_tracks = 4 if kind == "separate" else 1 if kind == "transcribe" else 0
    if len(context.get("tracks", [])) + new_tracks > 64:
        raise ValueError("导入后会超过 64 轨上限，请先整理工程。")
    result_hash = result.get("result_hash")
    if not isinstance(result_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", result_hash):
        raise ValueError("候选缺少不可变内容标识，不能提交导入。")
    source = result["source"]
    label = {"separate": f"新建 4 条音频轨并导入候选分轨", "transcribe": f"新建 1 条 MIDI 轨，导入 {total} 个候选音符",
             "chords": f"添加 {total} 个和弦标签区间"}[kind]
    changes = [label, f"保持原时间位置：{source['timeline_start']:.3f} 秒起；原音频保留"]
    if kind == "transcribe":
        changes.append("仅导入音符；不恢复原插件音色、弯音和踏板。新 MIDI 轨需选择乐器才能发声。")
    elif kind == "chords":
        changes.append("模板/HMM 基线：大三/小三/无和弦；分数不是正确概率，不生成伴奏音符。")
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": summary.strip(),
            "execution_kind": "analysis_import", "commands": [{"command": "accept_analysis_result", "args": {"result_id": result["result_id"]}}],
            "changes": changes, "steps": [{"index": 1, "label": "核对来源、候选和工程版本"}, {"index": 2, "label": label}],
            "checks": [], "note_clip_ids": [], "analysis": deepcopy(result), "scope": deepcopy(frozen)}

def authorize_chord_read(context, frozen, clip_id):
    assert_scope_unchanged(frozen, context)
    if frozen["mode"] == "project" and not clip_id:
        return ""
    cid = identifier(clip_id)
    # Reuse clip/range scope validation but cap this authorization probe at one
    # second. Reading labels may span a long source; inference's 600s budget is
    # not a restriction on the length of existing project objects.
    clip = next((c for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("id") == cid), None)
    if not clip:
        if frozen["mode"] == "project": return cid  # Provenance may outlive its source clip.
        raise ScopeError("和弦来源不在当前选择中。")
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    lower = max(0, timed.get("start_seconds", 0)-clip["start_seconds"]) if frozen["mode"] == "selection" and timed.get("active") else 0
    upper = min(clip["duration_seconds"], timed.get("end_seconds", 0)-clip["start_seconds"]) if frozen["mode"] == "selection" and timed.get("active") else clip["duration_seconds"]
    authorize_start(context, frozen, {"clip_id": cid, "kind": "chords", "start_seconds": lower, "duration_seconds": min(1, upper-lower)})
    return cid

def compile_chord_edit(args, region, context, frozen):
    if not isinstance(args, dict) or set(args)-{"region_id", "clip_id", "label", "start_seconds", "end_seconds", "summary"}:
        raise ValueError("和弦修改参数无效。")
    if identifier(args.get("region_id")) != region.get("id"):
        raise ValueError("和弦身份不匹配。")
    cid = authorize_chord_read(context, frozen, args.get("clip_id", ""))
    if not isinstance(args.get("summary"), str) or not args["summary"].strip() or len(args["summary"]) > 500:
        raise ValueError("请提供简短的和弦修改说明。")
    changes = {k: args[k] for k in ("label", "start_seconds", "end_seconds") if k in args}
    if not changes:
        raise ValueError("没有提出和弦修改。")
    after = deepcopy(region); after.update(changes)
    if not isinstance(after.get("label"), str) or not re.fullmatch(r"(?:N|(?:C#?|D#?|E|F#?|G#?|A#?|B):(?:maj|min))", after["label"]):
        raise ValueError("首版和弦标签只支持大三、小三和 N（无和弦）。")
    start, end = number(after.get("start_seconds"), 0, 172800), number(after.get("end_seconds"), 0, 172800)
    if start >= end:
        raise ValueError("和弦终点必须大于起点。")
    if frozen["mode"] != "project":
        clip = next(c for t in context["tracks"] for c in t.get("clips", []) if c["id"] == cid)
        for item in (region, after):
            authorize_start(context, frozen, {"clip_id": cid, "kind": "chords",
                "start_seconds": item["start_seconds"]-clip["start_seconds"], "duration_seconds": item["end_seconds"]-item["start_seconds"]})
    if all(region.get(k) == v for k, v in changes.items()):
        raise ValueError("和弦已经是这些值，无需修改。")
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": args["summary"].strip(),
        "execution_kind": "chord_edit", "commands": [{"command": "edit_chord_region", "args": {"id": region["id"], **changes}}],
        "changes": [f"和弦 {region['label']} → {after['label']}", f"时间 {region['start_seconds']:.3f}–{region['end_seconds']:.3f} 秒 → {start:.3f}–{end:.3f} 秒"],
        "checks": [], "note_clip_ids": [], "chord_before": deepcopy(region), "chord_after": after, "chord_clip_id": cid, "scope": deepcopy(frozen)}

def capability_groups(context, host, analysis):
    """Conservative adapter AND host AND current selection capability list."""
    commands = set(host.get("commands", [])) if isinstance(host, dict) else set()
    selected = set((context.get("selection_context") or {}).get("clip_ids", []))
    selected.add((context.get("selection_context") or {}).get("active_clip_id", ""))
    clips = [c for t in context.get("tracks", []) for c in t.get("clips", [])]
    audio = any(c.get("kind") == "audio" and c.get("id") in selected for c in clips)
    groups = []
    for key, label, needed, example in (
        ("project", "工程 / 选区", {"get_snapshot", "get_selection_context"}, "概括一下当前选择的内容。"),
        ("midi", "MIDI 编辑", {"get_clip_notes", "edit_notes"}, "把选中的 MIDI 音符升高一个八度。"),
        ("clips", "片段编辑", {"move_clip", "duplicate_clips", "trim_clip"}, "将选中的片段复制到后面，先列出修改。"),
        ("devices", "原生装置", {"get_native_effect", "set_native_effect", "get_native_instrument"}, "查看当前轨道的原生装置，说明可调整的参数。")):
        ok = needed <= commands
        if key == "devices" and ok:
            from .native_catalog import validate_effect_catalog, validate_instrument_catalog, NativeCatalogError
            try:
                validate_effect_catalog(host.get("native_effect_catalog"))
                validate_instrument_catalog(host.get("native_instrument_catalog"))
            except NativeCatalogError:
                ok = False
        groups.append({"id": key, "label": label, "status": "available" if ok else "unavailable",
                       "status_label": "可用" if ok else "宿主未就绪", "enabled": ok, "example": example,
                       "detail": "读取真实工程；修改先列出方案，确认后应用。"})
    providers = {p["kind"]: p for p in analysis.get("providers", [])} if isinstance(analysis, dict) else {}
    for kind, label in KINDS.items():
        p = providers.get(kind, {})
        installed = COMMANDS <= commands and p.get("available") is True
        applicable = audio and (kind != "transcribe" or any(c.get("id") in selected and c.get("kind") == "audio" and c.get("analysis_role") not in {"drums", "other"} for c in clips))
        status = "experimental" if installed and applicable else "not_applicable" if installed else "unavailable"
        example = {"separate": "把选中音频分成人声、鼓、贝斯、其他，先生成候选。", "transcribe": "把选中的有音高分轨转成 MIDI，保持原时间位置，先预览。",
                   "chords": "识别选中音频的和弦，低分结果标出来，先给我候选。"}[kind]
        detail = p.get("detail") or "请先安装本地分析运行库和模型。"
        if kind == "transcribe": detail += " 只适合有音高乐器；鼓转录待支持。"
        if kind == "chords": detail += " 24 种大/小三和弦与无和弦基线；分数未经校准。"
        groups.append({"id": kind, "label": label, "status": status,
                       "status_label": "实验中" if status == "experimental" else "选择音频" if status == "not_applicable" else "未就绪",
                       "enabled": installed and applicable, "example": example, "detail": detail})
    return groups
