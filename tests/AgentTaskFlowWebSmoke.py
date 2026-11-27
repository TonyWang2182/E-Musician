"""Agent task flow on real web assets, synthetic HTTP state, owned headless Edge.

No provider requests, audio devices, model jobs or user projects are touched.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import re
import subprocess
import threading
import uuid

from GenerationAgentWebSmoke import fixture as generation_fixture

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "scripts/music_agent/web"
OUTPUT = ROOT / "build/agent-task-flow-web"


def fixture(kind):
    state = generation_fixture()
    state["snapshot"]["name"] = "Neo soul study"
    state.update(can_undo=False, messages=[{"role": "user", "content": "Generate a short neo soul demo with vocals. Keep my original tracks."},
        {"role": "assistant", "origin": "runtime", "content": "A reviewable candidate is ready."}])
    state["plan"]["generation"].update(model_id="ace_step", execution="cloud")
    if kind in ("working", "receiving", "chords", "cancelling", "cancel-pending", "checking"):
        state.update(phase="planning", busy=True, plan=None, pause_requested=False,
            progress={"stage": "generating"}, generation_jobs=[{"job_id": "synthetic-job", "model_id": "ace_step", "phase": "running", "progress": 1.0}])
        if kind == "receiving": state["generation_jobs"][-1]["phase"] = "downloading"
        if kind == "chords":
            state.update(progress={"stage": "analyzing"}, analysis_jobs=[{"job_id": "synthetic-analysis", "model_id": "chordmini", "kind": "chords", "phase": "running", "progress": 1.0}])
        if kind == "cancelling": state.update(phase="cancelled")
        if kind == "cancel-pending":
            # cancel() leaves phase planning until its live worker acknowledges;
            # stage cancelled is a request, not confirmation of remote shutdown.
            state.update(progress={"stage":"cancelled","label":"Cancellation requested. Waiting for the in-flight request to finish; no further edits will be applied."},
                         last_result="Cancellation requested. Waiting for the in-flight request to finish; no further edits will be applied.")
        if kind == "checking": state.update(progress={"stage":"checking","label":"Preparing the selected result…"})
    elif kind in ("done", "done-view"): state.update(phase="done", plan=None, can_undo=True, last_result="Applied one change.")
    elif kind == "stale": state["snapshot"]["revision"] += 1
    elif kind == "error": state.update(phase="error", plan=None, error_code="insufficient_quota", error="API credits unavailable. No edits were made.")
    elif kind == "idle": state.update(phase="idle", plan=None, messages=[])
    elif kind in ("choices", "single-error", "choices-stale", "choices-busy"):
        state["generation_choices"] = [
            {"result_id": "earlier-yue", "model_id": "yue2", "duration_seconds": 31.81, "available": True, "applied": False, "selected": False, "truncated": True},
            {"result_id": "current-ace", "model_id": "ace-step-1.5-xl-turbo", "duration_seconds": 32.0, "available": True, "applied": False, "selected": True},
            {"result_id": "already-added", "model_id": "ace_step", "duration_seconds": 16, "available": True, "applied": True, "selected": False},
            {"result_id": "unavailable", "model_id": "yue2", "duration_seconds": 16, "available": False, "applied": False, "selected": False}]
        if kind == "single-error":
            state["generation_choices"] = state["generation_choices"][:1]
            state.update(phase="error", plan=None, error_code="insufficient_quota", error="Model quota exhausted after music finished. Candidate preserved.")
        if kind == "choices-stale": state["snapshot"]["revision"] += 1
        if kind == "choices-busy": state.update(phase="planning", busy=True, plan=None)
    return state


HARNESS = "<script>\nwindow.__taskErrors=[];window.addEventListener('error',e=>window.__taskErrors.push(e.message));\nlet attempt=0;const delay=ms=>new Promise(r=>setTimeout(r,ms));const check=setInterval(async()=>{\n const $=id=>document.getElementById(id);\n if((!$('connection')?.classList.contains('connected')||$('refresh').disabled)&&++attempt<50)return;\n clearInterval(check);\n const kind=new URLSearchParams(location.search).get('testcase'), visible=id=>!$(id).hidden;\n const r={kind,locale:document.documentElement.lang,width:innerWidth,widthOK:document.documentElement.scrollWidth<=innerWidth,\n  detailsClosed:!$('technical-details').open,historyClosed:!$('conversation-history').open,planDetailsClosed:!$('plan-details').open,\n  phase:$('phase').textContent,progressVisible:visible('task-progress'),indicatorValue:$('task-indicator').getAttribute('value'),\n  hint:$('progress-copy').textContent,cancelVisible:visible('cancel-work'),cancelEnabled:!$('cancel-work').disabled,pauseEnabled:!$('pause-work').disabled,\n  planVisible:visible('plan'),applyEnabled:!$('apply').disabled,staleVisible:visible('plan-stale'),\n  previewVisible:visible('generation-preview'),resultVisible:visible('result'),undoVisible:visible('undo'),undoEnabled:!$('undo').disabled,\n  notice:$('notice-text').textContent,errorDetailsClosed:!$('notice-details').open,technical:$('technical-details').textContent,\n  choicesVisible:visible('generation-choices'),planIdIndependentOfPrompt:true};\n if(kind==='idle'){\n   $('prompt').value='Keep my draft \u7528\u6237\u7d20\u6750';$('prompt').dispatchEvent(new Event('input'));\n   window.emusicianSetLanguage(r.locale==='en'?'zh-CN':'en');\n   r.draftPreserved=$('prompt').value==='Keep my draft \u7528\u6237\u7d20\u6750';\n   window.emusicianSetLanguage(r.locale);$('settings-toggle').click();\n   r.settingsAccessible=!$('settings').hidden&&$('api-key').type==='password';$('settings-toggle').click();\n   $('prompt').focus();r.focusable=document.activeElement===$('prompt');\n }\n if(['choices','single-error','choices-stale','choices-busy'].includes(kind)){\n   const buttons=[...$('generation-choice-list').querySelectorAll('button')];\n   r.choiceDisabled=buttons.map(b=>b.disabled);r.choiceNames=[...$('generation-choice-list').querySelectorAll('strong')].map(n=>n.textContent);if(kind!=='choices-busy'){buttons[0].click();await delay(500);}\n   r.chosenReview=$('generation-choice-list').querySelector('li.selected')?.textContent;\n   r.noImplicitApply=!$('plan').hidden&&!$('apply').disabled&&!visible('result');\n }\n if(kind==='done'){$('undo').click();await delay(350);r.undoSent=true;r.undoResultVisible=visible('result')&&$('result-text').textContent==='Undo complete.';}\n if(kind==='apply'){$('apply').click();await delay(350);r.appliedResult=visible('result')&&visible('undo')&&!$('undo').disabled;}\n if(kind==='working'){$('cancel-work').click();await delay(350);r.cancelSent=true;}\n if(kind==='cancel-pending'){$('cancel-work').click();$('pause-work').click();await delay(100);}\n r.posts=await(await fetch('/test-events')).json();r.errors=window.__taskErrors;\n $('transcript').scrollTop=0;\n document.body.setAttribute('data-analysis-smoke',JSON.stringify(r));\n},100);</script>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send(self, value, mime="application/json"):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", mime+"; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state": self.send(self.server.fixture); return
        if path == "/test-events": self.send(self.server.events); return
        if path not in ("/", "/app.js", "/i18n.js", "/style.css"): self.send_error(404); return
        data = (WEB/("index.html" if path == "/" else path[1:])).read_bytes()
        if path == "/": data = data.replace(b"</body>", HARNESS.encode()+b"</body>")
        self.send(data, "text/html" if path == "/" else "text/css" if path.endswith("css") else "text/javascript")
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.server.events.append({"path": self.path, "body": payload})
        state = self.server.fixture
        if self.path == "/api/generation/select":
            for choice in state["generation_choices"]: choice["selected"] = choice["result_id"] == payload["result_id"]
            if not state.get("plan"): state["plan"]=generation_fixture()["plan"]
            state.update(phase="ready",error=None,error_code=None)
            state["plan"].update(id="new-review-plan",revision=state["snapshot"]["revision"])
            state["plan"]["generation"].update(model_id="yue2", completion={"truncated": True})
        if self.path == "/api/undo": state.update(can_undo=False, last_result="Undo complete.")
        if self.path == "/api/apply": state.update(phase="done",plan=None,can_undo=True,last_result="Applied one change.")
        if self.path == "/api/cancel": state.update(phase="cancelled", busy=False, last_result="Stopped. No edits made.")
        self.send(state)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reports=[]
    cases=[("idle",320,"en"),("working",400,"en"),("receiving",320,"en"),("chords",400,"zh-CN"),
           ("cancelling",320,"en"),("ready",400,"en"),("ready",320,"zh-CN"),("done",400,"en"),
           ("stale",320,"en"),("error",400,"en"),("error",320,"zh-CN"),("choices",400,"en"),("choices",320,"zh-CN"),
           ("single-error",400,"en"),("choices-stale",320,"en"),("choices-busy",320,"en"),("apply",400,"en"),("done-view",400,"en"),
           ("cancel-pending",320,"en"),("cancel-pending",400,"zh-CN"),("checking",320,"en"),("checking",400,"zh-CN")]
    for kind,width,language in cases:
        label=f"flow-{kind}-{width}-{language}"
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler); server.fixture=fixture(kind); server.events=[]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/?embedded=1&lang={language}&testcase={kind}#token=synthetic-test-only"
            language = "en"
            proc=subprocess.run(["node",str(ROOT/"tests/analysis_agent_web_capture.mjs"),"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",str(OUTPUT/(uuid.uuid4().hex+"-profile")),url,str(OUTPUT/label),str(width),"850"],capture_output=True,timeout=45)
            (OUTPUT/(label+".stderr.log")).write_bytes(proc.stderr)
            assert proc.returncode==0,proc.stderr.decode(errors="replace")
            match=re.search(r'data-analysis-smoke="([^"]*)"',proc.stdout.decode("utf-8"));assert match,"UI checks did not finish"
            r=json.loads(html.unescape(match.group(1)))
            assert r["widthOK"] and r["width"]==width and r["locale"]==language and not r["errors"],r
            assert r["detailsClosed"] and r["historyClosed"] and r["planDetailsClosed"],r
            if kind in ("working","receiving","chords","cancelling","cancel-pending","checking"):
                assert r["progressVisible"] and r["indicatorValue"] is None and "%" not in r["phase"]+r["hint"],r
                assert not r["planVisible"],r
            if kind=="working": assert r["phase"]=="Generating music" and r["cancelVisible"] and r["cancelEnabled"] and r["posts"]==[{"path":"/api/cancel","body":{}}],r
            if kind=="receiving": assert r["phase"]=="Receiving the result",r
            if kind=="chords": assert r["phase"]=="Detecting chords",r
            if kind=="cancelling": assert r["phase"]=="Stopping the task" and "confirm" in r["hint"],r
            if kind=="cancel-pending":
                assert r["phase"]==("Stopping the task" if language=="en" else "Stopping the task"),r
                assert ("confirm" in r["hint"] if language=="en" else "\u786e\u8ba4\u505c\u6b62\u72b6\u6001" in r["hint"]),r
                assert not r["cancelEnabled"] and not r["pauseEnabled"] and not r["resultVisible"] and not r["applyEnabled"] and not r["posts"],r
            if kind=="checking":
                assert r["phase"]==("Preparing the selected result" if language=="en" else "Preparing the selected result"),r
                assert not r["resultVisible"] and not r["applyEnabled"] and not r["posts"],r
            if kind=="idle": assert r["draftPreserved"] and r["settingsAccessible"] and r["focusable"] and not r["progressVisible"],r
            if kind=="ready": assert r["planVisible"] and r["applyEnabled"] and r["previewVisible"] and not r["progressVisible"] and not r["choicesVisible"],r
            if kind=="done": assert r["resultVisible"] and r["undoVisible"] and r["undoEnabled"] and r["undoResultVisible"] and r["posts"]==[{"path":"/api/undo","body":{}}],r
            if kind=="done-view": assert r["resultVisible"] and r["undoVisible"] and r["undoEnabled"],r
            if kind=="apply": assert r["appliedResult"] and r["posts"]==[{"path":"/api/apply","body":{"plan_id":"synthetic-plan"}}],r
            if kind=="stale": assert r["staleVisible"] and not r["applyEnabled"],r
            if kind=="error": assert r["errorDetailsClosed"] and ("no API credits" in r["notice"] if language=="en" else "\u989d\u5ea6\u4e0d\u8db3" in r["notice"]),r
            if kind=="choices":
                assert r["choicesVisible"] and r["choiceDisabled"]==[False,True,True,True] and r["noImplicitApply"],r
                assert r["choiceNames"][1]=="ACE-Step",r
                assert "YuE2" in r["chosenReview"] and r["posts"]==[{"path":"/api/generation/select","body":{"result_id":"earlier-yue","scope":"selection"}}],r
            if kind in ("single-error","choices-stale"):
                assert r["choicesVisible"] and r["choiceDisabled"]==([False] if kind=="single-error" else [False,False,True,True]),r
                assert r["noImplicitApply"] and "YuE2" in r["chosenReview"] and r["posts"]==[{"path":"/api/generation/select","body":{"result_id":"earlier-yue","scope":"selection"}}],r
            if kind=="choices-busy": assert r["choicesVisible"] and all(r["choiceDisabled"]) and not r["posts"],r
            reports.append({"label":label,**r});print(label,"PASS",flush=True)
        finally: server.shutdown();server.server_close();thread.join(2)
    (OUTPUT/"results.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()
