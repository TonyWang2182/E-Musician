"""Durable idempotent queue and immutable streaming input assets."""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid
from .protocol import (TERMINAL, MAX_ASSET, atomic_json, canonical, digest,
                       identifier, read_json, sha256, validate_request, wav_info)


class Conflict(ValueError):
    pass


class QueueFull(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.state = self.root / 'state'
        self.assets = self.root / 'assets/compute'
        self.jobs = self.root / 'jobs/compute'
        for path in (self.state, self.assets, self.jobs):
            path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.dbpath = self.state / 'compute.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                phase TEXT NOT NULL, error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.dbpath, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.lock, self.connect() as db:
            db.execute("UPDATE jobs SET status='interrupted',phase='interrupted',error=?,updated=? "
                       "WHERE status NOT IN ('ready','failed','cancelled','interrupted')",
                       ('Service restarted; submit a new request ID to retry explicitly.', time.time()))

    def get(self, job_id):
        identifier(job_id)
        with self.lock, self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        import json
        value = dict(row)
        value['job_id'] = value['id']
        value['request'] = json.loads(value['request'])
        value['result'] = json.loads(value['result']) if value['result'] else None
        return value

    def submit(self, request):
        request = validate_request(request)
        encoded = canonical(request); job_id = request['request_id']
        with self.lock, self.connect() as db:
            prior = db.execute('SELECT request FROM jobs WHERE id=?', (job_id,)).fetchone()
            if prior:
                if prior['request'] != encoded:
                    raise Conflict('Request ID already belongs to a different request')
                return self.get(job_id), False
            active = db.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted')").fetchone()[0]
            if active >= 16:
                raise QueueFull('Cloud computation queue is full')
            if 'input' in request:
                self.asset_info(request['input']['sha256'])
            directory = self.jobs / job_id
            directory.mkdir(exist_ok=False)
            atomic_json(directory / 'request.json', request)
            now = time.time()
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)', (job_id, encoded, 'queued', 'queued', None, None, now, now))
        return self.get(job_id), True

    def next_job(self):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='loading',phase='loading',updated=? WHERE id=?", (time.time(), row['id']))
        return self.get(row['id'])

    def update(self, job_id, status, *, result=None, error=None):
        if status not in TERMINAL | {'queued', 'loading', 'running', 'postprocessing', 'cancelling'}:
            raise ValueError('Unknown job state')
        with self.lock, self.connect() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row['status'] in TERMINAL:
                return
            if row['status'] == 'cancelling':
                if status in TERMINAL:
                    status, result, error = 'cancelled', None, None
                else:
                    return
            db.execute('UPDATE jobs SET status=?,phase=?,result=?,error=?,updated=? WHERE id=?',
                       (status, status, canonical(result) if result is not None else None, error, time.time(), job_id))

    def cancel(self, job_id):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (identifier(job_id),)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row['status'] not in TERMINAL:
                status = 'cancelled' if row['status'] == 'queued' else 'cancelling'
                db.execute('UPDATE jobs SET status=?,phase=?,updated=? WHERE id=?', (status, status, time.time(), job_id))
        return self.get(job_id)

    def asset_info(self, content_hash):
        path = self.assets / (sha256(content_hash) + '.wav')
        if not path.is_file() or path.is_symlink():
            raise KeyError(content_hash)
        metadata = read_json(path.with_suffix('.json'), 16384)
        if metadata.get('sha256') != content_hash or metadata.get('bytes') != path.stat().st_size:
            raise ValueError('Stored asset integrity metadata is invalid')
        return metadata

    def upload(self, content_hash, length, stream):
        sha256(content_hash)
        if type(length) is not int or not 44 <= length <= MAX_ASSET:
            raise ValueError('Upload exceeds size budget')
        if shutil.disk_usage(self.assets).free < length + 2 * 1024**3:
            raise ValueError('Insufficient cloud disk reserve for upload')
        temporary = self.assets / (uuid.uuid4().hex + '.partial')
        final = self.assets / (content_hash + '.wav')
        try:
            remaining, hasher = length, hashlib.sha256()
            with temporary.open('xb') as output:
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Upload ended before Content-Length')
                    hasher.update(block); output.write(block); remaining -= len(block)
            if hasher.hexdigest() != content_hash:
                raise ValueError('Uploaded content SHA-256 mismatch')
            metadata = {'sha256': content_hash, **wav_info(temporary)}
            with self.lock:
                if final.exists():
                    if final.is_symlink() or digest(final) != content_hash:
                        raise ValueError('Existing content-addressed asset is corrupt')
                else:
                    temporary.replace(final)
                atomic_json(final.with_suffix('.json'), metadata)
            return metadata
        finally:
            temporary.unlink(missing_ok=True)

    def artifact(self, job_id, artifact_id):
        job = self.get(job_id)
        if job['status'] != 'ready':
            raise Conflict('Artifacts are only published for ready jobs')
        item = next((a for a in job['result']['artifacts'] if a['id'] == artifact_id), None)
        if item is None:
            raise KeyError(artifact_id)
        path = self.jobs / job_id / 'output' / artifact_id
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes']:
            raise ValueError('Published artifact is missing or changed')
        return path, item
