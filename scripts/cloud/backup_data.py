"""Create a verifiable archive of E-musician data after tasks have stopped."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path('/root/autodl-tmp/emusician')
INCLUDED = ('workspace', 'models', 'datasets', 'jobs', 'results',
            'experiments', 'manifests', 'tools')
EXCLUDED = {'.git', '.env', '.venv', 'node_modules', '__pycache__', 'secrets'}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def snapshot_generation_queue(root: Path) -> None:
    """Create a consistent SQLite backup, including committed WAL contents.

    Do not copy a live SQLite/WAL file with tar. Jobs must be terminal and users
    must stop submitting work while archiving the corresponding artifact files.
    """
    database = root / 'state' / 'generation.sqlite3'
    if not database.exists():
        return
    if database.is_symlink() or not database.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Generation database must be inside the cloud data root')
    directory = root / 'manifests'
    directory.mkdir(exist_ok=True)
    temporary = directory / ('generation-queue-' + uuid4().hex + '.partial')
    started = time.monotonic()
    def progress(status, remaining, total):
        if time.monotonic() - started > 60:
            raise RuntimeError('Generation database snapshot exceeded 60 seconds')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
            active = source.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted')").fetchone()[0]
            if active:
                raise RuntimeError('Finish or cancel generation jobs before backing up data')
            with closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination, pages=256, progress=progress, sleep=0.1)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Generation database snapshot failed integrity check')
        temporary.replace(directory / 'generation-queue.sqlite3')
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    root = ROOT.resolve(strict=True)
    snapshot_generation_queue(root)
    files = []
    omitted = []
    for name in INCLUDED:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(root)
            if any(part in EXCLUDED for part in relative.parts):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                omitted.append(str(relative))
                continue
            if path.is_file():
                stat = path.stat()
                files.append((path, relative.as_posix(), stat.st_size,
                              stat.st_mtime_ns))
    total = sum(item[2] for item in files)
    if shutil.disk_usage(root).free < total * 1.02 + 32 * 1024 * 1024:
        raise RuntimeError('Insufficient space for an additional backup archive')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = f'emusician-{stamp}-{uuid4().hex[:8]}.tar.gz'
    target = root / 'exports' / name
    target.parent.mkdir(exist_ok=True)
    entries = []
    # Weights dominate this archive; level 1 keeps CPU time reasonable while
    # preserving the same independently checked tar members and whole hash.
    with tarfile.open(target, mode='x:gz', compresslevel=1) as archive:
        for path, relative, size, mtime_ns in files:
            digest = sha256(path)
            archive.add(path, arcname=relative, recursive=False)
            after = path.stat()
            if after.st_size != size or after.st_mtime_ns != mtime_ns:
                raise RuntimeError(f'File changed during backup: {relative}')
            entries.append({'path': relative, 'size': size, 'sha256': digest})
        manifest = json.dumps({'schema': 1, 'created_utc': stamp,
            'included': INCLUDED, 'excluded_names': sorted(EXCLUDED),
            'omitted_links': omitted, 'files': entries}, indent=2).encode()
        info = tarfile.TarInfo('BACKUP-MANIFEST.json')
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
    result = {'archive': name, 'size': target.stat().st_size,
              'sha256': sha256(target), 'file_count': len(entries)}
    target.with_suffix(target.suffix + '.receipt.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
