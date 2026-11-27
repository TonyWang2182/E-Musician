"""Verify cooperative cancellation during an actual model's inference, not a mock."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
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
    entry = read_json(root / "registry.json")["providers"]["separate"]
    job_id = "cancel-running-" + uuid.uuid4().hex[:12]
    directory = root / "cache/jobs" / job_id
    directory.mkdir(parents=True)
    source = directory / "fixture.wav"
    write_fixture(source, 12.)
    atomic_json(directory / "request.json", {"schema_version": 1, "job_id": job_id, "kind": "separate",
                "analysis_root": str(root), "source_path": str(source), "source_offset_seconds": 0,
                "duration_seconds": 12., "source": {"project_id": "cancel-probe", "clip_id": "synthetic"}})
    command = [entry["python_executable"], str(Path(__file__).with_name("run.py")), "--request", str(directory / "request.json")]
    print("RUN", subprocess.list2cmdline(command), flush=True)
    process = subprocess.Popen(command)
    started = time.perf_counter()
    cancelled = None
    try:
        while process.poll() is None:
            if time.perf_counter() - started > 120:
                raise TimeoutError("Real cancellation probe exceeded 120 seconds")
            progress_file = directory / "progress.json"
            if progress_file.exists():
                state = read_json(progress_file)
                if state.get("phase") == "separating" and cancelled is None:
                    (directory / "cancel").touch()
                    cancelled = time.perf_counter()
                    print("Requested cancellation during model inference", flush=True)
            time.sleep(.1)
        assert cancelled is not None, "Worker completed without reaching the intended running cancellation point"
        assert process.returncode == 3, read_json(directory / "error.json")
        assert read_json(directory / "error.json")["code"] == "cancelled"
        assert not (directory / "result.json").exists()
        report = {"scope": "Cooperative cancellation of a real HTDemucs inference process", "job_id": job_id,
                  "device": entry["device"], "exit_code": process.returncode,
                  "cancel_to_exit_seconds": time.perf_counter() - cancelled,
                  "elapsed_wall_seconds": time.perf_counter() - started, "result_published": False}
        destination = root / "manifests" / ("cancel-probe-" + uuid.uuid4().hex[:12] + ".json")
        atomic_json(destination, report)
        print(report)
        print("Report:", destination)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
