"""Recorded build/test entry point for the separate cloud-generation candidate."""
import argparse
from pathlib import Path
import sys
from dev import Recorder, configure_console_output

ROOT = Path(__file__).resolve().parents[1]
BUILD = "E:/emusician-analysis-build"
EXE = "E:/emusician-analysis-build/bin-0.12.1/Release/E-musician.exe"


def main():
    configure_console_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["configure", "build", "test", "python-tests", "e2e"])
    args = parser.parse_args()
    recorder = Recorder("cloud-generation-" + args.action, "Release/Python", "0.12.1 generation/analysis stability; serial build for limited local memory; no physical audio acceptance inferred")
    if args.action == "configure":
        recorder.execute(["cmake", "--preset", "windows-msvc", "-S", "E:/emusician-analysis-source", "-B", BUILD,
                          "-DEMUSICIAN_RUNTIME_OUTPUT_ROOT=E:/emusician-analysis-build/bin-0.12.1"])
    elif args.action == "build":
        cache = Path(BUILD) / "CMakeCache.txt"
        expected = "EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH=E:/emusician-analysis-build/bin-0.12.1"
        if not cache.is_file() or expected not in cache.read_text(encoding="utf-8"):
            recorder.execute(["cmake", "--preset", "windows-msvc", "-S", "E:/emusician-analysis-source", "-B", BUILD,
                              "-DEMUSICIAN_RUNTIME_OUTPUT_ROOT=E:/emusician-analysis-build/bin-0.12.1"])
        recorder.execute(["cmake", "--build", BUILD, "--config", "Release", "--parallel", "1", "--",
                          "/p:UseMultiToolTask=true", "/p:CL_MPCount=1", "/p:EnforceProcessCountAcrossBuilds=true"])
    elif args.action == "test":
        recorder.execute(["ctest", "--test-dir", BUILD, "-C", "Release", "--output-on-failure"])
    elif args.action == "python-tests":
        recorder.execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_cloud_generation*.py", "-v"])
        recorder.execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_music_agent*.py", "-v"])
    else:
        recorder.execute([sys.executable, str(ROOT / "tests/CloudGenerationEndToEnd.py"), "--exe", EXE])


if __name__ == "__main__":
    main()
