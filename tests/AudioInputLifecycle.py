"""Opt-in physical input lifecycle probe; no playback, monitoring, or vendor UI.

Run through the repository Recorder. The parent preserves Settings.xml byte for
byte, refuses an already running E-musician, and bounds only its owned process
tree with a Windows Job Object. Captured silence is reported, never passed off
as proof that a microphone, cable, or instrument produced a signal.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError
from InstalledPluginAudit import OwnedJob


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def hosts(exe_name: str) -> list[dict]:
    """Read names/PIDs only; never read arguments, handles, or private data."""
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    result = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        found = api.Process32FirstW(handle, ctypes.byref(entry))
        while found:
            if entry.szExeFile.casefold() in {exe_name.casefold(), "e-musician.exe"}:
                result.append({"pid": int(entry.th32ProcessID), "name": entry.szExeFile})
            found = api.Process32NextW(handle, ctypes.byref(entry))
    finally:
        api.CloseHandle(handle)
    return result


def pcm_metrics(path: Path) -> dict:
    with wave.open(str(path), "rb") as reader:
        channels, width, rate, frames = (reader.getnchannels(), reader.getsampwidth(),
                                         reader.getframerate(), reader.getnframes())
        if reader.getcomptype() != "NONE" or width not in (1, 2, 3, 4) or not frames:
            raise AssertionError("Recording is empty or is not supported integer PCM")
        sums, peaks, nonzero, read_frames = [0.0] * channels, [0.0] * channels, [0] * channels, 0
        while data := reader.readframes(8192):
            stride = channels * width
            if len(data) % stride:
                raise AssertionError("Recorded PCM frame is truncated")
            read_frames += len(data) // stride
            for offset in range(0, len(data), stride):
                for channel in range(channels):
                    raw = data[offset + channel * width:offset + (channel + 1) * width]
                    value = ((raw[0] - 128) / 128.0 if width == 1
                             else int.from_bytes(raw, "little", signed=True) / float(1 << (width * 8 - 1)))
                    sums[channel] += value * value
                    peaks[channel] = max(peaks[channel], abs(value))
                    nonzero[channel] += value != 0
        if read_frames != frames:
            raise AssertionError("WAV header length differs from decoded PCM")
    return {"path": str(path), "sha256": sha(path.read_bytes()), "sample_rate": rate,
            "channels": channels, "sample_width": width, "frames": frames,
            "seconds": frames / rate, "rms": [math.sqrt(value / frames) for value in sums],
            "peak": peaks, "nonzero_samples": nonzero, "digital_silence": not any(nonzero),
            "physical_source_identity_verified": False, "listening_verified": False}


def configuration(device: dict) -> dict:
    return {key: device.get(key) for key in ("driver_type", "device_name", "input_device_name",
            "output_device_name", "sample_rate", "buffer_size", "active_input_channels", "input_stereo_pairs")}


def child(args) -> int:
    deadline = time.monotonic() + 15
    while not (args.out / "owned-process-ready").exists():
        if time.monotonic() >= deadline:
            return 2
        time.sleep(.02)
    report = {"status": "running", "started_utc": utc(), "checks": [], "captures": [],
              "scope": "Physical driver open, input masks, routes and WAV persistence; no listening or signal identity claim",
              "vendor_control_panel_tested": False, "hardware_playback_tested": False}
    client = None

    def save():
        (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def checked(name):
        report["checks"].append(name)
        save()

    def command(name, values=None):
        response = client.request({"command": name, "args": values or {}})
        # request(wait=True) retains the accepted acknowledgement and attaches
        # terminal job evidence; save/open are not immediate completed replies.
        if response.get("status") == "accepted":
            job = response.get("job_completion") or {}
            if job.get("status") not in {"completed", "ready", "applied"}:
                raise ControlError("Background command did not complete: " + repr(job))
            return job.get("result") or {}
        return client.completed(response)

    def reject(name, values):
        try:
            command(name, values)
        except ControlError as error:
            return str(error)
        raise AssertionError("Invalid request was accepted: " + name + " " + repr(values))

    def device():
        return command("get_audio_devices")

    def route(channels):
        found = [entry for entry in command("get_recording_inputs")["inputs"]
                 if not entry["midi"] and entry.get("channels") == channels]
        if len(found) != 1:
            raise AssertionError("Expected one physical route for channels " + repr(channels))
        return found[0]

    def setup(channels, pairs=()):
        command("configure_audio_device", {"driver_type": args.driver_type, "device_name": args.device_name,
                 "input_channels": channels, "input_stereo_pairs": list(pairs)})
        state = device()
        assert state["driver_type"] == args.driver_type and state["device_name"] == args.device_name
        assert state.get("device_open") and state["active_input_channels"] == channels
        assert state["input_stereo_pairs"] == list(pairs)
        return state

    def new_project():
        command("new_project")
        command("set_master_gain", {"gain_db": -60})
        command("set_recording_preferences", {"count_in_enabled": False, "metronome_enabled": False})
        report.setdefault("owned_recording_directories", []).append(command("get_recording_state").get("recording_directory"))

    def add_track(label, channels):
        command("create_track", {"kind": "audio", "name": label})
        track = client.state()["tracks"][-1]["id"]
        command("set_track_input", {"track_id": track, "input_device_id": route(channels)["id"]})
        command("set_input_monitor", {"track_id": track, "mode": "off"})
        return track

    def capture(label, tracks, expected_channels):
        before = client.state()
        assert not before["playing"] and all(t["monitor"] == "off" for t in before["tracks"])
        start_device = configuration(device())
        command("start_recording")
        guard = reject("configure_audio_device", {"input_channels": []})
        assert configuration(device()) == start_device
        end = time.monotonic() + args.seconds
        samples = []
        while time.monotonic() < end:
            state = client.state()
            assert state["recording"] and all(t["monitor"] == "off" for t in state["tracks"])
            samples.append({key: state.get(key) for key in ("position_seconds", "xruns", "cpu_usage")})
            time.sleep(.1)
        command("stop_recording")
        end = time.monotonic() + 15
        while client.state()["recording_finalizing"]:
            if time.monotonic() > end:
                raise AssertionError("Recording finalization exceeded 15 seconds")
            time.sleep(.02)
        after = client.state()
        assert after["revision"] == before["revision"] + 1
        for tid in tracks:
            command("set_track_armed", {"track_id": tid, "armed": False})
        project = args.out / (label + ".emproj")
        command("save_project", {"path": str(project)})
        stored = json.loads(project.read_text(encoding="utf-8-sig"))
        assets = {item["id"]: item for item in stored["assets"]}
        result = {"case": label, "configuration": start_device, "recording_guard": guard,
                  "transport_samples": samples, "xruns_delta": after.get("xruns", 0) - before.get("xruns", 0), "wav": []}
        for tid, channels in zip(tracks, expected_channels):
            track = next(track for track in after["tracks"] if track["id"] == tid)
            assert len(track["clips"]) == 1 and track["clips"][0]["duration_seconds"] >= args.seconds * .75
            source = (project.parent / assets[track["clips"][0]["asset_id"]]["source"]).resolve(strict=True)
            # Persisted assets must belong to this owned test directory.
            source.relative_to(args.out.resolve())
            metrics = pcm_metrics(source)
            assert metrics["channels"] == channels and metrics["sample_rate"] == start_device["sample_rate"]
            assert metrics["seconds"] >= args.seconds * .75
            result["wav"].append({"track": track["name"], **metrics})
        command("undo")
        assert all(not track["clips"] for track in client.state()["tracks"])
        command("redo")
        assert all(len(track["clips"]) == 1 for track in client.state()["tracks"])
        command("open_project", {"path": str(project)})
        reopened = client.state()
        assert not reopened["dirty"] and all(not t["armed"] and t["monitor"] == "off" for t in reopened["tracks"])
        report["captures"].append(result)
        checked(label + ": physical input writes readable PCM, one Undo/Redo, save/reopen disarmed; silence separately reported")

    try:
        if hosts(args.exe.name):
            raise RuntimeError("An E-musician process appeared before the probe; no existing process was touched")
        client = Client(args.exe, timeout=45, offline_test=False)
        report["owned_host_pid"] = client.process.pid
        report["startup_device"] = command("get_audio_devices", {"scan": True})
        command("stop")
        new_project()
        drivers = [item for item in report["startup_device"]["drivers"] if item["driver_type"] == args.driver_type]
        assert len(drivers) == 1 and args.device_name in drivers[0]["inputs"] and args.device_name in drivers[0]["outputs"]
        initial = setup([])
        if len(initial["input_channels"]) < 2:
            raise AssertionError("This In1/In2 probe requires two enumerated physical inputs")
        tid = add_track("Disabled input guard", [0])
        report["disabled_arm_refusal"] = reject("set_track_armed", {"track_id": tid, "armed": True})
        assert device()["active_input_channels"] == [] and not client.state()["tracks"][0]["armed"]
        checked("Explicitly disabled physical input stays disabled when arming is refused")

        new_project()
        setup([0])
        first = add_track("In1 mono", [0])
        command("set_track_armed", {"track_id": first, "armed": True})
        second = add_track("In2 mono", [1])
        reject("set_track_armed", {"track_id": second, "armed": True})
        assert device()["active_input_channels"] == [0]
        command("set_track_armed", {"track_id": first, "armed": False})
        setup([0, 1])
        for tid, channels in ((first, [0]), (second, [1])):
            command("set_track_input", {"track_id": tid, "input_device_id": route(channels)["id"]})
            command("set_track_armed", {"track_id": tid, "armed": True})
        capture("two-mono-inputs", [first, second], [1, 1])

        new_project()
        setup([1])
        before = configuration(device())
        command("configure_audio_device", {"sample_rate": before["sample_rate"], "buffer_size": before["buffer_size"]})
        assert configuration(device()) == before
        checked("Sample rate/buffer update preserves sparse In2 mask and mono pairing")
        for invalid in ({"input_channels": [True]}, {"input_channels": [0.5]}, {"input_channels": ["0"]},
                        {"input_channels": [len(device()["input_channels"])]}, {"input_stereo_pairs": [1]},
                        {"device_name": "E-musician deliberately absent test endpoint"}):
            rejection = reject("configure_audio_device", invalid)
            assert configuration(device()) == before
            report.setdefault("configuration_refusals", []).append({"args": invalid, "error": rejection})
        checked("Invalid types, channel bounds, stereo pairs and missing endpoint leave actual configuration intact")
        tid = add_track("In2 only mono", [1])
        command("set_track_armed", {"track_id": tid, "armed": True})
        capture("in2-only", [tid], [1])

        new_project()
        setup([0, 1], [0])
        tid = add_track("In1 + In2 stereo", [0, 1])
        command("set_track_armed", {"track_id": tid, "armed": True})
        capture("stereo-input-pair", [tid], [2])
        report["final_device"] = device()
        client.close()
        report["host_exit_code"] = client.process.poll()
        assert report["host_exit_code"] == 0
        client = None
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        if client:
            client.close()
            report["host_exit_code"] = client.process.poll()
        report["finished_utc"] = utc()
        save()
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--driver-type", default="ASIO")
    parser.add_argument("--device-name", required=True)
    parser.add_argument("--seconds", type=float, default=1.5)
    parser.add_argument("--deadline", type=float, default=240)
    parser.add_argument("--allow-physical-capture", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt" or not args.exe.is_file() or not .5 <= args.seconds <= 5 or not 30 <= args.deadline <= 600:
        parser.error("Requires Windows, existing EXE, 0.5..5 seconds and 30..600 second deadline")
    if not args.allow_physical_capture:
        parser.error("Use --allow-physical-capture only for an authorized physical input probe")
    args.exe, args.out = args.exe.resolve(), args.out.resolve()
    if args.child:
        return child(args)
    try:
        args.out.relative_to(ROOT.resolve())
    except ValueError:
        pass  # External artifact directories are outside this repository.
    else:
        ignored = subprocess.run(["git", "check-ignore", "--quiet", "--", str(args.out)], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ignored.returncode != 0:
            parser.error("Within the repository, --out must be ignored (for example build/audio-input-live/<run>)")
    args.out.mkdir(parents=True, exist_ok=False)
    settings = Path(os.environ["APPDATA"]) / "E-musician/Settings.xml"
    manifest = {"started_utc": utc(), "exe": str(args.exe), "exe_sha256": sha(args.exe.read_bytes()),
                "script_sha256": sha(Path(__file__).read_bytes()), "status": "running",
                "existing_processes_touched": False, "settings_path": str(settings)}
    before = None
    had_settings = False
    job = None
    process = None
    try:
        if existing := hosts(args.exe.name):
            manifest["existing_hosts"] = existing
            raise RuntimeError("Close E-musician normally before the hardware probe; no existing process was stopped")
        had_settings = settings.exists()
        before = settings.read_bytes() if had_settings else b""
        manifest["settings_before_sha256"] = sha(before) if had_settings else None
        (args.out / "Settings.before.xml").write_bytes(before)
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child", "--exe", str(args.exe),
                   "--out", str(args.out), "--driver-type", args.driver_type, "--device-name", args.device_name,
                   "--seconds", str(args.seconds), "--allow-physical-capture"]
        job = OwnedJob()
        with (args.out / "probe.log").open("wb") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            job.assign(process)
            (args.out / "owned-process-ready").write_text("assigned\n", encoding="ascii")
            try:
                manifest["exit_code"] = process.wait(timeout=args.deadline)
            except subprocess.TimeoutExpired:
                job.kill()
                manifest["timed_out"] = True
                manifest["exit_code"] = process.wait(timeout=10)
        report_path = args.out / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        manifest["status"] = "passed" if manifest["exit_code"] == 0 and report.get("status") == "passed" else "failed"
    except Exception as error:
        manifest.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        if job:
            job.close()  # Kills only owned descendants, including timeout/crash orphans.
        if process and process.poll() is None:
            process.wait(timeout=10)
        if before is not None:
            remaining = hosts(args.exe.name)
            if remaining:
                manifest.update(status="failed", settings_restored=False, restore_deferred_existing_hosts=remaining)
            else:
                try:
                    if had_settings:
                        settings.write_bytes(before)
                    elif settings.exists():
                        settings.unlink()
                    after = settings.read_bytes() if settings.exists() else b""
                    manifest["settings_restored"] = after == before and settings.exists() == had_settings
                    manifest["settings_after_sha256"] = sha(after) if settings.exists() else None
                    if not manifest["settings_restored"]:
                        manifest["status"] = "failed"
                except Exception as error:
                    manifest.update(status="failed", settings_restored=False, restore_error=str(error))
        manifest["finished_utc"] = utc()
        (args.out / "lifecycle.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": manifest["status"], "manifest": str(args.out / "lifecycle.json"),
                          "settings_restored": manifest.get("settings_restored")}, ensure_ascii=False), flush=True)
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
