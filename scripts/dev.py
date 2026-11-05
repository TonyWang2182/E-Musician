#!/usr/bin/env python3
"""Reproducible local DAW development commands with per-command evidence.

Examples:
    python scripts/dev.py bootstrap --note "Fetch pinned dependencies"
    python scripts/dev.py check --config Debug --note "Validate transport change"
    python scripts/dev.py run --config Debug

Build/test commands stream to the console and a log. ``run`` returns after
launching the GUI; subsequent application output goes to that command's log.
A launch is explicitly recorded as "launched", never as a passed runtime test.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import locale
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parent.parent
DISPLAY_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}\Z")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_fingerprint() -> dict:
    """Hash source inputs without hashing mutable documentation/build output."""
    candidates: set[Path] = set()
    errors: list[str] = []
    for name in ("apps", "core", "tests", "scripts", "cmake", "assets"):
        directory = ROOT / name
        if directory.is_dir():
            candidates.update(
                path for path in directory.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
                and path.suffix.lower() not in (".pyc", ".pyo")
            )
    for name in ("CMakeLists.txt", "CMakePresets.json", "Start-Agent.cmd"):
        path = ROOT / name
        if path.is_file():
            candidates.add(path)

    files: dict[str, str] = {}
    for path in sorted(candidates, key=lambda item: item.as_posix()):
        relative = path.relative_to(ROOT).as_posix()
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files[relative] = digest.hexdigest()
        except OSError as error:
            errors.append(f"{relative}: {error}")
    combined = hashlib.sha256()
    for relative, digest in files.items():
        combined.update(f"{relative}\0{digest}\n".encode("utf-8"))
    return {"algorithm": "sha256", "digest": combined.hexdigest(), "files": files, "errors": errors}


def source_git_head() -> str | None:
    """Read Git metadata directly, avoiding unlogged recursive git invocations."""
    try:
        git_directory = ROOT / ".git"
        if git_directory.is_file():
            location = git_directory.read_text(encoding="utf-8").strip()
            if not location.startswith("gitdir: "):
                return None
            git_directory = (ROOT / location[8:]).resolve()
        common_directory = git_directory
        common_file = git_directory / "commondir"
        if common_file.is_file():
            common_directory = (git_directory / common_file.read_text(encoding="utf-8").strip()).resolve()
        head = (git_directory / "HEAD").read_text(encoding="utf-8").strip()
        if COMMIT_PATTERN.fullmatch(head):
            return head.lower()
        if not head.startswith("ref: "):
            return None
        reference = head[5:]
        for directory in (git_directory, common_directory):
            ref_file = directory / reference
            if ref_file.is_file():
                value = ref_file.read_text(encoding="utf-8").strip()
                if COMMIT_PATTERN.fullmatch(value):
                    return value.lower()
        packed = common_directory / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith(("#", "^")):
                    value, name = line.split(" ", 1)
                    if name == reference and COMMIT_PATTERN.fullmatch(value):
                        return value.lower()
    except (OSError, ValueError):
        pass
    return None


def command_text(arguments: list[str]) -> str:
    # This formatting is for display only. Popen always receives the argument list.
    return subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)


def decode_output(value: bytes) -> str:
    """Prefer UTF-8, then the OS code page; exact bytes remain in the raw log."""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("mbcs" if os.name == "nt" else locale.getencoding(), errors="replace")


def configure_console_output() -> None:
    """Use UTF-8 for redirected developer-tool output, preserving native TTYs."""
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            # A Windows pipe otherwise defaults to the ANSI code page even
            # when the process consuming it (VS Code/Codex) expects UTF-8.
            stream.reconfigure(encoding="utf-8", errors="backslashreplace", newline="\n")


@dataclass
class CommandResult:
    output: str
    returncode: int
    record: Path


class CommandFailure(RuntimeError):
    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


class Recorder:
    def __init__(self, action: str, config: str, note: str):
        self.action = action
        self.config = config
        self.note = note
        self.session_id = uuid.uuid4().hex

    def new_record(self, arguments: list[str], kind: str = "command") -> tuple[dict, Path, Path]:
        record_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:10]
        record_path = ROOT / "docs" / "builds" / f"{record_id}.json"
        log_path = ROOT / "build-logs" / f"{record_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": 2,
            "id": record_id,
            "session_id": self.session_id,
            "kind": kind,
            "action": self.action,
            "config": self.config,
            "note": self.note,
            "command": arguments,
            "command_display": command_text(arguments) if arguments else "preflight",
            "cwd": str(ROOT),
            "status": "running",
            "started_at": timestamp(),
            "finished_at": None,
            "elapsed_seconds": None,
            "exit_code": None,
            "platform": platform.platform(),
            "python": sys.version,
            "git_head": source_git_head(),
            "source_fingerprint": source_fingerprint(),
            "log": log_path.relative_to(ROOT).as_posix(),
            "runtime_verified": False,
        }
        # A durable running record exists before launching any external command.
        write_json(record_path, record)
        return record, record_path, log_path

    def append_devlog(self, record: dict, record_path: Path, log_path: Path) -> None:
        devlog = ROOT / "docs" / "DEVLOG.md"
        devlog.parent.mkdir(parents=True, exist_ok=True)
        display_time = datetime.fromisoformat(record["started_at"]).astimezone(DISPLAY_ZONE).isoformat(timespec="seconds")
        note = " ".join(self.note.splitlines()) or "No additional note."
        entry = (
            f"\n### {display_time} · {self.action} · {record['status']}\n\n"
            f"- Config: {self.config}; exit code: {record['exit_code']}; "
            f"elapsed: {record['elapsed_seconds']:.3f}s.\n"
            f"- Command: `{record['command_display'].replace('`', chr(39))}`\n"
            f"- Context: {note}\n"
            f"- Source SHA-256: `{record['source_fingerprint']['digest']}`; "
            f"Git HEAD: `{record['git_head'] or 'unavailable'}`.\n"
            f"- [Record](builds/{record_path.name}) · [Raw log](../build-logs/{log_path.name})\n"
        )
        if record["status"] == "launched":
            entry += "- GUI process launched only; playback, interaction and performance remain unverified.\n"
        if record.get("raw_log"):
            entry += f"- [Exact process output](../{record['raw_log']})\n"
        if record.get("source_changed_during_command"):
            entry += "- Source files changed while this command ran; inspect both fingerprints before treating this as a reproducible build.\n"
        if record.get("error"):
            entry += "- Error: " + " ".join(str(record["error"]).splitlines()) + "\n"
        with devlog.open("a", encoding="utf-8", newline="\n") as stream:
            if devlog.stat().st_size == 0:
                stream.write("# Development command log\n\nGenerated by scripts/dev.py. Timestamps use Asia/Shanghai (UTC+08:00).\n")
            stream.write(entry)

    def finish(self, record: dict, record_path: Path, log_path: Path, started: float) -> None:
        record["finished_at"] = timestamp()
        record["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        record["source_fingerprint_end"] = source_fingerprint()
        record["source_changed_during_command"] = (
            record["source_fingerprint"]["files"] != record["source_fingerprint_end"]["files"]
        )
        write_json(record_path, record)
        self.append_devlog(record, record_path, log_path)

    def preflight_failure(self, message: str) -> None:
        started = time.perf_counter()
        record, record_path, log_path = self.new_record([], "preflight")
        record.update(status="failed", exit_code=2, error=message)
        log_path.write_text(message + "\n", encoding="utf-8")
        self.finish(record, record_path, log_path, started)

    def execute(self, arguments: list[str], *, launch_only: bool = False) -> CommandResult:
        started = time.perf_counter()
        record, record_path, log_path = self.new_record(arguments)
        raw_path = log_path.with_suffix(".raw.log")
        record["raw_log"] = raw_path.relative_to(ROOT).as_posix()
        # A local override keeps MSVC diagnostics readable without changing the
        # user's environment. Other tools may still emit their OS code page.
        environment = os.environ.copy()
        environment["VSLANG"] = "1033"
        record["environment_overrides"] = {"VSLANG": "1033"}
        record["log_encoding"] = "UTF-8; process bytes preserved separately"
        write_json(record_path, record)
        captured: list[str] = []
        captured_length = 0
        process: subprocess.Popen | None = None
        failure: CommandFailure | None = None
        interrupted = False

        print(f"\n> {record['command_display']}", flush=True)
        print(f"  Record: {record_path.relative_to(ROOT)}", flush=True)
        try:
            with log_path.open("a", encoding="utf-8", newline="") as log, raw_path.open("wb") as raw:
                def emit(value: str | bytes) -> None:
                    nonlocal captured_length
                    if isinstance(value, bytes):
                        raw.write(value)
                        raw.flush()
                        text = decode_output(value)
                    else:
                        text = value
                    log.write(text)
                    log.flush()
                    try:
                        sys.stdout.write(text)
                        sys.stdout.flush()
                    except UnicodeEncodeError:
                        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8")
                        sys.stdout.write(safe)
                        sys.stdout.flush()
                    if captured_length < 1024 * 1024:
                        captured.append(text[:1024 * 1024 - captured_length])
                        captured_length += len(captured[-1])

                if launch_only:
                    # The native GUI is intentionally visible. It owns its lifecycle;
                    # later output remains in this log after the CLI has returned.
                    process = subprocess.Popen(arguments, cwd=ROOT, stdin=subprocess.DEVNULL,
                                               stdout=raw, stderr=subprocess.STDOUT, shell=False,
                                               env=environment)
                    record.update(status="launched", pid=process.pid, exit_code=None)
                    emit(f"Launched PID {process.pid}; this is not a runtime verification.\n")
                    emit(f"Subsequent application output (exact bytes): {raw_path}\n")
                else:
                    group_options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                                     if os.name == "nt" else {"start_new_session": True})
                    process = subprocess.Popen(
                        arguments, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        shell=False, env=environment, **group_options,
                    )
                    record["pid"] = process.pid
                    try:
                        assert process.stdout is not None
                        for line in process.stdout:
                            emit(line)
                        code = process.wait()
                    except KeyboardInterrupt:
                        interrupted = True
                        record["status"] = "interrupted"
                        emit("\nInterrupted; stopping the command process group.\n")
                        self.stop_process(process, emit)
                        code = 130
                    finally:
                        if process.stdout is not None:
                            process.stdout.close()
                    record["exit_code"] = code
                    if not interrupted:
                        record["status"] = "succeeded" if code == 0 else "failed"
                    if code != 0:
                        failure = CommandFailure(f"Command failed with code {code}; see {log_path}", code)
                        record["error"] = str(failure)
        except KeyboardInterrupt:
            interrupted = True
            record.update(status="interrupted", exit_code=130, error="Interrupted during command startup")
            if process is not None and not launch_only:
                self.stop_process(process, lambda value: print(decode_output(value) if isinstance(value, bytes) else value, end="", flush=True))
        except OSError as error:
            record.update(status="failed", exit_code=127, error=str(error))
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\nLaunch or I/O error: {error}\n")
            failure = CommandFailure(f"Cannot execute {arguments[0]}: {error}. See {log_path}", 127)
            if process is not None and not launch_only:
                self.stop_process(process, lambda value: print(decode_output(value) if isinstance(value, bytes) else value, end="", flush=True))
        finally:
            self.finish(record, record_path, log_path, started)

        if interrupted:
            raise KeyboardInterrupt
        if failure is not None:
            raise failure
        return CommandResult("".join(captured), 0, record_path)

    @staticmethod
    def stop_process(process: subprocess.Popen, emit) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            remaining, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                remaining, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                emit("Command did not finish after termination; inspect remaining child processes.\n")
                return
        if remaining:
            emit(remaining)


def dependency_spec(data: dict, name: str) -> tuple[str, str]:
    specification = data.get(name)
    if not isinstance(specification, dict):
        raise ValueError(f"cmake/dependencies.json needs an object named {name!r}")
    repository = specification.get("repository")
    commit = specification.get("commit")
    if not isinstance(repository, str) or not repository.startswith("https://"):
        raise ValueError(f"{name}.repository must be an HTTPS Git URL")
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError(f"{name}.commit must be a full 40-character Git commit hash")
    return repository, commit.lower()


def verify_head(recorder: Recorder, path: Path, expected: str) -> None:
    actual = recorder.execute(["git", "-C", str(path), "rev-parse", "HEAD"]).output.strip().lower()
    if actual != expected:
        raise ValueError(
            f"Pinned dependency mismatch at {path}: expected {expected}, found {actual!r}. "
            "Existing files were not reset. Preserve any local changes and resolve the checkout before retrying."
        )


def bootstrap(recorder: Recorder) -> None:
    manifest = ROOT / "cmake" / "dependencies.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read {manifest}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("cmake/dependencies.json must contain a JSON object")
    repository, commit = dependency_spec(data, "tracktion")
    juce_repository, juce_commit = dependency_spec(data, "juce")
    # The engine is patched in an owned checkout, never the shared _deps tree.
    checkout = ROOT / ".cache" / "monitor-engine"
    checkout.parent.mkdir(parents=True, exist_ok=True)

    if checkout.exists() and not checkout.is_dir():
        raise ValueError(f"Dependency path is not a directory: {checkout}")
    new_checkout = not checkout.exists() or not any(checkout.iterdir())
    if new_checkout:
        recorder.execute(["git", "clone", "--no-checkout", "--depth", "1", "--no-tags",
                          repository, str(checkout)])
    elif not (checkout / ".git").exists():
        raise ValueError(f"{checkout} is non-empty and is not a Git checkout; it was left unchanged")

    # A failed --no-checkout clone/fetch can be resumed without overwriting a
    # user's populated worktree. A populated checkout must already match HEAD.
    only_git_metadata = all(path.name == ".git" for path in checkout.iterdir())
    if new_checkout or only_git_metadata:
        actual_repository = recorder.execute(
            ["git", "-C", str(checkout), "remote", "get-url", "origin"]
        ).output.strip()
        if actual_repository.rstrip("/") != repository.rstrip("/"):
            raise ValueError(f"Incomplete checkout origin differs from the manifest: {actual_repository!r}")
        recorder.execute(["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", commit])
        recorder.execute(["git", "-C", str(checkout), "checkout", "--detach", commit])
    verify_head(recorder, checkout, commit)

    # Override only this checkout's submodule URL, not the global Git config.
    recorder.execute(["git", "-C", str(checkout), "config", "--local",
                      "submodule.modules/juce.url", juce_repository])
    recorder.execute(["git", "-C", str(checkout), "submodule", "update", "--init", "--depth", "1",
                      "modules/juce"])
    verify_head(recorder, checkout / "modules" / "juce", juce_commit)
    recorder.execute([sys.executable, str(ROOT / "scripts" / "bootstrap_vst2.py")])
    recorder.execute([sys.executable, str(ROOT / "scripts" / "bootstrap_asio.py")])
    recorder.execute([sys.executable, str(ROOT / "scripts" / "bootstrap_stretch.py")])
    recorder.execute([sys.executable, str(ROOT / "scripts" / "apply_engine_patches.py"), "apply", "--engine-root", str(checkout)])
    print("Pinned Tracktion, JUCE and VST2 interface dependencies verified. No application build has run.", flush=True)


def configure(recorder: Recorder) -> None:
    recorder.execute(["cmake", "--preset", "windows-msvc"])


def build(recorder: Recorder, target: str | None) -> None:
    arguments = ["cmake", "--build", "--preset", f"windows-{recorder.config.lower()}", "--parallel", "2"]
    if target:
        arguments.extend(["--target", target])
    recorder.execute(arguments)


def test(recorder: Recorder) -> None:
    recorder.execute(["ctest", "--preset", f"windows-{recorder.config.lower()}", "--output-on-failure"])


def main() -> int:
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("bootstrap", "configure", "build", "test", "check", "run"))
    parser.add_argument("--config", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--target", help="Optional CMake target for build/check")
    parser.add_argument("--note", default="", help="Context saved with every external command")
    arguments = parser.parse_args()
    if arguments.target and arguments.action not in ("build", "check"):
        parser.error("--target is only valid for build/check")
    recorder = Recorder(arguments.action, arguments.config, arguments.note)
    try:
        if arguments.action == "bootstrap":
            bootstrap(recorder)
        elif arguments.action == "configure":
            configure(recorder)
        elif arguments.action == "build":
            build(recorder, arguments.target)
        elif arguments.action == "test":
            test(recorder)
        elif arguments.action == "check":
            configure(recorder)
            build(recorder, arguments.target)
            test(recorder)
        elif arguments.action == "run":
            executable = ROOT / "build" / "bin" / arguments.config / "E-musician.exe"
            if not executable.is_file():
                raise ValueError(f"Executable not found: {executable}. Build the {arguments.config} configuration first.")
            recorder.execute([str(executable)], launch_only=True)
    except KeyboardInterrupt:
        print("\nDevelopment command interrupted; completed command records remain available.", file=sys.stderr)
        return 130
    except CommandFailure as error:
        print(f"Error: {error}", file=sys.stderr)
        return error.returncode if 0 < error.returncode < 256 else 1
    except (OSError, ValueError) as error:
        message = str(error)
        print(f"Setup error: {message}", file=sys.stderr)
        try:
            recorder.preflight_failure(message)
        except OSError as logging_error:
            print(f"Could not save the failure record: {logging_error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
