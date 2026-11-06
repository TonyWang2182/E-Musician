"""Serialized, revision-checked access to one owned DAW process."""
from __future__ import annotations
import copy
from pathlib import Path
import threading
import time
import uuid
from agent_client import Client, ControlError

class BridgeError(RuntimeError):
    pass

class NativeJobFailed(BridgeError):
    """A native async job returned a definite unsuccessful terminal state."""
    pass

def identity(context):
    return context.get("project_id"), context.get("revision")

def public_snapshot(raw):
    fields = ("project_id", "revision", "name", "dirty", "bpm", "numerator",
              "denominator", "duration_seconds", "position_seconds", "playing",
              "selected_track_id", "selected_clip_id", "can_undo", "can_redo",
              "recording", "recording_finalizing", "counting_in", "tracks", "master_plugins", "selection_context")
    result = {k: copy.deepcopy(raw[k]) for k in fields if k in raw}
    def public_plugins(plugins):
        if not isinstance(plugins,list): return []
        safe=[]
        for plugin in plugins:
            if not isinstance(plugin,dict): continue
            item={k:copy.deepcopy(plugin[k]) for k in ("id","name","format","enabled","missing","is_instrument") if k in plugin}
            # Plugin identifiers may contain absolute VST paths. Even a plugin
            # with a path-like display name should not reveal its location.
            if isinstance(item.get("name"),str) and ("/" in item["name"] or "\\" in item["name"]):
                item["name"]="Plugin"
            safe.append(item)
        return safe
    result["master_plugins"] = public_plugins(result.get("master_plugins",[]))
    for track in result.get("tracks", []):
        for key in list(track):
            if key not in {"id", "name", "kind", "gain_db", "pan", "muted", "solo", "colour",
                           "clips", "clip_count", "clips_truncated", "plugins"}:
                del track[key]
        track["plugins"] = public_plugins(track.get("plugins",[]))
    result["clip_notes"] = {}
    from .analysis import safe_job
    result["analysis_jobs"] = [safe_job(j) for j in raw.get("analysis_jobs", [])[-12:] if isinstance(j, dict)]
    from .generation import safe_job as safe_generation_job
    result["generation_jobs"] = [safe_generation_job(j) for j in raw.get("generation_jobs", [])[-12:] if isinstance(j, dict)]
    result["context_limits"] = "Clip preview: max 64/track, 256 total. Notes read on demand, max 2000/clip."
    return result

class DawBridge:
    def __init__(self, executable: Path | None = None, *, offline=False, client=None, embedded=False):
        self.lock = threading.RLock()
        self.connected = True
        self._capabilities = None
        self._analysis_capabilities = {"providers": [], "available": False}
        self._analysis_checked = 0.0
        self._generation_capabilities = {"available": False}
        self._generation_checked = 0.0
        self.embedded = bool(embedded or getattr(client, "embedded", False))
        if self.embedded and client is None:
            raise ValueError("Embedded mode requires a host-owned transport.")
        self.client = client or Client(executable, timeout=20, show=not offline, offline_test=offline)

    def _request(self, envelope, *, allow_accepted=False):
        with self.lock:
            if not self.connected:
                raise BridgeError("DAW 连接已断开；请先保存并关闭受控窗口，再重新启动助手。")
            request = dict(envelope)
            request.setdefault("request_id", str(uuid.uuid4()))
            try:
                result = self.client.raw(request)
            except (OSError, EOFError, ControlError, AssertionError) as exc:
                # A timeout may still have committed. Never issue another request
                # on an ambiguous stream, nor blindly retry a write.
                self.connected = False
                raise BridgeError("DAW 未能及时返回。结果未知，已停止后续命令；请在 DAW 检查工程。") from exc
            if not isinstance(result, dict) or result.get("request_id") != request["request_id"]:
                self.connected = False
                raise BridgeError("DAW 响应顺序不匹配，已停止后续命令。")
            if result.get("status") != "completed" and not (allow_accepted and result.get("status") == "accepted"):
                status = result.get("status", "invalid")
                if status in ("conflict", "wrong_project"):
                    raise BridgeError("工程已变化，旧方案未应用。请重新提出要求。")
                if status == "selection_conflict":
                    raise BridgeError("音乐选择已变化，旧方案未应用。请重新生成方案。")
                raise BridgeError("DAW 拒绝操作：" + str(result.get("error") or status)[:500])
            return result

    def capabilities(self):
        with self.lock:
            if self._capabilities is None:
                value = self._request({"command":"get_capabilities"})["result"]
                if not isinstance(value,dict):
                    raise BridgeError("DAW 能力响应无效。")
                self._capabilities = copy.deepcopy(value)
            return copy.deepcopy(self._capabilities)

    def require_native_effect_catalog(self):
        from .native_catalog import NativeCatalogError, validate_effect_catalog
        try:
            validate_effect_catalog(self.capabilities().get("native_effect_catalog"))
        except NativeCatalogError as exc:
            raise BridgeError(str(exc)) from exc

    def require_native_instrument_catalog(self):
        from .native_catalog import NativeCatalogError, validate_instrument_catalog
        try:
            validate_instrument_catalog(self.capabilities().get("native_instrument_catalog"))
        except NativeCatalogError as exc:
            raise BridgeError(str(exc)) from exc

    def snapshot(self):
        return public_snapshot(self._request({"command": "get_snapshot"})["result"])

    def analysis_capabilities(self, refresh=False):
        from .analysis import COMMANDS, safe_capabilities
        with self.lock:
            if not COMMANDS <= set(self.capabilities().get("commands", [])):
                return {"providers": [], "available": False}
            if refresh or time.monotonic() - self._analysis_checked > 5:
                raw = self._request({"command": "get_analysis_capabilities"})["result"]
                self._analysis_capabilities = safe_capabilities(raw)
                self._analysis_checked = time.monotonic()
            return copy.deepcopy(self._analysis_capabilities)

    def generation_capabilities(self, refresh=False):
        from .generation import COMMANDS, safe_capabilities
        with self.lock:
            if not COMMANDS <= set(self.capabilities().get("commands", [])):
                return {"available": False}
            if refresh or time.monotonic() - self._generation_checked > 5:
                self._generation_capabilities = safe_capabilities(self._request({"command": "get_generation_capabilities"})["result"])
                self._generation_checked = time.monotonic()
            return copy.deepcopy(self._generation_capabilities)

    def start_generation(self, context, scope, args):
        from .generation import authorize_start
        from .analysis import identifier
        request = authorize_start(context, scope, args)
        if self.generation_capabilities(refresh=True).get("available") is not True:
            raise BridgeError("云端生成模型尚未就绪，请在 DAW 生成面板检查连接。")
        envelope = {"command": "start_generation", "project_id": context["project_id"], "expected_revision": context["revision"], "args": request}
        if scope.get("mode") != "project": envelope["expected_selection_revision"] = scope["selection_revision"]
        reply = self._request(envelope, allow_accepted=True)
        return {"job_id": identifier((reply.get("result") or {}).get("job_id"))}

    def generation_job(self, job_id):
        from .generation import safe_job
        from .analysis import identifier
        value = safe_job(self._request({"command": "get_generation_job", "args": {"job_id": identifier(job_id)}})["result"])
        if value.get("job_id") != job_id:
            raise BridgeError("生成任务身份不匹配。")
        return value

    def generation_result(self, result_id):
        from .generation import safe_result
        from .analysis import identifier
        value = safe_result(self._request({"command": "get_generation_result", "args": {"result_id": identifier(result_id)}})["result"])
        if value["result_id"] != result_id: raise BridgeError("生成候选身份不匹配。")
        return value

    def cancel_generation(self, job_id):
        from .analysis import identifier
        raw = self._request({"command": "get_job", "args": {"job_id": identifier(job_id)}})["result"]
        if not isinstance(raw, dict) or raw.get("kind") != "generation.generate" or raw.get("status") in {"completed", "ready", "failed", "cancelled", "stale", "applied"}:
            raise BridgeError("该任务已经结束或是导入任务，没有发送取消。")
        return self._request({"command": "cancel_generation_job", "args": {"job_id": job_id}})

    def preview_generation(self, result_id=None):
        from .analysis import identifier
        if result_id is None:
            return self._request({"command": "stop_generation_preview"})
        context = self.snapshot()
        return self._request({"command": "preview_generation_result", "project_id": context["project_id"], "expected_revision": context["revision"],
                              "args": {"result_id": identifier(result_id)}}, allow_accepted=True)

    def generation_preview_status(self, job_id):
        from .analysis import identifier, safe_text
        job_id = identifier(job_id)
        job = self._request({"command": "get_job", "args": {"job_id": job_id}})["result"]
        if not isinstance(job, dict) or job.get("id") != job_id or job.get("kind") != "generation.preview":
            raise BridgeError("生成试听任务身份不匹配。")
        state = job.get("status")
        if state in {"queued", "running"}: return {"status": "preparing", "job_id": job_id}
        if state in {"failed", "cancelled", "conflict"}:
            detail = safe_text(job.get("error"), 400)
            status = "unavailable" if "No audio output is active" in detail else "stopped" if state == "cancelled" else "failed"
            return {"status": status, "detail": detail, "job_id": job_id}
        if state != "completed": raise BridgeError("生成试听状态未知。")
        stream = self._request({"command": "get_analysis_preview_status"})["result"]
        if not isinstance(stream, dict) or stream.get("status") not in {"loading", "playing", "completed", "stopped", "failed", "unavailable"}:
            raise BridgeError("生成试听流状态无效。")
        return {"status": stream["status"], "detail": safe_text(stream.get("detail"), 400), "job_id": job_id}

    def start_analysis(self, context, scope, args):
        from .analysis import authorize_start, identifier
        with self.lock:
            request = authorize_start(context, scope, args)
            providers = self.analysis_capabilities().get("providers", [])
            if not any(p["kind"] == request["kind"] and p["available"] for p in providers):
                raise BridgeError("本地分析运行库或模型尚未就绪。请先在 DAW 分析面板检查。")
            envelope = {"command": "start_analysis", "project_id": context["project_id"],
                        "expected_revision": context["revision"], "args": request}
            if scope.get("mode") != "project":
                envelope["expected_selection_revision"] = scope["selection_revision"]
            reply = self._request(envelope, allow_accepted=True)
            result = reply.get("result") or {}
            return {"job_id": identifier(result.get("job_id"))}

    def analysis_job(self, job_id):
        from .analysis import identifier, safe_job
        value = safe_job(self._request({"command": "get_analysis_job", "args": {"job_id": identifier(job_id)}})["result"])
        if value.get("job_id", value.get("id")) != job_id:
            raise BridgeError("分析任务身份不匹配。")
        return value

    def analysis_result(self, result_id, offset=0, limit=24):
        from .analysis import identifier, safe_result
        if type(offset) is not int or not 0 <= offset <= 100000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("分析分页范围无效。")
        value = safe_result(self._request({"command": "get_analysis_result", "args": {
            "result_id": identifier(result_id), "offset": offset, "limit": limit}})["result"])
        if value["result_id"] != result_id or value.get("offset", offset) != offset or len(value["items"]) != min(limit, max(0, value["total"]-offset)):
            raise BridgeError("分析分页身份或数量不匹配。")
        return value

    def cancel_analysis(self, job_id):
        from .analysis import identifier
        # The generic job kind distinguishes an import even during the tiny
        # queued/running interval before its worker publishes "applying".
        raw = self._request({"command": "get_job", "args": {"job_id": identifier(job_id)}})["result"]
        if not isinstance(raw, dict) or raw.get("kind") not in {"analysis.separate", "analysis.transcribe", "analysis.chords", "analysis.beats"} or raw.get("status") not in {"queued", "preparing", "running", "validating"}:
            raise BridgeError("任务已结束或是导入任务，没有发送取消。")
        return self._request({"command": "cancel_analysis_job", "args": {"job_id": identifier(job_id)}})

    def chord_page(self, context, clip_id="", offset=0, limit=100):
        from .analysis import identifier, safe_text, number
        if type(offset) is not int or not 0 <= offset <= 10000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("和弦分页范围无效。")
        with self.lock:
            if not {"get_chord_regions", "edit_chord_region"} <= set(self.capabilities().get("commands", [])):
                raise BridgeError("当前宿主未提供和弦读写接口。")
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("读取和弦期间工程已变化。")
            args = {"offset": offset, "limit": limit}
            if clip_id: args["clip_id"] = identifier(clip_id)
            raw = self._request({"command": "get_chord_regions", "args": args})["result"]
            total, items = raw.get("total"), raw.get("items")
            if type(total) is not int or not 0 <= total <= 10000 or raw.get("offset") != offset or not isinstance(items, list) or len(items) != min(limit, max(0, total-offset)):
                raise BridgeError("和弦分页数量或身份不匹配。")
            safe = []
            for item in items:
                if not isinstance(item, dict): raise BridgeError("和弦对象无效。")
                start, end = number(item.get("start_seconds"), 0, 172800), number(item.get("end_seconds"), 0, 172800)
                if start >= end or type(item.get("uncertain")) is not bool: raise BridgeError("和弦对象时间无效。")
                safe.append({"id": identifier(item.get("id")), "analysis_id": identifier(item.get("analysis_id")),
                    "label": safe_text(item.get("label"), 30), "start_seconds": start, "end_seconds": end,
                    "score": number(item.get("score"), 0, 1), "uncertain": item["uncertain"]})
            if len({i["id"] for i in safe}) != len(safe) or identity(self.snapshot()) != identity(context):
                raise BridgeError("和弦读取不完整或工程已改变。")
            return {"items": safe, "total": total, "offset": offset, "score_kind": "uncalibrated_similarity"}

    def find_chord(self, context, region_id, clip_id=""):
        from .analysis import identifier
        identifier(region_id)
        offset, total = 0, None
        while total is None or offset < total:
            page = self.chord_page(context, clip_id, offset, 100)
            if total is not None and page["total"] != total:
                raise BridgeError("和弦分页期间总数发生变化。")
            total = page["total"]
            for item in page["items"]:
                if item["id"] == region_id: return item
            offset += 100
        raise BridgeError("该和弦不属于指定来源片段，或已经删除。")

    def resolve_clips(self, context, clip_ids):
        """Load exact requested IDs beyond the bounded preview, preserving limits.

        Pages are inspected locally; unrelated hidden clips never enter model
        context. The original clip_count/truncation stays truthful.
        """
        if not isinstance(clip_ids, (list, tuple, set)) or len(clip_ids) > 4096 or any(not isinstance(i, str) or not i for i in clip_ids):
            raise BridgeError("片段范围无效。")
        with self.lock:
            tracks = context.get("tracks", [])
            existing = {c["id"] for t in tracks for c in t.get("clips", [])}
            missing = set(clip_ids) - existing
            if not missing:
                return
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("读取片段期间工程已变化。")
            selection = context.get("selection_context") or {}
            preferred = set(selection.get("track_ids", [])) | {selection.get("active_track_id")}
            candidates = sorted(tracks, key=lambda t: t["id"] not in preferred)
            additions = []
            for track in candidates:
                total = track.get("clip_count", len(track.get("clips", [])))
                if type(total) is not int or not 0 <= total <= 4096:
                    raise BridgeError("轨道片段数量无效。")
                if total <= len(track.get("clips", [])):
                    continue
                page_ids = set()
                for offset in range(0, total, 256):
                    page = self._request({"command": "get_track_clips", "args": {
                        "track_id": track["id"], "offset": offset, "limit": 256}})["result"]
                    values = page.get("clips")
                    if page.get("total") != total or page.get("offset") != offset or not isinstance(values, list) or len(values) != min(256, total-offset):
                        raise BridgeError("片段分页发生变化或读取不完整。")
                    for clip in values:
                        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or clip["id"] in page_ids:
                            raise BridgeError("片段分页包含重复或无效身份。")
                        page_ids.add(clip["id"])
                        if clip["id"] in missing:
                            additions.append((track, copy.deepcopy(clip)))
                            missing.remove(clip["id"])
                    if not missing:
                        break
                if not missing:
                    break
            if missing or identity(self.snapshot()) != identity(context):
                raise BridgeError("选中片段已删除或工程在读取时发生变化。")
            for track, clip in additions:
                track.setdefault("clips", []).append(clip)
                track["clips_truncated"] = len(track["clips"]) < track["clip_count"]

    def resolve_selection(self, context):
        selection = context.get("selection_context") or {}
        ids = list(selection.get("clip_ids", []))
        for field in ("active_clip_id", "note_clip_id"):
            if selection.get(field):
                ids.append(selection[field])
        self.resolve_clips(context, set(ids))

    def read_notes(self, context, clip_id):
        with self.lock:
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("读取期间工程已变化，请重新提出要求。")
            clips = [c for t in context.get("tracks", []) for c in t.get("clips", [])]
            clip = next((c for c in clips if c["id"] == clip_id), None)
            if not clip or clip.get("kind") != "midi":
                raise BridgeError("请选择当前快照中的 MIDI 片段。")
            total = clip.get("note_count", 0)
            if type(total) is not int or total > 2000 or total < 0:
                raise BridgeError("首版单次处理最多 2000 个音符，请先在 DAW 分割片段。")
            notes = []
            for offset in range(0, max(1, total), 1000):
                page = self._request({"command": "get_clip_notes",
                    "args": {"clip_id": clip_id, "offset": offset, "limit": 1000}})["result"]
                if page.get("total") != total or page.get("offset") != offset:
                    raise BridgeError("音符分页发生变化，已放弃旧读取。")
                notes.extend(page.get("notes", []))
            if len(notes) != total or identity(self.snapshot()) != identity(context):
                raise BridgeError("音符读取不完整或工程已变化，请重试。")
            context["clip_notes"][clip_id] = notes
            return notes

    def read_native_effect(self, context, track_id, device_id):
        from .plans import validate_effect_state, PlanError, EFFECT_NAMES
        with self.lock:
            self.require_native_effect_catalog()
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("读取效果器期间工程已变化。")
            track = next((t for t in context.get("tracks", []) if t.get("id") == track_id), None)
            plugins = context.get("master_plugins",[]) if track_id == "master" else (track or {}).get("plugins", [])
            plugin = next((p for p in plugins if p.get("id") == device_id), None)
            if not plugin or plugin.get("format") != "E-musician" or plugin.get("is_instrument") is not False or plugin.get("name") not in EFFECT_NAMES.values():
                raise BridgeError("效果器不存在、类型不支持或不属于指定轨道。")
            result = self._request({"command":"get_native_effect", "args":{"track_id":track_id,"device_id":device_id}}).get("result")
            if not isinstance(result,dict) or result.get("device_id") != device_id:
                raise BridgeError("效果器回读身份不匹配。")
            try:
                state = validate_effect_state(result.get("state"))
            except PlanError as exc:
                raise BridgeError("效果器状态无效。") from exc
            if plugin["name"] != EFFECT_NAMES.get(state["type"]) or identity(self.snapshot()) != identity(context):
                raise BridgeError("效果器类型或工程版本在读取期间变化。")
            context.setdefault("native_effects", {})[device_id] = state
            return copy.deepcopy(state)

    def read_native_instrument(self, context, track_id):
        from .plans import PlanError, _number
        with self.lock:
            self.require_native_instrument_catalog()
            if identity(self.snapshot()) != identity(context): raise BridgeError("读取采样器期间工程已变化。")
            if not any(t.get("id")==track_id for t in context.get("tracks",[])): raise BridgeError("采样器轨道不存在。")
            raw=self._request({"command":"get_native_instrument","args":{"track_id":track_id}}).get("result")
            if not isinstance(raw,dict) or raw.get("type") not in {"sampler","drum_rack"} or raw.get("load_status") != "ready":
                raise BridgeError("采样器或鼓组尚未准备完成。")
            try:
                pads=raw.get("pads")
                count=1 if raw["type"]=="sampler" else 16
                if not isinstance(pads,list) or len(pads)!=count: raise ValueError("invalid pads")
                safe=[]
                for index,p in enumerate(pads):
                    if not isinstance(p,dict) or p.get("index")!=index or type(p.get("muted")) is not bool: raise ValueError("invalid pad")
                    sha=p.get("sample_sha256", "")
                    if not isinstance(sha,str) or len(sha) not in (0,64) or (sha and any(c not in "0123456789abcdef" for c in sha)): raise ValueError("invalid sample identity")
                    one_shot=p.get("one_shot",raw["type"]=="drum_rack")
                    if type(one_shot) is not bool: raise ValueError("invalid playback mode")
                    safe.append({"index":index,"gain_db":_number(p.get("gain_db"),"gain_db",-60,6),"muted":p["muted"],"sample_sha256":sha,
                                 "attack_ms":_number(p.get("attack_ms",3),"attack_ms",0.1,2000),
                                 "release_ms":_number(p.get("release_ms",30),"release_ms",1,5000),"one_shot":one_shot})
                state={"type":raw["type"],"device_id":raw.get("device_id"),"load_status":"ready","pads":safe}
                if not isinstance(state["device_id"],str) or not state["device_id"]: raise ValueError("missing device")
                if raw["type"]=="sampler":
                    state.update(root_note=_number(raw.get("root_note"),"root_note",0,127,True),start=_number(raw.get("start"),"start",0,1),end=_number(raw.get("end"),"end",0,1))
                    if state["start"]>=state["end"]: raise ValueError("bad sample range")
            except (PlanError,ValueError,TypeError) as exc: raise BridgeError("采样器状态无效。") from exc
            if identity(self.snapshot()) != identity(context): raise BridgeError("读取采样器期间工程已变化。")
            context.setdefault("native_instruments",{})[track_id]=state
            return copy.deepcopy(state)

    def audio_warp(self, context, clip_ids):
        from .tempo import safe_warp
        with self.lock:
            if not {"get_audio_warp","set_audio_warp"}<=set(self.capabilities().get("commands",[])):
                raise BridgeError("当前宿主未提供音频Warp接口。")
            if identity(self.snapshot())!=identity(context):raise BridgeError("读取Warp期间工程已变化。")
            value=safe_warp(self._request({"command":"get_audio_warp","args":{"clip_ids":clip_ids}})["result"],clip_ids)
            if identity(self.snapshot())!=identity(context):raise BridgeError("读取Warp期间工程已变化。")
            return value

    def apply(self, plan):
        if plan.get("execution_kind") == "generation_import":
            from .generation import compile_import
            candidate = self.generation_result(plan["generation"]["result_id"])
            if candidate.get("result_hash") != plan["generation"].get("result_hash"):
                raise BridgeError("生成候选在预览后发生变化，没有提交旧方案。")
            compile_import(candidate, self.snapshot(), plan["scope"], plan["summary"])
            envelope = {"request_id": plan["id"], "command": "accept_generation_result",
                        "project_id": plan["project_id"], "expected_revision": plan["revision"],
                        "args": {"result_id": candidate["result_id"], "result_hash": candidate["result_hash"]}}
            if plan["scope"].get("mode") != "project": envelope["expected_selection_revision"] = plan["scope"]["selection_revision"]
            reply = self._request(envelope, allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"), str):
                raise BridgeError("生成导入回执异常，结果未知；请检查 DAW，不要重复提交。")
            return reply
        if plan.get("execution_kind") in {"audio_warp","beat_apply"}:
            from .tempo import compile_warp, compile_beats
            current=self.snapshot();args=plan["commands"][0]["args"]
            ids=[item["clip_id"] for item in plan["warp_before"]]
            states=self.audio_warp(current,ids)
            if states!=plan["warp_before"]:raise BridgeError("Warp在预览后已变化，没有提交旧方案。")
            if plan["execution_kind"]=="beat_apply":
                candidate=self.analysis_result(plan["analysis"]["result_id"])
                if candidate.get("result_hash")!=plan["analysis"].get("result_hash"):raise BridgeError("节拍候选已变化。")
                compile_beats({**args,"summary":plan["summary"]},candidate,current,plan["scope"],states)
            else:
                compile_warp({**{k:v for k,v in args.items() if k!="mode"},"summary":plan["summary"]},current,plan["scope"],states)
            command=plan["commands"][0]["command"]
            if command not in self.capabilities().get("commands",[]):raise BridgeError("宿主缺少本次Warp命令。")
            envelope={"request_id":plan["id"],"project_id":plan["project_id"],"expected_revision":plan["revision"],"command":command,"args":args}
            if plan["scope"]["mode"]!="project":envelope["expected_selection_revision"]=plan["scope"]["selection_revision"]
            reply=self._request(envelope,allow_accepted=True)
            if reply.get("status")!="accepted" or not isinstance((reply.get("result") or {}).get("job_id"),str):
                raise BridgeError("Warp回执异常，结果未知；请检查DAW，不要重复提交。")
            return reply
        if plan.get("execution_kind") == "chord_edit":
            from .analysis import compile_chord_edit
            current = self.snapshot()
            region = self.find_chord(current, plan["chord_before"]["id"], plan.get("chord_clip_id", ""))
            if region != plan["chord_before"]:
                raise BridgeError("和弦在预览后发生变化，未提交旧方案。")
            args = plan["commands"][0]["args"]
            compile_chord_edit({"region_id": args["id"], "clip_id": plan.get("chord_clip_id", ""), "summary": plan["summary"],
                **{k: v for k, v in args.items() if k != "id"}}, region, current, plan["scope"])
            envelope = {"request_id": plan["id"], "project_id": plan["project_id"], "expected_revision": plan["revision"],
                "command": "edit_chord_region", "args": args}
            if plan["scope"].get("mode") != "project": envelope["expected_selection_revision"] = plan["scope"]["selection_revision"]
            return self._request(envelope)
        if plan.get("execution_kind") == "analysis_import":
            from .analysis import authorize_result
            result_id = plan["analysis"]["result_id"]
            result = self.analysis_result(result_id)
            if result.get("result_hash") != plan["analysis"].get("result_hash") or result.get("applied"):
                raise BridgeError("候选已变化或已导入；没有再次提交。")
            current = self.snapshot()
            authorize_result(current, plan["scope"], result)
            envelope = {"request_id": plan["id"], "command": "accept_analysis_result",
                "project_id": plan["project_id"], "expected_revision": plan["revision"],
                "args": {"result_id": result_id}}
            if plan["scope"].get("mode") != "project":
                envelope["expected_selection_revision"] = plan["scope"]["selection_revision"]
            reply = self._request(envelope, allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"), str):
                raise BridgeError("分析导入回执异常，结果未知；请检查 DAW，不要重复提交。")
            return reply
        if any(c.get("command") in {"add_native_effect", "set_native_effect"} for c in plan.get("commands",[])):
            self.require_native_effect_catalog()
        if (plan.get("scope") or {}).get("mode") != "project" and any(
            c.get("command") in {"add_native_effect","set_native_effect"} and c.get("args",{}).get("track_id") == "master"
            for c in plan.get("commands",[])):
            raise BridgeError("主轨效果器只能在工程范围修改。")
        if plan.get("execution_kind") == "native_async":
            self.require_native_instrument_catalog()
            commands=plan.get("commands",[])
            if (plan.get("scope") or {}).get("mode") != "project" or len(commands)!=1 or commands[0].get("command") not in {"set_native_pad","set_native_sampler"}:
                raise BridgeError("异步采样器方案必须为工程范围的单个操作。")
            envelope={"request_id":plan["id"],"project_id":plan["project_id"],"expected_revision":plan["revision"],
                      "command":commands[0]["command"],"args":commands[0]["args"]}
            reply=self._request(envelope,allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"),str):
                raise BridgeError("采样器操作回执异常，结果未知；请检查 DAW，不要重复提交。")
            return reply
        if any("as" in c for c in plan["commands"]):
            version = self.capabilities().get("batch_result_refs_version")
            if type(version) is not int or version != 1:
                raise BridgeError("DAW 未声明支持连续依赖方案，没有发送修改。")
        envelope = {"request_id": plan["id"], "project_id": plan["project_id"],
            "expected_revision": plan["revision"], "command": "batch",
            "args": {"commands": plan["commands"]}}
        scope = plan.get("scope") or {}
        if scope.get("mode") in {"selection", "clip"}:
            envelope["expected_selection_revision"] = scope["selection_revision"]
        return self._request(envelope,allow_accepted=True)

    def wait_edit_job(self,job_id,timeout=180.0):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            job=self._request({"command":"get_job","args":{"job_id":job_id}}).get("result")
            if not isinstance(job,dict) or job.get("id")!=job_id:raise BridgeError("后台编辑任务身份不匹配。")
            if job.get("status")=="completed":
                if not isinstance(job.get("result"),dict):raise BridgeError("后台编辑缺少完整回执；请检查DAW。")
                return job["result"]
            if job.get("status") in {"failed","conflict","cancelled","stale"}:
                raise NativeJobFailed("后台编辑未提交："+str(job.get("error") or job["status"])[:300])
            time.sleep(.05)
        raise BridgeError("后台编辑等待超时，结果未知；请检查DAW，不要重复提交。")

    def wait_native_job(self, job_id, timeout=30.0):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            job=self._request({"command":"get_job","args":{"job_id":job_id}}).get("result")
            if not isinstance(job,dict) or job.get("id")!=job_id: raise BridgeError("后台任务回执异常，结果未知；请检查 DAW。")
            if job.get("status")=="completed": return
            if job.get("status") in {"failed","conflict","cancelled"}:
                raise NativeJobFailed("采样器任务未提交："+str(job.get("error") or job["status"])[:300])
            time.sleep(0.05)
        raise BridgeError("已提交后台采样任务，但等待超时，结果未知；请检查 DAW，不要重复提交。")

    def wait_analysis_import(self, job_id, timeout=180.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.analysis_job(job_id)
            if job.get("status") == "applied":
                receipt = job.get("receipt")
                if not isinstance(receipt, dict) or receipt.get("applied") is not True:
                    raise BridgeError("分析导入完成回执无效；请检查 DAW，不要重复提交。")
                return receipt
            if job.get("status") in {"failed", "stale", "cancelled"}:
                raise NativeJobFailed("分析候选未导入：" + str(job.get("error") or job["status"])[:300])
            time.sleep(0.1)
        raise BridgeError("分析导入已受理，但等待超时；结果未知，请检查 DAW，不要重复提交。")

    def wait_generation_import(self, job_id, timeout=180.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.generation_job(job_id)
            if job.get("status") == "applied":
                receipt = job.get("receipt")
                if not isinstance(receipt, dict) or receipt.get("applied") is not True:
                    raise BridgeError("生成导入完成回执无效；请检查 DAW，不要重复提交。")
                return receipt
            if job.get("status") in {"failed", "stale", "cancelled", "conflict"}:
                raise NativeJobFailed("生成音频未导入：" + str(job.get("error") or job["status"])[:300])
            time.sleep(.1)
        raise BridgeError("生成导入已受理，但等待超时；结果未知，请检查 DAW，不要重复提交。")

    def undo(self, project_id, revision, request_id):
        return self._request({"request_id": request_id, "project_id": project_id,
            "expected_revision": revision, "command": "undo", "args": {}})

    def close(self):
        with self.lock:
            self.client.close()
            self.connected = False
