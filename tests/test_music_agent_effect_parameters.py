"""Natural one-parameter edits retain authoritative untouched state."""
import unittest
from copy import deepcopy
from test_music_agent_native_effects import context, proposal
from music_agent.plans import PlanError, compile_plan, required_effect_ids, resolve_plan_refs, verify_plan
from music_agent.selection import ScopeError, constrain_proposal, freeze_scope


class EffectParameterIntentTests(unittest.TestCase):
    def test_eq_shapes_are_per_band_absolute_and_legacy_is_preserved(self):
        before=context()
        add={"type":"add_native_effect","track_id":"t","effect_type":"eq8","as":"fx"}
        action={"type":"set_native_effect_parameter","track_id":"t","device_id":"@fx","parameter":"shape","band":4,"value":"high_pass"}
        plan=compile_plan(proposal(add,action),before)
        bands=plan["commands"][-1]["args"]["state"]["bands"]
        self.assertEqual(plan["commands"][-1]["args"]["state"]["version"],2)
        self.assertEqual([bands[i]["shape"] for i in (0,3,4,7)],["low_shelf","high_pass","bell","high_shelf"])
        self.assertEqual(bands[3]["gain_db"],0)
        for change in ({"value":"future"},{"value":True},{"mode":"delta"},{"band":9}):
            with self.subTest(change=change),self.assertRaises(PlanError):compile_plan(proposal(add,{**action,**change}),before)
        from music_agent.plans import validate_effect_state
        legacy=deepcopy(plan["commands"][-1]["args"]["state"])
        for band in legacy["bands"]:del band["shape"]
        resolved=validate_effect_state(legacy)
        self.assertEqual(resolved["version"],1)
        self.assertEqual([b["shape"] for b in resolved["bands"]],["low_shelf"]+["bell"]*6+["high_shelf"])

    def test_sampler_envelope_partial_edit_keeps_other_pad_fields_and_readback(self):
        before=context()
        before["native_instruments"]={"t":{"type":"sampler","device_id":"s","load_status":"ready",
            "root_note":60,"start":0.0,"end":1.0,"pads":[{"index":0,"gain_db":-3.0,"muted":False,
            "attack_ms":25.0,"release_ms":200.0,"one_shot":False,"sample_sha256":"a"*64}]}}
        action={"type":"set_native_pad","track_id":"t","pad":0,"attack_ms":100}
        plan=compile_plan(proposal(action),before)
        desired=plan["commands"][0]["args"]
        self.assertEqual((desired["attack_ms"],desired["release_ms"],desired["one_shot"]),(100,200,False))
        self.assertEqual((desired["gain_db"],desired["muted"]),(-3,False))
        with self.assertRaises(PlanError):compile_plan(proposal({"type":"set_native_pad","track_id":"t","pad":0}),before)
        after=deepcopy(before);after["revision"]+=1;after["native_instruments"]["t"]["pads"][0]["attack_ms"]=100
        self.assertEqual(verify_plan(plan,before,after),[])
        after["native_instruments"]["t"]["pads"][0]["release_ms"]=30
        self.assertTrue(verify_plan(plan,before,after))
        for change in ({"attack_ms":0},{"release_ms":5001},{"one_shot":1},{"attack_ms":float("nan")}):
            with self.subTest(change=change),self.assertRaises(PlanError):compile_plan(proposal({**action,**change}),before)
        self.assertEqual(before["native_instruments"]["t"]["pads"][0]["attack_ms"],25)

    def test_relative_compressor_change_preserves_rest_and_checks_readback(self):
        before = context()
        action = {"type":"set_native_effect_parameter", "track_id":"t", "device_id":"c",
                  "parameter":"threshold_db", "mode":"delta", "value":-3}
        self.assertEqual(required_effect_ids(proposal(action)), [("t", "c")])
        plan = compile_plan(proposal(action), before)
        command = plan["commands"][0]
        self.assertEqual(command["command"], "set_native_effect")
        desired = deepcopy(before["native_effects"]["c"])
        desired["threshold_db"] = -21
        self.assertEqual(command["args"]["state"], desired)
        self.assertEqual(before["native_effects"]["c"]["threshold_db"], -18)
        after = deepcopy(before); after["revision"] += 1; after["native_effects"]["c"] = desired
        self.assertEqual(verify_plan(plan, before, after), [])
        after["native_effects"]["c"]["ratio"] = 7
        self.assertTrue(verify_plan(plan, before, after))

    def test_new_eq_alias_and_chained_band_edits(self):
        before = context()
        plan = compile_plan(proposal(
            {"type":"add_native_effect", "track_id":"t", "effect_type":"eq8", "as":"eq"},
            {"type":"set_native_effect_parameter", "track_id":"t", "device_id":"@eq", "parameter":"gain_db", "band":3, "value":4},
            {"type":"set_native_effect_parameter", "track_id":"t", "device_id":"@eq", "parameter":"frequency", "band":3, "value":1000},
        ), before)
        self.assertEqual([c["command"] for c in plan["commands"]], ["add_native_effect", "set_native_effect", "set_native_effect"])
        state = plan["commands"][-1]["args"]["state"]
        self.assertEqual(state["bands"][2]["gain_db"], 4)
        self.assertEqual(state["bands"][2]["frequency"], 1000)
        self.assertEqual(state["bands"][3]["frequency"], 500)
        self.assertEqual(resolve_plan_refs(plan,{"eq":"new"})["refs"], {"eq":"new"})

    def test_rejects_wrong_scope_and_invalid_parameters_without_mutation(self):
        before = context()
        base = {"type":"set_native_effect_parameter", "track_id":"t", "device_id":"c", "parameter":"ratio", "value":4}
        for variation in ({"value":21}, {"value":True}, {"band":1}, {"parameter":"enabled"}, {"mode":"delta","value":-20}, {"mode":[]}):
            with self.subTest(variation=variation), self.assertRaises(PlanError):
                compile_plan(proposal({**base, **variation}), before)
        before["selection_context"].update(focus="piano_roll", note_ids=["n"], note_count=1, note_clip_id="x")
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal(base), before, freeze_scope(before,"selection"))

    def test_eq_enabled_and_bad_band_are_checked(self):
        before = context()
        actions = [{"type":"add_native_effect","track_id":"t","effect_type":"eq8","as":"fx"},
                   {"type":"set_native_effect_parameter","track_id":"t","device_id":"@fx","parameter":"enabled","band":1,"value":False}]
        plan=compile_plan(proposal(*actions),before)
        self.assertIs(plan["commands"][-1]["args"]["state"]["bands"][0]["enabled"], False)
        for change in ({"band":0}, {"band":True}, {"mode":"delta"}, {"value":1}):
            with self.subTest(change=change), self.assertRaises(PlanError):
                compile_plan(proposal(actions[0], {**actions[1], **change}),before)

    def test_compressor_dry_wet_legacy_default_and_relative_change(self):
        before = context()
        del before["native_effects"]["c"]["dry_wet"]  # old stored state defaults to fully wet
        action = {"type":"set_native_effect_parameter", "track_id":"t", "device_id":"c",
                  "parameter":"dry_wet", "mode":"delta", "value":-0.3}
        plan = compile_plan(proposal(action), before)
        self.assertAlmostEqual(plan["commands"][0]["args"]["state"]["dry_wet"], .7)
        with self.assertRaises(PlanError):
            compile_plan(proposal({**action,"value":.1}), before)

    def test_delay_and_reverb_alias_parameter_limits(self):
        before=context()
        for kind,parameter,value in (("delay","feedback",.9),("reverb","decay_seconds",4)):
            actions=[{"type":"add_native_effect","track_id":"t","effect_type":kind,"as":"fx"},
                     {"type":"set_native_effect_parameter","track_id":"t","device_id":"@fx","parameter":parameter,"value":value}]
            with self.subTest(kind=kind):
                plan=compile_plan(proposal(*actions),before)
                self.assertEqual(plan["commands"][-1]["args"]["state"][parameter],value)
                with self.assertRaises(PlanError):
                    compile_plan(proposal(actions[0],{**actions[1],"value":10000}),before)

    def test_auto_filter_mode_lfo_and_cutoff_are_independently_editable(self):
        before=context()
        add={"type":"add_native_effect","track_id":"t","effect_type":"auto_filter","as":"fx"}
        def change(parameter,value,**extra):
            return {"type":"set_native_effect_parameter","track_id":"t","device_id":"@fx","parameter":parameter,"value":value,**extra}
        plan=compile_plan(proposal(add,change("mode","high_pass"),change("lfo_enabled",True),change("frequency_hz",500)),before)
        state=plan["commands"][-1]["args"]["state"]
        self.assertEqual(state["mode"],"high_pass");self.assertIs(state["lfo_enabled"],True)
        self.assertEqual(state["frequency_hz"],500);self.assertEqual(state["lfo_depth"],0)
        for action in (change("mode","band_pass"),change("mode","high_pass",mode="delta"),
                       change("lfo_enabled",1),change("lfo_enabled",True,mode="delta"),
                       change("resonance_q",0.4),change("lfo_hz",21)):
            with self.subTest(action=action),self.assertRaises(PlanError):compile_plan(proposal(add,action),before)

if __name__ == "__main__": unittest.main()
