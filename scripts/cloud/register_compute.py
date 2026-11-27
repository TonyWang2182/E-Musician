"""Check protocol 2 readiness and explicitly publish a separate desktop registry."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import subprocess
import uuid
try:
    from . import compute_client as client
except ImportError:
    import compute_client as client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=client.ROOT)
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--python', default=sys.executable, help='Absolute local interpreter with numpy, scipy and soundfile installed.')
    parser.add_argument('--ssh-alias', help='Host alias in your own OpenSSH configuration.')
    parser.add_argument('--remote-port', type=int, help='Remote loopback compute port (default 18082).')
    parser.add_argument('--remote-root', help='Absolute Linux deployment root used by the service starter.')
    parser.add_argument('--remote-python', help='Absolute Linux interpreter used by the service starter.')
    parser.add_argument('--no-start-service', action='store_true', help='Connect to an already managed service without starting it over SSH.')
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    path = root / 'compute-registry.json'
    config = client.read_json(path) if path.exists() else {'schema_version': 1, 'available': False,
        'ssh_alias': 'emusician-cloud', 'remote_port': 18082, 'compute_protocol': 2, 'start_service': True}
    for name in ('ssh_alias', 'remote_port', 'remote_root', 'remote_python'):
        if getattr(args, name) is not None:
            config[name] = getattr(args, name)
    if args.no_start_service:
        config['start_service'] = False
    if args.register:
        if not Path(args.python).is_absolute() or not Path(args.python).is_file():
            raise RuntimeError('Supply an absolute --python path to the local streaming audio interpreter.')
        subprocess.run([args.python, '-c', 'import numpy, scipy, soundfile'], check=True, timeout=30)
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
            if capabilities.get('protocol_version') != 2 or not capabilities.get('providers') or not any(p['available'] for p in capabilities['providers']):
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
