"""CPU-only deployment integrity audit; never imports Torch or starts a service."""
import argparse
from pathlib import Path
import sys
import time
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compute.catalog import Catalog
from compute.protocol import SPECS, atomic_json, digest, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--runtime-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.output.resolve().is_relative_to(root):
        raise ValueError('Audit report must stay on the cloud data disk')
    runtime = root / 'tools/models/mir_upgrades/runtime.py'
    if digest(runtime) != sha256(args.runtime_sha):
        raise ValueError('Deployed MIR loader differs from the reviewed local source')
    catalog = Catalog(root)
    report = {'kind': 'CPU-only-file-integrity', 'gpu_inference': False,
              'service_started': False, 'mir_runtime_sha256': digest(runtime), 'models': []}
    success = True
    for model in SPECS:
        started = time.monotonic()
        item = {'model_id': model, 'status': 'checking'}
        try:
            provider = catalog.provider(model)
            if not provider['available']:
                raise ValueError(provider['detail'])
            item.update(status='passed', verification=catalog.verify_files(model))
        except Exception as error:
            success = False; item.update(status='failed', error=type(error).__name__ + ': ' + str(error)[:500])
        item['seconds'] = time.monotonic()-started
        report['models'].append(item)
        atomic_json(args.output, report)
        print(item, flush=True)
    report['status'] = 'passed' if success else 'failed'
    report['torch_imported'] = 'torch' in sys.modules
    atomic_json(args.output, report)
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
