"""Cloud-only, fixed-destination binary stdin receiver; never accepts credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

ROOT = Path('/root/autodl-tmp/emusician')
WEIGHT_BYTES = 1228144472
WEIGHT_SHA = 'ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec'
RESERVE = 50_000_000_000
CHUNK = 1024 * 1024


def no_links(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Symlink path refused')


def matches(path, size, digest):
    no_links(path)
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest() == digest


def receive(name, size, expected, stream):
    if name not in ('config.json', 'model.safetensors') or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Invalid fixed artifact metadata')
    if (name == 'config.json' and not 0 < size <= 65536) or (name == 'model.safetensors' and (size != WEIGHT_BYTES or expected != WEIGHT_SHA)):
        raise ValueError('Unexpected artifact size or SHA')
    directory = ROOT/'models/muscriptor'
    no_links(directory)
    if not ROOT.is_dir():
        raise ValueError('Cloud root missing')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/name
    no_links(target)
    if target.exists() and not matches(target, size, expected):
        raise ValueError('Existing different artifact preserved')
    if shutil.disk_usage(ROOT).free - size < RESERVE:
        raise RuntimeError('Cloud disk reserve insufficient')
    temporary = directory/('.relay-' + uuid.uuid4().hex + '.partial')
    owned = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        owned = True
        received, digest = 0, hashlib.sha256()
        with os.fdopen(fd, 'wb') as destination:
            while chunk := stream.read(min(CHUNK, size - received + 1)):
                received += len(chunk)
                if received > size:
                    raise ValueError('Input exceeds declared size')
                if shutil.disk_usage(ROOT).free - (size - received + len(chunk)) < RESERVE:
                    raise RuntimeError('Cloud disk reserve exhausted')
                destination.write(chunk)
                digest.update(chunk)
            if received != size or digest.hexdigest() != expected:
                raise ValueError('Input size or SHA mismatch')
            destination.flush()
            os.fsync(destination.fileno())
        no_links(directory)
        try:
            os.link(temporary, target)
            published = True
        except FileExistsError:
            if not matches(target, size, expected):
                raise ValueError('Concurrent different artifact preserved')
            published = False
        return {'status': 'passed', 'path': str(target), 'bytes': received, 'sha256': expected, 'published': published}
    finally:
        if owned:
            temporary.unlink(missing_ok=True)  # Exact unique file created by this process only.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--filename', required=True)
    parser.add_argument('--bytes', dest='size', type=int, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    try:
        if os.name != 'posix':
            raise RuntimeError('Cloud-only receiver')
        report = receive(args.filename, args.size, args.sha256, sys.stdin.buffer)
    except Exception as error:
        report = {'status': 'failed', 'error_type': type(error).__name__}
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
