"""Serialized whole-song evaluation guard; stops only its owned process group."""
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
import sys
import time
import uuid

ROOT = Path('/root/autodl-tmp/emusician')
GIB = 1024**3


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8'); temp.replace(path)


def health():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True, timeout=5)
    memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')}
    available = memory['MemAvailable']
    cgroup = None
    for maximum, current in (('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory.current'),
                             ('/sys/fs/cgroup/memory/memory.limit_in_bytes', '/sys/fs/cgroup/memory/memory.usage_in_bytes')):
        if Path(maximum).is_file() and Path(current).is_file():
            limit = Path(maximum).read_text().strip()
            if limit.isdecimal() and 0 < int(limit) < 2**60:
                used = int(Path(current).read_text())
                cgroup = {'limit_bytes': int(limit), 'current_bytes': used}
                available = min(available, max(0, int(limit)-used))
                break
    return {'active_ace_jobs': active, 'free_gpu_mib': int(gpu.strip().splitlines()[0]),
        'available_host_bytes': available, 'proc_memavailable_bytes': memory['MemAvailable'],
        'cgroup_memory': cgroup, 'free_disk_bytes': shutil.disk_usage(ROOT).free}


def stop_owned(process, grace=5):
    if process is None or process.poll() is not None:
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


def finish(path, report, process, started, reader=health):
    try:
        stop_owned(process)
    except BaseException as error:
        report.update(status='failed', cleanup_error=type(error).__name__+': '+str(error))
    report.update(exit_code=None if process is None else process.returncode,
        wall_seconds=time.monotonic()-started)
    try:
        report['after'] = reader()
    except BaseException as error:
        report['after_diagnostic_error'] = type(error).__name__+': '+str(error)
    try:
        write(path, report)
    except BaseException as error:
        report['receipt_write_error'] = type(error).__name__+': '+str(error)
        print(json.dumps(report), flush=True)
        raise
    print(json.dumps(report), flush=True)


def run(args):
    if os.name != 'posix' or not ROOT.is_dir() or not args.approved_slot:
        raise RuntimeError('Explicit cloud GPU slot required')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Owned evaluation interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+uuid.uuid4().hex[:8]
    output = ROOT/'results/evaluations/real_audio_20261106'/(args.model+'-'+stamp)
    report = {'model': args.model, 'status': 'preflight', 'started_utc': stamp,
        'input': str(args.input), 'expected_input_sha256': args.sha256, 'output': str(output),
        'deadline_seconds': 1800, 'guard_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'daw_connected': False, 'audio_downloaded_to_e': False, 'quality_verified': False,
        'attempts': 1, 'policy': {'admission_gpu_mib': 8192, 'stop_gpu_mib': 1024,
            'stop_available_host_bytes': 2*GIB, 'max_owned_worker_rss_bytes': 12*GIB}}
    started = time.monotonic(); lock = None; process = None
    try:
        output.mkdir(parents=True, exist_ok=False)
        lock = (ROOT/'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = health(); report['before'] = before
        if before['active_ace_jobs'] or before['free_gpu_mib'] < 8192 or before['free_disk_bytes'] < 50_000_000_000:
            raise RuntimeError('Admission denied: active ACE, GPU reserve, or disk reserve')
        command = [str(ROOT/'envs'/args.model/'bin/python'), str(Path(__file__).with_name('whole_file.py')),
            args.model, '--input', str(args.input), '--sha256', args.sha256]
        env = os.environ.copy(); env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2',
            OPENBLAS_NUM_THREADS='2', HF_HUB_OFFLINE='1', MPLBACKEND='Agg')
        inspection = subprocess.run(command+['--inspect'], capture_output=True, text=True, env=env, timeout=45)
        (output/'preflight.log').write_text(inspection.stdout+inspection.stderr, encoding='utf-8')
        if inspection.returncode != 0:
            raise RuntimeError('Whole-file preflight failed; see preflight.log')
        metadata = json.loads(inspection.stdout)
        report['input_metadata'] = metadata
        if before['available_host_bytes'] < metadata['required_available_host_bytes']:
            raise RuntimeError('Whole-file CPU-buffer memory budget is unavailable')
        write(output/'input.json', metadata)
        report.update(status='running', minimum_free_gpu_mib=before['free_gpu_mib'],
            minimum_available_host_bytes=before['available_host_bytes'], peak_sampled_worker_rss_bytes=0)
        write(output/'attempt.json', report)
        env.pop('CUDA_VISIBLE_DEVICES', None)
        with (output/'worker.log').open('wb') as log:
            process = subprocess.Popen(command+['--output', str(output/'data')], env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            last_print = 0
            while process.poll() is None:
                current = health()
                try:
                    text = Path(f'/proc/{process.pid}/status').read_text()
                    rss = next(int(line.split()[1])*1024 for line in text.splitlines() if line.startswith('VmRSS:'))
                except (FileNotFoundError, StopIteration):
                    rss = 0
                report['peak_sampled_worker_rss_bytes'] = max(report['peak_sampled_worker_rss_bytes'], rss)
                report['minimum_free_gpu_mib'] = min(report['minimum_free_gpu_mib'], current['free_gpu_mib'])
                report['minimum_available_host_bytes'] = min(report['minimum_available_host_bytes'], current['available_host_bytes'])
                elapsed = time.monotonic()-started
                if current['active_ace_jobs'] or current['free_gpu_mib'] < 1024 or current['available_host_bytes'] < 2*GIB or rss > 12*GIB or elapsed > 1800:
                    report.update(status='interrupted', reason='ACE activity, resource reserve, or deadline', observed=current)
                    break
                if elapsed-last_print >= 15:
                    print(json.dumps({'model': args.model, 'elapsed_seconds': elapsed, 'rss_bytes': rss,
                        'free_gpu_mib': current['free_gpu_mib']}), flush=True); last_print = elapsed
                time.sleep(.5)
        if report['status'] == 'running':
            if process.returncode != 0:
                raise RuntimeError('Worker failed; see worker.log')
            result = json.loads((output/'data/result.json').read_text())
            if result.get('status') != 'passed' or result['input']['sha256'] != args.sha256:
                raise RuntimeError('Worker result contract mismatch')
            report.update(status='passed', result=result)
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__+': '+str(error))
    finally:
        try:
            finish(output/'attempt.json', report, process, started)
        finally:
            if lock is not None:
                lock.close()
    if report['status'] != 'passed':
        log = output/'worker.log'
        if log.is_file():
            print(log.read_text(errors='replace')[-6000:], flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=('scnet', 'transkun', 'chordmini'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--approved-slot', action='store_true')
    run(parser.parse_args())
