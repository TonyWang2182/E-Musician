"""Cloud-only score-model staging. Never downloads weights or audio to a PC."""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')
HERE = Path(__file__).resolve().parent


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(path, item):
    if not path.is_file() or path.stat().st_size != item['bytes']:
        return False
    if item.get('sha256'):
        return digest(path) == item['sha256']
    blob = hashlib.sha1(f"blob {item['bytes']}\0".encode())
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            blob.update(block)
    return blob.hexdigest() == item['git_blob']


def free_space(needed=0):
    free = shutil.disk_usage(ROOT).free
    if free - needed < 50_000_000_000:
        raise RuntimeError('Cloud disk would fall below the 50 GB free-space reserve')
    return free


def download(directory, item):
    target = (directory / item['path']).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise ValueError('Artifact path escaped its assigned model directory')
    if verify(target, item):
        return artifact(target)
    if target.exists():
        raise RuntimeError('Refusing to replace a differing existing artifact: ' + item['path'])
    free_space(item['bytes'])
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + '.partial')
    last = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'E-musician-pinned-model-staging'})
            with urllib.request.urlopen(request, timeout=90) as response, part.open('wb') as stream:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > item['bytes']:
                        raise ValueError('Artifact exceeds pinned size: ' + item['path'])
                    stream.write(block)
                    if total % (128 * 1024 * 1024) == 0:
                        free_space()
                        print(json.dumps({'artifact': item['path'], 'downloaded_bytes': total}), flush=True)
            if not verify(part, item):
                raise ValueError('Artifact hash or size mismatch: ' + item['path'])
            part.replace(target)
            return artifact(target)
        except Exception as error:
            last = error
            print(json.dumps({'artifact': item['path'], 'attempt': attempt+1, 'error_type': type(error).__name__,
                              'http_status': getattr(error, 'code', None)}), flush=True)
            if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
                break
            time.sleep(2)
    raise RuntimeError('Artifact could not be staged: ' + item['path']) from last


def artifact(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def deployment(name, plan):
    file = ROOT / 'manifests/model-library' / name / 'deployment.json'
    if file.is_file():
        return json.loads(file.read_text())
    spec = plan['models'][name]
    return {'id': name, 'task': 'lead_sheet_transcription' if name == 'sheetsage2' else 'multi_instrument_transcription',
            'source_revision': spec['revision'],
            'model_revisions': ({'sheetsage2': spec['revision'], 'mert2': plan['models']['mert2']['revision']}
                                if name == 'sheetsage2' else {'medium': spec['medium']['revision']}),
            'paths': {'model': str(ROOT/'models'/name), 'environment': str(ROOT/'envs'/name),
                      'source': str(ROOT/'workspace/models'/name/'source')},
            'checks': {'files_verified': False, 'environment_verified': False, 'cpu_load_verified': False,
                       'gpu_inference_verified': False}, 'daw_connected': False, 'blockers': [], 'artifacts': [],
            'license': 'CC-BY-NC-4.0 model weights; public source terms retained',
            'velocity_limitation': 'Not inferred; upstream MIDI default 100' if name == 'muscriptor' else 'Symbolic playback velocities are not measured performance dynamics'}


def save_deployment(name, value):
    value['updated_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    value['cloud_free_bytes'] = free_space()
    write(ROOT/'manifests/model-library'/name/'deployment.json', value)


def stage(args, plan):
    name = args.model
    result = deployment(name, plan)
    result['stage_started_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    save_deployment(name, result)
    groups = ('sheetsage2', 'mert2') if name == 'sheetsage2' else ('muscriptor',)
    artifacts = []
    for group in groups:
        spec = plan['models'][group]
        directory = ROOT/'workspace/models/muscriptor/source' if group == 'muscriptor' else ROOT/'models'/group
        small = [item for item in spec['files'] if not item['path'].endswith('.safetensors')]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            artifacts.extend(pool.map(lambda item: download(directory, item), small))
        for item in spec['files']:
            if item['path'].endswith('.safetensors'):
                artifacts.append(download(directory, item))
    result['source_files_verified'] = True
    result['artifacts'] = artifacts
    if name == 'sheetsage2':
        result['paths']['source'] = str(ROOT/'models/sheetsage2')
        result['paths']['parent_model'] = str(ROOT/'models/mert2')
        # Upstream CLI keeps the pinned HF parent ID. Seed its private offline
        # cache with a symlink to the same verified bytes, without duplicating them.
        snapshot = ROOT/'workspace/models/sheetsage2/hf/hub/models--m-a-p--MERT-v2-FullSong/snapshots'/plan['models']['mert2']['revision']
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot.exists():
            snapshot.symlink_to(ROOT/'models/mert2', target_is_directory=True)
        elif snapshot.resolve() != (ROOT/'models/mert2').resolve():
            raise RuntimeError('Existing parent snapshot does not point to the approved model')
        result['checks']['files_verified'] = True
    else:
        model = plan['models']['muscriptor']['medium']
        url = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['path']}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception as error:
            status = type(error).__name__
        result['anonymous_weight_head_status'] = status
        result['blockers'] = ['MuScriptor medium is gated: authenticated account permission and model terms acceptance are not established. No weights downloaded, no bypass attempted.']
        result['checks']['files_verified'] = False
    save_deployment(name, result)
    print(json.dumps({'model': name, 'stage': 'weights-and-source-verified' if name == 'sheetsage2' else 'public-source-ready-weights-gated',
                      'artifacts': len(artifacts), 'free_bytes': free_space()}), flush=True)


def cpu_check(args, plan):
    if os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('CPU checks require CUDA_VISIBLE_DEVICES empty before interpreter startup')
    name = args.model
    result = deployment(name, plan)
    started = time.monotonic()
    import torch
    torch.set_num_threads(2)
    assert not torch.cuda.is_initialized()
    if name == 'sheetsage2':
        from transformers import AutoModel
        model = AutoModel.from_pretrained(str(ROOT/'models/sheetsage2'), trust_remote_code=True,
                                         local_files_only=True, base_model_path=str(ROOT/'models/mert2')).eval()
        assert all(param.device.type == 'cpu' for param in model.parameters())
        result['parameter_count'] = sum(param.numel() for param in model.parameters())
        result['checks']['cpu_load_verified'] = True
        result['upstream_window_seconds'] = float(model.hparams.input_audio_length)
        import importlib
        audio_module = importlib.import_module(type(model).__module__.rsplit('.', 1)[0]+'.audio_sheetsage2')
        fixture = ROOT/'jobs/generation/gateway-20261106T075755Z-120s/audio.wav'
        waveform = audio_module.load_audio(fixture, max_seconds=1, preset='default')
        assert waveform.ndim == 1 and len(waveform) == 24000 and torch.isfinite(waveform).all().item()
        result['file_input_decode_verified'] = True
        del model
        command = [sys.executable, str(ROOT/'models/sheetsage2/infer.py'), '--help']
    else:
        from muscriptor import TranscriptionModel
        assert callable(TranscriptionModel.load_model)
        command = [str(ROOT/'envs/muscriptor/bin/muscriptor'), 'transcribe', '--help']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (ROOT/'manifests/model-library'/name/'cli-help.txt').write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError('Upstream CLI help failed')
    assert not torch.cuda.is_initialized()
    result['checks']['environment_verified'] = True
    result['cpu_load_seconds'] = round(time.monotonic()-started, 3)
    result['upstream_cli_help_verified'] = True
    result['cuda_initialized'] = False
    result['python'] = sys.version
    result['torch'] = torch.__version__
    result['cuda_runtime'] = torch.version.cuda
    for path in (ROOT/'manifests/model-library'/name).glob('*'):
        if path.is_file() and path.name != 'deployment.json':
            item = artifact(path)
            result['artifacts'] = [old for old in result['artifacts'] if old['path'] != item['path']] + [item]
    save_deployment(name, result)
    print(json.dumps({'model': name, 'checks': result['checks'], 'seconds': result['cpu_load_seconds'],
                      'cuda_initialized': False}), flush=True)


def main():
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('This deployment entry point is cloud-only; it must never fetch models to E:')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'cpu-check'))
    parser.add_argument('--model', choices=('sheetsage2', 'muscriptor'), required=True)
    args = parser.parse_args()
    plan = json.loads((HERE/'artifacts.json').read_text())
    free_space()
    (stage if args.action == 'stage' else cpu_check)(args, plan)


if __name__ == '__main__':
    main()
