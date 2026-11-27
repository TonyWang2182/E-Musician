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
              "recording", "recording_finalizing", "counting_in", "tracks", "master_plugins", "selection_context",
              "master_gain_db", "master_peak_left_db", "master_peak_right_db", "master_overloaded", "master_automation")
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
    def summaries(values, fields):
        return [{k: copy.deepcopy(v) for k, v in item.items() if k in fields}
                for item in values if isinstance(item, dict)] if isinstance(values, list) else []
    automation_fields = {"id", "target", "plugin_id", "parameter_id", "enabled", "point_count"}
    if "master_automation" in result:
        result["master_automation"] = summaries(result["master_automation"], automation_fields)
    for track in result.get("tracks", []):
        for key in list(track):
            if key not in {"id", "name", "kind", "gain_db", "pan", "muted", "solo", "colour",
                           "clips", "clip_count", "clips_truncated", "plugins", "output_target_id", "sends", "automation",
                           "peak_left_db", "peak_right_db", "overloaded"}:
                del track[key]
        track["plugins"] = public_plugins(track.get("plugins",[]))
        if "sends" in track:
            track["sends"] = summaries(track["sends"], {"id", "target_track_id", "gain_db", "pre_fader", "enabled"})
        if "automation" in track:
            track["automation"] = summaries(track["automation"], automation_fields)
    result["meter_observation"] = {"kind": "instantaneous_peak_snapshot", "freshness_verified": False,
        "whole_song_loudness_available": False,
        "warning": "Peak displays can decay or be stale, especially while stopped. Not RMS/LUFS or a listening assessment."}
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
                raise BridgeError("DAW disconnected. Save and close the controlled window before restarting the assistant.")
            request = dict(envelope)
            request.setdefault("request_id", str(uuid.uuid4()))
            try:
                result = self.client.raw(request)
            except (OSError, EOFError, ControlError, AssertionError) as exc:
                # A timeout may still have committed. Never issue another request
                # on an ambiguous stream, nor blindly retry a write.
                self.connected = False
                raise BridgeError("The DAW did not respond in time. The outcome is unknown; further commands stopped. Check the project in the DAW.") from exc
            if not isinstance(result, dict) or result.get("request_id") != request["request_id"]:
                self.connected = False
                raise BridgeError("DAW responses arrived out of sequence. Further commands stopped.")
            if result.get("status") != "completed" and not (allow_accepted and result.get("status") == "accepted"):
                status = result.get("status", "invalid")
                if status in ("conflict", "wrong_project"):
                    raise BridgeError("The project changed. The old plan was not applied; send the request again.")
                if status == "selection_conflict":
                    raise BridgeError("The music selection changed. The old plan was not applied; create a new plan.")
                raise BridgeError("The DAW rejected the action: " + str(result.get("error") or status)[:500])
            return result

    def capabilities(self):
        with self.lock:
            if self._capabilities is None:
                value = self._request({"command":"get_capabilities"})["result"]
                if not isinstance(value,dict):
                    raise BridgeError("Invalid DAW capability response.")
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
        from .compute import require_route
        try: require_route(self.generation_capabilities(refresh=True), "generate", request)
        except ValueError as exc: raise BridgeError(str(exc)) from exc
        envelope = {"command": "start_generation", "project_id": context["project_id"], "expected_revision": context["revision"], "args": request}
        if scope.get("mode") != "project": envelope["expected_selection_revision"] = scope["selection_revision"]
        reply = self._request(envelope, allow_accepted=True)
        return {"job_id": identifier((reply.get("result") or {}).get("job_id"))}

    def generation_job(self, job_id):
        from .generation import safe_job
        from .analysis import identifier
        value = safe_job(self._request({"command": "get_generation_job", "args": {"job_id": identifier(job_id)}})["result"])
        if value.get("job_id") != job_id:
            raise BridgeError("Generation job identity mismatch.")
        return value

    def generation_result(self, result_id):
        from .generation import safe_result
        from .analysis import identifier
        value = safe_result(self._request({"command": "get_generation_result", "args": {"result_id": identifier(result_id)}})["result"])
        if value["result_id"] != result_id: raise BridgeError("Generated candidate identity mismatch.")
        return value

    def cancel_generation(self, job_id):
        from .analysis import identifier
        raw = self._request({"command": "get_job", "args": {"job_id": identifier(job_id)}})["result"]
        if not isinstance(raw, dict) or raw.get("kind") != "generation.generate" or raw.get("status") in {"completed", "ready", "failed", "cancelled", "stale", "applied"}:
            raise BridgeError("The task has ended or is an import job. No cancellation was sent.")
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
            raise BridgeError("Generation preview job identity mismatch.")
        state = job.get("status")
        if state in {"queued", "running"}: return {"status": "preparing", "job_id": job_id}
        if state in {"failed", "cancelled", "conflict"}:
            detail = safe_text(job.get("error"), 400)
            status = "unavailable" if "No audio output is active" in detail else "stopped" if state == "cancelled" else "failed"
            return {"status": status, "detail": detail, "job_id": job_id}
        if state != "completed": raise BridgeError("GeneratePreview status unknown。")
        stream = self._request({"command": "get_analysis_preview_status"})["result"]
        if not isinstance(stream, dict) or stream.get("status") not in {"loading", "playing", "completed", "stopped", "failed", "unavailable"}:
            raise BridgeError("Invalid generation preview stream state.")
        return {"status": stream["status"], "detail": safe_text(stream.get("detail"), 400), "job_id": job_id}

    def start_analysis(self, context, scope, args):
        from .analysis import authorize_start, identifier
        with self.lock:
            request = authorize_start(context, scope, args)
            from .compute import require_route
            try: require_route(self.analysis_capabilities(refresh=True), request["kind"], request)
            except ValueError as exc: raise BridgeError(str(exc)) from exc
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
            raise BridgeError("Analysis job identity mismatch.")
        return value

    def analysis_result(self, result_id, offset=0, limit=24, component=None):
        from .analysis import identifier, safe_result
        if type(offset) is not int or not 0 <= offset <= 100000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid analysis pagination range.")
        args = {"result_id": identifier(result_id), "offset": offset, "limit": limit}
        if component is not None:
            from .analysis import COMPONENTS
            if not isinstance(component, str) or component not in COMPONENTS: raise ValueError("Invalid analysis result type.")
            args["component"] = component
        value = safe_result(self._request({"command": "get_analysis_result", "args": args})["result"])
        if value["result_id"] != result_id or value.get("offset", offset) != offset or len(value["items"]) != min(limit, max(0, value["total"]-offset)):
            raise BridgeError("Analysis pagination identity or count mismatch.")
        return value

    def cancel_analysis(self, job_id):
        from .analysis import identifier
        # The generic job kind distinguishes an import even during the tiny
        # queued/running interval before its worker publishes "applying".
        raw = self._request({"command": "get_job", "args": {"job_id": identifier(job_id)}})["result"]
        if not isinstance(raw, dict) or raw.get("kind") not in {"analysis.separate", "analysis.transcribe", "analysis.chords", "analysis.beats", "analysis.score"} or raw.get("status") not in {"queued", "preparing", "uploading", "loading", "running", "postprocessing", "downloading", "validating", "cancelling"}:
            raise BridgeError("The task has ended or is an import job. No cancellation was sent.")
        return self._request({"command": "cancel_analysis_job", "args": {"job_id": identifier(job_id)}})

    def chord_page(self, context, clip_id="", offset=0, limit=100):
        from .analysis import identifier, safe_text, number
        if type(offset) is not int or not 0 <= offset <= 10000 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid chord pagination range.")
        with self.lock:
            if not {"get_chord_regions", "edit_chord_region"} <= set(self.capabilities().get("commands", [])):
                raise BridgeError("The current host does not provide chord read/write APIs.")
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("The project changed while reading chords.")
            args = {"offset": offset, "limit": limit}
            if clip_id: args["clip_id"] = identifier(clip_id)
            raw = self._request({"command": "get_chord_regions", "args": args})["result"]
            total, items = raw.get("total"), raw.get("items")
            if type(total) is not int or not 0 <= total <= 10000 or raw.get("offset") != offset or not isinstance(items, list) or len(items) != min(limit, max(0, total-offset)):
                raise BridgeError("Chord pagination count or identity mismatch.")
            safe = []
            for item in items:
                if not isinstance(item, dict): raise BridgeError("Invalid chord object.")
                start, end = number(item.get("start_seconds"), 0, 172800), number(item.get("end_seconds"), 0, 172800)
                if start >= end or type(item.get("uncertain")) is not bool: raise BridgeError("Invalid chord object time.")
                safe.append({"id": identifier(item.get("id")), "analysis_id": identifier(item.get("analysis_id")),
                    "label": safe_text(item.get("label"), 128), "start_seconds": start, "end_seconds": end,
                    "score": None if item.get("score") is None else number(item["score"], 0, 1), "uncertain": item["uncertain"]})
            if len({i["id"] for i in safe}) != len(safe) or identity(self.snapshot()) != identity(context):
                raise BridgeError("Chord reading is incomplete or the project changed.")
            return {"items": safe, "total": total, "offset": offset, "score_kind": "uncalibrated_similarity"}

    def find_chord(self, context, region_id, clip_id=""):
        from .analysis import identifier
        identifier(region_id)
        offset, total = 0, None
        while total is None or offset < total:
            page = self.chord_page(context, clip_id, offset, 100)
            if total is not None and page["total"] != total:
                raise BridgeError("The total chord count changed during pagination.")
            total = page["total"]
            for item in page["items"]:
                if item["id"] == region_id: return item
            offset += 100
        raise BridgeError("The chord does not belong to the specified source clip or was deleted.")

    def resolve_clips(self, context, clip_ids):
        """Load exact requested IDs beyond the bounded preview, preserving limits.

        Pages are inspected locally; unrelated hidden clips never enter model
        context. The original clip_count/truncation stays truthful.
        """
        if not isinstance(clip_ids, (list, tuple, set)) or len(clip_ids) > 4096 or any(not isinstance(i, str) or not i for i in clip_ids):
            raise BridgeError("Invalid clip range.")
        with self.lock:
            tracks = context.get("tracks", [])
            existing = {c["id"] for t in tracks for c in t.get("clips", [])}
            missing = set(clip_ids) - existing
            if not missing:
                return
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("The project changed while reading clips.")
            selection = context.get("selection_context") or {}
            preferred = set(selection.get("track_ids", [])) | {selection.get("active_track_id")}
            candidates = sorted(tracks, key=lambda t: t["id"] not in preferred)
            additions = []
            for track in candidates:
                total = track.get("clip_count", len(track.get("clips", [])))
                if type(total) is not int or not 0 <= total <= 4096:
                    raise BridgeError("Invalid track clip count.")
                if total <= len(track.get("clips", [])):
                    continue
                page_ids = set()
                for offset in range(0, total, 256):
                    page = self._request({"command": "get_track_clips", "args": {
                        "track_id": track["id"], "offset": offset, "limit": 256}})["result"]
                    values = page.get("clips")
                    if page.get("total") != total or page.get("offset") != offset or not isinstance(values, list) or len(values) != min(256, total-offset):
                        raise BridgeError("Clip pagination changed or reading is incomplete.")
                    for clip in values:
                        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or clip["id"] in page_ids:
                            raise BridgeError("Clip pagination contains duplicate or invalid identities.")
                        page_ids.add(clip["id"])
                        if clip["id"] in missing:
                            additions.append((track, copy.deepcopy(clip)))
                            missing.remove(clip["id"])
                    if not missing:
                        break
                if not missing:
                    break
            if missing or identity(self.snapshot()) != identity(context):
                raise BridgeError("The selected clip was deleted or the project changed while reading.")
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
                raise BridgeError("The project changed while reading. Send the request again.")
            clips = [c for t in context.get("tracks", []) for c in t.get("clips", [])]
            clip = next((c for c in clips if c["id"] == clip_id), None)
            if not clip or clip.get("kind") != "midi":
                raise BridgeError("Select a MIDI clip from the current snapshot.")
            total = clip.get("note_count", 0)
            if type(total) is not int or total > 2000 or total < 0:
                raise BridgeError("A request supports at most 2000 notes. Split the clip in the DAW first.")
            notes = []
            for offset in range(0, max(1, total), 1000):
                page = self._request({"command": "get_clip_notes",
                    "args": {"clip_id": clip_id, "offset": offset, "limit": 1000}})["result"]
                if page.get("total") != total or page.get("offset") != offset:
                    raise BridgeError("Note pagination changed. The old read was discarded.")
                notes.extend(page.get("notes", []))
            if len(notes) != total or identity(self.snapshot()) != identity(context):
                raise BridgeError("Note reading is incomplete or the project changed. Retry.")
            context["clip_notes"][clip_id] = notes
            return notes

    def read_native_effect(self, context, track_id, device_id):
        from .plans import validate_effect_state, PlanError, EFFECT_NAMES
        with self.lock:
            self.require_native_effect_catalog()
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("The project changed while reading effects.")
            track = next((t for t in context.get("tracks", []) if t.get("id") == track_id), None)
            plugins = context.get("master_plugins",[]) if track_id == "master" else (track or {}).get("plugins", [])
            plugin = next((p for p in plugins if p.get("id") == device_id), None)
            if not plugin or plugin.get("format") != "E-musician" or plugin.get("is_instrument") is not False or plugin.get("name") not in EFFECT_NAMES.values():
                raise BridgeError("The effect is missing, unsupported or does not belong to the specified track.")
            result = self._request({"command":"get_native_effect", "args":{"track_id":track_id,"device_id":device_id}}).get("result")
            if not isinstance(result,dict) or result.get("device_id") != device_id:
                raise BridgeError("Effect readback identity mismatch.")
            try:
                state = validate_effect_state(result.get("state"))
            except PlanError as exc:
                raise BridgeError("Invalid effect state.") from exc
            if plugin["name"] != EFFECT_NAMES.get(state["type"]) or identity(self.snapshot()) != identity(context):
                raise BridgeError("The effect type or project revision changed while reading.")
            context.setdefault("native_effects", {})[device_id] = state
            return copy.deepcopy(state)

    def imported_controller_counts(self, context, clip_ids):
        """Verify CC/program events locally without sending their arrays to LLM."""
        from .analysis import identifier, number
        if not isinstance(clip_ids, list) or len(clip_ids) > 64 or len(set(clip_ids)) != len(clip_ids):
            raise BridgeError("Invalid imported MIDI clip list.")
        known = {c["id"] for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("kind") == "midi"}
        if not set(clip_ids) <= known:
            raise BridgeError("The imported MIDI controller target is absent from the actual readback.")
        counts = {"controller_count": 0, "program_change_count": 0, "other_count": 0}
        with self.lock:
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("The project changed before verifying MIDI controllers.")
            for clip_id in clip_ids:
                identifier(clip_id)
                total, offset, seen = None, 0, set()
                while total is None or offset < total:
                    raw = self._request({"command": "get_clip_controllers", "args": {"clip_id": clip_id, "offset": offset, "limit": 1000}})["result"]
                    count, events = raw.get("total"), raw.get("events")
                    if (type(count) is not int or not 0 <= count <= 100000 or (total is not None and count != total)
                            or raw.get("offset") != offset or not isinstance(events, list) or len(events) != min(1000, count-offset)):
                        raise BridgeError("Imported MIDI controller pagination is incomplete.")
                    total = count
                    for event in events:
                        if not isinstance(event, dict): raise BridgeError("Invalid MIDI controller event.")
                        eid = identifier(event.get("id"))
                        if eid in seen: raise BridgeError("Duplicate MIDI controller event identity.")
                        seen.add(eid)
                        kind, value = event.get("type"), event.get("value")
                        number(event.get("beats"), 0, 1000000)
                        if type(kind) is not int or type(value) is not int or not 0 <= value <= 16383:
                            raise BridgeError("Invalid MIDI controller event type or value.")
                        field = "controller_count" if 0 <= kind <= 127 else "program_change_count" if kind == 4097 else "other_count"
                        counts[field] += 1
                    offset += len(events)
                    if sum(counts.values()) > 100000:
                        raise BridgeError("MIDI controllers exceed the project budget.")
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("The project changed while verifying MIDI controllers.")
        return counts

    def read_native_instrument(self, context, track_id):
        from .plans import PlanError, _number
        with self.lock:
            self.require_native_instrument_catalog()
            if identity(self.snapshot()) != identity(context): raise BridgeError("The project changed while reading the sampler.")
            if not any(t.get("id")==track_id for t in context.get("tracks",[])): raise BridgeError("The sampler track does not exist.")
            raw=self._request({"command":"get_native_instrument","args":{"track_id":track_id}}).get("result")
            if not isinstance(raw,dict) or raw.get("type") not in {"sampler","drum_rack"} or raw.get("load_status") != "ready":
                raise BridgeError("The sampler or Drum Rack is not ready.")
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
            except (PlanError,ValueError,TypeError) as exc: raise BridgeError("Invalid sampler state.") from exc
            if identity(self.snapshot()) != identity(context): raise BridgeError("The project changed while reading the sampler.")
            context.setdefault("native_instruments",{})[track_id]=state
            return copy.deepcopy(state)

    def audio_warp(self, context, clip_ids):
        from .tempo import safe_warp
        with self.lock:
            if not {"get_audio_warp","set_audio_warp"}<=set(self.capabilities().get("commands",[])):
                raise BridgeError("The current host does not provide the audio Warp API.")
            if identity(self.snapshot())!=identity(context):raise BridgeError("The project changed while reading Warp.")
            value=safe_warp(self._request({"command":"get_audio_warp","args":{"clip_ids":clip_ids}})["result"],clip_ids)
            if identity(self.snapshot())!=identity(context):raise BridgeError("The project changed while reading Warp.")
            return value

    def apply(self, plan):
        if plan.get("execution_kind") == "generation_import":
            from .generation import compile_import
            candidate = self.generation_result(plan["generation"]["result_id"])
            if candidate.get("result_hash") != plan["generation"].get("result_hash"):
                raise BridgeError("The generated candidate changed after preview. The old plan was not submitted.")
            compile_import(candidate, self.snapshot(), plan["scope"], plan["summary"])
            envelope = {"request_id": plan["id"], "command": "accept_generation_result",
                        "project_id": plan["project_id"], "expected_revision": plan["revision"],
                        "args": {"result_id": candidate["result_id"], "result_hash": candidate["result_hash"]}}
            if plan["scope"].get("mode") != "project": envelope["expected_selection_revision"] = plan["scope"]["selection_revision"]
            reply = self._request(envelope, allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"), str):
                raise BridgeError("Invalid generation import receipt. The outcome is unknown. Check the DAW and do not submit again.")
            return reply
        if plan.get("execution_kind") in {"audio_warp","beat_apply"}:
            from .tempo import compile_warp, compile_beats
            current=self.snapshot();args=plan["commands"][0]["args"]
            ids=[item["clip_id"] for item in plan["warp_before"]]
            states=self.audio_warp(current,ids)
            if states!=plan["warp_before"]:raise BridgeError("Warp changed after preview. The old plan was not submitted.")
            if plan["execution_kind"]=="beat_apply":
                candidate=self.analysis_result(plan["analysis"]["result_id"])
                if candidate.get("result_hash")!=plan["analysis"].get("result_hash"):raise BridgeError("The beat candidate changed.")
                compile_beats({**args,"summary":plan["summary"]},candidate,current,plan["scope"],states)
            else:
                compile_warp({**{k:v for k,v in args.items() if k!="mode"},"summary":plan["summary"]},current,plan["scope"],states)
            command=plan["commands"][0]["command"]
            if command not in self.capabilities().get("commands",[]):raise BridgeError("The host does not support the required Warp command.")
            envelope={"request_id":plan["id"],"project_id":plan["project_id"],"expected_revision":plan["revision"],"command":command,"args":args}
            if plan["scope"]["mode"]!="project":envelope["expected_selection_revision"]=plan["scope"]["selection_revision"]
            reply=self._request(envelope,allow_accepted=True)
            if reply.get("status")!="accepted" or not isinstance((reply.get("result") or {}).get("job_id"),str):
                raise BridgeError("Invalid Warp receipt. The outcome is unknown. Check the DAW and do not submit again.")
            return reply
        if plan.get("execution_kind") == "chord_edit":
            from .analysis import compile_chord_edit
            current = self.snapshot()
            region = self.find_chord(current, plan["chord_before"]["id"], plan.get("chord_clip_id", ""))
            if region != plan["chord_before"]:
                raise BridgeError("The chord changed after preview. The old plan was not submitted.")
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
                raise BridgeError("The candidate changed or was already imported. It was not submitted again.")
            current = self.snapshot()
            authorize_result(current, plan["scope"], result)
            envelope = {"request_id": plan["id"], "command": "accept_analysis_result",
                "project_id": plan["project_id"], "expected_revision": plan["revision"],
                "args": {"result_id": result_id}}
            if plan["scope"].get("mode") != "project":
                envelope["expected_selection_revision"] = plan["scope"]["selection_revision"]
            reply = self._request(envelope, allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"), str):
                raise BridgeError("Invalid analysis import receipt. The outcome is unknown. Check the DAW and do not submit again.")
            return reply
        if any(c.get("command") in {"add_native_effect", "set_native_effect"} for c in plan.get("commands",[])):
            self.require_native_effect_catalog()
        if (plan.get("scope") or {}).get("mode") != "project" and any(
            c.get("command") in {"add_native_effect","set_native_effect"} and c.get("args",{}).get("track_id") == "master"
            for c in plan.get("commands",[])):
            raise BridgeError("Master effects can only be modified in project scope.")
        if plan.get("execution_kind") == "native_async":
            self.require_native_instrument_catalog()
            commands=plan.get("commands",[])
            if (plan.get("scope") or {}).get("mode") != "project" or len(commands)!=1 or commands[0].get("command") not in {"set_native_pad","set_native_sampler"}:
                raise BridgeError("An asynchronous sampler plan must contain one action in project scope.")
            envelope={"request_id":plan["id"],"project_id":plan["project_id"],"expected_revision":plan["revision"],
                      "command":commands[0]["command"],"args":commands[0]["args"]}
            reply=self._request(envelope,allow_accepted=True)
            if reply.get("status") != "accepted" or not isinstance((reply.get("result") or {}).get("job_id"),str):
                raise BridgeError("Invalid sampler action receipt. The outcome is unknown. Check the DAW and do not submit again.")
            return reply
        if any("as" in c for c in plan["commands"]):
            version = self.capabilities().get("batch_result_refs_version")
            if type(version) is not int or version != 1:
                raise BridgeError("The DAW does not declare support for dependent actions. No changes were sent.")
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
            if not isinstance(job,dict) or job.get("id")!=job_id:raise BridgeError("Background edit job identity mismatch.")
            if job.get("status")=="completed":
                if not isinstance(job.get("result"),dict):raise BridgeError("The background edit receipt is incomplete. Check the DAW.")
                return job["result"]
            if job.get("status") in {"failed","conflict","cancelled","stale"}:
                raise NativeJobFailed("Background edits were not applied: "+str(job.get("error") or job["status"])[:300])
            time.sleep(.05)
        raise BridgeError("Timed out waiting for background edits. The outcome is unknown. Check the DAW and do not submit again.")

    def wait_native_job(self, job_id, timeout=30.0):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            job=self._request({"command":"get_job","args":{"job_id":job_id}}).get("result")
            if not isinstance(job,dict) or job.get("id")!=job_id: raise BridgeError("Invalid background job receipt. The outcome is unknown. Check the DAW.")
            if job.get("status")=="completed": return
            if job.get("status") in {"failed","conflict","cancelled"}:
                raise NativeJobFailed("The sampler task was not applied: "+str(job.get("error") or job["status"])[:300])
            time.sleep(0.05)
        raise BridgeError("The background sampler task was submitted, but waiting timed out. The outcome is unknown. Check the DAW and do not submit again.")

    def wait_analysis_import(self, job_id, timeout=180.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.analysis_job(job_id)
            if job.get("status") == "applied":
                receipt = job.get("receipt")
                if not isinstance(receipt, dict) or receipt.get("applied") is not True:
                    raise BridgeError("Invalid analysis import completion receipt. Check the DAW and do not submit again.")
                return receipt
            if job.get("status") in {"failed", "stale", "cancelled"}:
                raise NativeJobFailed("The analysis candidate was not imported: " + str(job.get("error") or job["status"])[:300])
            time.sleep(0.1)
        raise BridgeError("Analysis import was accepted, but waiting timed out. The outcome is unknown. Check the DAW and do not submit again.")

    def wait_generation_import(self, job_id, timeout=180.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.generation_job(job_id)
            if job.get("status") == "applied":
                receipt = job.get("receipt")
                if not isinstance(receipt, dict) or receipt.get("applied") is not True:
                    raise BridgeError("Invalid generation import completion receipt. Check the DAW and do not submit again.")
                return receipt
            if job.get("status") in {"failed", "stale", "cancelled", "conflict"}:
                raise NativeJobFailed("Generated audio was not imported: " + str(job.get("error") or job["status"])[:300])
            time.sleep(.1)
        raise BridgeError("Generation import was accepted, but waiting timed out. The outcome is unknown. Check the DAW and do not submit again.")

    def undo(self, project_id, revision, request_id):
        return self._request({"request_id": request_id, "project_id": project_id,
            "expected_revision": revision, "command": "undo", "args": {}})

    def close(self):
        with self.lock:
            self.client.close()
            self.connected = False
