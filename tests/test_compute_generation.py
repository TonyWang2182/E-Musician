"""New generation protocol with mock transport and real PCM16 files.

No SSH, GPU, desktop process or language model is used. Task validation,
artifact hashing/download, WAV inspection and candidate publication are real.
"""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cloud import compute_client as client
from cloud import run_compute_generation as compute
from cloud import run_generation as legacy


def pcm16():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(struct.pack("<hh", 2000, -2000) * 10000)
    return stream.getvalue()


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class ComputeGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.directory = self.root / "owned-job"
        self.directory.mkdir()
        self.request = {"schema_version": 1, "job_id": uuid.uuid4().hex, "kind": "generate", "model_id": "yue2",
                        "prompt": "Instrumental dark jungle", "lyrics": "", "duration_seconds": 12., "seed": 16384,
                        "bpm": 170, "meter_numerator": 4, "meter_denominator": 4,
                        "source": {"project_id": "owned", "revision": 4, "bpm": 170, "timeline_start": 2.5,
                                   "meter_numerator": 4, "meter_denominator": 4}}
        self.path = self.directory / "request.json"
        self.write_request()
        self.config = {"schema_version": 1, "available": True,
                       "providers": [{"kind": "generate", "model_id": "yue2", "execution": "cloud", "available": True}],
                       "defaults": {"generate": "yue2"}, "test_marker": "explicit-test-config"}
        self.audio = pcm16()
        self.artifact = {"id": "audio.wav", "bytes": len(self.audio), "sha256": hashlib.sha256(self.audio).hexdigest(),
                         "sample_rate": 16000, "channels": 1, "duration_seconds": 1.25}
        self.extra = {"warnings": [f"Synthetic limitation {i}" for i in range(22)], "truncated": True,
                      "conditioning": {"timing_is_exact": False, "requested_duration_seconds": 12.},
                      "processing": {"semantic_tokens": 31}, "metrics": {"model_seconds": .25}}
        self.instances = []
        self.wrong_model = False
        self.tamper = False

    def tearDown(self):
        self.temporary.cleanup()

    def write_request(self):
        self.path.write_text(json.dumps(self.request), encoding="utf-8")

    def tunnel_factory(self, config, directory):
        fixture = self
        class Tunnel:
            def __init__(self):
                self.config = deepcopy(config)
                self.directory = directory
                self.closed = False
                self.calls, self.downloads = [], []
                self.opened = 0
            def open(self): self.opened += 1
            def close(self): self.closed = True
            def call(self, method, path, body=None):
                self.calls.append((method, path, deepcopy(body)))
                if path == "/capabilities": return deepcopy(fixture.config)
                fixture.assertEqual((method, path), ("POST", "/jobs"))
                model = "wrong-model" if fixture.wrong_model else body["model_id"]
                parameters = body.get("parameters", {k: v for k, v in body.items() if k not in {"request_id", "kind", "model_id"}})
                artifact = {**fixture.artifact, "sha256": "0" * 64} if fixture.tamper else fixture.artifact
                return {"job_id": body["request_id"], "status": "ready", "result": {
                    "schema_version": 2, "kind": "generate", "model": {"id": model, "revision": "synthetic-no-model"},
                    "parameters": deepcopy(parameters), "artifacts": [deepcopy(artifact)], **deepcopy(fixture.extra)}}
            def response(self, method, path, **_kwargs):
                self.downloads.append((method, path))
                return Response(fixture.audio)
        instance = Tunnel()
        self.instances.append(instance)
        return instance

    def test_new_protocol_preserves_actual_audio_and_bounded_limitations(self):
        result = compute.run(self.path, self.config, self.tunnel_factory)
        self.assertEqual(result["execution"], "cloud")
        self.assertEqual(result["model"]["id"], "yue2")
        self.assertEqual(result["source"], self.request["source"])
        self.assertEqual(result["audio"]["duration_seconds"], 1.25)
        self.assertEqual(result["parameters"]["duration_seconds"], 12.)
        self.assertEqual(result["warnings"], self.extra["warnings"])
        self.assertEqual(result["limitations"], self.extra["warnings"][:20])
        self.assertEqual(result["completion"], {"truncated": True, "stages": {}, "reason": "token_budget", "timing_is_exact": False})
        self.assertEqual(result["conditioning"], self.extra["conditioning"])
        self.assertEqual(result["processing"], self.extra["processing"])
        self.assertEqual(result["metrics"]["model_seconds"], .25)
        self.assertGreaterEqual(result["metrics"]["desktop_elapsed_seconds"], 0)
        self.assertEqual((self.directory / "audio.wav").read_bytes(), self.audio)
        self.assertEqual(result["audio"]["sha256"], self.artifact["sha256"])
        self.assertEqual(len(result["waveform_peaks"]), 128)
        self.assertGreater(max(result["waveform_peaks"]), 0)
        self.assertEqual(client.read_json(self.directory / "result.json"), result)
        self.assertEqual(client.read_json(self.directory / "progress.json")["phase"], "ready")
        self.assertTrue(self.instances[0].closed)
        with self.assertRaises(client.GenerationError): compute.run(self.path, self.config, self.tunnel_factory)
        self.assertEqual(len(self.instances), 1, "Immutable candidate retry must not resubmit inference")

    def test_model_stop_and_missing_truncation_are_not_conflated(self):
        for index, (truncated, reason) in enumerate(((False, "model_stop"), (None, "unknown"), ("missing", "unknown"))):
            with self.subTest(truncated=truncated):
                directory = self.root / f"variant-{index}"; directory.mkdir()
                path = directory / "request.json"; path.write_text(json.dumps(self.request), encoding="utf-8")
                if truncated == "missing": self.extra.pop("truncated", None)
                else: self.extra["truncated"] = truncated
                self.extra.pop("conditioning", None)
                result = compute.run(path, self.config, self.tunnel_factory)
                self.assertEqual(result["completion"], {"truncated": None if truncated == "missing" else truncated, "stages": {},
                                                        "reason": reason, "timing_is_exact": False})
                self.assertTrue(self.instances[-1].closed)

    def test_actual_yue_stage_dictionary_is_normalized_without_losing_stages(self):
        for index, stages in enumerate(({"abc": False, "semantic": True}, {"abc": True, "semantic": False}, {"abc": False, "semantic": False})):
            with self.subTest(stages=stages):
                directory = self.root / f"stages-{index}"; directory.mkdir()
                path = directory / "request.json"; path.write_text(json.dumps(self.request), encoding="utf-8")
                self.extra["truncated"] = stages
                result = compute.run(path, self.config, self.tunnel_factory)
                expected = any(stages.values())
                self.assertIs(result["truncated"], expected)
                self.assertIs(result["completion"]["truncated"], expected)
                self.assertEqual(result["completion"]["stages"], stages)
                self.assertEqual(result["completion"]["reason"], "token_budget" if expected else "model_stop")
                self.assertEqual(client.read_json(directory / "result.json")["completion"], result["completion"])
                self.assertTrue(self.instances[-1].closed)

    def test_malformed_stage_dictionary_never_publishes(self):
        for index, invalid in enumerate(({}, {"semantic": 1}, {"abc": "false"}, {"semantic": None}, {"semantic": {}}, [], "true", 0)):
            with self.subTest(invalid=invalid):
                directory = self.root / f"invalid-{index}"; directory.mkdir()
                path = directory / "request.json"; path.write_text(json.dumps(self.request), encoding="utf-8")
                self.extra["truncated"] = invalid
                with self.assertRaises(client.GenerationError): compute.run(path, self.config, self.tunnel_factory)
                self.assertFalse((directory / "result.json").exists())
                self.assertTrue(self.instances[-1].closed)

    def test_dispatcher_uses_request_compute_root_instead_of_environment(self):
        actual_root = self.root / "request-deployment"; actual_root.mkdir()
        self.config["test_marker"] = "request-root-wins"
        (actual_root / "compute-registry.json").write_text(json.dumps(self.config), encoding="utf-8")
        wrong_root = self.root / "environment-deployment"; wrong_root.mkdir()
        (wrong_root / "compute-registry.json").write_text('{"schema_version":1,"available":false}', encoding="utf-8")
        self.request["compute_root"] = str(actual_root); self.write_request()
        real_compute_run = compute.run
        def new_protocol(path): return real_compute_run(path, tunnel_factory=self.tunnel_factory)
        def forbidden_legacy(*_args): raise AssertionError("Non-default compute root incorrectly fell through to legacy transport")
        with patch.dict(os.environ, {"EMUSICIAN_COMPUTE_ROOT": str(wrong_root)}), patch.object(compute, "run", side_effect=new_protocol) as routed:
            result = legacy.run(self.path, tunnel_factory=forbidden_legacy)
        routed.assert_called_once_with(self.path)
        self.assertEqual(self.instances[0].config["test_marker"], "request-root-wins")
        self.assertEqual(result["model"]["id"], "yue2")
        self.assertEqual(result["completion"]["reason"], "token_budget")
        self.assertTrue(self.instances[0].closed)

    def test_explicit_legacy_registry_stays_on_legacy_protocol(self):
        actual_root = self.root / "new-compute"; actual_root.mkdir()
        (actual_root / "compute-registry.json").write_text(json.dumps(self.config), encoding="utf-8")
        self.request["compute_root"] = str(actual_root); self.write_request()
        registry = {"available": True, "model_id": "ace-step-1.5-xl-turbo"}
        with patch.object(compute, "run", side_effect=AssertionError("Explicit legacy registry must not dispatch new compute")):
            result = legacy.run(self.path, registry, self.tunnel_factory)
        self.assertEqual(result["model"]["id"], "ace-step-1.5-xl-turbo")
        self.assertNotIn("/capabilities", [call[1] for call in self.instances[0].calls])
        self.assertEqual(result["audio"]["duration_seconds"], 1.25)
        self.assertTrue(self.instances[0].closed)

    def test_wrong_model_or_hash_never_publishes_candidate(self):
        for failure in ("wrong_model", "tamper"):
            with self.subTest(failure=failure):
                setattr(self, failure, True)
                with self.assertRaises(client.GenerationError): compute.run(self.path, self.config, self.tunnel_factory)
                self.assertFalse((self.directory / "result.json").exists())
                self.assertFalse((self.directory / "audio.wav").exists())
                self.assertTrue(self.instances[-1].closed)
                if failure == "wrong_model": self.assertFalse(self.instances[-1].downloads)
                setattr(self, failure, False)


if __name__ == "__main__":
    unittest.main()
