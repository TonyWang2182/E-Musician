"""Bounded compatibility probe. Does NOT verify the whole backup."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts' / 'cloud'))
import pull_full_backup as backup

directory = Path('E:/MusicAgent&DAW/cloud-inference/backups/full-20261107T080330Z')
with (directory / 'manifest.jsonl').open(encoding='utf-8') as source:
    entry = json.loads(source.readline())
with tarfile.open(directory / 'part-000000.tarpart', mode='r|') as archive:
    member = next(iter(archive))
assert entry['type'] == 'dir' and member.isdir()
assert entry['name'] == member.name
assert entry['mode'] == 16832 and member.mode == 448
assert backup.manifest_mode(entry['mode'], 'dir') == member.mode
report = {
    'checked_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'first manifest entry and first tar header only',
    'status': 'passed',
    'manifest_mode': entry['mode'],
    'tar_header_mode': member.mode,
    'normalized_mode': backup.manifest_mode(entry['mode'], 'dir'),
    'verifier_sha256': hashlib.sha256(Path(backup.__file__).read_bytes()).hexdigest(),
    'full_backup_verified': False,
    'quark_copy_read': False,
    'restore_tested': False,
}
output = Path(__file__).with_name('FIRST-HEADER.json')
output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
