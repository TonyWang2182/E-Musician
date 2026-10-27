"""Exercise real JSONL jobs in a dedicated DAW process (no user project/plugins).

python tests/AgentJobsSmoke.py --exe build/bin/Release/E-musician.exe

All generated inputs, outputs and the JSON report stay in a fresh UUID directory
under build/agent-jobs-smoke. The larger WAV (~94 MiB) and 100000-note SMF make
worker cancellation/concurrent-edit cases observable without production test hooks.
No test artifacts are deleted automatically. This script never starts playback.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError, TERMINAL_JOBS  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def tone(path: Path, seconds: int, amplitude: float = 0.25) -> None:
    samples = array.array("h")
    for frame in range(48000):
        for frequency in (220, 330):
            samples.append(round(amplitude * 32767 * math.sin(2 * math.pi * frequency * frame / 48000)))
    if sys.byteorder != "little":
        samples.byteswap()
    block = samples.tobytes()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        for _ in range(seconds):
            output.writeframesraw(block)


def vlq(value: int) -> bytes:
    require(0 <= value <= 0x0FFFFFFF, "fixture VLQ overflow")
    result = [value & 127]
    while value >> 7:
        value >>= 7
        result.insert(0, (value & 127) | 128)
    return bytes(result)


def smf(path: Path, tracks: list[list[tuple[int, bytes]]], file_type: int = 1, ppqn: int = 480) -> None:
    result = bytearray(b"MThd" + struct.pack(">IHHH", 6, file_type, len(tracks), ppqn))
    for events in tracks:
        payload = bytearray()
        previous = 0
        for tick, message in sorted(events, key=lambda event: event[0]):
            payload.extend(vlq(tick - previous))
            payload.extend(message)
            previous = tick
        payload.extend(b"\x00\xff\x2f\x00")
        result.extend(b"MTrk" + struct.pack(">I", len(payload)) + payload)
    path.write_bytes(result)


TEMPO = (0, b"\xff\x51\x03\x07\xa1\x20")
METER = (0, b"\xff\x58\x04\x04\x02\x18\x08")
MELODY = [(0, b"\x90\x3c\x64"), (480, b"\x80\x3c\x00")]
BASS = [(240, b"\x91\x43\x52"), (720, b"\x81\x43\x00")]


def midi_events(path: Path) -> tuple[int, list[tuple[int, int, int, int]]]:
    """Small independent SMF parser for checking exported note ticks/channels."""
    data = path.read_bytes()
    require(data[:4] == b"MThd", "export lacks SMF header")
    header, file_type, count, ppqn = struct.unpack_from(">IHHH", data, 4)
    require(file_type == 1 and ppqn == 960, "export must use SMF 1 / 960 PPQN")
    position = 8 + header
    notes = []
    for _ in range(count):
        require(data[position:position + 4] == b"MTrk", "export track chunk missing")
        length = struct.unpack_from(">I", data, position + 4)[0]
        position += 8
        end = position + length
        tick = 0
        running = 0

        def read_vlq() -> int:
            nonlocal position
            value = 0
            for _ in range(4):
                require(position < end, "truncated exported VLQ")
                byte = data[position]
                position += 1
                value = (value << 7) | (byte & 127)
                if byte < 128:
                    return value
            raise AssertionError("oversized exported VLQ")

        while position < end:
            tick += read_vlq()
            status = data[position]
            if status >= 128:
                position += 1
            else:
                status = running
            if status == 0xFF:
                position += 1  # meta type
                size = read_vlq()
                position += size
                running = 0
            elif status in (0xF0, 0xF7):
                size = read_vlq()
                position += size
                running = 0
            else:
                require(0x80 <= status < 0xF0, "invalid exported status")
                running = status
                count_bytes = 1 if status & 0xF0 in (0xC0, 0xD0) else 2
                require(position + count_bytes <= end, "truncated exported channel event")
                if status & 0xF0 in (0x80, 0x90):
                    pitch, velocity = data[position:position + 2]
                    kind = 0x90 if status & 0xF0 == 0x90 and velocity else 0x80
                    notes.append((tick, kind | (status & 15), pitch, velocity))
                position += count_bytes
        require(position == end, "export track boundary mismatch")
    require(position == len(data), "export trailing bytes")
    return ppqn, sorted(notes)


class Suite:
    def __init__(self, client: Client, directory: Path):
        self.client, self.directory = client, directory
        self.checks: list[dict] = []
        self.jobs: list[dict] = []
        self.observations: list[dict] = []

    def record(self, name: str, details: object = None) -> None:
        self.checks.append({"name": name, "passed": True, "details": details})
        print(f"PASS {name}", flush=True)

    def command(self, command: str, args: dict | None = None, *, wait: bool = True) -> dict:
        return self.client.request({"command": command, "args": args or {}}, wait=wait)

    def direct(self, command: str, state: dict, args: dict | None = None) -> dict:
        return self.client.raw({"command": command, "args": args or {}, "request_id": str(uuid.uuid4()),
                                "project_id": state["project_id"], "expected_revision": state["revision"]})

    def begin(self, command: str, args: dict, state: dict | None = None) -> str:
        response = self.direct(command, state or self.client.state(), args)
        require(response.get("status") == "accepted", f"{command} not accepted: {response}")
        job_id = response.get("result", {}).get("job_id")
        require(bool(job_id), "accepted task omitted job_id")
        return job_id

    def wait(self, job_id: str, expected: str = "completed") -> dict:
        deadline = time.monotonic() + self.client.timeout
        while time.monotonic() < deadline:
            job = self.client.completed(self.client.raw({"command": "get_job", "args": {"job_id": job_id}}))
            if job["status"] in TERMINAL_JOBS:
                self.jobs.append(job)
                require(job["status"] == expected, f"expected {expected}, got {job}")
                # Allow the next message-loop timer to join a completed file-only worker.
                time.sleep(0.05)
                return job
            time.sleep(0.02)
        raise AssertionError(f"task timeout: {job_id}")

    def running_render(self, job_id: str) -> None:
        deadline = time.monotonic() + min(self.client.timeout, 30)
        while time.monotonic() < deadline:
            job = self.client.completed(self.client.raw({"command": "get_job", "args": {"job_id": job_id}}))
            require(job["status"] not in TERMINAL_JOBS, f"render ended before concurrent operation: {job}")
            if job.get("progress", -1) > 0.2:
                return
            time.sleep(0.02)
        raise AssertionError("render worker failed to report progress")

    def notes(self) -> list[dict]:
        result = []
        for track in self.client.state()["tracks"]:
            for clip in track.get("clips", []):
                if clip["kind"] == "midi":
                    page = self.client.completed(self.client.raw({"command": "get_clip_notes", "args": {"clip_id": clip["id"], "limit": 1000}}))
                    require(page["total"] == len(page["notes"]), "small fixture unexpectedly needs pagination")
                    result.extend(page["notes"])
        return result

    def audio_and_render(self, short: Path, mp3: Path | None) -> None:
        self.command("new_project")
        before = self.client.state()
        require(before["bpm"] == 120, "new project BPM must be 120")
        self.wait(self.begin("import_audio", {"paths": [str(short)]}, before))
        state = self.client.state()
        require(len(state["tracks"]) == 1 and state["revision"] == before["revision"] + 1, "audio import must commit exactly once")
        self.record("background WAV import / one revision")
        if mp3:
            before = state
            self.wait(self.begin("import_audio", {"paths": [str(mp3)]}, before))
            state = self.client.state()
            require(len(state["tracks"]) == 2 and state["revision"] == before["revision"] + 1, "MP3 import commit failed")
            self.command("remove_track", {"track_id": state["tracks"][-1]["id"]})
            self.record("background MP3 import")

        output = self.directory / "partial-tail.wav"
        state = self.client.state()
        self.wait(self.begin("export_wav", {"path": str(output), "start_seconds": 0.5,
                  "end_seconds": 1.25, "tail_seconds": 0.5, "sample_rate": 48000, "bit_depth": 16}, state))
        with wave.open(str(output), "rb") as rendered:
            require((rendered.getnchannels(), rendered.getframerate(), rendered.getsampwidth()) == (2, 48000, 2), "WAV format mismatch")
            require(abs(rendered.getnframes() - 60000) <= 1, "partial range plus fixed tail frame count mismatch")
            samples = array.array("h", rendered.readframes(rendered.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        channel = samples[::2]
        middle = channel[4800:28800]
        rms = math.sqrt(sum((sample / 32768) ** 2 for sample in middle) / len(middle))
        expected = 0.25 * 10 ** (-6 / 20) / math.sqrt(2)
        require(abs(rms / expected - 1) < 0.03, f"master gain not reflected in WAV: {rms} vs {expected}")
        require(max(abs(value) for value in channel[40000:]) <= 2, "tail contains later source audio instead of decaying to silence")
        require(self.client.state()["revision"] == state["revision"], "export changed project revision")
        self.record("isolated WAV partial range / fixed tail / master gain", {"frames": 60000, "rms": rms})

        protected = self.directory / "cancel-protected.wav"
        sentinel = b"previous output must survive cancellation\n"
        protected.write_bytes(sentinel)
        job = self.begin("export_wav", {"path": str(protected), "start_seconds": 0,
                         "end_seconds": 2, "tail_seconds": 8, "realtime": True, "bit_depth": 16})
        self.running_render(job)
        self.command("cancel_job", {"job_id": job})
        self.wait(job, "cancelled")
        require(protected.read_bytes() == sentinel, "cancelled export replaced existing output")
        time.sleep(0.15)
        require(protected.read_bytes() == sentinel, "late worker overwrote target after cancellation")
        self.record("cancel render / preserve target / no late write")

        external = self.directory / "externally-changed.wav"
        external.write_bytes(b"original output\n")
        job = self.begin("export_wav", {"path": str(external), "start_seconds": 0,
                         "end_seconds": 2, "tail_seconds": 1, "realtime": True, "bit_depth": 16})
        self.running_render(job)
        marker = b"external edit while render was running\n"
        external.write_bytes(marker)
        result = self.wait(job, "failed")
        require("changed" in result.get("error", "").lower(), "external target change was not diagnosed")
        require(external.read_bytes() == marker, "export overwrote externally modified target")
        self.record("export fingerprint rejects changed destination")

    def concurrency_and_save(self, large: Path, many_notes: Path) -> None:
        self.command("new_project")
        before = self.client.state()
        job = self.begin("import_midi", {"path": str(many_notes)}, before)
        edit = self.direct("create_track", before, {"kind": "audio", "name": "Concurrent edit"})
        require(edit.get("status") == "completed", f"concurrent edit lost race before import preparation: {edit}")
        self.wait(job, "conflict")
        state = self.client.state()
        require(len(state["tracks"]) == 1 and state["tracks"][0]["name"] == "Concurrent edit", "stale import replaced active edit")
        require(state["revision"] == before["revision"] + 1, "conflicted task advanced revision")
        self.record("import revision conflict preserves concurrent edit")

        before = state
        job = self.begin("import_midi", {"path": str(many_notes)}, before)
        cancel = self.direct("cancel_job", before, {"job_id": job})
        require(cancel.get("status") == "completed", f"import cancellation was not accepted: {cancel}")
        self.wait(job, "cancelled")
        require(self.client.state()["revision"] == before["revision"], "cancelled import modified project")
        self.record("cancel MIDI preparation leaves project unchanged")

        self.command("new_project")
        self.wait(self.begin("import_audio", {"paths": [str(large)]}))
        state = self.client.state()
        track_id = state["tracks"][0]["id"]
        saved = self.directory / "snapshot-during-edit.emproj"
        job = self.begin("save_project", {"path": str(saved)}, state)
        edit = self.direct("set_track_gain", state, {"track_id": track_id, "gain_db": -9})
        require(edit.get("status") == "completed", f"edit during save failed: {edit}")
        self.wait(job)
        active = self.client.state()
        manifest = json.loads(saved.read_text(encoding="utf-8-sig"))
        require(active["dirty"] and abs(active["tracks"][0]["gain_db"] + 9) < 1e-6, "save incorrectly cleared newer edit")
        require(abs(manifest["tracks"][0]["gain_db"]) < 1e-6 and manifest["revision"] == state["revision"], "save did not retain captured revision/contents")
        self.record("save fixed snapshot / preserve later dirty edit")

        before = active
        job = self.begin("open_project", {"path": str(saved)}, before)
        edit = self.direct("rename_track", before, {"track_id": track_id, "name": "Keep this edit"})
        # A cached open can commit before the next JSONL request arrives. Both
        # serialized orders are legal; each has a different required guard and
        # final state. Never accept an arbitrary edit/open failure as a pass.
        musical_keys = ("project_id", "bpm", "numerator", "denominator", "duration_seconds", "looping",
                        "loop_start_seconds", "loop_end_seconds", "master_gain_db", "tracks", "master_plugins", "master_automation")

        def music(snapshot: dict) -> dict:
            return {key: snapshot[key] for key in musical_keys}

        evidence = {"case": "open versus rename", "job_id": job, "before_project_id": before["project_id"],
                    "before_revision": before["revision"], "saved_revision": manifest["revision"], "edit_response": edit,
                    "job_after_edit": self.client.completed(self.client.raw({"command": "get_job", "args": {"job_id": job}}))}
        self.observations.append(evidence)
        if edit.get("status") == "completed":
            evidence["order"] = "edit_before_open_commit"
            self.wait(job, "conflict")
            after = self.client.state()
            evidence["after"] = {"revision": after["revision"], "dirty": after["dirty"], "music": music(after)}
            expected_music = music(before)
            expected_music["tracks"] = [dict(track, name="Keep this edit") if track["id"] == track_id else track
                                        for track in before["tracks"]]
            require(edit["project_id"] == before["project_id"] and edit["revision"] == before["revision"] + 1,
                    "completed rename did not advance the original project exactly once")
            require(after["revision"] == before["revision"] + 1 and after["dirty"] and music(after) == expected_music,
                    "conflicted open changed the concurrently edited project or cleared its dirty state")
            self.record("open revision conflict preserves active project", {"order": evidence["order"]})
        else:
            evidence["order"] = "open_commit_before_edit"
            rejection = "conflict" if manifest["project_id"] == before["project_id"] else "wrong_project"
            require(edit.get("status") == rejection, f"unexpected rename failure during open: {edit}")
            self.wait(job, "completed")
            after = self.client.state()
            evidence["after"] = {"revision": after["revision"], "dirty": after["dirty"], "music": music(after)}
            expected_revision = max(before["revision"], manifest["revision"]) + 1
            require(edit["project_id"] == manifest["project_id"] and edit["revision"] == expected_revision
                    and after["revision"] == expected_revision, "stale rename was not rejected at the completed open revision")
            require(not after["dirty"] and not after["playing"] and not after["can_undo"] and not after["can_redo"]
                    and music(after) == music(state), "rejected stale rename modified the clean opened snapshot or history")
            self.record("completed open rejects stale edit and preserves opened snapshot", {"order": evidence["order"]})
        self.wait(self.begin("open_project", {"path": str(saved)}))
        reopened = self.client.state()
        require(not reopened["dirty"] and music(reopened) == music(state), "background reopen did not restore the complete saved snapshot")
        self.record("background open restores captured project cleanly")

    def midi(self, fixtures: dict[str, Path]) -> None:
        for name in ("type0", "type1"):
            self.command("new_project")
            before = self.client.state()
            self.wait(self.begin("import_midi", {"path": str(fixtures[name])}, before))
            state = self.client.state()
            notes = self.notes()
            require(len(state["tracks"]) == 2 and sorted(n["channel"] for n in notes) == [1, 2], "MIDI source track/channel split failed")
            require(state["revision"] == before["revision"] + 1, "MIDI import must commit exactly once")
            exported = self.directory / f"{name}-roundtrip.mid"
            self.wait(self.begin("export_midi", {"path": str(exported)}))
            ppqn, events = midi_events(exported)
            expected = sorted([(0, 0x90, 60, 100), (960, 0x80, 60, 0),
                               (480, 0x91, 67, 82), (1440, 0x81, 67, 0)])
            require(events == expected, f"SMF note timing/channel/velocity roundtrip changed: {events}")
            self.record(f"SMF {name} / channel split / {ppqn} PPQN roundtrip")

        for name in ("controllers", "tempo-map", "truncated", "smpte", "type2"):
            self.command("new_project")
            before = self.client.state()
            result = self.wait(self.begin("import_midi", {"path": str(fixtures[name])}, before), "failed")
            after = self.client.state()
            require(after["revision"] == before["revision"] and not after["tracks"], f"rejected {name} partially changed project")
            require(bool(result.get("error")), "rejected MIDI omitted explanation")
            self.record(f"MIDI rejects {name} without partial edits")
        self.wait(self.begin("import_midi", {"path": str(fixtures["controllers"]), "notes_only": True}))
        require(len(self.notes()) == 2, "notes_only failed to preserve actual notes")
        self.record("explicit notes_only imports notes from controller SMF")
        self.command("new_project")
        self.wait(self.begin("import_midi", {"path": str(fixtures["tempo150"])}))
        require(abs(self.client.state()["bpm"] - 150) < 1e-6, "empty project did not adopt fixed SMF tempo")
        self.wait(self.begin("import_midi", {"path": str(fixtures["type0"])}), "failed")
        self.wait(self.begin("import_midi", {"path": str(fixtures["type0"]), "notes_only": True}))
        require(abs(self.client.state()["bpm"] - 150) < 1e-6, "notes_only unexpectedly changed project tempo")
        self.record("fixed SMF tempo adoption / explicit existing-tempo policy")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    require(args.timeout > 0, "timeout must be positive")
    build_root = (ROOT / "build").resolve()
    parent = (build_root / "agent-jobs-smoke").resolve()
    require(parent.is_relative_to(build_root), "test output escaped build directory")
    directory = parent / str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    report: dict = {"passed": False, "workspace": str(directory), "checks": [], "jobs": []}
    started = time.monotonic()
    suite = None
    try:
        require(args.exe.is_file(), "DAW executable not found")
        short, large = directory / "short.wav", directory / "large.wav"
        tone(short, 2)
        tone(large, 512, 0.2)
        fixtures = {name: directory / f"{name}.mid" for name in
                    ("type0", "type1", "controllers", "tempo-map", "truncated", "smpte", "type2", "tempo150", "many-notes")}
        smf(fixtures["type0"], [[TEMPO, METER, *MELODY, *BASS]], 0)
        smf(fixtures["type1"], [[TEMPO, METER], MELODY, BASS])
        smf(fixtures["controllers"], [[TEMPO, METER, *MELODY, *BASS, (120, b"\xb0\x40\x7f")]], 0)
        smf(fixtures["tempo-map"], [[TEMPO, (240, b"\xff\x51\x03\x06\x1a\x80"), *MELODY]], 0)
        fixtures["truncated"].write_bytes(fixtures["type0"].read_bytes()[:-1])
        smf(fixtures["smpte"], [MELODY], 0, 0xE728)
        smf(fixtures["type2"], [MELODY], 2)
        smf(fixtures["tempo150"], [[(0, b"\xff\x51\x03\x06\x1a\x80"), METER, *MELODY]], 0)
        many = []
        for index in range(100000):
            pitch = 48 + index % 24
            many.extend([(index * 4, bytes([0x90, pitch, 80])), (index * 4 + 2, bytes([0x80, pitch, 0]))])
        smf(fixtures["many-notes"], [[TEMPO, METER, *many]], 0)
        del many
        mp3 = None
        repository_mp3 = ROOT / "tests/fixtures/audio/stereo-cbr-48000.mp3"
        if repository_mp3.is_file():
            mp3 = directory / "owned-fixture.mp3"
            shutil.copyfile(repository_mp3, mp3)
        inputs = [short, large, *fixtures.values(), *([mp3] if mp3 else [])]
        hashes = {str(path): digest(path) for path in inputs}
        with Client(args.exe, args.timeout) as client:
            suite = Suite(client, directory)
            suite.audio_and_render(short, mp3)
            suite.concurrency_and_save(large, fixtures["many-notes"])
            suite.midi(fixtures)
        require(all(digest(Path(path)) == original for path, original in hashes.items()), "an input fixture was modified")
        suite.record("all source files remain byte-identical")
        report["passed"] = True
        return 0
    except (AssertionError, ControlError, OSError, ValueError, KeyError) as error:
        report["error"] = str(error)
        print(f"FAIL {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if suite:
            report["checks"], report["jobs"] = suite.checks, suite.jobs
            report["observations"] = suite.observations
        report["elapsed_seconds"] = time.monotonic() - started
        target = directory / "report.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {target}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
