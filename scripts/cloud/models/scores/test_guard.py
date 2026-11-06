"""CPU-only fault injection for receipt persistence; no model/process is launched."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name('gpu_probe-final-v3.py')
if not SOURCE.exists():
    SOURCE = Path(__file__).with_name('gpu_probe.py')
spec = importlib.util.spec_from_file_location('scores_guard_under_test', SOURCE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class FakeChild:
    pid = 99999999
    returncode = None
    def poll(self):
        return self.returncode
    def wait(self, timeout):
        self.returncode = 0
        return 0


class GuardFaultTests(unittest.TestCase):
    def invoke(self, mode):
        with tempfile.TemporaryDirectory(prefix='guard-cpu-', dir=guard.BASE) as directory:
            root = Path(directory)
            (root/'state').mkdir()
            (root/'logs/model-library').mkdir(parents=True)
            child = FakeChild()
            good = {'active_ace_jobs': [], 'free_gpu_mib': 14774}
            calls = 0

            def fake_state():
                nonlocal calls
                calls += 1
                if mode == 'before' and calls == 1:
                    raise RuntimeError('simulated initial state query failure')
                if mode == 'admission':
                    return {'active_ace_jobs': [['running', 1]], 'free_gpu_mib': 14774}
                if mode == 'watchdog' and calls >= 2:
                    raise RuntimeError('simulated readonly state query failure')
                if mode == 'after' and calls == 2:
                    raise RuntimeError('simulated final state query failure')
                return good

            def fake_start(command, **kwargs):
                output = Path(command[-1])
                if mode == 'result':
                    (output/'probe-result.json').write_text('{bad-json')
                elif mode != 'watchdog':
                    (output/'probe-result.json').write_text('{"status":"passed"}')
                if mode != 'watchdog':
                    child.returncode = 0
                return child

            def fake_cleanup(owned):
                self.assertIs(owned, child)
                if mode == 'cleanup':
                    raise ProcessLookupError('simulated cleanup error')
                child.returncode = 0

            fake_deployment = {'checks': {'gpu_inference_verified': False}}
            with patch.object(guard, 'ROOT', root), patch.object(guard, 'state', side_effect=fake_state), \
                 patch.object(guard.subprocess, 'Popen', side_effect=fake_start) as spawn, \
                 patch.object(guard, 'stop_owned', side_effect=fake_cleanup) as cleanup, \
                 patch.object(guard, 'deployment', return_value=fake_deployment), \
                 patch.object(guard, 'save_deployment') as save, \
                 patch.object(guard.sys, 'argv', ['probe', '--approved-slot']):
                with self.assertRaises(SystemExit) as exit_info:
                    guard.main()
                self.assertEqual(exit_info.exception.code, 1)
                admitted = mode not in ('before', 'admission')
                self.assertEqual(spawn.call_count, int(admitted))
                self.assertEqual(cleanup.call_count, int(admitted))
                receipts = list((root/'manifests/model-library/sheetsage2').glob('gpu-probe-*.json'))
                self.assertEqual(len(receipts), 1)
                receipt = json.loads(receipts[0].read_text())
                self.assertEqual(receipt['status'], 'blocked' if mode == 'admission' else 'failed')
                self.assertIn('exit_code', receipt)
                self.assertFalse(fake_deployment['checks']['gpu_inference_verified'])
                self.assertEqual(save.call_count, 1)
                return receipt

    def test_watchdog_and_final_state_exceptions_keep_terminal_receipt(self):
        receipt = self.invoke('watchdog')
        self.assertEqual(receipt['error_type'], 'RuntimeError')
        self.assertEqual(receipt['after_state_error_type'], 'RuntimeError')

    def test_initial_state_failure_keeps_terminal_receipt_without_child(self):
        self.assertEqual(self.invoke('before')['error_type'], 'RuntimeError')

    def test_admission_rejection_keeps_terminal_receipt_without_child(self):
        self.assertIsNone(self.invoke('admission')['exit_code'])

    def test_final_state_exception_keeps_terminal_receipt(self):
        self.assertEqual(self.invoke('after')['after_state_error_type'], 'RuntimeError')

    def test_result_parse_failure_keeps_terminal_receipt(self):
        self.assertEqual(self.invoke('result')['result_error_type'], 'JSONDecodeError')

    def test_cleanup_failure_keeps_terminal_receipt(self):
        self.assertEqual(self.invoke('cleanup')['cleanup_error_type'], 'ProcessLookupError')

    def test_owned_child_exit_race_is_harmless(self):
        child = FakeChild()
        with patch.object(guard.os, 'killpg', side_effect=ProcessLookupError) as kill:
            guard.stop_owned(child)
        kill.assert_called_once_with(child.pid, guard.signal.SIGTERM)
        self.assertEqual(child.returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
