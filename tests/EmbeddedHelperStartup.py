"""Real helper startup, synthetic native socket, no DAW/window/model request.

Run this script through the repository Recorder. The launched run_agent.py also
records its own embedded startup. Keep the session pathname in logical APPDATA:
MSIX virtualization may resolve an existing input into LocalCache while its
not-yet-created ready sibling still resolves into AppData. The original
load_session compared those resolved parents and rejected a valid sibling.
This exercises the actual environment, rather than mocking Path.resolve.

Only this test's unique session/ready/tmp files and its own child are cleaned up.
Existing DAWs, devices, sessions, settings and encrypted credentials are not
controlled. Reports contain booleans/exit status only, never capability URLs,
tokens, provider credentials, dialogue, exception text or protected-file hashes.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from MusicAgentIntegration import protected
from test_music_agent_embedded import NativeFixture, TOKEN


def protected_files():
    """Reuse project guards and additionally hash actual local settings/keys."""
    result = protected()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        directory = Path(local) / "E-musician" / "agent"
        paths = {directory / "settings.json"}
        if directory.is_dir():
            paths.update(directory.glob("*.key"))
        for path in paths:
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


def root_html_is_ready(ready_path):
    """Read a bounded readiness envelope, then GET only localhost root HTML."""
    with ready_path.open("rb") as stream:
        payload = stream.read(4097)
    if not payload or len(payload) > 4096:
        return False
    value = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(value, dict) or set(value) != {"url"} or not isinstance(value["url"], str):
        return False
    address = urlsplit(value["url"])
    if (address.scheme != "http" or address.hostname != "127.0.0.1"
            or address.username is not None or address.password is not None
            or address.path != "/" or address.port is None
            or not 1 <= address.port <= 65535):
        return False
    # Do not follow redirects, use environment proxies, or send the capability.
    connection = http.client.HTTPConnection("127.0.0.1", address.port, timeout=2)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        content = response.read(1024 * 1024 + 1)
        return (response.status == 200 and len(content) <= 1024 * 1024
                and response.getheader("Content-Type", "").startswith("text/html")
                and b"<!doctype html>" in content.lower() and b'id="prompt"' in content)
    finally:
        connection.close()


def main():
    run_id = uuid.uuid4().hex
    report_directory = ROOT / "build" / "embedded-helper-startup" / run_id
    report_directory.mkdir(parents=True, exist_ok=False)
    report = {"ready": False, "exit": None, "physical_input": False,
              "no_model_call": True, "protected_files_unchanged": False,
              "owned_files_cleaned": False}
    baseline = None
    fixture = None
    child = None
    owned = []
    failed = False
    try:
        appdata = os.environ.get("APPDATA")
        if not appdata or not Path(appdata).is_absolute():
            raise ValueError("Logical APPDATA is required")
        baseline = protected_files()
        # Deliberately do not resolve this directory or any session sibling.
        directory = Path(appdata) / "E-musician" / "agent" / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        session = directory / ("startup-regression-" + run_id + ".json")
        ready = directory / (session.stem + ".ready.json")
        temporary = ready.with_suffix(".tmp")
        if any(path.exists() or path.is_symlink() for path in (session, ready, temporary)):
            raise ValueError("Unique fixture name is already occupied")
        fixture = NativeFixture()
        with session.open("x", encoding="utf-8") as stream:
            owned = [session, ready, temporary]
            json.dump({**fixture.session, "ready_path": str(ready)}, stream)
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        child = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "run_agent.py"),
             "--serve", "--embedded-session", str(session)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if child.poll() is not None:
                break
            if ready.is_file():
                report["ready"] = root_html_is_ready(ready)
                break
            time.sleep(0.05)
        if not report["ready"]:
            failed = True
        # The helper must have performed authentication only. No state request,
        # plan endpoint, provider request or music action is needed by this test.
        if fixture.requests != [{"auth": TOKEN}]:
            failed = True
        fixture.close()
        fixture = None
        # Native EOF should make watch_native stop the HTTP service naturally.
        child.wait(timeout=5)
        report["exit"] = child.returncode
        if child.returncode != 0:
            failed = True
    except Exception:
        # Never print raw exceptions: a path, URL or HTTP error may contain a
        # local session capability. The helper's own Recorder retains status.
        failed = True
    finally:
        if fixture is not None:
            try:
                fixture.close()
            except Exception:
                failed = True
        if child is not None:
            if child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    failed = True
                    child.terminate()  # Only the Popen child created above.
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
            report["exit"] = child.returncode
        clean = True
        for path in owned:
            try:
                path.unlink(missing_ok=True)  # Exact owned file, never recursive.
            except OSError:
                clean = False
        report["owned_files_cleaned"] = clean and bool(owned)
        try:
            report["protected_files_unchanged"] = baseline is not None and baseline == protected_files()
        except Exception:
            report["protected_files_unchanged"] = False
        failed = failed or not report["protected_files_unchanged"] or not report["owned_files_cleaned"]
        (report_directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
