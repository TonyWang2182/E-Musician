"""Analysis authorization/confirmation contracts; deterministic peers, no inference."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.analysis import (COMMANDS, authorize_start, authorize_result, compile_import,
                                 safe_result, safe_capabilities, safe_job, capability_groups, compile_chord_edit, authorize_cancel)
from music_agent.bridge import DawBridge, BridgeError
from music_agent.selection import freeze_scope, ScopeError
from music_agent.runtime import AgentRuntime
from music_agent.audit import Audit
from music_agent.config import DEFAULT_CONFIG
from test_music_agent_runtime import FakeProvider, FakeBridge, tool

def context():
    return {"project_id": "p", "revision": 3, "name": "Synthetic analysis scope fixture",
        "bpm": 120, "numerator": 4, "denominator": 4, "tracks": [{"id": "t", "kind": "audio", "name": "Source",
            "clips": [{"id": "c", "kind": "audio", "start_seconds": 8, "duration_seconds": 10}]}],
        "clip_notes": {}, "can_undo": False, "recording": False, "recording_finalizing": False,
        "selection_context": {"available": True, "project_id": "p", "project_revision": 3, "selection_revision": 8,
            "focus": "arrangement", "track_ids": ["t"], "clip_ids": ["c"], "note_ids": [], "note_count": 0,
            "active_track_id": "t", "active_clip_id": "c", "note_clip_id": "", "time_range": {"active": False}}}

def result(kind="transcribe", count=2):
    return {"result_id": "r", "kind": kind, "result_hash": "a"*64, "applied": False, "total": count, "offset": 0,
        "source": {"project_id": "p", "clip_id": "c", "track_id": "t", "asset_id": "a", "bpm": 120,
            "range_start_seconds": 0, "duration_seconds": 10, "clip_timeline_start": 8, "clip_duration": 10,
            "timeline_start": 8, "clip_source_offset": 0, "source_sha256": "b"*64},
        "model": {"id": "explicit-test-provider", "version": "mock"},
        "items": [{"pitch": 60+i, "start_seconds": i, "duration_seconds": 0.5, "velocity": 80, "channel": 1} for i in range(min(24,count))]}

class AnalysisScopeTests(unittest.TestCase):
    def test_selection_range_defaults_to_intersection(self):
        ctx = context(); ctx["selection_context"]["time_range"] = {"active": True, "start_seconds": 10, "end_seconds": 13}
        request = authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "chords"})
        self.assertEqual(request, {"clip_id": "c", "kind": "chords", "start_seconds": 2, "duration_seconds": 3})
        with self.assertRaises(ScopeError):
            authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "chords", "start_seconds": 0, "duration_seconds": 10})

    def test_parameters_use_worker_contract_and_reject_cross_kind_values(self):
        ctx=context(); args={"clip_id":"c","kind":"transcribe","parameters":{"onset_threshold":.7,"min_pitch":36,"max_pitch":84,"minimum_note_ms":40}}
        self.assertEqual(authorize_start(ctx,freeze_scope(ctx),args)["parameters"],args["parameters"])
        for params in ({"device":"cuda"},{"sensitivity":.5},{"min_pitch":40.5},{"min_pitch":80,"max_pitch":60},{"minimum_note_ms":-1}):
            with self.subTest(params=params),self.assertRaises(ValueError): authorize_start(ctx,freeze_scope(ctx),{**args,"parameters":params})

    def test_unselected_audio_and_paths_not_authorized(self):
        ctx = context(); ctx["tracks"][0]["clips"].append({"id": "else", "kind": "audio", "start_seconds": 0, "duration_seconds": 2})
        for args in ({"clip_id": "else", "kind": "separate"}, {"clip_id": "c", "kind": "separate", "source_path": "C:/secret"}):
            with self.subTest(args=args), self.assertRaises(ValueError): authorize_start(ctx, freeze_scope(ctx), args)

    def test_non_audio_nonfinite_and_long_range_rejected(self):
        ctx = context()
        for invalid in (float("nan"), True, -1, 601):
            with self.subTest(value=invalid), self.assertRaises(ValueError): authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "transcribe", "duration_seconds": invalid})
        ctx["tracks"][0]["clips"][0]["kind"] = "midi"
        with self.assertRaises(ScopeError): authorize_start(ctx, freeze_scope(ctx), {"clip_id": "c", "kind": "chords"})

    def test_provenance_drums_and_other_cannot_be_pitch_transcribed(self):
        for role in ("drums", "other"):
            ctx=context(); ctx["tracks"][0]["clips"][0]["analysis_role"]=role
            with self.subTest(role=role), self.assertRaises(ScopeError): authorize_start(ctx, freeze_scope(ctx), {"clip_id":"c", "kind":"transcribe"})

    def test_chord_edit_respects_source_and_time_selection(self):
        ctx=context(); chord={"id":"ch", "analysis_id":"r", "label":"C:maj", "start_seconds":10, "end_seconds":12, "score":0.8,"uncertain":False}
        ctx["selection_context"]["time_range"]={"active":True,"start_seconds":10,"end_seconds":13}
        args={"region_id":"ch","clip_id":"c","label":"D:min","summary":"修正标签"}
        plan=compile_chord_edit(args,chord,ctx,freeze_scope(ctx))
        self.assertEqual(plan["commands"],[{"command":"edit_chord_region","args":{"id":"ch","label":"D:min"}}])
        for change in ({"start_seconds":9}, {"end_seconds":14}, {"label":"C:maj7"}, {"label":"C:maj"}):
            with self.subTest(change=change),self.assertRaises(ValueError): compile_chord_edit({**args,**change},chord,ctx,freeze_scope(ctx))

    def test_project_chord_edit_survives_deleted_source(self):
        ctx=context();ctx["tracks"]=[]
        chord={"id":"ch","analysis_id":"r","label":"C:maj","start_seconds":0,"end_seconds":2,"score":.7,"uncertain":False}
        plan=compile_chord_edit({"region_id":"ch","label":"N","summary":"修正"},chord,ctx,freeze_scope(ctx,"project"))
        self.assertEqual(plan["chord_after"]["label"],"N")

    def test_manual_job_cancel_uses_real_source_scope(self):
        ctx=context();job={"job_id":"manual","kind":"chords","status":"running","source":result()["source"]}
        self.assertEqual(authorize_cancel(ctx,freeze_scope(ctx),job),"manual")
        ctx["selection_context"]["clip_ids"]=[];ctx["selection_context"]["track_ids"]=[]
        with self.assertRaises(ScopeError):authorize_cancel(ctx,freeze_scope(ctx),job)
        self.assertEqual(authorize_cancel(ctx,freeze_scope(ctx,"project"),job),"manual")
        ctx["selection_context"]["clip_ids"]=["c"];ctx["selection_context"]["time_range"]={"active":True,"start_seconds":10,"end_seconds":12}
        with self.assertRaises(ScopeError):authorize_cancel(ctx,freeze_scope(ctx),job)

    def test_cancel_rejects_other_project_import_and_finished_jobs(self):
        ctx=context();job={"job_id":"manual","kind":"chords","status":"running","source":result()["source"]}
        for status in ("ready","applying","applied","cancelled","failed","stale"):
            with self.subTest(status=status),self.assertRaises(ValueError):authorize_cancel(ctx,freeze_scope(ctx,"project"),{**job,"status":status})
        with self.assertRaises(ValueError):authorize_cancel(ctx,freeze_scope(ctx,"project"),{**job,"operation":"import"})
        with self.assertRaises(ScopeError):authorize_cancel(ctx,freeze_scope(ctx,"project"),{**job,"source":{**job["source"],"project_id":"other"}})

    def test_bridge_never_cancels_import_even_before_applying_state(self):
        bridge=object.__new__(DawBridge)
        for kind,status in (("analysis.accept","queued"),("analysis.chords","ready")):
            bridge._request=Mock(return_value={"result":{"kind":kind,"status":status}})
            with self.subTest(kind=kind,status=status),self.assertRaises(BridgeError):bridge.cancel_analysis("job")
            self.assertEqual(bridge._request.call_count,1)
        bridge._request=Mock(side_effect=[{"result":{"kind":"analysis.chords","status":"running"}},{"result":{"cancel_requested":True}}])
        bridge.cancel_analysis("job")
        self.assertEqual([c.args[0]["command"] for c in bridge._request.call_args_list],["get_job","cancel_analysis_job"])

    def test_candidate_stale_source_and_other_project_rejected(self):
        ctx = context()
        for key, value in (("project_id", "other"), ("bpm", 90), ("clip_timeline_start", 9), ("clip_duration", 12)):
            candidate = result(); candidate["source"][key] = value
            with self.subTest(key=key), self.assertRaises(ScopeError): authorize_result(ctx, freeze_scope(ctx), candidate)

    def test_import_uses_only_result_id_not_note_arrays(self):
        ctx = context(); plan = compile_import(result(count=4000), ctx, freeze_scope(ctx), "导入候选")
        self.assertEqual(plan["execution_kind"], "analysis_import")
        self.assertEqual(plan["commands"], [{"command": "accept_analysis_result", "args": {"result_id": "r"}}])
        self.assertEqual(len(plan["analysis"]["items"]), 24)
        self.assertIn("4000", plan["changes"][0])

    def test_reused_or_unhashed_candidate_is_not_plan(self):
        for mutation in ({"applied": True}, {"result_hash": "bad"}, {"total": 0}):
            candidate = result(); candidate.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): compile_import(candidate, context(), freeze_scope(context()), "导入")

    def test_model_context_drops_files_and_runtime_paths(self):
        value = result(); value["source"]["source_path"] = "C:/private.wav"; value["model"]["python_executable"] = "C:/python.exe"
        value["items"][0]["path"] = "C:/stem.wav"
        safe = safe_result(value)
        self.assertNotIn("C:/", str(safe))
        job = safe_job({"id": "j", "status": "failed", "error": "Failed: E:/private/runtime/model.bin", "request_file": "secret"})
        self.assertNotIn("E:/", str(job)); self.assertNotIn("request_file", job)

    def test_host_and_model_both_required_for_capability(self):
        caps = safe_capabilities({"providers": [{"kind": "separate", "available": True, "model_id": "test", "version": "mock"}]})
        groups = capability_groups(context(), {"commands": list(COMMANDS)}, caps)
        self.assertEqual(len(groups), 7)
        self.assertTrue(next(g for g in groups if g["id"] == "separate")["enabled"])
        missing = capability_groups(context(), {"commands": []}, caps)
        self.assertFalse(next(g for g in missing if g["id"] == "separate")["enabled"])
        self.assertFalse(next(g for g in groups if g["id"] == "transcribe")["enabled"])

class AnalysisBridge(FakeBridge):
    def __init__(self, running=False):
        super().__init__(); self.data = context(); self.candidate = result(); self.running = running
        self.started = threading.Event(); self.cancelled = False; self.job_polls = 0
        self.chords = [{"id":"ch","analysis_id":"r","label":"C:maj","start_seconds":8.,"end_seconds":10.,"score":.8,"uncertain":False}]
        self.last_chords = None

    def capabilities(self): return {"commands": list(COMMANDS)}
    def analysis_capabilities(self): return {"providers": [{"kind": "transcribe", "available": True}]}
    def start_analysis(self, context, frozen, args):
        authorize_start(context, frozen, args); self.calls.append(("start", args)); self.started.set(); return {"job_id": "j"}
    def analysis_job(self, jid):
        self.job_polls += 1
        return {"job_id": jid, "result_id": "r", "kind":"transcribe","source":deepcopy(self.candidate["source"]), "status": "cancelled" if self.cancelled else "running" if self.running else "ready"}
    def analysis_result(self, rid, offset=0, limit=24):
        if rid != "r": raise BridgeError("Unknown test result")
        value = deepcopy(self.candidate); value["offset"] = offset; value["items"] = value["items"][offset:offset+limit]; return value
    def cancel_analysis(self, jid): self.calls.append(("cancel", jid)); self.cancelled = True
    def chord_page(self, context, clip_id="", offset=0, limit=100):
        return {"total":len(self.chords),"offset":offset,"items":deepcopy(self.chords[offset:offset+limit]),"score_kind":"uncalibrated_similarity"}
    def find_chord(self, context, region_id, clip_id=""):
        if clip_id not in ("", "c"): raise BridgeError("Wrong provenance fixture")
        return deepcopy(next(c for c in self.chords if c["id"]==region_id))
    def apply(self, plan):
        if plan.get("execution_kind")=="chord_edit":
            self.calls.append(("apply",deepcopy(plan)));self.last_before=deepcopy(self.data);self.last_notes=deepcopy(self.notes);self.last_chords=deepcopy(self.chords)
            self.chords[0].update(plan["commands"][0]["args"]);self.data.update(revision=4,can_undo=True)
            return {"status":"completed","project_id":"p","revision":4,"result":deepcopy(self.chords[0])}
        if plan.get("execution_kind") != "analysis_import": return super().apply(plan)
        self.calls.append(("apply", deepcopy(plan))); self.last_before = deepcopy(self.data); self.last_notes = deepcopy(self.notes)
        return {"status": "accepted", "result": {"job_id": "import", "result_id": "r"}}
    def wait_analysis_import(self, jid):
        self.data["tracks"].append({"id": "new-track", "kind": "instrument", "name": "Transcription", "clips": [
            {"id": "new-clip", "kind": "midi", "start_seconds": 8, "duration_seconds": 10, "note_count": 2}]})
        self.data.update(revision=4, can_undo=True)
        self.candidate["applied"] = True
        return {"result_id": "r", "applied": True, "revision": 4, "track_ids": ["new-track"], "clip_ids": ["new-clip"], "chord_ids": []}
    def undo(self,*args):
        reply=super().undo(*args)
        if self.last_chords is not None:self.chords=deepcopy(self.last_chords)
        return reply

class AnalysisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.runtimes = []
        self.patches = [patch("music_agent.runtime.load_config", return_value=deepcopy(DEFAULT_CONFIG)),
                        patch("music_agent.runtime.has_key", return_value=False), patch("music_agent.providers.has_key", return_value=False)]
        for p in self.patches: p.start()

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.cancel_event.set()
            if runtime.worker: runtime.worker.join(3)
        for p in self.patches: p.stop()
        self.directory.cleanup()

    def make(self, *responses, running=False):
        runtime = AgentRuntime(AnalysisBridge(running), provider=FakeProvider(responses), audit=Audit(Path(self.directory.name)/"audit.jsonl"))
        self.runtimes.append(runtime); return runtime

    def finish(self, runtime):
        runtime.worker.join(3); self.assertFalse(runtime.worker.is_alive()); return runtime.state(False)

    def test_analysis_then_explicit_confirm_import_and_undo(self):
        runtime = self.make(tool("start_audio_analysis", {"clip_id": "c", "kind": "transcribe"}),
                            tool("propose_analysis_import", {"result_id": "r", "summary": "导入转录候选"}))
        runtime.plan_request("把选中的音频转 MIDI", "selection")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "ready", state)
        self.assertEqual(runtime.bridge.data["revision"], 3)
        self.assertEqual(len(runtime.provider.requests), 2)
        self.assertEqual([c[0] for c in runtime.bridge.calls], ["start"])
        plan_id = state["plan"]["id"]
        runtime.apply(plan_id); state = self.finish(runtime)
        self.assertEqual(state["phase"], "done", state)
        self.assertTrue(state["can_undo"])
        with self.assertRaises(ValueError): runtime.apply(plan_id)
        runtime.undo(); self.finish(runtime)
        self.assertEqual(len(runtime.bridge.data["tracks"]), 1)

    def test_stop_cancels_owned_analysis_without_second_model_request(self):
        runtime = self.make(tool("start_audio_analysis", {"clip_id": "c", "kind": "transcribe"}), running=True)
        runtime.plan_request("转录", "selection")
        self.assertTrue(runtime.bridge.started.wait(2)); runtime.cancel()
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "cancelled", state)
        self.assertTrue(runtime.bridge.cancelled)
        self.assertEqual(len(runtime.provider.requests), 1)
        self.assertFalse(any(c[0] == "apply" for c in runtime.bridge.calls))

    def test_scope_changed_after_preview_prevents_import(self):
        runtime = self.make(tool("propose_analysis_import", {"result_id": "r", "summary": "导入"}))
        runtime.plan_request("导入已有候选", "selection"); state = self.finish(runtime)
        self.assertEqual(state["phase"], "ready", state)
        runtime.bridge.data["selection_context"]["selection_revision"] += 1
        runtime.apply(state["plan"]["id"]); state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertFalse(runtime.bridge.calls)

    def test_source_changed_after_inference_cannot_propose(self):
        runtime = self.make(tool("propose_analysis_import", {"result_id": "r", "summary": "导入"}))
        runtime.bridge.candidate["source"]["clip_timeline_start"] = 9
        runtime.plan_request("导入", "project"); state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertFalse(runtime.bridge.calls)

    def test_chord_read_proposal_confirm_readback_and_undo(self):
        runtime=self.make(tool("read_chord_regions",{"clip_id":"c"}),tool("propose_chord_edit",{"region_id":"ch","clip_id":"c","label":"D:min","summary":"修正和弦"}))
        runtime.plan_request("把和弦改为D小三", "selection");state=self.finish(runtime)
        self.assertEqual(state["phase"],"ready",state);self.assertEqual(runtime.bridge.chords[0]["label"],"C:maj")
        runtime.apply(state["plan"]["id"]);state=self.finish(runtime)
        self.assertEqual(state["phase"],"done",state);self.assertEqual(runtime.bridge.chords[0]["label"],"D:min")
        runtime.undo();self.finish(runtime);self.assertEqual(runtime.bridge.chords[0]["label"],"C:maj")

    def test_manual_job_can_be_cancelled_without_being_agent_started(self):
        runtime=self.make(tool("cancel_audio_analysis",{"job_id":"manual"}),{"message":{"role":"assistant","content":"已核对任务取消。"},"usage":{}},running=True)
        runtime.plan_request("停止手动启动的分析", "selection");state=self.finish(runtime)
        self.assertEqual(state["phase"],"done",state);self.assertTrue(runtime.bridge.cancelled)
        self.assertEqual(runtime.bridge.calls,[("cancel","manual")])
        response=runtime.provider.requests[1][-1]
        self.assertTrue(__import__('json').loads(response["content"])["cancel_completed"])

    def test_manual_job_outside_scope_is_not_cancelled(self):
        runtime=self.make(tool("cancel_audio_analysis",{"job_id":"manual"}),running=True)
        selection=runtime.bridge.data["selection_context"];selection["clip_ids"]=[];selection["track_ids"]=[]
        runtime.plan_request("停止分析", "selection");state=self.finish(runtime)
        self.assertEqual(state["phase"],"error");self.assertFalse(runtime.bridge.cancelled);self.assertFalse(runtime.bridge.calls)

if __name__ == "__main__": unittest.main()
