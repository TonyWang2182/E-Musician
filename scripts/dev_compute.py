"""Recorded build/test/deployment commands for the separate 0.13 candidate."""
import argparse
import os
from pathlib import Path
import sys
from dev import Recorder, configure_console_output

BUILD = "E:/emusician-analysis-build"
OUTPUT = "E:/emusician-analysis-build/bin-0.13.0"
PYTHON_AUDIO = "E:/MusicAgent&DAW/analysis/runtimes/chords-py310/Scripts/python.exe"

def main():
    configure_console_output()
    temporary = Path(__file__).resolve().parents[1] / "build" / "compute-temp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temporary)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["configure", "build", "test", "transport-tests", "agent-tests", "command"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    record = Recorder("hybrid-compute-" + args.action, "Release/0.13.0", "Unified cloud task pipeline; automatic checks do not establish physical audio or musical accuracy acceptance")
    if args.action in ("configure", "build"):
        if args.action == "configure":
            record.execute(["cmake", "--preset", "windows-msvc", "-S", "E:/emusician-analysis-source", "-B", BUILD,
                "-DEMUSICIAN_RUNTIME_OUTPUT_ROOT=" + OUTPUT])
        else:
            cache = Path(BUILD) / "CMakeCache.txt"
            if "EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH=" + OUTPUT not in cache.read_text(encoding="utf-8"):
                record.preflight_failure("Configure the separate 0.13.0 output before building.")
                return 2
            record.execute(["cmake", "--build", BUILD, "--config", "Release", "--parallel", "1", "--", "/p:UseMultiToolTask=true", "/p:CL_MPCount=1", "/p:EnforceProcessCountAcrossBuilds=true"])
    elif args.action == "test":
        record.execute(["ctest", "--test-dir", BUILD, "-C", "Release", "--output-on-failure"])
    elif args.action == "transport-tests":
        record.execute([PYTHON_AUDIO, "-m", "unittest", "discover", "-s", "tests", "-p", "test_compute_transport.py", "-v"])
        record.execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_cloud_generation_transport.py", "-v"])
    elif args.action == "agent-tests":
        record.execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_music_agent*.py", "-v"])
    else:
        if not args.arguments:
            parser.error("command requires an executable and arguments")
        record.execute(args.arguments)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
