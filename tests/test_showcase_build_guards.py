"""Build routing checks only; no compiler or original binary is invoked."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dev_showcase
import dev_audio_input


class RecorderStub:
    calls = []
    failures = []
    def __init__(self, *args): pass
    def execute(self, args, **kwargs): self.calls.append(args)
    def preflight_failure(self, message): self.failures.append(message)


class BuildGuardTests(unittest.TestCase):
    def run_main(self, module, arguments, cache=''):
        RecorderStub.calls, RecorderStub.failures = [], []
        with patch.object(module, 'Recorder', RecorderStub), patch.object(sys, 'argv', ['tool', *arguments]), patch.object(Path, 'read_text', return_value=cache):
            result = module.main()
        return result, list(RecorderStub.calls), list(RecorderStub.failures)

    def test_wrong_mode_and_output_refused_for_build_and_test(self):
        for action in ('build', 'test'):
            for root, mode in ((dev_showcase.OUTPUTS['recording'], 'OFF'), (dev_showcase.OUTPUTS['showcase']+'-wrong', 'ON'), (dev_showcase.OUTPUTS['showcase'], 'OFF')):
                with self.subTest(action=action, root=root, mode=mode):
                    cache=f'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH={root}\nEMUSICIAN_SHOWCASE:BOOL={mode}\n'
                    result, calls, failures=self.run_main(dev_showcase, ['showcase', action], cache)
                    self.assertEqual(result, 2)
                    self.assertEqual(calls, [])
                    self.assertEqual(len(failures), 1)

    def test_correct_variant_routes_to_build(self):
        for variant, mode in (('recording','OFF'), ('showcase','ON')):
            cache=f'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH={dev_showcase.OUTPUTS[variant]}\nEMUSICIAN_SHOWCASE:BOOL={mode}\n'
            result,calls,failures=self.run_main(dev_showcase,[variant,'build'],cache)
            self.assertEqual(result,0)
            self.assertEqual(calls[0][:2],['cmake','--build'])
            self.assertFalse(failures)

    def test_original_configure_explicitly_disables_showcase(self):
        result,calls,failures=self.run_main(dev_audio_input,['configure'])
        self.assertEqual(result,0)
        self.assertIn('-DEMUSICIAN_SHOWCASE=OFF',calls[0])

    def test_original_build_refuses_showcase_cache(self):
        cache=f'EMUSICIAN_RUNTIME_OUTPUT_ROOT:PATH={dev_audio_input.OUTPUT}\nEMUSICIAN_SHOWCASE:BOOL=ON\n'
        result,calls,failures=self.run_main(dev_audio_input,['build'],cache)
        self.assertEqual(result,2)
        self.assertFalse(calls)
        self.assertTrue(failures)


if __name__ == '__main__': unittest.main()
