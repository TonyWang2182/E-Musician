"""Render real Agent UI against synthetic hybrid candidates, no desktop or LLM."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import html
import json
import re
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from music_agent import analysis as a, generation as g
from music_agent.selection import freeze_scope
from test_music_agent_analysis import context, result
from GenerationAgentWebSmoke import fixture as generation_fixture

OUTPUT = ROOT / "build/hybrid-agent-web"
WEB = ROOT / "scripts/music_agent/web"
HARNESS = r"""<script>
window.__smokeErrors=[];window.addEventListener('error',e=>window.__smokeErrors.push(e.message));
let attempts=0;const checker=setInterval(()=>{
 const plan=document.getElementById('plan');if((!plan||plan.hidden)&&++attempts<40)return;
 clearInterval(checker);plan.scrollIntoView({block:'start'});
 document.body.setAttribute('data-analysis-smoke',JSON.stringify({
  visible:!plan.hidden,changes:document.getElementById('changes').textContent,
  preview:document.getElementById('analysis-preview-items').textContent,
  widthOK:document.documentElement.scrollWidth<=innerWidth,
  language:document.documentElement.lang,errors:window.__smokeErrors}));
},100);</script>"""


def fixture(kind):
    state = generation_fixture()
    if kind == "generate":
        state["plan"]["generation"].update(model_id="yue2", execution="cloud", completion={"truncated": True, "reason": "token_budget", "timing_is_exact": False})
        return state
    ctx = context(); ctx["name"] = "Synthetic hybrid review / no model"
    raw = result(kind)
    raw.update(model_id="muscriptor" if kind == "transcribe" else "sheetsage2", execution="cloud",
               summary={"track_count": 2, "note_count": 2, "controller_count": 3,
                        "chord_count": 4 if kind == "score" else 0, "beat_count": 16 if kind == "score" else 0,
                        "annotation_count": 2 if kind == "score" else 0})
    plan = a.compile_import(a.safe_result(raw), ctx, freeze_scope(ctx), "Review synthetic candidate")
    plan["id"] = "synthetic-hybrid"
    state.update(snapshot=ctx, plan=plan)
    return state


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            data = json.dumps(self.server.fixture, ensure_ascii=False).encode(); mime = "application/json"
        elif path in ("/", "/app.js", "/style.css", "/i18n.js"):
            data = (WEB / ("index.html" if path == "/" else path[1:])).read_bytes()
            if path == "/": data = data.replace(b"</body>", HARNESS.encode() + b"</body>")
            mime = "text/html" if path == "/" else "text/css" if path.endswith("css") else "text/javascript"
        else: self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    browser = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    reports = []
    for kind, width, language in (("transcribe", 340, "en"), ("score", 400, "zh-CN"), ("score", 340, "en"), ("generate", 340, "en")):
        label = f"hybrid-{kind}-{width}-{language}"
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler); server.fixture = fixture(kind)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/?embedded=1&lang={language}#token=synthetic-ui-test"
            process = subprocess.run(["node", str(ROOT/"tests/analysis_agent_web_capture.mjs"), browser,
                str(OUTPUT/(uuid.uuid4().hex+"-profile")), url, str(OUTPUT/label), str(width), "850"],
                capture_output=True, timeout=45)
            (OUTPUT/(label+".stderr.log")).write_bytes(process.stderr)
            assert process.returncode == 0, process.stderr.decode(errors="replace")
            match = re.search(r'data-analysis-smoke="([^"]*)"', process.stdout.decode("utf-8")); assert match
            checks = json.loads(html.unescape(match.group(1)))
            assert checks["visible"] and checks["widthOK"] and not checks["errors"] and checks["language"] == language, checks
            assert "undefined" not in checks["preview"], checks
            if kind == "generate": assert "budget" in checks["changes"] and "yue2" in checks["changes"], checks
            else:
                assert "2" in checks["changes"] and "3" in checks["changes"] and "MIDI" in checks["changes"], checks
                assert "muscriptor" in checks["changes"] or "sheetsage2" in checks["changes"], checks
                if kind == "score": assert "速度不变" in checks["changes"] or "tempo stays unchanged" in checks["changes"], checks
            reports.append({"label": label, **checks}); print(label, "PASS")
        finally: server.shutdown(); server.server_close(); thread.join(2)
    (OUTPUT/"results.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
