"""Recorded, deterministic tests; optional real offline DAW integration."""
from pathlib import Path
import argparse
import sys
from dev import Recorder

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe",type=Path)
    args = parser.parse_args()
    recorder = Recorder("agent-check","Python","Kimi companion deterministic tests; no live model calls or physical audio")
    recorder.execute([sys.executable,"-m","unittest","discover","-s","tests","-p","test_music_agent*.py","-v"])
    if args.exe:
        recorder.execute([sys.executable,"tests/MusicAgentIntegration.py","--exe",str(args.exe.resolve())])
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
