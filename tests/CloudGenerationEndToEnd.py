"""Real ACE/SSH/desktop acceptance, with an owned offline audio device.

This invokes the rented GPU. It does not open user projects or claim listening
quality/physical ASIO acceptance. Invoke explicitly through scripts.dev.Recorder with your own configured server.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_paths import compute_root
from agent_client import Client, ControlError
from cloud.run_generation import inspect_wav
from MusicAgentIntegration import protected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    directory = (compute_root() / "experiments") / ("daw-ace-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    executable = directory / "E-musician.exe"
    shutil.copy2(args.exe, executable)
    packaged_runtime = args.exe.resolve().parent / "runtime"
    if packaged_runtime.is_dir():
        shutil.copytree(packaged_runtime, directory / "runtime")
    report = {"passed": False, "physical_audio": False, "real_music_model": True,
              "real_llm": False, "mode": "real-ACE-SSH-native-offline",
              "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "checks": []}
    baseline = protected()
    client = None
    started = time.monotonic()

    def read(command, arguments=None):
        return client.completed(client.raw({"command": command, "args": arguments or {}}))

    def write(command, arguments=None, wait=True):
        return client.request({"command": command, "args": arguments or {}}, wait=wait)

    def wait_generation(job_id):
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            value = read("get_generation_job", {"job_id": job_id})
            if value["status"] in {"ready", "applied", "completed"}:
                return value
            if value["status"] in {"failed", "cancelled", "stale", "interrupted"}:
                raise AssertionError(value)
            time.sleep(.2)
        raise AssertionError("Generation timed out: " + repr(value))

    try:
        client = Client(executable, timeout=120, offline_test=True)
        initial = client.state()
        assert not initial["tracks"]
        caps = read("get_generation_capabilities")
        assert caps["available"], caps
        request = {"prompt": "Instrumental warm jazz piano trio, acoustic bass, soft brushed drums, relaxed groove, clean studio sound, no vocals.",
                   "lyrics": "", "duration_seconds": 12, "seed": 16384, "timeline_start_seconds": 2.0}
        response = write("start_generation", request, False)
        rid = response["result"]["result_id"]
        wait_generation(response["result"]["job_id"])
        candidate = read("get_generation_result", {"result_id": rid})
        report["candidate"] = candidate
        report["generation_elapsed_seconds"] = time.monotonic() - started
        assert client.state()["revision"] == initial["revision"]
        assert not client.state()["tracks"]
        assert len(candidate["result_hash"]) == 64
        assert candidate["audio"]["duration_seconds"] > 0
        report["checks"].append("Real remote ACE returns verified local candidate without editing project")
        response = write("accept_generation_result", {"result_id": rid, "result_hash": candidate["result_hash"]}, False)
        wait_generation(response["result"]["job_id"])
        state = client.state()
        assert len(state["tracks"]) == 1 and len(state["tracks"][0]["clips"]) == 1
        assert state["revision"] == initial["revision"] + 1
        clip = state["tracks"][0]["clips"][0]
        assert abs(clip["duration_seconds"] - candidate["audio"]["duration_seconds"]) < .002
        imported_revision = state["revision"]
        try:
            write("accept_generation_result", {"result_id": rid, "result_hash": candidate["result_hash"]}, False)
        except ControlError:
            pass
        assert client.state()["revision"] == imported_revision
        assert len(client.state()["tracks"]) == 1
        write("undo")
        assert not client.state()["tracks"]
        write("redo")
        assert len(client.state()["tracks"]) == 1
        report["checks"].append("Accept creates one track, duplicate creates no edit, one Undo/Redo")
        project = directory / "ace-generated.emproj"
        write("save_project", {"path": str(project)})
        saved = json.loads(project.read_text(encoding="utf-8"))
        assert saved["schema"] == 7
        assert saved.get("generations") and saved.get("assets")
        report["project"] = str(project)
        report["project_sha256"] = hashlib.sha256(project.read_bytes()).hexdigest()
        client.close()
        client = None
        offline_root = directory / "offline-generation"
        offline_root.mkdir()
        (offline_root / "registry.json").write_text('{"available":false}', encoding="utf-8")
        # New process receives an unavailable generation configuration: saved
        # playback/import must not query the cloud or resolve remote paths.
        with patch.dict(os.environ, {"EMUSICIAN_GENERATION_ROOT": str(offline_root)}):
            client = Client(executable, timeout=120, offline_test=True)
        assert read("get_generation_capabilities")["available"] is False
        write("open_project", {"path": str(project)})
        assert len(client.state()["tracks"]) == 1
        rendered = directory / "offline-mix.wav"
        duration = candidate["audio"]["duration_seconds"]
        write("export_wav", {"path": str(rendered), "start_seconds": 0,
                             "end_seconds": duration + 4, "sample_rate": 48000, "bit_depth": 16, "tail_seconds": 0})
        assert rendered.is_file() and rendered.stat().st_size > 44
        import wave
        with wave.open(str(rendered), "rb") as wav:
            metadata = {"sha256": hashlib.sha256(rendered.read_bytes()).hexdigest(),
                        "duration_seconds": wav.getnframes()/wav.getframerate(), "sample_rate": wav.getframerate(), "channels": wav.getnchannels()}
        _, peaks = inspect_wav(rendered, metadata)
        assert max(peaks) > 0
        report["render"] = metadata
        report["checks"].append("Schema7 saves local assets, reopens with cloud disabled and renders non-silent audio")
        assert protected() == baseline, "A protected user project or setting changed"
        report["checks"].append("User settings and test projects unchanged")
        report["passed"] = True
    finally:
        if client:
            client.close()
        report["elapsed_seconds"] = time.monotonic() - started
        (directory / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": report["checks"], "report": str(directory / "report.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
