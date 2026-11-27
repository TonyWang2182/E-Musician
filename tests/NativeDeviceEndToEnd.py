"""Offline native sampler/rack end-to-end test using only disposable fixtures.

Run through scripts.dev.Recorder, e.g. Recorder(...).execute([sys.executable,
    'tests/NativeDeviceEndToEnd.py', '--exe', '.../E-musician.exe']).
No user projects, physical audio devices, third-party plugins, or model APIs.
The real controlled child is owned and closed by Client, and all media/projects
are contained in a unique ignored build/native-device-e2e/UUID directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError  # noqa: E402
from MusicAgentIntegration import protected  # noqa: E402


def make_fixture(path: Path) -> None:
    rate, duration = 48000, 0.14
    frames = int(rate * duration)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", round(11000 * math.sin(2 * math.pi * 440 * i / rate)))
                                   for i in range(frames)))


def rms_window(path: Path, start: float, duration: float) -> float:
    with wave.open(str(path), "rb") as source:
        if source.getcomptype() != "NONE" or source.getsampwidth() not in (2, 3, 4):
            raise AssertionError("Expected uncompressed integer PCM export")
        rate, width, channels = source.getframerate(), source.getsampwidth(), source.getnchannels()
        source.setpos(int(start * rate))
        data = source.readframes(int(duration * rate))
    stride = width * channels
    samples = [int.from_bytes(data[i:i + width], "little", signed=True) / (2 ** (8 * width - 1))
               for i in range(0, len(data) - stride + 1, stride)]
    if not samples:
        raise AssertionError(f"Empty render window at {start:.3f}s")
    return math.sqrt(sum(value * value for value in samples) / len(samples))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not args.exe.is_file() or args.timeout <= 0:
        parser.error("--exe must exist and --timeout must be positive")
    directory = ROOT / "build" / "native-device-e2e" / str(uuid.uuid4())
    directory.mkdir(parents=True)
    fixture = directory / "synthetic-tone.wav"
    bad = directory / "invalid.wav"
    make_fixture(fixture)
    bad.write_bytes(b"Not a WAV file; owned integration fixture only.")
    source_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    protected_before = protected()
    report = {"mode": "owned-offline-control-stdio", "physical_audio": False,
              "external_plugins": False, "existing_windows_touched": False,
              "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              "fixture_sha256": source_hash, "checks": [], "passed": False}
    client = None

    def checked(label: str) -> None:
        report["checks"].append(label)

    def snapshot() -> dict:
        return client.state()

    def write(command: str, arguments: dict | None = None) -> dict:
        return client.request({"command": command, "args": arguments or {}}, wait=True)

    def native(track_id: str) -> dict:
        # The current native description is logically read-only but this early
        # protocol routes it through the revision-checked generic command path.
        # A worker may commit between state() and raw(); retry ONLY explicit
        # revision conflicts, never a timeout, wrong-project response or write.
        deadline = time.monotonic() + min(args.timeout, 5.0)
        while time.monotonic() < deadline:
            state = snapshot()
            reply = client.raw({"command": "get_native_instrument", "args": {"track_id": track_id},
                                "request_id": str(uuid.uuid4()), "project_id": state["project_id"],
                                "expected_revision": state["revision"]})
            if reply.get("status") == "conflict":
                continue
            return client.completed(reply)
        raise ControlError("Native read repeatedly conflicted with worker commits")

    def wait_ready(track_id: str, *, newer_than: int | None = None) -> dict:
        deadline = time.monotonic() + args.timeout
        last = {}
        while time.monotonic() < deadline:
            state = snapshot()
            last = native(track_id)
            loading = any(job.get("kind") == "native_instrument" and job.get("status") == "running"
                          for job in state.get("jobs", []))
            if last.get("load_status") == "error" and not loading:
                raise AssertionError("Native load failed: " + str(last.get("error")))
            if last.get("load_status") == "ready" and not loading and (newer_than is None or state["revision"] > newer_than):
                return last
            time.sleep(0.03)
        raise AssertionError("Native instrument did not become ready: " + repr(last))

    def edit_native(command: str, track_id: str, **kwargs) -> dict:
        before = snapshot()["revision"]
        write(command, {"track_id": track_id, **kwargs})
        return wait_ready(track_id, newer_than=before)

    def track(name: str) -> str:
        write("create_track", {"kind": "instrument", "name": name})
        matches = [item for item in snapshot()["tracks"] if item["name"] == name]
        assert len(matches) == 1
        return matches[0]["id"]

    def clip_with_notes(track_id: str, start: float, length: float, notes: list[dict]) -> None:
        write("create_midi_clip", {"track_id": track_id, "start_beats": start, "length_beats": length})
        item = next(item for item in snapshot()["tracks"] if item["id"] == track_id)
        assert len(item["clips"]) == 1
        write("write_notes", {"clip_id": item["clips"][0]["id"], "notes": notes})

    def render(name: str) -> Path:
        output = directory / name
        write("export_wav", {"path": str(output), "start_seconds": 0.0, "end_seconds": 6.0,
                             "tail_seconds": 0.0, "sample_rate": 48000, "bit_depth": 24, "realtime": False})
        assert output.is_file() and output.stat().st_size > 1000
        return output

    try:
        client = Client(args.exe, timeout=args.timeout, show=False, offline_test=True)
        assert snapshot()["tracks"] == [], "Owned process did not start with a new project"
        sampler_id = track("E2E sampler")
        description = edit_native("add_native_instrument", sampler_id, type="sampler")
        assert description["type"] == "sampler" and len(description["pads"]) == 1
        description = edit_native("set_native_sample", sampler_id, pad=0, path=str(fixture))
        shared_id = description["pads"][0]["asset_id"]
        assert shared_id
        assert description["pads"][0].get("sample_sha256") == source_hash, "Waveform identity must match loaded sample bytes"
        clip_with_notes(sampler_id, 0.0, 2.0,
                        [{"pitch": 60, "start_beats": 0.5, "length_beats": 0.2, "velocity": 100, "channel": 1}])
        checked("sampler attaches, loads sample asynchronously and accepts MIDI")

        rack_id = track("E2E rack")
        description = edit_native("add_native_instrument", rack_id, type="drum_rack")
        assert description["type"] == "drum_rack" and len(description["pads"]) == 16
        for index in range(16):
            description = edit_native("set_native_sample", rack_id, pad=index, path=str(fixture))
            assert description["pads"][index]["asset_id"] == shared_id, "Shared path should reuse the same asset ID"
            assert description["pads"][index].get("sample_sha256") == source_hash, "Each loaded pad exposes the correct waveform identity"
        clip_with_notes(rack_id, 2.0, 9.0,
                        [{"pitch": 36 + i, "start_beats": i * 0.5, "length_beats": 0.2,
                          "velocity": 100, "channel": 1} for i in range(16)])
        checked("all 16 rack pads load one shared asset and receive independent MIDI pitches")

        unmuted = render("all-pads.wav")
        sampler_level = rms_window(unmuted, 0.27, 0.05)
        pad_levels = [rms_window(unmuted, 1.02 + i * 0.25, 0.05) for i in range(16)]
        assert sampler_level > 0.005 and min(pad_levels) > 0.005, (sampler_level, pad_levels)
        report["sampler_rms"] = sampler_level
        report["pad_rms"] = pad_levels
        checked("offline WAV contains measured sampler output and audible-level signal at each pad event")

        mute = edit_native("set_native_pad", rack_id, pad=8, gain_db=0.0, muted=True)
        assert mute["pads"][8]["muted"] is True
        muted_render = render("pad-eight-muted.wav")
        muted_level = rms_window(muted_render, 1.02 + 8 * 0.25, 0.05)
        neighbor_level = rms_window(muted_render, 1.02 + 9 * 0.25, 0.05)
        assert muted_level < 1e-5 and neighbor_level > 0.005, (muted_level, neighbor_level)
        write("undo")
        restored = wait_ready(rack_id)
        assert restored["pads"][8]["muted"] is False, "Undo did not restore pad mute"
        write("redo")
        restored = wait_ready(rack_id)
        assert restored["pads"][8]["muted"] is True, "Redo did not restore pad mute"
        checked("pad mute changes measured output and Undo/Redo restore the parameter")

        prior = snapshot()
        old = native(sampler_id)
        accepted = client.request({"command": "set_native_sample", "args": {
            "track_id": sampler_id, "pad": 0, "path": str(bad)}}, wait=False)
        assert accepted["status"] == "accepted", "Sample decode must return a trackable job"
        bad_job = accepted.get("result", {}).get("job_id")
        assert bad_job and bad_job.startswith("native-"), accepted
        deadline = time.monotonic() + args.timeout
        job = {}
        while time.monotonic() < deadline:
            job = client.completed(client.raw({"command": "get_job", "args": {"job_id": bad_job}}))
            if job.get("status") in {"completed", "failed", "cancelled", "conflict"}:
                break
            time.sleep(0.03)
        else:
            raise AssertionError("Invalid sample job did not reach a terminal state")
        assert job["status"] == "failed" and job.get("error"), job
        state = snapshot(); observed = native(sampler_id)
        assert observed.get("load_status") == "error" and observed.get("error"), "The native panel cannot see the failed load"
        assert state["revision"] == prior["revision"] and observed["pads"][0]["asset_id"] == old["pads"][0]["asset_id"]
        edit_native("set_native_sample", sampler_id, pad=0, path=str(fixture))
        checked("invalid sample is rejected asynchronously without committing an edit")

        envelope = edit_native("set_native_pad", sampler_id, pad=0, gain_db=0.0, muted=False,
                               attack_ms=20.0, release_ms=80.0, one_shot=True)
        assert envelope["pads"][0]["attack_ms"] == 20.0 and envelope["pads"][0]["release_ms"] == 80.0
        assert envelope["pads"][0]["one_shot"] is True
        assert envelope["pads"][0]["sample_sha256"] == source_hash
        write("undo")
        prior_envelope = wait_ready(sampler_id)["pads"][0]
        assert prior_envelope["attack_ms"] == 3.0 and prior_envelope["release_ms"] == 30.0 and prior_envelope["one_shot"] is False
        write("redo")
        assert wait_ready(sampler_id)["pads"][0]["one_shot"] is True
        # Old gain-only commands must retain newly configured musical parameters.
        envelope = edit_native("set_native_pad", sampler_id, pad=0, gain_db=0.0, muted=False)
        assert envelope["pads"][0]["attack_ms"] == 20.0 and envelope["pads"][0]["one_shot"] is True
        checked("sample envelope and playback mode use async commands, survive Undo/Redo and legacy partial edits")

        project = directory / "owned-native.emproj"
        write("save_project", {"path": str(project)})
        saved = json.loads(project.read_text(encoding="utf-8"))
        assert len(saved["assets"]) == 1 and saved["assets"][0]["id"] == shared_id
        bundled = project.parent / saved["assets"][0]["source"]
        assert bundled.is_file() and hashlib.sha256(bundled.read_bytes()).hexdigest() == source_hash
        checked("project archives shared source once and preserves its exact bytes")
        write("open_project", {"path": str(project)})
        reloaded = snapshot()
        assert {item["id"] for item in reloaded["tracks"]} == {sampler_id, rack_id}
        sampler_after, rack_after = wait_ready(sampler_id), wait_ready(rack_id)
        assert sampler_after["pads"][0]["asset_id"] == shared_id
        assert sampler_after["pads"][0]["attack_ms"] == 20.0 and sampler_after["pads"][0]["release_ms"] == 80.0
        assert sampler_after["pads"][0]["one_shot"] is True
        assert all(pad["asset_id"] == shared_id for pad in rack_after["pads"])
        assert rack_after["pads"][8]["muted"] is True
        reopened_render = render("reopened.wav")
        assert rms_window(reopened_render, 0.27, 0.05) > 0.005
        assert rms_window(reopened_render, 1.02 + 8 * 0.25, 0.05) < 1e-5
        assert rms_window(reopened_render, 1.02 + 9 * 0.25, 0.05) > 0.005
        checked("reopen restores both devices, shared assets, mute state and actual rendered audio")

        copy = directory / "owned-copy.emproj"
        write("save_project", {"path": str(copy)})
        copied = json.loads(copy.read_text(encoding="utf-8"))
        copied_asset = copy.parent / copied["assets"][0]["source"]
        assert copied_asset.is_file() and copied_asset != bundled
        assert hashlib.sha256(copied_asset.read_bytes()).hexdigest() == source_hash
        checked("Save As creates an independent shared sample bundle")

        # Use a fresh external fixture so the sampler bank contains a known
        # immutable decode while the old saved manifest remains an independent
        # baseline. Change one PCM byte, preserving the WAV header and length.
        mutable_source = directory / "mutable-source.wav"
        original_bytes = fixture.read_bytes()
        mutable_source.write_bytes(original_bytes)
        edit_native("set_native_sample", sampler_id, pad=0, path=str(mutable_source))
        old_manifest = project.read_bytes()
        changed = bytearray(original_bytes)
        changed[-3] ^= 0x01
        mutable_source.write_bytes(changed)

        def expect_changed_source_failure(command: str, arguments: dict) -> None:
            try:
                write(command, arguments)
            except ControlError as exc:
                assert "changed since it was loaded" in str(exc), str(exc)
            else:
                raise AssertionError(command + " accepted a changed native sample")

        expect_changed_source_failure("save_project", {"path": str(project)})
        assert project.read_bytes() == old_manifest, "Failed save changed an existing project manifest"
        changed_export = directory / "changed-sample-render.wav"
        expect_changed_source_failure("export_wav", {"path": str(changed_export), "start_seconds": 0.0,
                                      "end_seconds": 6.0, "tail_seconds": 0.0,
                                      "sample_rate": 48000, "bit_depth": 24, "realtime": False})
        assert not changed_export.exists(), "Failed export left an apparently successful output"
        checked("changed external native sample rejects save/export and preserves the prior manifest")
        mutable_source.write_bytes(original_bytes)
        write("save_project", {"path": str(project)})
        recovered = render("restored-source.wav")
        assert rms_window(recovered, 0.27, 0.05) > 0.005
        checked("restoring exact source bytes allows save and measured export again")
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == source_hash
        assert protected() == protected_before, "Protected user files changed during owned fixture test"
        checked("synthetic source and protected user files remain unchanged")
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if client is not None:
            client.close()
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                          "report": str(directory / "report.json"), "error": report.get("error")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
