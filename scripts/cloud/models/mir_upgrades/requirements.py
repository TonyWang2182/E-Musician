"""Write isolated inference dependency inputs, preserving the existing runtime pins."""
import argparse
from pathlib import Path

ROOT = Path('/root/autodl-tmp/emusician')
parser = argparse.ArgumentParser()
parser.add_argument('id', choices=('scnet', 'transkun', 'chordmini'))
args = parser.parse_args()
# Immutable coordinates only: never run pip in the existing base MIR / ACE environment.
base = (ROOT / 'workspace/mir-stage/torch.in').read_text().splitlines()
lines = [line for line in base if line.startswith(('torch @ ', 'torchaudio @ ', 'nvidia-'))]
lines += ['numpy==1.26.4', 'scipy==1.13.1', 'soundfile==0.13.1', 'psutil==7.1.0']
specific = {
    'scnet': ['PyYAML==6.0.3', 'ml-collections==1.1.0', 'loralib==0.1.2', 'tqdm==4.70.1'],
    'transkun': ['setuptools==80.9.0', 'ncls==0.0.71', 'pretty-midi==0.2.11.post0',
                'mir-eval==0.8.2', 'pydub==0.25.1', 'seaborn==0.13.2', 'matplotlib==3.10.1',
                'tensorboard==2.20.0', 'tqdm==4.70.1', 'torch-optimizer==0.3.0',
                'sox==1.5.0', 'soxr==1.1.0', 'moduleconf==0.1.4'],
    'chordmini': ['PyYAML==6.0.2', 'setuptools==80.9.0', 'librosa==0.10.1',
                 'tqdm==4.67.1', 'matplotlib==3.10.1', 'mir-eval==0.8.2',
                 'seaborn==0.13.2', 'scikit-learn==1.6.1'],
}
lines += specific[args.id]
folder = ROOT / 'manifests/model-library' / args.id
folder.mkdir(parents=True, exist_ok=True)
(folder / 'requirements.in').write_text('\n'.join(lines) + '\n')
print(f'{args.id}: explicit dependency input written')
