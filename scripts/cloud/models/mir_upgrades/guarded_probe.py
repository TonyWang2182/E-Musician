"""One root-authorized, monitored GPU probe; yields immediately to existing ACE work."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
import wave

ROOT = Path('/root/autodl-tmp/emusician')
FIXTURE_SOURCE = ROOT / 'jobs/generation/gateway-20261106T075755Z-120s/audio.wav'


def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    output = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], timeout=5, text=True)
    return {'active_ace_jobs': active, 'free_gpu_mib': int(output.strip().splitlines()[0])}


def stop_owned(process, grace=5):
    """Only the process group created by this guard; bounded TERM then KILL."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def monitor(process, receipt, started, *, state_reader=state, grace=5, interval=0.5):
    try:
        while process.poll() is None:
            now = state_reader()
            receipt['minimum_free_gpu_mib'] = min(receipt['minimum_free_gpu_mib'], now['free_gpu_mib'])
            if now['active_ace_jobs'] or now['free_gpu_mib'] < 1024 or time.monotonic() - started > 180:
                receipt.update(status='interrupted', interrupt_reason='ACE activity, VRAM floor, or 180-second deadline', observed=now)
                break
            time.sleep(interval)
    except BaseException as error:
        receipt.update(status='interrupted', interrupt_reason='health-monitor failure or caller interruption',
                       monitor_error=f'{type(error).__name__}: {error}'[:1000])
    finally:
        if process.poll() is None:
            stop_owned(process, grace=grace)
        receipt['exit_code'] = process.returncode


def finish_receipt(path, receipt, *, state_reader=state):
    # Diagnostic failure must not erase the terminal process/inference receipt.
    try:
        receipt['after'] = state_reader()
        receipt['after_health_check_passed'] = True
    except BaseException as error:
        receipt['after_health_check_passed'] = False
        receipt['after_health_error'] = f'{type(error).__name__}: {error}'[:1000]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id', choices=('scnet', 'transkun', 'chordmini'))
    args = parser.parse_args()
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    output = ROOT / 'results/model-library' / args.id / ('probe-' + stamp)
    logs = ROOT / 'logs/model-library'
    logs.mkdir(parents=True, exist_ok=True)
    logpath = logs / f'{args.id}-{stamp}-gpu.log'
    fixture = ROOT / 'results/model-library/fixtures/ace-piano-trio-first8s.wav'
    receipt = {'id': args.id, 'started_utc': stamp, 'input': str(fixture),
               'input_origin': str(FIXTURE_SOURCE), 'input_duration_seconds': 8,
               'status': 'running', 'log': str(logpath), 'output': str(output),
               'quality_evaluation': False, 'daw_connected': False,
               'guard_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    command = [str(ROOT / 'envs' / args.id / 'bin/python'), str(ROOT / 'tools/models/mir_upgrades/infer.py'),
               args.id, '--input', str(fixture), '--output', str(output), '--device', 'cuda']
    started = time.monotonic()
    path = ROOT / 'manifests/model-library' / args.id / f'gpu-probe-{stamp}.json'
    process = None
    lock = None
    try:
        lock = (ROOT / 'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = state()
        receipt.update(before=before, minimum_free_gpu_mib=before['free_gpu_mib'])
        if before['active_ace_jobs'] or before['free_gpu_mib'] < 8192:
            raise RuntimeError('GPU probe admission denied: ACE active or less than 8 GiB free')
        fixture.parent.mkdir(parents=True, exist_ok=True)
        if not fixture.exists():
            with wave.open(str(FIXTURE_SOURCE), 'rb') as source, wave.open(str(fixture), 'wb') as target:
                target.setparams(source.getparams())
                target.writeframes(source.readframes(source.getframerate() * 8))
        with fixture.open('rb') as stream:
            receipt['input_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        with logpath.open('wb') as log:
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MPLBACKEND='Agg')
            env.pop('CUDA_VISIBLE_DEVICES', None)
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            monitor(process, receipt, started)
        if receipt['status'] == 'running':
            receipt['status'] = 'passed' if process.returncode == 0 and (output / 'result.json').exists() else 'failed'
        if receipt['status'] == 'passed':
            receipt['result'] = json.loads((output / 'result.json').read_text())
    except BaseException as error:
        receipt.update(status='interrupted', interrupt_reason=f'{type(error).__name__}: {error}'[:1000])
    finally:
        if process is not None and process.poll() is None:
            try:
                stop_owned(process)
            except BaseException as error:
                receipt['cleanup_error'] = f'{type(error).__name__}: {error}'[:1000]
        receipt['wall_seconds'] = time.monotonic() - started
        finish_receipt(path, receipt)
        if lock is not None:
            lock.close()
    print(json.dumps(receipt), flush=True)
    if receipt['status'] != 'passed' or not receipt['after_health_check_passed']:
        if logpath.exists():
            print(logpath.read_text(errors='replace')[-8000:], flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
