"""Explicit local analysis setup with recorded commands. Never runs from audio callbacks.

python scripts/setup_analysis.py --root C:/E-musician-data/analysis
Use --register-only to probe/register already installed environments.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.dev import Recorder
from scripts.runtime_paths import analysis_root

NAMES = {"separate": "separation-py310", "transcribe": "transcription-py310", "chords": "chords-py310", "beats": "beats-py310"}
COMMON = ["numpy==1.26.4", "scipy==1.13.1", "soundfile==0.13.1", "psutil==7.1.0"]
PACKAGES = {"separate": ["demucs==4.1.0"],
            "transcribe": ["librosa==0.10.2.post1", "basic-pitch==0.4.0", "onnxruntime==1.20.1"],
            "chords": ["librosa==0.10.2.post1"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=analysis_root())
    parser.add_argument("--kind", choices=("all", *NAMES), default="all")
    parser.add_argument("--uv", default=shutil.which("uv") or str(Path.home() / ".local/bin/uv.exe"))
    parser.add_argument("--register-only", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu", help="CUDA applies to separation and beats; keeps the CPU environment.")
    parser.add_argument("--stems", type=int, choices=(4, 6), default=4, help="Six stems registers an additional model and preserves the four-stem model.")
    args = parser.parse_args()
    root = args.root.resolve()
    for name in ("runtimes", "models", "cache/downloads", "cache/tmp", "manifests", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ.update(UV_CACHE_DIR=str(root / "cache/downloads/uv"), UV_PYTHON_INSTALL_DIR=str(root / "runtimes/python"),
                      TEMP=str(root / "cache/tmp"), TMP=str(root / "cache/tmp"))
    recorder = Recorder("analysis-setup", "Python3.10 " + args.device.upper(), "Explicit isolated model installation/probe; weights remain outside Git.")
    for kind in NAMES if args.kind == "all" else (args.kind,):
        device = args.device if kind in ("separate", "beats") else "cpu"
        environment = root / "runtimes" / (("separation-cuda-py310" if kind == "separate" else "beats-cuda-py310") if device == "cuda" else NAMES[kind])
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not args.register_only:
            if not python.exists():
                recorder.execute([args.uv, "venv", "--python", "3.10.19", str(environment)])
            if kind in ("separate", "beats"):
                recorder.execute([args.uv, "pip", "install", "--python", str(python),
                                  "--index-url", "https://download.pytorch.org/whl/" + ("cu124" if device == "cuda" else "cpu"),
                                  "torch==2.5.1+" + ("cu124" if device == "cuda" else "cpu"),
                                  *(["torchaudio==2.5.1+" + ("cu124" if device == "cuda" else "cpu")] if kind == "beats" else [])])
            lock = Path(__file__).parent / "audio_analysis" / ("requirements-" + kind + ".txt")
            requirements = [line.strip() for line in lock.read_text(encoding="utf-8").splitlines()
                            if line.strip() and not line.startswith(("#", "torch=="))]
            recorder.execute([args.uv, "pip", "install", "--python", str(python), *requirements])
        recorder.execute([str(python), "scripts/audio_analysis/register.py", "--root", str(root), "--kind", kind, "--device", device,
                          "--stems", str(args.stems if kind == "separate" else 4)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
