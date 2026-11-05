"""Fetch/verify the exact MIT sources used by the offline audio Warp renderer.

No build, package installation, or tracked source modification is performed.
Existing dependency directories are never reset or overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "cmake/signalsmith.json").read_text(encoding="utf-8"))
    for library in manifest["libraries"]:
        folder = root / library["directory"]
        if not folder.exists():
            if args.verify_only:
                raise SystemExit(f"Missing {folder}; run python scripts/bootstrap_stretch.py")
            subprocess.run(["git", "clone", "--no-checkout", library["url"], str(folder)], check=True)
            subprocess.run(["git", "-C", str(folder), "checkout", "--detach", library["commit"]], check=True)
        commit = subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()
        if commit != library["commit"]:
            raise SystemExit(f"Unexpected {library['name']} commit: {commit}")
        for name, expected in library["files"].items():
            path = folder / name
            if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit(f"Changed or missing dependency source: {path}")
        print(f"Verified {library['name']} {commit} ({len(library['files'])} source/license files)")

if __name__ == "__main__":
    main()
