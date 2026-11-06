"""CPU-only tests of probe receipt integrity; no GPU, SSH, or models are used."""
import unittest
from unittest.mock import Mock
from gpu_smoke import finish_telemetry


class TerminalReceiptTests(unittest.TestCase):
    def test_after_health_success_preserves_render_evidence(self):
        report={'status':'passed','result':{'actual_generated_audio':True}}
        finish_telemetry(report,0,9960,lambda:{'free_gpu_mib':14774,'active_ace_jobs':[]})
        self.assertTrue(report['after_healthcheck_verified'])
        self.assertEqual(report['after']['free_gpu_mib'],14774)
        self.assertEqual(report['status'],'passed')
        self.assertTrue(report['result']['actual_generated_audio'])

    def test_after_health_failure_cannot_erase_render_or_terminal_receipt(self):
        report={'status':'passed','result':{'actual_generated_audio':True}}
        finish_telemetry(report,0,9960,Mock(side_effect=TimeoutError('telemetry unavailable')))
        self.assertFalse(report['after_healthcheck_verified'])
        self.assertEqual(report['after_probe_error'],'TimeoutError: telemetry unavailable')
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['minimum_free_gpu_mib'],9960)
        self.assertTrue(report['result']['actual_generated_audio'])
        self.assertIn('wall_seconds',report)

    def test_after_health_success_cannot_turn_failed_inference_into_success(self):
        report={'status':'failed','exit_code':1}
        finish_telemetry(report,0,1024,lambda:{'free_gpu_mib':14774})
        self.assertTrue(report['after_healthcheck_verified'])
        self.assertEqual(report['status'],'failed')
        self.assertEqual(report['exit_code'],1)


if __name__=='__main__':unittest.main()
