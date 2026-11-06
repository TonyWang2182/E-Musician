"""Bounded metadata audit; never persist prompts, notes, credentials or reasoning."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from .secrets import redact

def data_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "E-musician" / "agent"

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode("utf-8")).hexdigest()

class Audit:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "audit.jsonl"
        self.lock = threading.Lock()

    def write(self, event, **values):
        allowed = {"task_id", "plan_id", "project_id", "revision", "command_count",
                   "commands_sha256", "status", "calls", "prompt_tokens", "completion_tokens",
                   "model", "code", "duration_ms", "job_id", "result_id", "result_hash", "request_sha256"}
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event}
        record.update({k:v for k,v in values.items() if k in allowed})
        line = redact(json.dumps(record, ensure_ascii=False, allow_nan=False))
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 5 * 1024 * 1024:
                self.path.replace(self.path.with_suffix(".previous.jsonl"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
