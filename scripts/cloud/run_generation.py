"""Isolated desktop-to-cloud generation transport. No audio-engine dependency.

Only an SSH-authenticated loopback tunnel is used in production. Downloaded
audio is bounded and verified before result.json publishes the candidate.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

MAX_BYTES = 128 * 1024 * 1024
MAX_JSON = 256 * 1024
TERMINAL = {"failed", "cancelled", "interrupted"}
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from scripts.runtime_paths import generation_root, compute_root
except ModuleNotFoundError:
    from runtime_paths import generation_root, compute_root

ROOT = generation_root()


class GenerationError(RuntimeError):
    pass


class Cancelled(GenerationError):
    pass


class NetworkError(GenerationError):
    pass


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    # Native Windows polling can briefly deny delete-sharing on the old file.
    # Retry only this local publication; never restart or resubmit inference.
    for attempt in range(11):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 10:
                raise
            time.sleep(.02)


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise GenerationError("Missing or oversized generation configuration.")
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if not isinstance(value, dict):
        raise GenerationError("Generation JSON must be an object.")
    return value


def finite(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not lo <= value <= hi:
        raise GenerationError(f"Invalid {name}.")
    return value


def build_payload(request, registry):
    if request.get("schema_version") != 1 or request.get("kind") != "generate":
        raise GenerationError("Unsupported generation request.")
    job_id = request.get("job_id", "")
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-fA-F0-9-]{32,36}", job_id):
        raise GenerationError("Invalid generation job ID.")
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise GenerationError("Invalid generation job ID.") from exc
    prompt, lyrics = request.get("prompt"), request.get("lyrics", "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise GenerationError("Describe the music in at most 2000 characters.")
    if not isinstance(lyrics, str) or len(lyrics) > 4096:
        raise GenerationError("Lyrics must contain at most 4096 characters.")
    source = request.get("source", {})
    if not isinstance(source, dict):
        raise GenerationError("Invalid generation source context.")
    duration = finite(request.get("duration_seconds"), 10, 120, "generation duration")
    bpm = finite(request.get("bpm", source.get("bpm", 120)), 30, 300, "BPM")
    numerator = request.get("meter_numerator", source.get("meter_numerator", 4))
    denominator = request.get("meter_denominator", source.get("meter_denominator", 4))
    meter = f"{numerator}/{denominator}"
    if meter not in {"2/4", "3/4", "4/4", "6/8"}:
        raise GenerationError("ACE generation currently supports 2/4, 3/4, 4/4 and 6/8.")
    seed = request.get("seed", 0)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise GenerationError("Invalid generation seed.")
    model = registry.get("model_id")
    if not isinstance(model, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", model):
        raise GenerationError("No generation model is configured.")
    return {"request_id": job_id, "kind": "generate", "model_id": model,
            "prompt": prompt.strip(), "lyrics": lyrics, "instrumental": not lyrics.strip(),
            "duration_seconds": duration, "bpm": bpm, "time_signature": meter, "seed": seed}


class Tunnel:
    def __init__(self, registry, directory):
        self.registry, self.directory = registry, directory
        self.process = self.log = None
        self.url = None

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def open(self):
        self.close()
        alias = self.registry.get("ssh_alias", "emusician-cloud")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", alias):
            raise GenerationError("Invalid SSH host alias.")
        port = self.registry.get("remote_port", 18081)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise GenerationError("Invalid gateway port.")
        ssh = self.registry.get("ssh_executable", "C:/Windows/System32/OpenSSH/ssh.exe" if os.name == "nt" else "ssh")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            local_port = listener.getsockname()[1]
        self.log = (self.directory / "ssh.log").open("ab")
        if self.registry.get("start_service", True):
            starter = "compute_start.py" if self.registry.get("compute_protocol") == 2 else "gateway_start.py"
            remote_root = self.registry.get("remote_root", "/root/autodl-tmp/emusician")
            remote_python = self.registry.get("remote_python", "/root/miniconda3/bin/python")
            if any(not isinstance(value, str) or not value.startswith("/") or any(ord(c) < 32 for c in value)
                   for value in (remote_root, remote_python)):
                raise GenerationError("Remote root and Python must be absolute Linux paths.")
            remote_command = shlex.quote(remote_python) + " " + shlex.quote(remote_root.rstrip("/") + "/tools/" + starter)
            bootstrap = [ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15", alias,
                         remote_command]
            self.process = subprocess.Popen(bootstrap, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 35
            while self.process.poll() is None:
                if (self.directory / "cancel").exists():
                    raise Cancelled("Generation cancelled before service startup.")
                if time.monotonic() > deadline:
                    raise GenerationError("Cloud service startup timed out. Check the instance connection.")
                time.sleep(0.2)
            if self.process.returncode:
                raise GenerationError("Cannot start the generation service. Check the running instance and deployment.")
        args = [ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
                "-N", "-L", f"127.0.0.1:{local_port}:127.0.0.1:{port}", alias]
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.url = f"http://127.0.0.1:{local_port}"
        deadline = time.monotonic() + 22
        while time.monotonic() < deadline:
            if (self.directory / "cancel").exists():
                raise Cancelled("Generation cancelled before connection.")
            if self.process.poll() is not None:
                raise GenerationError("Cloud SSH connection failed. Check the instance and SSH key.")
            try:
                health = self.call("GET", "/health")
                compute = self.registry.get("compute_protocol") == 2
                if health.get("service") != ("emusician-compute" if compute else "emusician-generation") or health.get("protocol_version") != (2 if compute else 1):
                    raise GenerationError("The SSH endpoint is not a compatible generation service.")
                return health
            except NetworkError:
                time.sleep(0.2)
        raise GenerationError("The cloud generation service is unavailable. Start the instance and service.")

    def response(self, method, path, body=None, timeout=5):
        data = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data is not None else {})
        # The service is reachable only through our SSH tunnel; never use an HTTP proxy.
        try:
            return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise NetworkError("Cloud transport is temporarily unavailable.") from exc

    def call(self, method, path, body=None):
        try:
            with self.response(method, path, body) as response:
                try:
                    raw = response.read(MAX_JSON + 1)
                except OSError as exc:
                    raise NetworkError("Cloud response was interrupted.") from exc
            if len(raw) > MAX_JSON:
                raise GenerationError("Cloud response exceeds the size limit.")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise GenerationError("Invalid cloud response.")
            return value
        except urllib.error.HTTPError as exc:
            # Do not expose arbitrary remote HTML, paths or payloads in user-facing errors.
            raise GenerationError(f"Cloud request failed (HTTP {exc.code}).") from exc


def inspect_wav(path, metadata):
    peaks = [0.0] * 128
    energy = 0
    with wave.open(str(path), "rb") as reader:
        rate, channels, frames, width = reader.getframerate(), reader.getnchannels(), reader.getnframes(), reader.getsampwidth()
        if width != 2 or channels not in (1, 2) or not 16000 <= rate <= 96000 or not 0 < frames / rate <= 150:
            raise GenerationError("Generated audio must be bounded PCM16 mono/stereo WAV.")
        if metadata.get("sample_rate") != rate or metadata.get("channels") != channels:
            raise GenerationError("Generated audio format does not match its manifest.")
        actual = frames / rate
        declared = finite(metadata.get("duration_seconds"), 0.001, 150, "audio duration")
        if abs(actual - declared) > 1.1 / rate:
            raise GenerationError("Generated audio duration does not match its manifest.")
        offset = 0
        while offset < frames:
            raw = reader.readframes(min(8192, frames - offset))
            count = len(raw) // (channels * 2)
            if not count:
                raise GenerationError("Generated WAV is truncated.")
            samples = array("h", raw)
            if sys.byteorder != "little":
                samples.byteswap()
            for i, sample in enumerate(samples):
                bucket = min(127, (offset + i // channels) * 128 // frames)
                amp = abs(sample) / 32768.0
                if amp > peaks[bucket]:
                    peaks[bucket] = amp
                energy += sample * sample
            offset += count
    if energy == 0:
        raise GenerationError("The model returned silent audio. No candidate was published.")
    return {"path": "audio.wav", "sha256": metadata["sha256"], "duration_seconds": actual,
            "sample_rate": rate, "channels": channels}, peaks


def download(tunnel, job_id, result, directory, cancel):
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise GenerationError("Expected one generated audio artifact.")
    artifact = artifacts[0]
    if not isinstance(artifact, dict) or artifact.get("id") != "audio.wav":
        raise GenerationError("Unrecognized generated artifact.")
    size, checksum = artifact.get("bytes"), artifact.get("sha256")
    if type(size) is not int or not 44 < size <= MAX_BYTES or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise GenerationError("Invalid generated audio size or checksum.")
    model = result.get("model")
    params = result.get("parameters")
    if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"] or not isinstance(params, dict):
        raise GenerationError("Generation provenance is missing.")
    if (len(json.dumps(model, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 8192
            or len(json.dumps(params, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 32768):
        raise GenerationError("Generation provenance exceeds limits.")
    path = directory / "audio.wav.partial"
    digest, written = hashlib.sha256(), 0
    with tunnel.response("GET", f"/jobs/{job_id}/artifacts/audio.wav") as response, path.open("wb") as stream:
        while True:
            if cancel():
                raise Cancelled("Generation download cancelled.")
            try:
                block = response.read(256 * 1024)
            except OSError as exc:
                raise NetworkError("Cloud download was interrupted.") from exc
            if not block:
                break
            written += len(block)
            if written > size:
                raise GenerationError("Generated download exceeds declared size.")
            stream.write(block)
            digest.update(block)
    if written != size or digest.hexdigest() != checksum:
        raise GenerationError("Generated audio checksum or size verification failed.")
    audio, peaks = inspect_wav(path, artifact)
    os.replace(path, directory / "audio.wav")
    return audio, peaks


def run(request_path, registry=None, tunnel_factory=Tunnel):
    # Existing explicit registry/tests retain the original protocol. New DAW
    # requests use the separate compute configuration when it is installed.
    if registry is None:
        initial_request = read_json(Path(request_path))
        request_compute_root = Path(initial_request.get("compute_root") or compute_root())
        if (request_compute_root / "compute-registry.json").is_file():
            try:
                from .run_compute_generation import run as compute_run
            except ImportError:
                from run_compute_generation import run as compute_run
            return compute_run(request_path)
    request_path = Path(request_path).resolve()
    directory = request_path.parent
    request = read_json(request_path)
    registry = registry if registry is not None else read_json(ROOT / "registry.json")
    if registry.get("available") is not True:
        raise GenerationError("The generation runtime is not configured.")
    payload = build_payload(request, registry)
    job_id = payload["request_id"]
    cancel = lambda: (directory / "cancel").exists()
    progress = lambda phase, detail="": atomic_json(directory / "progress.json", {"phase": phase, "detail": detail})
    progress("connecting", "Connecting to generation service")
    tunnel = tunnel_factory(registry, directory)
    deadline = time.monotonic() + 3600
    try:
        tunnel.open()
        # Persist before POST: a lost response is retried with the same idempotency key.
        atomic_json(directory / "remote-request.json", payload)
        reconnects = 0
        submitted = False
        while time.monotonic() < deadline:
            if cancel():
                try:
                    response = tunnel.call("POST", f"/jobs/{job_id}/cancel", {})
                    remote_status = response.get("status", "unconfirmed")
                    atomic_json(directory / "cancellation.json", {"requested": True, "remote_status": remote_status,
                                "remote_cancel_confirmed": remote_status == "cancelled"})
                except Exception:
                    atomic_json(directory / "cancel-pending.json", {"job_id": job_id, "reason": "Cloud cancellation could not be confirmed."})
                    atomic_json(directory / "cancellation.json", {"requested": True, "remote_status": "unconfirmed", "remote_cancel_confirmed": False})
                raise Cancelled("Generation cancelled.")
            try:
                if not submitted:
                    state = tunnel.call("POST", "/jobs", payload)
                    submitted = True
                else:
                    state = tunnel.call("GET", f"/jobs/{job_id}")
                if state.get("job_id") != job_id:
                    raise GenerationError("Cloud returned a different generation job.")
                status = state.get("status")
                atomic_json(directory / "remote-state.json", state)
                if status in TERMINAL:
                    if status == "cancelled":
                        raise Cancelled("Generation cancelled by the cloud service.")
                    raise GenerationError(f"Cloud generation {status}. Inspect the saved job record for details.")
                if status == "ready":
                    progress("downloading", "Downloading and checking generated audio")
                    result = state.get("result")
                    if not isinstance(result, dict):
                        raise GenerationError("Ready job has no result.")
                    if result.get("model", {}).get("id") != registry["model_id"]:
                        raise GenerationError("Cloud returned a different generation model.")
                    audio, peaks = download(tunnel, job_id, result, directory, cancel)
                    if cancel():
                        raise Cancelled("Generation cancelled before publishing.")
                    output = {"schema_version": 1, "job_id": job_id, "result_id": job_id, "kind": "generate",
                              "audio": audio, "model": result["model"], "parameters": result["parameters"],
                              "source": request.get("source", {}), "waveform_peaks": peaks}
                    atomic_json(directory / "result.json", output)
                    progress("ready", "Ready to preview")
                    return output
                if status not in {"queued", "loading", "running", "postprocessing", "cancelling"}:
                    raise GenerationError("Unrecognized cloud task status.")
                progress(status)
                for _ in range(5):
                    if cancel():
                        break
                    time.sleep(0.2)
            except NetworkError:
                reconnects += 1
                if reconnects > 3:
                    raise GenerationError("Cloud connection was lost. The remote job ID is saved; do not start a duplicate task.")
                progress("reconnecting", "Reconnecting to the same generation job")
                tunnel.open()
        try:
            tunnel.call("POST", f"/jobs/{job_id}/cancel", {})
        except Exception:
            atomic_json(directory / "cancel-pending.json", {"job_id": job_id, "reason": "Timeout; cloud cancellation unconfirmed."})
        raise GenerationError("Generation exceeded the one-hour task limit.")
    finally:
        tunnel.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.request)
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, GenerationError) else "Cannot read or write local generation data. Check disk space and file permissions." if isinstance(exc, OSError) else f"Generation transport failed ({type(exc).__name__})."
        atomic_json(args.request.parent / "error.json", {"message": message, "cancelled": isinstance(exc, Cancelled)})
        return 2 if isinstance(exc, Cancelled) else 1


if __name__ == "__main__":
    raise SystemExit(main())
