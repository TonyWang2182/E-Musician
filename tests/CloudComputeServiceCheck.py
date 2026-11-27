"""Actual cloud HTTP/restart faults with the GPU lock held: no inference allowed.

Run only in an explicitly coordinated idle-service test window. Creates its own
tiny synthetic asset/jobs, and restarts only the verified compute service PID.
"""
import argparse
import fcntl
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
import uuid
import wave

ROOT = Path('/root/autodl-tmp/emusician')
PORT = 18082
TERMINAL = {'ready', 'cancelled', 'failed', 'interrupted'}


def call(method, path, body=None):
    if isinstance(body, dict):
        body = json.dumps(body).encode('utf-8')
    connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=5)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Test response exceeded its bound')
        return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
    finally:
        connection.close()


def query_active():
    with sqlite3.connect(f'file:{ROOT}/state/compute.sqlite3?mode=ro', uri=True, timeout=2) as database:
        return database.execute("SELECT id,status FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') ORDER BY id").fetchall()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def service_pid():
    pid = int((ROOT / 'state/compute.pid').read_text())
    command = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
    check(str(ROOT / 'tools/compute/server.py').encode() in command, 'Service PID is not the expected compute script')
    return pid


def alive(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def start_service():
    process = subprocess.run(['/root/miniconda3/bin/python', str(ROOT / 'tools/compute_start.py')],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, text=True)
    check(process.returncode == 0, 'Owned compute startup failed: ' + process.stdout[-500:])
    check(call('GET', '/health')[0] == 200, 'Compute service health did not recover')


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def run():
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
    output = ROOT / 'results/validation/compute-service' / stamp
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'started_unix': time.time(), 'checks': [], 'job_ids': [],
              'gpu_inference_performed': False, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    lock = (ROOT / 'state/model-library-gpu-probe.lock').open('a')
    locked = False; service_stopped = False
    started = time.monotonic()
    try:
        # The idle supervisor briefly polls under this same lock. Queue for it
        # with a deadline instead of misclassifying that interval as GPU work.
        previous_alarm = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('GPU lock admission exceeded 10 seconds')))
        signal.alarm(10)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX); locked = True
        finally:
            signal.alarm(0); signal.signal(signal.SIGALRM, previous_alarm)
        check(query_active() == [], 'Another active task exists; no test was started')
        pid_before = service_pid(); report['service_pid_before'] = pid_before
        status, _, health = call('GET', '/health')
        check(status == 200 and health['service'] == 'emusician-compute' and health['protocol_version'] == 2, 'Wrong service identity')
        capabilities = call('GET', '/capabilities')[2]
        check(len(capabilities['providers']) == 7 and all(p['available'] for p in capabilities['providers']), 'Model readiness differs from coordinated deployment')
        report['checks'].append('live-health-and-seven-capabilities')
        fixture = io.BytesIO()
        with wave.open(fixture, 'wb') as writer:
            writer.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            writer.writeframes(b'\x10\x00' * 2000)
        data = fixture.getvalue(); sha = hashlib.sha256(data).hexdigest()
        report['fixture'] = {'sha256': sha, 'bytes': len(data), 'seconds': .25, 'kind': 'synthetic-constant-low-amplitude'}
        check(call('PUT', '/assets/' + '0'*64, data)[0] == 400, 'Wrong upload SHA was accepted')
        check(call('HEAD', '/assets/' + '0'*64)[0] == 404, 'Failed upload was published')
        for _ in range(2):
            status, _, upload = call('PUT', '/assets/' + sha, data)
            check(status == 200 and upload['sha256'] == sha and upload['frames'] == 2000, 'Verified upload failed')
        check(call('HEAD', '/assets/' + sha)[0] == 200, 'Uploaded asset not discoverable')
        report['checks'].append('streamed-upload-hash-rejection-and-idempotent-content')

        def request(suffix):
            job_id = 'servicecheck-' + stamp + '-' + suffix
            report['job_ids'].append(job_id)
            return {'request_id': job_id, 'kind': 'chords', 'model_id': 'chordmini', 'input': {'sha256': sha}, 'parameters': {}}

        first = request('cancel')
        check(call('POST', '/jobs', first)[0] == 202, 'Initial submission failed')
        status, _, replay = call('POST', '/jobs', first)
        check(status == 200 and replay['status'] == 'queued', 'Idempotent request changed task state')
        conflicting = {**first, 'kind': 'separate', 'model_id': 'scnet'}
        check(call('POST', '/jobs', conflicting)[0] == 409, 'Changed payload reused a task ID')
        # Every call uses a fresh TCP connection: reconnecting reads the same
        # durable task and never creates a second model execution.
        replay = call('GET', '/jobs/' + first['request_id'])[2]
        check(replay['job_id'] == first['request_id'] and replay['status'] == 'queued', 'Reconnected task identity changed')
        for _ in range(2):
            cancelled = call('POST', '/jobs/' + first['request_id'] + '/cancel', {})[2]
            check(cancelled['status'] == 'cancelled', 'Queued cancellation was not terminal/idempotent')
        check(call('GET', '/jobs/' + first['request_id'] + '/artifacts/chords.json')[0] == 409, 'Cancelled artifacts became downloadable')
        report['checks'].append('request-idempotency-409-reconnect-queued-cancel-artifact-fence')

        pending = request('restart')
        check(call('POST', '/jobs', pending)[0] == 202, 'Restart fixture submission failed')
        check(query_active() == [(pending['request_id'], 'queued')], 'Foreign or running work arrived; service left untouched')
        check(service_pid() == pid_before, 'Service changed before controlled restart')
        os.kill(pid_before, signal.SIGSTOP)
        try:
            check(query_active() == [(pending['request_id'], 'queued')], 'A task changed before stop; resume without migration')
            os.kill(pid_before, signal.SIGTERM); service_stopped = True
        finally:
            try: os.kill(pid_before, signal.SIGCONT)
            except ProcessLookupError: pass
        deadline = time.monotonic()+15
        while alive(pid_before) and time.monotonic()<deadline: time.sleep(.1)
        check(not alive(pid_before), 'Owned service did not stop; no replacement started')
        start_service(); service_stopped = False
        report['service_pid_after'] = service_pid()
        recovered = call('GET', '/jobs/' + pending['request_id'])[2]
        check(recovered['status'] == 'interrupted', 'Restart did not mark pending task interrupted')
        check(call('POST', '/jobs', pending)[2]['status'] == 'interrupted', 'Retry silently relaunched interrupted task')
        check(call('GET', '/jobs/' + first['request_id'])[2]['status'] == 'cancelled', 'Restart altered a terminal task')
        check(call('HEAD', '/assets/' + sha)[0] == 200, 'Restart lost the immutable asset')
        check(query_active() == [], 'Unexpected active work after restart')
        report['checks'].append('controlled-restart-interrupted-recovery-terminal-and-asset-preservation')
        for job_id in report['job_ids']:
            folder = ROOT / 'jobs/compute' / job_id
            check(not (folder/'output').exists() and not (folder/'attempt.json').exists(), 'A model worker ran while inference was forbidden')
        report['checks'].append('no-worker-or-gpu-inference-was-started')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error)[:800])
    finally:
        # Never release the GPU lock with one of our synthetic tasks still queued.
        # A restart failure gets one bounded recovery attempt; original project
        # jobs/services and model environments are never removed or modified.
        if locked:
            if service_stopped:
                try: start_service()
                except Exception as error: report['recovery_error'] = type(error).__name__ + ': ' + str(error)[:300]
            try:
                with sqlite3.connect(ROOT/'state/compute.sqlite3', timeout=3) as database:
                    for job_id in report['job_ids']:
                        database.execute("UPDATE jobs SET status='cancelled',phase='cancelled',updated=? WHERE id=? AND status='queued'", (time.time(), job_id))
                report['active_after'] = query_active()
            except Exception as error:
                report.update(status='failed', cleanup_error=type(error).__name__ + ': ' + str(error)[:300])
            lock.close()
        else:
            lock.close()
        report.update(elapsed_seconds=time.monotonic()-started, finished_unix=time.time(), output=str(output))
        atomic(output/'receipt.json', report)
        print(json.dumps(report), flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-idle-restart-window',action='store_true',required=True)
    parser.parse_args()
    raise SystemExit(run())
