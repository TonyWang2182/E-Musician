"""Two bounded, real configured-provider tasks on a synthetic, never-applied DAW.

Invoked explicitly through the recorded runner, never unittest discovery.
No user project/prompt/audio, credentials or opaque reasoning is persisted.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from music_agent.audit import Audit
from music_agent.config import active_config, load_config
from music_agent.providers import create_provider
from music_agent.runtime import AgentRuntime
from music_agent.localization import public_response
from test_music_agent_mixing import MixBridge


class BoundedProvider:
    def __init__(self,provider):
        self.provider=provider
        self.calls=[]

    def __getattr__(self,name): return getattr(self.provider,name)

    def complete(self,messages,tools):
        if len(self.calls)>=3:
            raise ValueError("Synthetic live evaluation capped at three requests per task.")
        start=time.monotonic()
        # Count attempts, including failure. No automatic retry.
        entry={"status":"started"};self.calls.append(entry)
        response=self.provider.complete(messages,tools)
        entry.update(status="returned",seconds=round(time.monotonic()-start,3),model=response.get("model"),
            usage=response.get("usage"),tools=[c.get("function",{}).get("name") for c in response["message"].get("tool_calls",[])])
        return response


def main():
    output=ROOT/"docs/review/2026-11-08-plugin-agent-stability/agent"
    output.mkdir(parents=True,exist_ok=True)
    settings=active_config(load_config())
    if (settings["provider"],settings["model"],settings["reasoning_effort"]) != ("openai","gpt-5-mini","high"):
        raise RuntimeError("Configured provider/model/effort changed; evaluation stopped without request.")
    report={"fixture":"Three synthetic tracks (Drums, Bass, Pad), one native compressor per track; stopped transport; no real audio",
        "provider":"openai","model":"gpt-5-mini","reasoning_effort":"high","max_output_tokens":4096,
        "request_limit_per_task":3,"tasks":[],"limitations":"Plan validity and tool use only; not listening/mixing quality or real engine apply."}
    try:
        for name,prompt in (
            ("basic_mix","Give this project a conservative starting mix. Keep the arrangement and routing intact. Prepare the changes for review; I will audition them."),
            ("ordinary_edit","Rename the Bass track to Sub Bass and lower its current level by 2 dB. Keep everything else unchanged.")):
            bridge=MixBridge();before=deepcopy(bridge.data)
            provider=BoundedProvider(create_provider("openai",settings["model"],settings["base_url"],reasoning_effort="high"))
            runtime=AgentRuntime(bridge,provider=provider,audit=Audit(ROOT/f"build-logs/agent-mix-live-{name}.jsonl"))
            start=time.monotonic();runtime.plan_request(prompt,scope="project",language="en")
            runtime.worker.join(375)
            state=public_response(runtime.state(False),"en")
            plan=runtime.plan or {}
            result={"name":name,"synthetic_prompt":prompt,"seconds":round(time.monotonic()-start,3),
                "phase":state["phase"],"error_code":state.get("error_code"),"error":state.get("error"),
                "calls":provider.calls,"read_devices":len(bridge.reads),"summary":state.get("plan",{}).get("summary") if state.get("plan") else None,
                "changes":state.get("plan",{}).get("changes") if state.get("plan") else [],
                "commands":plan.get("commands",[]),"engine_unchanged":before==bridge.data,"mutations":len(bridge.calls)}
            report["tasks"].append(result)
            assert not runtime.worker.is_alive(),"Evaluation exceeded bounded request time"
            assert state["phase"]=="ready",f"{name} did not produce a reviewable plan: {state.get('error_code')}"
            assert before==bridge.data and not bridge.calls,"Synthetic project was unexpectedly modified"
            assert 1<=len(plan["commands"])<=16
            if name=="basic_mix":
                assert any("read_mix_context" in c.get("tools",[]) for c in provider.calls),"Model did not batch mix inspection"
                assert len(provider.calls)<=3
                assert {c["command"] for c in plan["commands"]}<={"set_track_gain","set_track_pan","set_native_effect","add_native_effect"},"Mix changed unrelated content"
            else:
                commands=plan["commands"]
                assert any(c["command"]=="rename_track" and c["args"].get("name")=="Sub Bass" for c in commands)
                assert any(c["command"]=="set_track_gain" and c["args"].get("gain_db")==-2 for c in commands)
            result["status"]="passed"
            print(json.dumps({k:result[k] for k in ("name","phase","seconds","read_devices","engine_unchanged","status")},ensure_ascii=True),flush=True)
        report["status"]="passed"
    finally:
        (output/"LIVE-EVAL.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":main()
