"""Compile an untrusted model proposal into one bounded, reviewable DAW batch.

Only this module translates model intent into commands. It never talks to the
DAW, a model, or the filesystem. Context is a read-only snapshot, augmented by
complete note pages in ``clip_notes``. All beat values are quarter-note beats.
"""
from __future__ import annotations

from copy import deepcopy
import math


class PlanError(ValueError):
    """A proposal cannot safely become an executable plan."""


MAX_ACTIONS = 16
MAX_NOTES = 2000
MAX_SECONDS = 172800
TRACK_FIELDS = ("name", "kind", "gain_db", "pan", "muted", "solo")
CLIP_FIELDS = ("kind", "start_seconds", "duration_seconds", "start_beats", "length_beats", "note_count")
NOTE_FIELDS = ("id", "pitch", "start_beats", "length_beats", "velocity", "channel")


def _shape(kind: str, fields: dict, optional: tuple = ()) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": {"type": {"const": kind}, **fields},
            "required": ["type", *(key for key in fields if key not in optional)]}


_ID = {"type": "string", "minLength": 1, "maxLength": 200}
_NAME = {"type": "string", "minLength": 1, "maxLength": 200}
_NOTE_SCOPE = {"clip_id": _ID, "note_ids": {"type": "array", "minItems": 1,
               "maxItems": MAX_NOTES, "items": _ID, "uniqueItems": True,
               "description": "Explicit note IDs; omit to edit ALL notes in this clip. GUI note selection is unavailable."}}
_ACTIONS = [
    _shape("set_tempo", {"bpm": {"type": "number", "minimum": 20, "maximum": 300}}),
    _shape("rename_track", {"track_id": _ID, "name": _NAME}),
    _shape("create_track", {"kind": {"enum": ["audio", "instrument", "bus"]}, "name": _NAME}),
    _shape("set_track_gain", {"track_id": _ID, "gain_db": {"type": "number", "minimum": -60, "maximum": 6}}),
    _shape("set_track_pan", {"track_id": _ID, "pan": {"type": "number", "minimum": -1, "maximum": 1}}),
    _shape("set_track_muted", {"track_id": _ID, "muted": {"type": "boolean"}}),
    _shape("set_track_solo", {"track_id": _ID, "solo": {"type": "boolean"}}),
    _shape("create_midi_clip", {"track_id": _ID, "start_beats": {"type": "number", "minimum": 0},
                                "length_beats": {"type": "number", "exclusiveMinimum": 0}}),
    _shape("move_clip", {"clip_id": _ID, "start_seconds": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS}}),
    _shape("transpose_notes", {**_NOTE_SCOPE, "semitones": {"type": "integer", "minimum": -127, "maximum": 127}}, ("note_ids",)),
    _shape("quantize_notes", {**_NOTE_SCOPE, "grid_denominator": {"type": "integer", "enum": [2 ** i for i in range(15)]}}, ("note_ids",)),
    _shape("set_note_velocity", {**_NOTE_SCOPE, "velocity": {"type": "integer", "minimum": 1, "maximum": 127}}, ("note_ids",)),
]
PLAN_TOOL = {"type": "function", "function": {"name": "propose_plan",
    "description": "Propose DAW edits for user review, NEVER execute. Use exact existing object IDs. Beat positions use quarter notes; a bar = numerator * 4 / denominator beats. New tracks/clips receive IDs only after Apply, so cannot be referenced in this proposal. Empty clips contain no generated music. Quantization changes note starts only and rejects notes that would extend beyond the clip. Omit unsupported work and explain the limitation; do not invent tools or claim you heard audio.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["summary", "actions"],
                   "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                                  "actions": {"type": "array", "minItems": 1, "maxItems": MAX_ACTIONS,
                                              "items": {"oneOf": _ACTIONS}}}}}}
_SCHEMAS = {shape["properties"]["type"]["const"]: shape for shape in _ACTIONS}


def _text(value: object, field: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise PlanError(f"{field} 必须是 1–{maximum} 字符的单行文本。")
    return value.strip()


def _number(value: object, field: str, low: float, high: float, integer: bool = False) -> float:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise PlanError(f"{field} 必须是 {low:g}–{high:g} 内的有限数字。")
    if integer and value != int(value):
        raise PlanError(f"{field} 必须是整数。")
    return int(value) if integer else float(value)


def _same(a: object, b: object, field: str = "") -> bool:
    if type(a) in (int, float) and type(b) in (int, float):
        tolerance = 2e-5 if field in ("gain_db", "pan") else 1e-9
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=tolerance)
    return type(a) is type(b) and a == b


def _projection(value: dict, fields: tuple) -> dict:
    return {field: value[field] for field in fields if field in value}


def _maps(context: dict) -> tuple[dict, dict]:
    tracks, clips = {}, {}
    raw_tracks = context.get("tracks")
    if not isinstance(raw_tracks, list):
        raise PlanError("工程轨道快照缺失。")
    for track in raw_tracks:
        if not isinstance(track, dict) or not isinstance(track.get("id"), str) or track["id"] in tracks:
            raise PlanError("工程轨道快照无效，请刷新。")
        tracks[track["id"]] = track
        if not isinstance(track.get("clips", []), list):
            raise PlanError("工程片段快照无效，请刷新。")
        for clip in track.get("clips", []):
            if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or clip["id"] in clips:
                raise PlanError("工程片段快照无效，请刷新。")
            clips[clip["id"]] = (track, clip)
    return tracks, clips


def _valid_notes(notes: object, clip: dict) -> list[dict]:
    if not isinstance(notes, list) or len(notes) != clip.get("note_count"):
        raise PlanError("该片段的完整音符尚未读取，请刷新后再生成方案。")
    if len(notes) > MAX_NOTES:
        raise PlanError(f"第一版一次最多编辑 {MAX_NOTES} 个音符。")
    result, ids, channels = [], set(), set()
    for raw in notes:
        if not isinstance(raw, dict) or set(raw) != set(NOTE_FIELDS):
            raise PlanError("音符数据字段不完整。")
        note = dict(raw)
        note["id"] = _text(note["id"], "note_id")
        if note["id"] in ids:
            raise PlanError("音符 ID 重复。")
        ids.add(note["id"])
        for field, low, high in (("pitch", 0, 127), ("velocity", 1, 127), ("channel", 1, 16)):
            note[field] = _number(note[field], field, low, high, True)
        note["start_beats"] = _number(note["start_beats"], "start_beats", 0, float(clip["length_beats"]))
        note["length_beats"] = _number(note["length_beats"], "length_beats", 0, float(clip["length_beats"]))
        end = note["start_beats"] + note["length_beats"]
        if end <= note["start_beats"] or end > clip["length_beats"] + 1e-9:
            raise PlanError("音符长度无效或超出片段范围；不会静默截断。")
        channels.add(note["channel"])
        result.append(note)
    if len(channels) > 1:
        raise PlanError("同一 MIDI 片段必须使用同一通道。")
    return result


def _validate_timeline(context: dict) -> None:
    bpm = _number(context.get("bpm"), "bpm", 20, 300)
    for track in context.get("tracks", []):
        for clip in track.get("clips", []):
            if clip["kind"] == "midi":
                start, length = clip["start_beats"], clip["length_beats"]
                _number(start, "start_beats", 0, MAX_SECONDS * bpm / 60)
                _number(length, "length_beats", 0, MAX_SECONDS * bpm / 60)
                if start + length <= start or start + length > MAX_SECONDS * bpm / 60:
                    raise PlanError("MIDI 片段必须有正长度且位于 48 小时时间线内。")
                clip["start_seconds"] = start * 60 / bpm
                clip["duration_seconds"] = length * 60 / bpm
            else:
                start, duration = clip["start_seconds"], clip["duration_seconds"]
                _number(start, "start_seconds", 0, MAX_SECONDS)
                _number(duration, "duration_seconds", 0, MAX_SECONDS)
                if duration <= 0 or start + duration > MAX_SECONDS:
                    raise PlanError("音频片段必须位于 48 小时时间线内。")


def compile_plan(payload: dict, context: dict) -> dict:
    """Validate model intent, compute exact edits, and retain final postconditions.

    Raises PlanError on unknown fields, unbounded data, missing IDs, out-of-range
    edits or a no-op. The returned command list is for ONE atomic DAW batch.
    """
    if not isinstance(payload, dict) or set(payload) != {"summary", "actions"}:
        raise PlanError("方案必须只包含 summary 和 actions。")
    summary = _text(payload["summary"], "summary", 1000)
    actions = payload["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise PlanError(f"每份方案需要 1–{MAX_ACTIONS} 个操作。")
    if not isinstance(context, dict) or not isinstance(context.get("project_id"), str) or type(context.get("revision")) is not int:
        raise PlanError("缺少当前工程身份和版本。")
    if context.get("recording") or context.get("recording_finalizing") or context.get("counting_in"):
        raise PlanError("录音或预备拍期间暂不生成编辑方案。")
    state = deepcopy(context)
    tracks, clips = _maps(state)
    original_track_ids, original_clip_ids = set(tracks), set(clips)
    if len(tracks) > 64:
        raise PlanError("工程轨道数超出支持范围。")
    commands, changes, added_tracks, added_clips = [], [], [], []
    touched_notes, total_notes = set(), 0
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("type"), str) or action["type"] not in _SCHEMAS:
            raise PlanError("方案包含不支持的操作。")
        kind, shape = action["type"], _SCHEMAS[action["type"]]
        if not set(shape["required"]) <= set(action) or not set(action) <= set(shape["properties"]):
            raise PlanError(f"{kind} 的参数缺失或包含未知字段。")
        args = {key: value for key, value in action.items() if key != "type"}
        track = None
        clip = None
        if "track_id" in args:
            track_id = _text(args["track_id"], "track_id")
            if track_id != args["track_id"] or track_id not in original_track_ids:
                raise PlanError("目标轨道不存在；新轨道请应用后再操作。")
            track = tracks[track_id]
        if "clip_id" in args:
            clip_id = _text(args["clip_id"], "clip_id")
            if clip_id != args["clip_id"] or clip_id not in original_clip_ids:
                raise PlanError("目标片段不存在或尚未读取，请刷新。")
            track, clip = clips[clip_id]
        command = {"command": kind, "args": args}
        changed = True
        if kind == "set_tempo":
            if any(t.get("clips_truncated") for t in tracks.values()):
                raise PlanError("更改速度前需要读取完整片段范围。")
            value = _number(args["bpm"], "bpm", 20, 300)
            old = state["bpm"]
            state["bpm"] = args["bpm"] = value
            changed = not _same(old, value)
            description = f"速度：{old:g} → {value:g} BPM（音频保持原速，MIDI 随速度变化）"
        elif kind == "create_track":
            if args["kind"] not in ("audio", "instrument", "bus"):
                raise PlanError("轨道类型必须是 audio、instrument 或 bus。")
            args["name"] = _text(args["name"], "name")
            if len(tracks) + len(added_tracks) >= 64:
                raise PlanError("工程最多支持 64 条轨道。")
            added_tracks.append(dict(args))
            description = f"新建 {args['kind']} 轨道「{args['name']}」（不自动加载插件）"
        elif kind.startswith("set_track_") or kind == "rename_track":
            field = {"rename_track": "name", "set_track_gain": "gain_db", "set_track_pan": "pan",
                     "set_track_muted": "muted", "set_track_solo": "solo"}[kind]
            value = args[field]
            if field == "name":
                value = _text(value, "name")
            elif field in ("muted", "solo"):
                if type(value) is not bool:
                    raise PlanError(f"{field} 必须是布尔值。")
            else:
                value = _number(value, field, *({"gain_db": (-60, 6), "pan": (-1, 1)}[field]))
            old = track[field]
            args[field] = value
            track[field] = value
            changed = not _same(old, value, field)
            description = f"轨道「{track['name']}」{field}：{old} → {value}"
        elif kind == "create_midi_clip":
            if track["kind"] != "instrument":
                raise PlanError("MIDI 片段只能建在 instrument 轨道上。")
            start = _number(args["start_beats"], "start_beats", 0, MAX_SECONDS * state["bpm"] / 60)
            length = _number(args["length_beats"], "length_beats", 0, MAX_SECONDS * state["bpm"] / 60)
            if sum(t.get("clip_count", len(t.get("clips", []))) for t in tracks.values()) >= 4096:
                raise PlanError("工程最多支持 4096 个片段。")
            args.update(start_beats=start, length_beats=length)
            new = {"id": f"@new-clip-{len(added_clips)}", "kind": "midi", "start_beats": start,
                   "length_beats": length, "note_count": 0}
            track["clip_count"] = track.get("clip_count", len(track.get("clips", []))) + 1
            track.setdefault("clips", []).append(new)
            added_clips.append((track["id"], new))
            bars = length / (state.get("numerator", 4) * 4 / state.get("denominator", 4))
            description = f"「{track['name']}」新建空 MIDI 片段：第 {start:g} 四分音符拍起，{length:g} 拍 / {bars:g} 小节"
        elif kind == "move_clip":
            value = _number(args["start_seconds"], "start_seconds", 0, MAX_SECONDS)
            old = clip["start_seconds"]
            clip["start_seconds"] = args["start_seconds"] = value
            if clip["kind"] == "midi":
                clip["start_beats"] = value * state["bpm"] / 60
            changed = not _same(old, value)
            description = f"「{track['name']}」片段 {clip['id']}：{old:g} → {value:g} 秒"
        else:
            if clip["kind"] != "midi":
                raise PlanError("音符编辑需要 MIDI 片段。")
            notes = _valid_notes(state.get("clip_notes", {}).get(clip["id"]), clip)
            selected = args.get("note_ids", [note["id"] for note in notes])
            if not isinstance(selected, list) or not selected or len(selected) > MAX_NOTES or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
                raise PlanError("需要非空且不重复的音符 ID 列表；空片段没有可编辑音符。")
            selected = set(selected)
            if not selected <= {note["id"] for note in notes}:
                raise PlanError("指定音符已不存在，请重新读取片段。")
            total_notes += len(selected)
            if total_notes > MAX_NOTES:
                raise PlanError(f"每份方案最多处理 {MAX_NOTES} 个音符操作。")
            if kind == "transpose_notes":
                amount = _number(args["semitones"], "semitones", -127, 127, True)
                detail = f"移调 {amount:+d} 半音"
            elif kind == "set_note_velocity":
                amount = _number(args["velocity"], "velocity", 1, 127, True)
                detail = f"力度设为 {amount}"
            else:
                denominator = _number(args["grid_denominator"], "grid_denominator", 1, 16384, True)
                if denominator & (denominator - 1):
                    raise PlanError("网格分母必须是 1–16384 内的 2 的幂。")
                amount = 4 / denominator
                detail = f"起音量化到 1/{denominator}（保留时长）"
            upsert = []
            for note in notes:
                if note["id"] not in selected:
                    continue
                old = dict(note)
                if kind == "transpose_notes":
                    note["pitch"] += amount
                elif kind == "set_note_velocity":
                    note["velocity"] = amount
                else:
                    note["start_beats"] = math.floor(note["start_beats"] / amount + 0.5) * amount
                if note != old:
                    upsert.append(dict(note))
            _valid_notes(notes, clip)
            state.setdefault("clip_notes", {})[clip["id"]] = notes
            touched_notes.add(clip["id"])
            command = {"command": "edit_notes", "args": {"clip_id": clip["id"], "upsert": upsert, "delete_ids": []}}
            changed = bool(upsert)
            description = f"「{track['name']}」片段 {clip['id']}：{detail}；改变 {len(upsert)} / 选定 {len(selected)} 个音符"
        _validate_timeline(state)
        if changed:
            commands.append(command)
            changes.append(description)
    original_tracks, original_clips = _maps(context)
    effective = bool(added_tracks or added_clips) or not _same(state["bpm"], context["bpm"])
    effective |= any(not _same(track.get(field), original_tracks[tid].get(field), field)
                     for tid, track in tracks.items() for field in TRACK_FIELDS)
    effective |= any(not _same(clip.get(field), original_clips[cid][1].get(field), field)
                     for cid, (_, clip) in clips.items() for field in CLIP_FIELDS)
    effective |= any(state["clip_notes"][cid] != context["clip_notes"][cid] for cid in touched_notes)
    if not commands or not effective:
        raise PlanError("所有值已符合要求，没有需要应用的修改。")
    checks = [{"kind": "bpm", "value": state["bpm"]},
              {"kind": "track_count", "value": len(tracks) + len(added_tracks)},
              {"kind": "new_tracks", "values": added_tracks}]
    for tid, track in tracks.items():
        checks.append({"kind": "track", "id": tid, "value": _projection(track, TRACK_FIELDS),
                       "clip_count": track.get("clip_count", len(track.get("clips", [])))})
        for clip in track.get("clips", []):
            if clip["id"] in original_clip_ids:
                checks.append({"kind": "clip", "id": clip["id"], "track_id": tid, "value": _projection(clip, CLIP_FIELDS)})
    checks.append({"kind": "new_clips", "values": [{"track_id": tid, **_projection(clip, CLIP_FIELDS)} for tid, clip in added_clips]})
    for cid in sorted(touched_notes):
        checks.append({"kind": "notes", "id": cid, "value": state["clip_notes"][cid]})
    return {"summary": summary, "commands": commands, "changes": changes, "checks": checks,
            "project_id": context["project_id"], "revision": context["revision"], "note_clip_ids": sorted(touched_notes)}


def verify_plan(plan: dict, before_context: dict, after_context: dict) -> list[str]:
    """Readback postconditions; these validate state, never sound or musical taste."""
    errors = []
    if plan.get("project_id") != before_context.get("project_id") or plan.get("revision") != before_context.get("revision"):
        return ["校验基线与已批准方案不一致。"]
    if after_context.get("project_id") != plan["project_id"]:
        return ["执行后工程身份改变。"]
    try:
        before_tracks, before_clips = _maps(before_context)
        tracks, clips = _maps(after_context)
    except (PlanError, TypeError):
        return ["执行后快照无效。"]

    def matches(actual: dict, expected: dict) -> bool:
        return all(key in actual and _same(actual[key], value, key) for key, value in expected.items())

    def match_new(actual: list[dict], expected: list[dict]) -> bool:
        remaining = list(actual)
        for value in expected:
            for index, candidate in enumerate(remaining):
                if matches(candidate, value):
                    remaining.pop(index)
                    break
            else:
                return False
        return not remaining

    for check in plan.get("checks", []):
        kind = check["kind"]
        if kind == "bpm" and not _same(after_context.get("bpm"), check["value"]):
            errors.append("速度回读与方案不一致。")
        elif kind == "track_count" and len(tracks) != check["value"]:
            errors.append("轨道数量回读与方案不一致。")
        elif kind == "track":
            track = tracks.get(check["id"])
            if track is None or not matches(track, check["value"]) or track.get("clip_count", len(track.get("clips", []))) != check["clip_count"]:
                errors.append(f"轨道 {check['id']} 回读与方案不一致。")
        elif kind == "clip":
            pair = clips.get(check["id"])
            if pair is None or pair[0]["id"] != check["track_id"] or not matches(pair[1], check["value"]):
                errors.append(f"片段 {check['id']} 回读与方案不一致。")
        elif kind == "new_tracks":
            actual = [t for tid, t in tracks.items() if tid not in before_tracks]
            if not match_new(actual, check["values"]):
                errors.append("新建轨道回读与方案不一致。")
        elif kind == "new_clips":
            actual = [{**c, "track_id": t["id"]} for cid, (t, c) in clips.items() if cid not in before_clips]
            if not match_new(actual, check["values"]):
                errors.append("新建片段回读与方案不一致。")
        elif kind == "notes":
            notes = after_context.get("clip_notes", {}).get(check["id"])
            expected = {n["id"]: n for n in check["value"]}
            if not isinstance(notes, list) or any(not isinstance(n, dict) or not isinstance(n.get("id"), str) for n in notes) or len(notes) != len(expected) or {n.get("id") for n in notes} != set(expected) or any(not matches(n, expected.get(n.get("id"), {})) for n in notes):
                errors.append(f"片段 {check['id']} 的音符回读与方案不一致。")
    return errors
