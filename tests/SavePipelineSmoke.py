"""Real JSONL save regression, run only via scripts/dev.py / Recorder.

python tests/SavePipelineSmoke.py --exe PATH [--module C:/.../Instrument.vst3]
    [--audio PATH --audio PATH]

All supplied media are copied to a fresh build/save-pipeline-smoke/<UUID> first.
No playback or native plugin editor is opened. No user project is opened/saved.
Default fixtures are generated WAV; pass the two real MP3 inputs for that case.
Timings are measurements, not an assertion of GUI/native-editor responsiveness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, TERMINAL_JOBS  # noqa: E402
from AgentJobsSmoke import tone  # noqa: E402
from PluginHostSmoke import exact_cache_entries, page  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--module", type=Path)
    parser.add_argument("--audio", type=Path, action="append", default=[])
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    require(not args.audio or len(args.audio) == 2, "Supply exactly two --audio paths, or use owned WAV fixtures")
    workspace = ROOT / "build" / "save-pipeline-smoke" / str(uuid.uuid4())
    workspace.mkdir(parents=True, exist_ok=False)
    report: dict = {"status": "running", "workspace": str(workspace), "saves": [], "checks": [],
                    "limitations": ["No audio playback, native editor or GUI Save-click coverage.",
                                    "Default plugin program only; no forced slow native getState."]}

    def checked(label: str) -> None:
        report["checks"].append(label)
        print("PASS " + label, flush=True)

    try:
        sources = []
        supplied = []
        for index in range(2):
            if args.audio:
                original = args.audio[index].resolve(strict=True)
                require(original.suffix.lower() in (".wav", ".mp3"), "Media must be WAV or MP3")
                supplied.append((original, digest(original)))
                path = workspace / f"owned-source-{index}{original.suffix.lower()}"
                shutil.copy2(original, path)
            else:
                path = workspace / f"owned-source-{index}.wav"
                tone(path, 16)
            sources.append(path)
        report["audio"] = [{"path": str(path), "size": path.stat().st_size, "sha256": digest(path)} for path in sources]
        media_bytes = sum(path.stat().st_size for path in sources)
        with Client(args.exe.resolve(strict=True), args.timeout) as client:
            def command(name: str, arguments: dict | None = None, wait: bool = True) -> dict:
                for attempt in range(3):
                    snapshot = client.state()
                    response = client.raw({"command": name, "args": arguments or {}, "request_id": str(uuid.uuid4()),
                                           "project_id": snapshot["project_id"], "expected_revision": snapshot["revision"]})
                    if response.get("status") == "conflict" and attempt < 2:
                        time.sleep(0.05)
                        continue
                    require(response.get("status") in ("accepted", "completed"), json.dumps(response))
                    if wait and response["status"] == "accepted":
                        response["job_completion"] = client.wait_job(response["result"]["job_id"])
                    return response
                raise AssertionError("Project changed continuously before command acceptance")

            command("import_audio", {"paths": [str(path) for path in sources]})
            command("create_track", {"kind": "instrument", "name": "Save regression MIDI"})
            track_id = client.state()["tracks"][-1]["id"]
            command("create_midi_clip", {"track_id": track_id, "start_beats": 0, "length_beats": 8})
            clip_id = client.state()["tracks"][-1]["clips"][0]["id"]
            command("write_notes", {"clip_id": clip_id, "notes": [
                {"id": "save-note-a", "pitch": 48, "start_beats": 0, "length_beats": 1, "velocity": 64, "channel": 1},
                {"id": "save-note-b", "pitch": 60, "start_beats": 4, "length_beats": 2, "velocity": 72, "channel": 1}]})
            if args.module:
                module = args.module.resolve(strict=True)
                command("scan_plugins", {"include_default_paths": False, "paths": [], "modules": [str(module)]})
                ids = {item["id"] for item in exact_cache_entries(module) if item["available"]}
                entries = [item for item in page(client, "get_plugin_catalog", "plugins") if item["id"] in ids and item["is_instrument"]]
                require(bool(entries), "Explicit module has no available instrument descriptor")
                entries.sort(key=lambda entry: (entry["name"], entry["id"]))
                report["plugin"] = {"module": str(module), "descriptor": entries[0], "untested": entries[1:]}
                command("add_plugin", {"track_id": track_id, "catalog_id": entries[0]["id"]})
                time.sleep(0.3)
            checked("two audio tracks and one MIDI track created")

            def save(path: Path, during=None) -> dict:
                began = time.perf_counter()
                response = command("save_project", {"path": str(path)}, wait=False)
                ack = time.perf_counter()
                require(response["status"] == "accepted" and response["result"].get("job_id"), "Save must return an observable accepted job")
                if during:
                    during()
                job_id = response["result"]["job_id"]
                phases, heartbeat = [], []
                deadline = time.monotonic() + args.timeout
                while True:
                    heartbeat_start = time.perf_counter()
                    job = client.completed(client.raw({"command": "get_job", "args": {"job_id": job_id}}))
                    heartbeat.append((time.perf_counter() - heartbeat_start) * 1000)
                    if job.get("phase") not in phases:
                        phases.append(job.get("phase"))
                    if job["status"] in TERMINAL_JOBS:
                        break
                    require(time.monotonic() < deadline, "Save timed out while still nonterminal")
                    time.sleep(0.01)
                metric = {"path": str(path), "ack_ms_including_revision_read": (ack - began) * 1000,
                          "total_ms": (time.perf_counter() - began) * 1000, "max_poll_ms": max(heartbeat),
                          "observed_phases": phases, "job": job}
                report["saves"].append(metric)
                require(job["status"] == "completed", json.dumps(job))
                require(all(key in job for key in ("phase", "detail", "capture_ms", "max_plugin_capture_ms",
                                                   "bytes_written", "bytes_reused", "plugins_captured")), "Missing save diagnostics")
                require(job["plugins_captured"] == (1 if args.module else 0), "Unexpected plugin capture count")
                return job

            target = workspace / "Repeated.emproj"
            first_paths = None
            for attempt in range(4):
                job = save(target)
                state = client.state()
                require(not state["playing"] and not state["dirty"], "Completed quiescent save must clear dirty without playback")
                data = json.loads(target.read_text(encoding="utf-8-sig"))
                require(data["schema"] == 4, "Expected schema4 output")
                paths = [entry["source"] for entry in data["assets"]]
                if first_paths is None:
                    first_paths = paths
                    require(job["bytes_written"] >= media_bytes and job["bytes_reused"] == 0, "First save copy metrics invalid")
                else:
                    require(paths == first_paths, "Repeated Save duplicated unchanged media")
                    plugin_bytes = sum(slot["state_bytes"] for track in data["tracks"] for slot in track["plugins"])
                    plugin_bytes += sum(slot["state_bytes"] for slot in data["master_plugins"])
                    require(job["bytes_reused"] == media_bytes
                            and job["bytes_written"] == plugin_bytes + target.stat().st_size, "Repeated Save wrote unexpected audio bytes")
                time.sleep(0.1)
                require(not client.state()["dirty"], "Save produced a delayed dirty notification")
            checked("four consecutive saves: media reused, metrics available, dirty remains clear")

            before = client.state()
            audio_id = before["tracks"][0]["id"]
            save(target, during=lambda: command("set_track_gain", {"track_id": audio_id, "gain_db": -3}))
            require(client.state()["dirty"], "An edit after Save acceptance was incorrectly marked saved")
            data = json.loads(target.read_text(encoding="utf-8-sig"))
            require(next(track for track in data["tracks"] if track["id"] == audio_id)["gain_db"] == before["tracks"][0]["gain_db"],
                    "Save did not preserve its accepted revision")
            checked("ordinary edit after acceptance preserves earlier saved snapshot and current dirty state")
            save(target)
            require(not client.state()["dirty"], "Follow-up save must capture the later edit")
            copy = workspace / "Copy.emproj"
            job = save(copy)
            require(job["bytes_reused"] == 0 and job["bytes_written"] >= media_bytes, "Save As must copy into a new bundle")
            copy_data = json.loads(copy.read_text(encoding="utf-8-sig"))
            require(all(item["source"].startswith("Copy.assets/") for item in copy_data["assets"]), "Save As contains external bundle references")
            checked("Save As contains independent audio and all current edits")
            command("open_project", {"path": str(copy)})
            loaded = client.state()
            require(len(loaded["tracks"]) == 3 and not loaded["dirty"] and not loaded["playing"], "Saved project failed to reopen cleanly")
            if args.module:
                require(not loaded["tracks"][2]["plugins"][0]["missing"], "Reopened plugin state is missing")
            checked("schema4 project and optional native plugin reopen cleanly")
        for path, before_hash in supplied:
            require(digest(path) == before_hash, "A supplied media source changed during the test")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        (workspace / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(workspace / "report.json"), "error": report.get("error")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
