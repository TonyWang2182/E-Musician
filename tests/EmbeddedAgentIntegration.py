"""Recorded native sidebar smoke wrapper; no desktop automation or model requests.

Native contract: --agent-sidebar-smoke OUTPUT --offline writes a fresh
agent-sidebar-report.json. WebView2 is verified by native JS/DOM probes; ordinary
JUCE component snapshots may omit its child HWND and are not visual proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dev import Recorder

REQUIRED_CHECKS = {"selection_context", "hide_show", "helper_restart", "same_project",
                   "single_engine", "no_paid_provider", "native_page_loaded", "key_focus"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def protected_files():
    directories = [Path("E:/E-musician/test-projects")]
    if os.environ.get("APPDATA"):
        directories.append(Path(os.environ["APPDATA"]) / "E-musician")
    result = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if "agent" in path.relative_to(directory).parts:
                continue  # Session/browser caches legitimately change during this test.
            if path.is_file() and path.suffix.lower() in {".xml", ".emproj", ".json", ".mid"}:
                result[str(path)] = digest(path)
    return result


def validate_report(path):
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise RuntimeError("Missing or oversized native sidebar report.")
    def reject_number(_): raise ValueError("Non-finite JSON")
    def finite_number(text):
        value = float(text)
        if not math.isfinite(value): raise ValueError("Non-finite JSON")
        return value
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    data = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_number,
                      parse_float=finite_number, object_pairs_hook=unique)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("status") != "passed":
        raise RuntimeError("Native sidebar smoke did not report success.")
    if data.get("physical_audio") is not False or data.get("provider_mode") not in {"synthetic", "no_model_calls"}:
        raise RuntimeError("Native test did not confirm offline audio and no live provider calls.")
    entries = data.get("checks")
    if not isinstance(entries, list):
        raise RuntimeError("Native test omitted named checks.")
    checks = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or type(entry.get("passed")) is not bool or entry["name"] in checks:
            raise RuntimeError("Invalid or duplicate native check record.")
        checks[entry["name"]] = entry["passed"]
    if REQUIRED_CHECKS - checks.keys() or not all(checks.values()):
        raise RuntimeError("Native sidebar checks are missing or failed.")
    timings = data.get("timings_ms", {})
    if not isinstance(timings, dict) or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in timings.values()):
        raise RuntimeError("Native timing measurements are invalid.")
    # Optional screenshots are useful for the surrounding JUCE layout only.
    for name in data.get("artifacts", []):
        if not isinstance(name, str): raise RuntimeError("Invalid native artifact entry.")
        artifact = (path.parent / name).resolve()
        if not artifact.is_relative_to(path.parent.resolve()) or not artifact.is_file():
            raise RuntimeError("Native artifact path is invalid or missing.")
        if artifact.suffix.lower() == ".png" and artifact.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Native PNG artifact is invalid.")
    return data


def run(executable, output_root, timeout):
    directory = output_root.resolve() / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=False)
    before = protected_files()
    result = {"mode": "native-sidebar-offline", "status": "running", "physical_audio": False,
              "exe_sha256": digest(executable), "protected_file_count": len(before),
              "webview_visual_acceptance": "not asserted by JUCE component snapshots"}
    output = directory / "native-output.log"
    command = [str(executable.resolve()), "--agent-sidebar-smoke", str(directory / "native"), "--offline"]
    started = time.monotonic()
    try:
        with output.open("wb") as stream:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, creationflags=flags)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Only this synthetic test's owned native process tree is stopped.
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                else:
                    process.kill()
                process.wait(timeout=10)
                raise RuntimeError("Native sidebar smoke exceeded its timeout.") from None
        result["exit_code"] = code
        if code != 0:
            raise RuntimeError("Native sidebar process returned a failure exit code; inspect local artifacts.")
        report = directory / "native" / "agent-sidebar-report.json"
        native = validate_report(report)
        result.update(status="passed", checks=native["checks"], native_report_sha256=digest(report),
                      timings_ms=native.get("timings_ms", {}))
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error)[:500])
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["protected_files_unchanged"] = before == protected_files()
        if not result["protected_files_unchanged"]:
            result.update(status="failed", error="Protected user files changed during the test.")
        (directory / "wrapper-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "directory": str(directory),
                      "protected_files_unchanged": result["protected_files_unchanged"]}))
    return 0 if result["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / "build" / "embedded-agent-integration")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--recorded", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.exe.is_file() or not 30 <= args.timeout <= 600:
        parser.error("Provide an existing executable and a 30–600 second timeout.")
    if not args.recorded:
        return Recorder("embedded-agent-integration", "Release + Python", "Native WebView2/Agent lifecycle smoke; offline audio, no provider calls").execute(
            [sys.executable, __file__, "--recorded", "--exe", str(args.exe),
             "--output-root", str(args.output_root), "--timeout", str(args.timeout)]).returncode
    return run(args.exe, args.output_root, args.timeout)

if __name__ == "__main__":
    raise SystemExit(main())
