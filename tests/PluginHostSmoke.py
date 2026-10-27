"""Verify explicitly named installed plugins through the real JSONL API.

python tests/PluginHostSmoke.py --exe PATH --module C:/.../Plugin.vst3 --module C:/.../Effect.dll

Each module gets a separate DAW process. No playback or native editor is opened.
The script never clicks authorisation dialogs, writes plugin/sample directories,
or supplies licence data. Its own fixtures/projects/renders/reports are retained
under build/plugin-host-smoke/<UUID>. Only a supplied module is scanned.
Host-parameter history is tested separately from native-editor changes; this
script does not simulate or claim coverage of editing a plugin's own GUI.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
import uuid
import wave
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normal_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def signed_hex(value: str) -> int:
    integer = int(value or "0", 16) & 0xFFFFFFFF
    return integer if integer < 0x80000000 else integer - 0x100000000


def exact_cache_entries(module: Path) -> list[dict]:
    """Read only the host's scan cache, never user plugin state or licence files."""
    appdata = os.environ.get("APPDATA")
    require(bool(appdata), "APPDATA is required to locate the host scan cache")
    cache = Path(appdata) / "E-musician/plugins-v1/catalog.json"
    require(cache.is_file() and cache.stat().st_size <= 16 * 1024 * 1024, "bounded plugin scan cache not found")
    document = json.loads(cache.read_text(encoding="utf-8-sig"))
    require(document.get("schema") == 1, "unsupported plugin scan cache schema")
    expected_format = "VST" if module.suffix.lower() == ".dll" else "VST3"
    matches = []
    for item in document.get("plugins", []):
        description = ET.fromstring(item.get("description", ""))
        properties = description.attrib
        if normal_path(properties.get("file", "")) != normal_path(module):
            continue
        if properties.get("format") != expected_format:
            continue
        identity = "\n".join([expected_format, properties["file"].lower(),
                              str(signed_hex(properties.get("uniqueId", "0"))),
                              str(signed_hex(properties.get("uid", "0")))])
        matches.append({"id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                        "available": bool(item.get("available")), "error": item.get("error", ""),
                        "name": properties.get("name", ""), "format": expected_format,
                        "is_instrument": properties.get("isInstrument", "0") in ("1", "true"),
                        "version": properties.get("version", "")})
    return matches


def tone(path: Path) -> None:
    samples = array.array("h")
    for index in range(96000):
        for frequency in (110, 220):
            samples.append(round(0.025 * 32767 * math.sin(2 * math.pi * frequency * index / 48000)))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(samples.tobytes())


def read_render(path: Path) -> dict:
    data = path.read_bytes()
    require(len(data) <= 8 * 1024 * 1024, "unexpectedly large two-second test render")
    require(data[:4] == b"RIFF" and data[8:12] == b"WAVE", "render is not RIFF/WAVE")
    position = 12
    fmt = payload = None
    while position + 8 <= len(data):
        tag, size = struct.unpack_from("<4sI", data, position)
        position += 8
        require(position + size <= len(data), "truncated render chunk")
        if tag == b"fmt ":
            fmt = data[position:position + size]
        elif tag == b"data":
            payload = data[position:position + size]
        position += size + (size & 1)
    require(fmt is not None and len(fmt) >= 16 and payload is not None, "WAV fmt/data chunk missing")
    encoding, channels, rate, _, alignment, bits = struct.unpack_from("<HHIIHH", fmt)
    if encoding == 0xFFFE:
        require(len(fmt) >= 40, "truncated extensible WAV format")
        encoding = struct.unpack_from("<H", fmt, 24)[0]
    require(channels == 2 and rate == 48000 and bits == 32 and alignment == 8,
            f"unexpected rendered format: {channels}ch {rate}Hz {bits}bit")
    frames = len(payload) // alignment
    require(len(payload) % alignment == 0 and abs(frames - 96000) <= 1, f"unexpected frame count: {frames}")
    require(encoding in (1, 3), f"unsupported WAV encoding: {encoding}")
    values = [value[0] if encoding == 3 else value[0] / 2147483648
              for value in struct.iter_unpack("<f" if encoding == 3 else "<i", payload)]
    finite = all(math.isfinite(value) for value in values)
    require(finite, "render contains non-finite audio samples")
    peak = max(abs(value) for value in values)
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    return {"channels": channels, "sample_rate": rate, "bit_depth": bits, "encoding": encoding,
            "frames": frames, "finite": finite, "peak": peak, "rms": rms, "nonzero": peak > 1e-7}


def page(client: Client, command: str, key: str, extra: dict | None = None) -> list[dict]:
    values = []
    offset = 0
    while True:
        result = client.completed(client.raw({"command": command, "args": {
            **(extra or {}), "offset": offset, "limit": 256}}))
        values.extend(result[key])
        offset += len(result[key])
        if offset >= result["total"]:
            return values
        require(bool(result[key]), f"{command} returned an empty page before its total")
        require(offset <= 100000, f"{command} exceeded the bound")


def read_parameter(client: Client, plugin_id: str, parameter_id: str) -> dict:
    parameters = page(client, "get_plugin_parameters", "parameters", {"plugin_id": plugin_id})
    matches = [parameter for parameter in parameters if parameter["id"] == parameter_id]
    require(len(matches) == 1, "saved parameter identity no longer exists uniquely")
    require(math.isfinite(matches[0]["value"]), "parameter value is non-finite")
    return matches[0]


def assert_close(actual: float, expected: float, stage: str) -> None:
    require(abs(actual - expected) <= 1e-4, f"{stage} value mismatch: {actual} vs {expected}")


def plugin_slot(client: Client, track_id: str, plugin_id: str) -> dict:
    state = client.state()
    require(not state["playing"], "test unexpectedly started playback")
    tracks = [track for track in state["tracks"] if track["id"] == track_id]
    require(len(tracks) == 1, "test track identity changed")
    slots = [plugin for plugin in tracks[0]["plugins"] if plugin["id"] == plugin_id]
    require(len(slots) == 1 and not slots[0]["missing"], "plugin became missing or lost its stable slot ID")
    return slots[0]


def test_module(executable: Path, module: Path, directory: Path, timeout: float, realtime: bool) -> dict:
    result: dict = {"module": str(module), "passed": False, "checks": [], "stage": "validate module",
                    "coverage_limits": ["Native editor changes are not exercised.",
                                        "Default program only; no cross-version state migration.",
                                        "Nonzero FX output verifies signal flow, not the intended DSP effect."]}
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()

    def checked(name: str, detail: object = None) -> None:
        result["checks"].append({"name": name, "passed": True, "detail": detail})
        print(f"PASS {module.name}: {name}", flush=True)

    try:
        require(module.is_absolute() and module.exists() and module.suffix.lower() in (".dll", ".vst3"),
                "module must be an existing absolute VST2 DLL or VST3 file/bundle")
        require(module.suffix.lower() != ".dll" or module.is_file(), "VST2 module must be a file")
        with Client(executable, timeout) as client:
            def command(name: str, args: dict | None = None) -> dict:
                result["stage"] = name
                # Plugin initialization may report its own change asynchronously.
                # A revision race may be retried with a fresh envelope, never a
                # failed/native operation or an already accepted file task.
                for attempt in range(3):
                    state = client.state()
                    response = client.raw({"command": name, "args": args or {},
                                           "request_id": str(uuid.uuid4()), "project_id": state["project_id"],
                                           "expected_revision": state["revision"]})
                    if response.get("status") == "conflict" and attempt < 2:
                        time.sleep(0.05)
                        continue
                    require(response.get("status") in ("accepted", "completed"), json.dumps(response, ensure_ascii=False))
                    if response["status"] == "accepted":
                        response["job_completion"] = client.wait_job(response["result"]["job_id"])
                        time.sleep(0.05)
                    return response
                raise AssertionError("plugin changed continuously during command")

            before_ids = {entry["id"] for entry in page(client, "get_plugin_catalog", "plugins")}
            scan = command("scan_plugins", {"include_default_paths": False, "paths": [], "modules": [str(module)]})
            after = page(client, "get_plugin_catalog", "plugins")
            cached = exact_cache_entries(module)
            result["scan"] = {"job": scan.get("job_completion"), "exact_module_entries": cached,
                              "new_catalog_ids": sorted({entry["id"] for entry in after} - before_ids)}
            exact_ids = {entry["id"] for entry in cached if entry["available"]}
            expected_format = "VST" if module.suffix.lower() == ".dll" else "VST3"
            candidates = [entry for entry in after if entry["id"] in exact_ids and entry["format"] == expected_format]
            require(bool(candidates), f"module scan returned no available exact-identity candidate: {cached}")
            # Shared shell modules may contain many products. This verifies one
            # named descriptor and reports all the remaining candidates explicitly.
            candidates.sort(key=lambda entry: (not entry["is_instrument"], entry["name"], entry["id"]))
            descriptor = candidates[0]
            result["descriptor"] = descriptor
            result["untested_descriptors"] = candidates[1:]
            checked("isolated single-module scan / exact catalog identity", descriptor)

            command("set_master_gain", {"gain_db": -18})
            if descriptor["is_instrument"]:
                command("create_track", {"kind": "instrument", "name": "Plugin compatibility instrument"})
                track_id = client.state()["tracks"][-1]["id"]
                command("create_midi_clip", {"track_id": track_id, "start_beats": 0, "length_beats": 4})
                clip_id = client.state()["tracks"][-1]["clips"][0]["id"]
                command("write_notes", {"clip_id": clip_id, "notes": [
                    {"id": "compat-note-low", "pitch": 48, "start_beats": 0, "length_beats": 1.8, "velocity": 36, "channel": 1},
                    {"id": "compat-note-mid", "pitch": 60, "start_beats": 2, "length_beats": 1.8, "velocity": 36, "channel": 1}]})
            else:
                source = directory / "quiet-input.wav"
                tone(source)
                command("import_audio", {"paths": [str(source)]})
                track_id = client.state()["tracks"][-1]["id"]
            command("set_track_gain", {"track_id": track_id, "gain_db": -12})
            command("add_plugin", {"track_id": track_id, "catalog_id": descriptor["id"]})
            time.sleep(0.2)
            state = client.state()
            slot = next(track for track in state["tracks"] if track["id"] == track_id)["plugins"][-1]
            plugin_id = slot["id"]
            plugin_slot(client, track_id, plugin_id)
            checked("load installed plugin on matching track", slot)

            result["stage"] = "get_plugin_parameters"
            parameters = page(client, "get_plugin_parameters", "parameters", {"plugin_id": plugin_id})
            result["parameter_count"] = len(parameters)
            excluded = re.compile(r"bypass|mute|solo|preset|program|bank|random|reset|init|licen[sc]|auth|load|save|file|midi.?learn|enable|power|on.?off", re.I)
            preferred = re.compile(r"mix|balance|pan|cutoff|frequency|attack|release|decay|sustain|resonance|tone|width|brightness|volume|gain", re.I)
            usable = [parameter for parameter in parameters if parameter.get("active")
                      and isinstance(parameter.get("value"), (int, float)) and math.isfinite(parameter["value"])
                      and 0 <= parameter["value"] <= 1 and not excluded.search(parameter.get("name", ""))]
            usable.sort(key=lambda parameter: (not bool(preferred.search(parameter.get("name", ""))),
                                                not 0.05 < parameter["value"] < 0.95))
            require(bool(usable), "plugin exposes no suitable active parameter for a bounded scalar change")
            selected = usable[0]
            parameter_id, original = selected["id"], float(selected["value"])
            requested = original + 0.01 if original <= 0.98 else original - 0.01
            command("set_plugin_parameter", {"plugin_id": plugin_id, "parameter_id": parameter_id, "value": requested})
            time.sleep(0.2)
            changed = float(read_parameter(client, plugin_id, parameter_id)["value"])
            require(abs(changed - original) > 1e-5, "chosen parameter quantised the change away; select a continuous parameter manually")
            require(abs(changed - original) <= 0.025, "plugin parameter jumped beyond the small requested change")
            result["parameter"] = {"id": parameter_id, "name": selected["name"], "original": original,
                                   "requested": requested, "observed_changed": changed}
            command("undo")
            time.sleep(0.15)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], original, "parameter Undo")
            command("redo")
            time.sleep(0.15)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], changed, "parameter Redo")
            checked("normalized parameter / Undo / Redo", result["parameter"])

            # The host parameter edit owns its own Undo entry. Undo it first,
            # then undo Add and let the original native instance be released.
            # This tests stable-ID history rebinding to a recreated instance;
            # it deliberately does not claim to simulate a native-editor edit.
            command("undo")
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], original, "before Undo Add")
            command("undo")
            require(not next(track for track in client.state()["tracks"] if track["id"] == track_id)["plugins"],
                    "Undo Add did not remove the plugin")
            time.sleep(2.25)
            command("redo")
            time.sleep(0.2)
            plugin_slot(client, track_id, plugin_id)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], original, "Redo Add")
            command("redo")
            time.sleep(0.15)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], changed, "parameter Redo after recreation")
            checked("host parameter Undo / Undo Add / wait / Redo Add / parameter Redo",
                    {"wait_seconds": 2.25, "native_editor_simulated": False})

            project = directory / "plugin-state.emproj"
            command("save_project", {"path": str(project)})
            command("remove_plugin", {"track_id": track_id, "plugin_id": plugin_id})
            require(not next(track for track in client.state()["tracks"] if track["id"] == track_id)["plugins"], "plugin removal did not empty its slot")
            time.sleep(2.25)  # Tracktion's cache cleanup timer is one second.
            command("undo")
            time.sleep(0.2)
            plugin_slot(client, track_id, plugin_id)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], changed, "remove/wait/Undo")
            checked("remove / wait beyond cache timer / Undo restores state", {"wait_seconds": 2.25})

            command("open_project", {"path": str(project)})
            time.sleep(0.2)
            plugin_slot(client, track_id, plugin_id)
            assert_close(read_parameter(client, plugin_id, parameter_id)["value"], changed, "saved project reopen")
            checked("save / reopen preserves plugin and parameter")

            rendered = directory / "plugin-render.wav"
            command("export_wav", {"path": str(rendered), "start_seconds": 0, "end_seconds": 2,
                                    "tail_seconds": 0, "sample_rate": 48000, "bit_depth": 32, "realtime": realtime})
            result["render"] = read_render(rendered)
            checked("isolated render format / frame count / finite samples", result["render"])
            require(result["render"]["nonzero"], "render is silent; default program may require manual preset/sample setup")
            checked("plugin render is nonzero")

            # Mutate only a fresh test-owned manifest, retaining its real state
            # bytes. A positional snapshot must not silently load against a
            # different declared plugin version, even with identical UID/path.
            mismatch = directory / "version-mismatch.emproj"
            command("save_project", {"path": str(mismatch)})
            manifest = json.loads(mismatch.read_text(encoding="utf-8-sig"))
            saved_slot = next(plugin for track in manifest["tracks"] for plugin in track["plugins"]
                              if plugin["id"] == plugin_id)
            original_hash, original_bytes = saved_slot["state_sha256"], saved_slot["state_bytes"]
            saved_slot["version"] = "__incompatible_version_fixture__"
            mismatch.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            command("open_project", {"path": str(mismatch)})
            missing_slot = next(plugin for track in client.state()["tracks"] for plugin in track["plugins"]
                                if plugin["id"] == plugin_id)
            require(missing_slot["missing"], "version mismatch loaded positional parameter state instead of preserving a placeholder")
            preserved = directory / "version-mismatch-preserved.emproj"
            command("save_project", {"path": str(preserved)})
            archived = json.loads(preserved.read_text(encoding="utf-8-sig"))
            preserved_slot = next(plugin for track in archived["tracks"] for plugin in track["plugins"]
                                  if plugin["id"] == plugin_id)
            require(preserved_slot["version"] == saved_slot["version"]
                    and preserved_slot["state_sha256"] == original_hash
                    and preserved_slot["state_bytes"] == original_bytes,
                    "saving a version-mismatch placeholder changed its version or opaque state")
            retained_file = (preserved.parent / preserved_slot["state_file"]).resolve()
            require(retained_file.is_relative_to(directory.resolve()), "preserved state path escaped the test workspace")
            require(hashlib.sha256(retained_file.read_bytes()).hexdigest() == original_hash,
                    "preserved opaque plugin bytes changed")
            checked("version mismatch remains missing and preserves opaque state",
                    {"fixture": "test manifest only; installed plugin unchanged", "state_sha256": original_hash})
            command("open_project", {"path": str(preserved)})
            reopened_missing = next(plugin for track in client.state()["tracks"] for plugin in track["plugins"]
                                    if plugin["id"] == plugin_id)
            require(reopened_missing["missing"], "saved version-mismatch placeholder did not survive reopen")
            checked("saved version-mismatch placeholder reopens without loading the plugin")
            command("open_project", {"path": str(project)})
            plugin_slot(client, track_id, plugin_id)
            require(not client.state()["playing"], "playback unexpectedly active at test completion")
            result["passed"] = True
    except (AssertionError, ControlError, OSError, ValueError, KeyError, ET.ParseError) as error:
        result["error"] = str(error)
        result["requires_manual_attention"] = "timed out" in str(error).lower() or "timeout" in str(error).lower()
        print(f"FAIL {module.name} at {result['stage']}: {error}", file=sys.stderr, flush=True)
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        (directory / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--module", required=True, action="append", type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args()
    require(args.exe.is_file() and args.timeout > 0, "valid --exe and positive --timeout required")
    require(len(args.module) <= 64, "at most 64 explicitly supplied modules are allowed")
    parent = (ROOT / "build/plugin-host-smoke").resolve()
    require(parent.is_relative_to((ROOT / "build").resolve()), "test workspace escaped build")
    workspace = parent / str(uuid.uuid4())
    workspace.mkdir(parents=True, exist_ok=False)
    results = []
    for index, module in enumerate(args.module):
        # Resolve the provided path without altering the module or its directory.
        result = test_module(args.exe.resolve(), module.absolute(), workspace / f"module-{index + 1}", args.timeout, args.realtime)
        results.append(result)
        report = {"passed": all(item["passed"] for item in results), "requested_modules": len(args.module),
                  "completed_modules": len(results), "workspace": str(workspace), "results": results,
                  "executable_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
                  "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        (workspace / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {workspace / 'report.json'}", flush=True)
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
