"""Explicit cloud-only activation of a hash-verified immutable compute release."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import time
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')


def atomic(path, value):
    temp = path.with_name(path.name + '.new')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def active(database):
    if not database.exists():
        return 0
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True, timeout=2) as db:
        return db.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted')").fetchone()[0]


def stop_service(pid_file, expected_script, database, report):
    if not pid_file.is_file():
        return
    pid = int(pid_file.read_text())
    proc = Path('/proc') / str(pid)
    if not proc.is_dir():
        return
    command = (proc / 'cmdline').read_bytes().split(b'\0')
    if str(expected_script).encode() not in command:
        raise RuntimeError('Service PID does not belong to the expected deployment; left untouched')
    if active(database):
        raise RuntimeError('Cloud service has active tasks; migration postponed without cancellation')
    # Freeze only this identified idle service before the second queue check.
    # Existing model/task processes are never enumerated and broadly killed.
    os.kill(pid, signal.SIGSTOP)
    try:
        if active(database):
            raise RuntimeError('A task arrived before migration; service retained')
        os.kill(pid, signal.SIGTERM)
    finally:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
    for _ in range(100):
        try:
            exited = (proc / 'stat').read_text().split()[2] == 'Z'
        except (FileNotFoundError, ProcessLookupError):
            exited = True
        if exited:
            report.setdefault('stopped_owned_services', []).append(pid)
            return
        time.sleep(.1)
    raise RuntimeError('Owned idle service has not exited; no replacement started')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    release = args.release.resolve()
    base = ROOT / 'deployments/compute'
    if release.parent != base or not release.name.isalnum():
        raise ValueError('Invalid compute release directory')
    manifest = json.loads((release / 'SHA256.json').read_text())
    for relative, sha in manifest['files'].items():
        path = release / relative
        if not path.resolve().is_relative_to(release) or path.is_symlink() or digest(path) != sha:
            raise ValueError('Release source hash mismatch')
    # These previously verified adapters are reused, not silently replaced.
    for relative, sha in manifest['dependencies'].items():
        path = ROOT / relative
        if not path.resolve().is_relative_to(ROOT) or digest(path) != sha:
            raise ValueError('Pinned deployed adapter differs: ' + relative)
    state = ROOT / 'state'; state.mkdir(exist_ok=True)
    report = {'release': str(release), 'files_verified': manifest['files'], 'dependencies_verified': manifest['dependencies'],
        'started_unix': time.time(), 'status': 'starting', 'model_files_changed': False}
    receipt = release / 'activation.json'
    atomic(receipt, report)
    try:
        with (state / 'gateway-start.lock').open('a') as lock, (state / 'compute-start.lock').open('a') as other:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stop_service(state / 'gateway.pid', ROOT / 'tools/gateway.py', state / 'generation.sqlite3', report)
            stop_service(state / 'compute.pid', ROOT / 'tools/compute/server.py', state / 'compute.sqlite3', report)
            for name, target in (('compute', release / 'compute'), ('compute_start.py', release / 'compute/start.py')):
                destination = ROOT / 'tools' / name
                if destination.exists() or destination.is_symlink():
                    if not destination.is_symlink() or not destination.resolve().is_relative_to(base):
                        raise RuntimeError('Refusing to replace an unmanaged compute path')
                    report.setdefault('previous_links', {})[name] = str(destination.resolve())
                temp = destination.with_name(destination.name + '.activate')
                if temp.exists() or temp.is_symlink():
                    raise RuntimeError('A prior activation staging link exists')
                temp.symlink_to(target, target_is_directory=target.is_dir())
                os.replace(temp, destination)
            atomic(state / 'compute-migration-complete.json', {'release': str(release), 'activated_unix': time.time()})
        # Starter has its own interprocess lock. Inference is not performed here.
        subprocess.run(['/root/miniconda3/bin/python', str(ROOT / 'tools/compute_start.py')], check=True)
        with urllib.request.urlopen('http://127.0.0.1:18082/capabilities', timeout=10) as response:
            capabilities = json.load(response)
        if capabilities.get('protocol_version') != 2 or not all(p['available'] for p in capabilities['providers']):
            raise RuntimeError('Not all intended model adapters are ready')
        report.update(status='ready', capabilities=capabilities, inference_performed=False)
    except BaseException as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc)[:500])
        raise
    finally:
        report['finished_unix'] = time.time()
        atomic(receipt, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
