"""CPU-only snapshot primitives; fixtures use the recorder's E-drive TEMP."""
import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('full_backup', Path(__file__).resolve().parents[1] / 'scripts/cloud/full_backup.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class CaptureTests(unittest.TestCase):
    def test_parts_boundary_and_hash(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            writer = backup.Parts(root, limit=7)
            writer.write(b'123')
            writer.write(b'456789abcdef')
            writer.flush_part()
            self.assertEqual([p['size'] for p in writer.parts], [7, 7, 1])
            self.assertEqual(b''.join((root / p['name']).read_bytes() for p in writer.parts), b'123456789abcdef')
            for part in writer.parts:
                self.assertEqual(backup.digest_file(root / part['name']), part['sha256'])
                self.assertFalse((root / (part['name'] + '.partial')).exists())

    def test_credentials_and_active_state_excluded_but_env_kept(self):
        self.assertTrue(backup.excluded(backup.DATA / 'workspace/models/muscriptor/hf/token'))
        self.assertTrue(backup.excluded(backup.DATA / 'state/compute.pid'))
        self.assertTrue(backup.excluded(backup.DATA / 'state/compute.sqlite3-wal'))
        self.assertFalse(backup.excluded(backup.DATA / 'envs/ace/bin/python'))
        self.assertFalse(backup.excluded(backup.DATA / 'workspace/example/.venv/bin/python'))
        self.assertFalse(backup.excluded(backup.DATA / 'state/compute.sqlite3'))

    def test_wal_commits_in_snapshot(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with closing(sqlite3.connect(root / 'queue.db')) as source:
                source.execute('PRAGMA journal_mode=WAL')
                source.execute('CREATE TABLE jobs (status TEXT)')
                source.execute("INSERT INTO jobs VALUES ('ready')")
                source.commit()
                backup.database_snapshot(root / 'queue.db', root / 'snapshot.db')
                with closing(sqlite3.connect(root / 'snapshot.db')) as restored:
                    self.assertEqual(restored.execute('SELECT status FROM jobs').fetchone()[0], 'ready')

    def test_active_queue_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with closing(sqlite3.connect(root / 'queue.db')) as source:
                source.execute('CREATE TABLE jobs (status TEXT)')
                source.execute("INSERT INTO jobs VALUES ('running')")
                source.commit()
            with self.assertRaisesRegex(RuntimeError, 'Nonterminal'):
                backup.database_snapshot(root / 'queue.db', root / 'snapshot.db')


if __name__ == '__main__':
    unittest.main()
