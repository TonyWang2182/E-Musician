"""CPU-only fault checks for the guard. Never invokes nvidia-smi, Torch, or ACE."""
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from guarded_probe import finish_receipt, monitor, stop_owned


class GuardFaultTests(unittest.TestCase):
    def spawn_stubborn(self):
        child = subprocess.Popen([sys.executable, '-u', '-c',
            'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        self.addCleanup(lambda: stop_owned(child, grace=0.05))
        self.addCleanup(child.stdout.close)
        return child

    def test_stubborn_owned_process_gets_sigkill(self):
        child = self.spawn_stubborn()
        stop_owned(child, grace=0.05)
        self.assertEqual(child.returncode, -signal.SIGKILL)

    def test_monitor_failure_stops_owned_process_and_marks_interrupted(self):
        child = self.spawn_stubborn()
        receipt = {'status': 'running', 'minimum_free_gpu_mib': 15000}
        def broken():
            raise OSError('injected read-only monitor failure')
        monitor(child, receipt, time.monotonic(), state_reader=broken, grace=0.05)
        self.assertEqual(receipt['status'], 'interrupted')
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertIn('monitor_error', receipt)

    def test_failed_after_diagnostic_still_writes_terminal_receipt(self):
        def broken():
            raise TimeoutError('injected final diagnostic timeout')
        with tempfile.TemporaryDirectory(prefix='mir-guard-cpu-') as temporary:
            path = Path(temporary) / 'receipt.json'
            finish_receipt(path, {'status': 'failed', 'exit_code': 7}, state_reader=broken)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['status'], 'failed')
            self.assertFalse(receipt['after_health_check_passed'])
            self.assertEqual(receipt['exit_code'], 7)


if __name__ == '__main__':
    unittest.main(verbosity=2)
