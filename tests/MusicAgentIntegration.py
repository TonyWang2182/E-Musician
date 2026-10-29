"""Real DAW, offline memory-device integration. --live explicitly uses Kimi."""
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
from music_agent.bridge import DawBridge
from music_agent.runtime import AgentRuntime
from music_agent.provider import KimiProvider

def proposal(actions):
    return {"message":{"role":"assistant","content":None,"tool_calls":[
        {"id":"proposal","type":"function","function":{"name":"propose_plan",
          "arguments":json.dumps({"summary":"集成测试修改","actions":actions})}}]},"usage":{}}
class FakeProvider:
    model="synthetic-fixture"
    base_url="https://api.moonshot.cn/v1"
    def __init__(self,responses): self.responses=iter(responses)
    def complete(self,*_): return next(self.responses)
def wait(runtime):
    deadline=time.monotonic()+120
    while runtime.busy() and time.monotonic()<deadline:
        time.sleep(.02)
    assert not runtime.busy(),"Task exceeded integration deadline"
    return runtime.state(False)
def execute(runtime, text):
    runtime.plan_request(text)
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
    args=parser.parse_args()
    directory=ROOT/"build"/"music-agent-integration"/str(uuid.uuid4())
    directory.mkdir(parents=True)
    report={"mode":"live-kimi" if args.live else "synthetic-provider-real-daw",
            "exe_sha256":hashlib.sha256(args.exe.read_bytes()).hexdigest(),
            "physical_audio":False,"checks":[],"passed":False}
    guard=protected()
    bridge=DawBridge(args.exe,offline=True)
    def command(name,values):
        state=bridge.snapshot()
        return bridge._request({"request_id":str(uuid.uuid4()),"project_id":state["project_id"],
             "expected_revision":state["revision"],"command":name,"args":values})
    try:
        provider=KimiProvider(model="kimi-k2.6") if args.live else FakeProvider([
          proposal([{"type":"set_tempo","bpm":98},{"type":"create_track","kind":"instrument","name":"Agent test piano"}])])
        runtime=AgentRuntime(bridge,provider,Audit(directory/"audit.jsonl"))
        execute(runtime,"将工程速度设为98 BPM，并新建一条名为 Agent test piano 的 MIDI 乐器轨。请直接提出一个方案。")
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
            runtime.provider=FakeProvider([
              {"message":{"role":"assistant","content":None,"reasoning_content":"synthetic","tool_calls":[
                {"id":"read","type":"function","function":{"name":"read_clip_notes","arguments":json.dumps({"clip_id":cid})}}]},"usage":{}},
              proposal([{"type":"transpose_notes","clip_id":cid,"semitones":2},{"type":"set_track_gain","track_id":tid,"gain_db":-4}])])
        execute(runtime,"请把唯一 MIDI 片段的所有音符升高2个半音，并把这条轨道音量设为-4 dB。")
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
        report["live_model_calls"] = runtime.usage["calls"] if args.live else 0
        # No further model calls: test concurrent manual edit against an approved plan.
        runtime.provider=FakeProvider([proposal([{"type":"set_tempo","bpm":110}])])
        runtime.plan_request("fixture stale plan")
        ready=wait(runtime)
        assert ready["phase"]=="ready",ready.get("error")
        command("rename_track",{"track_id":tid,"name":"Manual edit after proposal"})
        runtime.apply(ready["plan"]["id"])
        stale=wait(runtime)
        assert stale["phase"]=="error" and bridge.snapshot()["bpm"]==98
        report["checks"].append("concurrent manual edit rejects stale plan without mutation")
        report["usage"]=runtime.usage
        report["passed"]=True
    except Exception as exc:
        report["error"]=str(exc)[:1000]
    finally:
        # Disposable fixture only. Never closes an existing user's DAW.
        bridge.close()
        report["protected_file_count"]=len(guard)
        report["protected_files_unchanged"]=protected()==guard
        report["passed"]=report["passed"] and report["protected_files_unchanged"]
        (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
