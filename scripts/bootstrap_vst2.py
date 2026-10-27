"""Fetch the pinned historical VST2 interface for this local host build.

The original header notices are retained. This is a build dependency, not a
plugin installer; no user plugin, licence or sample library is modified.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a54535bc317b5c005a8cda5c22a9c8d4c6e0c67e"
BASE = f"https://raw.githubusercontent.com/juce-framework/JUCE/{COMMIT}/modules/juce_audio_processors/format_types/VST3_SDK/pluginterfaces/vst2.x/"
FILES = {
    "aeffect.h": "f59acd8cdf205dc36ceaff2d4c1054fa3e8e863d",
    "aeffectx.h": "44bd2e274fbd1b01d5ee8a65e3ae30d9fccbdc79",
    "vstfxstore.h": "ad7c91ee1211fa03d43d58317d7f95f6e30f925c",
}


def blob_id(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "_deps" / "vst2_sdk")
    args = parser.parse_args()
    destination = args.destination.resolve()
    headers = destination / "pluginterfaces" / "vst2.x"
    metadata = {"source": "juce-framework/JUCE", "commit": COMMIT, "files": {}}
    prepared: dict[str, bytes] = {}
    for name, expected in FILES.items():
        target = headers / name
        if target.is_file():
            data = target.read_bytes()
            if blob_id(data) != expected:
                raise RuntimeError(f"Refusing to overwrite modified SDK header: {target}")
        else:
            request = urllib.request.Request(BASE + name, headers={"User-Agent": "E-musician-dependency-bootstrap"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024 or blob_id(data) != expected:
                raise RuntimeError(f"Pinned source verification failed: {name}")
        prepared[name] = data
        metadata["files"][name] = {"url": BASE + name, "git_blob_sha1": expected,
                                   "sha256": hashlib.sha256(data).hexdigest()}
    headers.mkdir(parents=True, exist_ok=True)
    for name, data in prepared.items():
        target = headers / name
        if not target.exists():
            with target.open("xb") as output:
                output.write(data)
    (destination / "SOURCE.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ready", "sdk_root": str(destination), "commit": COMMIT}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
