"""Inspect an existing clone and start only its already-pinned compute service.

Uses existing SSH key authentication; never accepts or logs passwords, uploads
models, changes model environments, or cancels existing cloud tasks.
Run via dev_reconnect.py command to retain the operational record.
"""
import argparse
import json
from pathlib import Path
import subprocess

REMOTE = r'''
from datetime import datetime, timezone
import hashlib, json, os, shutil, sqlite3, subprocess, sys, urllib.request
from pathlib import Path
root = Path('/root/autodl-tmp/emusician')
report = {'checked_utc': datetime.now(timezone.utc).isoformat(), 'status': 'checking',
          'model_upload_performed': False, 'inference_performed': False}
try:
    release = (root / 'tools/compute').resolve().parent
    assert release.parent == root / 'deployments/compute'
    assert release.name == 'ed7d6a920487a651c988', 'Unexpected compute release'
    manifest = json.loads((release / 'SHA256.json').read_text())
    for rel, expected in manifest['files'].items():
        assert hashlib.sha256((release / rel).read_bytes()).hexdigest() == expected, rel
    for rel, expected in manifest['dependencies'].items():
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == expected, rel
    report['release'] = release.name
    report['release_files_verified'] = True
    report['environments'] = {}
    for name in ('ace','chordmini','mir-torch','mir-transcription','muscriptor','scnet','sheetsage2','transkun','yue2'):
        interpreter = root / 'envs' / name / 'bin/python'
        result = subprocess.run([str(interpreter), '-c', 'import sys; print(sys.version.split()[0])'],
                                capture_output=True, text=True, timeout=15, check=True)
        report['environments'][name] = {'interpreter': str(interpreter), 'python': result.stdout.strip()}
    report['databases'] = {}
    for name in ('compute.sqlite3', 'generation.sqlite3'):
        database = root / 'state' / name
        with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True, timeout=3) as conn:
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted')").fetchone()[0]
        assert integrity == 'ok', name
        assert active == 0, 'Existing active tasks require review; not starting another service'
        report['databases'][name] = {'integrity': integrity, 'active_jobs': active}
    report['ffmpeg'] = shutil.which('ffmpeg')
    assert report['ffmpeg'], 'ffmpeg missing'
    report['gpu'] = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],
                                   capture_output=True,text=True,timeout=15,check=True).stdout.strip()
    if '--start' in sys.argv:
        result = subprocess.run(['/root/miniconda3/bin/python',str(root/'tools/compute_start.py')],
                                capture_output=True,text=True,timeout=25,check=True)
        report['start'] = json.loads(result.stdout.strip().splitlines()[-1])
    for name in ('health','capabilities'):
        with urllib.request.urlopen('http://127.0.0.1:18082/' + name,timeout=5) as response:
            report[name] = json.load(response)
    assert report['health']['service'] == 'emusician-compute'
    assert report['capabilities']['protocol_version'] == 2
    providers = report['capabilities']['providers']
    assert len(providers) == 7 and all(p['available'] for p in providers)
    report['status'] = 'ready'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = type(exc).__name__ + ': ' + str(exc)
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if report['status'] == 'ready' else 1)
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-port', type=int, required=True)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.ssh_port <= 65535:
        parser.error('Invalid SSH port')
    command = ['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
               '-p',str(args.ssh_port),'emusician-autodl','/root/miniconda3/bin/python -' + (' --start' if args.start else '')]
    result = subprocess.run(command,input=REMOTE,text=True,encoding='utf-8',capture_output=True,timeout=150)
    if result.stderr:
        print(result.stderr)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return result.returncode

if __name__ == '__main__':
    raise SystemExit(main())
