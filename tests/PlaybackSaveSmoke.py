"""Versioned real-device playback/save regression; run through dev.py / Recorder.

python tests/PlaybackSaveSmoke.py --exe PATH --module C:/.../Serum.vst3
    --audio PATH --audio PATH [--saves 6] [--max-xrun-delta 0]

Uses a dedicated Client process and fresh copies under build/playback-save-smoke.
Playback is quiet (-42 dB master, -18 dB tracks, velocity 36), with no input
monitoring or native editor. The current output device is used without changing
its configuration. No user project or source is modified. Transport/xrun checks
do not measure an acoustic dropout; reports retain that limitation explicitly.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import time
import uuid

from SavePipelineSmoke import (  # Reuse the same real Client and exact module helpers.
    Client, ROOT, TERMINAL_JOBS, digest, exact_cache_entries, page, require,
)
from PluginHostSmoke import normal_path

TEST_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--audio", type=Path, action="append", required=True)
    parser.add_argument("--saves", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-xrun-delta", type=int)
    args = parser.parse_args()
    require(len(args.audio) == 2, "Supply exactly two --audio sources")
    require(3 <= args.saves <= 50, "--saves must be 3..50")
    require(args.max_xrun_delta is None or args.max_xrun_delta >= 0, "xrun limit must be nonnegative")
    workspace = ROOT / "build" / "playback-save-smoke" / str(uuid.uuid4())
    workspace.mkdir(parents=True, exist_ok=False)
    report: dict = {"schema_version": 1, "test_version": TEST_VERSION, "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(), "workspace": str(workspace),
                    "machine": {"platform": platform.platform(), "processor": platform.processor()},
                    "checks": [], "saves": [], "playback_samples": [], "save_diagnostics": [],
                    "limitations": ["API transport and driver xrun counters do not prove acoustic continuity.",
                                    "No GUI Save click, native editor or physical input coverage.",
                                    "Default program of one exact scanned instrument descriptor only."]}
    supplied: list[tuple[Path, str]] = []
    stage = "prepare owned media"

    def checked(label: str) -> None:
        report["checks"].append(label)
        print("PASS " + label, flush=True)

    try:
        executable, module = args.exe.resolve(strict=True), args.module.resolve(strict=True)
        report["executable"] = {"path": str(executable), "sha256": digest(executable)}
        sources = []
        for index, source in enumerate(args.audio):
            original = source.resolve(strict=True)
            require(original.is_file() and original.suffix.lower() in (".wav", ".mp3"), "Audio must be an existing WAV or MP3")
            source_hash = digest(original)
            supplied.append((original, source_hash))
            owned = workspace / f"owned-{index}{original.suffix.lower()}"
            shutil.copy2(original, owned)
            require(digest(owned) == source_hash, "Owned copy differs from source")
            sources.append(owned)
        report["media"] = [{"path": str(path), "bytes": path.stat().st_size, "sha256": supplied[index][1]}
                           for index, path in enumerate(sources)]
        media_bytes = sum(path.stat().st_size for path in sources)
        target = workspace / "Playing.emproj"
        with Client(executable, args.timeout) as client:
            def command(name: str, arguments: dict | None = None, wait: bool = True) -> dict:
                nonlocal stage
                stage = name
                for attempt in range(3):
                    state = client.state()
                    response = client.raw({"command": name, "args": arguments or {}, "request_id": str(uuid.uuid4()),
                                           "project_id": state["project_id"], "expected_revision": state["revision"]})
                    if response.get("status") == "conflict" and attempt < 2:
                        time.sleep(0.05)
                        continue
                    require(response.get("status") in ("accepted", "completed"), json.dumps(response))
                    if wait and response["status"] == "accepted":
                        response["job_completion"] = client.wait_job(response["result"]["job_id"])
                    return response
                raise AssertionError("Project did not settle for command acceptance")

            def sample(label: str) -> dict:
                started = time.perf_counter()
                state = client.state()
                report["playback_samples"].append({"label": label, "at": time.perf_counter(),
                    "request_ms": (time.perf_counter() - started) * 1000, "position_seconds": state["position_seconds"],
                    "playing": state["playing"], "dirty": state["dirty"], "revision": state["revision"],
                    "xruns": state["xruns"], "cpu_usage": state["cpu_usage"],
                    "sample_rate": state["sample_rate"], "buffer_size": state["buffer_size"]})
                require(state["playing"], "Playback stopped during " + label)
                require(not state.get("recording") and not state.get("recording_finalizing"), "Recording unexpectedly started")
                return state

            def diagnostics(label: str) -> dict:
                value = client.completed(client.raw({"command": "get_save_diagnostics", "args": {}}))
                report["save_diagnostics"].append({"label": label, **value})
                return value

            try:
                command("set_master_gain", {"gain_db": -42})
                command("import_audio", {"paths": [str(path) for path in sources]})
                command("create_track", {"kind": "instrument", "name": "Quiet playback-save instrument"})
                instrument_id = client.state()["tracks"][-1]["id"]
                command("create_midi_clip", {"track_id": instrument_id, "start_beats": 0, "length_beats": 16})
                clip_id = client.state()["tracks"][-1]["clips"][0]["id"]
                notes = [{"id": f"playback-save-note-{index}", "pitch": 48 + index % 5,
                          "start_beats": index, "length_beats": 0.75, "velocity": 36, "channel": 1}
                         for index in range(16)]
                command("write_notes", {"clip_id": clip_id, "notes": notes})
                for track in client.state()["tracks"]:
                    command("set_track_gain", {"track_id": track["id"], "gain_db": -18})
                command("scan_plugins", {"include_default_paths": False, "paths": [], "modules": [str(module)]})
                exact_ids = {entry["id"] for entry in exact_cache_entries(module) if entry["available"]}
                entries = [entry for entry in page(client, "get_plugin_catalog", "plugins")
                           if entry["id"] in exact_ids and entry["is_instrument"]]
                require(bool(entries), "Exact module has no available instrument descriptor")
                entries.sort(key=lambda entry: (entry["name"], entry["id"]))
                report["plugin"] = {"module": str(module), "descriptor": entries[0], "untested": entries[1:]}
                command("add_plugin", {"track_id": instrument_id, "catalog_id": entries[0]["id"]})
                command("set_loop_range", {"start_seconds": 0, "end_seconds": 8})
                command("set_loop", {"enabled": True})
                time.sleep(0.3)
                report["audio_device"] = client.completed(client.raw({"command": "get_audio_devices", "args": {"scan": False}}))
                before_play = diagnostics("before play")
                require(before_play["current_key"] == before_play["fresh_content_key"], "Cached content key is already stale before playback")
                command("play")
                sample("play started")
                time.sleep(1.0)  # Settle first process/voice/device startup before measured saves.
                before_window = sample("before save window")
                after_play = diagnostics("after play")
                require(after_play["current_key"] == after_play["fresh_content_key"] == before_play["current_key"],
                        "Playback changed persistent project identity/content without an edit")
                require(before_window["sample_rate"] > 0 and before_window["buffer_size"] > 0, "No active output device")
                checked("two owned audio tracks and exact instrument play quietly on the existing output device")

                first_paths = None

                def save(label: str, during=None) -> dict:
                    nonlocal first_paths, stage
                    stage = "save " + label
                    before = sample(label + " before")
                    began = time.perf_counter()
                    # This measures actual acceptance without hiding a snapshot request in ack_ms.
                    response = client.raw({"command": "save_project", "args": {"path": str(target)},
                        "request_id": str(uuid.uuid4()), "project_id": before["project_id"], "expected_revision": before["revision"]})
                    accepted = time.perf_counter()
                    require(response.get("status") == "accepted", "Save was not accepted: " + json.dumps(response))
                    job_id = response["result"]["job_id"]
                    metric: dict = {"label": label, "job_id": job_id, "ack_ms": (accepted - began) * 1000,
                                    "accepted_revision": response["revision"], "phases": []}
                    report["saves"].append(metric)
                    if during:
                        # Record the observed phase; fast jobs may finish before the
                        # edit arrives. The accepted snapshot assertion still applies.
                        observed = client.completed(client.raw({"command": "get_job", "args": {"job_id": job_id}}))
                        metric["job_before_edit"] = observed
                        during()
                    deadline = time.monotonic() + args.timeout
                    polls = []
                    while True:
                        poll_start = time.perf_counter()
                        job = client.completed(client.raw({"command": "get_job", "args": {"job_id": job_id}}))
                        polls.append((time.perf_counter() - poll_start) * 1000)
                        if job.get("phase") not in metric["phases"]:
                            metric["phases"].append(job.get("phase"))
                        current = sample(label + " polling")
                        require((current["sample_rate"], current["buffer_size"]) ==
                                (before_window["sample_rate"], before_window["buffer_size"]), "Audio configuration changed during measurement")
                        if job["status"] in TERMINAL_JOBS:
                            break
                        require(time.monotonic() < deadline, "Save job timed out")
                        time.sleep(0.05)
                    metric.update(total_ms=(time.perf_counter() - began) * 1000, max_job_poll_ms=max(polls), job=job,
                                  xruns_before=before["xruns"], xruns_after=current["xruns"])
                    require(job["status"] == "completed", "Save failed: " + json.dumps(job))
                    metric["save_diagnostics"] = diagnostics(label + " completed")
                    data = json.loads(target.read_text(encoding="utf-8-sig"))
                    require(data["schema"] == 4 and len(data["tracks"]) == 3, "Saved project structure is incomplete")
                    require(job["plugins_captured"] == 1, "Expected one captured native instrument")
                    slots = [slot for track in data["tracks"] for slot in track["plugins"]]
                    metric["saved_plugin_identity"] = [{key: slot[key] for key in
                        ("id", "identifier", "format", "unique_id", "deprecated_unique_id", "version", "role")} for slot in slots]
                    require(len(slots) == 1 and normal_path(slots[0]["identifier"]) == normal_path(module),
                            "Playback save changed the exact scanned module to a runtime binary alias")
                    paths = [entry["source"] for entry in data["assets"]]
                    if first_paths is None:
                        first_paths = paths
                        require(job["bytes_reused"] == 0 and job["bytes_written"] >= media_bytes, "First playing save did not archive all audio")
                    else:
                        require(paths == first_paths and job["bytes_reused"] == media_bytes, "Repeated playing save duplicated media")
                    return data

                for iteration in range(args.saves):
                    save(f"repeat-{iteration + 1}")
                    saved_diagnostics = report["saves"][-1]["save_diagnostics"]
                    require(saved_diagnostics["current_key"] == saved_diagnostics["saved_key"] == saved_diagnostics["fresh_content_key"]
                            and not saved_diagnostics["plugin_dirty"] and not saved_diagnostics["pending_plugin_changes"],
                            "Quiescent save has divergent content keys or unsaved plugin changes")
                    require(not sample("saved clean")["dirty"], "Quiescent playing save remained dirty")
                    time.sleep(0.15)
                    require(not sample("post-save settle")["dirty"], "Playback alone marked the saved project dirty")
                checked("repeated async saves complete with playback continuing and unchanged media reused")

                updated_note = dict(notes[0], pitch=notes[0]["pitch"] + 7, velocity=42)
                earlier = save("edit after acceptance", during=lambda: command("edit_notes", {"clip_id": clip_id, "upsert": [updated_note]}))
                old_clip = next(clip for track in earlier["tracks"] for clip in track["clips"] if clip["id"] == clip_id)
                require(next(note for note in old_clip["notes"] if note["id"] == notes[0]["id"])["pitch"] == notes[0]["pitch"],
                        "Save changed its accepted note snapshot")
                require(sample("later edit retained")["dirty"], "Edit made after Save acceptance was incorrectly marked saved")
                notes[0] = updated_note
                final_manifest = save("save later edit")
                after_window = sample("after save window")
                require(not after_window["dirty"], "Follow-up playing save did not capture the edit")
                checked("editing after acceptance preserves earlier disk snapshot and later dirty state; next Save includes the edit")
                before_xruns, after_xruns = before_window["xruns"], after_window["xruns"]
                available = isinstance(before_xruns, int) and isinstance(after_xruns, int) and 0 <= before_xruns <= after_xruns
                report["xrun_measurement"] = {"available": available, "before": before_xruns, "after": after_xruns,
                    "delta": after_xruns - before_xruns if available else None, "requested_limit": args.max_xrun_delta}
                if args.max_xrun_delta is not None:
                    require(available and after_xruns - before_xruns <= args.max_xrun_delta, "Xrun counter unavailable/reset or exceeded requested limit")
                positions = [item["position_seconds"] for item in report["playback_samples"]]
                require(max(positions) - min(positions) > 0.1, "Playback flag stayed true but its clock did not advance")
                command("stop")
                command("open_project", {"path": str(target)})
                loaded = client.state()
                require(not loaded["dirty"] and not loaded["playing"] and len(loaded["tracks"]) == 3, "Reopened project is not clean/stopped/complete")
                track = next(track for track in loaded["tracks"] if track["id"] == instrument_id)
                require(len(track["plugins"]) == 1 and not track["plugins"][0]["missing"], "Native instrument did not restore")
                actual = page(client, "get_clip_notes", "notes", {"clip_id": clip_id})
                require(sorted(actual, key=lambda item: item["id"]) == sorted(notes, key=lambda item: item["id"]), "MIDI edits were lost after reopen")
                archived_hashes = sorted(digest(workspace / asset["source"]) for asset in final_manifest["assets"])
                require(archived_hashes == sorted(item[1] for item in supplied), "Archived media differs from original copies")
                require(abs(loaded["master_gain_db"] + 42) < 0.01 and loaded["looping"], "Quiet gain or loop state did not persist")
                checked("saved native plugin, all MIDI notes, media bytes and mixer/loop state reopen intact")
                diagnostics("reopened clean")
            except Exception:
                # Retain evidence before stop changes any playback/plugin state.
                try:
                    report["failure_snapshot"] = client.state()
                    diagnostics("failure before stop")
                except Exception as diagnostic_error:
                    report["diagnostic_error"] = str(diagnostic_error)
                raise
            finally:
                # Stop only this test-owned process. Client closes it even when a
                # transport/control assertion fails; no other DAW is touched.
                failure_stage = stage
                if client.process.poll() is None:
                    try:
                        command("stop")
                    except Exception as stop_error:
                        report["stop_error"] = str(stop_error)
                stage = failure_stage
        report["status"] = "passed"
    except Exception as error:
        report["status"], report["error"], report["failed_stage"] = "failed", str(error), stage
    finally:
        source_checks = []
        for path, before_hash in supplied:
            try:
                source_checks.append({"path": str(path), "unchanged": digest(path) == before_hash})
            except OSError as error:
                source_checks.append({"path": str(path), "unchanged": False, "error": str(error)})
        report["source_checks"] = source_checks
        if any(not item["unchanged"] for item in source_checks):
            report["status"] = "failed"
            report["source_error"] = "A supplied source changed or became unavailable during the test"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (workspace / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(workspace / "report.json"), "error": report.get("error")}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
