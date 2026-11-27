"""Idempotently start the private generation gateway after an AutoDL restart."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/root/autodl-tmp/emusician")


def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=2) as response:
            value = json.load(response)
        return value.get("service") == "emusician-generation" and value.get("protocol_version") == 1
    except (OSError, ValueError):
        return False


def main():
    # Serialize concurrent GUI/helper starts; Linux advisory lock has no PID races.
    import fcntl
    ROOT.joinpath("state").mkdir(parents=True, exist_ok=True)
    with ROOT.joinpath("state/gateway-start.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if health():
            print(json.dumps({"status": "already_running", "port": 18081}))
            return
        ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        with ROOT.joinpath(f"logs/gateway-{stamp}.log").open("ab") as log:
            process = subprocess.Popen([str(ROOT / "envs/ace/bin/python"), "-u", str(ROOT / "tools/gateway.py"), "--root", str(ROOT)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        ROOT.joinpath("state/gateway.pid").write_text(str(process.pid), encoding="ascii")
        for _ in range(40):
            if health():
                print(json.dumps({"status": "started", "port": 18081, "pid": process.pid}))
                return
            if process.poll() is not None:
                raise RuntimeError("Generation service exited during startup; see cloud logs.")
            time.sleep(0.25)
        raise RuntimeError("Generation service did not become healthy; see cloud logs.")


if __name__ == "__main__":
    main()
