"""Start the optional Agent, or serve the embedded DAW-owned sidebar."""
from __future__ import annotations
import argparse
import getpass
import json
from pathlib import Path
import sys
import time
import threading
import webbrowser
from dev import Recorder, CommandFailure
from music_agent.audit import data_directory
from music_agent.config import load_config, active_config
from music_agent.providers import create_provider
from music_agent.bridge import DawBridge
from music_agent.provider import ProviderError
from music_agent.runtime import AgentRuntime
from music_agent.secrets import save_key, SecretError
from music_agent.server import AgentServer

ROOT = Path(__file__).resolve().parent.parent

def embedded_session(path, provider):
    from music_agent.embedded import load_session, SocketClient
    recorder=Recorder("agent-embedded-launch","Python + native DAW","DAW-owned helper only; launch is not GUI/audio acceptance")
    started=time.perf_counter()
    record, record_path, log_path=recorder.new_record([sys.executable,__file__,"--serve","--embedded-session","<local session capability file>"],"launch")
    stage="load_session"
    try:
        config=load_session(path)
        stage="connect_native"
        bridge=DawBridge(client=SocketClient(config),embedded=True)
        stage="create_runtime"
        runtime=AgentRuntime(bridge,provider)
        stage="bind_http"
        server=AgentServer(runtime)
        stage="publish_ready"
        ready=Path(config["ready_path"])
        temporary=ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"url":server.origin+"/?embedded=1#token="+server.token}),encoding="utf-8")
        temporary.replace(ready)
        record.update(status="launched",exit_code=0)
        log_path.write_text("Authenticated loopback helper ready; no model request sent.\n",encoding="utf-8")
    except Exception as exc:
        import traceback
        # Never log exception messages, source lines or locals: they may contain
        # session capabilities or credentials. Stage/type/locations are sufficient.
        diagnostic={"stage":stage,"exception_type":type(exc).__name__,
                    "frames":[{"file":Path(frame.filename).name,"function":frame.name,"line":frame.lineno}
                              for frame in traceback.extract_tb(exc.__traceback__)]}
        if stage=="load_session":
            try:
                source=Path(path).resolve()
                with source.open("rb") as sample:
                    payload=sample.read(4097)
                if len(payload)<=4096:
                    value=json.loads(payload.decode("utf-8-sig"))
                    ready=Path(value["ready_path"]).resolve()
                    expected=source.stem+".ready.json"
                    diagnostic["path_shape"]={"parent_equal":ready.parent==source.parent,
                        "name_equal":ready.name==expected,
                        "name_casefold_equal":ready.name.casefold()==expected.casefold(),
                        "input_name_length":len(source.name),"ready_name_length":len(ready.name)}
            except Exception:
                pass
        record.update(status="failed",exit_code=2,error="Embedded helper startup failed; capability and credentials omitted.",
                      startup_diagnostic=diagnostic)
        log_path.write_text(json.dumps(diagnostic,ensure_ascii=False)+"\n",encoding="utf-8")
        recorder.finish(record,record_path,log_path,started)
        raise
    recorder.finish(record,record_path,log_path,started)
    stopping=threading.Event()
    def watch_native():
        while not stopping.wait(1.0):
            if not bridge.client.is_alive():
                bridge.connected=False
                runtime.cancel_event.set()
                server.shutdown()
                return
    watcher=threading.Thread(target=watch_native,daemon=True,name="Native DAW lifetime")
    watcher.start()
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        stopping.set()
        server.server_close()
        bridge.close()
    return 0

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe",type=Path)
    parser.add_argument("--provider",choices=["kimi","openai"])
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--configure-key",action="store_true")
    parser.add_argument("--serve",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--embedded-session",type=Path,help=argparse.SUPPRESS)
    parser.add_argument("--check-provider",action="store_true")
    args=parser.parse_args()
    config=load_config()
    selected=args.provider or config["active_provider"]
    preference=config["providers"][selected]
    model=args.model or preference["model"]
    base=args.base_url or preference["base_url"]
    if args.configure_key:
        try:
            value=getpass.getpass(selected+" API key (hidden): ")
            save_key(value,provider=selected)
            print("Credential encrypted for the current Windows user.")
            return 0
        except (SecretError,KeyboardInterrupt,EOFError):
            print("Credential setup was not completed.")
            return 2
    provider=create_provider(selected,model,base,
        **({"reasoning_effort":preference.get("reasoning_effort","medium")} if selected=="openai" else {}))
    if args.check_provider:
        if not args.serve:
            return Recorder("agent-provider-check","Python","Official /models availability only; no inference").execute(
                [sys.executable,__file__,"--check-provider","--serve","--provider",selected,"--model",model,"--base-url",base]).returncode
        try:
            print(json.dumps({"status":"connected","provider":selected,"models":provider.list_models()},ensure_ascii=False))
            return 0
        except ProviderError as exc:
            print(json.dumps({"status":"failed","code":exc.code,"http_status":exc.status,"message":str(exc)},ensure_ascii=False))
            return 2
    if args.embedded_session:
        return embedded_session(args.embedded_session,provider)
    exe=args.exe or ROOT/"build/agent-batch2/bin/Release/E-musician.exe"
    if not exe.is_file():
        Recorder("agent-launch","Python","Missing DAW executable").preflight_failure("DAW executable not found.")
        parser.error("DAW executable missing. Pass --exe with the built path.")
    if not args.serve:
        command=[sys.executable,__file__,"--serve","--exe",str(exe.resolve()),"--provider",selected,"--model",model,"--base-url",base]
        if args.no_browser:command.append("--no-browser")
        Recorder("agent-launch","Python + Release DAW","Legacy external companion launch; use native Agent button for embedding").execute(command,launch_only=True)
        return 0
    bridge=DawBridge(exe)
    runtime=AgentRuntime(bridge,provider)
    server=AgentServer(runtime)
    print("Agent ready on localhost port",server.server_port,flush=True)
    print("Save the project in the controlled DAW before closing the external assistant.",flush=True)
    if not args.no_browser:
        webbrowser.open(server.launch_url)
    else:
        link=data_directory()/"current-session.url"
        link.parent.mkdir(parents=True,exist_ok=True)
        link.write_text("[InternetShortcut]\nURL="+server.launch_url+"\n",encoding="utf-8")
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

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (CommandFailure,ProviderError,SecretError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(2)
