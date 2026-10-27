"""Measure real JSONL editing with 100000 notes, without playback or plugins.

Run through scripts/dev.py Recorder. Reported latency is pipe roundtrip, not
physical GUI input-to-paint latency. Artifacts stay in a fresh build directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client
from AgentJobsSmoke import METER, TEMPO, require, smf


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--budget-ms", type=float, default=50)
    args = parser.parse_args()
    require(args.exe.is_file() and args.timeout > 0 and args.budget_ms > 0, "invalid probe arguments")
    directory = ROOT / "build/midi-control-performance" / str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "many-notes.mid"
    events = []
    for i in range(100000):
        pitch = 48 + i % 24
        events.extend([(i * 4, bytes([0x90, pitch, 80])), (i * 4 + 2, bytes([0x80, pitch, 0]))])
    smf(source, [[TEMPO, METER, *events]], 0)
    del events
    report = {"status": "running", "notes": 100000, "budget_ms": args.budget_ms,
              "scope": "JSONL pipe roundtrip, stopped transport, 100000-note clip, no plugins; not GUI render latency",
              "executable_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        with Client(args.exe, args.timeout) as client:
            started = time.perf_counter()
            client.request({"command": "import_midi", "args": {"path": str(source)}})
            report["import_seconds"] = time.perf_counter() - started
            state = client.state()
            track_id = state["tracks"][0]["id"]
            clip_id = state["tracks"][0]["clips"][0]["id"]
            notes = client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip_id, "limit": 1}}))
            require(notes["total"] == 100000, "import lost notes")
            note = notes["notes"][0]
            original_velocity = note["velocity"]

            def edit(command: str, args: dict) -> float:
                state = client.state()
                started = time.perf_counter()
                response = client.raw({"command": command, "args": args, "request_id": str(uuid.uuid4()),
                                       "project_id": state["project_id"], "expected_revision": state["revision"]})
                elapsed = (time.perf_counter() - started) * 1000
                require(response.get("status") == "completed", str(response))
                return elapsed

            pan = [edit("set_track_pan", {"track_id": track_id, "pan": 0.2 if i % 2 else -0.2}) for i in range(20)]
            require(abs(client.state()["tracks"][0]["pan"] - 0.2) < 1e-5, "pan did not apply")
            snapshot = []
            for _ in range(20):
                started = time.perf_counter()
                state = client.state()
                snapshot.append((time.perf_counter() - started) * 1000)
            single_note = []
            for i in range(10):
                note["velocity"] = 65 if i % 2 else 66
                single_note.append(edit("edit_notes", {"clip_id": clip_id, "upsert": [note]}))
            read = lambda: client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip_id, "limit": 1}}))
            require(read()["notes"][0]["velocity"] == 65, "single-note edit did not apply")
            undo_ms = edit("undo", {})
            require(read()["notes"][0]["velocity"] == 66, "single-note Undo failed")
            redo_ms = edit("redo", {})
            final = read()
            require(final["total"] == 100000 and final["notes"][0]["velocity"] == 65, "single-note Redo lost notes")
            require(not client.state()["playing"], "probe unexpectedly played audio")
            report.update({"pan_roundtrip_ms": pan, "snapshot_roundtrip_ms": snapshot,
                           "single_note_roundtrip_ms": single_note, "undo_ms": undo_ms, "redo_ms": redo_ms,
                           "original_velocity": original_velocity, "note_edit_undo_redo": "passed"})
            report["p95_ms"] = {"pan": percentile(pan, .95), "snapshot": percentile(snapshot, .95),
                                 "single_note": percentile(single_note, .95)}
            require(all(value < args.budget_ms for value in report["p95_ms"].values()),
                    f"roundtrip P95 exceeds {args.budget_ms} ms: {report['p95_ms']}")
            report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        print(f"Report: {directory / 'report.json'}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
