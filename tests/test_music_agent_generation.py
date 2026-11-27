"""Generation contract and orchestration tests with explicit fake host/model.

No GPU, music inference, audio-device operation or paid LLM requests occur here.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from music_agent import generation as g
from music_agent.bridge import DawBridge, BridgeError
from music_agent.runtime import AgentRuntime, SYSTEM
from music_agent.selection import ScopeError, freeze_scope
from music_agent.audit import Audit
from music_agent.config import DEFAULT_CONFIG
from test_music_agent_runtime import FakeProvider, FakeBridge, tool
from test_music_agent_selection import context as selected_context


def context():
    ctx = selected_context()
    ctx.update(tracks=[], clip_notes={}, position_seconds=5, can_undo=False, numerator=4, denominator=4)
    ctx["selection_context"].update(active_track_id="", active_clip_id="", track_ids=[], clip_ids=[], note_clip_id="", note_ids=[], note_count=0, focus="none")
    return ctx


def candidate():
    return {"result_id": "gen-r", "kind": "generate", "result_hash": "a"*64, "applied": False, "present_in_project": False, "stale": False,
            "source": {"project_id": "p", "revision": 4, "timeline_start": 5., "bpm": 120., "meter_numerator": 4, "meter_denominator": 4},
            "audio": {"path": "audio.wav", "sha256": "b"*64, "duration_seconds": 16., "sample_rate": 48000, "channels": 2},
            "parameters": {"duration_seconds": 16, "seed": 42}, "model": {"id": "synthetic-no-inference", "version": "fixture"}}


class ContractTests(unittest.TestCase):
    def test_omitted_fields_use_real_project_defaults_not_hardcoded_tempo(self):
        ctx = context(); ctx.update(bpm=93., numerator=3, denominator=4, position_seconds=17.5)
        before = deepcopy(ctx); frozen = freeze_scope(ctx)
        defaults = g.generation_defaults(ctx, frozen); request = g.authorize_start(ctx, frozen, {})
        self.assertEqual((defaults["bpm"], defaults["meter_numerator"], defaults["meter_denominator"]), (93., 3, 4))
        self.assertAlmostEqual(defaults["seconds_per_bar"], 180/93)
        self.assertEqual(request, {"prompt": g.DEFAULT_PROMPT, "lyrics": "", "duration_seconds": 20., "timeline_start_seconds": 17.5})
        self.assertEqual(ctx, before)

    def test_bar_duration_uses_actual_meter_and_does_not_reach_native_as_bars(self):
        ctx = context(); ctx.update(numerator=6, denominator=8)
        request = g.authorize_start(ctx, freeze_scope(ctx), {"prompt": "Guitar", "duration_bars": 8})
        self.assertEqual(request["duration_seconds"], 12.)
        self.assertNotIn("duration_bars", request); self.assertNotIn("bpm", request)

    def test_default_duration_fits_short_valid_time_selection(self):
        ctx = context(); ctx["selection_context"]["time_range"] = {"active": True, "start_seconds": 10, "end_seconds": 22}
        request = g.authorize_start(ctx, freeze_scope(ctx), {"prompt": "Piano"})
        self.assertEqual((request["duration_seconds"], request["timeline_start_seconds"]), (12., 10.))
        with self.assertRaises(ScopeError): g.authorize_start(ctx, freeze_scope(ctx), {"prompt": "Piano", "duration_seconds": 16})

    def test_short_selection_does_not_silently_widen_or_generate(self):
        ctx = context(); ctx["selection_context"]["time_range"] = {"active": True, "start_seconds": 10, "end_seconds": 15}
        self.assertFalse(g.generation_defaults(ctx, freeze_scope(ctx))["supported"])
        with self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {})

    def test_missing_invalid_and_unsupported_tempo_never_falls_back_to_120(self):
        for value in (None, True, float("nan"), 20, 301):
            ctx = context(); ctx["bpm"] = value
            self.assertFalse(g.generation_defaults(ctx, freeze_scope(ctx))["supported"])
            with self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {})
        ctx = context(); ctx.update(numerator=7, denominator=8)
        self.assertFalse(g.generation_defaults(ctx, freeze_scope(ctx))["supported"])

    def test_explicit_duration_and_description_preserved_and_conflicts_rejected(self):
        ctx = context(); args = {"prompt": "Jazz piano with brushed drums", "duration_seconds": 33, "lyrics": "Original lyric", "seed": 71}
        request = g.authorize_start(ctx, freeze_scope(ctx), args)
        for key, value in args.items(): self.assertEqual(request[key], value)
        for extra in ({"duration_bars": 8}, {"bpm": 140}):
            with self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {**args, **extra})
        for bars in (True, float("nan"), 1, 1000):
            with self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {"duration_bars": bars})

    def test_empty_project_generates_at_frozen_playhead_without_source(self):
        ctx = context(); scope = freeze_scope(ctx)
        request = g.authorize_start(ctx, scope, {"prompt": "Warm piano", "duration_seconds": 16})
        self.assertEqual(request["timeline_start_seconds"], 5)
        self.assertEqual(request["lyrics"], "")
        self.assertNotIn("clip_id", request)

    def test_time_selection_determines_start_and_bounds(self):
        ctx = context(); ctx["selection_context"]["time_range"] = {"active": True, "start_seconds": 10, "end_seconds": 30}
        self.assertEqual(g.authorize_start(ctx, freeze_scope(ctx), {"prompt": "Piano", "duration_seconds": 16})["timeline_start_seconds"], 10)
        with self.assertRaises(ScopeError): g.authorize_start(ctx, freeze_scope(ctx), {"prompt": "Piano", "duration_seconds": 30})

    def test_explicit_other_location_requires_project_scope(self):
        ctx = context(); args = {"prompt": "Piano", "duration_seconds": 16, "timeline_start_seconds": 30}
        with self.assertRaises(ScopeError): g.authorize_start(ctx, freeze_scope(ctx), args)
        self.assertEqual(g.authorize_start(ctx, freeze_scope(ctx, "project"), args)["timeline_start_seconds"], 30)

    def test_invalid_numbers_seeds_limits_and_paths_rejected(self):
        ctx = context(); args = {"prompt": "Piano", "duration_seconds": 16}
        for update in ({"duration_seconds": True}, {"duration_seconds": float("nan")}, {"duration_seconds": 9}, {"duration_seconds": 121}, {"seed": -1}, {"seed": 1.5}, {"prompt": " "}, {"lyrics": "x"*4097}, {"path": "E:/private.wav"}, {"endpoint": "http://attacker"}):
            with self.subTest(update=str(update)[:80]), self.assertRaises(ValueError): g.authorize_start(ctx, freeze_scope(ctx), {**args, **update})

    def test_import_only_ids_and_hash_preserves_content_identity(self):
        ctx = context(); plan = g.compile_import(candidate(), ctx, freeze_scope(ctx), "Add music")
        self.assertEqual(plan["execution_kind"], "generation_import")
        self.assertEqual(plan["commands"], [{"command": "accept_generation_result", "args": {"result_id": "gen-r", "result_hash": "a"*64}}])
        self.assertNotIn("path", plan["generation"]["audio"])

    def test_stale_wrong_project_tempo_meter_and_applied_refused(self):
        ctx = context()
        for field, value in (("project_id", "other"), ("bpm", 90), ("meter_numerator", 3), ("meter_denominator", 8)):
            c = candidate(); c["source"][field] = value
            with self.subTest(field=field), self.assertRaises(ScopeError): g.compile_import(c, ctx, freeze_scope(ctx), "add")
        for update in ({"applied": True}, {"stale": True}, {"result_hash": "bad"}):
            with self.subTest(update=update), self.assertRaises(ValueError): g.compile_import({**candidate(), **update}, ctx, freeze_scope(ctx), "add")

    def test_unrelated_edits_allow_fresh_plan_but_frozen_plan_cannot_apply(self):
        ctx = context(); frozen = freeze_scope(ctx); ctx["revision"] += 1; ctx["selection_context"]["project_revision"] += 1
        with self.assertRaises(ScopeError): g.compile_import(candidate(), ctx, frozen, "old")
        self.assertEqual(g.compile_import(candidate(), ctx, freeze_scope(ctx), "fresh")["revision"], 5)

    def test_format_identity_track_budget_and_missing_timing_refused(self):
        for field, value in (("channels", 3), ("channels", 1.5), ("sample_rate", 5000), ("sha256", "bad"), ("duration_seconds", 0)):
            c = candidate(); c["audio"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): g.safe_result(c)
        ctx = context(); ctx["tracks"] = [{}]*64
        with self.assertRaises(ValueError): g.compile_import(candidate(), ctx, freeze_scope(ctx), "add")

    def test_sensitive_runtime_fields_never_enter_context(self):
        c = candidate(); c["audio"]["path"] = "E:/private/generated.wav"; c["model"]["python"] = "/root/private/python"
        c["parameters"]["endpoint"] = "http://secret"; c["source"]["api_key"] = "key"
        safe = g.safe_result(c)
        self.assertNotIn("private", str(safe)); self.assertNotIn("endpoint", str(safe)); self.assertNotIn("api_key", str(safe))

    def test_capabilities_require_host_and_runtime(self):
        self.assertFalse(g.capability_group({}, {"available": True})["enabled"])
        self.assertFalse(g.capability_group({"commands": list(g.COMMANDS)}, {"available": False})["enabled"])
        self.assertTrue(g.capability_group({"commands": list(g.COMMANDS)}, {"available": True})["enabled"])
        self.assertIn("start_generation", SYSTEM)
        self.assertNotIn("\u4e0d\u80fd\u76f4\u63a5\u542c\u5230\u97f3\u9891\u3001\u751f\u6210\u97f3\u9891", SYSTEM)

    def test_bridge_refuses_import_cancel_and_mismatched_result(self):
        bridge = object.__new__(DawBridge)
        bridge._request = Mock(return_value={"result": {"kind": "generation.accept", "status": "running"}})
        with self.assertRaises(BridgeError): bridge.cancel_generation("job")
        self.assertEqual(bridge._request.call_count, 1)
        bridge._request = Mock(return_value={"result": candidate()})
        with self.assertRaises(BridgeError): bridge.generation_result("different")

    def test_bridge_envelope_is_revision_selection_and_hash_guarded(self):
        bridge = object.__new__(DawBridge); ctx = context(); scope = freeze_scope(ctx)
        bridge.generation_capabilities = Mock(return_value={"available": True})
        bridge._request = Mock(return_value={"status": "accepted", "result": {"job_id": "job"}})
        bridge.start_generation(ctx, scope, {"prompt": "Piano", "duration_seconds": 16})
        envelope = bridge._request.call_args.args[0]
        self.assertEqual((envelope["project_id"], envelope["expected_revision"], envelope["expected_selection_revision"]), ("p", 4, 8))
        bridge.snapshot = Mock(return_value=ctx); bridge.generation_result = Mock(return_value=g.safe_result(candidate()))
        plan = g.compile_import(candidate(), ctx, scope, "add"); plan["id"] = "plan"
        bridge.apply(plan)
        self.assertEqual(bridge._request.call_args.args[0]["args"], {"result_id": "gen-r", "result_hash": "a"*64})

    def test_preview_checks_async_preparation_then_stream_and_errors(self):
        bridge = object.__new__(DawBridge)
        job = {"id": "preview-j", "kind": "generation.preview", "status": "running"}
        bridge._request = Mock(return_value={"result": job})
        self.assertEqual(bridge.generation_preview_status("preview-j")["status"], "preparing")
        self.assertEqual(bridge._request.call_count, 1)
        job["status"] = "completed"
        for state in ("loading", "playing", "completed", "failed", "unavailable"):
            bridge._request = Mock(side_effect=[{"result": job}, {"result": {"status": state, "detail": "Synthetic status"}}])
            self.assertEqual(bridge.generation_preview_status("preview-j")["status"], state)
            self.assertEqual(bridge._request.call_args.args[0]["command"], "get_analysis_preview_status")
        bridge._request = Mock(return_value={"result": {**job, "status": "failed", "error": "No audio output is active. Open audio settings before previewing a stem."}})
        self.assertEqual(bridge.generation_preview_status("preview-j")["status"], "unavailable")
        self.assertEqual(bridge._request.call_count, 1)
        bridge._request = Mock(return_value={"result": {**job, "kind": "analysis.preview"}})
        with self.assertRaises(BridgeError): bridge.generation_preview_status("preview-j")

    def test_changed_candidate_hash_refused_before_native_submission(self):
        bridge = object.__new__(DawBridge)
        ctx = context(); plan = g.compile_import(candidate(), ctx, freeze_scope(ctx), "review")
        changed = candidate(); changed["result_hash"] = "c" * 64
        bridge.snapshot = Mock(return_value=ctx)
        bridge.generation_result = Mock(return_value=g.safe_result(changed))
        bridge._request = Mock()
        with self.assertRaises(BridgeError): bridge.apply(plan)
        bridge._request.assert_not_called()

    def test_preview_start_uses_native_revision_envelope_but_stop_is_read(self):
        bridge = object.__new__(DawBridge); bridge.snapshot = Mock(return_value=context())
        bridge._request = Mock(return_value={"status": "accepted", "result": {"job_id": "preview-j"}})
        bridge.preview_generation("gen-r")
        request = bridge._request.call_args.args[0]
        self.assertEqual((request["project_id"], request["expected_revision"]), ("p", 4))
        self.assertEqual(request["args"], {"result_id": "gen-r"})
        bridge.preview_generation()
        self.assertEqual(bridge._request.call_args.args[0], {"command": "stop_generation_preview"})
        self.assertEqual(bridge.snapshot.call_count, 1)

    def test_sample_rate_matches_native_generation_contract(self):
        for rate in (8000, 12000, 96001, 192000):
            c = candidate(); c["audio"]["sample_rate"] = rate
            with self.subTest(rate=rate), self.assertRaises(ValueError): g.safe_result(c)
        for rate in (16000, 48000, 96000):
            c = candidate(); c["audio"]["sample_rate"] = rate
            self.assertEqual(g.safe_result(c)["audio"]["sample_rate"], rate)


class GenerationBridge(FakeBridge):
    def __init__(self, running=False):
        super().__init__(); self.data = context(); self.candidate = g.safe_result(candidate()); self.running = running
        self.started = threading.Event(); self.cancelled = False; self.preview_status = "loading"
    def capabilities(self): return {"commands": list(g.COMMANDS)}
    def generation_capabilities(self): return {"available": True}
    def start_generation(self, ctx, scope, args):
        g.authorize_start(ctx, scope, args); self.calls.append(("start", deepcopy(args))); self.started.set(); return {"job_id": "gen-j"}
    def generation_job(self, jid):
        return {"job_id": jid, "result_id": "gen-r", "status": "cancelled" if self.cancelled else "running" if self.running else "ready", "source": deepcopy(self.candidate["source"])}
    def generation_result(self, rid): return deepcopy(self.candidate)
    def cancel_generation(self, jid): self.calls.append(("cancel", jid)); self.cancelled = True
    def preview_generation(self, rid=None): self.calls.append(("preview", rid)); return {"result": {"job_id": "preview-j"}}
    def generation_preview_status(self, jid): return {"job_id": jid, "status": self.preview_status, "detail": "Synthetic output detail"}
    def apply(self, plan):
        self.calls.append(("apply", deepcopy(plan))); self.last_before = deepcopy(self.data); self.last_notes = deepcopy(self.notes)
        return {"status": "accepted", "result": {"job_id": "import-j"}}
    def wait_generation_import(self, jid):
        self.candidate["applied"] = True
        self.data["tracks"].append({"id": "generated-track", "kind": "audio", "clips": [{"id": "generated-clip", "kind": "audio", "start_seconds": 5., "duration_seconds": 16.}]})
        self.data.update(revision=5, can_undo=True)
        self.data["selection_context"]["project_revision"] = 5
        return {"project_id": "p", "revision": 5, "applied": True, "result_id": "gen-r", "track_ids": ["generated-track"], "clip_ids": ["generated-clip"]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.runtimes = []
        self.patches = [patch("music_agent.runtime.load_config", return_value=deepcopy(DEFAULT_CONFIG)), patch("music_agent.runtime.has_key", return_value=False), patch("music_agent.providers.has_key", return_value=False)]
        for p in self.patches: p.start()
    def tearDown(self):
        for r in self.runtimes:
            r.cancel_event.set()
            if r.worker: r.worker.join(3)
        for p in self.patches: p.stop()
        self.temp.cleanup()
    def make(self, *responses, running=False):
        r = AgentRuntime(GenerationBridge(running), FakeProvider(responses), Audit(Path(self.temp.name)/"audit.jsonl"))
        self.runtimes.append(r); return r
    def finish(self, r):
        r.worker.join(3); self.assertFalse(r.worker.is_alive()); return r.state(False)
    def ready(self):
        r = self.make(tool("start_generation", {"prompt": "Warm piano", "duration_seconds": 16}), tool("propose_generation_import", {"result_id": "gen-r", "summary": "Add generated piano"}))
        r.plan_request("Generate piano", "selection"); s = self.finish(r)
        self.assertEqual(s["phase"], "ready", s); return r, s
    def test_generation_without_bpm_or_duration_reaches_review_from_current_context(self):
        r = self.make(tool("start_generation", {"prompt": "Jazz piano"}), tool("propose_generation_import", {"result_id": "gen-r", "summary": "Review generated jazz piano"}))
        r.bridge.data.update(bpm=93., numerator=3, denominator=4)
        r.bridge.candidate["source"].update(bpm=93., meter_numerator=3, meter_denominator=4)
        r.plan_request("\u751f\u6210\u4e00\u6bb5\u7235\u58eb\u94a2\u7434", "selection"); state = self.finish(r)
        self.assertEqual(state["phase"], "ready", state)
        self.assertEqual(len(r.provider.requests), 2)
        sent_context = json.loads(r.provider.requests[0][-1]["content"].split("Current project data (read-only):\n")[1])
        self.assertEqual(sent_context["generation_defaults"]["bpm"], 93.)
        self.assertIn('"bpm": 93.0', r.provider.requests[0][0]["content"])
        started = [call[1] for call in r.bridge.calls if call[0] == "start"]
        self.assertEqual(len(started), 1); self.assertEqual(started[0]["duration_seconds"], 20.)
        self.assertEqual(started[0]["prompt"], "Jazz piano")
        self.assertFalse(r.bridge.data["tracks"]); self.assertFalse(any(call[0] == "apply" for call in r.bridge.calls))

    def test_two_cached_results_can_be_reviewed_without_regeneration_or_model_calls(self):
        r, state = self.ready()
        first = deepcopy(r.bridge.candidate)
        second = deepcopy(first); second["result_id"] = "gen-second"; second["model"]["id"] = "second-fixture"
        r._remember_generation(second)
        results = {first["result_id"]: first, second["result_id"]: second}
        r.bridge.generation_result = lambda rid: deepcopy(results[rid])
        r.bridge.data["revision"] += 1
        r.bridge.data["selection_context"]["project_revision"] += 1
        calls = len(r.provider.requests)
        for rid in ("gen-second", "gen-r"):
            r.select_generation_result(rid, "project", language="en")
            state = self.finish(r)
            self.assertEqual(state["phase"], "ready", state)
            self.assertEqual(state["plan"]["revision"], 5)
            self.assertEqual(state["plan"]["generation"]["result_id"], rid)
            self.assertEqual(sum(c["selected"] for c in state["generation_choices"]), 1)
            self.assertIn("Review", state["plan"]["summary"])
        self.assertEqual(len(r.provider.requests), calls)
        self.assertEqual(sum(c[0] == "start" for c in r.bridge.calls), 1)
        self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))
        self.assertEqual(len(state["generation_choices"]), 2)
        self.assertNotIn("path", str(state["generation_choices"]))

    def test_selection_revalidates_candidate_and_scope_before_exposing_apply(self):
        for failure in ("project", "tempo", "applied", "stale", "time", "recording", "identity"):
            with self.subTest(failure=failure):
                r, _ = self.ready()
                if failure == "project": r.bridge.data["project_id"] = "other"
                elif failure == "tempo": r.bridge.data["bpm"] = 99
                elif failure == "applied": r.bridge.candidate["applied"] = True
                elif failure == "stale": r.bridge.candidate["stale"] = True
                elif failure == "recording": r.bridge.data["recording"] = True
                elif failure == "identity": r.bridge.candidate["result_id"] = "other"
                else: r.bridge.data["selection_context"]["time_range"] = {"active": True, "start_seconds": 10, "end_seconds": 12}
                r.select_generation_result("gen-r", "selection")
                state = self.finish(r)
                self.assertEqual(state["phase"], "error", state)
                self.assertIsNone(state["plan"])
                self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))

    def test_selection_unknown_busy_and_cache_limit(self):
        r, _ = self.ready()
        with self.assertRaises(ValueError): r.select_generation_result("unknown", "project")
        with patch.object(r, "busy", return_value=True):
            with self.assertRaises(ValueError): r.select_generation_result("gen-r", "project")
        for i in range(8):
            c = deepcopy(r.bridge.candidate); c["result_id"] = "cached-" + str(i)
            r._remember_generation(c)
        choices = r.state(False)["generation_choices"]
        self.assertEqual(len(choices), 6)
        self.assertEqual(choices[0]["result_id"], "cached-2")
        r.bridge.data["project_id"] = "other"
        self.assertEqual(r.state()["generation_choices"], [])

    def test_applied_result_stays_consumed_other_candidate_remains_available(self):
        r, state = self.ready()
        c = deepcopy(r.bridge.candidate); c["result_id"] = "gen-other"; r._remember_generation(c)
        r.apply(state["plan"]["id"])
        state = self.finish(r)
        self.assertEqual(state["phase"], "done", state)
        choices = {c["result_id"]: c for c in state["generation_choices"]}
        self.assertTrue(choices["gen-r"]["applied"])
        self.assertFalse(choices["gen-r"]["available"])
        self.assertTrue(choices["gen-other"]["available"])

    def test_stale_plan_allows_reselecting_same_candidate_and_stops_previous_preview(self):
        r, state = self.ready()
        r.preview_generation_plan(state["plan"]["id"])
        r.bridge.data["revision"] += 1
        r.bridge.data["selection_context"]["project_revision"] += 1
        self.assertFalse(r.state()["generation_choices"][0]["selected"])
        r.select_generation_result("gen-r", "project", language="en")
        state = self.finish(r)
        self.assertEqual(state["phase"], "ready", state)
        self.assertEqual(state["generation_preview"]["status"], "stopped")
        self.assertEqual(r.bridge.calls[-1], ("preview", None))
        self.assertTrue(state["generation_choices"][0]["selected"])
        self.assertEqual(len(r.provider.requests), 2)

    def test_mutation_during_candidate_read_prevents_ready(self):
        for field in ("revision", "selection"):
            r, _ = self.ready()
            def changing_read(_):
                if field == "revision":
                    r.bridge.data["revision"] += 1
                    r.bridge.data["selection_context"]["project_revision"] += 1
                else:
                    r.bridge.data["selection_context"]["selection_revision"] += 1
                return deepcopy(r.bridge.candidate)
            r.bridge.generation_result = changing_read
            r.select_generation_result("gen-r", "selection")
            state = self.finish(r)
            self.assertEqual(state["phase"], "error", state)
            self.assertIn(state["error_code"], {"ScopeError", "BridgeError"})
            self.assertIsNone(state["plan"])
            self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))

    def test_new_request_stops_previous_audition_before_hiding_review(self):
        r, state = self.ready()
        r.preview_generation_plan(state["plan"]["id"])
        r.provider = FakeProvider([{"message": {"role": "assistant", "content": "Ready."}, "usage": {}}])
        r.plan_request("Explain the current project.", "project", language="en")
        state = self.finish(r)
        self.assertEqual(state["phase"], "done", state)
        self.assertEqual(state["generation_preview"]["status"], "stopped")
        self.assertEqual(r.bridge.calls[-1], ("preview", None))
        self.assertEqual(sum(c[0] == "start" for c in r.bridge.calls), 1)
        self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))

    def test_bar_request_resolves_locally_before_generation(self):
        r = self.make(tool("start_generation", {"prompt": "Guitar", "duration_bars": 8}), tool("propose_generation_import", {"result_id": "gen-r", "summary": "Review guitar"}))
        r.bridge.data.update(numerator=6, denominator=8); r.bridge.candidate["source"].update(meter_numerator=6, meter_denominator=8)
        r.plan_request("\u751f\u62108\u5c0f\u8282\u5409\u4ed6", "selection"); self.assertEqual(self.finish(r)["phase"], "ready")
        request = next(call[1] for call in r.bridge.calls if call[0] == "start")
        self.assertEqual(request["duration_seconds"], 12.); self.assertNotIn("duration_bars", request)

    def test_information_question_is_not_forced_into_generation(self):
        r = self.make({"message": {"role": "assistant", "content": "\u53ef\u4ee5\u6839\u636e\u5de5\u7a0b\u901f\u5ea6\u751f\u6210\u97f3\u4e50\uff0c\u5e76\u5148\u7ed9\u51fa\u5019\u9009\u3002"}, "usage": {}})
        r.plan_request("\u4f60\u80fd\u751f\u6210\u97f3\u4e50\u5417\uff0c\u5148\u8bf4\u660e\u6d41\u7a0b", "selection")
        self.assertEqual(self.finish(r)["phase"], "done")
        self.assertFalse(any(call[0] in {"start", "apply"} for call in r.bridge.calls))
    def test_generate_review_preview_apply_verify_and_one_undo(self):
        r, s = self.ready(); self.assertEqual(r.bridge.data["tracks"], []); self.assertEqual(len(r.provider.requests), 2)
        pid = s["plan"]["id"]; r.preview_generation_plan(pid); r.preview_generation_plan(stop=True)
        self.assertEqual(r.bridge.calls[-2:], [("preview", "gen-r"), ("preview", None)])
        r.apply(pid); s = self.finish(r); self.assertEqual(s["phase"], "done", s); self.assertTrue(s["can_undo"])
        with self.assertRaises(ValueError): r.apply(pid)
        r.undo(); self.finish(r); self.assertEqual(r.bridge.data["tracks"], [])
    def test_preview_state_poll_reports_device_failure_without_losing_review(self):
        r, s = self.ready(); r.preview_generation_plan(s["plan"]["id"])
        self.assertEqual(r.state(False)["generation_preview"]["status"], "preparing")
        self.assertEqual(r.state()["generation_preview"]["status"], "loading")
        r.bridge.preview_status = "unavailable"; state = r.state()
        self.assertEqual(state["generation_preview"]["status"], "unavailable")
        self.assertEqual(state["phase"], "ready"); self.assertEqual(state["plan"]["id"], s["plan"]["id"])
        self.assertFalse(r.bridge.data["tracks"])
    def test_preview_disconnect_never_retains_a_playing_claim(self):
        r, s = self.ready(); r.preview_generation_plan(s["plan"]["id"])
        r.bridge.preview_status = "playing"; self.assertEqual(r.state()["generation_preview"]["status"], "playing")
        r.bridge.connected = False
        self.assertEqual(r.state()["generation_preview"]["status"], "unavailable")
    def test_preview_refresh_after_stop_does_not_restore_old_playback(self):
        r, s = self.ready(); r.preview_generation_plan(s["plan"]["id"])
        def racing_status(_):
            r.preview_generation_plan(stop=True)
            return {"status": "playing"}
        r.bridge.generation_preview_status = racing_status
        self.assertEqual(r.state()["generation_preview"]["status"], "stopped")
    def test_cancel_generation_does_not_make_more_model_calls(self):
        r = self.make(tool("start_generation", {"prompt": "Warm piano", "duration_seconds": 16}), running=True)
        r.plan_request("Generate piano", "selection"); self.assertTrue(r.bridge.started.wait(2)); r.cancel()
        s = self.finish(r); self.assertEqual(s["phase"], "cancelled", s); self.assertTrue(r.bridge.cancelled)
        self.assertEqual(len(r.provider.requests), 1); self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))
        self.assertIn("Cloud cancellation is unconfirmed", s["last_result"])
    def test_local_cancellation_never_claims_cloud_stopped_without_ack(self):
        for remote in (None, "unconfirmed", "cancelling"):
            raw = {"status": "cancelled", "remote_status": remote, "remote_cancel_confirmed": True}
            status = g.cancellation_status(g.safe_job(raw))
            self.assertTrue(status["local_cancelled"]); self.assertFalse(status["cancel_completed"])
        job = g.safe_job({"status": "cancelled", "remote_status": "cancelled", "remote_cancel_confirmed": True})
        self.assertTrue(g.cancellation_status(job)["cancel_completed"])
        self.assertIn("Local and cloud", g.cancellation_label(job))
    def test_repeated_identical_generation_reuses_job_not_compute(self):
        args = {"prompt": "Warm piano", "duration_seconds": 16}
        r = self.make(tool("start_generation", args), tool("start_generation", args), tool("propose_generation_import", {"result_id": "gen-r", "summary": "Add"}))
        r.plan_request("Generate", "selection"); s = self.finish(r); self.assertEqual(s["phase"], "ready", s)
        self.assertEqual(sum(c[0] == "start" for c in r.bridge.calls), 1)
    def test_changed_generation_request_in_same_task_refused(self):
        r = self.make(tool("start_generation", {"prompt": "Piano", "duration_seconds": 16}), tool("start_generation", {"prompt": "Drums", "duration_seconds": 16}))
        r.plan_request("Generate", "selection"); s = self.finish(r); self.assertEqual(s["phase"], "error")
        self.assertEqual(sum(c[0] == "start" for c in r.bridge.calls), 1)
    def test_changed_revision_after_review_does_not_commit_or_preview(self):
        r, s = self.ready(); r.bridge.data["revision"] += 1
        with self.assertRaises(ScopeError): r.preview_generation_plan(s["plan"]["id"])
        r.apply(s["plan"]["id"]); s = self.finish(r); self.assertEqual(s["phase"], "error")
        self.assertFalse(any(c[0] == "apply" for c in r.bridge.calls))
    def test_generation_readback_detects_wrong_clip(self):
        r, s = self.ready(); plan = deepcopy(r.plan); receipt = r.bridge.wait_generation_import("i")
        after = r.bridge.snapshot(); self.assertEqual(r._verify_generation_import(plan, receipt, after), [])
        after["tracks"][0]["clips"][0]["duration_seconds"] = 2
        self.assertTrue(r._verify_generation_import(plan, receipt, after))


if __name__ == "__main__": unittest.main()
