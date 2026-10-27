"""Verify Windows JSONL stdout isolation without loading third-party plugins.

python tests/ControlOutputSmoke.py --exe build/bin/Release/E-musician.exe

The application receives an explicit test-only CLI flag. Both the parent and
its owned child write diagnostic sentinels through CRT and Win32 stdout. Every
protocol response must remain valid JSON and preserve request order.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError, MAX_LINE_BYTES  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_strict_client() -> None:
    for bad_line in (b"initializing UJAM Lib" + b"x" * 4096 + b"\n", b"\xffnative log\n", b"\n"):
        # Exercise the real reader on an in-memory stream. It must report the
        # corrupt frame, not skip it and return the later valid response.
        client = Client.__new__(Client)
        client.closed = threading.Event()
        client.responses = queue.Queue(maxsize=32)
        client.process = SimpleNamespace(stdout=io.BytesIO(bad_line + b'{"status":"completed"}\n'))
        client._read()
        error = client.responses.get_nowait()
        require(isinstance(error, ControlError), "client accepted a non-JSON protocol line")
        require("raw_prefix=" in str(error) and repr(bad_line[:160]) in str(error),
                "invalid response error omitted its bounded escaped byte prefix")
        require(len(str(error)) < 1000, "invalid response error exposed unbounded output")
        require(client.responses.empty(), "client skipped corrupt output and consumed a later reply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    require(os.name == "nt", "ControlOutputSmoke requires Windows")
    require(args.exe.is_file() and 0 < args.timeout <= 60, "existing --exe and timeout 0..60 required")
    directory = ROOT / "build/control-output-smoke" / str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    executable = args.exe.resolve()
    report: dict = {"passed": False, "executable": str(executable),
                   "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                   "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "checks": [], "workspace": str(directory)}
    started = time.monotonic()
    stdout = stderr = b""
    try:
        check_strict_client()
        report["checks"].append("strict client rejects bad UTF-8, plugin text and blank lines with bounded evidence")
        commands = ["get_capabilities", "get_snapshot", "get_jobs"] * 8
        payload = b"".join(json.dumps({"command": command}).encode("utf-8") + b"\n" for command in commands)
        process = subprocess.Popen([str(executable), "--control-stdio", "--control-output-probe"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            stdout, stderr = process.communicate(payload, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.kill()  # Only this fresh test-owned application process.
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError("stdout isolation probe timed out")
        report["exit_code"] = process.returncode
        require(process.returncode == 0, f"probe application exited {process.returncode}")
        require(len(stdout) <= 4 * 1024 * 1024 and len(stderr) <= 1024 * 1024, "unexpectedly large probe output")
        lines = stdout.splitlines()
        require(len(lines) == len(commands), f"expected {len(commands)} JSONL replies, got {len(lines)}")
        for index, (line, command) in enumerate(zip(lines, commands)):
            require(len(line) <= MAX_LINE_BYTES, "oversized protocol reply")
            response = json.loads(line.decode("utf-8"))
            require(isinstance(response, dict) and response.get("status") == "completed", f"reply {index} failed")
            result = response.get("result") or {}
            key = {"get_capabilities": "protocol_version", "get_snapshot": "project_id", "get_jobs": "jobs"}[command]
            require(key in result, f"reply {index} was lost or reordered")
            if command == "get_snapshot":
                require(not result.get("playing") and not result.get("tracks"), "probe changed or started the empty project")
        report["checks"].append("24 ordered JSONL replies and clean EOF shutdown")
        sentinels = [f"CONTROL_OUTPUT_PROBE_{scope}_{method}".encode("ascii")
                     for scope in ("PARENT", "CHILD") for method in ("PRINTF", "COUT", "CRT", "WIN32")]
        sentinels.append(b"CONTROL_OUTPUT_PROBE_PROTOCOL_NONINHERIT")
        for sentinel in sentinels:
            require(stderr.count(sentinel) == 1, f"diagnostic sentinel missing or repeated: {sentinel!r}")
            require(sentinel not in stdout, f"diagnostic sentinel contaminated protocol stdout: {sentinel!r}")
        report["checks"].append("printf, cout, CRT fd 1 and Win32 stdout route to stderr in parent and inherited child")
        report["checks"].append("dedicated protocol handle has HANDLE_FLAG_INHERIT cleared")
        report["passed"] = True
    except (AssertionError, OSError, ValueError, queue.Empty, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    finally:
        (directory / "stdout.bin").write_bytes(stdout)
        (directory / "stderr.bin").write_bytes(stderr)
        report["elapsed_seconds"] = time.monotonic() - started
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
