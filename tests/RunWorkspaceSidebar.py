"""Run the actual embedded WebView/helper against an offline synthetic project."""
from pathlib import Path
import json
import subprocess
import sys
import uuid

exe, root=map(Path,sys.argv[1:3]);root.mkdir(parents=True,exist_ok=True)
directory=root/uuid.uuid4().hex[:12]
result=subprocess.run([str(exe),'--agent-sidebar-smoke',str(directory.resolve()),'--offline'],timeout=180)
if result.returncode:raise RuntimeError(f'Embedded sidebar smoke returned {result.returncode}: {directory}')
report=json.loads((directory/'agent-sidebar-report.json').read_text(encoding='utf-8-sig'))
if report.get('status')!='passed':raise RuntimeError(report)
(root/'latest.json').write_text(json.dumps({'directory':str(directory),'report':report},indent=2),encoding='utf-8')
print(f'Native embedded WebView/helper smoke passed: {directory}; physical IME/mouse/audio not tested')
