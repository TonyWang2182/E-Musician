"""Hybrid Agent contract tests; synthetic host data, no inference or API calls."""
from copy import deepcopy
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent import analysis as a, generation as g
from music_agent.compute import require_route
from music_agent.bridge import DawBridge, BridgeError
from music_agent.runtime import AgentRuntime, SYSTEM
from music_agent.selection import freeze_scope, ScopeError
from test_music_agent_analysis import context, result
from test_music_agent_generation import candidate as generation_candidate


class HybridAgentContracts(unittest.TestCase):
    def test_explicit_route_does_not_fall_back(self):
        caps = a.safe_capabilities({"providers": [
            {"kind": "transcribe", "model_id": "basic-pitch", "available": True, "execution": "local"},
            {"kind": "transcribe", "model_id": "transkun", "available": False, "execution": "cloud"}]})
        require_route(caps, "transcribe", {})
        for route in ({"execution": "cloud"}, {"model_id": "transkun"}, {"model_id": "unknown"},
                      {"model_id": "basic-pitch", "execution": "cloud"}):
            with self.subTest(route=route), self.assertRaises(ValueError): require_route(caps, "transcribe", route)

    def test_duplicate_kind_capability_keeps_available_model(self):
        caps = a.safe_capabilities({"providers": [
            {"kind": "transcribe", "model_id": "basic-pitch", "available": True},
            {"kind": "transcribe", "model_id": "transkun", "available": False, "execution": "cloud"}]})
        groups = a.capability_groups(context(), {"commands": list(a.COMMANDS)}, caps)
        self.assertTrue(next(x for x in groups if x["id"] == "transcribe")["enabled"])

    def test_route_arguments_preserve_scope_and_reject_paths(self):
        ctx = context(); scope = freeze_scope(ctx)
        args = {"clip_id": "c", "kind": "score", "execution": "cloud", "model_id": "sheetsage2"}
        request = a.authorize_start(ctx, scope, args)
        self.assertEqual(request["duration_seconds"], 10)
        self.assertEqual(request["model_id"], "sheetsage2")
        for change in ({"model_id": "/root/secret"}, {"execution": "remote"}, {"execution": []},
                       {"start_seconds": 9, "duration_seconds": 3}, {"parameters": {"onset_threshold": .5}}):
            with self.subTest(change=change), self.assertRaises(ValueError): a.authorize_start(ctx, scope, {**args, **change})

    def test_cloud_models_do_not_accept_local_knobs(self):
        ctx = context(); scope = freeze_scope(ctx)
        for model, kind, params in (("transkun", "transcribe", {"instrument": "piano"}),
                                    ("chordmini", "chords", {"sensitivity": .5}),
                                    ("scnet", "separate", {"stems": 6})):
            with self.subTest(model=model), self.assertRaises(ValueError):
                a.authorize_start(ctx, scope, {"clip_id": "c", "kind": kind, "model_id": model, "parameters": params})

    def test_explicit_multi_instrument_accepts_other_and_drums(self):
        for role in ("other", "drums"):
            ctx = context(); ctx["tracks"][0]["clips"][0]["analysis_role"] = role
            a.authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "transcribe", "execution": "cloud", "model_id": "muscriptor"})
            with self.assertRaises(ScopeError): a.authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "transcribe", "execution": "local"})

    def test_multitrack_import_counts_and_bounded_projection(self):
        ctx = context(); raw = result(); raw.update(execution="cloud", model_id="muscriptor",
            summary={"track_count": 3, "note_count": 2, "controller_count": 4},
            midi_tracks=[{"id": "piano", "instrument": "piano", "note_count": 2, "controller_count": 4,
                          "notes": [{"pitch": 60}], "controllers": [{"value": 127}], "path": "/root/private.mid"}])
        candidate = a.safe_result(raw)
        self.assertNotIn("path", str(candidate["midi_tracks"]))
        self.assertNotIn("controllers", candidate["midi_tracks"][0])
        self.assertFalse(candidate["notes_only"])
        plan = a.compile_import(candidate, ctx, freeze_scope(ctx), "Import")
        self.assertIn("3", plan["changes"][0])
        ctx["tracks"].extend({"id": f"extra-{i}", "clips": []} for i in range(61))
        with self.assertRaisesRegex(ValueError, "64"): a.compile_import(candidate, ctx, freeze_scope(ctx), "Import")

    def test_score_without_notes_can_import_chord_and_structure_metadata(self):
        ctx = context(); raw = result("score", 0)
        raw.update(summary={"track_count": 0, "note_count": 0, "controller_count": 0, "chord_count": 3,
                            "beat_count": 20, "annotation_count": 2}, execution="cloud", model_id="sheetsage2")
        candidate = a.safe_result(raw)
        plan = a.compile_import(candidate, ctx, freeze_scope(ctx), "Import")
        self.assertEqual(a.import_track_count(candidate), 0)
        self.assertEqual(plan["commands"][0]["command"], "accept_analysis_result")
        self.assertIn("不会自动", plan["changes"][-1])

    def test_summary_overflow_and_nested_payload_rejected(self):
        for summary in ({"track_count": 65}, {"controller_count": -1}, {"note_count": True}, {"beat_count": 10001}, {"program_change_count": 65}):
            with self.subTest(summary=summary), self.assertRaises(ValueError): a.safe_result({**result(), "summary": summary})
        with self.assertRaises(ValueError): a.safe_result({**result(), "midi_tracks": [{}]*65})
        for value in ({"private_path": "/root/token"}, float("inf"), "not a number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                a.safe_result({**result(), "items": [{"pitch": value}]})

    def test_generation_routes_keep_defaults_and_reject_explicit_unavailable(self):
        ctx = context(); ctx["position_seconds"] = 4
        request = g.authorize_start(ctx, freeze_scope(ctx, "project"), {"model_id": "yue2"})
        self.assertEqual(request["duration_seconds"], 20)
        self.assertEqual(request["timeline_start_seconds"], 4)
        caps = g.safe_capabilities({"providers": [{"model_id": "ace-step-1.5-xl-turbo", "available": True}, {"model_id": "yue2", "available": False}]})
        require_route(caps, "generate", {})
        with self.assertRaises(ValueError): require_route(caps, "generate", request)
        with self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {"execution": "local"})

    def test_secrets_and_cloud_paths_do_not_enter_model_context(self):
        secret = "hf_" + "A"*30
        value = a.safe_text("failure " + secret + " /root/autodl-tmp/private/file")
        self.assertNotIn(secret, value); self.assertNotIn("/root/", value)
        cleaned = a.safe_result({**result("chords", 1), "items": [{"label": "C:maj7/E", "score": None,
            "uncertain": True, "path": "/root/private", "start_seconds": 0, "end_seconds": 2}]})
        self.assertEqual(cleaned["items"][0]["label"], "C:maj7/E")
        self.assertIsNone(cleaned["items"][0]["score"])
        self.assertNotIn("path", cleaned["items"][0])

    def test_readback_checks_multitrack_total_notes(self):
        approved = result(); approved["summary"] = {"track_count": 2, "note_count": 2, "controller_count": 1}
        applied = {**approved, "applied": True}
        class Bridge:
            def analysis_result(self, _): return applied
        class Runtime:
            bridge = Bridge()
        after = {"tracks": [{"id": "t1", "clips": [{"id": "c1", "kind": "midi", "start_seconds": 8, "note_count": 1, "controller_count": 1}]},
                            {"id": "t2", "clips": [{"id": "c2", "kind": "midi", "start_seconds": 8, "note_count": 1, "controller_count": 0}]}]}
        receipt = {"track_ids": ["t1", "t2"], "clip_ids": ["c1", "c2"]}
        verify = lambda: AgentRuntime._verify_analysis_import(Runtime(), {"analysis": approved}, receipt, after)
        self.assertEqual(verify(), [])
        after["tracks"][1]["clips"][0]["note_count"] = 0
        self.assertTrue(verify())

    def test_readback_distinguishes_cc_from_program_even_when_total_matches(self):
        approved = result(); approved["summary"] = {"track_count": 1, "note_count": 2, "controller_count": 1, "program_change_count": 1}
        class Bridge:
            counts = {"controller_count": 1, "program_change_count": 1, "other_count": 0}
            def analysis_result(self, _): return {**approved, "applied": True}
            def imported_controller_counts(self, context, clip_ids): return self.counts
        class Runtime:
            bridge = Bridge()
        after = {"tracks": [{"id": "t1", "clips": [{"id": "c1", "kind": "midi", "start_seconds": 8, "note_count": 2, "controller_count": 2}]}]}
        receipt = {"track_ids": ["t1"], "clip_ids": ["c1"]}
        verify = lambda: AgentRuntime._verify_analysis_import(Runtime(), {"analysis": approved}, receipt, after)
        self.assertEqual(verify(), [])
        Runtime.bridge.counts = {"controller_count": 0, "program_change_count": 2, "other_count": 0}
        self.assertTrue(verify())

    def test_controller_readback_pages_and_validates_public_14bit_events(self):
        bridge = object.__new__(DawBridge); bridge.lock = threading.RLock()
        ctx = {"project_id": "p", "revision": 7, "tracks": [{"clips": [{"id": "midi", "kind": "midi"}]}]}
        bridge.snapshot = lambda: ctx
        events = [{"id": f"cc-{i}", "type": 64, "value": 127 << 7, "beats": i / 1000} for i in range(1001)]
        events.append({"id": "program", "type": 4097, "value": 5 << 7, "beats": 0})
        calls = []
        def request(envelope):
            self.assertEqual(envelope["command"], "get_clip_controllers")
            args = envelope["args"]; calls.append(args)
            return {"result": {"total": len(events), "offset": args["offset"], "events": events[args["offset"]:args["offset"] + args["limit"]]}}
        bridge._request = request
        self.assertEqual(bridge.imported_controller_counts(ctx, ["midi"]), {"controller_count": 1001, "program_change_count": 1, "other_count": 0})
        self.assertEqual([item["offset"] for item in calls], [0, 1000])
        events[-1]["id"] = "cc-0"
        with self.assertRaises(BridgeError): bridge.imported_controller_counts(ctx, ["midi"])

    def test_generation_budget_projection_keeps_unknown_and_true_distinct(self):
        for truncated, reason in ((True, "token_budget"), (False, "model_stop"), (None, "unknown")):
            completion = {"truncated": truncated, "reason": reason, "timing_is_exact": False}
            raw = generation_candidate(); raw["completion"] = completion
            self.assertEqual(g.safe_result(raw)["completion"], completion)
        raw["completion"] = {"truncated": "yes", "reason": {"private_path": "/root/private"}, "timing_is_exact": "yes"}
        self.assertEqual(g.safe_result(raw)["completion"], {})

    def test_prompt_requires_evidence_and_no_model_followup(self):
        for text in ("不为选择模型再次追问", "score=null", "token_limit_reached", "不可静默换模型"):
            self.assertIn(text, SYSTEM)


if __name__ == "__main__": unittest.main()
