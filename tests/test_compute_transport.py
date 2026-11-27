"""Real file/HTTP boundary tests; no model-quality claims or GPU inference."""
import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.cloud import compute_client as c
from scripts.cloud import run_analysis as a


class Response(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


class ArtifactTunnel:
    def __init__(self, data):
        self.data = data
    def response(self, *args, **kwargs):
        return Response(self.data)


class ComputeTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, data=b"actual-result", name="events.json"):
        return {"id": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def test_windows_reader_sharing_retries_only_atomic_publication(self):
        path = self.root / "progress.json"
        path.write_text('{"phase":"old"}')
        original = os.replace
        attempts = []
        def busy(source, destination):
            attempts.append(1)
            self.assertEqual(json.loads(path.read_text()), {"phase": "old"})
            if len(attempts) < 3:
                raise PermissionError("simulated Windows reader sharing")
            return original(source, destination)
        with patch("scripts.cloud.run_generation.os.replace", side_effect=busy):
            c.atomic_json(path, {"phase": "new"})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads(path.read_text()), {"phase": "new"})
        with patch("scripts.cloud.run_generation.os.replace", side_effect=PermissionError("permanent")):
            with self.assertRaises(PermissionError):
                c.atomic_json(path, {"phase": "not published"})
        self.assertEqual(json.loads(path.read_text()), {"phase": "new"})

    def test_verified_artifact_and_idempotent_download(self):
        data = b"same immutable content"
        r = {"artifacts": [self.artifact(data)]}
        c.download_artifacts(ArtifactTunnel(data), "job", r, self.root, lambda: False, lambda *args: None)
        c.download_artifacts(ArtifactTunnel(b"must not be read"), "job", r, self.root, lambda: False, lambda *args: None)
        self.assertEqual((self.root / "events.json").read_bytes(), data)

    def test_tamper_does_not_publish(self):
        with self.assertRaises(c.GenerationError):
            c.download_artifacts(ArtifactTunnel(b"bad!"), "job", {"artifacts": [self.artifact(b"good")]}, self.root, lambda: False, lambda *args: None)
        self.assertFalse((self.root / "events.json").exists())
        self.assertFalse((self.root / "events.json.download").exists())

    def test_short_body_reconnects_without_resubmitting_inference(self):
        data = b"complete artifact"
        class Interrupted:
            def __init__(self): self.calls = 0; self.reconnects = 0
            def response(self, method, path, **kwargs):
                self.calls += 1
                return Response(data[:3] if self.calls == 1 else data, len(data))
            def open(self): self.reconnects += 1
        transport = Interrupted()
        c.download_artifacts(transport, "job", {"artifacts": [self.artifact(data)]}, self.root, lambda: False, lambda *args: None)
        self.assertEqual(transport.reconnects, 1)
        self.assertEqual((self.root / "events.json").read_bytes(), data)

    def test_existing_content_is_preserved(self):
        (self.root / "events.json").write_text("existing user data")
        with self.assertRaises(c.GenerationError):
            c.download_artifacts(ArtifactTunnel(b"new"), "job", {"artifacts": [self.artifact(b"new")]}, self.root, lambda: False, lambda *args: None)
        self.assertEqual((self.root / "events.json").read_text(), "existing user data")

    def test_paths_reserved_names_and_duplicates_rejected(self):
        for name in ("../escape.wav", "C:/escape.wav", "result.json", "input.wav", "cancel", "a..b"):
            with self.subTest(name=name), self.assertRaises(c.GenerationError):
                c.download_artifacts(None, "job", {"artifacts": [self.artifact(name=name)]}, self.root, lambda: False, lambda *args: None)
        item = self.artifact()
        with self.assertRaises(c.GenerationError):
            c.download_artifacts(None, "job", {"artifacts": [item, item]}, self.root, lambda: False, lambda *args: None)

    def test_exact_model_never_substituted(self):
        config = {"providers": [{"kind": "transcribe", "model_id": "transkun", "available": True, "default": True},
                                {"kind": "transcribe", "model_id": "muscriptor", "available": False}]}
        self.assertEqual(c.select_model(config, "transcribe"), "transkun")
        with self.assertRaises(c.GenerationError):
            c.select_model(config, "transcribe", "muscriptor")
        with self.assertRaises(c.GenerationError):
            c.select_model(config, "score", "transkun")

    def test_lost_submit_response_reuses_same_id(self):
        payload = {"request_id": "same", "kind": "chords", "model_id": "chordmini", "parameters": {}}
        class LostReply:
            def __init__(self): self.posts = []; self.reopens = 0
            def open(self): self.reopens += 1
            def call(self, method, path, body=None):
                self.posts.append(body)
                if len(self.posts) == 1: raise c.NetworkError("lost reply after server committed")
                return {"job_id": "same", "status": "ready", "result": {"schema_version": 2, "kind": "chords", "model": {"id": "chordmini"}}}
        transport = LostReply()
        c.task(transport, payload, self.root, lambda: False, lambda *args: None, poll_seconds=0)
        self.assertEqual(transport.posts, [payload, payload])
        self.assertEqual(transport.reopens, 1)

    def test_cancel_unreachable_is_not_claimed_confirmed(self):
        class Offline:
            def call(self, *args): raise c.NetworkError("offline")
        with self.assertRaises(c.Cancelled):
            c.task(Offline(), {"request_id": "cancelled"}, self.root, lambda: True, lambda *args: None)
        receipt = c.read_json(self.root / "cancellation.json")
        self.assertFalse(receipt["remote_cancel_confirmed"])

    def test_result_identity_conflict_rejected(self):
        class Wrong:
            def call(self, *args): return {"job_id": "other", "status": "ready"}
        with self.assertRaises(c.GenerationError):
            c.task(Wrong(), {"request_id": "wanted"}, self.root, lambda: False, lambda *args: None)

    def test_freeze_only_selected_range_no_full_audio_array(self):
        import numpy as np
        import soundfile as sf
        source = self.root / "source.wav"
        sf.write(source, np.arange(32000, dtype=np.float32)[:, None] / 32000, 8000, subtype="FLOAT")
        request = {"source_path": str(source), "source": {}, "duration_seconds": 1., "source_offset_seconds": 2.}
        result = a.freeze(request, self.root, lambda: False, lambda *args: None)
        data, rate = sf.read(self.root / "input.wav")
        self.assertEqual(len(data), 8000)
        self.assertAlmostEqual(data[0], .5)
        self.assertEqual(result["source_start_sample"], 16000)
        self.assertEqual(result["frozen_input_sha256"], c.digest(self.root / "input.wav"))

    def test_freeze_source_identity_and_nonfinite_fail(self):
        import numpy as np
        import soundfile as sf
        source = self.root / "source.wav"
        sf.write(source, np.array([float("nan")] * 8000, dtype=np.float32), 8000, subtype="FLOAT")
        req = {"source_path": str(source), "source": {}, "duration_seconds": 1.}
        with self.assertRaises(c.GenerationError): a.freeze(req, self.root, lambda: False, lambda *args: None)
        req["source"] = {"source_sha256": "0" * 64}
        with self.assertRaises(c.GenerationError): a.freeze(req, self.root, lambda: False, lambda *args: None)
        self.assertFalse((self.root / "input.wav").exists())

    def result(self):
        return {"duration_seconds": 4., "time_basis": "input_relative_seconds", "model": {"id": "muscriptor"},
            "artifacts": [], "midi_tracks": [{"id": "piano", "name": "Piano", "instrument": "acoustic_piano", "program": 0, "channel": 1, "is_drum": False,
                "notes": [{"pitch": 60, "velocity": 100, "channel": 1, "start_seconds": .5, "duration_seconds": 1.}],
                "controllers": [{"controller": 64, "value": 127, "channel": 1, "time_seconds": .4}, {"controller": 64, "value": 0, "channel": 1, "time_seconds": 2.}]}],
            "chord_regions": [{"label": "C:maj9/G", "raw_label": "C:maj9/G", "start_seconds": 0., "end_seconds": 4., "score": None, "uncertain": True}],
            "structure_regions": [{"label": "Verse", "start_seconds": 0., "end_seconds": 4.}]}

    def test_multitrack_cc_and_chord_labels_retained(self):
        out = a.normalize(self.result(), {"job_id": "j", "kind": "score"}, {"duration_seconds": 4.}, {}, self.root, lambda: False)
        self.assertEqual(out["controllers"][0]["value"], 127)
        self.assertEqual(out["notes"][0]["track_id"], "piano")
        self.assertEqual(out["chord_regions"][0]["label"], "C:maj9/G")
        self.assertIsNone(out["chord_regions"][0]["score"])
        self.assertEqual(out["summary"]["controller_count"], 2)
        self.assertEqual(out["summary"]["annotation_count"], 1)

    def test_out_of_range_and_duplicate_tracks_rejected(self):
        result = self.result()
        result["midi_tracks"][0]["controllers"][0]["time_seconds"] = 5.
        with self.assertRaises(c.GenerationError):
            a.normalize(result, {"job_id": "j", "kind": "score"}, {"duration_seconds": 4.}, {}, self.root, lambda: False)
        result = self.result(); result["midi_tracks"].append(result["midi_tracks"][0].copy())
        with self.assertRaises(c.GenerationError):
            a.normalize(result, {"job_id": "j", "kind": "score"}, {"duration_seconds": 4.}, {}, self.root, lambda: False)

    def test_nonfinite_json_and_local_parameter_knobs_rejected(self):
        file = self.root / "bad.json"; file.write_text('{"x":NaN}')
        with self.assertRaises(ValueError): c.read_json(file)
        directory = (self.root / "cache/jobs/job"); directory.mkdir(parents=True)
        req = {"schema_version": 1, "job_id": "job", "kind": "transcribe", "analysis_root": str(self.root), "source_path": str(self.root / "x.wav"),
               "source": {}, "duration_seconds": 1., "parameters": {"onset_threshold": .2}}
        with self.assertRaises(c.GenerationError): a.validate(req, directory)

    def test_result_input_digest_mismatch_never_publishes(self):
        class WrongInput:
            def call(self, *args):
                return {"job_id": "same", "status": "ready", "result": {"schema_version": 2, "kind": "chords", "model": {"id": "chordmini"}, "input": {"sha256": "1" * 64}}}
        with self.assertRaises(c.GenerationError):
            c.task(WrongInput(), {"request_id": "same", "kind": "chords", "model_id": "chordmini", "input": {"sha256": "0" * 64}},
                   self.root, lambda: False, lambda *args: None)


if __name__ == "__main__": unittest.main()
