"""Small, stdlib-only analysis protocol and artifact validation helpers."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any

MAX_DURATION = 600.0
MAX_NOTES = 100_000
MAX_CHORDS = 10_000
MAX_JSON_BYTES = 16 * 1024 * 1024
PRESETS = {"separate": "htdemucs", "transcribe": "basic-pitch", "chords": "chroma-hmm"}
PARAMETERS = {
    "separate": {"segment_seconds": (3., 4., 4.)},
    "transcribe": {"onset_threshold": (0., 1., .5), "frame_threshold": (0., 1., .3),
                   "minimum_note_ms": (10., 2000., 80.), "min_pitch": (21., 108., 21.),
                   "max_pitch": (21., 108., 108.)},
    "chords": {"sensitivity": (.2, .99, .55), "min_region_seconds": (.05, 2., .15)},
}


class AnalysisError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Cancelled(AnalysisError):
    def __init__(self):
        super().__init__("cancelled", "Analysis cancelled; no project changes were made.")


def atomic_json(path: Path, data: Any) -> None:
    value = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(value.encode("utf-8")) > MAX_JSON_BYTES:
        raise AnalysisError("result_limit", "Analysis JSON exceeds the 16 MiB limit; select a shorter range.")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers may momentarily hold a file handle without delete sharing.
    # A short worker-side retry prevents a progress poll from failing inference.
    for attempt in range(11):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 10:
                raise
            time.sleep(.02)


def read_json(path: Path, max_bytes: int = MAX_JSON_BYTES) -> Any:
    if path.stat().st_size > max_bytes:
        raise AnalysisError("input_limit", "JSON input is too large.")
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=lambda value: (_ for _ in ()).throw(
            AnalysisError("invalid_number", f"Non-finite JSON value: {value}")))


def finite_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AnalysisError("invalid_request", f"{name} must be a finite number.")
    if not minimum <= value <= maximum:
        raise AnalysisError("invalid_request", f"{name} must be between {minimum:g} and {maximum:g}.")
    return float(value)


def validate_request(request: Any) -> dict:
    if not isinstance(request, dict) or request.get("schema_version") != 1:
        raise AnalysisError("protocol_version", "Unsupported analysis request version.")
    job_id = request.get("job_id", "")
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", job_id):
        raise AnalysisError("invalid_request", "Invalid job ID.")
    kind = request.get("kind")
    if kind not in PRESETS or request.get("preset", "") not in ("", "default", PRESETS[kind]):
        raise AnalysisError("unsupported_provider", "Unknown analysis kind or preset.")
    source = request.get("source", {})
    if not isinstance(source, dict):
        raise AnalysisError("invalid_request", "source must be an object.")
    if kind == "transcribe" and source.get("input_role") in ("drums", "other"):
        raise AnalysisError("unsupported_input", "Basic Pitch is for pitched instruments, not drum classification or a mixed other stem.")
    params = request.get("parameters", {})
    if not isinstance(params, dict) or set(params) - set(PARAMETERS[kind]):
        raise AnalysisError("invalid_parameter", "Unknown analysis parameter.")
    normalized = {}
    for name, (low, high, default) in PARAMETERS[kind].items():
        normalized[name] = finite_number(params.get(name, default), name, low, high)
    if kind == "transcribe":
        if any(normalized[k] != int(normalized[k]) for k in ("min_pitch", "max_pitch")):
            raise AnalysisError("invalid_parameter", "Pitch limits must be integers.")
        if normalized["min_pitch"] > normalized["max_pitch"]:
            raise AnalysisError("invalid_parameter", "Minimum pitch exceeds maximum pitch.")
    offset = finite_number(request.get("source_offset_seconds", 0), "source_offset_seconds", 0, 172800.)
    duration = finite_number(request.get("duration_seconds"), "duration_seconds", .001, MAX_DURATION)
    source_path = request.get("source_path")
    if not isinstance(source_path, str) or not Path(source_path).is_absolute():
        raise AnalysisError("invalid_request", "source_path must be an absolute prepared audio file path.")
    root = request.get("analysis_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise AnalysisError("invalid_request", "analysis_root must be an absolute path.")
    return {**request, "preset": PRESETS[kind], "parameters": normalized,
            "source_offset_seconds": offset, "duration_seconds": duration, "source": dict(source)}


class Job:
    def __init__(self, request_path: Path):
        self.directory = request_path.resolve().parent
        self.request = validate_request(read_json(request_path, 128 * 1024))
        self.started = time.perf_counter()
        self.phase = "initializing"
        self.phase_started = self.started
        self.phase_seconds = {}
        self.root = Path(self.request["analysis_root"]).resolve()
        expected = self.root / "cache" / "jobs" / self.request["job_id"]
        if self.directory != expected.resolve():
            raise AnalysisError("invalid_job_directory", "Job must reside in analysis_root/cache/jobs/job_id.")
        if (self.directory / "result.json").exists():
            raise AnalysisError("result_exists", "This immutable job already has a result; create a new job to re-analyze.")

    def check_cancelled(self) -> None:
        if (self.directory / "cancel").exists():
            raise Cancelled()

    def progress(self, phase: str, fraction: float, detail: str = "", status: str = "running") -> None:
        self.check_cancelled()
        now = time.perf_counter()
        if phase != self.phase:
            self.phase_seconds[self.phase] = self.phase_seconds.get(self.phase, 0.) + now - self.phase_started
            self.phase, self.phase_started = phase, now
        atomic_json(self.directory / "progress.json", {
            "schema_version": 1, "job_id": self.request["job_id"], "status": status,
            "phase": phase, "progress": min(1., max(0., fraction)), "detail": detail,
            "elapsed_seconds": time.perf_counter() - self.started,
        })

    def timings(self) -> dict:
        return {**self.phase_seconds, self.phase: self.phase_seconds.get(self.phase, 0.) + time.perf_counter() - self.phase_started}


def sha256_file(path: Path, job: Job | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if job:
                job.check_cancelled()
            digest.update(block)
    return digest.hexdigest()


def provider_entry(root: Path, kind: str) -> dict:
    registry = read_json(root / "registry.json", 1024 * 1024)
    entry = registry.get("providers", {}).get(kind)
    if not isinstance(entry, dict) or entry.get("available") is not True:
        raise AnalysisError("provider_unavailable", "Analysis provider is not installed or did not pass its runtime probe.")
    return entry


def validate_notes(notes: list, duration: float) -> list:
    if len(notes) > MAX_NOTES:
        raise AnalysisError("result_limit", "More than 100000 notes; choose a shorter input range.")
    normalized = []
    for item in notes:
        pitch = finite_number(item.get("pitch"), "pitch", 0, 127)
        velocity = finite_number(item.get("velocity"), "velocity", 1, 127)
        channel = finite_number(item.get("channel", 1), "channel", 1, 16)
        start = finite_number(item.get("start_seconds"), "start_seconds", 0, duration)
        length = finite_number(item.get("duration_seconds"), "duration_seconds", 0.000001, duration)
        if pitch != int(pitch) or velocity != int(velocity) or channel != int(channel) or start + length > duration + 1e-7:
            raise AnalysisError("invalid_result", "A model note is outside the input range or has non-integral MIDI data.")
        normalized.append({"pitch": int(pitch), "start_seconds": start, "duration_seconds": length,
                           "velocity": int(velocity), "channel": int(channel)})
    return sorted(normalized, key=lambda item: (item["start_seconds"], item["pitch"], item["duration_seconds"]))
