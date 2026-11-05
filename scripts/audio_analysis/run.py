"""One isolated, offline analysis job. No project editing and no API credentials.

Run with the provider's registered Python: run.py --request <job>/request.json.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.metadata
import hashlib
import math
import os
from pathlib import Path
import sys
import threading
import time
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audio_analysis.common import (AnalysisError, Cancelled, Job, atomic_json, provider_entry,
                                           sha256_file)


def configure_environment(root: Path) -> None:
    # Child-local only; this never persists an environment change to Windows.
    caches = {"HF_HOME": root / "cache/downloads/huggingface", "TORCH_HOME": root / "cache/downloads/torch",
              "NUMBA_CACHE_DIR": root / "cache/numba", "TEMP": root / "cache/tmp", "TMP": root / "cache/tmp"}
    for name, directory in caches.items():
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2",
                      NUMBA_NUM_THREADS="2", VECLIB_MAXIMUM_THREADS="2", NUMEXPR_NUM_THREADS="2",
                      HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")


class ResourceSampler:
    def __init__(self):
        self.peak_rss = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        try:
            import psutil
            process = psutil.Process()
            if sys.platform == "win32":
                process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            while not self.stop.is_set():
                self.peak_rss = max(self.peak_rss, process.memory_info().rss)
                self.stop.wait(.1)
        except (ImportError, OSError):
            pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=1)


def prepare(job):
    import numpy as np
    import soundfile as sf
    source = Path(job.request["source_path"])
    if not source.is_file():
        raise AnalysisError("missing_source", "The selected source file no longer exists.")
    job.progress("hashing_source", .02, "Checking source identity on the analysis worker.", "preparing")
    before = source.stat()
    digest = sha256_file(source, job)
    expected = job.request["source"].get("source_sha256")
    if expected and digest != expected:
        raise AnalysisError("source_changed", "The prepared source has changed since this job was requested.")
    with sf.SoundFile(source) as stream:
        rate = int(stream.samplerate)
        if stream.channels not in (1, 2) or not 8000 <= rate <= 192000:
            raise AnalysisError("unsupported_audio", "Select mono/stereo audio between 8 and 192 kHz.")
        first = math.floor(job.request["source_offset_seconds"] * rate + .5)
        count = math.floor(job.request["duration_seconds"] * rate + .5)
        if count < 1 or first >= stream.frames or first + count > stream.frames + 1:
            raise AnalysisError("source_range", "The requested range exceeds the source audio duration.")
        count = min(count, stream.frames - first)
        stream.seek(first)
        blocks = []
        remaining = count
        while remaining:
            job.check_cancelled()
            block = stream.read(min(65536, remaining), dtype="float32", always_2d=True)
            if not len(block) or not np.isfinite(block).all():
                raise AnalysisError("invalid_audio", "Source audio is truncated or contains NaN/Infinity.")
            blocks.append(block)
            remaining -= len(block)
        audio = np.concatenate(blocks, axis=0)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AnalysisError("source_changed", "The source file changed while its range was being frozen.")
    sf.write(job.directory / "input.wav", audio, rate, subtype="FLOAT")
    job.progress("prepared", .12, "Frozen dry source range; track effects are not rendered.", "preparing")
    metadata = {**job.request["source"], "source_sha256": digest, "source_sample_rate": rate,
                "source_offset_seconds": first / rate, "duration_seconds": count / rate,
                "source_start_sample": first, "source_frames": count, "source_channels": audio.shape[1],
                "frozen_input_sha256": sha256_file(job.directory / "input.wav", job)}
    return audio, rate, metadata


def execute(job):
    configure_environment(job.root)
    kind = job.request["kind"]
    entry = provider_entry(job.root, "separate_6s" if kind == "separate" and job.request["parameters"]["stems"] == 6 else kind)
    with ResourceSampler() as resources:
        audio, rate, source = prepare(job)
        kind = job.request["kind"]
        if kind == "chords":
            from scripts.audio_analysis.chords import analyze
        else:
            from scripts.audio_analysis import providers
            analyze = getattr(providers, kind)
        result = analyze(job, audio, rate, entry)
        job.progress("validating", .95, "Checking candidate artifacts before publishing.", "validating")
        model = {key: entry[key] for key in ("model_id", "version", "weight_sha256", "source_revision",
                                             "license_status", "source_url", "experimental") if key in entry}
        model["id"] = model.pop("model_id", kind)
        implementation = hashlib.sha256()
        for filename in ("__init__.py", "common.py", "chords.py", "providers.py", "run.py"):
            implementation.update((filename + "\0" + sha256_file(Path(__file__).with_name(filename)) + "\n").encode("utf-8"))
        model["worker_version"] = "1.1.0"
        if kind == "chords":
            # This algorithm ships with the worker, not with external weights;
            # do not report a stale v1 registry as the executed algorithm.
            model.update(version="2.0.0", source_revision="emusician-chroma-hmm-2")
        model["worker_source_sha256"] = implementation.hexdigest()
        runtime_metrics = result.pop("runtime_metrics", {})
        packages = ["numpy", "scipy", "soundfile"] + {
            "separate": ["torch", "demucs"], "transcribe": ["basic-pitch", "onnxruntime", "librosa"],
            "chords": []}[kind]
        result.update(schema_version=1, job_id=job.request["job_id"], result_id=job.request["job_id"],
                      kind=kind, model=model, source=source, duration_seconds=len(audio) / rate,
                      parameters=job.request["parameters"], stems=result.get("stems", []),
                      notes=result.get("notes", []), chord_regions=result.get("chord_regions", []),
                      performance={"elapsed_seconds": time.perf_counter() - job.started,
                                   "peak_process_rss_bytes": resources.peak_rss,
                                   "rss_sampling_interval_seconds": .1, "device": "cpu", "cpu_threads": 2,
                                   "python": sys.version.split()[0], "audio_device": "none-offline-worker",
                                   "input_sample_rate": rate, "input_duration_seconds": len(audio) / rate,
                                   "phase_seconds": job.timings(),
                                   **runtime_metrics},
                      runtime_versions={name: importlib.metadata.version(name) for name in packages})
        job.check_cancelled()
        atomic_json(job.directory / "result.json", result)
        job.progress("ready", 1., "Candidate ready. Review and accept to change the project.", "ready")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    directory = args.request.resolve().parent
    if not directory.is_dir():
        return 2
    with (directory / "worker.log").open("a", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        try:
            job = Job(args.request)
            execute(job)
            return 0
        except BaseException as error:
            code = error.code if isinstance(error, AnalysisError) else "worker_failed"
            if isinstance(error, MemoryError) or "out of memory" in str(error).lower():
                code = "out_of_memory"
            message = str(error)[:2000] or type(error).__name__
            traceback.print_exc()
            atomic_json(directory / "error.json", {"schema_version": 1, "code": code, "message": message})
            atomic_json(directory / "progress.json", {"schema_version": 1,
                        "status": "cancelled" if isinstance(error, Cancelled) else "failed",
                        "phase": code, "progress": 0, "detail": message})
            return 3 if isinstance(error, Cancelled) else 2


if __name__ == "__main__":
    sys.exit(main())
