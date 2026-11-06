"""Check protocol 2 readiness and explicitly publish a separate desktop registry."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid
try:
    from . import compute_client as client
except ImportError:
    import compute_client as client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=client.ROOT)
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--python', default='E:/MusicAgent&DAW/analysis/runtimes/chords-py310/Scripts/python.exe')
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    path = root / 'compute-registry.json'
    config = client.read_json(path) if path.exists() else {'schema_version': 1, 'available': False,
        'ssh_alias': 'emusician-autodl', 'remote_port': 18082, 'compute_protocol': 2, 'start_service': True}
    directory = root / 'experiments' / ('compute-connect-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    tunnel = client.Tunnel(config, directory)
    try:
        health = tunnel.open()
        capabilities = tunnel.call('GET', '/capabilities')
        report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'health': health,
            'capabilities': capabilities, 'inference_performed': False}
        client.atomic_json(directory / 'report.json', report)
        if args.register:
            if not Path(args.python).is_file() or not Path(args.python).is_absolute():
                raise RuntimeError('The local streaming audio interpreter is not installed.')
            if capabilities.get('protocol_version') != 2 or not capabilities.get('providers') or not all(p['available'] for p in capabilities['providers']):
                raise RuntimeError('Cloud readiness checks failed; registry unchanged.')
            if path.exists():
                backup = directory / 'previous-registry.json'
                backup.write_bytes(path.read_bytes())
            config.update(available=True, python_executable=args.python, providers=capabilities['providers'],
                defaults={'separate': 'scnet', 'transcribe': 'transkun', 'chords': 'chordmini',
                          'score': 'sheetsage2', 'generate': 'ace-step-1.5-xl-turbo'},
                checked_at=report['checked_at'], status='Configured; live connectivity is checked at each task start.')
            client.atomic_json(path, config)
        print(json.dumps({'registered': args.register, 'provider_count': len(capabilities.get('providers', [])),
                          'report': str(directory / 'report.json')}, ensure_ascii=False))
    finally:
        tunnel.close()


if __name__ == '__main__': main()
