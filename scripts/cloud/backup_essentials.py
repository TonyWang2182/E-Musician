"""Prioritize small recovery metadata while the full environment backup transfers."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

PREFIX = 'root/autodl-tmp/emusician/'


def create(directory):
    receipt = json.loads((directory / 'receipt.json').read_text())
    manifest = directory / 'manifest.jsonl'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != receipt['manifest']['sha256']:
        raise ValueError('Source manifest hash mismatch')
    target = directory / 'recovery-essentials.zip'
    entries, links = [], []
    selected = tuple(PREFIX + name + '/' for name in ('manifests', 'deployments', 'tools', 'sources'))
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        with manifest.open(encoding='utf-8') as lines:
            for line in lines:
                entry = json.loads(line)
                name = entry['name']
                database = name in {PREFIX + 'state/compute.sqlite3', PREFIX + 'state/generation.sqlite3'}
                wanted = name.startswith(selected) or database or name.endswith('/pyvenv.cfg')
                if not wanted:
                    continue
                if entry['type'] in {'symlink', 'hardlink'}:
                    links.append(entry)
                    continue
                if entry['type'] != 'file':
                    continue
                if entry['size'] > 16 * 1024 * 1024:
                    raise ValueError('Unexpectedly large recovery metadata: ' + name)
                path = (directory / 'database-snapshots' / Path(name).name) if database else Path('/') / name
                payload = path.read_bytes()
                if len(payload) != entry['size'] or hashlib.sha256(payload).hexdigest() != entry['sha256']:
                    raise ValueError('Recovery source changed since snapshot: ' + name)
                archive.writestr(name, payload)
                entries.append(entry)
        archive.writestr('ESSENTIALS-MANIFEST.json', json.dumps({'files': entries, 'links': links,
            'scope': 'Recovery configuration and queue snapshots ONLY; no full model weights/environments',
            'full_backup': directory.name}, indent=2))
    result = {'name': target.name, 'size': target.stat().st_size,
              'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'files': len(entries)}
    target.with_suffix('.receipt.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


def verify(path):
    receipt = json.loads(path.with_suffix('.receipt.json').read_text())
    if path.stat().st_size != receipt['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
        raise ValueError('Essentials archive hash mismatch')
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('ESSENTIALS-MANIFEST.json'))
        expected = {entry['name']: entry for entry in manifest['files']}
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate zip members')
        if set(archive.namelist()) != set(expected) | {'ESSENTIALS-MANIFEST.json'}:
            raise ValueError('Essentials member set mismatch')
        for name, entry in expected.items():
            payload = archive.read(name)  # zipfile also verifies CRC.
            if len(payload) != entry['size'] or hashlib.sha256(payload).hexdigest() != entry['sha256']:
                raise ValueError('Essentials member hash mismatch')
    result = {'phase': 'verified', 'scope': manifest['scope'], **receipt}
    path.with_suffix('.verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['create', 'verify'])
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    (create if args.action == 'create' else verify)(args.path)
