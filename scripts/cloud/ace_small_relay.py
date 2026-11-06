"""Check and relay small pinned model metadata files; leave large transfers alone."""
import concurrent.futures
import hashlib
import json
import subprocess
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path('E:/MusicAgent&DAW/cloud-inference')
TARGET = ROOT / 'models/ace/checkpoints'


def fetch(entry):
    query = urllib.parse.urlencode({'Revision':entry['revision'], 'FilePath':entry['path']})
    url = f"https://modelscope.cn/api/v1/models/{entry['repository']}/repo?{query}"
    with urllib.request.urlopen(url,timeout=30) as stream:
        content = stream.read(entry['size']+1)
    if len(content) != entry['size'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise RuntimeError('Metadata checksum mismatch: '+entry['path'])
    path = TARGET / entry['local_path']
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(content)
    print('checked '+entry['local_path'],flush=True)
    return path


def main():
    entries = json.loads((ROOT/'manifests/ace-model-lock.json').read_text(encoding='utf-8'))['files']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(fetch,[entry for entry in entries if entry['size']<1000000]))
    archive = ROOT / 'manifests/ace-small-files.tar.gz'
    with tarfile.open(archive,'w:gz') as package:
        for path in paths:
            package.add(path,arcname=path.relative_to(TARGET).as_posix(),recursive=False)
    subprocess.run(['scp','-o','BatchMode=yes',str(archive),'emusician-autodl:/root/autodl-tmp/emusician/cache/ace-small-files.tar.gz'],check=True,timeout=60)
    subprocess.run(['ssh','-o','BatchMode=yes','emusician-autodl','tar -xzf /root/autodl-tmp/emusician/cache/ace-small-files.tar.gz -C /root/autodl-tmp/emusician/models/ace/checkpoints'],check=True,timeout=30)
    print('Pinned small metadata relayed.',flush=True)


if __name__ == '__main__':
    main()
