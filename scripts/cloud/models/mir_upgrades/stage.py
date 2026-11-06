"""Cloud-only pinned MIR upgrade assets. Does not enable a provider or run inference."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')
SPECS = {
    'scnet': {'repo': 'ZFTurbo/Music-Source-Separation-Training',
              'revision': 'a8a862231de29e6832a26c590e5c29f82f736f66', 'task': 'separate',
              'weight': 'model_scnet_ep_36_sdr_10.0891.ckpt', 'bytes': 214063778,
              'weight_sha256': 'ac25975f0f5704f3d1a3c3c251505b7a0f417a22eafe82773440ee4f7e14b74f',
              'release': 'v1.0.15', 'config': 'config_musdb18_scnet_xl_more_wide_v5.yaml',
              'config_sha256': '54ddcb8aeeae85c8d0e148741e7d87b0fbd38bd21cffa5d59ba124fe1e672f40'},
    'transkun': {'repo': 'Yujia-Yan/Transkun', 'revision': 'c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6',
                 'task': 'piano_transcription', 'weight': 'transkun/pretrained/2.0.pt', 'bytes': 56408978,
                 'git_blob': '42183f2e0ce08017b74675a2ccf9f2e88732dfc9'},
    'chordmini': {'repo': 'ptnghia-j/ChordMini', 'revision': 'aa6e3a8d7b017f082fd2aaff9329d5c26af49c03',
                  'task': 'chords', 'weight': 'checkpoints/btc_model_best.pth', 'bytes': 35942692,
                  'git_blob': 'a691af56aec01fcd52d3bd46992f96bb9874ee59'},
}


def hashes(path):
    sha = hashlib.sha256()
    git = hashlib.sha1(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk); git.update(chunk)
    return sha.hexdigest(), git.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def download(url, path, *, size=None, sha=None, git=None, maximum=256 * 1024 * 1024):
    path.parent.mkdir(parents=True, exist_ok=True)
    def valid():
        if not path.is_file() or (size is not None and path.stat().st_size != size):
            return False
        actual, blob = hashes(path)
        return (not sha or sha == actual) and (not git or git == blob)
    if path.exists():
        if not valid():
            raise ValueError(f'Existing asset differs, refusing overwrite: {path}')
    else:
        partial = path.with_suffix(path.suffix + '.partial')
        for attempt in range(2):
            try:
                started = time.monotonic()
                request = urllib.request.Request(url, headers={'User-Agent': 'E-musician-cloud-model-evaluation'})
                with urllib.request.urlopen(request, timeout=90) as response, partial.open('wb') as stream:
                    count = 0
                    while block := response.read(1024 * 1024):
                        count += len(block)
                        if count > maximum or time.monotonic() - started > 1200:
                            raise TimeoutError('Bounded asset transfer exceeded limit')
                        stream.write(block)
                partial.replace(path)
                if not valid():
                    raise ValueError(f'Download integrity mismatch: {path}')
                break
            except (TimeoutError, OSError):
                if attempt == 1:
                    raise
                time.sleep(2)
    digest, blob = hashes(path)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest,
            'git_blob': blob, 'url': url}


def main():
    if sys.platform != 'linux' or not ROOT.is_dir():
        raise RuntimeError('This downloader runs only on the authorized cloud data disk')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id', choices=SPECS)
    args = parser.parse_args()
    spec = SPECS[args.id]
    source = ROOT / 'workspace/models' / (args.id + '-' + spec['revision'])
    model = ROOT / 'models' / args.id / spec['revision']
    manifest = ROOT / 'manifests/model-library' / args.id / 'deployment.json'
    tree_url = f'https://api.github.com/repos/{spec["repo"]}/git/trees/{spec["revision"]}?recursive=1'
    with urllib.request.urlopen(tree_url, timeout=90) as response:
        tree = json.load(response)
    if tree.get('truncated') or tree.get('sha') != spec['revision']:
        raise ValueError('Pinned repository tree is incomplete or mismatched')
    allowed_suffixes = {'.py', '.yaml', '.yml', '.toml', '.conf'}
    files = [item for item in tree['tree'] if item['type'] == 'blob' and (
        Path(item['path']).suffix in allowed_suffixes or item['path'] in ('README.md', 'LICENSE', 'requirements.txt'))]
    if len(files) > 600 or sum(item.get('size', 0) for item in files) > 32 * 1024 * 1024:
        raise ValueError('Source selection exceeds staging bounds')
    def get_source(item):
        path = (source / item['path']).resolve()
        if not path.is_relative_to(source.resolve()):
            raise ValueError('Unsafe source path')
        url = f'https://raw.githubusercontent.com/{spec["repo"]}/{spec["revision"]}/{item["path"]}'
        return download(url, path, size=item['size'], git=item['sha'], maximum=8 * 1024 * 1024)
    with ThreadPoolExecutor(max_workers=6) as pool:
        artifacts = list(pool.map(get_source, files))
    print(json.dumps({'id': args.id, 'source_files_verified': len(artifacts)}), flush=True)
    if args.id == 'scnet':
        base = f'https://github.com/{spec["repo"]}/releases/download/{spec["release"]}'
        artifacts.append(download(f'{base}/{spec["config"]}', model / spec['config'],
                                  size=5906, sha=spec['config_sha256']))
        url = f'{base}/{spec["weight"]}'
    else:
        url = f'https://raw.githubusercontent.com/{spec["repo"]}/{spec["revision"]}/{spec["weight"]}'
    weight = download(url, model / Path(spec['weight']).name, size=spec['bytes'],
                      sha=spec.get('weight_sha256'), git=spec.get('git_blob'))
    artifacts.append(weight)
    value = {'schema_version': 1, 'id': args.id, 'task': spec['task'],
             'source_revision': spec['revision'], 'source_url': 'https://github.com/' + spec['repo'],
             'model_revisions': {'revision': spec.get('release', spec['revision']), 'sha256': weight['sha256']},
             'paths': {'model': str(model), 'environment': str(ROOT / 'envs' / args.id), 'source': str(source)},
             'checks': {'files_verified': True, 'environment_verified': False,
                        'cpu_load_verified': False, 'gpu_inference_verified': False},
             'daw_connected': False, 'blockers': ['environment installation', 'CPU load validation',
                'serialized GPU inference validation', 'DAW integration not authorized in this phase'],
             'artifacts': artifacts, 'scope': 'private cloud evaluation; no local weight/audio copy'}
    save(manifest, value)
    print(json.dumps({'id': args.id, 'weight_bytes': weight['bytes'], 'weight_sha256': weight['sha256'],
                      'manifest': str(manifest)}), flush=True)


if __name__ == '__main__':
    main()
