"""Resume an SSH backup transfer and verify its raw tar stream without extraction.

Only finalized producer parts are downloaded. Linux modes and link metadata are
checked against the separate JSONL manifest; nothing is unpacked on Windows.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shlex
import sqlite3
import subprocess
import tarfile
import threading
import time
from uuid import uuid4

CHUNK = 256 * 1024
PART_LIMIT = 512 * 1024 * 1024
METADATA_LIMIT = 1024 * 1024
MANIFEST_LIMIT = 1024 * 1024 * 1024
SIDECAR_LIMIT = 64 * 1024 * 1024
STALL_TIMEOUT_SECONDS = 180
ROOTS = ('root/autodl-tmp/emusician', 'root/miniconda3')


class BackupError(ValueError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BackupError('Duplicate JSON property')
            result[key] = value
        return result
    def nonfinite(value):
        raise BackupError('Non-finite JSON number')
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise BackupError('Expected a JSON object')
    return result


def safe_local(path):
    path = Path(path)
    if path.is_symlink():
        raise BackupError('Refusing a linked local file: ' + path.name)
    return path


def atomic_json(path, value):
    path = safe_local(path)
    temporary = safe_local(path.with_name(path.name + '.partial'))
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def file_hash(path):
    digest = hashlib.sha256()
    with safe_local(path).open('rb') as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def artifact(value, expected_name, limit=PART_LIMIT):
    if (not isinstance(value, dict) or value.get('name') != expected_name
            or type(value.get('size')) is not int or not 0 < value['size'] <= limit
            or not isinstance(value.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', value['sha256'])):
        raise BackupError('Invalid artifact metadata for ' + expected_name)
    return {key: value[key] for key in ('name', 'size', 'sha256')}


def validate_receipt(value):
    if type(value.get('schema')) is not int or value['schema'] != 2:
        raise BackupError('Unsupported receipt schema')
    parts = value.get('parts')
    if not isinstance(parts, list) or not 0 < len(parts) <= 100000:
        raise BackupError('Invalid receipt part list')
    parts = [artifact(part, f'part-{index:06d}.tarpart') for index, part in enumerate(parts)]
    manifest = artifact(value.get('manifest'), 'manifest.jsonl', MANIFEST_LIMIT)
    return parts, manifest


def validate_sidecars(receipt, manifest):
    values = receipt.get('metadata', {})
    if not isinstance(values, dict) or set(values) - {'manifest.jsonl', 'inventory.json', 'system.json', 'links.json'}:
        raise BackupError('Invalid backup metadata sidecar mapping')
    if 'manifest.jsonl' in values and artifact(values['manifest.jsonl'], 'manifest.jsonl', MANIFEST_LIMIT) != manifest:
        raise BackupError('Conflicting manifest metadata')
    return [artifact(value, name, SIDECAR_LIMIT) for name, value in values.items() if name != 'manifest.jsonl']


class Remote:
    def __init__(self, host, root, *, executable='ssh', config=None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', host):
            raise BackupError('Expected an SSH host alias')
        if (not re.fullmatch(r'/root/autodl-tmp/emusician/exports/[A-Za-z0-9][A-Za-z0-9_.-]*', root)
                or root.rsplit('/', 1)[-1] in {'.', '..'}):
            raise BackupError('Remote root must be one named emusician export')
        self.host, self.root = host, root
        self.executable, self.config = executable, config

    def command(self, name, *, offset=None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise BackupError('Invalid remote artifact name')
        quoted = shlex.quote(self.root + '/' + name)
        if offset is not None and (type(offset) is not int or offset < 0):
            raise BackupError('Invalid remote byte offset')
        reader = (f'dd if={quoted} iflag=skip_bytes skip={offset} bs=1048576 status=none'
                  if offset is not None else f'cat -- {quoted}')
        command = f'if test -f {quoted}; then {reader}; else exit 44; fi'
        return ([self.executable] + (['-F', str(self.config)] if self.config else [])
                + ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                   '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', self.host, command])

    @contextmanager
    def stream(self, name, *, optional=False):
        process = subprocess.Popen(
            self.command(name), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        try:
            yield process.stdout
            code = process.wait(timeout=60)
            if code and not (optional and code == 44):
                raise BackupError(f'SSH read failed for {name} (exit {code})')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            process.stdout.close()

    def download_to(self, metadata, pending, *, progress=None, cancel=None):
        """Append only the missing suffix; completed files still need full SHA."""
        pending = safe_local(pending)
        if pending.exists() and not pending.is_file():
            raise BackupError('Owned partial is not a regular file')
        offset = pending.stat().st_size if pending.exists() else 0
        if offset > metadata['size']:
            # An overlong partial cannot be a prefix of this immutable artifact.
            with pending.open('wb'):
                pass
            offset = 0
        if offset == metadata['size']:
            if progress:
                progress(offset)
            return
        with pending.open('ab') as output:
            process = subprocess.Popen(self.command(metadata['name'], offset=offset), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.DEVNULL)
            previous, last_change = offset, time.monotonic()
            try:
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise BackupError('Transfer cancelled after another worker failed')
                    count = pending.stat().st_size
                    if count > metadata['size']:
                        raise BackupError('Remote artifact exceeds expected size')
                    now = time.monotonic()
                    if count > previous:
                        previous, last_change = count, now
                    elif now - last_change >= STALL_TIMEOUT_SECONDS:
                        raise BackupError('SSH transfer made no byte progress for 180 seconds')
                    if progress:
                        progress(count)
                    time.sleep(.5)
                if process.returncode:
                    raise BackupError(f'SSH read failed for {metadata["name"]} (exit {process.returncode})')
                output.flush()
                os.fsync(output.fileno())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=15)
        if progress:
            progress(pending.stat().st_size)

    def metadata(self, name, *, optional=False):
        for attempt in range(3):
            try:
                with self.stream(name, optional=optional) as stream:
                    raw = stream.read(METADATA_LIMIT + 1)
                    if len(raw) > METADATA_LIMIT:
                        raise BackupError('Remote metadata exceeds limit')
                if not raw and optional:
                    return None
                return decode_json(raw)
            except (OSError, BackupError, subprocess.SubprocessError):
                if attempt == 2:
                    raise
                time.sleep(2)


def fetch_verified(remote, metadata, directory, *, retries=3, progress=None, direct_file=False, cancel=None):
    """Publish only a complete hash-verified part; retry only our partial file."""
    target = safe_local(Path(directory) / metadata['name'])
    if target.exists():
        if not target.is_file() or target.stat().st_size != metadata['size'] or file_hash(target) != metadata['sha256']:
            raise BackupError('Existing local artifact differs: ' + target.name)
        return False
    pending = safe_local(target.with_name(target.name + '.partial'))
    for attempt in range(retries):
        if cancel is not None and cancel.is_set():
            raise BackupError('Transfer cancelled after another worker failed')
        digest, count = hashlib.sha256(), 0
        try:
            if direct_file:
                remote.download_to(metadata, pending, cancel=cancel,
                    progress=(lambda value: progress(value, attempt + 1)) if progress else None)
                count = pending.stat().st_size
                actual_hash = file_hash(pending) if count == metadata['size'] else None
            else:
                with remote.stream(metadata['name']) as source, pending.open('wb') as output:
                    while block := source.read(CHUNK):
                        if cancel is not None and cancel.is_set():
                            raise BackupError('Transfer cancelled after another worker failed')
                        count += len(block)
                        if count > metadata['size']:
                            raise BackupError('Remote artifact exceeds expected size')
                        digest.update(block)
                        output.write(block)
                        if progress:
                            progress(count, attempt + 1)
                    output.flush()
                    os.fsync(output.fileno())
                actual_hash = digest.hexdigest()
            if count != metadata['size'] or actual_hash != metadata['sha256']:
                if direct_file and count >= metadata['size']:
                    # A complete but corrupt prefix must never be appended again.
                    # Reset only our own partial; verified final files are untouched.
                    with safe_local(pending).open('wb'):
                        pass
                raise BackupError('Downloaded artifact checksum or size mismatch')
            os.replace(pending, target)
            return True
        except (OSError, BackupError, subprocess.SubprocessError):
            if attempt + 1 == retries or (cancel is not None and cancel.is_set()):
                raise
            # The next attempt truncates only this owned .partial file.
    raise BackupError('No transfer attempt completed')


def member_name(name):
    if (not isinstance(name, str) or not name or len(name) > 4096
            or '\\' in name or ':' in name or any(ord(c) < 32 for c in name)):
        raise BackupError('Invalid tar member name')
    name = name.removesuffix('/')
    if any(part in {'', '.', '..'} for part in name.split('/')):
        raise BackupError('Unsafe tar member path')
    if not any(name == root or name.startswith(root + '/') for root in ROOTS):
        raise BackupError('Tar member lies outside permitted restore roots')
    return name


def link_target(name, link, kind):
    if not isinstance(link, str) or not link or '\\' in link or any(ord(c) < 32 for c in link):
        raise BackupError('Invalid tar link target')
    if kind == 'hardlink':
        return member_name(link)
    resolved = posixpath.normpath(link.lstrip('/') if link.startswith('/')
                                 else posixpath.join(posixpath.dirname(name), link))
    return member_name(resolved)


class StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf, encoding, errors):
        try:
            return super().frombuf(buf, encoding, errors)
        except (tarfile.InvalidHeaderError, tarfile.TruncatedHeaderError, tarfile.EmptyHeaderError) as exc:
            raise tarfile.SubsequentHeaderError(str(exc)) from exc


class PartReader:
    """Concatenate parts while checking every byte against its producer hash."""
    def __init__(self, directory, parts):
        self.directory, self.parts = Path(directory), parts
        self.index, self.source, self.count = 0, None, 0
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size=-1):
        if size == 0 or self.index == len(self.parts):
            return b''
        if self.source is None:
            self.path = safe_local(self.directory / self.parts[self.index]['name'])
            self.before = self.path.stat()
            if not self.path.is_file() or self.before.st_size != self.parts[self.index]['size']:
                raise BackupError('Local part size differs from receipt')
            self.source = self.path.open('rb')
            self.part_digest, self.count = hashlib.sha256(), 0
        remaining = self.parts[self.index]['size'] - self.count
        block = self.source.read(min(CHUNK, remaining, CHUNK if size < 0 else size))
        if not block:
            raise BackupError('Unexpected end of a backup part')
        self.count += len(block)
        self.bytes_read += len(block)
        self.part_digest.update(block)
        self.digest.update(block)
        if self.count == self.parts[self.index]['size']:
            after = self.path.stat()
            if (self.before.st_size, self.before.st_mtime_ns, self.before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise BackupError('Part changed during verification')
            if self.part_digest.hexdigest() != self.parts[self.index]['sha256']:
                raise BackupError('Part checksum differs from receipt')
            self.source.close()
            self.source = None
            self.index += 1
        return block

    def close(self):
        if self.source is not None:
            self.source.close()
            self.source = None


def verify(directory, receipt=None, *, progress=None):
    directory = Path(directory)
    if receipt is None:
        receipt = decode_json(safe_local(directory / 'receipt.json').read_bytes())
    parts, manifest = validate_receipt(receipt)
    sidecars = validate_sidecars(receipt, manifest)
    for metadata in sidecars:
        sidecar = safe_local(directory / metadata['name'])
        if sidecar.stat().st_size != metadata['size'] or file_hash(sidecar) != metadata['sha256']:
            raise BackupError('Sidecar checksum or size differs from receipt: ' + metadata['name'])
    manifest_path = safe_local(directory / manifest['name'])
    if manifest_path.stat().st_size != manifest['size'] or file_hash(manifest_path) != manifest['sha256']:
        raise BackupError('Manifest checksum or size differs from receipt')
    # Disk-backed uniqueness and hardlink checks keep large environment manifests
    # from accumulating hundreds of thousands of Python objects in RAM.
    index_path = directory / ('.verify-index-' + uuid4().hex + '.partial')
    index = sqlite3.connect(index_path)
    index.execute('PRAGMA journal_mode=OFF')
    index.execute('PRAGMA cache_size=-512')
    index.execute('CREATE TABLE members(name TEXT PRIMARY KEY,kind TEXT)')
    reader = PartReader(directory, parts)
    counts = {kind: 0 for kind in ('file', 'dir', 'symlink', 'hardlink')}
    content_bytes = 0
    if progress:
        progress({'members_verified': 0, 'archive_bytes_read': 0, 'content_bytes_verified': 0})
    try:
        with manifest_path.open('rb') as expected, tarfile.open(
                fileobj=reader, mode='r|', bufsize=CHUNK, tarinfo=StrictTarInfo) as archive:
            for member in archive:
                line = expected.readline(METADATA_LIMIT + 1)
                if not line or len(line) > METADATA_LIMIT:
                    raise BackupError('Manifest missing or oversized member line')
                entry = decode_json(line)
                name = member_name(member.name)
                kind = ('file' if member.isfile() else 'dir' if member.isdir()
                        else 'symlink' if member.issym() else 'hardlink' if member.islnk() else None)
                if kind is None or member.sparse is not None:
                    raise BackupError('Unsupported special or sparse tar member')
                if (entry.get('name') != name or entry.get('type') != kind
                        or type(entry.get('size')) is not int or entry['size'] != member.size
                        or type(entry.get('mode')) is not int or entry['mode'] != member.mode
                        or entry.get('linkname', '') != member.linkname):
                    raise BackupError('Tar metadata differs from manifest: ' + name)
                if not 0 <= member.mode <= 0o7777 or member.size < 0:
                    raise BackupError('Invalid member mode or size')
                try:
                    index.execute('INSERT INTO members VALUES (?,?)', (name, kind))
                except sqlite3.IntegrityError as exc:
                    raise BackupError('Duplicate tar member: ' + name) from exc
                if kind in {'hardlink', 'symlink'}:
                    target = link_target(name, member.linkname, kind)
                    if kind == 'hardlink':
                        prior = index.execute('SELECT kind FROM members WHERE name=?', (target,)).fetchone()
                        if target == name or prior is None or prior[0] not in {'file', 'hardlink'}:
                            raise BackupError('Hardlink does not refer to an earlier regular file')
                if kind != 'file' and member.size:
                    raise BackupError('Non-file tar member has content')
                if kind == 'file':
                    if not isinstance(entry.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
                        raise BackupError('Invalid manifest file checksum')
                    digest, size = hashlib.sha256(), 0
                    with archive.extractfile(member) as stream:
                        while block := stream.read(CHUNK):
                            digest.update(block)
                            size += len(block)
                    if size != member.size or digest.hexdigest() != entry['sha256']:
                        raise BackupError('Tar file checksum differs from manifest: ' + name)
                    content_bytes += size
                counts[kind] += 1
                archive.members.clear()
                if progress and sum(counts.values()) % 10000 == 0:
                    progress({'members_verified': sum(counts.values()),
                              'archive_bytes_read': reader.bytes_read,
                              'content_bytes_verified': content_bytes})
            if expected.read(1):
                raise BackupError('Manifest has members absent from the archive')
            padding = 0
            while block := archive.fileobj.read(CHUNK):
                padding += len(block)
                if any(block):
                    raise BackupError('Nonzero data follows tar end marker')
            if padding < tarfile.BLOCKSIZE:
                raise BackupError('Tar is missing its second end block')
        if reader.index != len(parts) or reader.bytes_read != sum(part['size'] for part in parts):
            raise BackupError('Verification did not consume all part bytes')
    finally:
        reader.close()
        index.close()
        index_path.unlink(missing_ok=True)
    if progress:
        progress({'members_verified': sum(counts.values()), 'archive_bytes_read': reader.bytes_read,
                  'content_bytes_verified': content_bytes})
    return {'schema': 2, 'phase': 'verified', 'verified_utc': utc(), 'parts': len(parts),
            'archive_bytes': reader.bytes_read, 'raw_tar_sha256': reader.digest.hexdigest(),
            'members': counts, 'member_count': sum(counts.values()), 'content_bytes': content_bytes,
            'part_hashes_verified': True, 'member_hashes_verified': True,
            'metadata_verified': True, 'tar_padding_verified': True, 'extracted': False,
            'sidecars_verified': [entry['name'] for entry in sidecars],
            'restore_tested': False}


def pull(host, remote_root, destination, *, poll_seconds=5, timeout_seconds=172800,
         workers=1, direct_file=False, ssh_executable='ssh', ssh_config=None):
    if not 1 <= workers <= 4:
        raise BackupError('Transfer supports one to four workers')
    remote = Remote(host, remote_root, executable=ssh_executable, config=ssh_config)
    directory = safe_local(Path(destination))
    directory.mkdir(parents=True, exist_ok=True)
    identity_path = directory / 'source.json'
    identity = {'schema': 2, 'host': host, 'remote_root': remote_root}
    if identity_path.exists() and decode_json(safe_local(identity_path).read_bytes()) != identity:
        raise BackupError('Destination belongs to another backup source')
    atomic_json(identity_path, identity)
    started = time.monotonic()
    progress = {'schema': 2, 'phase': 'pulling', 'started_utc': utc(), 'parts_verified': 0,
                'bytes_verified': 0, 'current_part_bytes': 0, 'downloaded_parts': 0, 'reused_parts': 0,
                'workers': workers, 'direct_file': direct_file, 'active_parts': {}}
    local_parts, last_progress = [], 0.0
    state_lock = threading.RLock()
    cancel = threading.Event()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='backup-part')
    pending = {}

    def record(force=False):
        nonlocal last_progress
        with state_lock:
            now = time.monotonic()
            if force or now - last_progress >= 5:
                progress.update(updated_utc=utc(), elapsed_seconds=round(now - started, 2))
                atomic_json(directory / 'progress.json', progress)
                last_progress = now

    def callback(name):
        def chunk_progress(count, attempt):
            with state_lock:
                progress['active_parts'][name] = {'bytes': count, 'attempt': attempt}
                progress['current_part_bytes'] = sum(value['bytes'] for value in progress['active_parts'].values())
                record()
        return chunk_progress

    def verification_progress(value):
        with state_lock:
            progress.update(value)
            record(True)
        print(json.dumps({'phase': 'verifying', **value}), flush=True)

    record(True)
    try:
        while True:
            if time.monotonic() - started > timeout_seconds:
                raise BackupError('Backup transfer exceeded its configured time limit; rerun to resume')
            for number, future in list(pending.items()):
                if not future.done():
                    continue
                downloaded = future.result()
                metadata = local_parts[number]
                atomic_json(directory / f'part-{number:06d}.json', metadata)
                with state_lock:
                    progress['active_parts'].pop(metadata['name'], None)
                    progress['parts_verified'] += 1
                    progress['bytes_verified'] += metadata['size']
                    progress['downloaded_parts' if downloaded else 'reused_parts'] += 1
                    progress['current_part_bytes'] = sum(value['bytes'] for value in progress['active_parts'].values())
                    record(True)
                    completed_bytes = progress['bytes_verified']
                print(json.dumps({'phase': 'part_verified', 'name': metadata['name'], 'size': metadata['size'],
                                  'reused': not downloaded, 'bytes_verified': completed_bytes}), flush=True)
                del pending[number]
            while len(pending) < workers:
                number = len(local_parts)
                name = f'part-{number:06d}.tarpart'
                marker = remote.metadata(f'part-{number:06d}.json', optional=True)
                if marker is None:
                    break
                metadata = artifact(marker, name)
                local_parts.append(metadata)
                with state_lock:
                    progress['current_part'] = name
                pending[number] = pool.submit(fetch_verified, remote, metadata, directory,
                    progress=callback(name), direct_file=direct_file, cancel=cancel)
            if pending:
                wait(list(pending.values()), timeout=1, return_when=FIRST_COMPLETED)
                continue
            status = remote.metadata('status.json', optional=True)
            if status is not None:
                if status.get('phase') == 'failed':
                    raise BackupError('Remote backup producer reported failure; verified parts retained')
                if status.get('phase') == 'complete':
                    receipt = remote.metadata('receipt.json')
                    remote_parts, manifest = validate_receipt(receipt)
                    sidecars = validate_sidecars(receipt, manifest)
                    if remote_parts != local_parts:
                        raise BackupError('Final receipt differs from finalized part markers')
                    atomic_json(directory / 'receipt.json', receipt)
                    progress.update(phase='manifest', current_part='manifest.jsonl', current_part_bytes=0)
                    record(True)
                    fetch_verified(remote, manifest, directory, progress=callback(manifest['name']), direct_file=direct_file)
                    progress['active_parts'].clear()
                    for metadata in sidecars:
                        progress.update(phase='metadata', current_part=metadata['name'], current_part_bytes=0)
                        record(True)
                        fetch_verified(remote, metadata, directory, progress=callback(metadata['name']), direct_file=direct_file)
                        progress['active_parts'].clear()
                    progress.update(phase='verifying', current_part_bytes=0)
                    record(True)
                    print(json.dumps({'phase': 'verifying', 'parts': len(local_parts)}), flush=True)
                    report = verify(directory, receipt, progress=verification_progress)
                    atomic_json(directory / 'verification.json', report)
                    progress.update(phase='verified', current_part=None)
                    record(True)
                    print(json.dumps(report), flush=True)
                    return report
                if status.get('phase') != 'capturing':
                    raise BackupError('Unknown producer phase')
            record(True)
            time.sleep(poll_seconds)
    except BaseException as exc:
        cancel.set()
        pool.shutdown(wait=True, cancel_futures=True)
        progress.update(phase='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                        error_type=type(exc).__name__)
        record(True)
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    transfer = commands.add_parser('pull')
    transfer.add_argument('--host', required=True)
    transfer.add_argument('--remote-root', required=True)
    transfer.add_argument('--destination', type=Path, required=True)
    transfer.add_argument('--poll-seconds', type=float, default=5)
    transfer.add_argument('--timeout-seconds', type=float, default=172800)
    transfer.add_argument('--workers', type=int, choices=range(1, 5), default=1)
    transfer.add_argument('--direct-file', action='store_true', help='SSH writes directly to disk, then SHA-256 verifies it')
    transfer.add_argument('--ssh-executable', default='ssh')
    transfer.add_argument('--ssh-config', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'pull':
            if not 1 <= args.poll_seconds <= 60 or args.timeout_seconds <= 0:
                raise BackupError('Invalid polling interval or timeout')
            pull(args.host, args.remote_root, args.destination,
                 poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds,
                 workers=args.workers, direct_file=args.direct_file,
                 ssh_executable=args.ssh_executable, ssh_config=args.ssh_config)
        else:
            result = verify(args.destination, progress=lambda value: print(json.dumps({'phase': 'verifying', **value}), flush=True))
            atomic_json(args.destination / 'verification.json', result)
            print(json.dumps(result), flush=True)
    except (OSError, BackupError, ValueError, tarfile.TarError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({'phase': 'failed', 'error_type': type(exc).__name__, 'error': str(exc)[:400]}), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
