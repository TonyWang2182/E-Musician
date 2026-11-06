"""Small synthetic CPU checks; fixtures are created and removed only on cloud."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
from analyze import ROOT, REPORT_ROOT, measure


class MeasurementsTests(unittest.TestCase):
    def setUp(self):
        REPORT_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-cpu-', dir=REPORT_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'fixture.wav'

    def test_twenty_second_windows_and_duration_weighted_silence(self):
        audio = np.full((41*8000, 1), .25, dtype=np.float32)
        audio[20*8000:40*8000] = 0
        sf.write(self.path, audio, 8000, subtype='FLOAT')
        result = measure(self.path)
        self.assertEqual(len(result['windows_20_seconds']), 3)
        self.assertEqual(result['windows_20_seconds'][-1]['end_seconds'], 41)
        self.assertAlmostEqual(result['overall']['silence_duration_fraction'], 20/41)
        self.assertAlmostEqual(result['overall']['rms_linear'], .25*np.sqrt(21/41))
        self.assertIsNone(result['overall']['lr_pearson_correlation'])

    def test_correlation_and_digital_rail_are_not_conflated_with_quality(self):
        wave = np.sin(np.arange(48000)*2*np.pi*440/48000)*.5
        stereo = np.stack([wave, -wave], axis=1)
        stereo[0] = [1, -1]
        sf.write(self.path, stereo, 48000, subtype='FLOAT')
        result = measure(self.path)['overall']
        self.assertAlmostEqual(result['lr_pearson_correlation'], -1)
        self.assertAlmostEqual(result['digital_rail_sample_fraction'], 1/48000)
        self.assertEqual(result['over_full_scale_sample_fraction'], 0)

    def test_nonfinite_audio_is_flagged_without_nonfinite_json_values(self):
        audio = np.full((8000, 1), .1)
        audio[0, 0] = np.nan
        audio[1, 0] = np.inf
        sf.write(self.path, audio, 8000, subtype='FLOAT')
        result = measure(self.path)
        self.assertFalse(result['overall']['all_samples_finite'])
        self.assertEqual(result['overall']['nonfinite_samples'], 2)
        import json
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    if not ROOT.is_dir():
        raise RuntimeError('Synthetic audio tests must stay on cloud')
    unittest.main(verbosity=2)
