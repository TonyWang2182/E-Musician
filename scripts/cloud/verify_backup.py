"""Verify an E-musician .tar.gz without extraction or a second archive read.

Members are hashed while streaming, then compared to the trailing manifest.
An optional receipt also checks the compressed file's SHA-256 in that same
pass. This proves archive integrity, not that every intended source was saved.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import tarfile
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MANIFEST = "BACKUP-MANIFEST.json"
CHUNK = 1024 * 1024
MAX_MANIFEST = 16 * CHUNK
MAX_ENTRIES = 100_000


class VerificationError(ValueError):
    pass


def safe_name(name, *, directory=False):
    if not isinstance(name, str) or not name or len(name) > 2048:
        raise VerificationError("Invalid archive member name.")
    value = name[:-1] if directory and name.endswith("/") else name
    if (not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise VerificationError("Unsafe archive member path: " + name[:160])
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError("Duplicate JSON property: " + key[:100])
        result[key] = value
    return result


def decode_json(data):
    def nonfinite(_):
        raise VerificationError("Non-finite JSON value.")
    value = json.loads(data, object_pairs_hook=unique_object, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise VerificationError("Expected a JSON object.")
    return value


class StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf, encoding, errors):
        try:
            return super().frombuf(buf, encoding, errors)
        except (tarfile.InvalidHeaderError, tarfile.TruncatedHeaderError, tarfile.EmptyHeaderError) as exc:
            # TarFile otherwise treats invalid non-initial headers as EOF.
            raise tarfile.SubsequentHeaderError(str(exc)) from exc


class CountedInput:
    def __init__(self, raw, hash_archive):
        self.raw = raw
        self.digest = hashlib.sha256() if hash_archive else None
        self.bytes_read = 0

    def read(self, size=-1):
        block = self.raw.read(size)
        self.bytes_read += len(block)
        if self.digest is not None:
            self.digest.update(block)
        return block


def verify(archive_path, receipt_path=None):
    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise VerificationError("Archive must be an existing regular file.")
    archive_path = archive_path.resolve()
    before = archive_path.stat()
    receipt = None
    if receipt_path is not None:
        receipt_path = Path(receipt_path)
        if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > CHUNK:
            raise VerificationError("Receipt is missing, linked or too large.")
        receipt = decode_json(receipt_path.read_bytes())
        if (type(receipt.get("size")) is not int or receipt["size"] < 1
                or not isinstance(receipt.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])):
            raise VerificationError("Receipt size or SHA-256 is invalid.")
        if receipt.get("archive") != archive_path.name:
            raise VerificationError("Receipt names a different archive.")
        if receipt["size"] != before.st_size:
            raise VerificationError("Archive size differs from receipt.")
    actual = {}
    seen = set()
    manifest = None
    with archive_path.open("rb") as raw:
        counted = CountedInput(raw, receipt is not None)
        with gzip.GzipFile(fileobj=counted, mode="rb") as compressed:
            with tarfile.open(fileobj=compressed, mode="r|", bufsize=CHUNK, tarinfo=StrictTarInfo) as archive:
                for member in archive:
                    name = safe_name(member.name, directory=member.isdir())
                    if name in seen:
                        raise VerificationError("Duplicate archive member: " + name)
                    seen.add(name)
                    if len(seen) > MAX_ENTRIES:
                        raise VerificationError("Archive has too many members.")
                    if manifest is not None:
                        raise VerificationError("Backup manifest must be the final member.")
                    if member.isdir():
                        if member.size != 0:
                            raise VerificationError("Directory has nonzero content size.")
                        continue
                    if not member.isfile() or member.sparse is not None:
                        raise VerificationError("Links, sparse files and special entries are unsupported: " + name)
                    if member.size < 0:
                        raise VerificationError("Negative member size.")
                    if name == MANIFEST and member.size > MAX_MANIFEST:
                        raise VerificationError("Backup manifest is too large.")
                    stream = archive.extractfile(member)  # A stream only; nothing is extracted to disk.
                    if stream is None:
                        raise VerificationError("Cannot read archive member: " + name)
                    digest, size = hashlib.sha256(), 0
                    manifest_bytes = bytearray()
                    with stream:
                        while block := stream.read(CHUNK):
                            size += len(block)
                            digest.update(block)
                            if name == MANIFEST:
                                manifest_bytes.extend(block)
                    if size != member.size:
                        raise VerificationError("Member size mismatch: " + name)
                    if name == MANIFEST:
                        manifest = decode_json(manifest_bytes)
                    else:
                        actual[name] = {"size": size, "sha256": digest.hexdigest()}
                # Consume stream-buffered bytes too, not just gzip's fileobj.
                # Validate gzip CRC/EOF and disallow a second hidden tar after
                # the first end marker. A tar ends with at least two zero blocks.
                padding = 0
                while block := archive.fileobj.read(CHUNK):
                    padding += len(block)
                    if any(block):
                        raise VerificationError("Nonzero data follows the tar end marker.")
                if padding < tarfile.BLOCKSIZE:
                    raise VerificationError("Missing second tar end block.")
        if counted.bytes_read != before.st_size:
            raise VerificationError("Archive stream did not consume the complete file.")
    after = archive_path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise VerificationError("Archive changed during verification.")
    if manifest is None or type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise VerificationError("Missing or unsupported backup manifest.")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise VerificationError("Invalid backup manifest file list.")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise VerificationError("Invalid manifest entry.")
        name = safe_name(entry.get("path"))
        if name == MANIFEST or name in expected:
            raise VerificationError("Duplicate or reserved manifest path: " + name)
        if (type(entry.get("size")) is not int or entry["size"] < 0
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise VerificationError("Invalid manifest size or SHA-256: " + name)
        expected[name] = {"size": entry["size"], "sha256": entry["sha256"]}
    if actual.keys() != expected.keys():
        missing, unlisted = sorted(expected.keys()-actual.keys()), sorted(actual.keys()-expected.keys())
        raise VerificationError(f"Manifest/member mismatch; missing={missing[:3]}, unlisted={unlisted[:3]}.")
    for name, entry in expected.items():
        if entry != actual[name]:
            raise VerificationError("Member checksum or size mismatch: " + name)
    archive_hash = counted.digest.hexdigest() if counted.digest is not None else None
    if receipt is not None:
        if archive_hash != receipt["sha256"]:
            raise VerificationError("Archive SHA-256 differs from receipt.")
        if type(receipt.get("file_count")) is not int or receipt["file_count"] != len(actual):
            raise VerificationError("Receipt file count differs from manifest.")
    return {"status": "passed", "archive": str(archive_path), "archive_size": before.st_size,
            "archive_sha256": archive_hash, "receipt_verified": receipt is not None,
            "file_count": len(actual), "content_bytes": sum(item["size"] for item in actual.values()),
            "member_checksums_verified": True, "gzip_crc_verified": True, "archive_read_passes": 1,
            "manifest_created_utc": manifest.get("created_utc"), "extracted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, help="Optional whole-archive receipt from Save Cloud Data")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    inputs = [args.archive.resolve()] + ([args.receipt.resolve()] if args.receipt else [])
    if args.report.resolve() in inputs or args.report.is_symlink():
        print(json.dumps({"status": "failed", "error": "Report must not overwrite or link to an input file."}))
        return 1
    try:
        report = verify(args.archive, args.receipt)
        code = 0
    except (ValueError, OSError, EOFError, tarfile.TarError, zlib.error) as exc:
        report = {"status": "failed", "archive": str(args.archive.resolve()), "error": str(exc)[:700], "extracted": False}
        code = 1
    report.update(checked_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=round(time.monotonic()-started, 3))
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    temporary = args.report.with_name(args.report.name + "." + uuid4().hex + ".tmp")
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(args.report)
    except OSError as exc:
        print(json.dumps({"status": "failed", "error": "Cannot write verification report: " + str(exc)[:300]}))
        return 1
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    print(encoded, end="")
    return code


if __name__ == "__main__":
    sys.exit(main())
