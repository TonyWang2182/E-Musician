"""Build explicit MIR requirements using existing ACE artifact pins, without mutating ACE."""
import hashlib
import json
from pathlib import Path
import tomllib
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')
SOURCE = ROOT / 'workspace/third_party/ACE-Step-1.5-ca1e85fe9430179831e6bc6be790c332190a3866'
lock = tomllib.loads((SOURCE / 'uv.lock').read_text())
assets = json.loads((ROOT / 'manifests/mir-stage-assets.json').read_text())
torch = []
for name in ('torch', 'torchaudio'):
    package = next(p for p in lock['package'] if p['name'] == name and p['version'] == '2.10.0+cu128')
    wheel = next(w for w in package['wheels'] if 'cp312-cp312-manylinux_2_28_x86_64' in w['url'])
    torch.append(f'{name} @ {wheel["url"]}#{wheel["hash"].replace(":", "=", 1)}')
for wheel in sorted((ROOT / 'cache/wheels').glob('nvidia_*.whl')):
    digest = hashlib.file_digest(wheel.open('rb'), 'sha256').hexdigest()
    name = wheel.name.split('-')[0].replace('_', '-')
    torch.append(f'{name} @ {wheel.as_uri()}#sha256={digest}')
source = next(item for item in assets['files'] if item['path'].startswith('sources/beat-this-'))
torch.extend([
    f'beat-this @ {(ROOT / source["path"]).as_uri()}#sha256={source["sha256"]}',
    'demucs==4.1.0', 'numpy==1.26.4', 'scipy==1.13.1', 'soundfile==0.13.1',
    'psutil==7.1.0', 'einops==0.8.2', 'rotary-embedding-torch==0.6.4',
    'soxr==0.3.7', 'safetensors==0.8.0', 'julius==0.2.8', 'sphn==0.2.1',
    'lameenc==1.9.0', 'tqdm==4.70.1', 'setuptools==75.8.2',
])
transcription = [
    'setuptools==75.8.2', 'numpy==1.26.4', 'scipy==1.13.1', 'soundfile==0.13.1',
    'onnxruntime==1.20.1', 'librosa==0.10.2.post1', 'mir-eval==0.8.2',
    'pretty-midi==0.2.11.post0', 'resampy==0.4.2', 'scikit-learn==1.7.2',
    'psutil==7.1.0', 'typing-extensions==4.16.0',
]
for name, lines in (('torch', torch), ('transcription', transcription)):
    (ROOT / f'workspace/mir-stage/{name}.in').write_text('\n'.join(lines) + '\n')
with urllib.request.urlopen('https://pypi.org/pypi/basic-pitch/0.4.0/json', timeout=60) as response:
    package = json.load(response)
wheel = next(file for file in package['urls'] if file['filename'].endswith('-py2.py3-none-any.whl') or file['filename'].endswith('-py3-none-any.whl'))
url = wheel['url'].replace('https://files.pythonhosted.org/', 'https://mirrors.aliyun.com/pypi/')
(ROOT / 'manifests/mir-basic-pitch-overlay.lock.txt').write_text(
    f'basic-pitch @ {url} --hash=sha256:{wheel["digests"]["sha256"]}\n')
print('Generated isolated MIR requirement inputs; immutable ACE wheel pins reused.')
