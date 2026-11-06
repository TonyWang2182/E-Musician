"""CPU-only guard fault tests. No CUDA, models or existing service calls."""
import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from guard import finish, stop_owned


class GuardTests(unittest.TestCase):
    def test_stubborn_owned_process_is_killed(self):
        child = subprocess.Popen([sys.executable, '-u', '-c',
            'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)'],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: stop_owned(child, .05)); self.addCleanup(child.stdout.close)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        stop_owned(child, .05)
        self.assertEqual(child.returncode, -signal.SIGKILL)

    def test_exit_race_is_harmless(self):
        class Child:
            pid = 99999999
            def poll(self): return None
            def wait(self, timeout): return 0
        with patch('guard.os.killpg', side_effect=ProcessLookupError) as kill:
            stop_owned(Child())
        kill.assert_called_once_with(99999999, signal.SIGTERM)

    def test_final_health_failure_keeps_receipt(self):
        def broken(): raise OSError('injected final health failure')
        with tempfile.TemporaryDirectory(prefix='mir-whole-guard-') as temp:
            path = Path(temp)/'receipt.json'
            finish(path, {'status': 'failed'}, None, time.monotonic(), broken)
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertIn('after_diagnostic_error', report)
            self.assertIsNone(report['exit_code'])

    def test_cleanup_failure_keeps_failed_receipt(self):
        with tempfile.TemporaryDirectory(prefix='mir-whole-guard-') as temp:
            path = Path(temp)/'receipt.json'
            with patch('guard.stop_owned', side_effect=OSError('injected cleanup failure')):
                finish(path, {'status': 'passed'}, None, time.monotonic(), lambda: {})
            report = json.loads(path.read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertIn('cleanup_error', report)

    def test_disk_failure_prints_terminal_receipt(self):
        stream = io.StringIO()
        with patch('guard.write', side_effect=OSError('injected disk failure')), contextlib.redirect_stdout(stream):
            with self.assertRaises(OSError):
                finish(Path('/unused'), {'status': 'failed'}, None, time.monotonic(), lambda: {})
        report = json.loads(stream.getvalue())
        self.assertIn('receipt_write_error', report)
        self.assertEqual(report['status'], 'failed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
