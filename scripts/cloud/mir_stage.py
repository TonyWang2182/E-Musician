"""Stage registered MIR assets; deliberately does not run inference or enable a service."""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import time
import urllib.request

REMOTE = Path('/root/autodl-tmp/emusician')
KINDS = ('separate', 'separate_6s', 'transcribe', 'beats')
BEAT_COMMIT = 'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def prepare(args):
    root, output = Path(args.local_analysis), Path(args.output)
    registry = json.loads((root / 'registry.json').read_text(encoding='utf-8'))['providers']
    stage = output / 'mir-stage'
    stage.mkdir(parents=True, exist_ok=True)
    files, providers = [], {}

    def copy(source, relative):
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(source)
        if not target.exists() or sha(target) != digest:
            shutil.copyfile(source, target)
        files.append({'path': relative.as_posix(), 'bytes': target.stat().st_size, 'sha256': digest})

    for kind in KINDS:
        provider = registry[kind]
        source = Path(provider['model_path'])
        if sha(source) != provider['weight_sha256']:
            raise ValueError(f'Registered weight hash mismatch: {kind}')
        relative = Path('models/mir') / source.relative_to(root / 'models')
        copy(source, relative)
        for auxiliary in sorted(source.parent.glob('*')):
            if auxiliary.is_file() and auxiliary.suffix.lower() in ('.yaml', '.md', '.json'):
                copy(auxiliary, relative.parent / auxiliary.name)
        providers[kind] = {key: provider[key] for key in (
            'model_id', 'version', 'source_revision', 'source_url', 'weight_sha256', 'license_status')}
        providers[kind].update(available=False, status='staged-not-inference-validated',
                               model_path=(REMOTE / relative).as_posix(),
                               python_executable=(REMOTE / 'envs' /
                                   ('mir-transcription' if kind == 'transcribe' else 'mir-torch') / 'bin/python').as_posix())
    source = stage / 'sources' / f'beat-this-{BEAT_COMMIT}.zip'
    source.parent.mkdir(exist_ok=True)
    source_url = f'https://codeload.github.com/CPJKU/beat_this/zip/{BEAT_COMMIT}'
    if not source.exists():
        partial = source.with_suffix('.partial')
        with urllib.request.urlopen(source_url, timeout=120) as response, partial.open('wb') as stream:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 32 * 1024 * 1024:
                    raise ValueError('BeatThis source archive exceeds bounded 32 MiB')
                stream.write(block)
        partial.replace(source)
    files.append({'path': source.relative_to(stage).as_posix(), 'bytes': source.stat().st_size,
                  'sha256': sha(source), 'source_url': source_url, 'source_commit': BEAT_COMMIT})
    manifest = {'schema_version': 1, 'stage': 'files-only', 'providers': providers, 'files': files,
                'gpu_inference_tested': False, 'daw_connected': False,
                'weight_bytes': sum(Path(registry[k]['model_path']).stat().st_size for k in KINDS)}
    write(stage / 'manifests/mir-stage-assets.json', manifest)
    archive = output / 'mir-stage-assets.tar'
    with tarfile.open(archive, 'w') as tar:
        for item in files:
            tar.add(stage / item['path'], arcname=item['path'], recursive=False)
        tar.add(stage / 'manifests/mir-stage-assets.json', arcname='manifests/mir-stage-assets.json')
    write(output / 'mir-stage-transfer.json', {'archive': archive.name, 'bytes': archive.stat().st_size,
          'sha256': sha(archive), 'model_count': len(providers), 'weight_bytes': manifest['weight_bytes']})
    print(json.dumps({'archive': str(archive), 'weight_bytes': manifest['weight_bytes'],
                      'archive_bytes': archive.stat().st_size, 'source_sha256': sha(source)}), flush=True)


def verify(args):
    root = Path(args.root)
    manifest = json.loads((root / 'manifests/mir-stage-assets.json').read_text())
    for item in manifest['files']:
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root.resolve()) or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError(f'Staged file integrity mismatch: {item["path"]}')
    print(json.dumps({'files_verified': len(manifest['files']), 'weight_bytes': manifest['weight_bytes']}), flush=True)


def unpack(args):
    root = Path(args.root).resolve()
    receipt = json.loads((root / 'cache/mir-stage-transfer.json').read_text())
    archive = root / 'cache/mir-stage-assets.tar'
    if archive.stat().st_size != receipt['bytes'] or sha(archive) != receipt['sha256']:
        raise ValueError('Transfer archive integrity mismatch')
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (root / member.name).resolve()
            allowed = member.name.startswith(('models/mir/', 'sources/beat-this-')) or member.name == 'manifests/mir-stage-assets.json'
            if not member.isfile() or not allowed or not target.is_relative_to(root):
                raise ValueError('Unexpected archive member')
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source:
                if target.exists():
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                    if target.stat().st_size != member.size or sha(target) != digest:
                        raise ValueError(f'Will not replace differing staged file: {member.name}')
                else:
                    temporary = target.with_suffix(target.suffix + '.partial')
                    with temporary.open('wb') as stream:
                        shutil.copyfileobj(source, stream, 1024 * 1024)
                    temporary.replace(target)
    verify(args)


def cpu_check(args):
    # Also set by the installer, before this fresh interpreter starts. Never select GPU.
    if os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('CPU-only staging check requires CUDA_VISIBLE_DEVICES empty before launch')
    root = Path(args.root)
    manifest = json.loads((root / 'manifests/mir-stage-assets.json').read_text())
    started = time.monotonic()
    result = {'schema_version': 1, 'check': args.backend, 'python': sys.version,
              'platform': platform.platform(), 'gpu_inference_tested': False,
              'cpu_inference_tested': False, 'models': {}, 'dependencies': {}}
    if args.backend == 'torch':
        import torch
        import torchaudio
        from demucs.hf import load_safetensors_model
        from beat_this.inference import load_model
        torch.set_num_threads(2)
        assert not torch.cuda.is_initialized()
        for kind in ('separate', 'separate_6s', 'beats'):
            checkpoint = manifest['providers'][kind]['model_path']
            model = load_model(checkpoint, device='cpu') if kind == 'beats' else load_safetensors_model(checkpoint)
            model.eval()
            assert all(p.device.type == 'cpu' for p in model.parameters())
            result['models'][kind] = {'loaded_on_cpu': True, 'parameter_count': sum(p.numel() for p in model.parameters()),
                                      'sources': list(getattr(model, 'sources', [])),
                                      'sample_rate': getattr(model, 'samplerate', None)}
            del model
            gc.collect()
        result['torch_cuda_build'] = torch.version.cuda
        result['compiled_architectures'] = torch.cuda.get_arch_list()
        result['cuda_initialized'] = torch.cuda.is_initialized()
        assert not result['cuda_initialized']
        packages = ('torch', 'torchaudio', 'demucs', 'beat-this', 'numpy', 'safetensors', 'rotary-embedding-torch')
    else:
        import onnxruntime as ort
        from basic_pitch.inference import Model
        checkpoint = manifest['providers']['transcribe']['model_path']
        # Instantiate upstream wrapper as used by the existing provider; no prediction.
        model = Model(checkpoint)
        assert model.model_type == Model.MODEL_TYPES.ONNX
        result['models']['transcribe'] = {'loaded_on_cpu': True, 'model_type': model.model_type.name,
            'execution_providers': model.model.get_providers(),
            'inputs': [{'name': x.name, 'shape': x.shape} for x in model.model.get_inputs()]}
        assert model.model.get_providers() == ['CPUExecutionProvider']
        packages = ('basic-pitch', 'onnxruntime', 'numpy', 'librosa', 'numba')
    for name in packages:
        result['dependencies'][name] = importlib.metadata.version(name)
    result['elapsed_seconds'] = time.monotonic() - started
    write(root / f'manifests/mir-{args.backend}-cpu-check.json', result)
    print(json.dumps(result), flush=True)


def finalize(args):
    root = Path(args.root)
    path = root / 'manifests/mir-stage-assets.json'
    manifest = json.loads(path.read_text())
    checks = {name: json.loads((root / f'manifests/mir-{name}-cpu-check.json').read_text())
              for name in ('torch', 'onnx')}
    manifest.update(stage='environment-and-cpu-load-verified', checks=checks,
                    gpu_inference_tested=False, daw_connected=False,
                    activation_blockers=['shared GPU scheduler', 'bounded audio upload and result download',
                                         'real inference evaluation', 'DAW local/cloud settings and routing'])
    for provider in manifest['providers'].values():
        provider.update(available=False, status='cpu-load-verified-awaiting-inference-and-routing')
    write(root / 'manifests/mir-stage-status.json', manifest)
    print(json.dumps({'status': manifest['stage'], 'available': False, 'gpu_inference_tested': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--local-analysis', default='E:/MusicAgent&DAW/analysis')
    p.add_argument('--output', default='E:/MusicAgent&DAW/cloud-inference/environments/mir')
    p.set_defaults(function=prepare)
    for name, function in (('unpack', unpack), ('verify', verify), ('cpu-check', cpu_check), ('finalize', finalize)):
        p = sub.add_parser(name)
        p.add_argument('--root', default=str(REMOTE))
        if name == 'cpu-check':
            p.add_argument('--backend', choices=('torch', 'onnx'), required=True)
        p.set_defaults(function=function)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
