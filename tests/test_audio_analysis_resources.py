"""Lightweight resource-failure tests; no model, CUDA import or large allocation."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.audio_analysis.common import AnalysisError, Job, atomic_json, validate_request
from scripts.audio_analysis import resources as r


def request(root, **changes):
    return validate_request({'schema_version': 1, 'job_id': 'resource-test', 'kind': 'separate',
        'analysis_root': str(root), 'source_path': str(root/'absent.wav'), 'duration_seconds': 75,
        'source': {'sample_rate': 48000}, 'parameters': {'stems': 6, 'quality': 'quality'}, **changes})


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request = request(self.root)

    def test_commit_exhaustion_rejected_even_when_physical_memory_is_free(self):
        with self.assertRaises(AnalysisError) as caught:
            r.check_admission(self.request, {}, {'available_commit_bytes': 2800*r.MIB,
                'available_physical_bytes': 6*r.GIB})
        self.assertEqual(caught.exception.code, 'insufficient_memory')
        self.assertGreater(caught.exception.resource_report['required_available_commit_bytes'], 4*r.GIB)
        self.assertIn('project was not changed', str(caught.exception))

    def test_policy_is_shared_and_cannot_be_weakened(self):
        for kind, expected in (('separate', 4), ('transcribe', 2), ('beats', 2), ('chords', 1)):
            value = {**self.request, 'kind': kind, 'resource_policy': {'minimum_available_commit_bytes': 1}}
            self.assertEqual(r.resource_policy(value)['minimum_available_commit_bytes'], expected*r.GIB)
        value = {**self.request, 'resource_policy': {'version': 1, 'minimum_available_commit_bytes': 6*r.GIB}}
        self.assertEqual(r.resource_policy(value)['minimum_available_commit_bytes'], 6*r.GIB)
        for bad in ([], {'version': 2}, {'minimum_available_commit_bytes': True}, {'critical_grace_ms': -1}):
            with self.subTest(bad=bad), self.assertRaises(AnalysisError):
                r.resource_policy({**self.request, 'resource_policy': bad})

    def test_known_buffers_scale_with_stems_duration_and_shift_accumulation(self):
        quality = r.known_buffer_budget(self.request, {})
        fast = copy.deepcopy(self.request);fast['parameters']['quality'] = 'fast'
        fast_budget = r.known_buffer_budget(fast, {})
        self.assertEqual(quality['known_buffer_bytes']-fast_budget['known_buffer_bytes'], quality['separation_output_bytes'])
        shorter = {**self.request, 'duration_seconds': 10}
        self.assertLess(r.known_buffer_budget(shorter, {})['known_buffer_bytes'], quality['known_buffer_bytes'])
        four = copy.deepcopy(self.request);four['parameters']['stems'] = 4
        self.assertLess(r.known_buffer_budget(four, {})['known_buffer_bytes'], quality['known_buffer_bytes'])

    def test_physical_headroom_and_success_report_are_separate(self):
        with self.assertRaises(AnalysisError):
            r.check_admission(self.request, {}, {'available_commit_bytes': 20*r.GIB, 'available_physical_bytes': 100*r.MIB})
        report = r.check_admission(self.request, {}, {'available_commit_bytes': 20*r.GIB, 'available_physical_bytes': 8*r.GIB})
        self.assertFalse(report['model_peak_guaranteed'])

    def test_runtime_guard_stops_at_safe_checkpoint(self):
        with patch.object(r, 'memory_snapshot', return_value={'available_commit_bytes': 100*r.MIB}), self.assertRaises(AnalysisError) as caught:
            r.MemoryGuard(self.request).checkpoint()
        self.assertEqual(caught.exception.code, 'memory_pressure')

    def test_torch_style_and_plain_runtime_oom_are_single_attempt(self):
        class TorchLikeOom(RuntimeError): pass
        for error in (TorchLikeOom('CUDA out of memory'), RuntimeError('CUDA error: out of memory'),
                      RuntimeError('DefaultCPUAllocator: not enough memory'), MemoryError()):
            calls = []
            def operation():
                calls.append(True)
                raise error
            with self.subTest(error=type(error)), self.assertRaises(AnalysisError) as caught:
                r.run_inference_once(operation, 'Separation')
            self.assertEqual(calls, [True])
            self.assertEqual(caught.exception.code, 'out_of_memory')
            self.assertIn('No automatic CPU retry', str(caught.exception))
        with self.assertRaisesRegex(RuntimeError, 'shape mismatch'):
            r.run_inference_once(lambda: (_ for _ in ()).throw(RuntimeError('shape mismatch')))
        self.assertEqual(r.run_inference_once(lambda: 42), 42)

    def test_gpu_admission_uses_observed_probe_but_does_not_retry_cpu(self):
        class Cuda:
            @staticmethod
            def mem_get_info(): return 700*r.MIB, 4*r.GIB
        class Torch: cuda = Cuda()
        with self.assertRaises(AnalysisError) as caught:
            r.check_gpu_headroom(Torch, {'probe_peak_cuda_reserved_bytes': 800*r.MIB})
        self.assertEqual(caught.exception.code, 'insufficient_gpu_memory')

    def test_low_memory_rejected_before_decode_or_provider_import(self):
        from scripts.audio_analysis import run
        job_dir = self.root/'cache/jobs/resource-test';job_dir.mkdir(parents=True)
        atomic_json(job_dir/'request.json', self.request)
        atomic_json(self.root/'registry.json', {'providers': {'separate_6s': {'available': True}}})
        with patch.object(r, 'memory_snapshot', return_value={'available_commit_bytes': 2*r.GIB, 'available_physical_bytes': 6*r.GIB}), \
                patch.object(run, 'prepare') as decode, self.assertRaises(AnalysisError):
            run.execute(Job(job_dir/'request.json'))
        decode.assert_not_called()
        self.assertFalse((job_dir/'input.wav').exists())

    def test_real_worker_process_rejects_without_loading_model_and_leaves_receipt(self):
        # Deliberately impossible admission requirement triggers the real CLI's
        # safe path; it does not reserve/allocate this memory or load a model.
        self.request['resource_policy'] = {'version': 1, 'minimum_available_commit_bytes': 512*r.GIB}
        job_dir = self.root/'cache/jobs/resource-test';job_dir.mkdir(parents=True)
        atomic_json(job_dir/'request.json', self.request)
        atomic_json(self.root/'registry.json', {'providers': {'separate_6s': {'available': True}}})
        command = [sys.executable, str(Path(__file__).resolve().parents[1]/'scripts/audio_analysis/run.py'),
                   '--request', str(job_dir/'request.json')]
        child = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(child.returncode, 2, child.stderr.decode(errors='replace'))
        error = json.loads((job_dir/'error.json').read_text(encoding='utf-8'))
        self.assertEqual(error['code'], 'insufficient_memory')
        self.assertFalse((job_dir/'input.wav').exists())
        self.assertFalse((job_dir/'result.json').exists())
        self.assertTrue((job_dir/'fault.log').is_file())
        self.assertTrue((job_dir/'resource-budget.json').is_file())

    @unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('demucs'),
                         'Tiny tensor test runs separately in the CPU separation environment')
    def test_inference_tensor_restoration_preserves_values_without_second_model(self):
        if r.memory_snapshot()['available_commit_bytes'] < 4*r.GIB:
            self.skipTest('Insufficient headroom for even a CPU Torch import; no model is loaded')
        import numpy as np
        import soundfile as sf
        import torch
        from scripts.audio_analysis.providers import separate
        from scripts.audio_analysis.common import sha256_file
        model_file = self.root/'fake-model';model_file.write_bytes(b'not real weights')
        class Model:
            sources = ['vocals', 'drums', 'bass', 'other']
            samplerate, audio_channels, segment, use_train_segment = 44100, 2, 7.8, True
            def eval(self): return self
        class TestJob:
            directory = self.root
            request = {'parameters': {'stems': 4, 'quality': 'fast', 'segment_seconds': 4}}
            def progress(self, *args): pass
            def check_cancelled(self): pass
        source = np.arange(32, dtype=np.float32).reshape(16,2)/32
        reference = torch.from_numpy(source.T.copy()).mean(0)
        expected = .5*float(reference.std()) + float(reference.mean())
        def tiny_infer(model, mix, **kwargs):
            self.assertTrue(torch.is_inference_mode_enabled())
            return torch.full((1, 4, 2, 16), .5)
        with patch('demucs.hf.load_safetensors_model', return_value=Model()), \
                patch('demucs.apply.apply_model', side_effect=tiny_infer) as infer:
            result = separate(TestJob(), source, 44100, {'device': 'cpu', 'model_path': str(model_file),
                                                       'weight_sha256': sha256_file(model_file)})
        self.assertEqual(infer.call_count, 1)
        self.assertEqual(len(result['stems']), 4)
        self.assertEqual(result['timing']['effective_forward_segment_seconds'], 7.8)
        for stem in result['stems']:
            data, rate = sf.read(self.root/stem['path'], dtype='float32')
            np.testing.assert_allclose(data, expected, rtol=0, atol=1e-6)


if __name__ == '__main__':
    unittest.main()
