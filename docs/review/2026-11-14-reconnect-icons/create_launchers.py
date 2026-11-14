from pathlib import Path
import hashlib, json

root = Path('E:/MusicAgent&DAW')
launcher = root / 'Start E-musician 0.13.3.cmd'
body = '''@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'C:/Python314/python.exe' -ArgumentList '-X utf8 scripts/dev_reconnect_icons.py run' -WorkingDirectory 'E:/MusicAgent&DAW/worktrees/audio-analysis' -WindowStyle Hidden"
'''
workspace = root / 'E-musician-0.13.3.code-workspace'
previous = (root / 'E-musician-0.13.2.code-workspace').read_text(encoding='utf-8-sig')
updated = previous.replace('0.13.2', '0.13.3').replace('dev_stability.py', 'dev_reconnect_icons.py').replace('bin-0.13.3-final', 'bin-0.13.3')
for path, text in [(launcher, body), (workspace, updated)]:
    if path.exists():
        assert path.read_text(encoding='utf-8-sig') == text, 'Existing user entry differs: ' + str(path)
    else:
        path.write_text(text, encoding='utf-8')
report = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [launcher, workspace]}
Path('docs/review/2026-11-14-reconnect-icons/LAUNCHERS.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
