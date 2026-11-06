"""CPU-only fault-path checks; no model, network, or GPU calls."""
import contextlib
import io
import json
import unittest
from unittest.mock import Mock,patch
import yue2_eval as subject


class SupervisorFaultTests(unittest.TestCase):
    def test_exit_race_is_not_a_failure(self):
        process=Mock(pid=1234);process.poll.return_value=None
        with patch.object(subject.os,'killpg',side_effect=ProcessLookupError(),create=True):subject.stop(process)
        process.wait.assert_called_once_with(timeout=5)

    def test_cleanup_error_cannot_leave_running_receipt(self):
        report={'status':'running'}
        with patch.object(subject,'stop',side_effect=OSError('cannot signal')):
            subject.fail_and_stop(report,RuntimeError('health lost'),Mock())
        self.assertEqual(report['status'],'failed')
        self.assertIn('health lost',report['error'])
        self.assertIn('cannot signal',report['cleanup_error'])

    def test_admission_error_has_failed_status_without_owned_process(self):
        report={'status':'admitting','inference_started':False}
        subject.fail_and_stop(report,BlockingIOError('lock busy'),None)
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['inference_started'])

    def test_disk_failure_still_emits_terminal_stdout(self):
        stream=io.StringIO();report={'status':'passed','result':{'actual_generated_audio':True}}
        with patch.object(subject,'write',side_effect=OSError('disk full')),contextlib.redirect_stdout(stream):
            subject.terminal_receipt('unused.json',report)
        receipt=json.loads(stream.getvalue())
        self.assertEqual(receipt['status'],'passed')
        self.assertTrue(receipt['result']['actual_generated_audio'])
        self.assertIn('disk full',receipt['receipt_write_error'])


if __name__=='__main__':unittest.main()
