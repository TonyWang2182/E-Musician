"""Fresh native/offline workspace process; never accept a forwarded GUI launch."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

exe, root = map(Path, sys.argv[1:3])
directory = root / uuid.uuid4().hex[:12]
root.mkdir(parents=True, exist_ok=True)
result = subprocess.run([str(exe), '--workspace-smoke', str(directory.resolve()), '--offline'], timeout=135)
if result.returncode:
    failure = directory / 'failure.txt'
    if failure.exists(): print(failure.read_text(encoding='utf-8'))
    raise RuntimeError(f'Workspace smoke returned {result.returncode}: {directory}')
reports = {}
for name in ('workspace-engine-report.json', 'workspace-brand-report.json'):
    data = json.loads((directory / name).read_text(encoding='utf-8-sig'))
    if data.get('status') != 'passed': raise RuntimeError(f'{name}: {data}')
    reports[name] = data
(root / 'latest.json').write_text(json.dumps({'directory': str(directory), 'reports': reports}, indent=2), encoding='utf-8')
print(f'Native brand, track colour, gesture and workspace checks passed: {directory}')
