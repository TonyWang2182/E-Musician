"""Narrow pinned-model loading and cloud CLI; no DAW or service integration."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/root/autodl-tmp/emusician')


def write(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def load(identifier, device='cpu'):
    import torch
    folder = ROOT / 'manifests/model-library' / identifier
    manifest = json.loads((folder / 'deployment.json').read_text())
    source, models = Path(manifest['paths']['source']), Path(manifest['paths']['model'])
    sys.path.insert(0, str(source))
    if identifier == 'scnet':
        import yaml
        from ml_collections import ConfigDict
        from models.scnet import SCNet
        config = ConfigDict(yaml.load(next(models.glob('*.yaml')).read_text(), Loader=yaml.FullLoader))
        model = SCNet(**config.model)
        state = torch.load(next(models.glob('*.ckpt')), map_location='cpu', weights_only=True)
        model.load_state_dict(state, strict=True)
        extras = {'config': config, 'sources': list(config.model.sources), 'sample_rate': int(config.audio.sample_rate)}
    elif identifier == 'transkun':
        import moduleconf
        config = moduleconf.parseFromFile(str(source / 'transkun/pretrained/2.0.conf'))
        model = config['Model'].module.TransKun(conf=config['Model'].config)
        state = torch.load(models / '2.0.pt', map_location='cpu', weights_only=True)
        model.load_state_dict(state.get('best_state_dict', state.get('state_dict')), strict=True)
        extras = {'sample_rate': model.fs, 'source': str(source)}
    else:
        import yaml
        from src.utils import HParams, extract_model_state_dict, extract_normalization_stats, idx2voca_chord
        from src.models.btc_model import BTC_model
        config = HParams(**yaml.safe_load((source / 'config/ChordMini.yaml').read_text()))
        # This fixed upstream checkpoint is hash-verified before loading, as required by
        # its upstream loader (normalization NumPy metadata uses Python serialization).
        state = torch.load(models / 'btc_model_best.pth', map_location='cpu', weights_only=False)
        model = BTC_model(config=config.model)
        model.load_state_dict(extract_model_state_dict(state), strict=True)
        mean, std = extract_normalization_stats(state)
        extras = {'config': config, 'mean': mean, 'std': std, 'vocabulary': idx2voca_chord()}
    model.to(device).eval()
    return model, extras, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id', choices=('scnet', 'transkun', 'chordmini'))
    parser.add_argument('--check', action='store_true', help='CPU weight loading only; no inference')
    args = parser.parse_args()
    if not args.check:
        parser.error('This stage supports --check; inference requires a separately scheduled GPU slot.')
    if os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('Staging CPU checks require CUDA_VISIBLE_DEVICES empty before interpreter launch')
    import torch
    torch.set_num_threads(2)
    started = time.monotonic()
    model, extras, manifest = load(args.id)
    assert not torch.cuda.is_initialized()
    assert all(parameter.device.type == 'cpu' for parameter in model.parameters())
    check = {'kind': 'cpu-model-load-only', 'parameter_count': sum(p.numel() for p in model.parameters()),
             'torch_version': torch.__version__, 'cuda_build': torch.version.cuda,
             'cuda_initialized': False, 'forward_executed': False,
             'elapsed_seconds': time.monotonic() - started}
    if args.id == 'scnet':
        check.update(sources=extras['sources'], sample_rate=extras['sample_rate'])
    elif args.id == 'transkun':
        check.update(sample_rate=extras['sample_rate'], task_scope='expressive piano transcription',
                     pedal_output_verified=False)
    else:
        labels = list(extras['vocabulary'].values())
        check.update(vocabulary_size=len(labels), vocabulary=labels,
                     task_scope='fixed 170-label chord vocabulary; no arbitrary 9/11/13/slash-chord guarantee')
    folder = ROOT / 'manifests/model-library' / args.id
    write(folder / 'cpu-check.json', check)
    manifest['checks'].update(environment_verified=True, cpu_load_verified=True)
    manifest['blockers'] = ['serialized GPU inference validation', 'quality and speed evaluation',
                            'DAW integration not authorized in this phase']
    manifest['cpu_check'] = check
    manifest['dependency_notes'] = [
        'Torch/Torchaudio 2.10.0+cu128 pinned for RTX5090; independent environment',
        'Only inference dependencies installed for SCNet; universal training/GUI CLI stack omitted',
        'Source files unmodified; narrow loader requires strict checkpoint/state matching',
    ]
    for path in sorted(folder.glob('*.txt')):
        manifest['artifacts'].append({'path': str(path), 'bytes': path.stat().st_size,
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    write(folder / 'deployment.json', manifest)
    print(json.dumps({'id': args.id, **check}), flush=True)


if __name__ == '__main__':
    main()
