"""Local JSONL control client for a dedicated E-musician subprocess.

Examples:
  python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --request-json '{"command":"get_capabilities"}'
  python scripts/agent_client.py --exe PATH --script commands.json
  python scripts/agent_client.py --exe PATH --demo OUTPUT_DIRECTORY

A script is a JSON array or JSONL file containing request objects. Missing write
identity/revision fields are filled from a fresh snapshot; explicit fields are
preserved so optimistic concurrency and idempotency can be tested. The demo is
test data, not a musical generation feature. It writes an eight-bar MIDI clip,
exports its SMF, and undoes the note edit. It never starts audio playback.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

MAX_LINE_BYTES = 1024 * 1024
READ_COMMANDS = {
    "get_capabilities", "get_snapshot", "get_project_state", "get_jobs",
    "get_job", "get_events", "get_clip_notes", "get_track_clips", "get_plugin_catalog", "get_plugin_parameters",
    "get_recording_state", "get_recording_inputs", "get_audio_devices",
    "get_automation_targets", "get_automation_points", "get_clip_controllers", "get_save_diagnostics",
}
TERMINAL_JOBS = {"completed", "failed", "cancelled", "canceled", "conflict"}


class ControlError(RuntimeError):
    pass


class Client:
    def __init__(self, executable: Path, timeout: float = 120.0, show: bool = False):
        self.timeout = timeout
        self.responses: queue.Queue[object] = queue.Queue(maxsize=32)
        self.closed = threading.Event()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            [str(executable.resolve()), "--control-stdio", *(["--show"] if show else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.logger = threading.Thread(target=self._log, daemon=True)
        self.reader.start()
        self.logger.start()

    def _post(self, item: object) -> None:
        while not self.closed.is_set():
            try:
                self.responses.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while not self.closed.is_set():
                line = self.process.stdout.readline(MAX_LINE_BYTES + 2)
                if not line:
                    self._post(ControlError("Control process closed stdout."))
                    return
                if len(line.rstrip(b"\r\n")) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    raise ControlError("Invalid or oversized control response.")
                try:
                    response = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeError) as exc:
                    # Remain strict: skipping a plugin log could hide corrupted
                    # or reordered replies. Preserve only a bounded byte prefix.
                    raise ControlError("Invalid JSON control response: " + str(exc)[:200]
                                       + "; raw_prefix=" + repr(line[:160])) from exc
                if not isinstance(response, dict):
                    raise ControlError("A control response must be a JSON object.")
                self._post(response)
        except (ValueError, UnicodeError, OSError, ControlError) as exc:
            self._post(ControlError(str(exc)))

    def _log(self) -> None:
        assert self.process.stderr is not None
        try:
            while chunk := self.process.stderr.read(4096):
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
        except (OSError, ValueError):
            pass

    def raw(self, envelope: dict) -> dict:
        """Send exactly one envelope. Requests are intentionally serialized."""
        encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_LINE_BYTES:
            raise ControlError("Request exceeds the 1 MiB JSONL limit.")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(encoded + b"\n")
            self.process.stdin.flush()
            response = self.responses.get(timeout=self.timeout)
        except (OSError, queue.Empty) as exc:
            raise ControlError("Control request failed or timed out.") from exc
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response

    @staticmethod
    def completed(response: dict) -> dict:
        if response.get("status") != "completed":
            raise ControlError(json.dumps(response, ensure_ascii=False))
        return response.get("result") or {}

    def state(self) -> dict:
        return self.completed(self.raw({"command": "get_snapshot"}))

    def wait_job(self, job_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            job = self.completed(self.raw({"command": "get_job", "args": {"job_id": job_id}}))
            if job.get("status") in TERMINAL_JOBS:
                if job["status"] != "completed":
                    raise ControlError("Background task did not complete: " + json.dumps(job, ensure_ascii=False))
                return job
            time.sleep(0.05)
        raise ControlError(f"Timed out waiting for job {job_id}; accepted is not completed.")

    def request(self, envelope: dict, wait: bool = True) -> dict:
        if not isinstance(envelope, dict) or not isinstance(envelope.get("command"), str):
            raise ControlError("Each request must be an object with a command string.")
        request = dict(envelope)
        if request["command"] not in READ_COMMANDS:
            request.setdefault("request_id", str(uuid.uuid4()))
            if "project_id" not in request or "expected_revision" not in request:
                state = self.state()
                request.setdefault("project_id", state["project_id"])
                request.setdefault("expected_revision", state["revision"])
        response = self.raw(request)
        if response.get("status") not in {"completed", "accepted"}:
            raise ControlError(json.dumps(response, ensure_ascii=False))
        if wait and response["status"] == "accepted":
            job_id = (response.get("result") or {}).get("job_id")
            if not job_id:
                raise ControlError("Accepted response omitted job_id.")
            # Keep the original acknowledgement visible; attach actual completion.
            response = dict(response, job_completion=self.wait_job(job_id))
        return response

    def close(self) -> None:
        if self.closed.is_set():
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()  # Only the dedicated child owned by this client.
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        finally:
            self.closed.set()
            self.reader.join(timeout=1)
            self.logger.join(timeout=1)
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stderr:
                self.process.stderr.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def demo(client: Client, directory: Path) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    output = directory.resolve() / ("agent-eight-bars-" + uuid.uuid4().hex[:8] + ".mid")
    replies = [client.request({"command": "create_track", "args": {"kind": "instrument", "name": "Agent API test"}})]
    track = client.state()["tracks"][-1]
    replies.append(client.request({"command": "create_midi_clip", "args": {"track_id": track["id"], "start_beats": 0, "length_beats": 32}}))
    clip = client.state()["tracks"][-1]["clips"][0]
    notes = [{"id": f"demo-note-{i}", "pitch": 60 + i % 5, "start_beats": i,
              "length_beats": 0.5, "velocity": 70, "channel": 1} for i in range(32)]
    replies.append(client.request({"command": "write_notes", "args": {"clip_id": clip["id"], "notes": notes}}))
    replies.append(client.request({"command": "export_midi", "args": {"path": str(output)}}))
    replies.append(client.request({"command": "undo"}))
    page = client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip["id"]}}))
    if page.get("total") != 0 or not output.is_file() or output.stat().st_size < 14:
        raise ControlError("Demo export/one-step undo postcondition failed.")
    replies.append({"demo_status": "completed", "midi_file": str(output), "undo_note_count": 0})
    return replies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request-json")
    source.add_argument("--script", type=Path)
    source.add_argument("--demo", type=Path, metavar="OUTPUT_DIRECTORY")
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise ControlError("--timeout must be positive.")
        requests = []
        if args.request_json:
            requests = [json.loads(args.request_json)]
        elif args.script:
            data = args.script.read_text(encoding="utf-8-sig")
            requests = json.loads(data) if data.lstrip().startswith("[") else [json.loads(line) for line in data.splitlines() if line.strip()]
            if not isinstance(requests, list):
                raise ControlError("Script must contain a JSON array or JSONL requests.")
        with Client(args.exe, args.timeout) as client:
            responses = demo(client, args.demo) if args.demo else [client.request(request) for request in requests]
            for response in responses:
                print(json.dumps(response, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, ControlError, KeyboardInterrupt) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
