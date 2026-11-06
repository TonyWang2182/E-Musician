"""Explicit versioned service activation; no model downloads, no user project access."""
from pathlib import Path
import hashlib
import json
import sys
from dev import Recorder, configure_console_output

ROOT = Path(__file__).resolve().parents[1]
CLOUD = '/root/autodl-tmp/emusician'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    configure_console_output()
    folder = ROOT / 'scripts/cloud/compute'
    files = {'compute/' + p.name: sha(p) for p in sorted(folder.glob('*.py'))}
    files['install_compute.py'] = sha(ROOT / 'scripts/cloud/install_compute.py')
    dependencies = {'tools/ace_worker.py': sha(ROOT / 'scripts/cloud/ace_worker.py'),
        'tools/models/mir_upgrades/runtime.py': sha(ROOT / 'scripts/cloud/models/mir_upgrades/runtime.py')}
    identity = hashlib.sha256(json.dumps({'files': files, 'dependencies': dependencies}, sort_keys=True).encode()).hexdigest()[:20]
    stage = ROOT / 'build/compute-deployment' / identity
    stage.mkdir(parents=True, exist_ok=True)
    manifest = stage / 'SHA256.json'
    manifest.write_text(json.dumps({'files': files, 'dependencies': dependencies}, indent=2), encoding='utf-8')
    remote = CLOUD + '/deployments/compute/' + identity
    record = Recorder('compute-service-deployment', 'Linux/stdlib protocol2', 'Explicit idle-service migration; versioned scripts and hashes; no inference, no model/environment changes')
    record.execute(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'emusician-autodl', 'mkdir -p ' + remote + '/compute'])
    record.execute(['scp', '-q', '-o', 'BatchMode=yes', *[str(p) for p in sorted(folder.glob('*.py'))], 'emusician-autodl:' + remote + '/compute/'])
    record.execute(['scp', '-q', '-o', 'BatchMode=yes', str(manifest), str(ROOT / 'scripts/cloud/install_compute.py'), 'emusician-autodl:' + remote + '/'])
    result = record.execute(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'emusician-autodl',
        '/root/miniconda3/bin/python ' + remote + '/install_compute.py --release ' + remote])
    result_path = ROOT / 'docs/review/2026-11-07-hybrid-pipeline/DEPLOYMENT.json'
    lines = result.output.strip().splitlines()
    report = json.loads(lines[-1])
    result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Deployment receipt: ' + str(result_path))


if __name__ == '__main__':
    main()
