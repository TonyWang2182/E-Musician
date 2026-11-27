"""Offline Linux cloud snapshot; raw split tar preserves environments and links.

No GPU/model imports. Use only while the two production scheduling locks are free.
Finalized chunks are immutable and may be pulled while later chunks are written.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import time

DATA = Path('/root/autodl-tmp/emusician')
RUNTIME = Path('/root/miniconda3')
TOPS = ('manifests', 'sources', 'deployments', 'tools', 'assets', 'jobs',
        'results', 'experiments', 'logs', 'state', 'workspace', 'models', 'envs')
OMIT_NAMES = {'.git', '__pycache__', '.env', 'secrets', 'token', 'stored_tokens'}
BLOCK = 1024 * 1024


def write_json(path, value):
    temporary = path.with_name(path.name + '.partial')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest_file(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(BLOCK):
            result.update(block)
    return result.hexdigest()


class Parts:
    def __init__(self, directory, limit=512 * BLOCK):
        self.directory, self.limit = directory, limit
        self.parts, self.stream, self.size = [], None, 0
        self.total = 0

    def write(self, data):
        count = len(data)
        remaining = memoryview(data)
        while remaining:
            if self.stream is None:
                self.name = 'part-%06d.tarpart' % len(self.parts)
                self.path = self.directory / (self.name + '.partial')
                self.stream = self.path.open('xb')
                self.sha = hashlib.sha256()
                self.size = 0
            piece = remaining[:self.limit - self.size]
            self.stream.write(piece)
            self.sha.update(piece)
            self.size += len(piece)
            self.total += len(piece)
            remaining = remaining[len(piece):]
            if self.size == self.limit:
                self.flush_part()
        return count

    def flush_part(self):
        if self.stream is None:
            return
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        self.path.replace(self.directory / self.name)
        receipt = {'name': self.name, 'size': self.size, 'sha256': self.sha.hexdigest()}
        self.parts.append(receipt)
        write_json(self.directory / (self.name.replace('.tarpart', '.json')), receipt)
        write_json(self.directory / 'status.json', {
            'phase': 'capturing', 'parts_ready': len(self.parts), 'bytes_ready': self.total,
            'updated_unix': time.time()})
        self.stream = None


class HashedInput:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, count=-1):
        result = self.stream.read(count)
        self.digest.update(result)
        return result


def excluded(path, data=DATA, runtime=RUNTIME):
    # Do not follow links here. A private HF login is deliberately not portable.
    parts = path.parts
    if any(name in OMIT_NAMES for name in parts) or path.suffix in {'.pyc', '.pyo'}:
        return True
    if path.is_relative_to(data / 'workspace/models/muscriptor/hf'):
        return True
    if path.is_relative_to(runtime / 'pkgs'):
        return True
    if path.is_relative_to(data / 'state') and (
            path.suffix in {'.pid', '.lock'} or path.name.endswith(('-wal', '-shm'))):
        return True
    return False


def walk(path):
    if excluded(path):
        return
    yield path
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.iterdir()):
            yield from walk(child)


def database_snapshot(source, destination):
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as connection:
        active = connection.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN "
                                    "('ready','failed','cancelled','interrupted')").fetchone()[0]
        if active:
            raise RuntimeError('Nonterminal cloud jobs: backup requires an idle queue')
        with closing(sqlite3.connect(destination)) as target:
            deadline = time.monotonic() + 60
            def progress(*_):
                if time.monotonic() > deadline:
                    raise TimeoutError('Database backup timeout')
            connection.backup(target, pages=256, progress=progress)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database integrity check failed')


def capture(destination):
    import fcntl
    root = DATA.resolve(strict=True)
    if destination.parent.resolve() != (root / 'exports').resolve():
        raise ValueError('Backup destination must be a new child of exports')
    locks = []
    for name in ('gateway-service.lock', 'model-library-gpu-probe.lock'):
        lock = (root / 'state' / name).open('a+b')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(lock)
    destination.mkdir(mode=0o700)
    write_json(destination / 'status.json', {'phase': 'capturing', 'parts_ready': 0})
    started = time.time()
    try:
        snapshot_dir = destination / 'database-snapshots'
        snapshot_dir.mkdir()
        replacements = {}
        for name in ('generation.sqlite3', 'compute.sqlite3'):
            original = root / 'state' / name
            if original.exists():
                replacement = snapshot_dir / name
                database_snapshot(original, replacement)
                replacements[original] = replacement
        # Small system reconstruction evidence only; no shell profiles or credentials.
        system = {'platform': os.uname()._asdict() if hasattr(os.uname(), '_asdict') else list(os.uname()),
                  'os_release': Path('/etc/os-release').read_text(),
                  'system_image': 'User reports AutoDL image saved; image is separate from this archive.'}
        for label, command in [('packages', ['dpkg-query', '-W']),
                               ('python', ['/root/miniconda3/bin/python', '--version']),
                               ('ffmpeg', ['ffmpeg', '-version']), ('glibc', ['ldd', '--version'])]:
            if not shutil.which(command[0]):
                system[label] = {'available_on_noninteractive_path': False}
                continue
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=30, check=False)
            system[label] = {'exit_code': result.returncode, 'output': result.stdout}
        write_json(destination / 'system.json', system)
        roots = [root / name for name in TOPS if (root / name).exists()] + [RUNTIME]
        # Preserve reusable wheels; ephemeral HF/uv caches and existing backups excluded.
        if (root / 'cache/wheels').is_dir():
            roots.append(root / 'cache/wheels')
        paths = []
        unique = {}
        for base in roots:
            for path in walk(base):
                info = path.lstat()
                paths.append((path, info))
                if stat.S_ISREG(info.st_mode):
                    unique[(info.st_dev, info.st_ino)] = info.st_size
        required = sum(unique.values()) + len(paths) * 4096 + 1024 * BLOCK
        if shutil.disk_usage(root).free < required:
            raise RuntimeError('Insufficient disk headroom for raw archive')
        write_json(destination / 'inventory.json', {'members': len(paths),
                   'unique_regular_bytes': sum(unique.values()), 'reserved_bytes': required,
                   'included': [str(p) for p in roots], 'excluded_names': sorted(OMIT_NAMES),
                   'excluded_other': ['*.pyc', '*.pyo', 'state/*.pid', 'state/*.lock',
                                      'state/*-wal', 'state/*-shm', str(RUNTIME / 'pkgs'),
                                      str(root / 'workspace/models/muscriptor/hf'),
                                      'cache except wheels', '.cache', 'exports', 'vscode-server']})
        parts = Parts(destination)
        manifest_path = destination / 'manifest.jsonl'
        counts = {'file': 0, 'dir': 0, 'symlink': 0, 'hardlink': 0}
        links = []
        with manifest_path.open('x', encoding='utf-8', newline='\n') as manifest:
            with tarfile.open(fileobj=parts, mode='w|', bufsize=BLOCK, format=tarfile.PAX_FORMAT) as archive:
                archive.copybufsize = BLOCK
                for path, before in paths:
                    real = replacements.get(path, path)
                    name = path.as_posix().lstrip('/')
                    member = archive.gettarinfo(str(real), arcname=name)
                    if member is None:
                        raise ValueError('Unsupported member type: ' + name)
                    kind = ('file' if member.isfile() else 'dir' if member.isdir() else
                            'symlink' if member.issym() else 'hardlink' if member.islnk() else None)
                    if kind is None:
                        raise ValueError('Special files are not backed up: ' + name)
                    entry = {'name': name, 'type': kind, 'size': member.size,
                             'mode': member.mode, 'linkname': member.linkname}
                    if kind == 'file':
                        with real.open('rb') as stream:
                            hashed = HashedInput(stream)
                            archive.addfile(member, hashed)
                            entry['sha256'] = hashed.digest.hexdigest()
                    else:
                        archive.addfile(member)
                    if path not in replacements:
                        after = path.lstat()
                        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                                after.st_size, after.st_mtime_ns, after.st_ino):
                            raise RuntimeError('Source changed while capturing: ' + name)
                    if kind == 'symlink':
                        target = path.resolve(strict=False)
                        links.append({'name': name, 'target': str(target), 'exists': target.exists(),
                                      'inside_backed_roots': any(target.is_relative_to(p) for p in roots)
                                      and not excluded(target)})
                    manifest.write(json.dumps(entry, separators=(',', ':')) + '\n')
                    counts[kind] += 1
                    # tarfile otherwise retains hundreds of thousands of TarInfo objects.
                    archive.members.clear()
        parts.flush_part()
        write_json(destination / 'links.json', {'links': links})
        metadata = {}
        for name in ('manifest.jsonl', 'inventory.json', 'system.json', 'links.json'):
            path = destination / name
            metadata[name] = {'name': name, 'size': path.stat().st_size, 'sha256': digest_file(path)}
        receipt = {'schema': 2, 'parts': parts.parts, 'manifest': metadata['manifest.jsonl'],
                   'metadata': metadata, 'summary': {'counts': counts, 'archive_bytes': parts.total,
                   'started_unix': started, 'finished_unix': time.time(),
                   'source_root': str(root), 'restoration_tested': False}}
        write_json(destination / 'receipt.json', receipt)
        write_json(destination / 'status.json', {'phase': 'complete', 'parts_ready': len(parts.parts),
                   'bytes_ready': parts.total, 'finished_unix': time.time()})
        print(json.dumps(receipt['summary']), flush=True)
    except BaseException as error:
        write_json(destination / 'status.json', {'phase': 'failed', 'error_type': type(error).__name__})
        raise
    finally:
        for lock in locks:
            lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    capture(args.destination)
