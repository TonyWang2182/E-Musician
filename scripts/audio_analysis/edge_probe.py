"""Actual worker-process edge cases using the installed CPU chord provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import struct
import sys
import time
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.runtime_paths import analysis_root
from scripts.audio_analysis.common import atomic_json, read_json
from scripts.audio_analysis.probe import write_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=analysis_root())
    args = parser.parse_args()
    root = args.root.resolve()
    registry = read_json(root / "registry.json")
    source_dir = root / "cache/edge-fixtures"
    source_dir.mkdir(parents=True, exist_ok=True)
    silent = source_dir / "silence.wav"
    write_fixture(silent, .2, silence=True)
    malformed = source_dir / "not-a-wave.wav"
    malformed.write_text("Not an audio file", encoding="utf-8")
    nonfinite = source_dir / "nonfinite.wav"
    frames = struct.pack("<ff", float("nan"), 0.) * 100
    fmt = struct.pack("<HHIIHH", 3, 2, 44100, 44100 * 8, 8, 32)
    nonfinite.write_bytes(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(frames)) + b"WAVEfmt "
                         + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames)
    cases = [("silence", {}, None), ("tiny", {"duration_seconds": .005}, None),
             ("out-of-range", {"source_offset_seconds": .15, "duration_seconds": .1}, "source_range"),
             ("missing", {"source_path": str(source_dir / "missing.wav")}, "missing_source"),
             ("corrupt", {"source_path": str(malformed)}, "worker_failed"),
             ("nonfinite", {"source_path": str(nonfinite), "duration_seconds": .001}, "invalid_audio"),
             ("changed", {"source": {"source_sha256": "0" * 64}}, "source_changed"),
             ("cancel", {}, "cancelled"), ("overlong", {"duration_seconds": 601}, "invalid_request"),
             ("drum-input", {"kind": "transcribe", "source": {"input_role": "drums"}}, "unsupported_input"),
             ("tiny-transcription", {"kind": "transcribe", "duration_seconds": .005}, None),
             ("silent-transcription", {"kind": "transcribe"}, None)]
    evidence = []
    for name, overrides, expected in cases:
        job_id = "edge-" + name + "-" + uuid.uuid4().hex[:10]
        directory = root / "cache/jobs" / job_id
        directory.mkdir(parents=True)
        request = {"schema_version": 1, "job_id": job_id, "kind": "chords", "analysis_root": str(root),
                   "source_path": str(silent), "source_offset_seconds": 0, "duration_seconds": .2,
                   "source": {"project_id": "edge-probe", "clip_id": "test"}, **overrides}
        atomic_json(directory / "request.json", request)
        if name == "cancel":
            (directory / "cancel").touch()
        command = [registry["providers"][request["kind"]]["python_executable"], str(Path(__file__).with_name("run.py")),
                   "--request", str(directory / "request.json")]
        started = time.perf_counter()
        completed = subprocess.run(command, timeout=120)
        if expected:
            assert completed.returncode != 0, name
            error = read_json(directory / "error.json")
            assert error["code"] == expected, (name, error)
            assert not (directory / "result.json").exists(), name
        else:
            if completed.returncode:
                print((directory / "worker.log").read_text(encoding="utf-8"))
                raise RuntimeError((name, read_json(directory / "error.json")))
            result = read_json(directory / "result.json")
            if request["kind"] == "chords":
                assert [item["label"] for item in result["chord_regions"]] == ["N"], result
                assert result["chord_regions"][-1]["end_seconds"] == result["source"]["source_frames"] / result["source"]["source_sample_rate"], result
            else:
                assert result["notes"] == [], result
            assert abs(result["duration_seconds"] - request["duration_seconds"]) <= .5 / 44100 + 1e-9, result
        evidence.append({"case": name, "job_id": job_id, "exit_code": completed.returncode,
                         "expected_code": expected, "elapsed_seconds": time.perf_counter() - started})
        print("PASS", name, flush=True)
    destination = root / "manifests" / ("edge-probe-" + uuid.uuid4().hex[:12] + ".json")
    atomic_json(destination, {"scope": "Actual isolated worker processes; controlled synthetic/error inputs", "cases": evidence})
    print("Report:", destination)


if __name__ == "__main__":
    main()
