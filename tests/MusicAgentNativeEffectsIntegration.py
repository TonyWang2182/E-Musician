"""Owned offline DAW + deterministic model: native async parameter and EQ batch.

Run with scripts.dev.Recorder and --exe PATH. No real project, audio device,
model service or third-party plugin is used. All fixture files are unique.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client
from music_agent.bridge import DawBridge
from music_agent.runtime import AgentRuntime
from music_agent.native_catalog import validate_effect_catalog
from NativeDeviceEndToEnd import make_fixture
from MusicAgentIntegration import protected


class Provider:
    model="fixture";base_url="https://example.invalid";provider_id="kimi"
    def __init__(self, payload): self.payload=payload
    def complete(self, messages, tools):
        return {"message":{"role":"assistant","content":None,"tool_calls":[{"id":"call","type":"function",
            "function":{"name":"propose_plan","arguments":json.dumps(self.payload)}}]},"usage":{}}


class NullAudit:
    def write(self,*args,**kwargs): pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--exe",type=Path,required=True);parser.add_argument("--timeout",type=float,default=90)
    args=parser.parse_args()
    if not args.exe.is_file() or args.timeout <= 0: parser.error("A valid executable and positive timeout are required")
    directory=ROOT/"build"/"agent-native-e2e"/str(uuid.uuid4());directory.mkdir(parents=True)
    fixture=directory/"fixture.wav";make_fixture(fixture)
    before=protected();checks=[];client=None
    report={"mode":"offline-owned-control-stdio", "external_model":False,"physical_audio":False,"checks":checks,"passed":False}
    def wait(runtime):
        runtime.worker.join(args.timeout)
        if runtime.busy(): raise AssertionError("Agent worker timed out")
        if runtime.phase=="error": raise AssertionError(runtime.error)
    try:
        client=Client(args.exe,timeout=args.timeout,show=False,offline_test=True)
        assert not client.state()["tracks"]
        client.request({"command":"create_track","args":{"kind":"instrument","name":"Owned test"}})
        track=client.state()["tracks"][0]["id"]
        client.request({"command":"add_native_instrument","args":{"track_id":track,"type":"sampler"}})
        client.request({"command":"set_native_sample","args":{"track_id":track,"pad":0,"path":str(fixture)}})
        bridge=DawBridge(client=client)
        snapshot=bridge.snapshot(); sample=bridge.read_native_instrument(snapshot,track)
        assert sample["pads"][0]["sample_sha256"] and "path" not in json.dumps(sample)
        checks.append("owned WAV sample loaded asynchronously; sanitized instrument read")
        proposal={"summary":"Lower sample gain and shape envelope", "actions":[{"type":"set_native_pad","track_id":track,"pad":0,"gain_db":-7,"muted":False,"attack_ms":70,"release_ms":240,"one_shot":True}]}
        with patch("music_agent.runtime.has_key",return_value=False),patch("music_agent.providers.has_key",return_value=False):
            runtime=AgentRuntime(bridge,provider=Provider(proposal),audit=NullAudit())
            runtime.plan_request("Lower sample gain",scope="project");wait(runtime)
            assert runtime.phase=="ready" and runtime.plan["execution_kind"]=="native_async"
            assert bridge.read_native_instrument(bridge.snapshot(),track)["pads"][0]["gain_db"]==0
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase=="done" and runtime.undo_target
            assert abs(bridge.read_native_instrument(bridge.snapshot(),track)["pads"][0]["gain_db"]+7)<1e-5
            actual_pad=bridge.read_native_instrument(bridge.snapshot(),track)["pads"][0]
            assert (actual_pad["attack_ms"],actual_pad["release_ms"],actual_pad["one_shot"])==(70,240,True)
            checks.append("async approved sampler operation reached terminal completion and verified real readback")
            runtime.undo();wait(runtime)
            deadline=time.monotonic()+args.timeout
            while time.monotonic()<deadline:
                try:
                    restored=bridge.read_native_instrument(bridge.snapshot(),track)
                    if abs(restored["pads"][0]["gain_db"])<1e-5: break
                except Exception: pass
                time.sleep(.05)
            else: raise AssertionError("Sampler undo did not restore loaded sample state")
            checks.append("one Agent undo restored sampler gain")
            assert (restored["pads"][0]["attack_ms"],restored["pads"][0]["release_ms"],restored["pads"][0]["one_shot"])==(3,30,False)
            checks.append("new sample envelope and playback mode controlled and undone through real Agent path")
            bands=[{"enabled":True,"frequency":f,"gain_db":0,"q":.7071} for f in (60,120,250,500,1000,2500,6000,12000)]
            bands[3]["gain_db"]=3
            eq={"version":1,"type":"eq8","bands":bands}
            runtime.provider=Provider({"summary":"Add and set EQ", "actions":[
                {"type":"add_native_effect","track_id":track,"effect_type":"eq8","as":"fx"},
                {"type":"set_native_effect","track_id":track,"device_id":"@fx","state":eq}]})
            runtime.plan_request("Add EQ",scope="project");wait(runtime)
            assert runtime.phase=="ready"
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase=="done"
            eq_id=next(p["id"] for p in bridge.snapshot()["tracks"][0]["plugins"] if p["name"]=="EQ Eight")
            assert abs(bridge.read_native_effect(bridge.snapshot(),track,eq_id)["bands"][3]["gain_db"]-3)<1e-5
            checks.append("atomic add and set EQ resolved actual alias and verified readback")
            eq_before = bridge.read_native_effect(bridge.snapshot(),track,eq_id)
            runtime.provider=Provider({"summary":"Raise band three by 2 dB", "actions":[
                {"type":"set_native_effect_parameter","track_id":track,"device_id":eq_id,
                 "parameter":"gain_db","band":3,"mode":"delta","value":2}]})
            runtime.plan_request("\u628a\u7b2c\u4e09\u6bb5\u63d0\u9ad82 dB\uff0c\u5176\u4ed6\u4fdd\u6301\u4e0d\u53d8",scope="project");wait(runtime)
            assert runtime.phase == "ready"
            pending = runtime.plan["commands"][0]
            assert pending["command"] == "set_native_effect"
            assert bridge.read_native_effect(bridge.snapshot(),track,eq_id) == eq_before
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase == "done" and runtime.undo_target
            eq_after = bridge.read_native_effect(bridge.snapshot(),track,eq_id)
            expected = deepcopy(eq_before);expected["bands"][2]["gain_db"] += 2
            assert eq_after == expected, (eq_after,expected)
            runtime.undo();wait(runtime)
            assert bridge.read_native_effect(bridge.snapshot(),track,eq_id) == eq_before
            checks.append("relative EQ band edit preserved all other values and one undo restored baseline")
            runtime.provider=Provider({"summary":"Set high pass", "actions":[
                {"type":"set_native_effect_parameter","track_id":track,"device_id":eq_id,"parameter":"shape","band":1,"value":"high_pass"},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":eq_id,"parameter":"frequency","band":1,"value":120}]})
            runtime.plan_request("\u7b2c\u4e00\u6bb5\u8bbe\u4e3a120 Hz\u9ad8\u901a",scope="project");wait(runtime)
            assert runtime.phase=="ready"
            runtime.apply(runtime.plan["id"]);wait(runtime);assert runtime.phase=="done"
            highpass=bridge.read_native_effect(bridge.snapshot(),track,eq_id)
            assert highpass["bands"][0]["shape"]=="high_pass" and highpass["bands"][0]["frequency"]==120
            assert highpass["bands"][1:]==eq_before["bands"][1:]
            runtime.undo();wait(runtime);assert bridge.read_native_effect(bridge.snapshot(),track,eq_id)==eq_before
            checks.append("EQ shape and cutoff controlled through real Agent batch with Undo and untouched-band preservation")
            comp={"version":1,"type":"compressor","threshold_db":-12,"ratio":3,"attack_ms":10,"release_ms":100,"makeup_db":0}
            runtime.provider=Provider({"summary":"Add and set master effects", "actions":[
                {"type":"add_native_effect","track_id":"master","effect_type":"eq8","as":"master_eq"},
                {"type":"set_native_effect","track_id":"master","device_id":"@master_eq","state":eq},
                {"type":"add_native_effect","track_id":"master","effect_type":"compressor","as":"master_comp"},
                {"type":"set_native_effect","track_id":"master","device_id":"@master_comp","state":comp}]})
            runtime.plan_request("Add master EQ and compressor",scope="project");wait(runtime)
            assert runtime.phase=="ready"
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase=="done"
            master=bridge.snapshot()["master_plugins"]
            master_eq=next(p["id"] for p in master if p["name"]=="EQ Eight")
            master_comp=next(p["id"] for p in master if p["name"]=="Compressor")
            assert abs(bridge.read_native_effect(bridge.snapshot(),"master",master_eq)["bands"][3]["gain_db"]-3)<1e-5
            assert abs(bridge.read_native_effect(bridge.snapshot(),"master",master_comp)["threshold_db"]+12)<1e-5
            checks.append("master EQ and compressor added, configured and independently read back")
            runtime.provider=Provider({"summary":"Add delay and reverb", "actions":[
                {"type":"add_native_effect","track_id":track,"effect_type":"delay","as":"delay"},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":"@delay","parameter":"feedback","value":.4},
                {"type":"add_native_effect","track_id":track,"effect_type":"reverb","as":"reverb"},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":"@reverb","parameter":"decay_seconds","value":2.5}]})
            runtime.plan_request("Add delay and reverb",scope="project");wait(runtime)
            assert runtime.phase=="ready"
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase=="done"
            plugins=bridge.snapshot()["tracks"][0]["plugins"]
            delay_id=next(p["id"] for p in plugins if p["name"]=="Stereo Delay")
            reverb_id=next(p["id"] for p in plugins if p["name"]=="Reverb")
            assert abs(bridge.read_native_effect(bridge.snapshot(),track,delay_id)["feedback"]-.4)<1e-5
            assert abs(bridge.read_native_effect(bridge.snapshot(),track,reverb_id)["decay_seconds"]-2.5)<1e-5
            checks.append("delay and reverb additions, partial parameters, aliases and readback")
            runtime.provider=Provider({"summary":"Add Auto Filter", "actions":[
                {"type":"add_native_effect","track_id":track,"effect_type":"auto_filter","as":"filter"},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":"@filter","parameter":"mode","value":"high_pass"},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":"@filter","parameter":"frequency_hz","value":2000},
                {"type":"set_native_effect_parameter","track_id":track,"device_id":"@filter","parameter":"lfo_enabled","value":True}]})
            runtime.plan_request("Add high-pass Auto Filter",scope="project");wait(runtime)
            assert runtime.phase=="ready"
            runtime.apply(runtime.plan["id"]);wait(runtime)
            assert runtime.phase=="done"
            filter_id=next(p["id"] for p in bridge.snapshot()["tracks"][0]["plugins"] if p["name"]=="Auto Filter")
            filter_state=bridge.read_native_effect(bridge.snapshot(),track,filter_id)
            assert filter_state["mode"]=="high_pass" and filter_state["lfo_enabled"] is True and filter_state["frequency_hz"]==2000
            checks.append("Auto Filter mode, cutoff and LFO enabled via real Agent batch and readback")
            catalog=bridge.capabilities()["native_effect_catalog"]
            assert validate_effect_catalog(catalog)
            ids={"eq8":(track,eq_id),"compressor":("master",master_comp),"delay":(track,delay_id),"reverb":(track,reverb_id),"auto_filter":(track,filter_id)}
            for descriptor in catalog["types"]:
                kind=descriptor["type"];owner,device=ids[kind]
                state=bridge.read_native_effect(bridge.snapshot(),owner,device)
                names={p["name"] for p in descriptor["parameters"]}
                actual=set(state["bands"][0]) if kind=="eq8" else set(state)-{"version","type"}
                assert names==actual,(kind,names,actual)
            checks.append("registered host types and actual state fields match the Agent catalogue")
        report["passed"]=True
    finally:
        if client: client.close()
        after_protected=protected()
        report["protected_unchanged"]=before==after_protected
        report["protected_changes"]={"added":sorted(set(after_protected)-set(before)),
            "removed":sorted(set(before)-set(after_protected)),
            "modified":sorted(k for k in set(before)&set(after_protected) if before[k]!=after_protected[k])}
        if not report["protected_unchanged"]: report["passed"]=False
        (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({**report,"report":str(directory/"report.json")},ensure_ascii=False))
    if not report["passed"]: raise SystemExit(1)


if __name__=="__main__": main()
