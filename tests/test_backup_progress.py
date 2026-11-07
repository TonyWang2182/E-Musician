"""Synthetic metadata checks; never access a real backup or downloader."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "cloud"))
from backup_progress import BackupProgress, MAX_METADATA_BYTES
import full_backup
import pull_full_backup


class BackupProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
        self.source = {"schema": 2, "host": "test-host", "remote_root": "/backup/exports/example"}
        self.receipt = {"schema": 2,
                        "parts": [{"name": f"part-{i:06d}.tarpart", "size": size, "sha256": str(i) * 64}
                                  for i, size in enumerate((1000, 1000, 500))],
                        "manifest": {"name": "manifest.jsonl", "size": 100, "sha256": "f" * 64},
                        "summary": {"archive_bytes": 2500, "counts": {"file": 3, "dir": 1}, "source_root": "/backup"}}
        self.progress = {"schema": 2, "phase": "pulling", "started_utc": self.now.isoformat(),
                         "updated_utc": self.now.isoformat(), "bytes_verified": 1000,
                         "parts_verified": 1, "current_part_bytes": 250,
                         "active_parts": {"part-000001.tarpart": {"bytes": 250, "attempt": 1}}}
        self.write("source.json", self.source)
        self.write("receipt.remote.json", self.receipt)
        self.write("progress.json", self.progress)
        self.model = BackupProgress(self.directory)

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value), encoding="utf-8")

    def update(self, seconds=0, **values):
        self.progress.update(values, updated_utc=(self.now + timedelta(seconds=seconds)).isoformat())
        self.write("progress.json", self.progress)
        return self.model.poll(self.now + timedelta(seconds=seconds))

    def report(self, **values):
        result = {"schema": 2, "phase": "verified", "verified_utc": (self.now + timedelta(seconds=30)).isoformat(),
                  "parts": 3, "archive_bytes": 2500, "raw_tar_sha256": "a" * 64,
                  "members": {"file": 3, "dir": 1}, "member_count": 4, "content_bytes": 1800,
                  "part_hashes_verified": True, "member_hashes_verified": True,
                  "metadata_verified": True, "tar_padding_verified": True, "sidecars_verified": []}
        result.update(values)
        self.write("verification.json", result)

    def test_partial_total_includes_current_bytes_once_without_stat(self):
        with patch.object(Path, "stat", side_effect=AssertionError("must not stat archive files")):
            snapshot = self.model.poll(self.now)
        self.assertEqual(snapshot["downloaded_bytes"], 1250)
        self.assertEqual(snapshot["download_percent"], 50)
        self.assertEqual(snapshot["remaining_bytes"], 1250)
        self.assertEqual(snapshot["verified_bytes"], 1000)
        self.assertFalse(snapshot["completed"])

    def test_summary_fallback_and_unknown_total(self):
        self.write("receipt.remote.json", {"schema": 2, "summary": {"archive_bytes": 5000, "parts": 5}})
        snapshot = self.model.poll(self.now)
        self.assertEqual(snapshot["download_percent"], 25)
        self.assertEqual(snapshot["parts_total"], 5)
        self.report(archive_bytes=5000, parts=5)
        self.assertFalse(self.model.poll(self.now)["completed"])
        other = BackupProgress(self.directory / "absent")
        self.assertIsNone(other.poll(self.now)["download_percent"])

    def test_clamps_counters_and_does_not_add_sidecars(self):
        snapshot = self.update(bytes_verified=2400, current_part_bytes=99999, parts_verified=99)
        self.assertEqual(snapshot["download_percent"], 100)
        self.assertEqual(snapshot["parts_verified"], 3)
        self.assertFalse(snapshot["completed"])
        snapshot = self.update(phase="metadata", bytes_verified=1000, current_part_bytes=250)
        self.assertEqual(snapshot["downloaded_bytes"], 1000)

    def test_phase_alone_is_never_full_completion(self):
        snapshot = self.update(phase="verified", bytes_verified=2500, parts_verified=3)
        self.assertFalse(snapshot["completed"])
        self.report()
        snapshot = self.model.poll(self.now + timedelta(seconds=31))
        self.assertTrue(snapshot["completed"])
        self.assertEqual(snapshot["verification_percent"], 100)
        self.assertEqual(snapshot["members_verified"], 4)

    def test_report_must_match_receipt_and_verification_flags(self):
        for bad in ({"archive_bytes": 2499}, {"parts": 2}, {"member_count": 1},
                    {"tar_padding_verified": False}, {"raw_tar_sha256": "bad"},
                    {"sidecars_verified": ["unknown.json"]}, {"source": {"host": "other"}},
                    {"verified_utc": (self.now - timedelta(days=1)).isoformat()}):
            with self.subTest(bad=bad):
                self.report(**bad)
                snapshot = self.model.poll(self.now)
                self.assertFalse(snapshot["completed"])
                self.assertIn("未确认完成", snapshot["warning"])

    def test_different_receipts_and_source_change_prevent_completion(self):
        self.report()
        self.assertTrue(self.model.poll(self.now)["completed"])
        self.write("receipt.json", {**self.receipt, "summary": {"archive_bytes": 9999}})
        self.assertFalse(self.model.poll(self.now)["completed"])
        self.write("receipt.json", self.receipt)
        self.write("source.json", {**self.source, "remote_root": "/backup/exports/another"})
        self.assertFalse(self.model.poll(self.now + timedelta(seconds=60))["completed"])

    def test_verification_callback_and_long_silence_do_not_claim_stopped(self):
        snapshot = self.update(phase="verifying", bytes_verified=2500, parts_verified=3,
                               archive_bytes_read=1000, members_verified=2)
        self.assertEqual(snapshot["verification_percent"], 40)
        self.assertIn("2 / 4", snapshot["detail_text"])
        snapshot = self.model.poll(self.now + timedelta(hours=1))
        self.assertTrue(snapshot["stale"])
        self.assertIn("正在全量校验", snapshot["status_text"])
        self.assertIn("进度暂未更新", snapshot["status_text"])
        self.assertNotIn("停止", snapshot["status_text"])
        self.assertIsNone(snapshot["eta_seconds"])

    def test_stale_threshold_and_explicit_errors(self):
        self.assertFalse(self.model.poll(self.now + timedelta(seconds=89))["stale"])
        self.assertTrue(self.model.poll(self.now + timedelta(seconds=90))["stale"])
        snapshot = self.update(phase="failed", error_type="BackupError")
        self.assertEqual(snapshot["error"], "BackupError")
        self.assertIn("失败", snapshot["status_text"])
        self.assertIsNone(snapshot["speed_bps"])
        snapshot = self.update(phase="interrupted")
        self.assertIn("中断", snapshot["status_text"])

    def test_atomic_missing_corrupt_and_invalid_counter_keep_last_good(self):
        initial = self.model.poll(self.now)
        for raw in ("{", "[]", '{"schema":2,"phase":"pulling","bytes_verified":-1}',
                    '{"schema":2,"schema":2,"phase":"pulling"}',
                    '{"schema":2,"phase":"pulling","bytes_verified":NaN}'):
            with self.subTest(raw=raw):
                (self.directory / "progress.json").write_text(raw, encoding="utf-8")
                snapshot = self.model.poll(self.now + timedelta(seconds=5))
                self.assertEqual(snapshot["downloaded_bytes"], initial["downloaded_bytes"])
                self.assertIn("保留最近有效数据", snapshot["warning"])
                self.assertIsNone(snapshot["speed_bps"])
        (self.directory / "progress.json").unlink()
        self.assertEqual(self.model.poll(self.now)["downloaded_bytes"], 1250)

    def test_oversized_metadata_is_bounded_and_cached(self):
        self.model.poll(self.now)
        (self.directory / "receipt.remote.json").write_bytes(b" " * (MAX_METADATA_BYTES + 1))
        snapshot = self.model.poll(self.now)
        self.assertEqual(snapshot["total_bytes"], 2500)
        self.assertIn("receipt.remote.json 暂不可读", snapshot["warning"])

    def test_speed_eta_requires_ten_seconds_and_resets_for_restart(self):
        self.assertIsNone(self.model.poll(self.now)["speed_bps"])
        self.assertIsNone(self.update(9, current_part_bytes=340)["speed_bps"])
        snapshot = self.update(10, current_part_bytes=350)
        self.assertEqual(snapshot["speed_bps"], 10)
        self.assertEqual(snapshot["eta_seconds"], 115)
        snapshot = self.update(11, started_utc=(self.now + timedelta(seconds=11)).isoformat(),
                               bytes_verified=0, current_part_bytes=20)
        self.assertIsNone(snapshot["speed_bps"])
        self.assertIsNone(snapshot["eta_seconds"])
        snapshot = self.update(21, current_part_bytes=120)
        self.assertEqual(snapshot["speed_bps"], 10)

    def test_retry_counter_regression_and_clock_reversal_reset_speed(self):
        self.model.poll(self.now)
        self.assertEqual(self.update(10, current_part_bytes=350)["speed_bps"], 10)
        self.assertIsNone(self.update(11, current_part_bytes=300)["speed_bps"])
        self.assertEqual(self.update(21, current_part_bytes=400)["speed_bps"], 10)
        self.assertIsNone(self.update(22, current_part_bytes=500,
            active_parts={"part-000001.tarpart": {"bytes": 500, "attempt": 2}})["speed_bps"])
        self.assertIsNone(self.model.poll(self.now)["speed_bps"])

    def test_missing_source_cannot_confirm_completion(self):
        (self.directory / "source.json").unlink()
        self.report()
        snapshot = self.model.poll(self.now)
        self.assertFalse(snapshot["completed"])
        self.assertIn("等待 source.json", snapshot["warning"])

    def test_real_capture_parts_and_verifier_report_are_accepted_then_mismatch_rejected(self):
        # Exercise the actual producer's portable primitives and the real stream
        # verifier against a tiny archive, with no cloud access or Linux capture.
        writer = full_backup.Parts(self.directory, limit=4096)
        payload = b"small environment fixture\0" * 17
        member = tarfile.TarInfo("root/autodl-tmp/emusician/envs/fixture.txt")
        member.size, member.mode = len(payload), 0o644
        hashed = full_backup.HashedInput(io.BytesIO(payload))
        with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            archive.addfile(member, hashed)
        writer.flush_part()
        entry = {"name": member.name, "type": "file", "size": member.size,
                 "mode": member.mode, "linkname": "", "sha256": hashed.digest.hexdigest()}
        manifest_path = self.directory / "manifest.jsonl"
        manifest_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        manifest = {"name": "manifest.jsonl", "size": manifest_path.stat().st_size,
                    "sha256": full_backup.digest_file(manifest_path)}
        counts = {"file": 1, "dir": 0, "symlink": 0, "hardlink": 0}
        receipt = {"schema": 2, "parts": writer.parts, "manifest": manifest,
                   "metadata": {"manifest.jsonl": manifest},
                   "summary": {"archive_bytes": writer.total, "counts": counts,
                               "source_root": "/root/autodl-tmp/emusician"}}
        full_backup.write_json(self.directory / "receipt.json", receipt)
        self.write("receipt.remote.json", receipt)
        self.write("source.json", {**self.source,
                   "remote_root": "/root/autodl-tmp/emusician/exports/fixture"})
        callbacks = []
        with patch.object(pull_full_backup, "utc", return_value=(self.now + timedelta(seconds=30)).isoformat()):
            report = pull_full_backup.verify(self.directory, receipt, progress=callbacks.append)
        self.write("verification.json", report)
        self.update(31, phase="verified", bytes_verified=writer.total,
                    parts_verified=len(writer.parts), current_part_bytes=0, **callbacks[-1])
        snapshot = self.model.poll(self.now + timedelta(seconds=32))
        self.assertTrue(snapshot["completed"])
        self.assertEqual(snapshot["downloaded_bytes"], writer.total)
        self.assertEqual(snapshot["members_verified"], 1)
        self.assertEqual(snapshot["verification_percent"], 100)
        report["archive_bytes"] -= 1
        self.write("verification.json", report)
        snapshot = self.model.poll(self.now + timedelta(seconds=33))
        self.assertFalse(snapshot["completed"])
        self.assertIn("未确认完成", snapshot["warning"])


if __name__ == "__main__":
    unittest.main()
