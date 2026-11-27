"""Install as tools/compute_start.py; no migration or model download is automatic."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')


def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=2) as response:
            value = json.load(response)
            return value if value.get('service') == 'emusician-compute' and value.get('protocol_version') == 2 else None
    except (OSError, ValueError):
        return None


def main():
    import fcntl
    state = ROOT / 'state'; state.mkdir(parents=True, exist_ok=True)
    with (state / 'compute-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if health():
            print(json.dumps({'status': 'ready', 'already_running': True})); return
        # Explicit migration marker is created only by the coordinated installer
        # after checking the legacy queue and stopping the legacy process.
        if not (state / 'compute-migration-complete.json').is_file():
            raise RuntimeError('Cloud compute migration has not been completed; old ACE is left untouched')
        log = ROOT / 'logs/compute-service.log'; log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('ab') as stream:
            process = subprocess.Popen(['/root/miniconda3/bin/python', str(ROOT / 'tools/compute/server.py'),
                '--root', str(ROOT)], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        for _ in range(40):
            if health():
                print(json.dumps({'status': 'ready', 'already_running': False})); return
            if process.poll() is not None:
                raise RuntimeError('Cloud compute service did not start; inspect service log')
            time.sleep(.25)
        raise RuntimeError('Cloud compute service startup deadline exceeded; no duplicate launch attempted')


if __name__ == '__main__':
    main()
