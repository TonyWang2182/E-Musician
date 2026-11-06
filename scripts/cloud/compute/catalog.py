"""Fixed deployment identities; installation evidence and service activation differ."""
from pathlib import Path
from .protocol import SPECS, read_json, digest

DETAILS = {
    'scnet': 'SCNet XL IHF: vocals/drums/bass/other (four stems).',
    'transkun': 'TransKun V2: expressive piano transcription including emitted pedal controls.',
    'chordmini': 'ChordMini BTC: fixed 170-label vocabulary; no arbitrary jazz extensions.',
    'muscriptor': 'MuScriptor medium: multiple instrument note tracks; exported velocity is a default, not predicted.',
    'sheetsage2': 'SheetSage2: symbolic score, notes and available structural annotations; inspect predictions.',
    'yue2': 'YuE2: semantic token duration budget; natural stopping/truncation is reported.',
    'ace-step-1.5-xl-turbo': 'ACE-Step XL Turbo + 1.7B LM: musical conditioning is not exact timing verification.',
}


class Catalog:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def manifest(self, model):
        if model == 'ace-step-1.5-xl-turbo':
            return read_json(self.root / 'manifests/ace-runtime.json')
        return read_json(self.root / 'manifests/model-library' / model / 'deployment.json')

    def python(self, model):
        return self.root / 'envs' / SPECS[model]['env'] / 'bin/python'

    def provider(self, model):
        spec = SPECS[model]
        available, reason = False, ''
        try:
            manifest = self.manifest(model)
            if not self.python(model).is_file():
                raise ValueError('The isolated model interpreter is missing')
            if model == 'ace-step-1.5-xl-turbo':
                if manifest.get('ready') is not True:
                    raise ValueError('ACE deployment manifest is not ready')
            else:
                checks = manifest.get('checks', {})
                if not all(checks.get(k) is True for k in ('files_verified', 'environment_verified', 'cpu_load_verified', 'gpu_inference_verified')):
                    raise ValueError('The deployment has not passed its required structural checks')
            available = True
        except (OSError, ValueError, KeyError, TypeError) as error:
            reason = str(error)[:200]
        return {'kind': spec['kind'], 'model_id': model, 'execution': 'cloud', 'available': available,
                'default': model in ('ace-step-1.5-xl-turbo', 'scnet', 'transkun', 'chordmini', 'sheetsage2'),
                'max_duration_seconds': spec['limit'], 'detail': DETAILS[model] + (' Unavailable: ' + reason if reason else ''),
                'parameters': 'fixed' if spec['kind'] != 'generate' else 'generation-conditioning',
                'quality_verified': False}

    def capabilities(self):
        return {'protocol_version': 2, 'execution': 'cloud', 'single_heavy_task': True,
                'providers': [self.provider(model) for model in SPECS]}

    def verify_files(self, model):
        """Before deserialization, hash pinned code/config/weights, never secrets.

        The API capability check remains inexpensive. Every isolated invocation
        verifies its own fixed deployment files before importing model code.
        """
        manifest = self.manifest(model)
        if model == 'ace-step-1.5-xl-turbo':
            base = self.root / 'models/ace/checkpoints'
            entries = [{**item, 'path': str(base / item['path'])} for item in
                       read_json(self.root / 'manifests/ace-runtime-model-files.json')]
            allowed = [base]
        else:
            entries = manifest['artifacts']
            paths = manifest['paths']
            allowed = [self.root / 'models', Path(paths['source'])]
        count = total = weights = 0
        suffixes = {'.py', '.json', '.yaml', '.yml', '.conf', '.ini', '.pt', '.pth', '.ckpt', '.safetensors', '.bin', '.tiktoken'}
        for item in entries:
            path = Path(item['path'])
            if not path.resolve().is_relative_to(self.root):
                raise ValueError('Deployment artifact escaped the configured cloud root')
            if path.suffix not in suffixes or not any(path.resolve().is_relative_to(base.resolve()) for base in allowed):
                continue
            if path.is_symlink() or not path.is_file() or digest(path) != item['sha256']:
                raise ValueError('Pinned model/config/code integrity check failed: ' + path.name)
            count += 1; total += path.stat().st_size
            weights += path.suffix in {'.pt', '.pth', '.ckpt', '.safetensors', '.bin'}
        if not weights:
            raise ValueError('Deployment manifest contains no verifiable model weights')
        return {'files': count, 'bytes': total, 'before_model_loading': True}
