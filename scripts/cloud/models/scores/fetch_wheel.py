"""Cloud-only parallel range fetch of exactly pinned public wheels."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request
from stage import ROOT, free_space, digest
from toolchain import WHEEL

TORCH = {
    'path': 'torch-2.8.0+cu128-cp311-cp311-manylinux_2_28_x86_64.whl',
    'url': 'https://download-r2.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp311-cp311-manylinux_2_28_x86_64.whl',
    'sha256': '039b9dcdd6bdbaa10a8a5cd6be22c4cb3e3589a341e5f904cbb571ca28f55bed',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name', choices=['torch', 'ffmpeg'])
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud only')
    spec = TORCH if args.name == 'torch' else WHEEL
    directory = ROOT/'workspace/models/sheetsage2'/('wheels' if args.name == 'torch' else 'toolchain')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/spec['path']
    if target.exists():
        if digest(target) == spec['sha256']:
            print(json.dumps({'status': 'existing-verified', 'path': str(target)}))
            return
        raise RuntimeError('Existing wheel differs; refusing overwrite')
    request = urllib.request.Request(spec['url'], headers={'Range': 'bytes=0-0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        match = re.fullmatch(r'bytes 0-0/(\d+)', response.headers.get('Content-Range', ''))
        if response.status != 206 or not match:
            raise RuntimeError('Server must support exact byte ranges')
        size = int(match[1])
        if len(response.read(2)) != 1 or not 0 < size < 1_000_000_000:
            raise RuntimeError('Unexpected wheel size')
    if spec.get('bytes', size) != size:
        raise RuntimeError('Pinned wheel size differs')
    free_space(size * 2)
    chunks = directory/(spec['path']+'.chunks')
    chunks.mkdir(exist_ok=True)
    chunk_size = 4*1024*1024
    started = time.monotonic()

    def fetch(index):
        start = index*chunk_size
        end = min(start+chunk_size, size)-1
        part = chunks/str(index)
        # Every part is verified against the aggregate pinned SHA at the end.
        if part.is_file() and part.stat().st_size == end-start+1:
            return index
        for attempt in range(3):
            try:
                req = urllib.request.Request(spec['url'], headers={'Range': f'bytes={start}-{end}'})
                with urllib.request.urlopen(req, timeout=45) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                        raise RuntimeError('CDN returned incorrect byte range')
                    data = response.read(end-start+2)
                if len(data) != end-start+1:
                    raise RuntimeError('Truncated or oversized range')
                part.write_bytes(data)
                return index
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1)

    count = (size+chunk_size-1)//chunk_size
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for done, _ in enumerate(executor.map(fetch, range(count)), 1):
            if done % 10 == 0 or done == count:
                print(json.dumps({'wheel': args.name, 'chunks_complete': done, 'chunks_total': count}), flush=True)
    partial = directory/(spec['path']+'.verified-partial')
    with partial.open('wb') as output:
        for index in range(count):
            output.write((chunks/str(index)).read_bytes())
    if partial.stat().st_size != size or digest(partial) != spec['sha256']:
        raise RuntimeError('Full official wheel SHA256 mismatch')
    partial.replace(target)
    # Remove only the exact range files just consumed, retaining no duplicate bytes.
    for index in range(count):
        (chunks/str(index)).unlink()
    chunks.rmdir()
    print(json.dumps({'status': 'verified', 'path': str(target), 'bytes': size,
                      'sha256': spec['sha256'], 'seconds': time.monotonic()-started}), flush=True)


if __name__ == '__main__':
    main()
