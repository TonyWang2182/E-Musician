"""Real sidebar HTML/JS, synthetic waiting/error data; no LLM or desktop."""
from http.server import ThreadingHTTPServer
import html
import json
from pathlib import Path
import re
import subprocess
import threading
import uuid
import HybridAgentWebSmoke as hybrid
from GenerationAgentWebSmoke import fixture
from music_agent.mixing import capability_group
from music_agent.localization import L
from test_music_agent_mixing import MixBridge

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"build/agent-mix-web"
hybrid.HARNESS=r"""<script>
window.__errors=[];window.addEventListener('error',e=>window.__errors.push(e.message));
let attempts=0;const check=setInterval(()=>{
 const mix=document.querySelector('[data-capability="mix"]');
 if((!mix||!document.getElementById('busy-detail').textContent)&&++attempts<50)return;
 clearInterval(check); if(mix)mix.open=true;
 document.body.setAttribute('data-analysis-smoke',JSON.stringify({
 progress:document.getElementById('busy-detail').textContent,
 notice:document.getElementById('notice').textContent,
 capability:mix?.textContent, model:document.getElementById('current-model').title,
 prompt:mix?.querySelector('button')?.textContent,
 widthOK:document.documentElement.scrollWidth<=innerWidth,errors:window.__errors}));
},100);</script>"""


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True); reports=[]
    for kind in ("waiting","output_limit"):
        state=fixture();state.update(plan=None,snapshot=MixBridge().snapshot(),messages=[],capability_groups=[capability_group(MixBridge().capabilities())])
        state["provider"].update(id="openai",model="gpt-5-mini",reasoning_effort="high")
        state["model_request"]={"waiting":kind=="waiting","elapsed_seconds":49,"timeout_seconds":120,"round":2,"max_rounds":6}
        state.update(phase="planning" if kind=="waiting" else "error",busy=kind=="waiting",error_code=None,error=None)
        state["progress"]={"stage":"model","label":L("\u7b49\u5f85\u6a21\u578b \u00b7 \u7b2c 2/6 \u8f6e\uff1b\u5c1a\u672a\u4fee\u6539\u5de5\u7a0b","Waiting for model · round 2/6; project unchanged")}
        if kind=="output_limit":
            state.update(error_code="output_limit",error="The model reached its output and reasoning token limit before completing a plan. No edits were made. Request a smaller task, or lower reasoning effort in model settings before retrying.")
            state["progress"]={"stage":"error","label":state["error"]}
        server=ThreadingHTTPServer(("127.0.0.1",0),hybrid.Handler)
        server.fixture=state;server.request_languages=[]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/?embedded=1&lang=en#token=synthetic-ui-test"
            process=subprocess.run(["node",str(ROOT/"tests/analysis_agent_web_capture.mjs"),
                "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",str(OUTPUT/(uuid.uuid4().hex+"-profile")),url,str(OUTPUT/kind),"340","850"],capture_output=True,timeout=45)
            (OUTPUT/(kind+".stderr.log")).write_bytes(process.stderr)
            assert process.returncode==0,process.stderr.decode(errors="replace")
            match=re.search(r'data-analysis-smoke="([^"]*)"',process.stdout.decode("utf-8"));assert match
            checks=json.loads(html.unescape(match.group(1)))
            assert checks["widthOK"] and not checks["errors"],checks
            assert not re.search(r"[\u4e00-\u9fff]",checks["capability"]+checks["progress"]+checks["notice"]),checks
            assert "Basic mix" in checks["capability"] and "current scope" in checks["prompt"],checks
            assert "openai" in checks["model"].lower() and "high" in checks["model"] and "120s" in checks["model"],checks
            if kind=="waiting": assert "49s / 120s" in checks["progress"] and "round 2/6" in checks["progress"],checks
            else: assert "[output_limit]" in checks["notice"] and "No edits were made" in checks["notice"],checks
            reports.append({"case":kind,"status":"passed",**checks});print(kind,"PASS")
        finally:server.shutdown();server.server_close();thread.join(2)
    (OUTPUT/"results.json").write_text(json.dumps(reports,indent=2)+"\n",encoding="utf-8")


if __name__=="__main__":main()
