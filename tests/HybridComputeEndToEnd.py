"""Real native-command / cloud-GPU acceptance on disposable projects.

This spends rented GPU time when run. The Agent's real authorization/proposal
compiler is used with deterministic requests, not a language model. Each model
runs serially. An eight-second MIR crop proves plumbing, not full-song quality.
Run through scripts.dev.Recorder after freezing the desktop build and services.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import time
import uuid
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError
from cloud.run_generation import inspect_wav
from music_agent import analysis, generation
from music_agent.compute import require_route
from music_agent.selection import freeze_scope
from MusicAgentIntegration import protected

MODELS = {
    "scnet": ("separate", "newlight"),
    "transkun": ("transcribe", "keyboard"),
    "chordmini": ("chords", "newlight"),
    "muscriptor": ("transcribe", "keyboard"),
    "sheetsage2": ("score", "newlight"),
    "ace-step-1.5-xl-turbo": ("generate", None),
    "yue2": ("generate", None),
}
SOURCE_ROOT = Path("E:/E-musician/test-projects/test9-newlight")
EXPERIMENTS = Path("E:/MusicAgent&DAW/cloud-inference/experiments")
MIR_SECONDS, GENERATION_SECONDS, TIMELINE_START = 8.0, 12.0, 2.5


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def model_names(value):
    names = [part.strip() for argument in value for part in argument.split(",") if part.strip()]
    if not names or len(set(names)) != len(names) or set(names) - set(MODELS):
        raise ValueError("Use unique model IDs from: " + ", ".join(MODELS))
    return names


def latency_summary(samples):
    """Small local-control samples are a range, not a percentile claim."""
    result = {"count": len(samples), "scope": "Local offline-device native read-only control request round-trip; not GUI, ASIO or audio-callback latency"}
    if samples:
        ordered = sorted(samples)
        result.update(min_ms=ordered[0], max_ms=ordered[-1])
        if len(samples) >= 20:
            result.update(p50_ms=statistics.median(ordered), p95_ms=ordered[(95 * len(ordered) + 99) // 100 - 1])
    return result


def stable_music(value):
    """Ignore JSON round-trip noise below one nanosecond/beat, not events."""
    if isinstance(value, float): return round(value, 9)
    if isinstance(value, list): return [stable_music(item) for item in value]
    if isinstance(value, dict): return {key: stable_music(item) for key, item in value.items()}
    return value


class Acceptance:
    def __init__(self, executable, directory, timeout, report):
        self.executable, self.directory, self.timeout, self.report = executable, directory, timeout, report
        self.client = None

    def checkpoint(self):
        save_json(self.directory / "report.json", self.report)

    @contextmanager
    def phase(self, name):
        receipt = {"phase": name, "started_at": utc(), "passed": False}
        self.report["phases"].append(receipt)
        self.checkpoint()
        started = time.perf_counter()
        try:
            yield receipt
            receipt["passed"] = True
        finally:
            receipt.update(finished_at=utc(), elapsed_seconds=time.perf_counter() - started)
            self.checkpoint()

    def open(self, offline_root=None):
        # The executable is frozen at the experiment root. Reuse its owned
        # decoded-audio cache across model cases without filling the C: profile.
        cache = self.executable.parent / "audio-cache"
        temporary = self.executable.parent / "temporary"
        cache.mkdir(exist_ok=True)
        temporary.mkdir(exist_ok=True)
        environment = {"EMUSICIAN_AUDIO_CACHE_ROOT": str(cache), "TEMP": str(temporary), "TMP": str(temporary)}
        if offline_root is not None:
            environment.update(EMUSICIAN_COMPUTE_ROOT=str(offline_root), EMUSICIAN_GENERATION_ROOT=str(offline_root))
        with patch.dict(os.environ, environment):
            self.client = Client(self.executable, timeout=120, show=False, offline_test=True)

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def read(self, command, args=None):
        return self.client.completed(self.client.raw({"command": command, "args": args or {}}))

    def write(self, command, args=None, wait=True):
        return self.client.request({"command": command, "args": args or {}}, wait=wait)

    def wait(self, kind, job_id, terminal):
        command = "get_generation_job" if kind == "generate" else "get_analysis_job"
        deadline = time.monotonic() + self.timeout
        transitions, previous, samples = [], None, []
        while time.monotonic() < deadline:
            started = time.perf_counter()
            job = self.read(command, {"job_id": job_id})
            samples.append((time.perf_counter() - started) * 1000)
            self.report.setdefault("control_requests", {})[job_id] = {
                "command": command, "samples_ms": samples, **latency_summary(samples)}
            marker = (job.get("status"), job.get("phase"))
            if marker != previous:
                transitions.append({"at": utc(), "status": marker[0], "phase": marker[1]})
                self.report["jobs"][job_id] = {"transitions": transitions, "last": job}
                self.checkpoint()
                previous = marker
            if job.get("status") in terminal:
                self.report["jobs"][job_id]["last"] = job
                return job
            if job.get("status") in {"failed", "cancelled", "canceled", "stale", "interrupted"}:
                raise AssertionError("Model job did not complete: " + analysis.safe_text(job.get("error") or job.get("detail") or job.get("status")))
            time.sleep(.2)
        raise AssertionError("Model job exceeded timeout; receipt retained. Remote work may still need cancellation.")

    def pages(self, command, args=None, key="items", limit=100, maximum=100000):
        result, total = [], None
        while total is None or len(result) < total:
            page = self.read(command, {**(args or {}), "offset": len(result), "limit": limit})
            count = page.get("total")
            assert type(count) is int and 0 <= count <= maximum, page
            assert total is None or total == count, "Page total changed during readback"
            total = count
            items = page.get(key)
            assert isinstance(items, list) and len(items) <= limit
            assert items or len(result) == total, "Pagination stopped before all items were returned"
            result.extend(items)
            assert len(result) <= total
        return result

    def musical_state(self):
        snapshot = self.client.state()
        tracks = []
        for track in snapshot["tracks"]:
            clips = []
            for clip in track["clips"]:
                item = {key: clip.get(key) for key in ("id", "kind", "start_seconds", "duration_seconds", "note_count", "controller_count")}
                if clip["kind"] == "midi":
                    item["notes"] = self.pages("get_clip_notes", {"clip_id": clip["id"]}, "notes", 1000)
                    item["controllers"] = self.pages("get_clip_controllers", {"clip_id": clip["id"]}, "events", 1000)
                clips.append(item)
            tracks.append({"id": track["id"], "name": track.get("name"), "clips": clips})
        return stable_music({"bpm": snapshot["bpm"], "tracks": tracks,
                "chords": self.pages("get_chord_regions", maximum=10000),
                "beats": self.pages("get_analysis_annotations", {"component": "beats"}, maximum=10000),
                "structure": self.pages("get_analysis_annotations", {"component": "structure"}, maximum=10000),
                "midi_tracks": self.pages("get_analysis_annotations", {"component": "midi_tracks"}, maximum=10000)})

    def run(self, model, source):
        kind = MODELS[model][0]
        with self.phase("open_owned_daw_and_import_input"):
            self.open()
            assert not self.client.state()["tracks"]
            if kind == "generate":
                self.write("set_tempo", {"bpm": 170})
            if source is not None:
                self.write("import_audio", {"paths": [str(source)]})
                clip_id = self.client.state()["tracks"][0]["clips"][0]["id"]
                self.write("move_clip", {"clip_id": clip_id, "start_seconds": TIMELINE_START})
            baseline = self.musical_state()
            context = self.client.state()
            frozen = freeze_scope(context, "project")
            caps = self.read("get_generation_capabilities" if kind == "generate" else "get_analysis_capabilities")
            require_route(caps, kind, {"execution": "cloud", "model_id": model})
            self.report["capability"] = next(p for p in caps["providers"] if p.get("model_id") == model)
        with self.phase("real_gpu_inference_candidate_without_project_edit"):
            if kind == "generate":
                request = generation.authorize_start(context, frozen, {"execution": "cloud", "model_id": model,
                    "prompt": "Instrumental dark UK jungle, 170 BPM, chopped Amen break, rolling breakbeats, deep sub bass, dark pads, raw pirate radio texture, no sung vocals.",
                    "lyrics": "", "duration_seconds": GENERATION_SECONDS, "seed": 16384, "timeline_start_seconds": TIMELINE_START})
            else:
                request = analysis.authorize_start(context, frozen, {"clip_id": clip_id, "kind": kind,
                    "execution": "cloud", "model_id": model, "start_seconds": 0, "duration_seconds": MIR_SECONDS})
            self.report["request"] = request
            response = self.write("start_generation" if kind == "generate" else "start_analysis", request, False)
            ready = self.wait(kind, response["result"]["job_id"], {"ready"})
            rid = ready["result_id"]
            result_command = "get_generation_result" if kind == "generate" else "get_analysis_result"
            candidate = self.read(result_command, {"result_id": rid})
            self.report["candidate"] = candidate
            assert candidate["execution"] == "cloud" and candidate["model_id"] == model, candidate
            assert len(candidate["result_hash"]) == 64
            assert abs(candidate["source"]["timeline_start"] - TIMELINE_START) < 1e-8
            assert self.client.state()["revision"] == context["revision"]
            assert self.musical_state() == baseline, "Candidate inference mutated project before acceptance"
            if kind == "score":
                self.report["component_totals"] = {component: self.read(result_command, {
                    "result_id": rid, "component": component, "limit": 1})["total"]
                    for component in ("notes", "chords", "beats", "structure")}
            if kind == "generate":
                completion = candidate.get("completion")
                assert isinstance(completion, dict), "Generated candidate omitted completion evidence"
                truncated = completion.get("truncated")
                assert truncated is None or type(truncated) is bool, "Completion truncation must be canonical bool/null, not an upstream stage dictionary"
                assert "truncated" in completion and candidate.get("truncated") is truncated
                assert completion.get("reason") == ("token_budget" if truncated is True else "model_stop" if truncated is False else "unknown")
                plan = generation.compile_import(candidate, context, frozen, "Deterministic acceptance fixture")
                self.report["agent_completion"] = plan["generation"]["completion"]
                assert plan["generation"]["completion"].get("truncated") is truncated
                assert plan["generation"]["completion"].get("reason") == completion["reason"]
            else:
                plan = analysis.compile_import(analysis.safe_result(candidate), context, frozen, "Deterministic acceptance fixture")
            self.report["agent_proposal"] = {k: plan[k] for k in ("execution_kind", "commands", "changes")}
            assert len(plan["commands"]) == 1
        with self.phase("accept_once_idempotency_and_single_undo_redo"):
            command = plan["commands"][0]
            response = self.write(command["command"], command["args"], False)
            applied = self.wait(kind, response["result"]["job_id"], {"applied"})
            state = self.client.state()
            assert state["revision"] == context["revision"] + 1
            expected = 1 if kind == "generate" else analysis.import_track_count(candidate)
            assert len(state["tracks"]) == len(context["tracks"]) + expected
            receipt = applied["receipt"]
            assert receipt["applied"] and receipt["revision"] == state["revision"]
            after = self.musical_state()
            assert after["bpm"] == baseline["bpm"], "Import silently changed project tempo"
            added = [c for t in after["tracks"] for c in t["clips"] if c["id"] in receipt["clip_ids"]]
            assert all(abs(c["start_seconds"] - TIMELINE_START) < 1e-8 for c in added)
            if kind in {"transcribe", "score"}:
                summary = candidate["summary"]
                assert sum(len(c.get("notes", [])) for c in added) == summary["note_count"]
                controls = [event for c in added for event in c.get("controllers", [])]
                assert sum(0 <= event["type"] <= 127 for event in controls) == summary["controller_count"]
                assert sum(event["type"] == 4097 for event in controls) == summary["program_change_count"]
                assert len(controls) == summary["controller_count"] + summary["program_change_count"]
                metadata = {item["clip_id"]: item for item in after["midi_tracks"]}
                for clip in added:
                    programs = [event for event in clip["controllers"] if event["type"] == 4097]
                    assert len(programs) == 1 and programs[0]["value"] == metadata[clip["id"]]["program"] << 7
                    assert all(note["channel"] == metadata[clip["id"]]["channel"] for note in clip["notes"])
                if kind == "score":
                    assert len(after["chords"]) == summary["chord_count"]
                    assert len(after["beats"]) == summary["beat_count"]
                    assert len(after["structure"]) == summary["annotation_count"]
            if kind == "chords": assert len(after["chords"]) == candidate["total"]
            try:
                self.write(command["command"], command["args"], False)
            except ControlError:
                pass
            assert self.client.state()["revision"] == state["revision"] and self.musical_state() == after
            self.write("undo")
            assert self.musical_state() == baseline
            self.write("redo")
            assert self.musical_state() == after
            save_json(self.directory / "accepted-musical-state.json", after)
        with self.phase("save_close_disable_cloud_reopen_and_compare_full_music_state"):
            project = self.directory / (model + ".emproj")
            self.write("save_project", {"path": str(project)})
            manifest = json.loads(project.read_text(encoding="utf-8"))
            assert manifest["schema"] >= (8 if kind in {"transcribe", "score"} else 7 if kind == "generate" else 5)
            if kind == "generate":
                records = [item for item in manifest.get("generations", []) if item["id"] == rid]
                assert len(records) == 1, "Saved generation provenance is missing or duplicated"
                provenance = json.loads(records[0]["parameters_json"])
                assert provenance.get("completion") == candidate["completion"], "Save dropped or changed generation completion/stages"
                assert provenance.get("truncated") is candidate["truncated"]
                assert provenance.get("limitations") == candidate.get("limitations", [])
                assert abs(provenance["actual_duration_seconds"] - candidate["audio"]["duration_seconds"]) < 1e-8
                self.report["generation_provenance_verified"] = True
            self.report["project"] = {"path": str(project), "schema": manifest["schema"], "sha256": sha256(project)}
            self.close()
            offline = self.directory / "offline-registry"
            offline.mkdir()
            for name in ("registry.json", "compute-registry.json"):
                save_json(offline / name, {"schema_version": 1, "available": False, "providers": []})
            self.open(offline)
            assert self.read("get_generation_capabilities")["available"] is False
            assert not any(p.get("execution") == "cloud" and p.get("available") for p in self.read("get_analysis_capabilities")["providers"])
            self.write("open_project", {"path": str(project)})
            assert self.musical_state() == after, "Saved notes, CC, chord/beat/structure metadata did not round-trip"
        with self.phase("local_offline_render"):
            rendered = self.directory / "offline-render.wav"
            duration = candidate["audio"]["duration_seconds"] if kind == "generate" else MIR_SECONDS
            self.write("export_wav", {"path": str(rendered), "start_seconds": 0,
                "end_seconds": TIMELINE_START + duration, "sample_rate": 48000, "bit_depth": 16, "tail_seconds": 0})
            with wave.open(str(rendered), "rb") as wav:
                metadata = {"sha256": sha256(rendered), "duration_seconds": wav.getnframes() / wav.getframerate(),
                            "sample_rate": wav.getframerate(), "channels": wav.getnchannels()}
            _, peaks = inspect_wav(rendered, metadata)
            assert max(peaks) > 0, "Offline audio asset render was silent"
            self.report["render"] = metadata
            self.report["render_scope"] = "Local audio assets; source audio is retained. This does not verify newly imported MIDI instrument sounds."
        self.report["passed"] = True
        self.checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--models", nargs="+", default=list(MODELS), help="Space-separated or comma-separated exact model IDs")
    parser.add_argument("--out", type=Path, help="New disposable output directory; existing paths are refused")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--newlight", type=Path, default=SOURCE_ROOT / "New Light()" / "New Light.mp3")
    parser.add_argument("--keyboard", type=Path, default=SOURCE_ROOT / "Keyboard.mp3")
    args = parser.parse_args()
    selected = model_names(args.models)
    directory = (args.out or EXPERIMENTS / ("hybrid-native-" + uuid.uuid4().hex)).resolve()
    if os.name == "nt" and directory.drive.upper() != "E:":
        raise ValueError("This machine's acceptance outputs, audio cache and temporary files must be on E:.")
    directory.mkdir(parents=True, exist_ok=False)
    temporary = directory / "temporary"
    temporary.mkdir()
    cache = directory / "audio-cache"
    cache.mkdir()
    source_exe = args.exe.resolve(strict=True)
    executable = directory / "E-musician.exe"
    shutil.copy2(source_exe, executable)
    source_paths = {"newlight": args.newlight, "keyboard": args.keyboard}
    required = {MODELS[name][1] for name in selected} - {None}
    inputs = {name: {"path": str(source_paths[name].resolve(strict=True)), "sha256": sha256(source_paths[name]),
                     "bytes": source_paths[name].stat().st_size} for name in sorted(required)}
    report = {"passed": False, "started_at": utc(), "mode": "real-native-public-command-real-cloud-model",
        "real_music_model": True, "real_llm": False, "agent_requests": "deterministic test fixtures using production authorization/proposal compiler",
        "physical_audio": False, "listening_quality_verified": False, "mir_excerpt_seconds": MIR_SECONDS,
        "generation_requested_seconds": GENERATION_SECONDS, "selected_models": selected, "inputs": inputs,
        "exe_sha256": sha256(executable), "original_exe": str(source_exe), "models": [],
        "test_environment": {"TEMP": str(temporary), "TMP": str(temporary), "EMUSICIAN_AUDIO_CACHE_ROOT": str(cache)}}
    save_json(directory / "report.json", report)
    protected_before, started = protected(), time.perf_counter()
    acceptance = None
    previous_temporary = {name: os.environ.get(name) for name in ("TEMP", "TMP")}
    os.environ.update(TEMP=str(temporary), TMP=str(temporary))
    try:
        for model in selected:
            model_directory = directory / model
            model_directory.mkdir()
            item = {"model_id": model, "kind": MODELS[model][0], "passed": False, "phases": [], "jobs": {}}
            report["models"].append(item)
            save_json(directory / "report.json", report)
            acceptance = Acceptance(executable, model_directory, args.timeout, item)
            source_name = MODELS[model][1]
            acceptance.run(model, source_paths[source_name] if source_name else None)
            acceptance.close()
            assert sha256(executable) == report["exe_sha256"], "Frozen executable changed during acceptance"
            for value in inputs.values(): assert sha256(value["path"]) == value["sha256"], "Original input changed"
            assert protected() == protected_before, "Protected user projects/settings changed"
            save_json(directory / "report.json", report)
        report["passed"] = True
    except Exception as exc:
        report["error"] = analysis.safe_text(str(exc), 1500)
        if acceptance:
            acceptance.report["error"] = report["error"]
            acceptance.checkpoint()
        raise
    finally:
        for name, previous in previous_temporary.items():
            if previous is None: os.environ.pop(name, None)
            else: os.environ[name] = previous
        if acceptance: acceptance.close()
        report.update(finished_at=utc(), elapsed_seconds=time.perf_counter() - started,
                      protected_unchanged=protected() == protected_before,
                      frozen_exe_unchanged=sha256(executable) == report["exe_sha256"])
        save_json(directory / "report.json", report)
        print(json.dumps({"passed": report["passed"], "report": str(directory / "report.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
