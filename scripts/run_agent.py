"""Launch the optional Kimi companion; all launches/checks use development Recorder."""
from __future__ import annotations
import argparse
import getpass
import json
from pathlib import Path
import sys
import webbrowser
from dev import Recorder, CommandFailure
from music_agent.audit import data_directory
from music_agent.config import load_config
from music_agent.bridge import DawBridge
from music_agent.provider import KimiProvider, ProviderError
from music_agent.runtime import AgentRuntime
from music_agent.secrets import save_key, SecretError
from music_agent.server import AgentServer

ROOT = Path(__file__).resolve().parent.parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--configure-key", action="store_true", help="Hidden console entry; encrypt with current-user DPAPI.")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check-provider", action="store_true", help="List model availability; no chat request.")
    args = parser.parse_args()
    config = load_config()
    args.model = args.model or config["model"]
    args.base_url = args.base_url or config["base_url"]
    if args.configure_key:
        # Never pass a key on argv or print it. No traceback includes the value.
        try:
            value = getpass.getpass("Kimi API key (hidden): ")
            save_key(value)
            print("Credential encrypted for the current Windows user.")
            return 0
        except (SecretError, KeyboardInterrupt, EOFError) as exc:
            print("Credential setup was not completed.")
            return 2
    if args.check_provider:
        if not args.serve:
            return Recorder("agent-provider-check","Python","Official /models availability; no chat inference").execute(
                [sys.executable,__file__,"--check-provider","--serve","--model",args.model,"--base-url",args.base_url]).returncode
        try:
            models = KimiProvider(model=args.model,base_url=args.base_url).list_models()
            print(json.dumps({"status":"connected","models":models},ensure_ascii=False))
            return 0
        except ProviderError as exc:
            print(json.dumps({"status":"failed","code":exc.code,"http_status":exc.status,"message":str(exc)},ensure_ascii=False))
            return 2
    exe = args.exe or ROOT/"build/bin/Release/E-musician.exe"
    if not exe.is_file():
        Recorder("agent-launch","Python","Missing DAW executable").preflight_failure("DAW executable not found.")
        parser.error("DAW executable missing. Pass --exe with the built E-musician.exe path.")
    if not args.serve:
        command = [sys.executable,__file__,"--serve","--exe",str(exe.resolve()),
                   "--model",args.model,"--base-url",args.base_url]
        if args.no_browser:
            command.append("--no-browser")
        Recorder("agent-launch","Python + Release DAW","Launch only; GUI/hearing acceptance remains manual").execute(command,launch_only=True)
        return 0
    bridge = DawBridge(exe)
    runtime = AgentRuntime(bridge,KimiProvider(model=args.model,base_url=args.base_url))
    server = AgentServer(runtime)
    # Capability URL stays out of logs; no user key is sent to a browser.
    print("Agent ready on localhost port",server.server_port,flush=True)
    print("Save the project in the controlled DAW before closing the assistant.",flush=True)
    if not args.no_browser:
        webbrowser.open(server.launch_url)
    else:
        # Explicit debug mode: a protected launcher file gives the user a clickable
        # entry without exposing capabilities in process argv or development logs.
        link = data_directory()/"current-session.url"
        link.parent.mkdir(parents=True,exist_ok=True)
        link.write_text("[InternetShortcut]\nURL="+server.launch_url+"\n",encoding="utf-8")
        print("Open the local current-session.url under the Agent data directory.",flush=True)
    try:
        while True:
            try:
                server.serve_forever(poll_interval=0.25)
                break
            except KeyboardInterrupt:
                try:
                    runtime.close()
                    break
                except (RuntimeError,ValueError):
                    print("Please save the DAW project and close from the Agent window.",flush=True)
    finally:
        server.server_close()
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CommandFailure, ProviderError, SecretError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
