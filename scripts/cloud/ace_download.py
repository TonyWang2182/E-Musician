"""Download pinned public ACE files from official publisher's ModelScope repo.

Manifest entries record upstream file revision, size and SHA-256. The downloader
has bounded retry, resumes partial HTTP ranges, and publishes only checked files.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download(entry, target):
    output = target / entry["local_path"]
    if not output.resolve().is_relative_to(target.resolve()):
        raise ValueError("Invalid model destination")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size == entry["size"] and digest(output) == entry["sha256"]:
        print(f"checked {entry['local_path']}", flush=True)
        return
    partial = output.with_name(output.name + ".partial")
    query = urllib.parse.urlencode({"Revision": entry["revision"], "FilePath": entry["path"]})
    url = f"https://modelscope.cn/api/v1/models/{entry['repository']}/repo?{query}"
    for attempt in range(3):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"User-Agent": "E-musician-model-deployment/1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                append = offset > 0 and response.status == 206
                written = offset if append else 0
                with partial.open("ab" if append else "wb") as stream:
                    for chunk in iter(lambda: response.read(4 * 1024 * 1024), b""):
                        written += len(chunk)
                        if written > entry["size"]:
                            raise ValueError("Upstream file exceeds pinned size")
                        stream.write(chunk)
            if partial.stat().st_size != entry["size"] or digest(partial) != entry["sha256"]:
                raise ValueError("Upstream model checksum mismatch")
            partial.replace(output)
            print(f"downloaded {entry['local_path']} {entry['size']}", flush=True)
            return
        except Exception as exc:
            print(f"attempt {attempt+1} {entry['local_path']}: {type(exc).__name__}: {exc}", flush=True)
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda entry: download(entry, target), manifest["files"]))
    print(json.dumps({"status": "verified", "files": len(manifest["files"]), "elapsed_seconds": time.time()-start}), flush=True)


if __name__ == "__main__":
    main()
