"""Use verified relayed wheels as lockfile transport; versions/hashes unchanged."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/autodl-tmp/emusician')
SOURCE = ROOT / 'workspace/third_party/ACE-Step-1.5-ca1e85fe9430179831e6bc6be790c332190a3866'
manifest = json.loads(ROOT.joinpath('manifests/ace-wheel-relay.json').read_text(encoding='utf-8'))
lock = SOURCE / 'uv.lock'
raw = lock.read_text(encoding='utf-8')
before = hashlib.sha256(raw.encode()).hexdigest()
for wheel in manifest:
    path = ROOT / 'cache/wheels' / wheel['url'].rsplit('/',1)[-1]
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):
            sha.update(block)
    if path.stat().st_size != wheel['size'] or sha.hexdigest() != wheel['hash'].removeprefix('sha256:'):
        raise RuntimeError('Relayed wheel verification failed: '+path.name)
    raw = raw.replace(wheel['url'],path.as_uri())
    raw = raw.replace(wheel['url'].replace('https://files.pythonhosted.org/packages/','https://mirrors.aliyun.com/pypi/packages/'),path.as_uri())
lock.write_text(raw,encoding='utf-8')
record={'reason':'Pinned NVIDIA wheels checked locally and on cloud, relayed over SSH to avoid very slow PyPI streams.',
        'previous_transport_sha256':before,'transport_lock_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'upstream_sha256':hashlib.sha256(SOURCE.joinpath('uv.lock.upstream').read_bytes()).hexdigest(),
        'wheel_count':len(manifest),'versions_hashes_unchanged':True}
ROOT.joinpath('manifests/ace-lock-relay-transport.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
