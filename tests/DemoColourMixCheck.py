"""Real offline DAW colour/mix transaction; deterministic Provider, NOT an LLM test.

Creates an owned four-track fixture, never opens a user project or audio device.
Run through scripts/dev_agent_demo.py command to retain the full test record.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import time
from unittest.mock import patch
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client
from dev import configure_console_output
from music_agent.bridge import DawBridge
from music_agent.config import DEFAULT_CONFIG
from music_agent.plans import verify_plan
from music_agent.runtime import AgentRuntime
from MusicAgentTempoIntegration import protected_changes, protected_snapshot

PROMPTS = {
    "en-US": "Work on the four tracks named Drums, Bass, Pad and Vocal in the whole project. Set their track colours to #D8BEBC, #BFD2CF, #91A7C3 and #DCCCA1 respectively. Set their track volumes to -6 dB, -8 dB, -12 dB and -4 dB respectively. Set Pad pan to -0.20 (20% left) and Vocal pan to +0.10 (10% right). Leave the other pans, clips, MIDI notes, tempo, routing and device settings unchanged. Prepare one plan for review and wait for me to apply it.",
    "zh-CN": "操作整个工程中名为 Drums、Bass、Pad、Vocal 的四条轨道。将轨道颜色依次设为 #D8BEBC、#BFD2CF、#91A7C3、#DCCCA1；将轨道音量依次设为 -6 dB、-8 dB、-12 dB、-4 dB。将 Pad 的声像设为 -0.20（左偏 20%），Vocal 的声像设为 +0.10（右偏 10%）。其他声像、片段、MIDI 音符、速度、路由和装置参数保持不变。只提出一个待审阅方案，等我点击应用。",
}
TARGETS = {
    "Drums": {"colour": "#D8BEBC", "gain_db": -6.0, "pan": 0.0},
    "Bass": {"colour": "#BFD2CF", "gain_db": -8.0, "pan": 0.0},
    "Pad": {"colour": "#91A7C3", "gain_db": -12.0, "pan": -0.2},
    "Vocal": {"colour": "#DCCCA1", "gain_db": -4.0, "pan": 0.1},
}


class DeterministicDemoProvider:
    """Exact input guard + predetermined tool call, with no language inference."""
    model = "deterministic-colour-mix-fixture-not-an-llm"
    provider_id = "kimi"
    base_url = "https://example.invalid"

    def __init__(self, language, proposal):
        self.language = language
        self.proposal = deepcopy(proposal)
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        assert self.calls == 1, "The deterministic fixture should need one proposal"
        actual = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        # The production runtime appends its authoritative read-only snapshot.
        # Keep the user's exact text assertion separate from that context.
        user_text, separator, context = actual.partition("\n\n当前工程数据（只读）：\n")
        assert user_text == PROMPTS[self.language] and separator and context, "The exact demo prompt or native context changed"
        assert any(t["function"]["name"] == "propose_plan" for t in tools)
        return {"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "colour-mix-fixture", "type": "function", "function": {
                "name": "propose_plan", "arguments": json.dumps(self.proposal, ensure_ascii=False)}}]}, "usage": {}}


class OwnedAudit:
    def __init__(self, path):
        self.path = path

    def write(self, *args, **kwargs):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"args": args, "kwargs": kwargs}, ensure_ascii=False, default=str) + "\n")


class ObservedBridge(DawBridge):
    def __init__(self, client):
        super().__init__(client=client)
        self.applied = []

    def apply(self, plan):
        result = super().apply(plan)
        self.applied.append(deepcopy(result))
        return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_synthetic_tone(path, frequency, seconds):
    """Explicit test oscillator, not a recording, stem or generated music."""
    rate = 48000
    count = round(rate * seconds)
    pcm = bytearray()
    for i in range(count):
        envelope = min(1.0, i / 240, (count - 1 - i) / 960)
        sample = round(32767 * 0.12 * envelope * math.sin(2 * math.pi * frequency * i / rate))
        pcm.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(pcm)


def musical_content(snapshot, omit_mix=False):
    result = {k: deepcopy(snapshot[k]) for k in (
        "bpm", "numerator", "denominator", "tracks", "master_plugins", "master_gain_db")}
    # Meters are observations, never persistent musical state.
    for track in result["tracks"]:
        for key in ("peak_left_db", "peak_right_db", "overloaded"):
            track.pop(key, None)
        if omit_mix:
            for key in ("colour", "gain_db", "pan"):
                track.pop(key, None)
    return result


def main():
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--version", default="0.13.4")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not args.exe.is_file() or args.timeout <= 0:
        parser.error("An existing executable and positive timeout are required")
    directory = ROOT / "build/demo-colour-mix" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    executable = directory / "E-musician.exe"
    shutil.copy2(args.exe, executable)
    source = directory / "SYNTHETIC-sampler-test-tone.wav"
    vocal = directory / "SYNTHETIC-not-a-vocal-recording.wav"
    make_synthetic_tone(source, 261.625565, 2.0)
    make_synthetic_tone(vocal, 440.0, 4.0)
    report = {"passed": False, "version_label": args.version, "input_executable": str(args.exe),
              "exe_sha256": digest(executable), "mode": "real-native-offline-host-deterministic-provider",
              "external_llm": False, "language_understanding_verified": False, "music_model_called": False,
              "physical_audio": False, "gui_mouse_tested": False, "listening_verified": False,
              "fixture_notice": "Synthetic oscillator audio; Vocal is only a track label, not a voice recording.",
              "sources": [{"path": str(p), "sha256": digest(p), "origin": "generated deterministic sine test fixture"}
                          for p in (source, vocal)], "languages": [], "checks": []}
    checks = report["checks"]
    protected_before = protected_snapshot()
    client = None

    def write(command, **arguments):
        return client.request({"command": command, "args": arguments})

    def wait(runtime, phase):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(), "Agent operation timed out"
        assert runtime.phase == phase, runtime.error or f"Expected {phase}, got {runtime.phase}"

    def instruments(bridge):
        end = time.monotonic() + args.timeout
        while True:
            try:
                snapshot = bridge.snapshot()
                return {t["name"]: bridge.read_native_instrument(snapshot, t["id"])
                        for t in snapshot["tracks"] if t["kind"] == "instrument"}
            except Exception:
                if time.monotonic() >= end:
                    raise
                time.sleep(0.05)

    def note_data(snapshot):
        return {clip["id"]: client.completed(client.raw({"command": "get_clip_notes", "args": {
            "clip_id": clip["id"]}}))["notes"] for track in snapshot["tracks"]
                for clip in track["clips"] if clip["kind"] == "midi"}

    try:
        client = Client(executable, timeout=args.timeout, show=False, offline_test=True)
        assert not client.state()["tracks"], "Must start an isolated empty project"
        note_sets = {
            "Drums": [(36, 0.0, 0.25), (36, 2.0, 0.25), (36, 4.0, 0.25), (36, 6.0, 0.25)],
            "Bass": [(36, 0.0, 1.5), (43, 2.0, 1.5), (36, 4.0, 1.5), (41, 6.0, 1.5)],
            "Pad": [(60, 0.0, 3.5), (64, 0.0, 3.5), (67, 0.0, 3.5)],
        }
        for name, notes in note_sets.items():
            write("create_track", kind="instrument", name=name)
            track = next(t for t in client.state()["tracks"] if t["name"] == name)
            tid = track["id"]
            write("add_native_instrument", track_id=tid, type="drum_rack" if name == "Drums" else "sampler")
            write("set_native_sample", track_id=tid, pad=0, path=str(source))
            write("set_native_pad", track_id=tid, pad=0, gain_db=-3.0, muted=False,
                  attack_ms=5.0, release_ms=125.0, one_shot=name == "Drums")
            write("create_midi_clip", track_id=tid, start_beats=0, length_beats=8)
            track = next(t for t in client.state()["tracks"] if t["id"] == tid)
            write("write_notes", clip_id=track["clips"][0]["id"], notes=[{
                "id": f"demo-{name.lower()}-{i}", "pitch": pitch, "start_beats": start,
                "length_beats": length, "velocity": 82 + i, "channel": 1
            } for i, (pitch, start, length) in enumerate(notes)])
        write("import_audio", paths=[str(vocal)])
        audio = next(t for t in client.state()["tracks"] if t["kind"] == "audio")
        write("rename_track", track_id=audio["id"], name="Vocal")
        baseline_project = directory / "SYNTHETIC-four-track-baseline.emproj"
        write("save_project", path=str(baseline_project))
        write("open_project", path=str(baseline_project))
        bridge = ObservedBridge(client)
        initial = bridge.snapshot()
        initial_instruments = instruments(bridge)
        initial_notes = note_data(initial)
        assert [t["name"] for t in initial["tracks"]] == list(TARGETS)
        assert len(initial_notes) == 3 and sum(map(len, initial_notes.values())) == 11
        assert initial_instruments["Drums"]["type"] == "drum_rack"
        assert initial_instruments["Bass"]["type"] == initial_instruments["Pad"]["type"] == "sampler"
        assert all(s["pads"][0]["sample_sha256"] == digest(source) for s in initial_instruments.values())
        assert {"set_track_colour", "set_track_gain", "set_track_pan"} <= set(bridge.capabilities()["commands"])
        report["initial"] = {"snapshot": initial, "native_instruments": initial_instruments, "notes": initial_notes}
        checks.append("Owned real 0.13.x host: Drums/Bass/Pad MIDI with loaded Rack/Samplers, Vocal synthetic audio; 11 original notes")

        def preserved(current):
            assert musical_content(current, omit_mix=True) == musical_content(initial, omit_mix=True)
            assert note_data(current) == initial_notes, "Original MIDI note content changed"
            assert instruments(bridge) == initial_instruments, "Rack/Sampler state or sample identity changed"

        with patch("music_agent.runtime.has_key", return_value=False), \
             patch("music_agent.providers.has_key", return_value=False), \
             patch("music_agent.runtime.load_config", return_value=deepcopy(DEFAULT_CONFIG)):
            for language, prompt in PROMPTS.items():
                write("open_project", path=str(baseline_project))
                before = bridge.snapshot()
                preserved(before)
                actions = []
                for track in before["tracks"]:
                    target = TARGETS[track["name"]]
                    actions.extend([
                        {"type": "set_track_colour", "track_id": track["id"], "colour": target["colour"]},
                        {"type": "set_track_gain", "track_id": track["id"], "gain_db": target["gain_db"]},
                    ])
                    if track["name"] in {"Pad", "Vocal"}:
                        actions.append({"type": "set_track_pan", "track_id": track["id"], "pan": target["pan"]})
                assert len(actions) == 10
                proposal = {"summary": "Review four track colours, four volumes and two pans", "actions": actions}
                provider = DeterministicDemoProvider(language, proposal)
                runtime = AgentRuntime(bridge, provider=provider, audit=OwnedAudit(directory / f"{language}-audit.jsonl"))
                applied_count = len(bridge.applied)
                runtime.plan_request(prompt, scope="project", language=language)
                wait(runtime, "ready")
                plan = deepcopy(runtime.plan)
                assert len(plan["commands"]) == 10
                assert len(bridge.applied) == applied_count
                assert bridge.snapshot()["revision"] == before["revision"]
                assert musical_content(bridge.snapshot()) == musical_content(before)
                preserved(bridge.snapshot())
                runtime.apply(plan["id"])
                wait(runtime, "done")
                applied = bridge.snapshot()
                assert len(bridge.applied) == applied_count + 1
                assert bridge.applied[-1]["result"]["executed_commands"] == 10
                assert applied["revision"] == before["revision"] + 1
                assert not verify_plan(plan, before, applied)
                for track in applied["tracks"]:
                    target = TARGETS[track["name"]]
                    assert track["colour"] == target["colour"]
                    assert abs(track["gain_db"] - target["gain_db"]) < 1e-4
                    assert abs(track["pan"] - target["pan"]) < 1e-6
                preserved(applied)
                runtime.undo()
                wait(runtime, "done")
                assert musical_content(bridge.snapshot()) == musical_content(before)
                preserved(bridge.snapshot())
                write("redo")
                assert musical_content(bridge.snapshot()) == musical_content(applied)
                preserved(bridge.snapshot())
                final_project = directory / f"SYNTHETIC-four-track-{language}-mixed.emproj"
                write("save_project", path=str(final_project))
                write("open_project", path=str(final_project))
                reopened = bridge.snapshot()
                assert musical_content(reopened) == musical_content(applied)
                preserved(reopened)
                entry = {"language": language, "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                         "scope": "project", "deterministic_provider_calls": provider.calls, "external_llm": False,
                         "action_count": len(actions), "native_apply_count": 1,
                         "revision_before_apply": before["revision"], "revision_after_apply": applied["revision"],
                         "plan": plan, "native_apply_reply": bridge.applied[-1],
                         "saved_project": str(final_project), "saved_project_sha256": digest(final_project),
                         "after_reopen": reopened, "passed": True}
                report["languages"].append(entry)
                checks.append(f"{language}: exact text fixture → production compiler → unchanged review → one atomic 10-command batch → verified readback → one Undo/Redo → real save/reopen; untouched music/routing/instruments preserved")
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if client:
            client.close()
        report["protected_file_changes"] = protected_changes(protected_before, protected_snapshot())
        report["protected_settings_unchanged"] = report["protected_file_changes"]["unchanged"]
        report["source_files_unchanged"] = all(digest(Path(item["path"])) == item["sha256"] for item in report["sources"])
        report["passed"] = report["passed"] and report["protected_settings_unchanged"] and report["source_files_unchanged"]
        output = directory / "report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("passed", "mode", "external_llm", "checks", "protected_file_changes", "source_files_unchanged")}, ensure_ascii=False, indent=2))
        print("Report:", output)
    assert report["passed"]


if __name__ == "__main__":
    main()
