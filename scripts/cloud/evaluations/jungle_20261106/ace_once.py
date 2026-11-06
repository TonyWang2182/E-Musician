"""One complete, unchanged Jungle prompt through the existing ACE queue.

Cloud-only evaluation. No model/service edits, generation retry or local audio copy.
"""
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
import urllib.error
import urllib.request
import uuid
import wave

ROOT = Path('/root/autodl-tmp/emusician')
BASE = 'http://127.0.0.1:18081'
TERMINAL = {'ready', 'failed', 'cancelled', 'interrupted'}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def call(path, value=None):
    data = None if value is None else json.dumps(value, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu',
        '--format=csv,noheader,nounits'], text=True, timeout=5).strip()
    return {'active_ace_jobs': active, 'gpu_csv_name_total_used_free_mib_util_percent': gpu}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def cancel_owned(job_id, report):
    code, item = call('/jobs/' + job_id)
    if code == 404:
        report['owned_job_final_state'] = 'not_found'
        return
    if code != 200:
        raise RuntimeError('Cannot determine owned job state for cancellation')
    if item['status'] not in TERMINAL:
        code, item = call('/jobs/' + job_id + '/cancel', {})
        report['cancellation_http_code'] = code
        deadline = time.monotonic() + 60
        while item.get('status') not in TERMINAL and time.monotonic() < deadline:
            time.sleep(1)
            code, item = call('/jobs/' + job_id)
    report['owned_job_final_state'] = item.get('status')
    report['owned_job_terminal'] = item.get('status') in TERMINAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', type=Path, required=True)
    parser.add_argument('--approved-slot', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir() or not args.approved_slot:
        raise RuntimeError('Requires the approved cloud GPU slot')
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Evaluation interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    job_id = 'jungle-ace-' + stamp + '-' + uuid.uuid4().hex[:10]
    directory = ROOT/'results/evaluations/jungle-20261106'/job_id
    directory.mkdir(parents=True, exist_ok=False)
    report = {'id': job_id, 'status': 'preflight', 'started_utc': stamp,
        'attempts_requested': 1, 'audio_copied_to_e': False, 'daw_connected': False,
        'quality_evaluation': False, 'evaluation_script_sha256': sha(Path(__file__))}
    started = time.monotonic()
    lock = None
    submitted = False
    try:
        raw = args.prompt.read_bytes()
        prompt = raw.decode('utf-8').rstrip('\r\n')
        directory.joinpath('prompt.txt').write_bytes(raw)
        report.update(prompt_file_sha256=hashlib.sha256(raw).hexdigest(),
            prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(), prompt_characters=len(prompt))
        if not 1 <= len(prompt.strip()) <= 2000:
            raise ValueError('Complete prompt exceeds existing gateway limit; no truncation or submission')
        request = {'request_id': job_id, 'kind': 'generate', 'model_id': 'ace-step-1.5-xl-turbo',
            'prompt': prompt, 'lyrics': '', 'instrumental': True, 'duration_seconds': 120,
            'bpm': 170, 'time_signature': '4/4', 'seed': 170611}
        save(directory/'request.json', request)
        lock = (ROOT/'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report['before'] = state()
        if report['before']['active_ace_jobs']:
            raise RuntimeError('ACE queue is active; no request submitted')
        code, capabilities = call('/capabilities')
        if code != 200:
            raise RuntimeError('Cannot read current gateway capabilities')
        save(directory/'capabilities.json', capabilities)
        report['status'] = 'submitting'
        save(directory/'evaluation.json', report)
        submitted = True  # A transport failure can occur after server admission.
        code, item = call('/jobs', request)  # Exactly one submission; never retried.
        if code != 202:
            raise RuntimeError(f'Generation submission returned HTTP {code}: {item}')
        report['submission_http_code'] = code
        last = None
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            code, item = call('/jobs/' + job_id)
            if code != 200:
                raise RuntimeError(f'Cannot read owned generation job: HTTP {code}')
            if item['status'] != last:
                last = item['status']
                print(json.dumps({'job_id': job_id, 'status': last, 'elapsed_seconds': time.monotonic()-started}), flush=True)
            if item['status'] in TERMINAL:
                break
            time.sleep(1)
        else:
            raise TimeoutError('900-second evaluation deadline reached')
        save(directory/'receipt.json', item)
        report.update(owned_job_final_state=item['status'], owned_job_terminal=True)
        if item['status'] != 'ready':
            raise RuntimeError('Generation ended without audio: ' + str(item.get('error')))
        result = item['result']
        if result['parameters'] != request:
            raise RuntimeError('Gateway effective request differs from complete test request')
        audio = ROOT/'jobs/generation'/job_id/'audio.wav'
        evidence = result['artifacts'][0]
        if audio.is_symlink() or audio.stat().st_size != evidence['bytes'] or sha(audio) != evidence['sha256']:
            raise RuntimeError('Cloud audio size/hash does not match gateway receipt')
        with wave.open(str(audio), 'rb') as stream:
            actual = {'frames': stream.getnframes(), 'sample_rate': stream.getframerate(),
                'channels': stream.getnchannels(), 'sample_width_bytes': stream.getsampwidth(),
                'duration_seconds': stream.getnframes()/stream.getframerate()}
        if actual['sample_width_bytes'] != 2 or actual['channels'] not in (1, 2) or abs(actual['duration_seconds']-120) > 1:
            raise RuntimeError('Unexpected generated audio format or duration')
        report.update(status='passed', audio_path=str(audio), actual_audio=actual,
            audio_sha256=evidence['sha256'], audio_bytes=evidence['bytes'],
            model=result['model'], metrics=result['metrics'], conditioning=result['conditioning'])
    except BaseException as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:1000])
        if submitted:
            try:
                cancel_owned(job_id, report)
            except BaseException as cancel_error:
                report['cancellation_error'] = f'{type(cancel_error).__name__}: {cancel_error}'[:1000]
    finally:
        report['wall_seconds'] = time.monotonic()-started
        try:
            report['after'] = state()
        except BaseException as error:
            report['after_diagnostic_error'] = f'{type(error).__name__}: {error}'[:1000]
        try:
            save(directory/'evaluation.json', report)
        finally:
            if lock is not None:
                lock.close()
        print(json.dumps(report, ensure_ascii=True), flush=True)
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
