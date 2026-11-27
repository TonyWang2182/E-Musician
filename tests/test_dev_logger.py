"""Verify durable failure evidence and source drift without running a build."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("emusician_dev", Path(__file__).resolve().parents[1] / "scripts" / "dev.py")
assert spec is not None and spec.loader is not None
dev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dev
spec.loader.exec_module(dev)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="emusician-logger-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(dev, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        (self.root / "core").mkdir()
        (self.root / "core" / "fixture.txt").write_text("before", encoding="utf-8")
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def record(self):
        records = list((self.root / "docs" / "builds").glob("*.json"))
        self.assertEqual(len(records), 1)
        return json.loads(records[0].read_text(encoding="utf-8"))

    def test_failed_command_preserves_raw_bytes_and_source_drift(self):
        # The child verifies evidence is already durable before it runs, then
        # mutates a source input and fails as a real compiler could.
        child = """
import json, os, pathlib, sys
root = pathlib.Path.cwd()
record = json.loads(next((root / 'docs' / 'builds').glob('*.json')).read_text(encoding='utf-8'))
assert record['status'] == 'running' and record['finished_at'] is None
assert os.environ['VSLANG'] == '1033'
(root / 'core' / 'fixture.txt').write_text('after', encoding='utf-8')
sys.stdout.buffer.write(bytes([0xb4, 0xed, 0xce, 0xf3, 10]))
sys.stdout.buffer.flush()
sys.exit(7)
"""
        recorder = dev.Recorder("logger-test", "Debug", "intentional subprocess failure")
        with self.assertRaises(dev.CommandFailure) as failure:
            recorder.execute([sys.executable, "-c", child])
        self.assertEqual(failure.exception.returncode, 7)
        record = self.record()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 7)
        self.assertIsNotNone(record["finished_at"])
        self.assertTrue(record["source_changed_during_command"])
        self.assertNotEqual(record["source_fingerprint"]["digest"], record["source_fingerprint_end"]["digest"])
        self.assertEqual((self.root / record["raw_log"]).read_bytes(), bytes([0xb4, 0xed, 0xce, 0xf3, 10]))
        self.assertIn("Source files changed", (self.root / "docs" / "DEVLOG.md").read_text(encoding="utf-8"))

    def test_startup_failure_is_finalized(self):
        recorder = dev.Recorder("logger-test", "Debug", "missing executable")
        with self.assertRaises(dev.CommandFailure) as failure:
            recorder.execute([str(self.root / "missing-command")])
        self.assertEqual(failure.exception.returncode, 127)
        record = self.record()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 127)
        self.assertFalse(record["source_changed_during_command"])
        self.assertIsNotNone(record["finished_at"])
        self.assertTrue((self.root / record["log"]).read_text(encoding="utf-8"))

    def test_redirected_console_uses_utf8(self):
        # Reproduce an ANSI Windows-style pipe, then ensure our CLI output
        # can be decoded by VS Code/Codex without altering child log bytes.
        scripts = str(Path(__file__).resolve().parents[1] / "scripts")
        child = (
            "import sys; sys.path.insert(0, sys.argv[1]); import dev; "
            "dev.configure_console_output(); print('\\u9002\\u7528\\u4e8e MSBuild')"
        )
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp936"
        result = subprocess.run([sys.executable, "-c", child, scripts],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=environment, check=True)
        self.assertEqual(result.stdout.decode("utf-8"), "\u9002\u7528\u4e8e MSBuild\n")


if __name__ == "__main__":
    unittest.main()
