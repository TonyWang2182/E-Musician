"""Explicit versioned service activation; no model downloads, no user project access."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from dev import Recorder, configure_console_output

ROOT = Path(__file__).resolve().parents[1]
CLOUD = '/root/autodl-tmp/emusician'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-alias', required=True, help='Your own configured OpenSSH host alias.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', args.ssh_alias):
        raise ValueError('Invalid SSH host alias')
    alias = args.ssh_alias
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
    record.execute(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15', alias, 'mkdir -p ' + remote + '/compute'])
    record.execute(['scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', *[str(p) for p in sorted(folder.glob('*.py'))], alias + ':' + remote + '/compute/'])
    record.execute(['scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', str(manifest), str(ROOT / 'scripts/cloud/install_compute.py'), alias + ':' + remote + '/'])
    result = record.execute(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15', alias,
        '/root/miniconda3/bin/python ' + remote + '/install_compute.py --release ' + remote])
    result_path = stage / 'DEPLOYMENT.json'
    lines = result.output.strip().splitlines()
    report = json.loads(lines[-1])
    result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Deployment receipt: ' + str(result_path))


if __name__ == '__main__':
    main()
