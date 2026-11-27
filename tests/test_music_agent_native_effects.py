"""Native effects remain bounded, scoped and independently verified."""
from copy import deepcopy
import math
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.plans import PlanError, compile_plan, resolve_plan_refs, verify_plan, validate_effect_state
from music_agent.selection import ScopeError, constrain_proposal, freeze_scope
from music_agent.bridge import DawBridge, BridgeError, public_snapshot
from music_agent.runtime import AgentRuntime
from music_agent.native_catalog import agent_effect_catalog, agent_instrument_catalog


def compressor():
    return {"version":1,"type":"compressor","threshold_db":-18,"ratio":4,"attack_ms":10,"release_ms":100,"makeup_db":0,"dry_wet":1}

def fake_effect_catalog():
    return {"version":1,"types":[{"type":kind,"bands":data["bands"],"readable":True,"writable":True,
            "parameters":[{"name":name,**spec} for name,spec in data["parameters"].items()]}
            for kind,data in agent_effect_catalog().items()]}

def fake_instrument_catalog():
    types=[]
    for kind,data in agent_instrument_catalog().items():
        item={k:v for k,v in data.items() if k!="actions"};item["type"]=kind
        item["actions"]=[{"command":name,"parameters":[{"name":p,**details} for p,details in params.items()]}
                         for name,params in data["actions"].items()]
        types.append(item)
    return {"version":1,"types":types}


def context():
    return {"project_id":"p","revision":2,"bpm":120,"numerator":4,"denominator":4,"clip_notes":{},
      "tracks":[{"id":"t","name":"Piano","kind":"instrument","gain_db":0,"pan":0,"muted":False,"solo":False,
                 "clips":[],"plugins":[{"id":"c","name":"Compressor","format":"E-musician","is_instrument":False}]}],
      "native_effects":{"c":compressor()},"selection_context":{"project_id":"p","project_revision":2,"selection_revision":1,
      "active_track_id":"t","active_clip_id":"","track_ids":["t"],"clip_ids":[],"note_clip_id":"","note_ids":[],
      "note_count":0,"notes_truncated":False,"time_range":{"active":False,"start_seconds":0,"end_seconds":0},"focus":"track","available":True}}


def proposal(*actions):
    return {"summary":"Native effect", "actions":list(actions)}


class NativeEffectTests(unittest.TestCase):
    def test_create_and_set_bind_alias_and_verify_real_readback(self):
        before=context()
        state=compressor(); state["ratio"]=7
        plan=compile_plan(proposal({"type":"add_native_effect","track_id":"t","effect_type":"compressor","as":"fx"},
                                   {"type":"set_native_effect","track_id":"t","device_id":"@fx","state":state}),before)
        self.assertEqual(plan["commands"][0],{"command":"add_native_effect","args":{"track_id":"t","type":"compressor"},"as":"fx"})
        self.assertEqual(plan["commands"][1]["args"]["device_id"],"@fx")
        resolved=resolve_plan_refs(plan,{"fx":"new-fx"})
        after=deepcopy(before); after["revision"]=3
        after["tracks"][0]["plugins"].append({"id":"new-fx","name":"Compressor","format":"E-musician","is_instrument":False})
        after["native_effects"]["new-fx"]=deepcopy(state)
        self.assertEqual(verify_plan(resolved,before,after),[])
        after["native_effects"]["new-fx"]["ratio"]=4
        self.assertTrue(verify_plan(resolved,before,after))
        after["native_effects"].pop("new-fx")
        self.assertTrue(verify_plan(resolved,before,after))

    def test_existing_effect_needs_valid_complete_baseline_and_device_ownership(self):
        before=context(); desired=compressor(); desired["ratio"]=5
        action={"type":"set_native_effect","track_id":"t","device_id":"c","state":desired}
        self.assertEqual(compile_plan(proposal(action),before)["commands"][0]["args"]["state"]["ratio"],5)
        no_state=deepcopy(before); no_state["native_effects"]={}
        with self.assertRaises(PlanError): compile_plan(proposal(action),no_state)
        bad=deepcopy(before); bad["tracks"][0]["plugins"][0]["format"]="VST3"
        with self.assertRaises(PlanError): compile_plan(proposal(action),bad)
        wrong=deepcopy(action); wrong["state"]["type"]="eq8"
        with self.assertRaises(PlanError): compile_plan(proposal(wrong),before)

    def test_parameter_validation(self):
        for field,value in [("ratio",True),("ratio",math.inf),("threshold_db",-61),("attack_ms",0),("release_ms",2001),("makeup_db",25)]:
            state=compressor();state[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(PlanError): validate_effect_state(state)
        with self.assertRaises(PlanError): validate_effect_state({**compressor(),"path":"C:/sample.wav"})
        for bands in ([],[{"enabled":True,"frequency":20,"gain_db":0,"q":1}]*7,
                      [{"enabled":1,"frequency":20,"gain_db":0,"q":1}]*8):
            with self.assertRaises(PlanError): validate_effect_state({"version":1,"type":"eq8","bands":bands})

    def test_selection_requires_selected_whole_track(self):
        before=context();action={"type":"add_native_effect","track_id":"t","effect_type":"eq8"}
        self.assertEqual(constrain_proposal(proposal(action),before,freeze_scope(before,"selection"))["actions"][0]["type"],"add_native_effect")
        before["selection_context"]["focus"]="piano_roll"
        before["selection_context"]["note_ids"]=["n"]
        before["selection_context"]["note_count"]=1
        before["selection_context"]["note_clip_id"]="c"
        with self.assertRaises(ScopeError): constrain_proposal(proposal(action),before,freeze_scope(before,"selection"))

    def test_master_effect_alias_scope_and_readback(self):
        before=context(); before["master_plugins"]=[]
        desired=compressor(); desired["threshold_db"]=-12
        actions=proposal({"type":"add_native_effect","track_id":"master","effect_type":"compressor","as":"master_fx"},
                         {"type":"set_native_effect","track_id":"master","device_id":"@master_fx","state":desired})
        plan=compile_plan(actions,before)
        with self.assertRaises(ScopeError): constrain_proposal(actions,before,freeze_scope(before,"selection"))
        self.assertEqual(plan["commands"][0]["args"],{"track_id":"master","type":"compressor"})
        self.assertEqual(plan["commands"][1]["args"]["device_id"],"@master_fx")
        plan=resolve_plan_refs(plan,{"master_fx":"mfx"})
        after=deepcopy(before);after["revision"]=3
        after["master_plugins"]=[{"id":"mfx","name":"Compressor","format":"E-musician","is_instrument":False}]
        after["native_effects"]["mfx"]=desired
        self.assertEqual(verify_plan(plan,before,after),[])
        after["master_plugins"]=[]
        self.assertTrue(verify_plan(plan,before,after))
        with self.assertRaises(PlanError): compile_plan(proposal({"type":"set_track_gain","track_id":"master","gain_db":-2}),before)

    def test_snapshot_removes_third_party_plugin_paths_on_all_tracks(self):
        raw=context();raw["tracks"][0]["plugins"].append({"id":"v1","name":"C:\\secret\\Synth.vst3","identifier":"C:\\secret\\Synth.vst3","format":"VST3","is_instrument":True})
        raw["master_plugins"]=[{"id":"v2","name":"Effect","identifier":"E:\\private\\Effect.vst3","format":"VST3","is_instrument":False}]
        clean=public_snapshot(raw)
        self.assertNotIn("secret",json.dumps(clean)); self.assertNotIn("private",json.dumps(clean))
        self.assertEqual(clean["tracks"][0]["plugins"][-1]["name"],"Plugin")
        self.assertEqual(clean["master_plugins"][0]["name"],"Effect")

    def test_master_read_uses_master_snapshot_and_rejects_track_mismatch(self):
        class Client:
            def raw(self,request):
                if request["command"]=="get_snapshot":
                    result=context();result["master_plugins"]=[{"id":"mc","name":"Compressor","format":"E-musician","is_instrument":False}]
                elif request["command"]=="get_capabilities": result={"native_effect_catalog":fake_effect_catalog()}
                elif request["command"]=="get_native_effect":
                    self.assert_called=request["args"];result={"device_id":"mc","state":compressor()}
                else: raise AssertionError(request["command"])
                return {"request_id":request["request_id"],"status":"completed","result":result}
            def close(self): pass
        client=Client();bridge=DawBridge(client=client);snapshot=bridge.snapshot()
        self.assertEqual(bridge.read_native_effect(snapshot,"master","mc")["type"],"compressor")
        self.assertEqual(client.assert_called,{"track_id":"master","device_id":"mc"})
        with self.assertRaises(BridgeError): bridge.read_native_effect(snapshot,"t","mc")
        plan={"scope":{"mode":"selection"},"commands":[{"command":"set_native_effect","args":{"track_id":"master"}}]}
        with self.assertRaises(BridgeError): bridge.apply(plan)

    def test_runtime_reads_proposes_then_verifies_readback(self):
        class FakeClient:
            def __init__(self):
                self.project=context(); self.effect=compressor(); self.reads=0; self.corrupt=False
            def raw(self, request):
                command=request["command"]; result={}
                if command == "get_snapshot": result=deepcopy(self.project)
                elif command == "get_capabilities": result={"native_effect_catalog":fake_effect_catalog()}
                elif command == "get_native_effect":
                    self.reads+=1; result={"device_id":"c","state":deepcopy(self.effect)}
                    if self.corrupt: result["state"]["ratio"]=2
                elif command == "batch":
                    if request["expected_revision"] != self.project["revision"]: raise AssertionError("stale write")
                    edits=request["args"]["commands"]
                    if len(edits)!=1 or edits[0]["command"]!="set_native_effect": raise AssertionError("unexpected batch")
                    self.effect=deepcopy(edits[0]["args"]["state"]); self.project["revision"]+=1
                else: raise AssertionError(command)
                return {"request_id":request["request_id"],"status":"completed","result":result,
                        "project_id":"p","revision":self.project["revision"]}
            def close(self): pass
        class Provider:
            model="fake"; base_url="https://example.invalid"; provider_id="kimi"
            def __init__(self): self.calls=0
            def complete(self,messages,tools):
                self.calls+=1
                names={item["function"]["name"] for item in tools}
                if "read_native_effect" not in names: raise AssertionError("missing read tool")
                if self.calls==1: name="read_native_effect"; args={"track_id":"t","device_id":"c"}
                else:
                    name="propose_plan"; desired=compressor();desired["ratio"]=7
                    args=proposal({"type":"set_native_effect","track_id":"t","device_id":"c","state":desired})
                return {"message":{"role":"assistant","content":None,"tool_calls":[{"id":"call","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]},"usage":{}}
        class NullAudit:
            def write(self,*args,**kwargs): pass
        client=FakeClient(); bridge=DawBridge(client=client)
        with patch("music_agent.runtime.has_key",return_value=False), patch("music_agent.providers.has_key",return_value=False):
            runtime=AgentRuntime(bridge,provider=Provider(),audit=NullAudit())
            runtime.plan_request("\u8c03\u6574\u538b\u7f29\u6bd4",scope="selection"); runtime.worker.join(4)
            self.assertFalse(runtime.busy()); self.assertEqual(runtime.phase,"ready",runtime.error)
            self.assertEqual(client.effect["ratio"],4)
            plan_id=runtime.plan["id"]; runtime.apply(plan_id); runtime.worker.join(4)
            self.assertFalse(runtime.busy()); self.assertEqual(runtime.phase,"done",runtime.error)
            self.assertEqual(client.effect["ratio"],7); self.assertGreaterEqual(client.reads,3)

    def test_sampler_single_async_scope_and_parameter_validation(self):
        before=context(); before["native_instruments"]={"t":{"type":"sampler","device_id":"s","load_status":"ready",
            "root_note":60,"start":0.0,"end":1.0,"pads":[{"index":0,"gain_db":0.0,"muted":False,"sample_sha256":"a"*64}]}}
        action={"type":"set_native_pad","track_id":"t","pad":0,"gain_db":-4,"muted":False}
        plan=compile_plan(proposal(action),before)
        self.assertEqual(plan["execution_kind"],"native_async")
        with self.assertRaises(ScopeError): constrain_proposal(proposal(action),before,freeze_scope(before,"selection"))
        with self.assertRaises(PlanError): compile_plan(proposal(action,{"type":"set_tempo","bpm":100}),before)
        empty=deepcopy(before);empty["native_instruments"]["t"]["pads"][0]["sample_sha256"]=""
        with self.assertRaises(PlanError): compile_plan(proposal(action),empty)
        with self.assertRaises(PlanError): compile_plan(proposal({"type":"set_native_sampler","track_id":"t","root_note":60,"start":0.9,"end":0.1}),before)

    def test_sampler_runtime_waits_for_commit_and_hides_path(self):
        class Client:
            def __init__(self):
                self.project=context(); self.polls=0; self.writes=0; self.fail=False
                self.state={"type":"sampler","device_id":"s","load_status":"ready","root_note":60,"start":0.0,"end":1.0,
                    "pads":[{"index":0,"gain_db":0.0,"muted":False,"sample_sha256":"a"*64,"path":"C:/private/sample.wav"}]}
            def raw(self,request):
                command=request["command"]; status="completed"; result={}
                if command=="get_snapshot": result=deepcopy(self.project)
                elif command=="get_capabilities": result={"native_instrument_catalog":fake_instrument_catalog()}
                elif command=="get_native_instrument": result=deepcopy(self.state)
                elif command=="set_native_pad":
                    self.writes+=1;self.pending=deepcopy(request["args"]);status="accepted";result={"job_id":"native-1"}
                elif command=="get_job":
                    self.polls+=1
                    if self.fail: result={"id":"native-1","status":"conflict","error":"changed"}
                    elif self.polls==1: result={"id":"native-1","status":"running"}
                    else:
                        self.state["pads"][0].update(gain_db=self.pending["gain_db"],muted=self.pending["muted"])
                        self.project["revision"]+=1;result={"id":"native-1","status":"completed"}
                else: raise AssertionError(command)
                return {"request_id":request["request_id"],"status":status,"result":result,"project_id":"p","revision":self.project["revision"]}
            def close(self): pass
        class Provider:
            model="fake";base_url="https://example.invalid";provider_id="kimi"
            def __init__(self): self.calls=0
            def complete(self,messages,tools):
                self.calls+=1
                if self.calls==1: name="read_native_instrument";args={"track_id":"t"}
                else:
                    assert "C:/private" not in json.dumps(messages)
                    name="propose_plan";args=proposal({"type":"set_native_pad","track_id":"t","pad":0,"gain_db":-4,"muted":False})
                return {"message":{"role":"assistant","content":None,"tool_calls":[{"id":"call","function":{"name":name,"arguments":json.dumps(args)}}]},"usage":{}}
        class NullAudit:
            def write(self,*args,**kwargs): pass
        client=Client();bridge=DawBridge(client=client)
        with patch("music_agent.runtime.has_key",return_value=False),patch("music_agent.providers.has_key",return_value=False):
            runtime=AgentRuntime(bridge,provider=Provider(),audit=NullAudit())
            runtime.plan_request("\u964d\u4f4e\u91c7\u6837\u589e\u76ca",scope="project");runtime.worker.join(4)
            self.assertEqual(runtime.phase,"ready",runtime.error)
            runtime.apply(runtime.plan["id"]);runtime.worker.join(4)
            self.assertEqual(runtime.phase,"done",runtime.error)
            self.assertEqual((client.writes,client.polls),(1,2));self.assertEqual(client.state["pads"][0]["gain_db"],-4)
            self.assertEqual(runtime.undo_target,("p",3))
        with self.assertRaisesRegex(BridgeError,"outcome is unknown"):
            bridge.wait_native_job("native-1",timeout=0)
        # A timed-out accepted task is consumed, never automatically retried.
        client2=Client();bridge2=DawBridge(client=client2)
        with patch("music_agent.runtime.has_key",return_value=False),patch("music_agent.providers.has_key",return_value=False):
            runtime2=AgentRuntime(bridge2,provider=Provider(),audit=NullAudit())
            runtime2.plan_request("\u964d\u4f4e\u91c7\u6837\u589e\u76ca",scope="project");runtime2.worker.join(4)
            self.assertEqual(runtime2.phase,"ready",runtime2.error)
            bridge2.wait_native_job=lambda job_id: (_ for _ in ()).throw(BridgeError("transport unavailable"))
            runtime2.apply(runtime2.plan["id"]);runtime2.worker.join(4)
            self.assertEqual(runtime2.phase,"error");self.assertIn("outcome is unknown",runtime2.error)
            self.assertEqual(client2.writes,1);self.assertIsNone(runtime2.plan);self.assertIsNone(runtime2.undo_target)


if __name__ == "__main__": unittest.main()
