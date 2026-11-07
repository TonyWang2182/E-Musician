"""Synthetic archive/transport checks; never connects to the cloud."""
from contextlib import contextmanager
import hashlib
import io
import itertools
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/cloud'))
import pull_full_backup as backup

BASE = 'root/autodl-tmp/emusician'


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def artifact(name, data):
    return {'name': name, 'size': len(data), 'sha256': checksum(data)}


def build_tar(entries):
    stream, lines = io.BytesIO(), []
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for kind, name, content in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if kind == 'dir' else 0o644
            member.type = {'file': tarfile.REGTYPE, 'dir': tarfile.DIRTYPE,
                           'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE}[kind]
            member.linkname = content if kind in {'symlink', 'hardlink'} else ''
            member.size = len(content) if kind == 'file' else 0
            archive.addfile(member, io.BytesIO(content) if kind == 'file' else None)
            entry = {'name': name, 'type': kind, 'size': member.size,
                     'mode': member.mode, 'linkname': member.linkname}
            if kind == 'file':
                entry['sha256'] = checksum(content)
            lines.append(entry)
    return stream.getvalue(), lines


def write_archive(directory, data, entries, split=333):
    parts = []
    for number, offset in enumerate(range(0, len(data), split)):
        name = f'part-{number:06d}.tarpart'
        content = data[offset:offset + split]
        (directory / name).write_bytes(content)
        parts.append(artifact(name, content))
    manifest = b''.join(json.dumps(entry).encode() + b'\n' for entry in entries)
    (directory / 'manifest.jsonl').write_bytes(manifest)
    receipt = {'schema': 2, 'parts': parts, 'manifest': artifact('manifest.jsonl', manifest), 'summary': {}}
    (directory / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    return receipt


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def standard(self):
        return build_tar([
            ('dir', BASE, b''), ('dir', BASE + '/envs', b''),
            ('file', BASE + '/envs/data', b'actual environment bytes\0' * 57),
            ('hardlink', BASE + '/envs/shared', BASE + '/envs/data'),
            ('symlink', BASE + '/envs/current', 'data'),
            ('symlink', BASE + '/envs/python', '/root/miniconda3/bin/python3.12'),
            ('file', 'root/miniconda3/bin/python3.12', b'fixture executable')])

    def test_streams_across_part_boundaries_and_preserves_link_metadata(self):
        data, entries = self.standard()
        receipt = write_archive(self.directory, data, entries)
        report = backup.verify(self.directory, receipt)
        self.assertEqual(report['members'], {'file': 2, 'dir': 2, 'symlink': 2, 'hardlink': 1})
        self.assertEqual(report['raw_tar_sha256'], checksum(data))
        self.assertFalse(report['extracted'])
        self.assertFalse(report['restore_tested'])
        self.assertFalse(list(self.directory.glob('*.partial')))
        self.assertFalse((self.directory / 'root').exists())

    def test_detects_part_corruption(self):
        data, entries = self.standard()
        receipt = write_archive(self.directory, data, entries)
        part = self.directory / receipt['parts'][-1]['name']
        content = part.read_bytes()
        part.write_bytes(b'x' + content[1:])
        with self.assertRaises(backup.BackupError):
            backup.verify(self.directory, receipt)

    def test_file_hash_detects_content_change_even_with_updated_part_hashes(self):
        data, entries = self.standard()
        data = data.replace(b'actual environment bytes', b'altered environment byte', 1)
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'file checksum'):
            backup.verify(self.directory, receipt)

    def test_detects_manifest_metadata_mismatch(self):
        data, entries = self.standard()
        entries[2]['mode'] = 0o777
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'metadata differs'):
            backup.verify(self.directory, receipt)

    def test_rejects_hidden_tar_tail_even_with_valid_part_hashes(self):
        data, entries = self.standard()
        receipt = write_archive(self.directory, data + b'hidden payload', entries)
        with self.assertRaisesRegex(backup.BackupError, 'Nonzero data'):
            backup.verify(self.directory, receipt)

    def test_rejects_extra_manifest_entry(self):
        data, entries = self.standard()
        entries.append(dict(entries[2]))
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'absent from'):
            backup.verify(self.directory, receipt)

    def test_rejects_duplicate_archive_member(self):
        data, entries = build_tar([('file', BASE + '/duplicate', b'a'),
                                   ('file', BASE + '/duplicate', b'b')])
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'Duplicate tar'):
            backup.verify(self.directory, receipt)

    def test_rejects_escaping_symlink(self):
        data, entries = build_tar([('symlink', BASE + '/outside', '/etc/passwd')])
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'outside permitted'):
            backup.verify(self.directory, receipt)

    def test_rejects_hardlink_to_missing_file(self):
        data, entries = build_tar([('hardlink', BASE + '/link', BASE + '/missing')])
        receipt = write_archive(self.directory, data, entries)
        with self.assertRaisesRegex(backup.BackupError, 'earlier regular file'):
            backup.verify(self.directory, receipt)

    def test_rejects_missing_second_tar_end_block(self):
        data, entries = build_tar([('file', BASE + '/data', b'a')])
        # Header + padded content + only one zero end block.
        receipt = write_archive(self.directory, data[:1536], entries)
        with self.assertRaisesRegex(backup.BackupError, 'second end block'):
            backup.verify(self.directory, receipt)

    def test_verifies_optional_sidecars_and_rejects_corruption(self):
        data, entries = self.standard()
        receipt = write_archive(self.directory, data, entries)
        sidecar = b'{"fixture":true}\n'
        (self.directory / 'inventory.json').write_bytes(sidecar)
        receipt['metadata'] = {'manifest.jsonl': receipt['manifest'],
                               'inventory.json': artifact('inventory.json', sidecar)}
        updates = []
        report = backup.verify(self.directory, receipt, progress=updates.append)
        self.assertEqual(report['sidecars_verified'], ['inventory.json'])
        self.assertEqual(updates[0]['members_verified'], 0)
        self.assertEqual(updates[-1]['members_verified'], len(entries))
        (self.directory / 'inventory.json').write_bytes(b'changed')
        with self.assertRaisesRegex(backup.BackupError, 'Sidecar checksum'):
            backup.verify(self.directory, receipt)

    def test_sidecar_limit_and_conflicting_manifest_are_rejected(self):
        data, entries = self.standard()
        receipt = write_archive(self.directory, data, entries)
        receipt['metadata'] = {'inventory.json': {'name': 'inventory.json',
            'size': backup.SIDECAR_LIMIT + 1, 'sha256': 'a' * 64}}
        with self.assertRaisesRegex(backup.BackupError, 'Invalid artifact'):
            backup.verify(self.directory, receipt)
        receipt['metadata'] = {'manifest.jsonl': dict(receipt['manifest'], sha256='a' * 64)}
        with self.assertRaisesRegex(backup.BackupError, 'Conflicting manifest'):
            backup.verify(self.directory, receipt)


class FakeRemote:
    def __init__(self, files, metadata=None, failures=0):
        self.files, self.values, self.failures = files, metadata or {}, failures
        self.calls = 0

    @contextmanager
    def stream(self, name, **kwargs):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            class Disconnected(io.BytesIO):
                def read(self, size=-1):
                    if self.tell():
                        raise OSError('synthetic disconnect')
                    return super().read(3)
            yield Disconnected(self.files[name])
        else:
            yield io.BytesIO(self.files[name])

    def metadata(self, name, *, optional=False):
        if optional:
            return self.values.get(name)
        return self.values[name]


class DirectRemote(FakeRemote):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def download_to(self, metadata, pending, *, progress=None, cancel=None):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            fail = self.failures > 0
            if fail:
                self.failures -= 1
        try:
            time.sleep(.03)
            if cancel is not None and cancel.is_set():
                raise backup.BackupError('synthetic cancellation')
            data = self.files[metadata['name']]
            pending.write_bytes(data[:3] if fail else data)
            if fail:
                raise OSError('synthetic direct disconnect')
            if progress:
                progress(len(data))
        finally:
            with self.lock:
                self.active -= 1


class ResumingRemote(FakeRemote):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.offsets = []
        self.bytes_sent = 0

    def download_to(self, metadata, pending, *, progress=None, cancel=None):
        self.calls += 1
        offset = pending.stat().st_size if pending.exists() else 0
        self.offsets.append(offset)
        data = self.files[metadata['name']][offset:]
        fail = self.failures > 0
        if fail:
            self.failures -= 1
            data = data[:3]
        with pending.open('ab') as output:
            output.write(data)
        self.bytes_sent += len(data)
        if fail:
            raise OSError('synthetic suffix disconnect')
        if progress:
            progress(pending.stat().st_size)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.name = 'part-000000.tarpart'
        self.content = b'nonempty finalized part data'
        self.meta = artifact(self.name, self.content)

    def tearDown(self):
        self.temp.cleanup()

    def test_retries_disconnect_and_publishes_only_verified_part(self):
        remote = FakeRemote({self.name: self.content}, failures=1)
        self.assertTrue(backup.fetch_verified(remote, self.meta, self.directory))
        self.assertEqual(remote.calls, 2)
        self.assertEqual((self.directory / self.name).read_bytes(), self.content)
        self.assertFalse((self.directory / (self.name + '.partial')).exists())

    def test_failed_download_retains_only_partial_and_stops_after_three(self):
        remote = FakeRemote({self.name: self.content}, failures=3)
        with self.assertRaises(OSError):
            backup.fetch_verified(remote, self.meta, self.directory)
        self.assertEqual(remote.calls, 3)
        self.assertFalse((self.directory / self.name).exists())
        self.assertTrue((self.directory / (self.name + '.partial')).exists())

    def test_reuses_only_hash_verified_part(self):
        (self.directory / self.name).write_bytes(self.content)
        remote = FakeRemote({})
        self.assertFalse(backup.fetch_verified(remote, self.meta, self.directory))
        self.assertEqual(remote.calls, 0)
        (self.directory / self.name).write_bytes(b'corrupt')
        with self.assertRaisesRegex(backup.BackupError, 'Existing local artifact'):
            backup.fetch_verified(remote, self.meta, self.directory)
        self.assertEqual(remote.calls, 0)

    def test_bad_payload_is_never_published(self):
        remote = FakeRemote({self.name: b'x' * len(self.content)})
        with self.assertRaisesRegex(backup.BackupError, 'checksum'):
            backup.fetch_verified(remote, self.meta, self.directory)
        self.assertEqual(remote.calls, 3)
        self.assertFalse((self.directory / self.name).exists())

    def test_full_pull_and_resume_without_network_part_downloads(self):
        raw, entries = build_tar([('file', BASE + '/fixture', b'complete data')])
        with tempfile.TemporaryDirectory() as staging:
            stage = Path(staging)
            receipt = write_archive(stage, raw, entries, split=4096)
            sidecar = b'{"test_system":true}\n'
            (stage / 'system.json').write_bytes(sidecar)
            receipt['metadata'] = {'manifest.jsonl': receipt['manifest'],
                                   'system.json': artifact('system.json', sidecar)}
            files = {p.name: p.read_bytes() for p in stage.iterdir()}
        values = {f'part-{i:06d}.json': part for i, part in enumerate(receipt['parts'])}
        values.update({'status.json': {'phase': 'complete'}, 'receipt.json': receipt})
        first = FakeRemote(files, values)
        with patch.object(backup, 'Remote', return_value=first), patch('sys.stdout', new=io.StringIO()):
            report = backup.pull('fixture', '/root/autodl-tmp/emusician/exports/fixture', self.directory)
        self.assertEqual(report['phase'], 'verified')
        self.assertEqual(first.calls, len(receipt['parts']) + 2)
        self.assertEqual(report['sidecars_verified'], ['system.json'])
        second = FakeRemote({}, values)
        with patch.object(backup, 'Remote', return_value=second), patch('sys.stdout', new=io.StringIO()):
            backup.pull('fixture', '/root/autodl-tmp/emusician/exports/fixture', self.directory)
        self.assertEqual(second.calls, 0)
        progress = json.loads((self.directory / 'progress.json').read_text())
        self.assertEqual(progress['phase'], 'verified')
        self.assertEqual(progress['reused_parts'], len(receipt['parts']))

    def test_remote_failure_does_not_claim_complete(self):
        remote = FakeRemote({}, {'status.json': {'phase': 'failed'}})
        with patch.object(backup, 'Remote', return_value=remote):
            with self.assertRaisesRegex(backup.BackupError, 'producer reported failure'):
                backup.pull('fixture', '/root/autodl-tmp/emusician/exports/fixture', self.directory)
        self.assertEqual(json.loads((self.directory / 'progress.json').read_text())['phase'], 'failed')
        self.assertFalse((self.directory / 'verification.json').exists())

    def test_direct_download_retries_and_checks_sha_before_publish(self):
        remote = DirectRemote({self.name: self.content}, failures=1)
        self.assertTrue(backup.fetch_verified(remote, self.meta, self.directory, direct_file=True))
        self.assertEqual(remote.calls, 2)
        self.assertEqual((self.directory / self.name).read_bytes(), self.content)

    def test_direct_bad_hash_never_publishes(self):
        remote = DirectRemote({self.name: b'x' * len(self.content)})
        with self.assertRaisesRegex(backup.BackupError, 'checksum'):
            backup.fetch_verified(remote, self.meta, self.directory, direct_file=True)
        self.assertEqual(remote.calls, 3)
        self.assertFalse((self.directory / self.name).exists())

    def test_four_workers_overlap_and_verify_the_ordered_archive(self):
        raw, entries = build_tar([('file', BASE + '/fixture', b'complete data')])
        with tempfile.TemporaryDirectory() as staging:
            stage = Path(staging)
            receipt = write_archive(stage, raw, entries, split=2048)
            files = {p.name: p.read_bytes() for p in stage.iterdir()}
        values = {f'part-{i:06d}.json': part for i, part in enumerate(receipt['parts'])}
        values.update({'status.json': {'phase': 'complete'}, 'receipt.json': receipt})
        remote = DirectRemote(files, values)
        with patch.object(backup, 'Remote', return_value=remote), patch('sys.stdout', new=io.StringIO()):
            result = backup.pull('fixture', '/root/autodl-tmp/emusician/exports/fixture',
                                 self.directory, workers=4, direct_file=True)
        self.assertEqual(result['phase'], 'verified')
        self.assertGreaterEqual(remote.peak, 2)
        self.assertLessEqual(remote.peak, 4)
        progress = json.loads((self.directory / 'progress.json').read_text())
        self.assertEqual(progress['parts_verified'], len(receipt['parts']))
        self.assertEqual(progress['bytes_verified'], len(raw))
        self.assertEqual(progress['active_parts'], {})

    def test_remote_builds_explicit_client_config_without_shell_interpolation(self):
        remote = backup.Remote('fixture', '/root/autodl-tmp/emusician/exports/fixture',
                               executable='C:/Program Files/Git/usr/bin/ssh.exe', config='E:/with spaces/ssh_config')
        command = remote.command(self.name)
        self.assertEqual(command[:3], ['C:/Program Files/Git/usr/bin/ssh.exe', '-F', 'E:/with spaces/ssh_config'])
        self.assertEqual(command[-2], 'fixture')

    def test_interrupted_prefix_resumes_without_resending_verified_prefix(self):
        pending = self.directory / (self.name + '.partial')
        pending.write_bytes(self.content[:9])
        remote = ResumingRemote({self.name: self.content})
        self.assertTrue(backup.fetch_verified(remote, self.meta, self.directory, direct_file=True))
        self.assertEqual(remote.offsets, [9])
        self.assertEqual(remote.bytes_sent, len(self.content) - 9)
        self.assertEqual((self.directory / self.name).read_bytes(), self.content)

    def test_disconnect_preserves_downloaded_prefix_for_next_attempt(self):
        remote = ResumingRemote({self.name: self.content}, failures=1)
        backup.fetch_verified(remote, self.meta, self.directory, direct_file=True)
        self.assertEqual(remote.offsets, [0, 3])
        self.assertEqual(remote.bytes_sent, len(self.content))

    def test_corrupt_prefix_requires_full_hash_failure_then_fresh_retry(self):
        pending = self.directory / (self.name + '.partial')
        pending.write_bytes(b'corrupt!!')
        remote = ResumingRemote({self.name: self.content})
        backup.fetch_verified(remote, self.meta, self.directory, direct_file=True)
        self.assertEqual(remote.offsets, [9, 0])
        self.assertEqual(remote.bytes_sent, 2 * len(self.content) - 9)
        self.assertEqual((self.directory / self.name).read_bytes(), self.content)

    def test_resume_command_uses_validated_byte_offset(self):
        remote = backup.Remote('fixture', '/root/autodl-tmp/emusician/exports/fixture')
        command = remote.command(self.name, offset=12345)
        self.assertIn('iflag=skip_bytes skip=12345', command[-1])
        for invalid in (-1, '1; command', True):
            with self.assertRaises(backup.BackupError):
                remote.command(self.name, offset=invalid)

    def test_stalled_direct_transfer_kills_only_owned_child_and_keeps_prefix(self):
        pending = self.directory / (self.name + '.partial')
        pending.write_bytes(self.content[:5])
        remote = backup.Remote('fixture', '/root/autodl-tmp/emusician/exports/fixture')
        class Process:
            returncode = None
            killed = False
            def poll(self):
                return self.returncode
            def kill(self):
                self.killed = True
                self.returncode = -1
            def wait(self, timeout=None):
                return self.returncode
        process = Process()
        ticks = itertools.count(0, 100)
        with patch.object(backup.subprocess, 'Popen', return_value=process), \
                patch.object(backup.time, 'monotonic', side_effect=lambda: next(ticks)), \
                patch.object(backup.time, 'sleep'):
            with self.assertRaisesRegex(backup.BackupError, 'no byte progress'):
                remote.download_to(self.meta, pending)
        self.assertTrue(process.killed)
        self.assertEqual(pending.read_bytes(), self.content[:5])


if __name__ == '__main__':
    unittest.main()
