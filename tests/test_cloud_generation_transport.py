"""Deterministic transport contract tests, not model-quality validation."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cloud import run_generation as transport


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(struct.pack("<h", 1000) * 160000)
    return stream.getvalue()


class FakeTunnel:
    data = wav_bytes()
    failure = None
    cancel = False
    submissions = []
    parameters = {"seed": 1}

    def __init__(self, registry, directory):
        self.directory = directory
        self.closed = False

    def open(self):
        return {"ok": True}

    def close(self):
        self.closed = True

    def call(self, method, path, body=None):
        if path.endswith("/cancel"):
            type(self).cancel = True
            return {"status": "cancelled"}
        if method == "POST":
            type(self).submissions.append(body["request_id"])
            self.job = body["request_id"]
            if type(self).failure == "connection_once":
                type(self).failure = None
                raise transport.NetworkError("Simulated lost POST acknowledgement")
        artifact = {"id": "audio.wav", "sha256": hashlib.sha256(self.data).hexdigest(),
                    "bytes": len(self.data), "sample_rate": 16000, "channels": 1, "duration_seconds": 10}
        if self.failure == "checksum":
            artifact["sha256"] = "0" * 64
        if self.failure == "path":
            artifact["id"] = "../../secrets"
        if self.failure == "size":
            artifact["bytes"] = transport.MAX_BYTES + 1
        return {"job_id": self.job, "status": "ready", "result": {
            "artifacts": [artifact], "model": {"id": "ace-step-1.5-xl-turbo", "revision": "test-only"}, "parameters": self.parameters}}

    @contextmanager
    def response(self, method, path, body=None, timeout=5):
        yield io.BytesIO(self.data)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.request = {"schema_version": 1, "job_id": uuid.uuid4().hex, "kind": "generate",
                        "prompt": "Gentle jazz piano", "duration_seconds": 10, "seed": 1,
                        "source": {"project_id": "test", "revision": 0, "bpm": 120, "timeline_start": 0}}
        self.registry = {"available": True, "model_id": "ace-step-1.5-xl-turbo"}
        self.path = self.directory / "request.json"
        transport.atomic_json(self.path, self.request)
        FakeTunnel.failure = None
        FakeTunnel.cancel = False
        FakeTunnel.submissions = []
        FakeTunnel.parameters = {"seed": 1}

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self):
        return transport.run(self.path, self.registry, FakeTunnel)

    def test_valid_download_publishes_after_hash_and_audio_checks(self):
        result = self.run_job()
        self.assertEqual(result["audio"]["duration_seconds"], 10)
        self.assertEqual(len(result["waveform_peaks"]), 128)
        self.assertGreater(max(result["waveform_peaks"]), 0)
        self.assertTrue((self.directory / "audio.wav").is_file())
        self.assertTrue((self.directory / "result.json").is_file())
        self.assertFalse((self.directory / "audio.wav.partial").exists())

    def test_retry_after_lost_post_uses_identical_request_id(self):
        FakeTunnel.failure = "connection_once"
        self.run_job()
        self.assertEqual(FakeTunnel.submissions, [self.request["job_id"]] * 2)

    def test_maximum_unicode_prompt_and_lyrics_survive_provenance_validation(self):
        self.request.update(prompt="\u97f3" * 2000, lyrics="\u4e50" * 4096)
        transport.atomic_json(self.path, self.request)
        FakeTunnel.parameters = {"prompt": self.request["prompt"], "lyrics": self.request["lyrics"], "seed": 1}
        result = self.run_job()
        self.assertEqual(result["parameters"]["lyrics"], self.request["lyrics"])
        self.assertTrue((self.directory / "audio.wav").is_file())

    def test_oversized_provenance_never_publishes(self):
        FakeTunnel.parameters = {"lyrics": "x" * 32768}
        with self.assertRaises(transport.GenerationError):
            self.run_job()
        self.assertFalse((self.directory / "result.json").exists())

    def test_corrupt_or_unbounded_artifact_never_publishes(self):
        for failure in ("checksum", "path", "size"):
            with self.subTest(failure=failure):
                FakeTunnel.failure = failure
                with self.assertRaises(transport.GenerationError):
                    self.run_job()
                self.assertFalse((self.directory / "result.json").exists())
                self.assertFalse((self.directory / "audio.wav").exists())

    def test_cancel_sends_cloud_request_no_candidate(self):
        (self.directory / "cancel").touch()
        with self.assertRaises(transport.Cancelled):
            self.run_job()
        self.assertTrue(FakeTunnel.cancel)
        self.assertFalse((self.directory / "result.json").exists())

    def test_reject_invalid_requests_before_submission(self):
        for key, value in (("duration_seconds", float("nan")), ("duration_seconds", 121),
                           ("seed", True), ("prompt", ""), ("lyrics", "a" * 4097),
                           ("job_id", "../../unsafe"), ("meter_numerator", 7)):
            with self.subTest(key=key, value=str(value)[:20]):
                bad = dict(self.request, **{key: value})
                with self.assertRaises(transport.GenerationError):
                    transport.build_payload(bad, self.registry)
        self.assertEqual(FakeTunnel.submissions, [])

    def test_bad_manifest_duration_rejected(self):
        path = self.directory / "bad.wav"
        path.write_bytes(FakeTunnel.data)
        with self.assertRaises(transport.GenerationError):
            transport.inspect_wav(path, {"sample_rate": 16000, "channels": 1, "duration_seconds": 11, "sha256": "0" * 64})

    def test_silent_wav_rejected(self):
        path = self.directory / "silent.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
            out.writeframes(b"\0" * 32000)
        with self.assertRaises(transport.GenerationError):
            transport.inspect_wav(path, {"sample_rate": 16000, "channels": 1, "duration_seconds": 1, "sha256": "0" * 64})

    def test_no_runtime_no_network(self):
        self.registry["available"] = False
        with self.assertRaises(transport.GenerationError):
            self.run_job()
        self.assertEqual(FakeTunnel.submissions, [])

    def test_local_disk_error_is_not_retried_as_network_failure(self):
        with patch.object(transport, "download", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_job()
        self.assertEqual(len(FakeTunnel.submissions), 1)


if __name__ == "__main__":
    unittest.main()
