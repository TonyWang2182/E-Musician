"""Worker contract tests: stdlib suite plus numerical tests in the ML environments."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from scripts.audio_analysis.common import (AnalysisError, Cancelled, Job, atomic_json, read_json,
                                           sha256_file, validate_notes, validate_request)


def request(root, kind="transcribe"):
    return {"schema_version": 1, "job_id": "unit-job", "kind": kind, "analysis_root": str(root),
            "source_path": str(root / "source.wav"), "source_offset_seconds": 0,
            "duration_seconds": 4, "source": {"project_id": "project", "clip_id": "clip"}}


class WorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_request_defaults_and_preserved_source(self):
        result = validate_request(request(self.root))
        self.assertEqual(result["parameters"]["minimum_note_ms"], 80.)
        self.assertEqual(result["preset"], "basic-pitch")
        self.assertEqual(result["source"]["project_id"], "project")

    def test_request_rejects_nonfinite_and_overlong_ranges(self):
        for value in (float("nan"), float("inf"), -1, 0, True, 601):
            with self.subTest(value=value), self.assertRaises(AnalysisError):
                validate_request({**request(self.root), "duration_seconds": value})

    def test_bad_parameters_and_fractional_pitch_rejected(self):
        for params in ({"shell": "command"}, {"min_pitch": 34.5}, {"min_pitch": 80, "max_pitch": 40},
                       {"onset_threshold": -1}, {"frame_threshold": True}):
            with self.subTest(params=params), self.assertRaises(AnalysisError):
                validate_request({**request(self.root), "parameters": params})

    def test_drum_and_other_stem_do_not_masquerade_as_pitched_transcription(self):
        for role in ("drums", "other"):
            value = request(self.root)
            value["source"]["input_role"] = role
            with self.assertRaisesRegex(AnalysisError, "not drum classification"):
                validate_request(value)

    def test_other_requires_explicit_pitched_profile_and_drums_still_rejected(self):
        value = request(self.root)
        value["source"]["input_role"] = "other"
        for profile in ("piano", "bass", "guitar", "vocals"):
            result = validate_request({**value, "parameters": {"instrument": profile}})
            self.assertEqual(result["parameters"]["instrument"], profile)
        for profile in ("auto", "unknown", "", True):
            with self.subTest(profile=profile), self.assertRaises(AnalysisError):
                validate_request({**value, "parameters": {"instrument": profile}})
        value["source"]["input_role"] = "drums"
        with self.assertRaisesRegex(AnalysisError, "not drum classification"):
            validate_request({**value, "parameters": {"instrument": "piano"}})

    def test_registered_presets_only(self):
        with self.assertRaises(AnalysisError):
            validate_request({**request(self.root), "preset": "http://arbitrary-model"})
        for kind in ("separate", "transcribe", "chords"):
            self.assertEqual(validate_request(request(self.root, kind))["kind"], kind)

    def test_six_stem_and_quality_profiles_are_bounded(self):
        value = request(self.root, "separate")
        defaults = validate_request(value)["parameters"]
        self.assertEqual((defaults["stems"], defaults["quality"]), (4, "fast"))
        six = validate_request({**value, "parameters": {"stems": 6, "quality": "quality"}})
        self.assertEqual(six["parameters"]["stems"], 6)
        self.assertEqual(validate_request({**value, "preset": "htdemucs_6s"})["parameters"]["stems"], 6)
        for parameters in ({"stems": 5}, {"stems": 4.5}, {"stems": True}, {"quality": "unlimited"}):
            with self.subTest(parameters=parameters), self.assertRaises(AnalysisError):
                validate_request({**value, "parameters": parameters})
        from scripts.audio_analysis.providers import separation_settings
        self.assertEqual(separation_settings(six["parameters"]), {"overlap": .5, "shifts": 2})
        self.assertEqual(separation_settings(defaults), {"overlap": .25, "shifts": 0})

    def test_instrument_profiles_respect_manual_ranges_and_source_roles(self):
        value = request(self.root)
        bass = validate_request({**value, "parameters": {"instrument": "bass"}})["parameters"]
        self.assertEqual((bass["min_pitch"], bass["max_pitch"]), (23, 72))
        manual = validate_request({**value, "parameters": {"instrument": "bass", "max_pitch": 90}})["parameters"]
        self.assertEqual(manual["max_pitch"], 90)
        value["source"]["input_role"] = "guitar"
        auto = validate_request(value)["parameters"]
        self.assertEqual((auto["min_pitch"], auto["max_pitch"]), (28, 96))
        with self.assertRaises(AnalysisError):
            validate_request({**value, "parameters": {"instrument": "drums"}})

    def test_chord_vocabulary_is_explicit_and_validated(self):
        value = request(self.root, "chords")
        self.assertEqual(validate_request(value)["parameters"]["vocabulary"], "extended")
        self.assertEqual(validate_request({**value, "parameters": {"vocabulary": "triads"}})["parameters"]["vocabulary"], "triads")
        with self.assertRaises(AnalysisError):
            validate_request({**value, "parameters": {"vocabulary": "arbitrary"}})

    def test_job_ids_are_not_paths(self):
        for job_id in ("../outside", "x/y", "", "x" * 100, "x;command"):
            with self.subTest(job_id=job_id), self.assertRaises(AnalysisError):
                validate_request({**request(self.root), "job_id": job_id})

    def make_job(self):
        directory = self.root / "cache/jobs/unit-job"
        directory.mkdir(parents=True)
        file = directory / "request.json"
        atomic_json(file, request(self.root))
        return Job(file)

    def test_job_folder_binding(self):
        file = self.root / "request.json"
        atomic_json(file, request(self.root))
        with self.assertRaisesRegex(AnalysisError, "Job must reside"):
            Job(file)

    def test_cancel_is_terminal_and_does_not_publish_result(self):
        job = self.make_job()
        (job.directory / "cancel").touch()
        with self.assertRaises(Cancelled):
            job.progress("starting", .1)
        self.assertFalse((job.directory / "result.json").exists())

    def test_progress_is_atomic_and_bounded(self):
        job = self.make_job()
        job.progress("model", 2.)
        data = read_json(job.directory / "progress.json")
        self.assertEqual(data["progress"], 1.)
        self.assertFalse((job.directory / "progress.json.tmp").exists())

    def test_existing_result_is_immutable(self):
        job = self.make_job()
        atomic_json(job.directory / "result.json", {"sentinel": 12})
        with self.assertRaisesRegex(AnalysisError, "immutable"):
            Job(job.directory / "request.json")
        self.assertEqual(read_json(job.directory / "result.json"), {"sentinel": 12})

    def test_json_rejects_nonfinite_and_bounded_size(self):
        file = self.root / "data.json"
        file.write_text('{"a":NaN}', encoding="utf-8")
        with self.assertRaises(AnalysisError):
            read_json(file)
        file.write_text('{"a":0}', encoding="utf-8")
        with self.assertRaises(AnalysisError):
            read_json(file, 2)

    def test_sha256_is_content_based(self):
        first = self.root / "a.wav"
        second = self.root / "b.wav"
        first.write_bytes(b"audio")
        second.write_bytes(b"audio")
        self.assertEqual(sha256_file(first), sha256_file(second))
        second.write_bytes(b"changed")
        self.assertNotEqual(sha256_file(first), sha256_file(second))

    def test_model_integrity_checked_before_deserialization(self):
        from scripts.audio_analysis.providers import checked_model
        path = self.root / "model.onnx"
        path.write_bytes(b"model bytes")
        class DummyJob:
            def check_cancelled(self):
                pass
        entry = {"model_path": str(path), "weight_sha256": sha256_file(path)}
        self.assertEqual(checked_model(entry, DummyJob()), path)
        path.write_bytes(b"changed bytes")
        with self.assertRaisesRegex(AnalysisError, "SHA-256"):
            checked_model(entry, DummyJob())

    def test_notes_keep_unquantized_seconds_and_integral_velocity(self):
        note = {"pitch": 60, "start_seconds": .12345, "duration_seconds": .11111, "velocity": 72}
        normalized = validate_notes([note], 2.)[0]
        self.assertEqual(normalized["start_seconds"], .12345)
        self.assertEqual(normalized["channel"], 1)

    def test_invalid_notes_rejected_without_silent_trim(self):
        base = {"pitch": 60, "start_seconds": 1., "duration_seconds": .5, "velocity": 72}
        for changes in ({"pitch": 60.5}, {"pitch": 128}, {"velocity": 0}, {"channel": 0},
                        {"start_seconds": -.1}, {"duration_seconds": 0}, {"duration_seconds": 2},
                        {"start_seconds": math.nan}):
            with self.subTest(changes=changes), self.assertRaises(AnalysisError):
                validate_notes([{**base, **changes}], 2.)


try:
    import numpy as np
    import scipy
except ImportError:
    np = None


@unittest.skipIf(np is None, "Numerical tests require NumPy/SciPy and run separately in the isolated chord environment")
class ChordDecoderTests(unittest.TestCase):
    def test_waveform_envelope_preserves_actual_audio_and_stereo_peaks(self):
        from scripts.audio_analysis.providers import waveform_peaks
        source = np.zeros((256, 2), dtype=np.float32)
        source[1, 1], source[80, 0], source[-1, 0] = -.8, .4, 1.25
        original = source.copy()
        peaks = waveform_peaks(source)
        self.assertEqual(len(peaks), 128)
        self.assertAlmostEqual(peaks[0], .8)
        self.assertAlmostEqual(peaks[40], .4)
        self.assertAlmostEqual(peaks[-1], 1.25)
        np.testing.assert_array_equal(source, original)
        self.assertEqual(max(waveform_peaks(np.zeros((3, 1), dtype=np.float32))), 0.)

    def test_extended_vocabulary_keeps_sevenths_and_half_diminished(self):
        from scripts.audio_analysis.chords import chord_labels, templates, decode_chroma
        labels = chord_labels("extended")
        self.assertEqual(len(labels), 133)
        expected = ["C:maj7", "D:min7", "G:7", "B:hdim7", "C:maj"]
        matrix = templates("extended")
        features = np.column_stack([np.repeat(matrix[labels.index(name), :, None], 40, axis=1) for name in expected])
        regions = decode_chroma(features, np.ones(features.shape[1]), .05, 10., .55, .15, vocabulary="extended")
        self.assertEqual([item["label"] for item in regions], expected)
        self.assertEqual(regions[-1]["end_seconds"], 10.)

    def test_extended_actual_audio_identifies_cmaj7_then_g7(self):
        from scripts.audio_analysis.chords import pitch_class_features, decode_chroma
        rate = 22050
        times = np.arange(4 * rate) / rate
        samples = np.zeros_like(times)
        for first, last, pitches in ((0, 2 * rate, (60, 64, 67, 71)), (2 * rate, 4 * rate, (55, 59, 62, 65))):
            for pitch in pitches:
                samples[first:last] += .1 * np.sin(2 * np.pi * 440 * 2 ** ((pitch - 69) / 12) * times[first:last])
        chroma, energy = pitch_class_features(samples.astype(np.float32))
        regions = decode_chroma(chroma, energy, 512 / rate, 4., .55, .15, vocabulary="extended")
        self.assertEqual([item["label"] for item in regions], ["C:maj7", "G:7"])
        self.assertLess(abs(regions[0]["end_seconds"] - 2.), .08)

    def test_extended_symmetric_chord_is_flagged_uncertain(self):
        from scripts.audio_analysis.chords import chord_labels, templates, decode_chroma
        labels = chord_labels("extended")
        template = templates("extended")[labels.index("C:dim7")]
        regions = decode_chroma(np.repeat(template[:, None], 40, axis=1), np.ones(40), .05, 2., .55, .15, vocabulary="extended")
        self.assertEqual(len(regions), 1)
        self.assertIn(regions[0]["label"], ("C:dim7", "D#:dim7", "F#:dim7", "A:dim7"))
        self.assertTrue(regions[0]["uncertain"])

    def test_extended_no_chord_state_does_not_overflow_int8(self):
        from scripts.audio_analysis.chords import decode_chroma
        regions = decode_chroma(np.zeros((12, 25)), np.zeros(25), .05, 1.25, .55, .15, vocabulary="extended")
        self.assertEqual(regions, [{"start_seconds": 0., "end_seconds": 1.25, "label": "N", "score": 0., "uncertain": False}])

    def test_actual_stft_features_keep_c_major_a_minor_and_source_timing(self):
        from scripts.audio_analysis.chords import pitch_class_features, decode_chroma
        rate = 22050
        times = np.arange(2 * rate) / rate
        samples = np.zeros_like(times)
        for first, last, pitches in ((0, rate, (60, 64, 67)), (rate, 2 * rate, (57, 60, 64))):
            for pitch in pitches:
                samples[first:last] += .1 * np.sin(2 * np.pi * 440 * 2 ** ((pitch - 69) / 12) * times[first:last])
        chroma, energy = pitch_class_features(samples.astype(np.float32))
        regions = decode_chroma(chroma, energy, 512 / rate, 2., .55, .15)
        self.assertEqual([x["label"] for x in regions], ["C:maj", "A:min"])
        self.assertLess(abs(regions[0]["end_seconds"] - 1.), .08)
        self.assertEqual(regions[-1]["end_seconds"], 2.)

    def test_exact_major_then_minor_with_no_chord_and_coverage(self):
        from scripts.audio_analysis.chords import decode_chroma, templates
        features = np.column_stack([np.repeat(templates()[0, :, None], 40, axis=1),
                                    np.repeat(templates()[21, :, None], 40, axis=1), np.zeros((12, 20))])
        rms = np.concatenate([np.ones(80), np.zeros(20)])
        regions = decode_chroma(features, rms, .05, 5., .55, .15)
        self.assertEqual([x["label"] for x in regions], ["C:maj", "A:min", "N"])
        self.assertEqual(regions[0]["start_seconds"], 0.)
        self.assertEqual(regions[-1]["end_seconds"], 5.)
        self.assertTrue(all(a["end_seconds"] == b["start_seconds"] for a, b in zip(regions, regions[1:])))

    def test_ambiguous_energy_is_not_mislabeled_no_chord(self):
        from scripts.audio_analysis.chords import decode_chroma
        regions = decode_chroma(np.ones((12, 30)), np.ones(30), .05, 1.5, .55, .15)
        self.assertNotEqual(regions[0]["label"], "N")
        self.assertTrue(regions[0]["uncertain"])

    def test_silence_has_no_chord_without_fake_probability(self):
        from scripts.audio_analysis.chords import decode_chroma
        regions = decode_chroma(np.zeros((12, 10)), np.zeros(10), .05, .5, .55, .15)
        self.assertEqual(regions, [{"start_seconds": 0., "end_seconds": .5, "label": "N", "score": 0., "uncertain": False}])


if __name__ == "__main__":
    unittest.main()
