"""Real DAW, offline memory-device integration; --live explicitly calls the selected provider."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from music_agent.audit import Audit
from music_agent.bridge import DawBridge, BridgeError
from music_agent.runtime import AgentRuntime
from music_agent.providers import create_provider

def proposal(actions):
    return {"message":{"role":"assistant","content":None,"tool_calls":[
        {"id":"proposal","type":"function","function":{"name":"propose_plan",
          "arguments":json.dumps({"summary":"\u96c6\u6210\u6d4b\u8bd5\u4fee\u6539","actions":actions})}}]},"usage":{}}
class FakeProvider:
    model="synthetic-fixture"
    base_url="https://api.moonshot.cn/v1"
    def __init__(self,responses): self.responses=iter(responses)
    def complete(self,*_): return next(self.responses)
class MeasuredProvider:
    """Count actual attempts and returned token usage separately from fixture calls."""
    def __init__(self,provider):
        self.provider=provider
        self.usage={"attempts":0,"completed_responses":0,"prompt_tokens":0,"completion_tokens":0}
        self.returned_models=set()
    def __getattr__(self,name):return getattr(self.provider,name)
    def complete(self,*args,**kwargs):
        self.usage["attempts"]+=1
        response=self.provider.complete(*args,**kwargs)
        self.usage["completed_responses"]+=1
        usage=response.get("usage") or {}
        for field in ("prompt_tokens","completion_tokens"):
            self.usage[field]+=max(0,int(usage.get(field,0)))
        if isinstance(response.get("model"),str):self.returned_models.add(response["model"])
        return response
def wait(runtime):
    deadline=time.monotonic()+120
    while runtime.busy() and time.monotonic()<deadline:
        time.sleep(.02)
    assert not runtime.busy(),"Task exceeded integration deadline"
    return runtime.state(False)
def execute(runtime, text):
    # This fixture intentionally operates on the whole disposable project.
    runtime.plan_request(text,scope="project")
    ready=wait(runtime)
    assert ready["phase"]=="ready",ready.get("error") or ready["messages"][-1]
    runtime.apply(ready["plan"]["id"])
    done=wait(runtime)
    assert done["phase"]=="done",done.get("error")
    return done
def protected():
    locations=[Path(os.environ.get("APPDATA",""))/"E-musician",
               Path("E:/E-musician/test-projects")]
    result={}
    for directory in locations:
        if directory.is_dir():
            for p in directory.rglob("*"):
                if p.is_file() and (p.suffix.lower() in {".xml",".emproj",".json",".mid",".wav",".mp3"}) and p.stat().st_size<20*1024*1024:
                    result[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--exe",required=True,type=Path)
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--provider",choices=["kimi","openai"],default="kimi")
    parser.add_argument("--model",help="Optional exact model ID; otherwise use the selected provider registry default.")
    args=parser.parse_args()
    directory=ROOT/"build"/"music-agent-integration"/str(uuid.uuid4())
    directory.mkdir(parents=True)
    report={"mode":"live-"+args.provider if args.live else "synthetic-provider-real-daw",
            "requested_provider":args.provider,"requested_model":args.model,
            "exe_sha256":hashlib.sha256(args.exe.read_bytes()).hexdigest(),
            "physical_audio":False,"checks":[],"passed":False}
    guard=protected()
    bridge=DawBridge(args.exe,offline=True)
    real_provider=None
    synthetic_providers=[]
    def fixture_provider(responses):
        measured=MeasuredProvider(FakeProvider(responses))
        synthetic_providers.append(measured)
        return measured
    def command(name,values):
        state=bridge.snapshot()
        return bridge._request({"request_id":str(uuid.uuid4()),"project_id":state["project_id"],
             "expected_revision":state["revision"],"command":name,"args":values})
    try:
        if args.live:
            real_provider=MeasuredProvider(create_provider(args.provider,model=args.model))
            provider=real_provider
        else:
            provider=fixture_provider([
              proposal([{"type":"set_tempo","bpm":98},{"type":"create_track","kind":"instrument","name":"Agent test piano"}])])
        report["configured_model"]=provider.model
        runtime=AgentRuntime(bridge,provider,Audit(directory/"audit.jsonl"))
        execute(runtime,"\u5c06\u5de5\u7a0b\u901f\u5ea6\u8bbe\u4e3a98 BPM\uff0c\u5e76\u65b0\u5efa\u4e00\u6761\u540d\u4e3a Agent test piano \u7684 MIDI \u4e50\u5668\u8f68\u3002\u8bf7\u76f4\u63a5\u63d0\u51fa\u4e00\u4e2a\u65b9\u6848\u3002")
        report["checks"].append("tempo + new track plan/atomic apply/native readback")
        state=bridge.snapshot()
        assert state["bpm"]==98 and len(state["tracks"])==1
        tid=state["tracks"][0]["id"]
        command("create_midi_clip",{"track_id":tid,"start_beats":0,"length_beats":16})
        state=bridge.snapshot()
        cid=state["tracks"][0]["clips"][0]["id"]
        original=[{"id":"agent-integration-note-"+str(i),"pitch":60+i,"start_beats":i+.125,
                   "length_beats":.5,"velocity":80,"channel":1} for i in range(4)]
        command("write_notes",{"clip_id":cid,"notes":original})
        if not args.live:
            runtime.provider=fixture_provider([
              {"message":{"role":"assistant","content":None,"reasoning_content":"synthetic","tool_calls":[
                {"id":"read","type":"function","function":{"name":"read_clip_notes","arguments":json.dumps({"clip_id":cid})}}]},"usage":{}},
              proposal([{"type":"transpose_notes","clip_id":cid,"semitones":2},{"type":"set_track_gain","track_id":tid,"gain_db":-4}])])
        execute(runtime,"\u8bf7\u628a\u552f\u4e00 MIDI \u7247\u6bb5\u7684\u6240\u6709\u97f3\u7b26\u5347\u9ad82\u4e2a\u534a\u97f3\uff0c\u5e76\u628a\u8fd9\u6761\u8f68\u9053\u97f3\u91cf\u8bbe\u4e3a-4 dB\u3002")
        after=bridge.snapshot()
        bridge.read_notes(after,cid)
        assert [n["pitch"] for n in after["clip_notes"][cid]]==[n["pitch"]+2 for n in original]
        assert abs(after["tracks"][0]["gain_db"]+4)<.001
        report["checks"].append("read tool -> note transpose + track gain -> native verification")
        runtime.undo()
        undone=wait(runtime)
        assert undone["phase"]=="done",undone.get("error")
        state=bridge.snapshot()
        bridge.read_notes(state,cid)
        assert [n["pitch"] for n in state["clip_notes"][cid]]==[n["pitch"] for n in original]
        assert abs(state["tracks"][0]["gain_db"])<.001
        report["checks"].append("single undo restores both notes and mix")
        # Freeze real model evidence before the conflict fixture switches provider.
        # Report totals below are provider-owned counters, never mixed runtime totals.
        report["real_provider_phase_complete"]=bool(args.live)
        # No further model calls: test concurrent manual edit against an approved plan.
        runtime.provider=fixture_provider([proposal([{"type":"set_tempo","bpm":110}])])
        runtime.plan_request("fixture stale plan",scope="project")
        ready=wait(runtime)
        assert ready["phase"]=="ready",ready.get("error")
        command("rename_track",{"track_id":tid,"name":"Manual edit after proposal"})
        runtime.apply(ready["plan"]["id"])
        stale=wait(runtime)
        assert stale["phase"]=="error" and bridge.snapshot()["bpm"]==98
        report["checks"].append("concurrent manual edit rejects stale plan without mutation")
        capabilities=bridge._request({"command":"get_capabilities"})["result"]
        if "get_selection_context" in capabilities.get("commands",[]):
            selection=bridge._request({"command":"get_selection_context"})["result"]
            before=bridge.snapshot()
            try:
                bridge._request({"request_id":str(uuid.uuid4()),"project_id":before["project_id"],
                    "expected_revision":before["revision"],
                    "expected_selection_revision":selection["selection_revision"]+1,
                    "command":"set_tempo","args":{"bpm":111}})
            except BridgeError as exc:
                assert "selection changed" in str(exc),"Wrong rejection reason for stale selection"
            else:raise AssertionError("Native write accepted a stale selection revision")
            unchanged=bridge.snapshot()
            assert unchanged["bpm"]==98 and unchanged["revision"]==before["revision"]
            report["checks"].append("native selection revision guard rejects without mutation")
        else:
            report["selection_native_guard"]="not available in the tested executable"
        report["passed"]=True
    except Exception as exc:
        report["error"]=str(exc)[:1000]
    finally:
        # Disposable fixture only. Never closes an existing user's DAW.
        bridge.close()
        report["real_model_usage"]=({**real_provider.usage,"returned_models":sorted(real_provider.returned_models)}
            if real_provider else {"attempts":0,"completed_responses":0,"prompt_tokens":0,"completion_tokens":0,"returned_models":[]})
        report["synthetic_provider_usage"]={field:sum(p.usage[field] for p in synthetic_providers)
            for field in ("attempts","completed_responses","prompt_tokens","completion_tokens")}
        report["usage_note"]="Real provider attempts/token totals exclude synthetic conflict tests. A failed attempt may be billed without returned usage."
        report["protected_file_count"]=len(guard)
        report["protected_files_unchanged"]=protected()==guard
        report["passed"]=report["passed"] and report["protected_files_unchanged"]
        (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
