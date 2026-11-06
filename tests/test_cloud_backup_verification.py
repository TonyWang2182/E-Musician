"""Synthetic archive verification boundaries; no extraction or cloud access."""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/cloud"))
from verify_backup import MANIFEST, VerificationError, main, verify


class BackupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "backup.tar.gz"
        self.files = {"models/weights.bin": b"model-weights" * 1000, "workspace/description.txt": "音乐测试".encode()}

    def write(self, *, entries=None, manifest_files=None, include_manifest=True, after=None):
        entries = list(self.files.items()) if entries is None else entries
        expected = self.files if manifest_files is None else manifest_files
        manifest = {"schema": 1, "created_utc": "fixture", "files": [
            {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for path, data in expected.items()]}
        with tarfile.open(self.path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                if data is None:
                    info.type = tarfile.SYMTYPE
                    info.linkname = "models/weights.bin"
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            if include_manifest:
                data = json.dumps(manifest).encode()
                info = tarfile.TarInfo(MANIFEST)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if after:
                info = tarfile.TarInfo(after)
                archive.addfile(info, io.BytesIO())
        return self.path

    def receipt(self):
        path = self.root / "receipt.json"
        path.write_text(json.dumps({"archive": self.path.name, "size": self.path.stat().st_size,
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(), "file_count": len(self.files)}), encoding="utf-8")
        return path

    def test_valid_manifest_without_receipt(self):
        self.write()
        result = verify(self.path)
        self.assertEqual(result["file_count"], 2)
        self.assertTrue(result["gzip_crc_verified"])
        self.assertIsNone(result["archive_sha256"])
        self.assertFalse(result["receipt_verified"])
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_receipt_hash_same_single_read(self):
        self.write()
        receipt = self.receipt()
        original, archive_opens = Path.open, []
        def counted(path, *args, **kwargs):
            if path.resolve() == self.path.resolve():
                archive_opens.append(args)
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "open", counted):
            result = verify(self.path, receipt)
        self.assertTrue(result["receipt_verified"])
        self.assertEqual(len(archive_opens), 1)
        self.assertEqual(result["archive_sha256"], json.loads(receipt.read_text())["sha256"])

    def test_tampered_member(self):
        changed = list(self.files.items())
        changed[0] = (changed[0][0], b"bad-weights!" * 1000)
        self.write(entries=changed)
        with self.assertRaisesRegex(VerificationError, "checksum or size"):
            verify(self.path)

    def test_missing_and_unlisted_files(self):
        for files, expected in [([], self.files), (list(self.files.items()), {})]:
            with self.subTest(files=files[:1]):
                self.write(entries=files, manifest_files=expected)
                with self.assertRaisesRegex(VerificationError, "missing=.*unlisted="):
                    verify(self.path)

    def test_duplicate_member(self):
        entries = list(self.files.items())
        self.write(entries=entries + entries[:1])
        with self.assertRaisesRegex(VerificationError, "Duplicate archive member"):
            verify(self.path)

    def test_unsafe_paths(self):
        for name in ("../escape", "/absolute", "C:/windows", "folder\\escape", "x/../escape", "x//file"):
            with self.subTest(name=name):
                self.write(entries=[(name, b"x")])
                with self.assertRaisesRegex(VerificationError, "Unsafe archive member path"):
                    verify(self.path)

    def test_symlink_rejected(self):
        self.write(entries=[("workspace/link", None)])
        with self.assertRaisesRegex(VerificationError, "Links"):
            verify(self.path)

    def test_manifest_must_be_present_and_last(self):
        self.write(include_manifest=False)
        with self.assertRaisesRegex(VerificationError, "manifest"):
            verify(self.path)
        self.write(after="extra")
        with self.assertRaisesRegex(VerificationError, "final member"):
            verify(self.path)

    def test_manifest_path_is_checked(self):
        self.write(manifest_files={"../escape": b"x"})
        with self.assertRaisesRegex(VerificationError, "Unsafe"):
            verify(self.path)

    def test_bad_receipt(self):
        self.write()
        path = self.receipt()
        receipt = json.loads(path.read_text())
        receipt["sha256"] = "0" * 64
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(VerificationError, "SHA-256 differs"):
            verify(self.path, path)

    def test_truncated_gzip(self):
        self.write()
        self.path.write_bytes(self.path.read_bytes()[:-5])
        with self.assertRaises((EOFError, OSError, tarfile.TarError)):
            verify(self.path)

    def test_hidden_concatenated_tar_rejected(self):
        self.write()
        raw = gzip.decompress(self.path.read_bytes())
        self.path.write_bytes(gzip.compress(raw + raw))
        with self.assertRaisesRegex(VerificationError, "Nonzero data follows"):
            verify(self.path)

    def test_cli_records_failure_without_extraction(self):
        self.write(include_manifest=False)
        report = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--archive", str(self.path), "--report", str(report)]), 1)
        self.assertEqual(json.loads(report.read_text())["status"], "failed")
        self.assertEqual({path.name for path in self.root.iterdir()}, {self.path.name, report.name})

    def test_report_cannot_overwrite_archive(self):
        self.write()
        before = self.path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--archive", str(self.path), "--report", str(self.path)]), 1)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
