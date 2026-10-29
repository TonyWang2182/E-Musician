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
              "recording", "recording_finalizing", "counting_in", "tracks")
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
    def __init__(self, executable: Path | None = None, *, offline=False, client=None):
        self.lock = threading.RLock()
        self.connected = True
        self.client = client or Client(executable, timeout=20, show=not offline, offline_test=offline)

    def _request(self, envelope):
        with self.lock:
            if not self.connected:
                raise BridgeError("DAW 连接已断开；请先保存并关闭受控窗口，再重新启动助手。")
            request = dict(envelope)
            request.setdefault("request_id", str(uuid.uuid4()))
            try:
                result = self.client.raw(request)
            except (OSError, ControlError, AssertionError) as exc:
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
                raise BridgeError("DAW 拒绝操作：" + str(result.get("error") or status)[:500])
            return result

    def snapshot(self):
        return public_snapshot(self._request({"command": "get_snapshot"})["result"])

    def read_notes(self, context, clip_id):
        with self.lock:
            if identity(self.snapshot()) != identity(context):
                raise BridgeError("读取期间工程已变化，请重新提出要求。")
            clips = [c for t in context.get("tracks", []) for c in t.get("clips", [])]
            clip = next((c for c in clips if c["id"] == clip_id), None)
            if not clip or clip.get("kind") != "midi":
                raise BridgeError("请选择当前快照中的 MIDI 片段。")
            total = clip.get("note_count", 0)
            if not isinstance(total, int) or total > 2000 or total < 0:
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
        return self._request({"request_id": plan["id"], "project_id": plan["project_id"],
            "expected_revision": plan["revision"], "command": "batch",
            "args": {"commands": plan["commands"]}})

    def undo(self, project_id, revision, request_id):
        return self._request({"request_id": request_id, "project_id": project_id,
            "expected_revision": revision, "command": "undo", "args": {}})

    def close(self):
        with self.lock:
            self.client.close()
            self.connected = False
