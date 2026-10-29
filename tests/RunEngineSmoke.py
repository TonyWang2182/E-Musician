"""Run a fresh app process and require artifacts, so a forwarded launch cannot pass."""
from pathlib import Path
import json
import math
import subprocess
import sys
import uuid


def main() -> int:
    executable, root = Path(sys.argv[1]), Path(sys.argv[2])
    directory = root / uuid.uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=False)
    fixtures = Path(__file__).resolve().parent / "fixtures" / "audio"
    result = subprocess.run([str(executable), "--smoke-test", str(directory), str(fixtures), "--offline"], timeout=240)
    if result.returncode:
        failure = directory / "failure.txt"
        if failure.exists():
            print(failure.read_text(encoding="utf-8"))
        raise RuntimeError(f"Engine smoke returned {result.returncode}; artifacts: {directory}")
    report = json.loads((directory / "engine-report.json").read_text(encoding="utf-8-sig"))
    if report["status"] != "passed" or report["samples"] != 96000 or report["channels"] != 2:
        raise RuntimeError(f"Unexpected engine report: {report}")
    ratio = report["rms_minus12"] / report["rms_minus6"]
    if not math.isfinite(ratio) or abs(ratio - 10 ** (-6 / 20)) > 0.02:
        raise RuntimeError(f"Unexpected rendered gain ratio: {ratio}")
    transport = json.loads((directory / "transport-report.json").read_text(encoding="utf-8-sig"))
    if transport["status"] not in ("passed", "skipped"):
        raise RuntimeError(f"Unexpected transport report: {transport}")
    if report["device_available"] and transport["status"] != "passed":
        raise RuntimeError("An available output device must pass transport checks")
    project = json.loads((directory / "project-report.json").read_text(encoding="utf-8-sig"))
    if project["status"] != "passed":
        raise RuntimeError(f"MP3/project checks failed: {project}")
    clips = json.loads((directory / "clip-report.json").read_text(encoding="utf-8-sig"))
    if clips["status"] != "passed":
        raise RuntimeError(f"Clip editing checks failed: {clips}")
    daw = json.loads((directory / "daw-report.json").read_text(encoding="utf-8-sig"))
    storage = json.loads((directory / "storage-v3-report.json").read_text(encoding="utf-8-sig"))
    production = json.loads((directory / "production-smoke.json").read_text(encoding="utf-8-sig"))
    if production.get("ok") is not True:
        raise RuntimeError(f"Recording, routing and automation checks failed: {production}")
    if daw["status"] != "passed" or storage["status"] != "passed":
        raise RuntimeError(f"DAW/schema4 checks failed: {daw}, {storage}")
    arrangement = json.loads((directory / "arrangement-report.json").read_text(encoding="utf-8-sig"))
    if arrangement["status"] != "passed":
        raise RuntimeError(f"Arrangement view checks failed: {arrangement}")
    for size in ("1280x800", "1000x650"):
        screenshot = directory / f"ui-{size}.png"
        if screenshot.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(f"Missing or invalid UI capture: {screenshot}")
    (root / "latest.json").write_text(json.dumps({"directory": str(directory), "report": report, "transport": transport, "project": project, "arrangement": arrangement, "clips": clips, "daw": daw, "storage": storage, "production":production}, indent=2), encoding="utf-8")
    print(f"Engine render, MP3, project, arrangement and native captures passed; transport {transport['status']}: {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
