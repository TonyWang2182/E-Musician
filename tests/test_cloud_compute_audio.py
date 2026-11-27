"""CPU regression for adapter-specific audio dependencies; no model imports."""
import builtins
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/cloud'))
from compute.adapters import read_audio


class AudioDependencyTests(unittest.TestCase):
    def modules(self, *, finite=True):
        audio = Mock(name='decoded_audio')
        numpy = types.SimpleNamespace(isfinite=Mock(return_value=types.SimpleNamespace(all=lambda: finite)),
                                     float32='float32')
        soundfile = types.SimpleNamespace(read=Mock(return_value=(audio, 44100)))
        return audio, {'numpy': numpy, 'soundfile': soundfile}

    def test_original_and_already_matching_rates_do_not_require_scipy(self):
        original_import = builtins.__import__
        attempted = []
        def without_scipy(name, *args, **kwargs):
            if name == 'scipy' or name.startswith('scipy.'):
                attempted.append(name)
                raise ModuleNotFoundError("No module named 'scipy'")
            return original_import(name, *args, **kwargs)
        for target in (None, 44100):
            audio, modules = self.modules()
            with self.subTest(target=target), patch.dict(sys.modules, modules), patch('builtins.__import__', without_scipy):
                decoded, rate = read_audio('fixture.wav', target)
                self.assertIs(decoded, audio)
                self.assertEqual(rate, 44100)
                modules['soundfile'].read.assert_called_once_with('fixture.wav', dtype='float32', always_2d=True)
        self.assertEqual(attempted, [])

    def test_different_rate_still_uses_polyphase_resampling(self):
        audio, modules = self.modules()
        resampled = Mock(name='resampled_audio')
        converted = object()
        resampled.astype.return_value = converted
        resample = Mock(return_value=resampled)
        modules['scipy.signal'] = types.SimpleNamespace(resample_poly=resample)
        with patch.dict(sys.modules, modules):
            decoded, rate = read_audio('fixture.wav', 48000)
        resample.assert_called_once_with(audio, 160, 147, axis=0)
        resampled.astype.assert_called_once_with('float32')
        self.assertIs(decoded, converted)
        self.assertEqual(rate, 48000)

    def test_nonfinite_samples_still_fail_before_conversion(self):
        _, modules = self.modules(finite=False)
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(ValueError, 'nonfinite'):
            read_audio('fixture.wav')


if __name__ == '__main__':
    unittest.main()
