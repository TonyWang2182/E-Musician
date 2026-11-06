"""One real queued generation, idempotency/conflict, and verified download probe."""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path('/root/autodl-tmp/emusician')
BASE = 'http://127.0.0.1:18081'


def call(path, value=None):
    data = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=120)
    args = parser.parse_args()
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    job_id = f'gateway-{stamp}-{args.duration}s'
    directory = ROOT / 'experiments' / job_id
    directory.mkdir(parents=True)
    request = {'request_id': job_id, 'kind': 'generate', 'model_id': 'ace-step-1.5-xl-turbo',
               'prompt': 'Relaxed instrumental piano jazz trio with upright bass and brushed drums, warm clean studio sound, flowing musical phrases.',
               'lyrics': '', 'instrumental': True, 'duration_seconds': args.duration, 'bpm': 120,
               'time_signature': '4/4', 'seed': 122}
    started = time.monotonic()
    status, submitted = call('/jobs', request)
    if status != 202:
        raise RuntimeError(f'Submit failed: {status} {submitted}')
    status, duplicate = call('/jobs', request)
    if status != 200 or duplicate['job_id'] != job_id:
        raise RuntimeError('Idempotent replay failed')
    status, conflict = call('/jobs', dict(request, seed=123))
    if status != 409:
        raise RuntimeError('Conflict was not rejected')
    last = None
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        status, item = call('/jobs/' + job_id)
        if status != 200:
            raise RuntimeError(f'Polling failed: {status}')
        if item['status'] != last:
            print(json.dumps({'job_id': job_id, 'status': item['status'], 'elapsed_seconds': time.monotonic()-started}), flush=True)
            last = item['status']
        if last in {'ready', 'failed', 'cancelled', 'interrupted'}:
            break
        time.sleep(2)
    else:
        call('/jobs/' + job_id + '/cancel', {})
        raise TimeoutError('Real gateway probe exceeded 900 seconds and cancellation was requested')
    directory.joinpath('request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
    directory.joinpath('receipt.json').write_text(json.dumps(item, indent=2), encoding='utf-8')
    if last != 'ready':
        raise RuntimeError(f'Generation failed: {item.get("error")}')
    with urllib.request.urlopen(BASE+'/jobs/'+job_id+'/artifacts/audio.wav', timeout=30) as response:
        payload = response.read(30 * 1024 * 1024 + 1)
    artifact = item['result']['artifacts'][0]
    if len(payload) != artifact['bytes'] or hashlib.sha256(payload).hexdigest() != artifact['sha256']:
        raise RuntimeError('Downloaded artifact hash/size mismatch')
    output = directory / 'downloaded.wav'
    output.write_bytes(payload)
    with wave.open(str(output)) as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
            raise RuntimeError('Nonportable WAV')
        duration = audio.getnframes() / audio.getframerate()
        if abs(duration-args.duration) > 1:
            raise RuntimeError('Generated duration differs by over one second')
    evidence = {'utc': stamp, 'request_id': job_id, 'idempotent_replay': True, 'different_parameters_rejected': True,
                'download_hash_verified': True, 'wall_seconds': time.monotonic()-started,
                'result': item['result']}
    directory.joinpath('probe.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence), flush=True)


if __name__ == '__main__':
    main()
