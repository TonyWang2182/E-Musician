"""CPU-only lifecycle tests; no models, audio decode or CUDA initialization."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('scores_run', Path(__file__).with_name('run.py'))
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
IDLE = {'active_ace_jobs': [], 'free_gpu_mib': 14774}


class Process:
    returncode = 0
    pid = 999999

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'state').mkdir()
        self.output = self.root/'output'
        self.log = self.root/'log.txt'
        self.root_patch = patch.object(subject, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def invoke(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = subject.run_guard(self.output, self.log)
        return code, json.loads((self.output/'guard-receipt.json').read_text())

    def fake_success(self, *args, **kwargs):
        subject.write(self.output/'result-receipt.json', {'status': 'passed', 'simulated_test': True})
        return Process()

    def test_admission_denied_has_terminal_receipt(self):
        with patch.object(subject, 'state', return_value={'active_ace_jobs': [('running', 1)], 'free_gpu_mib': 14774}), patch.object(subject.subprocess, 'Popen') as start:
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'blocked')
        start.assert_not_called()

    def test_initial_diagnostic_error_has_receipt(self):
        with patch.object(subject, 'state', side_effect=[OSError('diagnostics'), IDLE]):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['error_type'], 'OSError')
        self.assertIsNone(report['exit_code'])

    def test_success_and_source_guard_hash(self):
        with patch.object(subject, 'state', return_value=IDLE), patch.object(subject.subprocess, 'Popen', side_effect=self.fake_success):
            code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(report['result']['simulated_test'])
        self.assertEqual(len(report['guard_script']['sha256']), 64)

    def test_after_diagnostic_error_does_not_lose_result(self):
        with patch.object(subject, 'state', side_effect=[IDLE, OSError('after')]), patch.object(subject.subprocess, 'Popen', side_effect=self.fake_success):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['after_state_error_type'], 'OSError')
        self.assertTrue(report['result']['simulated_test'])

    def test_cleanup_error_preserves_terminal_receipt(self):
        with patch.object(subject, 'state', return_value=IDLE), patch.object(subject.subprocess, 'Popen', side_effect=self.fake_success), patch.object(subject, 'stop_owned', side_effect=OSError('cleanup')):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['cleanup_error_type'], 'OSError')

    def test_invalid_result_has_terminal_receipt(self):
        def invalid(*args, **kwargs):
            (self.output/'result-receipt.json').write_text('{')
            return Process()
        with patch.object(subject, 'state', return_value=IDLE), patch.object(subject.subprocess, 'Popen', side_effect=invalid):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['result_error_type'], 'JSONDecodeError')

    def test_process_exit_race_only_targets_owned_pid(self):
        process = Process()
        process.returncode = None
        with patch.object(subject.os, 'killpg', side_effect=ProcessLookupError) as kill:
            subject.stop_owned(process)
        kill.assert_called_once_with(process.pid, subject.signal.SIGTERM)

    def test_supervisor_interrupt_cleans_child_and_keeps_receipt(self):
        process = Process()
        process.returncode = None

        def monitored_state():
            subject.interrupt(subject.signal.SIGTERM, None)

        def cleanup(owned):
            self.assertIs(owned, process)
            owned.returncode = -15

        with patch.object(subject, 'state', side_effect=[IDLE, KeyboardInterrupt('SIGTERM'), IDLE]), patch.object(subject.subprocess, 'Popen', return_value=process), patch.object(subject, 'stop_owned', side_effect=cleanup) as stop:
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'interrupted')
        self.assertEqual(report['exit_code'], -15)
        stop.assert_called_once_with(process)
        self.assertRaises(KeyboardInterrupt, monitored_state)


if __name__ == '__main__':
    unittest.main(verbosity=2)
