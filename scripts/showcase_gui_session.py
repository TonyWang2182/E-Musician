"""Owned native/WebView capture session controlled by a local file inbox.

No model calls or fabricated UI. Requests act on the actual isolated DAW.
Use dev_showcase.py to record launch/exit, then place numbered JSON requests
in <output>/inbox. The session only opens staged capture projects.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from agent_client import Client
from showcase_capture import CaptureSession


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9229)
    parser.add_argument("--device-output", action="store_true",
                        help="Use this isolated workspace's audio device for real Preview; never starts recording")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inbox = args.output / "inbox"
    inbox.mkdir(exist_ok=True)
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={args.port}"
    os.environ["EMUSICIAN_UI_LANGUAGE"] = "en"
    client = Client(args.exe, show=True, offline_test=not args.device_output, timeout=180)
    capture = None
    handled = set()
    try:
        capture = CaptureSession(client=client, output=args.output)
        # The visible HWND can precede its activation message during device
        # startup. Retry only the owned window; never synthesize global input.
        for attempt in range(5):
            try:
                capture.foreground()
                break
            except RuntimeError:
                if attempt == 4:
                    raise
                time.sleep(.3)
        capture.resize(1920, 1080)
        capture.open_project(args.project)
        capture.foreground()
        capture.invoke("Agent")
        time.sleep(3)
        capture.screenshot("00-initial")
        write(args.output / "controls-initial.json", capture.controls())
        write(args.output / "ready.json", {"pid": client.process.pid, "title": capture.win.title(capture.hwnd)})
        print("Owned capture session ready", flush=True)
        started = time.monotonic()
        while time.monotonic() - started < 3600:
            for path in sorted(inbox.glob("*.request.json")):
                if path.name in handled:
                    continue
                handled.add(path.name)
                result = {"ok": False}
                try:
                    request = json.loads(path.read_text(encoding="utf-8-sig"))
                    action = request["action"]
                    if action == "close":
                        write(path.with_name(path.name.replace(".request", ".result")), {"ok": True, "closed": True})
                        return 0
                    if action == "screenshot":
                        result["value"] = str(capture.screenshot(request["name"]))
                    elif action == "controls":
                        result["value"] = capture.controls()
                    elif action == "invoke":
                        capture.foreground()
                        result["value"] = capture.invoke(request["name"], request.get("index", 0))
                    elif action == "menu":
                        result["value"] = capture.invoke_menu(request["button"], request["item"])
                    elif action == "open":
                        result["value"] = capture.open_project(Path(request["path"]))
                    elif action == "native":
                        if request["command"] not in {"showcase_select_clip", "remove_track", "set_track_muted", "set_track_solo", "play", "stop", "seek", "save_project", "accept_analysis_result", "get_analysis_result", "list_analysis_jobs", "get_chord_regions", "undo", "redo"}:
                            raise ValueError("Native command is outside this capture workflow")
                        if request["command"] == "save_project":
                            target = Path(request["args"]["path"]).resolve()
                            if not target.is_relative_to(capture.project_root):
                                raise ValueError("Save only to a staged capture project")
                        result["value"] = capture.command(request["command"], request.get("args", {}))
                    elif action == "snapshot":
                        result["value"] = client.state()
                    elif action == "cdp":
                        command = ["node", str(Path(__file__).with_name("showcase_cdp.mjs")), str(args.port), *request["arguments"]]
                        run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                        if run.returncode:
                            raise RuntimeError(run.stderr[-1500:])
                        result["value"] = json.loads(run.stdout)
                    elif action == "record":
                        capture.foreground()
                        result["value"] = str(capture.record(request["name"], seconds=float(request["seconds"]), ffmpeg=Path(request["ffmpeg"]), fps=15))
                    else:
                        raise ValueError("Unknown capture action")
                    result["ok"] = True
                except Exception as exc:
                    result["error"] = str(exc)[:1800]
                write(path.with_name(path.name.replace(".request", ".result")), result)
                print(path.name + (" passed" if result["ok"] else " failed"), flush=True)
            time.sleep(.15)
        raise TimeoutError("Capture session exceeded its one-hour bound")
    finally:
        if capture is not None:
            capture.flush()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
