"""Record the post-probe guard hardening separately from the tested GPU version."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/autodl-tmp/emusician')
TOOLS = ROOT / 'tools/models/mir_upgrades'
OLD_GUARD = '6b68695bcd54d73dd7b3d0915ad99d536a9d933a6214ba23a43eaca60ee7d709'
for identifier in ('scnet', 'transkun', 'chordmini'):
    path = ROOT / 'manifests/model-library' / identifier / 'deployment.json'
    data = json.loads(path.read_text())
    data['guard_change_after_gpu_probes'] = {
        'gpu_tested_sha256': OLD_GUARD,
        'final_sha256': hashlib.sha256((TOOLS / 'guarded_probe.py').read_bytes()).hexdigest(),
        'change': 'Exceptional monitor/cleanup now TERM-then-KILL and durable terminal receipt; final diagnostic errors separate',
        'cpu_fault_tests': {'passed': 3, 'gpu_access': False,
            'record': 'docs/builds/20261106T102503.755071Z-fc91eeea5d.json'},
        'gpu_probes_repeated_after_guard_change': False,
    }
    data['artifacts'] = [item for item in data['artifacts'] if not item['path'].startswith(str(TOOLS) + '/')]
    for artifact in sorted(TOOLS.iterdir()):
        if artifact.is_file() and artifact.suffix in ('.py', '.sh'):
            data['artifacts'].append({'path': str(artifact), 'bytes': artifact.stat().st_size,
                'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()})
    path.write_text(json.dumps(data, indent=2) + '\n')
    print(identifier, data['checks'], 'final_guard_sha256', data['guard_change_after_gpu_probes']['final_sha256'])
