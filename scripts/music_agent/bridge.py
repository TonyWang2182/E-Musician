"""Serialized, revision-checked access to one owned DAW process."""
from __future__ import annotations
import copy
from pathlib import Path
import threading
import uuid
from agent_client import Client, ControlError

class BridgeError(RuntimeError):
    pass

def identity(context):
    return context.get("project_id"), context.get("revision")

def public_snapshot(raw):
    fields = ("project_id", "revision", "name", "dirty", "bpm", "numerator",
              "denominator", "duration_seconds", "position_seconds", "playing",
              "selected_track_id", "selected_clip_id", "can_undo", "can_redo",
              "recording", "recording_finalizing", "counting_in", "tracks", "selection_context")
    result = {k: copy.deepcopy(raw[k]) for k in fields if k in raw}
    # Engine snapshots have no source paths here; keep only musical metadata.
    for track in result.get("tracks", []):
        for key in list(track):
            if key not in {"id", "name", "kind", "gain_db", "pan", "muted", "solo",
                           "clips", "clip_count", "clips_truncated", "plugins"}:
                del track[key]
    result["clip_notes"] = {}
    result["context_limits"] = "Clip preview: max 64/track, 256 total. Notes read on demand, max 2000/clip."
    return result

class DawBridge:
    def __init__(self, executable: Path | None = None, *, offline=False, client=None, embedded=False):
        self.lock = threading.RLock()
        self.connected = True
        self._capabilities = None
        self.embedded = bool(embedded or getattr(client, "embedded", False))
        if self.embedded and client is None:
            raise ValueError("Embedded mode requires a host-owned transport.")
        self.client = client or Client(executable, timeout=20, show=not offline, offline_test=offline)

    def _request(self, envelope):
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
            if result.get("status") != "completed":
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

    def snapshot(self):
        return public_snapshot(self._request({"command": "get_snapshot"})["result"])

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

    def apply(self, plan):
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
        return self._request(envelope)

    def undo(self, project_id, revision, request_id):
        return self._request({"request_id": request_id, "project_id": project_id,
            "expected_revision": revision, "command": "undo", "args": {}})

    def close(self):
        with self.lock:
            self.client.close()
            self.connected = False
