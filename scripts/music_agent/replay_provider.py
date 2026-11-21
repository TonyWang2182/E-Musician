"""Finite local scene planner for the separately built filming executable.

This is deliberately not an LLM or inference provider. It translates only the
manifest's prepared instructions to existing native candidate commands. The
normal runtime still checks selection, project revisions, review and undo.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import uuid
from showcase.package import Package

CONTEXT_MARKER = "\n\n当前工程数据（只读）：\n"


def install_loopback_guard():
    """Defense in depth: this helper may only connect to its local native host."""
    def guard(event, args):
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
                raise PermissionError("Only local workspace connections are permitted.")
        elif event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise PermissionError("External name lookup is disabled in this workspace.")
    sys.addaudithook(guard)


class ReplayProvider:
    is_replay = True
    provider_id = "retained-results"
    model = "music-workspace"
    base_url = ""
    timeout = 1
    label = "Music assistant"
    capabilities = {"text": True, "tools": True, "streaming": False,
                    "image_input": False, "audio_input": False, "audio_output": False}

    def __init__(self, root):
        self.package = Package(root)
        self.audit_path = self.package.root / "runtime" / "agent" / "audit.jsonl"

    def capability_groups(self, project_id):
        labels={"yue":"YuE2","ace":"ACE-Step","separate":"Separate","chords":"Chords","beats":"Beat & Warp","transcribe":"Piano to MIDI"}
        return [{"id":"prepared-"+s["id"],"label":labels.get(s["id"],s["kind"]),
                 "status":"available","status_label":"Ready","enabled":True,
                 "example":s["prompts"][0],"detail":"Review the result before applying changes."}
                for s in self.package.scenes if s["project_id"]==project_id]

    def _reply(self, *, text=None, tool=None, arguments=None, tools=()):
        message = {"role": "assistant", "content": text}
        if tool:
            allowed = {t.get("function", {}).get("name") for t in tools}
            if tool not in allowed:
                raise ValueError("This workspace does not expose the required action.")
            message["tool_calls"] = [{"id": "local_" + uuid.uuid4().hex, "type": "function",
                "function": {"name": tool, "arguments": json.dumps(arguments, allow_nan=False)}}]
        return {"message": message, "usage": {}, "model": self.model}

    def complete(self, messages, tools):
        latest = next((i for i in range(len(messages)-1, -1, -1)
            if messages[i].get("role") == "user" and CONTEXT_MARKER in (messages[i].get("content") or "")), None)
        if latest is None: raise ValueError("Current project context is missing.")
        prompt, raw_context = messages[latest]["content"].rsplit(CONTEXT_MARKER, 1)
        context = json.loads(raw_context)
        scene = self.package.instruction(prompt, context.get("project_id"))
        returned = [m for m in messages[latest+1:] if m.get("role") == "tool"]
        if not returned:
            if scene["kind"] == "generate":
                expected = scene["parameters"]
                if abs(float(context.get("bpm", 0)) - float(expected["bpm"])) > 1e-7:
                    raise ValueError("Set the project to the tempo in this instruction first.")
                arguments = {k: expected[k] for k in ("prompt", "lyrics", "duration_seconds", "seed") if k in expected}
                arguments.update(model_id=scene["model_id"], execution="cloud", timeline_start_seconds=0)
                return self._reply(tool="start_generation", arguments=arguments, tools=tools)
            cid = context.get("selection_context", {}).get("active_clip_id")
            clips = [c for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("id") == cid and c.get("kind") == "audio"]
            if len(clips) != 1: raise ValueError("Select the matching audio clip before continuing.")
            clip = clips[0]
            offset = float(scene["source"]["offset_seconds"]) - float(clip.get("playback_source_offset", clip.get("source_offset", 0)))
            if offset < -1e-7: raise ValueError("Select the original audio range before continuing.")
            return self._reply(tool="start_audio_analysis", tools=tools, arguments={
                "kind": scene["kind"], "clip_id": cid, "model_id": scene["model_id"],
                "execution": "local" if scene["kind"] == "beats" else "cloud",
                "start_seconds": max(0, offset), "duration_seconds": scene["source"]["duration_seconds"],
                "parameters": scene.get("parameters", {})})
        if len(returned) != 1: raise ValueError("The prepared action has already been requested.")
        answer = json.loads(returned[0]["content"])
        candidate = answer.get("candidate")
        if not isinstance(candidate, dict) or not candidate.get("result_id"):
            raise ValueError("Unable to prepare this result. Check the selected clip and local package.")
        if candidate.get("kind") != scene["kind"]:
            raise ValueError("The candidate belongs to a different operation.")
        if scene.get("application") == "manual":
            return self._reply(text="Chord analysis is ready. Open Analysis, then add the chord track.")
        arguments = {"result_id": candidate["result_id"]}
        if scene["kind"] == "generate":
            arguments["summary"] = "Ready to preview. Apply changes to add this take to a new track."
            tool = "propose_generation_import"
        elif scene.get("application") == "warp":
            arguments.update(mode="audio_to_project", summary="Align this clip to the project tempo with pitch-preserving Warp. The linked chord track follows the audio.")
            tool = "propose_beat_application"
        else:
            arguments["summary"] = ("Four stems are ready. Apply changes to add vocals, drums, bass, and other. The original track stays in place."
                if scene["kind"] == "separate" else "Piano notes are ready. Apply changes to add an editable MIDI track.")
            tool = "propose_analysis_import"
        return self._reply(tool=tool, arguments=arguments, tools=tools)


class LocalLaunchRecorder:
    """Runtime diagnostics belong to the isolated package, not repo build logs."""
    def __init__(self, root):
        self.root = Path(root) / "runtime" / "agent" / "launches"

    def new_record(self, command, label):
        self.root.mkdir(parents=True, exist_ok=True)
        identity = uuid.uuid4().hex
        return {"operation": "local_sidebar_launch", "mode": "retained_result_replay"}, self.root / (identity+".json"), self.root / (identity+".log")

    def finish(self, record, path, log_path, started):
        path.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
