"""Relay pinned NVIDIA wheels via local E drive when cloud PyPI is slow.

Uses the upstream uv.lock hashes, never changes a dependency version. Run on the
Windows development machine; completed wheels are retained for reproducibility.
"""
import concurrent.futures
import hashlib
import json
import subprocess
import time
import tomllib
import urllib.request
from pathlib import Path

LOCAL = Path('E:/MusicAgent&DAW/cloud-inference')
SOURCE = LOCAL / 'tools/ACE-Step-1.5-ca1e85fe9430179831e6bc6be790c332190a3866'
TARGET = LOCAL / 'environments/wheels/ace'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(wheel):
    name = wheel['url'].rsplit('/', 1)[-1]
    final = TARGET / name
    expected = wheel['hash'].removeprefix('sha256:')
    began = time.monotonic()
    if not final.exists() or final.stat().st_size != wheel['size'] or sha(final) != expected:
        partial = final.with_suffix('.whl.partial')
        for attempt in range(3):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                headers = {'Range': f'bytes={offset}-'} if offset else {}
                with urllib.request.urlopen(urllib.request.Request(wheel['url'], headers=headers), timeout=60) as response:
                    append = offset > 0 and response.status == 206
                    with partial.open('ab' if append else 'wb') as output:
                        for block in iter(lambda: response.read(4*1024*1024), b''):
                            if time.monotonic()-began > 1800:
                                raise TimeoutError('Wheel relay exceeded 30 minutes')
                            output.write(block)
                if partial.stat().st_size != wheel['size'] or sha(partial) != expected:
                    raise ValueError('Wheel checksum mismatch')
                partial.replace(final)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
    print(f'checked local {name} {time.monotonic()-began:.1f}s', flush=True)
    subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', str(final),
                    f'emusician-autodl:/root/autodl-tmp/emusician/cache/wheels/{name}'], check=True, timeout=900)
    print(f'transferred {name} {time.monotonic()-began:.1f}s', flush=True)


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    lock = tomllib.loads((SOURCE / 'uv.lock').read_text(encoding='utf-8'))
    wheels = []
    for package in lock['package']:
        if package['name'].startswith('nvidia-') and package['name'].endswith('-cu12'):
            wheel = next(w for w in package['wheels'] if 'x86_64.whl' in w['url'])
            wheels.append(wheel)
    (LOCAL/'manifests/ace-wheel-relay.json').write_text(json.dumps(wheels, indent=2), encoding='utf-8')
    subprocess.run(['ssh','-o','BatchMode=yes','emusician-autodl','mkdir -p /root/autodl-tmp/emusician/cache/wheels'],check=True,timeout=30)
    print(json.dumps({'wheels': len(wheels), 'bytes': sum(w['size'] for w in wheels)}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, wheels))
    print('All pinned NVIDIA wheels relayed.', flush=True)


if __name__ == '__main__':
    main()
