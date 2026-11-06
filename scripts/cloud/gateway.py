"""Private, loopback-only generation queue. Run inside the pinned ACE environment.

The SSH tunnel is the transport boundary. No model-controlled paths or commands
are accepted. SQLite retains idempotency receipts across reconnects/restarts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MODEL_ID = "ace-step-1.5-xl-turbo"
TERMINAL = {"ready", "failed", "cancelled", "interrupted"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def validate_request(value):
    if not isinstance(value, dict):
        raise ValueError("Request must be an object.")
    allowed = {"request_id", "kind", "model_id", "prompt", "lyrics", "instrumental", "duration_seconds", "bpm", "time_signature", "seed"}
    if set(value) - allowed:
        raise ValueError("Unknown generation fields.")
    item = dict(value)
    if not isinstance(item.get("request_id"), str) or not ID_PATTERN.fullmatch(item["request_id"]):
        raise ValueError("Invalid request ID.")
    if item.get("kind") != "generate" or item.get("model_id") != MODEL_ID:
        raise ValueError("Unsupported generation capability.")
    for key, minimum, maximum in (("prompt", 1, 2000), ("lyrics", 0, 4096)):
        field = item.get(key, "")
        if not isinstance(field, str) or not minimum <= len(field.strip()) <= maximum:
            raise ValueError(f"Invalid {key} length.")
        item[key] = field.strip()
    if not isinstance(item.get("instrumental"), bool):
        raise ValueError("instrumental must be a boolean.")
    if item["instrumental"] and item["lyrics"]:
        raise ValueError("Instrumental generation cannot include lyrics.")
    for key, low, high in (("duration_seconds", 10, 120), ("bpm", 30, 300)):
        field = item.get(key)
        if isinstance(field, bool) or not isinstance(field, (int, float)) or not math.isfinite(field) or not low <= field <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
    if item.get("time_signature") not in ("2/4", "3/4", "4/4", "6/8"):
        raise ValueError("Unsupported time signature.")
    seed = item.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
        raise ValueError("Invalid seed.")
    return item


class Queue:
    def __init__(self, root, generator=None):
        self.root = Path(root).resolve()
        self.root.joinpath("state").mkdir(parents=True, exist_ok=True)
        self.root.joinpath("jobs", "generation").mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.generator = generator
        self.injected_generator = generator is not None
        self.thread = None
        self.db = sqlite3.connect(self.root / "state/generation.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL, error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL)")
        self.db.execute("UPDATE jobs SET status='interrupted', phase='interrupted', error='Cloud service restarted during this task.', updated=? WHERE status NOT IN ('ready','failed','cancelled','interrupted')", (time.time(),))
        self.db.commit()

    def capability(self):
        path = self.root / "manifests/ace-runtime.json"
        ready = False
        model = {"id": MODEL_ID}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            ready = manifest.get("ready") is True
            model.update(manifest.get("model", {}))
        except (OSError, ValueError):
            pass
        return {"protocol_version": 1, "providers": [{"kind": "generate", "model_id": MODEL_ID, "available": ready, "model": model,
                "min_duration_seconds": 10, "max_duration_seconds": 120, "time_signatures": ["2/4", "3/4", "4/4", "6/8"],
                "lyrics": True, "instrumental": True, "audio_format": "wav", "batch_size": 1}], "max_parallel_jobs": 1, "max_queued_jobs": 16}

    def get(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return {"job_id": row["id"], "status": row["status"], "phase": row["phase"], "progress": None,
                "error": row["error"], "result": json.loads(row["result"]) if row["result"] else None,
                "created_at": row["created"], "updated_at": row["updated"]}

    def submit(self, value):
        request = validate_request(value)
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.lock:
            old = self.db.execute("SELECT request FROM jobs WHERE id=?", (request["request_id"],)).fetchone()
            if old is not None:
                if old["request"] != canonical:
                    return 409, {"error": "Request ID already has different parameters."}
                return 200, self.get(request["request_id"])
            if not self.capability()["providers"][0]["available"] and not self.injected_generator:
                return 503, {"error": "Generation model is not ready."}
            count = self.db.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted')").fetchone()[0]
            if count >= 16:
                return 429, {"error": "Generation queue is full."}
            if shutil.disk_usage(self.root).free < 512 * 1024 * 1024:
                return 503, {"error": "Cloud data disk has insufficient free space."}
            now = time.time()
            self.db.execute("INSERT INTO jobs VALUES (?,?, 'queued','queued', NULL,NULL,?,?)", (request["request_id"], canonical, now, now))
            self.db.commit()
        self.wake.set()
        return 202, self.get(request["request_id"])

    def update(self, job_id, status, error=None, result=None):
        with self.lock:
            current = self.get(job_id)
            if current["status"] == "cancelling" and status not in ("cancelled", "interrupted"):
                return
            self.db.execute("UPDATE jobs SET status=?,phase=?,error=?,result=?,updated=? WHERE id=?", (status, status, error,
                json.dumps(result, ensure_ascii=False) if result is not None else None, time.time(), job_id))
            self.db.commit()

    def cancel(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if job is None:
                return None
            if job["status"] == "queued":
                self.update(job_id, "cancelled")
            elif job["status"] not in TERMINAL:
                self.update(job_id, "cancelling")
        return self.get(job_id)

    def _run(self):
        while not self.stop.is_set():
            with self.lock:
                row = self.db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    self.update(row["id"], "loading")
            if row is None:
                self.wake.wait(1)
                self.wake.clear()
                continue
            job_id = row["id"]
            request = json.loads(row["request"])
            directory = self.root / "jobs/generation" / job_id
            cancelled = lambda: self.get(job_id)["status"] == "cancelling" or self.stop.is_set()
            phase = lambda value: self.update(job_id, value)
            try:
                directory.mkdir(parents=True, exist_ok=True)
                directory.joinpath("request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                if self.generator is None:
                    from ace_worker import AceGenerator
                    self.generator = AceGenerator(self.root)
                result = self.generator(request, directory, phase, cancelled)
                if cancelled():
                    self.update(job_id, "cancelled")
                else:
                    # Never expose an arbitrary output path from a model.
                    audio = directory / "audio.wav"
                    artifact = result["artifacts"][0]
                    if artifact["id"] != "audio.wav" or not audio.is_file() or audio.is_symlink() or artifact["sha256"] != hashlib.sha256(audio.read_bytes()).hexdigest():
                        raise RuntimeError("Generated audio failed publication checks.")
                    directory.joinpath("result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    # Cancellation can arrive during hash/write publication.
                    # Resolve its final state under the same lock as cancel().
                    with self.lock:
                        if cancelled():
                            self.update(job_id, "cancelled")
                        else:
                            self.update(job_id, "ready", result=result)
            except Exception as exc:
                try:
                    directory.joinpath("error.log").write_text(traceback.format_exc(), encoding="utf-8")
                except OSError:
                    pass  # An unavailable output directory must not kill the queue.
                with self.lock:
                    if cancelled():
                        self.update(job_id, "cancelled")
                    else:
                        self.update(job_id, "failed", error=str(exc)[:1000])

    def start(self):
        self.thread = threading.Thread(target=self._run, name="single-gpu-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)


def handler_for(queue):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EMusicianGeneration/1"

        def log_message(self, fmt, *args):
            # Paths contain only generated IDs; never log prompts, headers or credentials.
            print(f"http {self.command} {urlsplit(self.path).path[:180]} {fmt % args}", flush=True)

        def respond(self, code, value):
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def route(self):
            self.connection.settimeout(20)
            path = urlsplit(self.path).path
            parts = path.strip("/").split("/")
            if self.command == "GET" and path == "/health":
                return self.respond(200, {"status": "ok", "protocol_version": 1, "service": "emusician-generation"})
            if self.command == "GET" and path == "/capabilities":
                return self.respond(200, queue.capability())
            if self.command == "POST" and path == "/jobs":
                if self.headers.get("Transfer-Encoding"):
                    return self.respond(400, {"error": "Chunked requests are not supported."})
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32768:
                        return self.respond(413, {"error": "Invalid request size."})
                    value = json.loads(self.rfile.read(size))
                    code, result = queue.submit(value)
                except (ValueError, TypeError, UnicodeError) as exc:
                    return self.respond(400, {"error": str(exc)[:250]})
                return self.respond(code, result)
            if len(parts) >= 2 and parts[0] == "jobs" and ID_PATTERN.fullmatch(parts[1]):
                job = queue.get(parts[1])
                if job is None:
                    return self.respond(404, {"error": "Unknown job."})
                if len(parts) == 2 and self.command == "GET":
                    return self.respond(200, job)
                if len(parts) == 3 and parts[2] == "cancel" and self.command == "POST":
                    return self.respond(200, queue.cancel(parts[1]))
                if len(parts) == 4 and parts[2:] == ["artifacts", "audio.wav"] and self.command == "GET":
                    if job["status"] != "ready":
                        return self.respond(409, {"error": "Audio is not ready."})
                    audio = queue.root / "jobs/generation" / parts[1] / "audio.wav"
                    if not audio.is_file() or audio.is_symlink():
                        return self.respond(410, {"error": "Audio is missing."})
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(audio.stat().st_size))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    with audio.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            self.wfile.write(chunk)
                    return
            self.respond(404, {"error": "Unknown endpoint."})

        def do_GET(self):
            self.route()

        def do_POST(self):
            self.route()
    return Handler


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/root/autodl-tmp/emusician")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.joinpath("state").mkdir(parents=True, exist_ok=True)
    # A second direct launch must not reset an active service's persisted jobs.
    with root.joinpath("state/gateway-service.lock").open("a") as service_lock:
        fcntl.flock(service_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue = Queue(root)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(queue))
        queue.start()
        print(f"Generation gateway listening on 127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        finally:
            queue.close()
            server.server_close()


if __name__ == "__main__":
    main()
