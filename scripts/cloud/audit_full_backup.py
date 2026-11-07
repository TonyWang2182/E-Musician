"""Audit snapshot scope and small recovery evidence; not full payload validation."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile


def hash_file(path):
    sha = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def main(directory):
    receipt = json.loads((directory / 'receipt.remote.json').read_text())
    pending = directory / 'manifest.jsonl.download'
    manifest = directory / 'manifest.jsonl'
    source = manifest if manifest.exists() else pending
    if source.stat().st_size != receipt['manifest']['size'] or hash_file(source) != receipt['manifest']['sha256']:
        raise ValueError('Manifest download is incomplete or invalid')
    if source == pending:
        pending.replace(manifest)
    for name, entry in receipt['metadata'].items():
        path = directory / name
        if path.stat().st_size != entry['size'] or hash_file(path) != entry['sha256']:
            raise ValueError('Metadata checksum mismatch: ' + name)
    groups = {name: {'files': 0, 'bytes': 0} for name in
              ('ace', 'yue2', 'scnet', 'transkun', 'chordmini', 'muscriptor', 'sheetsage2', 'mert2', 'mir')}
    envs, total = set(), 0
    root = 'root/autodl-tmp/emusician/'
    with manifest.open(encoding='utf-8') as stream:
        for line in stream:
            entry = json.loads(line)
            name = entry['name']
            total += 1
            if name.startswith(root + 'workspace/models/muscriptor/hf/') or Path(name).name in {'token', 'stored_tokens'}:
                raise ValueError('Credential name included unexpectedly')
            if name.startswith(root + 'envs/') and name.endswith('/pyvenv.cfg'):
                envs.add(name.split('/')[4])
            for model, values in groups.items():
                if name.startswith(root + 'models/' + model + '/') and entry['type'] == 'file':
                    values['files'] += 1
                    values['bytes'] += entry['size']
    if total != sum(receipt['summary']['counts'].values()) or len(envs) != 9 or any(v['files'] == 0 for v in groups.values()):
        raise ValueError('Snapshot scope is incomplete')
    links = json.loads((directory / 'links.json').read_text())['links']
    bad_links = [item for item in links if not item['exists'] or not item['inside_backed_roots']]
    if bad_links:
        raise ValueError('Snapshot has unresolved runtime links')
    queues = {}
    # Explicit small SQLite files only; no general archive extraction.
    with zipfile.ZipFile(directory / 'recovery-essentials.zip') as archive, tempfile.TemporaryDirectory(dir=directory) as tmp:
        for name in ('compute.sqlite3', 'generation.sqlite3'):
            data = archive.read(root + 'state/' + name)
            path = Path(tmp) / name
            path.write_bytes(data)
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                result = db.execute('PRAGMA integrity_check').fetchone()[0]
                counts = dict(db.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status').fetchall())
                if result != 'ok' or set(counts) - {'ready', 'failed', 'cancelled', 'interrupted'}:
                    raise ValueError('Invalid queue snapshot')
                queues[name] = {'integrity_check': result, 'terminal_status_counts': counts}
    result = {'phase': 'metadata-and-essentials-verified', 'full_payload_verified': False,
              'members_in_manifest': total, 'models': groups, 'envs': sorted(envs),
              'symbolic_links': len(links), 'unresolved_links': len(bad_links),
              'queues': queues, 'archive_bytes_expected': receipt['summary']['archive_bytes']}
    (directory / 'scope-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
