"""CPU-only guard regression: no model loads, token access, or CUDA."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mu_probe',Path(__file__).with_name('probe.py'))
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
IDLE = {'active_ace_jobs':[],'free_gpu_mib':14774}


class Process:
    returncode = 0
    pid = 999999

    def poll(self):
        return self.returncode

    def wait(self,timeout=None):
        return self.returncode


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'state').mkdir()
        self.output,self.log = self.root/'out',self.root/'log'
        self.patch_root = patch.object(subject,'ROOT',self.root)
        self.patch_root.start()

    def tearDown(self):
        self.patch_root.stop()
        self.temp.cleanup()

    def invoke(self,mode='gpu'):
        with contextlib.redirect_stdout(io.StringIO()):
            code = subject.run_guard(mode,self.output,self.log)
        return code,json.loads((self.output/'guard.json').read_text())

    def success(self,*args,**kwargs):
        subject.write(self.output/'result.json',{'status':'passed','simulated':True})
        return Process()

    def test_cpu_hides_cuda_and_never_queries_gpu(self):
        def start(*args,**kwargs):
            self.assertEqual(kwargs['env']['CUDA_VISIBLE_DEVICES'],'-1')
            self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'],'1')
            self.assertNotIn('HF_TOKEN',kwargs['env'])
            self.assertNotIn('HUGGING_FACE_HUB_TOKEN',kwargs['env'])
            return self.success()
        with patch.object(subject,'state') as gpu,patch.object(subject.subprocess,'Popen',side_effect=start):
            code,report = self.invoke('cpu')
        gpu.assert_not_called()
        self.assertEqual(code,0)
        self.assertEqual(report['mode'],'cpu')

    def test_admission_denied_does_not_start_child(self):
        with patch.object(subject,'state',return_value={'active_ace_jobs':[('running',1)],'free_gpu_mib':14774}),patch.object(subject.subprocess,'Popen') as start:
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertEqual(report['status'],'blocked')
        start.assert_not_called()

    def test_initial_state_error_has_receipt(self):
        with patch.object(subject,'state',side_effect=[OSError(),IDLE]):
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertEqual(report['error_type'],'OSError')

    def test_after_state_error_preserves_result(self):
        with patch.object(subject,'state',side_effect=[IDLE,OSError()]),patch.object(subject.subprocess,'Popen',side_effect=self.success):
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertTrue(report['result']['simulated'])
        self.assertEqual(report['after_state_error_type'],'OSError')

    def test_invalid_result_preserves_terminal(self):
        def start(*args,**kwargs):
            (self.output/'result.json').write_text('{')
            return Process()
        with patch.object(subject,'state',return_value=IDLE),patch.object(subject.subprocess,'Popen',side_effect=start):
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertEqual(report['result_error_type'],'JSONDecodeError')

    def test_cleanup_error_preserves_receipt(self):
        with patch.object(subject,'state',return_value=IDLE),patch.object(subject.subprocess,'Popen',side_effect=self.success),patch.object(subject,'stop_owned',side_effect=OSError()):
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertEqual(report['cleanup_error_type'],'OSError')

    def test_signal_interrupt_cleans_owned_child(self):
        process = Process()
        process.returncode = None
        def stop(owned):
            self.assertIs(owned,process)
            owned.returncode = -15
        with patch.object(subject,'state',side_effect=[IDLE,KeyboardInterrupt(),IDLE]),patch.object(subject.subprocess,'Popen',return_value=process),patch.object(subject,'stop_owned',side_effect=stop) as cleanup:
            code,report = self.invoke()
        self.assertEqual(code,1)
        self.assertEqual(report['status'],'interrupted')
        self.assertEqual(report['exit_code'],-15)
        cleanup.assert_called_once_with(process)
        self.assertRaises(KeyboardInterrupt,subject.interrupt,subject.signal.SIGTERM,None)

    def test_exit_race_does_not_signal_other_pid(self):
        process = Process()
        process.returncode = None
        with patch.object(subject.os,'killpg',side_effect=ProcessLookupError) as kill:
            subject.stop_owned(process)
        kill.assert_called_once_with(process.pid,subject.signal.SIGTERM)


if __name__ == '__main__':
    unittest.main(verbosity=2)
