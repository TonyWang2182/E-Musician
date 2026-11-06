"""Pure receipt helpers only; importing the real-GPU runner must not launch it."""
import unittest
from HybridComputeEndToEnd import latency_summary, model_names, stable_music


class HybridAcceptanceReceipts(unittest.TestCase):
    def test_short_samples_do_not_claim_percentiles(self):
        for values in ([], [2.5], list(range(19))):
            result = latency_summary(values)
            self.assertEqual(result["count"], len(values))
            self.assertNotIn("p50_ms", result)
            self.assertNotIn("p95_ms", result)
        self.assertEqual(latency_summary([5, 1, 2])["min_ms"], 1)
        self.assertEqual(latency_summary([5, 1, 2])["max_ms"], 5)

    def test_twenty_samples_report_nearest_rank_and_median(self):
        result = latency_summary(list(range(20, 0, -1)))
        self.assertEqual(result["p50_ms"], 10.5)
        self.assertEqual(result["p95_ms"], 19)
        self.assertIn("not GUI", result["scope"])

    def test_requested_models_are_exact_and_unique(self):
        self.assertEqual(model_names(["scnet,transkun", "yue2"]), ["scnet", "transkun", "yue2"])
        for value in ([], ["scnet,scnet"], ["unknown"], ["/root/model"]):
            with self.assertRaises(ValueError): model_names(value)

    def test_music_comparison_preserves_cc_channels_and_unknown_scores(self):
        value = {"chords": [{"label": "C:maj7/E", "score": None}],
                 "events": [{"type": 64, "value": 127, "channel": 2, "beats": 1.000000000000001}]}
        normalized = stable_music(value)
        self.assertEqual(normalized["events"][0], {"type": 64, "value": 127, "channel": 2, "beats": 1.0})
        self.assertEqual(normalized["chords"], value["chords"])
        self.assertIsNot(normalized, value)


if __name__ == "__main__":
    unittest.main()
