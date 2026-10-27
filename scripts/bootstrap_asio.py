"""Install the pinned official ASIO interface headers into _deps/asio_sdk.

Run only through scripts/dev.py / Recorder. No drivers or registry changes.
Download is integrity checked before any file is installed. Distribution terms
remain those in the unmodified upstream LICENSE.txt and project dependency doc.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

URL = "https://download.steinberg.net/sdk_downloads/ASIO-SDK_2.3.4_2025-10-15.zip"
ARCHIVE_SHA256 = "d5ebf0c20dd2c5f43771fd0c1418f4b361bf52434ee670097cfa6b3a335e2eca"
ARCHIVE_BYTES = 8910208
FILES = {
    "common/iasiodrv.h": "86ad4788452c74823653cf57d4bd557c48bb6542d7e6eb7fff80102c705a066d",
    "common/asio.h": "93d2f80d49b4ac9c963514e7c1307ab5111d8104246192233745beb058534ea1",
    "common/asiosys.h": "f44a1ed0fd7c056ff047aeebc4c05a8c185f0585a24d8debc55c70107777dbef",
    "LICENSE.txt": "61e56814f24b32216884b2db0b4dcc317111a5ab354d54d19dd9fc13d71b1c7a",
    "common/LICENSE.txt": "61e56814f24b32216884b2db0b4dcc317111a5ab354d54d19dd9fc13d71b1c7a",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Verify installed files without network or writes")
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official archive instead of network")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / "_deps" / "asio_sdk"
    valid = all((destination / name).is_file() and digest((destination / name).read_bytes()) == sha for name, sha in FILES.items())
    if args.verify_only:
        print(json.dumps({"verified": valid, "directory": str(destination), "archive_sha256": ARCHIVE_SHA256}))
        return 0 if valid else 1
    if valid:
        print(json.dumps({"verified": True, "reused": True, "directory": str(destination)}))
        return 0
    if args.archive:
        data = args.archive.read_bytes()
    else:
        request = urllib.request.Request(URL, headers={"User-Agent": "E-musician-dependency-bootstrap/0.5"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(ARCHIVE_BYTES + 1)
    if len(data) != ARCHIVE_BYTES or digest(data) != ARCHIVE_SHA256:
        raise ValueError("ASIO archive size/hash does not match the pinned official SDK; nothing installed")
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name, sha in FILES.items():
            payload = archive.read("ASIOSDK/" + name)
            if digest(payload) != sha:
                raise ValueError(f"ASIO archive member hash mismatch: {name}")
            payloads[name] = payload
    for name, payload in payloads.items():
        target = destination / name
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Unsafe ASIO output path")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".pending")
        temporary.write_bytes(payload)
        temporary.replace(target)
    manifest = {"url": URL, "archive_sha256": ARCHIVE_SHA256, "archive_bytes": ARCHIVE_BYTES, "files": FILES,
                "notice": "Official upstream files. Review LICENSE.txt for internal use and redistribution terms."}
    (destination / "source.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verified": True, "reused": False, "directory": str(destination), "headers": 3}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
