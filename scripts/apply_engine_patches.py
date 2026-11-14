#!/usr/bin/env python3
"""Apply/verify the exact, pinned E-musician Tracktion source patch.

No Git writes or package downloads. Only manifest-listed source files may change.
All hashes describe UTF-8 source with LF newlines, independent of checkout EOLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile


def normalized(data: bytes) -> bytes:
    data = data.replace(b"\r\n", b"\n")
    if b"\r" in data or data.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Unexpected source encoding/newline convention")
    data.decode("utf-8")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(normalized(data)).hexdigest()


def inside(root: Path, relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(part in {"", ".", ".."} for part in name.parts) or ":" in relative or "\\" in relative:
        raise ValueError(f"Unsafe relative path: {relative}")
    path = root.joinpath(*name.parts)
    path.resolve().relative_to(root.resolve())
    current = root
    for part in name.parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError(f"Linked patch/source path is not allowed: {current}")
    return path


def git_head(checkout: Path) -> str:
    directory = checkout / ".git"
    if directory.is_file():
        value = directory.read_text(encoding="utf-8").strip()
        if not value.startswith("gitdir: "):
            raise ValueError("Invalid Git metadata pointer")
        directory = (checkout / value[8:]).resolve()
    common = directory
    if (directory / "commondir").is_file():
        common = (directory / (directory / "commondir").read_text(encoding="utf-8").strip()).resolve()
    head = (directory / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head.lower()
    reference = head[5:]
    if not reference.startswith("refs/") or ".." in PurePosixPath(reference).parts:
        raise ValueError("Invalid HEAD reference")
    for base in (directory, common):
        file = base / reference
        if file.is_file():
            return file.read_text(encoding="utf-8").strip().lower()
        packed = base / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith(("#", "^")):
                    commit, ref = line.split(" ", 1)
                    if ref == reference:
                        return commit.lower()
    raise ValueError("Could not resolve checkout HEAD")


def apply_exact_patch(source: bytes, patch: bytes, filename: str) -> bytes:
    """Strict unified diff application; no fuzzy matching, rename or extra file."""
    original = normalized(source).decode("utf-8").splitlines(keepends=True)
    lines = normalized(patch).decode("utf-8").splitlines(keepends=True)
    if len(lines) < 3 or lines[0] != f"--- a/{filename}\n" or lines[1] != f"+++ b/{filename}\n":
        raise ValueError("Patch must address exactly its declared source file")
    result: list[str] = []
    cursor = 0
    index = 2
    while index < len(lines):
        header = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[index])
        if header is None:
            raise ValueError("Invalid or unexpected unified diff hunk")
        old_start, old_count, new_start, new_count = (int(header[1]), int(header[2] or 1), int(header[3]), int(header[4] or 1))
        position = old_start - 1 if old_count else old_start
        if position < cursor or position > len(original):
            raise ValueError("Overlapping or out-of-bounds patch hunk")
        result.extend(original[cursor:position])
        cursor = position
        expected_new = new_start - 1 if new_count else new_start
        if len(result) != expected_new:
            raise ValueError("Unexpected output hunk position")
        old_seen = new_seen = 0
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if not line or line[0] not in " +-":
                raise ValueError("Unsupported patch content")
            prefix, content = line[0], line[1:]
            if prefix in " -":
                if cursor >= len(original) or original[cursor] != content:
                    raise ValueError("Patch context differs from pinned source")
                cursor += 1
                old_seen += 1
            if prefix in " +":
                result.append(content)
                new_seen += 1
            index += 1
        if old_seen != old_count or new_seen != new_count:
            raise ValueError("Hunk line counts do not match")
    result.extend(original[cursor:])
    return "".join(result).encode("utf-8")


def run(mode: str, checkout: Path, manifest_file: Path) -> dict:
    checkout = checkout.resolve(strict=True)
    manifest_file = manifest_file.resolve(strict=True)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if mode not in {"apply", "verify"}:
        raise ValueError("Unknown patch mode")
    schema = manifest.get("schema")
    if schema not in {1, 2} or manifest.get("hash_normalization") != "utf8-lf":
        raise ValueError("Unsupported patch manifest")
    commit = manifest.get("upstream_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or git_head(checkout) != commit:
        raise ValueError("Tracktion HEAD does not match the pinned upstream commit")
    entries = manifest.get("files")
    # Schema 1 retains its original single-source boundary. Schema 2 explicitly
    # adds a bounded list with complete preflight before any checkout write.
    if not isinstance(entries, list) or not entries or len(entries) > (1 if schema == 1 else 16):
        raise ValueError("Patch manifest requires one source for schema 1 or 1..16 sources for schema 2")
    plan = []
    source_names, patch_names = set(), set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each patch entry must be an object")
        target = inside(checkout, entry["path"])
        patch_file = inside(manifest_file.parent, entry["patch"])
        source_key, patch_key = str(target).casefold(), str(patch_file).casefold()
        if source_key in source_names or patch_key in patch_names:
            raise ValueError("Duplicate source or patch path in manifest")
        source_names.add(source_key)
        patch_names.add(patch_key)
        for key in ("before_sha256_lf", "after_sha256_lf", "patch_sha256_lf"):
            if not re.fullmatch(r"[0-9a-f]{64}", entry.get(key, "")):
                raise ValueError(f"Invalid declared hash: {key}")
        patch = patch_file.read_bytes()
        if digest(patch) != entry["patch_sha256_lf"]:
            raise ValueError("Patch file hash differs from manifest")
        before = target.read_bytes()
        current = digest(before)
        patched = None
        if current == entry["after_sha256_lf"]:
            pass
        elif current != entry["before_sha256_lf"]:
            raise ValueError("Source is neither pinned upstream nor the exact patched result; refusing overwrite")
        elif mode == "verify":
            raise ValueError("The required source patch has not been applied")
        else:
            patched = apply_exact_patch(before, patch, entry["path"])
            if digest(patched) != entry["after_sha256_lf"]:
                raise ValueError("Patched source does not match declared output hash")
            if b"\r\n" in before:
                patched = patched.replace(b"\n", b"\r\n")
        plan.append({"entry": entry, "target": target, "before": before, "patched": patched, "temporary": None})

    # Each replacement is atomic. An OS failure between replacements can leave
    # a verified subset applied; a later run safely resumes from those hashes.
    try:
        for item in plan:
            if item["patched"] is None:
                continue
            target = item["target"]
            descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".patch-", dir=target.parent)
            item["temporary"] = temporary
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(item["patched"])
                stream.flush()
                os.fsync(stream.fileno())
        for item in plan:
            if item["target"].read_bytes() != item["before"]:
                raise ValueError("Source changed during patch preparation; refusing overwrite")
        for item in plan:
            if item["temporary"] is not None:
                if item["target"].read_bytes() != item["before"]:
                    raise ValueError("Source changed during patch preparation; refusing overwrite")
                os.replace(item["temporary"], item["target"])
            if digest(item["target"].read_bytes()) != item["entry"]["after_sha256_lf"]:
                raise ValueError("Source hash verification failed after replacement")
    finally:
        for item in plan:
            if item["temporary"] is not None and os.path.exists(item["temporary"]):
                os.unlink(item["temporary"])
    result = {"status": "applied" if any(item["patched"] is not None for item in plan) else "verified", "mode": mode,
              "upstream_commit": commit, "files": [{"path": item["entry"]["path"], "sha256_lf": item["entry"]["after_sha256_lf"]} for item in plan]}
    if len(plan) == 1:
        result.update(result["files"][0])
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument("--engine-root", type=Path, default=root / ".cache" / "monitor-engine")
    parser.add_argument("--manifest", type=Path, default=root / "cmake" / "patches" / "tracktion" / "manifest.json")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.mode, args.engine_root, args.manifest), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Engine patch {args.mode} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
