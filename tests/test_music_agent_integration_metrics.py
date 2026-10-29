"""Integration evidence accounting only: no real provider or DAW is created."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("music_agent_fixture",Path(__file__).with_name("MusicAgentIntegration.py"))
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class IntegrationMetricsTests(unittest.TestCase):
    def test_provider_phase_usage_excludes_later_synthetic_fixture(self):
        actual=fixture.MeasuredProvider(fixture.FakeProvider([
            {"message":{"role":"assistant","content":"ok"},
             "usage":{"prompt_tokens":37,"completion_tokens":11},"model":"actual-model-id"}]))
        synthetic=fixture.MeasuredProvider(fixture.FakeProvider([fixture.proposal([])]))
        actual.complete([])
        frozen=dict(actual.usage)
        synthetic.complete([])
        self.assertEqual(actual.usage,frozen)
        self.assertEqual(actual.usage,{"attempts":1,"completed_responses":1,"prompt_tokens":37,"completion_tokens":11})
        self.assertEqual(synthetic.usage,{"attempts":1,"completed_responses":1,"prompt_tokens":0,"completion_tokens":0})
        self.assertEqual(actual.returned_models,{"actual-model-id"})

    def test_failed_attempt_does_not_invent_response_or_token_measurement(self):
        measured=fixture.MeasuredProvider(fixture.FakeProvider([]))
        with self.assertRaises(StopIteration):
            measured.complete([])
        self.assertEqual(measured.usage,{"attempts":1,"completed_responses":0,"prompt_tokens":0,"completion_tokens":0})
        self.assertFalse(measured.returned_models)


if __name__=="__main__":unittest.main()
