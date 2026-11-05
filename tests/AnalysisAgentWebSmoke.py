"""Render the real Agent page with explicitly synthetic host state in owned Edge.

No existing browser profile or user desktop is read or controlled. Run via the
development Recorder; captures and the isolated browser profile stay in build/.
"""
from __future__ import annotations
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from music_agent.analysis import capability_groups, COMMANDS, compile_import
from music_agent.selection import freeze_scope
from test_music_agent_analysis import context, result
from test_music_agent_native_effects import fake_effect_catalog, fake_instrument_catalog
from music_agent.tempo import compile_beats
from test_music_agent_tempo import candidate as beat_candidate, warp

OUTPUT = ROOT / "build" / "analysis-agent-web"
WEB = ROOT / "scripts" / "music_agent" / "web"

def fixture(ready):
    ctx = context(); ctx["name"] = "Synthetic UI fixture / no inference"
    host = {"commands": sorted(COMMANDS | {"get_snapshot", "get_selection_context", "get_clip_notes", "edit_notes", "move_clip", "duplicate_clips", "trim_clip", "get_native_effect", "set_native_effect", "get_native_instrument", "get_audio_warp", "set_audio_warp", "apply_beat_analysis"}),
            "native_effect_catalog": fake_effect_catalog(), "native_instrument_catalog": fake_instrument_catalog()}
    caps = {"providers": [{"kind": k, "available": k != "separate", "detail": "合成界面状态，未执行模型推理。"} for k in ("separate", "transcribe", "chords", "beats")]}
    plan = compile_import(result(), ctx, freeze_scope(ctx), "把候选音符导入到新的 MIDI 轨道") if ready else None
    if ready == "beats":plan=compile_beats({"result_id":"r","mode":"audio_to_project","summary":"Synthetic beat review fixture / no inference"},beat_candidate(),ctx,freeze_scope(ctx),[warp()])
    if plan: plan["id"] = "synthetic-preview"
    return {"phase": "ready" if ready else "idle", "busy": False, "snapshot": ctx,
            "provider": {"id": "kimi", "configured": True, "model": "synthetic-no-model", "base_url": "https://api.moonshot.cn/v1"},
            "providers": [], "capability_groups": capability_groups(ctx, host, caps), "analysis_jobs": [],
            "messages": [], "plan": plan, "last_result": "", "error": None, "can_undo": False,
            "control": {"connected": True, "embedded": True}, "progress": {"stage": "ready" if ready else "idle"}, "usage": {"calls": 0}}

HARNESS = r"""<script>
window.__smokeErrors=[]; window.addEventListener('error',e=>window.__smokeErrors.push(e.message));
let attempt=0; const checker=setInterval(()=>{
 const rows=[...document.querySelectorAll('.capability-row')]; if(rows.length!==10 && ++attempt<30)return;
 clearInterval(checker);
 const target=rows.find(r=>r.dataset.capability==='transcribe'); if(target)target.open=true;
 const btn=target?.querySelector('button'); if(btn&&!btn.disabled)btn.click();
 const draft=document.getElementById('prompt').value, project=document.getElementById('project-title').textContent;
 const initialLanguage=document.documentElement.lang;
 window.emusicianSetLanguage('en');
 const englishLabel=document.getElementById('submit').textContent==='Send';
 window.emusicianSetLanguage('zh-CN');
 const chineseLabel=document.getElementById('submit').textContent==='发送';
 window.emusicianSetLanguage('en');
 const localePreservesDraft=document.getElementById('prompt').value===draft;
 const localePreservesProject=document.getElementById('project-title').textContent===project;
 const restoresEnglish=document.documentElement.lang==='en'&&document.getElementById('submit').textContent==='Send';
 const rawValue='发送 <b>track</b>';
 const literalValues=window.emusicianI18n.t`轨道：${rawValue}`===`Track: ${rawValue}`;
 const newAnalysisCopy=window.emusicianI18n.t('新建 4 条音频轨并导入候选分轨').startsWith('Create 4 audio tracks')
  &&window.emusicianI18n.t('新建 6 条音频轨并导入候选分轨').startsWith('Create 6 audio tracks')
  &&window.emusicianI18n.t('添加和弦轨，可直接修正标签和时间。')==='Add a chord lane with editable labels and timing.';
 window.emusicianSetLanguage(initialLanguage);
 const offline=rows.find(r=>r.dataset.capability==='separate')?.querySelector('button');
 const preview=document.getElementById('analysis-preview'); if(preview&&!preview.hidden)preview.open=true;
 const checks={rows:rows.length,capabilitiesInitiallyCompact:!document.getElementById('capabilities').open,disabledUnavailable:!!offline?.disabled,examplePopulates:document.getElementById('prompt').value.includes('MIDI'),
 widthOK:document.documentElement.scrollWidth<=innerWidth,viewportWidth:innerWidth,errors:window.__smokeErrors,
 initialLanguage,englishLabel,chineseLabel,restoresEnglish,localePreservesDraft,localePreservesProject,literalValues,newAnalysisCopy,
 previewRows:preview&&!preview.hidden?document.querySelectorAll('#analysis-preview-items li').length:0};
 document.body.setAttribute('data-analysis-smoke',JSON.stringify(checks));
 if(preview&&!preview.hidden)document.getElementById('plan').scrollIntoView({block:'start'});
},50);
</script>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            body = json.dumps(self.server.fixture, ensure_ascii=False).encode("utf-8"); mime = "application/json"
        elif path in ("/", "/app.js", "/i18n.js", "/style.css"):
            file = WEB / ("index.html" if path == "/" else path[1:]); body = file.read_bytes()
            mime = "text/html" if path == "/" else "text/javascript" if path.endswith("js") else "text/css"
            if path == "/": body = body.replace(b"</body>", HARNESS.encode("utf-8")+b"</body>")
        else: self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type",mime+"; charset=utf-8"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

def main():
    browser = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not browser.is_file(): raise RuntimeError("Headless Edge unavailable")
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for ready, width, height, language in ((False,400,800,"en"),(True,400,800,"en"),(False,1000,800,"en"),(False,400,800,"zh-CN"),("beats",400,800,"en")):
        label = ("beats" if ready == "beats" else "ready" if ready else "empty") + f"-{width}x{height}" + ("-zh" if language=="zh-CN" else "")
        server = ThreadingHTTPServer(("127.0.0.1",0),Handler); server.fixture=fixture(ready)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/?embedded=1&lang={language}#token=synthetic-ui-test"
            screenshot=OUTPUT/f"{label}.png"
            import uuid
            args=['node',str(ROOT/'tests'/'analysis_agent_web_capture.mjs'),str(browser),str(OUTPUT/(label+'-'+uuid.uuid4().hex+'-profile')),
                  url,str(OUTPUT/label),str(width),str(height)]
            response=subprocess.run(args,capture_output=True,timeout=45)
            output=response.stdout.decode('utf-8',errors='replace')
            (OUTPUT/f"{label}.html").write_text(output,encoding='utf-8')
            (OUTPUT/f"{label}.stderr.log").write_bytes(response.stderr)
            if response.returncode: raise RuntimeError(f"Edge exited {response.returncode}")
            import html
            match=re.search(r'data-analysis-smoke="([^"]*)"',output)
            if not match: raise RuntimeError(f"No completed UI check in {label}")
            checks=json.loads(html.unescape(match.group(1)))
            assert checks['rows']==10 and checks['capabilitiesInitiallyCompact'] and checks['disabledUnavailable'] and checks['examplePopulates'] and checks['widthOK'] and not checks['errors'],checks
            assert checks['viewportWidth']==width,checks
            assert checks['initialLanguage']==language and all(checks[key] for key in ('englishLabel','chineseLabel','restoresEnglish','localePreservesDraft','localePreservesProject','literalValues','newAnalysisCopy')),checks
            assert checks['previewRows']==(20 if ready == "beats" else 2 if ready else 0),checks
            if ready == "beats":
                assert 'Keep the current project tempo and meter.' in output
                assert 'Confirmation applies tempo and alignment without creating a track.' in output
            assert screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
            print(label,json.dumps(checks),str(screenshot))
        finally: server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__': main()
