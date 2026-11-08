"""Synthetic mix inspection and planning boundaries; no real audio/model calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.bridge import public_snapshot, BridgeError
from music_agent.localization import public_response
from music_agent.mixing import read_mix_context, capability_group
from music_agent.openai_provider import OpenAIProvider
from music_agent.provider import ProviderError
from music_agent.selection import freeze_scope, ScopeError
from test_music_agent_native_effects import context, compressor, fake_effect_catalog, fake_instrument_catalog
import test_music_agent_runtime as runtime_fixture
from test_music_agent_runtime import FakeBridge, tool, proposal


class MixBridge(FakeBridge):
    """Three synthetic tracks, each with an installed native compressor."""
    def __init__(self):
        super().__init__()
        self.data = context()
        first = self.data["tracks"][0]
        self.data["tracks"] = []
        self.effects = {}
        for index, name in enumerate(("Drums", "Bass", "Pad")):
            track = deepcopy(first)
            track.update(id=f"t{index}", name=name, gain_db=(4 if index == 0 else 0), pan=(.7 if index == 1 else 0),
                         output_target_id="master", peak_left_db=-100, peak_right_db=-100, overloaded=False,
                         sends=[], automation=[])
            track["plugins"][0]["id"] = f"fx{index}"
            self.effects[f"fx{index}"] = compressor()
            self.data["tracks"].append(track)
        self.data.update(native_effects={}, playing=False, master_gain_db=-6, master_plugins=[], position_seconds=0)
        self.data["selection_context"].update(active_track_id="t0", track_ids=["t0"])
        self.reads = []

    def capabilities(self):
        return {"commands":["get_native_effect","set_native_effect","set_track_gain","set_track_pan","get_native_instrument"],
                "native_effect_catalog":fake_effect_catalog(), "native_instrument_catalog":fake_instrument_catalog()}

    def read_native_effect(self, context, track_id, device_id):
        assert any(t["id"] == track_id and any(p["id"] == device_id for p in t["plugins"]) for t in self.data["tracks"])
        self.reads.append((track_id, device_id))
        context.setdefault("native_effects", {})[device_id] = deepcopy(self.effects[device_id])
        return deepcopy(self.effects[device_id])


class MixInspectionTests(unittest.TestCase):
    def test_batch_read_all_effects_and_truthful_stopped_meter_semantics(self):
        bridge = MixBridge(); ctx = bridge.snapshot()
        result = read_mix_context(bridge, ctx, freeze_scope(ctx,"project"), {})
        self.assertEqual(len(result["tracks"]),3)
        self.assertEqual(len(result["native_effects"]),3)
        self.assertEqual(len(bridge.reads),3)
        self.assertEqual(len(ctx["native_effects"]),3)
        self.assertFalse(result["observation"]["playing"])
        self.assertFalse(result["observation"]["freshness_verified"])
        self.assertFalse(result["observation"]["whole_song_loudness_available"])
        self.assertFalse(bridge.calls)

    def test_scope_master_and_malformed_ids_fail_before_effect_reads(self):
        for args in ({"track_ids":["t1"]},{"include_master":True},{"track_ids":["t0","t0"]},{"include_effects":1}):
            bridge=MixBridge();ctx=bridge.snapshot()
            with self.subTest(args=args), self.assertRaises((ValueError,ScopeError)):
                read_mix_context(bridge,ctx,freeze_scope(ctx,"selection"),args)
            self.assertFalse(bridge.reads)
        bridge=MixBridge();ctx=bridge.snapshot()
        result=read_mix_context(bridge,ctx,freeze_scope(ctx,"selection"),{})
        self.assertEqual([t["id"] for t in result["tracks"]],["t0"])

    def test_effect_read_revision_change_rejects_entire_result(self):
        bridge=MixBridge();ctx=bridge.snapshot(); original=bridge.read_native_effect
        def changed(*args):
            value=original(*args);bridge.data["revision"]+=1;return value
        with patch.object(bridge,"read_native_effect",side_effect=changed),self.assertRaises(BridgeError):
            read_mix_context(bridge,ctx,freeze_scope(ctx,"project"),{})

    def test_track_and_effect_limits_are_reported_not_hidden(self):
        bridge=MixBridge()
        first=deepcopy(bridge.data["tracks"][0])
        bridge.data["tracks"]=[{**deepcopy(first),"id":f"t{i}"} for i in range(17)]
        ctx=bridge.snapshot()
        result=read_mix_context(bridge,ctx,freeze_scope(ctx,"project"),{"include_effects":False})
        self.assertEqual(len(result["tracks"]),16)
        self.assertTrue(result["tracks_truncated"])
        self.assertEqual(result["authorized_track_count"],17)
        bridge=MixBridge();first=bridge.data["tracks"][0]
        first["plugins"]=[{**first["plugins"][0],"id":f"fx{i}"} for i in range(17)]
        bridge.effects={f"fx{i}":compressor() for i in range(17)}
        ctx=bridge.snapshot()
        result=read_mix_context(bridge,ctx,freeze_scope(ctx,"selection"),{})
        self.assertEqual(len(result["native_effects"]),16)
        self.assertTrue(result["effects_truncated"])

    def test_public_mix_metadata_keeps_safe_routes_but_not_private_fields(self):
        raw=MixBridge().snapshot();track=raw["tracks"][0]
        track["input_device_id"]="PRIVATE_DRIVER"
        track["plugins"][0]["identifier"]="PRIVATE_PLUGIN_PATH"
        track["automation"]=[{"id":"a","target":"volume","enabled":True,"point_count":2,"points":"PRIVATE_POINTS"}]
        track["sends"]=[{"id":"s","target_track_id":"t2","gain_db":-12,"enabled":True,"private":"PRIVATE_SEND"}]
        snapshot=public_snapshot(raw);rendered=json.dumps(snapshot)
        for secret in ("PRIVATE_DRIVER","PRIVATE_PLUGIN_PATH","PRIVATE_POINTS","PRIVATE_SEND"):
            self.assertNotIn(secret,rendered)
        self.assertEqual(snapshot["tracks"][0]["output_target_id"],"master")
        self.assertEqual(snapshot["tracks"][0]["peak_left_db"],-100)
        self.assertEqual(snapshot["master_gain_db"],-6)
        self.assertFalse(snapshot["meter_observation"]["whole_song_loudness_available"])
        self.assertTrue(capability_group(MixBridge().capabilities())["enabled"])
        self.assertFalse(capability_group({})["enabled"])

    def test_reasoning_wait_budget_does_not_change_model_or_token_budget(self):
        provider=OpenAIProvider(reasoning_effort="high")
        self.assertEqual(provider.model,"gpt-5-mini")
        self.assertEqual(provider.reasoning_effort,"high")
        self.assertEqual(provider.timeout,120)
        self.assertEqual(OpenAIProvider(timeout=45).timeout,45)


class MixRuntimeTests(unittest.TestCase):
    setUp=runtime_fixture.RuntimeTests.setUp
    tearDown=runtime_fixture.RuntimeTests.tearDown
    make=runtime_fixture.RuntimeTests.make
    finish=runtime_fixture.RuntimeTests.finish

    def test_inspect_three_devices_then_review_in_two_rounds_without_writing(self):
        runtime=self.make(tool("read_mix_context",{}),proposal({"type":"set_track_gain","track_id":"t0","gain_db":-2}))
        runtime.bridge=MixBridge()
        runtime.plan_request("Prepare a conservative starting mix.",scope="project",language="en")
        state=public_response(self.finish(runtime),"en")
        self.assertEqual(state["phase"],"ready",state)
        self.assertEqual(state["usage"]["calls"],2)
        self.assertEqual(len(runtime.bridge.reads),3)
        self.assertFalse(runtime.bridge.calls)
        self.assertEqual(runtime.bridge.data["tracks"][0]["gain_db"],4)
        result=json.loads(runtime.provider.requests[1][-1]["content"])
        self.assertEqual(len(result["native_effects"]),3)
        self.assertIn("not a finished mastering judgment",runtime.provider.requests[0][0]["content"])
        audit=[json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        tools=[e for e in audit if e["event"]=="tools_requested"]
        self.assertEqual(tools[0]["tool_names"],["read_mix_context"])
        self.assertEqual(audit[0]["scope"],"project")

    def test_timeout_visible_error_code_and_metadata_no_raw_error_or_prompt(self):
        runtime=self.make()
        with patch.object(runtime.provider,"complete",side_effect=ProviderError("timeout","Model request timed out.")):
            runtime.plan_request("PRIVATE_REQUEST",scope="project",language="en")
            state=self.finish(runtime)
        self.assertEqual(state["phase"],"error")
        self.assertEqual(state["error_code"],"timeout")
        self.assertFalse(state["model_request"]["waiting"])
        audit=self.audit_path.read_text(encoding="utf-8")
        self.assertIn('"code": "timeout"',audit)
        self.assertIn('"duration_ms"',audit)
        self.assertNotIn("PRIVATE_REQUEST",audit)
        self.assertNotIn("Model request timed out",audit)
        self.assertEqual(len(runtime.bridge.calls),0)

    def test_pending_request_is_visible_and_answer_only_has_outcome(self):
        runtime=self.make({"message":{"role":"assistant","content":"Advice only."}},block=True)
        runtime.plan_request("Only explain mixing.",scope="project",language="en")
        self.assertTrue(runtime.provider.entered.wait(1))
        pending=public_response(runtime.state(False),"en")
        self.assertTrue(pending["model_request"]["waiting"])
        self.assertIn("round 1/6",pending["progress"]["label"])
        runtime.provider.release.set();state=self.finish(runtime)
        self.assertEqual(state["phase"],"done")
        self.assertIn("answered_no_edit",self.audit_path.read_text(encoding="utf-8"))

    def test_round_budget_has_distinct_visible_code(self):
        runtime=self.make(*[tool("read_clip_notes",{"clip_id":"clip-1"}) for _ in range(6)])
        runtime.plan_request("Synthetic repeated reads",scope="project",language="en")
        state=public_response(self.finish(runtime),"en")
        self.assertEqual(state["error_code"],"tool_round_limit")
        self.assertIn("6-round",state["error"])
        self.assertFalse(runtime.bridge.calls)


if __name__ == "__main__": unittest.main()
