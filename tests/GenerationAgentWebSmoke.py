"""Real sidebar HTML with synthetic generation result; owned headless browser.

No music inference or user desktop. Tests the manual Preview/Stop HTTP flow,
new-track review, no-selection hint and responsive bilingual rendering.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import re
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
from music_agent import generation as g
from music_agent.selection import freeze_scope
from test_music_agent_generation import context, candidate

OUTPUT = ROOT/"build/generation-agent-web"
WEB = ROOT/"scripts/music_agent/web"


def fixture():
    ctx = context(); ctx["name"] = "Synthetic generation review / no inference"
    plan = g.compile_import(candidate(), ctx, freeze_scope(ctx), "Add the generated piano to a new track."); plan["id"] = "synthetic-plan"
    return {"phase": "ready", "busy": False, "snapshot": ctx, "plan": plan,
            "provider": {"id": "kimi", "configured": True, "model": "synthetic-no-LLM", "base_url": "https://example.invalid"},
            "providers": [], "messages": [], "usage": {"calls": 0}, "last_result": "", "error": None,
            "capability_groups": [g.capability_group({"commands": list(g.COMMANDS)}, {"available": True})],
            "control": {"connected": True, "embedded": True}, "progress": {"stage": "ready"}}


HARNESS = "<script>\nwindow.__smokeErrors=[]; window.addEventListener('error',e=>window.__smokeErrors.push(e.message));\nlet attempt=0; const checker=setInterval(async()=>{\n const preview=document.getElementById('generation-preview');\n if((!preview||preview.hidden)&&++attempt<40)return;\n clearInterval(checker);\n const play=document.getElementById('generation-play'), stop=document.getElementById('generation-stop');\n const scope=document.getElementById('scope-hint').textContent;\n const language=document.documentElement.lang;\n const checks={previewVisible:!preview.hidden,playEnabled:!play.disabled,stopEnabled:!stop.disabled,\n  changes:document.getElementById('changes').textContent,noSelectionHint:scope.includes('generate')||scope.includes('\u751f\u6210'),\n  widthOK:document.documentElement.scrollWidth<=innerWidth,viewportWidth:innerWidth,language,errors:window.__smokeErrors};\n play.click(); await new Promise(r=>setTimeout(r,250));\n for(let i=0;i<40;i++) {\n  const value=document.getElementById('generation-preview-status').textContent;\n  if(value.includes('unavailable')||value.includes('\u4e0d\u53ef\u7528'))break;\n  await new Promise(r=>setTimeout(r,100));\n }\n checks.previewFailure=document.getElementById('generation-preview-status').textContent;\n stop.click(); await new Promise(r=>setTimeout(r,400));\n const events=await (await fetch('/test-events')).json(); checks.previewPosts=events;\n document.getElementById('plan').scrollIntoView({block:'start'});\n document.body.setAttribute('data-analysis-smoke',JSON.stringify(checks));\n},100);\n</script>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send(self, body, mime="application/json"):
        self.send_response(200); self.send_header("Content-Type", mime+"; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            if getattr(self.server, "pending_preview", False):
                self.server.fixture["generation_preview"] = {"status": "unavailable", "detail": "No audio output is active. Open audio settings before previewing a stem."}
                self.server.pending_preview = False
            self.send(json.dumps(self.server.fixture, ensure_ascii=False).encode()); return
        if path == "/test-events": self.send(json.dumps(self.server.events).encode()); return
        if path not in ("/", "/app.js", "/style.css", "/i18n.js"): self.send_error(404); return
        content = (WEB/("index.html" if path == "/" else path[1:])).read_bytes()
        if path == "/": content = content.replace(b"</body>", HARNESS.encode()+b"</body>")
        self.send(content, "text/html" if path == "/" else "text/css" if path.endswith(".css") else "text/javascript")
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.events.append({"path": self.path, "body": body})
        if body.get("plan_id"):
            self.server.fixture["generation_preview"] = {"status": "preparing"}; self.server.pending_preview = True
        if body.get("stop"): self.server.fixture["generation_preview"] = {"status": "stopped"}
        self.send(json.dumps(self.server.fixture, ensure_ascii=False).encode())


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    browser = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    assert browser.is_file()
    reports = []
    for width, height, language in ((340, 800, "en"), (400, 800, "zh-CN"), (1000, 800, "en")):
        label = f"generation-{width}x{height}-{language}"
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler); server.fixture = fixture(); server.events = []
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/?embedded=1&lang={language}#token=synthetic-ui-test"
            language = "en"
            response = subprocess.run(["node", str(ROOT/"tests/analysis_agent_web_capture.mjs"), str(browser), str(OUTPUT/(uuid.uuid4().hex+"-profile")), url, str(OUTPUT/label), str(width), str(height)], capture_output=True, timeout=45)
            (OUTPUT/(label+".stderr.log")).write_bytes(response.stderr)
            assert response.returncode == 0, response.stderr.decode(errors="replace")
            dom = response.stdout.decode("utf-8"); match = re.search(r'data-analysis-smoke="([^"]*)"', dom)
            assert match, "UI checks did not finish"
            checks = json.loads(html.unescape(match.group(1)))
            assert all(checks[k] for k in ("previewVisible", "playEnabled", "stopEnabled", "widthOK", "noSelectionHint")), checks
            assert checks["viewportWidth"] == width and checks["language"] == language and not checks["errors"], checks
            assert checks["previewPosts"] == [{"path": "/api/generation/preview", "body": {"plan_id": "synthetic-plan"}}, {"path": "/api/generation/preview", "body": {"stop": True}}], checks
            assert ("new audio track" in checks["changes"] if language == "en" else "\u65b0\u5efa1\u6761\u97f3\u9891\u8f68" in checks["changes"]), checks
            assert ("Preview unavailable" in checks["previewFailure"] if language == "en" else "Preview unavailable" in checks["previewFailure"]), checks
            assert "audio output" in checks["previewFailure"], checks
            reports.append({"label": label, **checks}); print(label, "PASS")
        finally: server.shutdown(); server.server_close(); thread.join(2)
    (OUTPUT/"results.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
