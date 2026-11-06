"""Bounded desktop transport for compute protocol 2; never runs in the audio thread."""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import urllib.error
from urllib.parse import urlsplit

try:
    from .run_generation import Tunnel as LegacyTunnel, GenerationError, NetworkError, Cancelled, atomic_json
except ImportError:
    from run_generation import Tunnel as LegacyTunnel, GenerationError, NetworkError, Cancelled, atomic_json

ROOT = Path(os.environ.get("EMUSICIAN_COMPUTE_ROOT", "E:/MusicAgent&DAW/cloud-inference"))
MAX_JSON = 16 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 1536 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
ARTIFACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
TERMINAL = {"ready", "failed", "cancelled", "interrupted"}


def read_json(path, limit=MAX_JSON):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise GenerationError("Missing or oversized compute data.")
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    if not isinstance(value, dict):
        raise GenerationError("Compute data must be an object.")
    return value


def registry(root=None):
    value = read_json(Path(root or ROOT) / "compute-registry.json", 256 * 1024)
    if value.get("schema_version") != 1 or value.get("available") is not True:
        raise GenerationError("Cloud compute is not configured. Check AI Compute settings.")
    return {**value, "compute_protocol": 2, "remote_port": value.get("remote_port", 18082)}


def checked_number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise GenerationError(f"Invalid {name}.")
    return value


def check_cancel(cancel):
    if cancel():
        raise Cancelled("Task cancelled; no project changes were made.")


def digest(path, cancel=lambda: False):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancel(cancel)
            result.update(block)
    return result.hexdigest()


class Tunnel(LegacyTunnel):
    def __init__(self, config, directory):
        super().__init__({**config, "compute_protocol": 2, "remote_port": config.get("remote_port", 18082)}, directory)

    def call(self, method, path, body=None):
        try:
            with self.response(method, path, body, timeout=10) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise GenerationError("Cloud result exceeds the 16 MiB limit.")
            value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite result")))
            if not isinstance(value, dict):
                raise GenerationError("Invalid compute response.")
            return value
        except urllib.error.HTTPError as exc:
            raise GenerationError(f"Cloud request failed (HTTP {exc.code}); inspect the task record.") from exc
        except (http.client.HTTPException, OSError) as exc:
            raise NetworkError("Cloud response was interrupted.") from exc

    def upload(self, path, sha, cancel, progress):
        if not HASH.fullmatch(sha):
            raise GenerationError("Invalid asset digest.")
        try:
            with self.response("HEAD", f"/assets/{sha}"):
                return
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise GenerationError(f"Cloud asset check failed (HTTP {exc.code}).") from exc
        size = Path(path).stat().st_size
        if not 0 < size <= MAX_FILE:
            raise GenerationError("Frozen audio exceeds the upload limit.")
        endpoint = urlsplit(self.url)
        if endpoint.hostname != "127.0.0.1" or endpoint.scheme != "http":
            raise GenerationError("Compute uploads require the private SSH tunnel.")
        connection = http.client.HTTPConnection("127.0.0.1", endpoint.port, timeout=20)
        try:
            connection.putrequest("PUT", f"/assets/{sha}")
            connection.putheader("Content-Type", "audio/wav")
            connection.putheader("Content-Length", str(size))
            connection.endheaders()
            sent = 0
            with Path(path).open("rb") as stream:
                for block in iter(lambda: stream.read(256 * 1024), b""):
                    check_cancel(cancel)
                    connection.send(block)
                    sent += len(block)
                    progress("uploading", sent / size)
            response = connection.getresponse()
            raw = response.read(65537)
            if response.status not in (200, 201):
                raise GenerationError(f"Cloud upload failed (HTTP {response.status}).")
            if len(raw) > 65536 or json.loads(raw).get("sha256") != sha:
                raise GenerationError("Cloud upload receipt does not match this audio.")
        except (OSError, http.client.HTTPException) as exc:
            raise NetworkError("Audio upload was interrupted.") from exc
        finally:
            connection.close()


def select_model(config, kind, requested=""):
    if not isinstance(requested, str):
        raise GenerationError("Invalid model selection.")
    choices = [p for p in config.get("providers", []) if isinstance(p, dict) and p.get("kind") == kind and p.get("available") is True]
    if requested:
        chosen = next((p for p in choices if p.get("model_id") == requested), None)
    else:
        default = config.get("defaults", {}).get(kind)
        chosen = next((p for p in choices if p.get("model_id") == default), None) if default else None
        chosen = chosen or next((p for p in choices if p.get("default") is True), None)
        chosen = chosen or (choices[0] if len(choices) == 1 else None)
    if chosen is None:
        raise GenerationError("The selected cloud model is unavailable for this task; no model was substituted.")
    return chosen["model_id"]


def cancel_remote(tunnel, job_id, directory):
    status = "unconfirmed"
    try:
        status = tunnel.call("POST", f"/jobs/{job_id}/cancel", {}).get("status", status)
    except Exception:
        pass
    atomic_json(directory / "cancellation.json", {"requested": True, "remote_status": status,
        "remote_cancel_confirmed": status == "cancelled", "job_id": job_id})


def task(tunnel, payload, directory, cancel, progress, input_path=None, deadline_seconds=3600, poll_seconds=.5):
    job_id = payload.get("request_id")
    if not isinstance(job_id, str) or not ID.fullmatch(job_id):
        raise GenerationError("Invalid task ID.")
    atomic_json(directory / "remote-request.json", payload)
    submitted = False
    uploaded = input_path is None
    deadline = time.monotonic() + deadline_seconds
    failures = 0
    while time.monotonic() < deadline:
        if cancel():
            cancel_remote(tunnel, job_id, directory)
            check_cancel(cancel)
        try:
            if not uploaded:
                tunnel.upload(input_path, payload["input"]["sha256"], cancel, progress)
                uploaded = True
            if not submitted:
                state = tunnel.call("POST", "/jobs", payload)
                submitted = True
            else:
                state = tunnel.call("GET", f"/jobs/{job_id}")
            if state.get("job_id") != job_id:
                raise GenerationError("Cloud returned a different task identity.")
            atomic_json(directory / "remote-state.json", state)
            status = state.get("status")
            if status in TERMINAL:
                if status != "ready":
                    if status == "cancelled":
                        raise Cancelled("Cloud task cancelled.")
                    raise GenerationError(f"Cloud task {status}; see the saved task record.")
                result = state.get("result")
                if not isinstance(result, dict) or result.get("schema_version") != 2 or result.get("kind") != payload["kind"] or result.get("model", {}).get("id") != payload["model_id"]:
                    raise GenerationError("Cloud result does not match the requested model and task.")
                if payload.get("input") and result.get("input", {}).get("sha256") != payload["input"]["sha256"]:
                    raise GenerationError("Cloud result does not match the submitted audio identity.")
                if result.get("parameters", {}) != payload.get("parameters", {}):
                    raise GenerationError("Cloud result conditioning differs from the submitted parameters.")
                return result
            if status not in {"queued", "loading", "running", "postprocessing", "cancelling"}:
                raise GenerationError("Unrecognized compute task state.")
            progress(status, None)
            time.sleep(poll_seconds)
        except NetworkError:
            failures += 1
            if failures > 5:
                raise GenerationError("Cloud connection lost. The same task ID is retained for reconnection; do not submit a duplicate.")
            progress("reconnecting", None)
            tunnel.open()
    cancel_remote(tunnel, job_id, directory)
    raise GenerationError("Compute task exceeded its one-hour limit.")


def download_artifacts(tunnel, job_id, result, directory, cancel, progress):
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64:
        raise GenerationError("Invalid result artifact count.")
    seen, total = set(), 0
    for item in artifacts:
        if not isinstance(item, dict):
            raise GenerationError("Invalid result artifact.")
        name, size, sha = item.get("id"), item.get("bytes"), item.get("sha256")
        if not isinstance(name, str) or not ARTIFACT.fullmatch(name) or ".." in name or name in seen or name in {"request.json", "result.json", "progress.json", "input.wav", "cancel"}:
            raise GenerationError("Unsafe or duplicate artifact ID.")
        if type(size) is not int or not 0 < size <= MAX_FILE or not isinstance(sha, str) or not HASH.fullmatch(sha):
            raise GenerationError("Invalid result artifact size or digest.")
        seen.add(name)
        total += size
    if total > MAX_TOTAL or shutil.disk_usage(directory).free < total + 512 * 1024 * 1024:
        raise GenerationError("Not enough local space for verified compute results.")
    for index, item in enumerate(artifacts):
        check_cancel(cancel)
        destination = directory / item["id"]
        if destination.is_symlink():
            raise GenerationError("Artifact destination must not be a symbolic link.")
        if destination.exists():
            if destination.stat().st_size == item["bytes"] and digest(destination, cancel) == item["sha256"]:
                continue
            raise GenerationError("An existing artifact has different content; it was preserved.")
        temporary = destination.with_name(destination.name + ".download")
        if temporary.is_symlink():
            raise GenerationError("Unsafe download staging path.")
        attempts = 0
        while True:
            try:
                with tunnel.response("GET", f"/jobs/{job_id}/artifacts/{item['id']}", timeout=20) as response, temporary.open("wb") as output:
                    declared = response.headers.get("Content-Length")
                    if declared is None or int(declared) != item["bytes"]:
                        raise GenerationError("Download length does not match its manifest.")
                    count, checksum = 0, hashlib.sha256()
                    while True:
                        check_cancel(cancel)
                        try:
                            block = response.read(min(256 * 1024, item["bytes"] - count + 1))
                        except OSError as exc:
                            raise NetworkError("Artifact body interrupted.") from exc
                        if not block:
                            break
                        count += len(block)
                        if count > item["bytes"]:
                            raise GenerationError("Download exceeds its declared size.")
                        checksum.update(block)
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                if count != item["bytes"]:
                    raise NetworkError("Artifact body ended before its declared length.")
                if checksum.hexdigest() != item["sha256"]:
                    raise GenerationError("Downloaded artifact failed SHA-256 verification.")
                os.replace(temporary, destination)
                break
            except (NetworkError, http.client.HTTPException):
                attempts += 1
                if attempts > 3:
                    raise GenerationError("Result download interrupted; the cloud result and task ID are retained.")
                progress("reconnecting", None)
                tunnel.open()
            finally:
                if temporary.exists() and not temporary.is_symlink():
                    temporary.unlink()
        progress("downloading", (index + 1) / len(artifacts))
    return {item["id"]: item for item in artifacts}
