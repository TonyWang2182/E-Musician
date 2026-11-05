"""Real local models through the real offline DAW. Synthetic signal validates
the pipeline and time mapping, not music recognition quality or physical audio.
Run via scripts.dev.Recorder; never opens or overwrites a user's project.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import shutil
import sys
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client, ControlError
from MusicAgentIntegration import protected

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", default=300, type=float)
    parser.add_argument("--skip-separation", action="store_true")
    parser.add_argument("--old-exe", type=Path)
    args = parser.parse_args()
    directory = ROOT / "build/analysis-e2e" / str(uuid.uuid4())
    directory.mkdir(parents=True)
    source = directory / "synthetic-chords.wav"
    rate = 44100
    with wave.open(str(source), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(rate)
        for i in range(rate * 5):
            pitches = (60, 64, 67) if i < rate * 2.5 else (57, 60, 64)
            value = round(sum(math.sin(i / rate * 2 * math.pi * 440 * 2 ** ((p-69)/12)) for p in pitches) * 5000)
            out.writeframesraw(struct.pack("<hh", value, value))
    report = {"passed": False, "checks": [], "fixture": "synthetic C/Am signal, no music-quality claim",
              "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(), "physical_audio": False}
    before = protected()
    client = None
    def check(name): report["checks"].append(name)
    def read(command, arguments=None): return client.completed(client.raw({"command": command, "args": arguments or {}}))
    def write(command, arguments=None, wait=True): return client.request({"command": command, "args": arguments or {}}, wait=wait)
    def failed(command, arguments):
        try: write(command, arguments, False)
        except ControlError: return
        raise AssertionError("Expected rejection: " + command)
    def wait_job(job, terminal=("ready", "applied")):
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            value = read("get_analysis_job", {"job_id": job})
            if value["status"] in terminal: return value
            if value["status"] in ("failed", "cancelled", "stale"):
                raise AssertionError(value)
            time.sleep(.08)
        raise AssertionError("Analysis timed out: " + repr(value))
    try:
        client = Client(args.exe, timeout=args.timeout, show=False, offline_test=True)
        caps = read("get_analysis_capabilities")
        assert all(p["available"] for p in caps["providers"]), caps
        write("import_audio", {"paths": [str(source)]})
        state = client.state(); original = state["tracks"][0]["clips"][0]["id"]
        write("move_clip", {"clip_id": original, "start_seconds": 12.5})
        legacy_project = directory / "plain.emproj"
        write("save_project", {"path": str(legacy_project)})
        assert json.loads(legacy_project.read_text(encoding="utf-8"))["schema"] == 4
        kinds = ["chords", "transcribe"] + ([] if args.skip_separation else ["separate"])
        for kind in kinds:
            state = client.state(); revision = state["revision"]; count = len(state["tracks"])
            response = write("start_analysis", {"clip_id": original, "kind": kind, "start_seconds": .5, "duration_seconds": 4}, False)
            ready = wait_job(response["result"]["job_id"])
            result_id = ready["result_id"]
            result = read("get_analysis_result", {"result_id": result_id, "limit": 3})
            assert client.state()["revision"] == revision, "Analysis changed the project before acceptance"
            assert result["total"] > 0 and result["source"]["timeline_start"] == 13, result
            assert result["offset"] == 0 and len(result["items"]) <= 3
            assert len(result["result_hash"]) == 64
            failed("get_analysis_result", {"result_id": result_id, "limit": 101})
            response = write("accept_analysis_result", {"result_id": result_id}, False)
            applied = wait_job(response["result"]["job_id"])
            state = client.state(); assert state["revision"] == revision + 1
            receipt = applied["receipt"]
            assert receipt["applied"] and receipt["revision"] == state["revision"]
            if kind == "chords":
                saved = read("get_chord_regions", {"clip_id": original})
                assert saved["total"] == result["total"]
                assert all(13 <= c["start_seconds"] < c["end_seconds"] <= 17.000001 for c in saved["items"])
            else:
                assert len(state["tracks"]) == count + (4 if kind == "separate" else 1)
                created = [c for t in state["tracks"] for c in t["clips"] if c["id"] in receipt["clip_ids"]]
                assert all(abs(c["start_seconds"]-13) < 1e-8 and abs(c["duration_seconds"]-4) < .002 for c in created)
                if kind == "transcribe":
                    notes = read("get_clip_notes", {"clip_id": created[0]["id"], "limit": 1000})
                    assert notes["total"] == result["total"]
                else:
                    drums = next(c for c in created if c["analysis_role"] == "drums")
                    drum_track = next(t for t in state["tracks"] if any(c["id"] == drums["id"] for c in t["clips"]))
                    # Role survives user-facing renames; never infer permissions
                    # or model suitability from an untrusted display name.
                    write("rename_track", {"track_id": drum_track["id"], "name": "Piano label"})
                    failed("start_analysis", {"clip_id": drums["id"], "kind": "transcribe"})
                    write("undo")
                    state = client.state()
            duplicate = write("accept_analysis_result", {"result_id": result_id}, False)
            assert duplicate["result"]["applied"] and client.state()["revision"] == state["revision"]
            write("undo")
            assert len(client.state()["tracks"]) == count
            failed("accept_analysis_result", {"result_id": result_id})
            write("redo")
            check(kind + ": real inference, no premature edit, range mapping, import, idempotency, one Undo/Redo")
        regions = read("get_chord_regions")["items"]
        first = regions[0]
        write("edit_chord_region", {"id": first["id"], "label": "F#:min"})
        assert read("get_chord_regions")["items"][0]["label"] == "F#:min"
        failed("edit_chord_region", {"id": first["id"], "label": "Invented"})
        write("undo"); assert read("get_chord_regions")["items"][0]["label"] == first["label"]
        write("redo"); check("Persistent chord correction validates labels and Undo/Redo")
        project = directory / "analyzed.emproj"
        write("save_project", {"path": str(project)})
        manifest = json.loads(project.read_text(encoding="utf-8"))
        assert manifest["schema"] == 5 and len(manifest["analyses"]) == len(kinds)
        upgrade = directory / "upgrade.emproj"
        # A schema4 manifest with no referenced assets is an owned upgrade case.
        plain = json.loads(legacy_project.read_text(encoding="utf-8"))
        plain["tracks"] = []; plain["assets"] = []
        original_manifest = json.dumps(plain).encode("utf-8")
        upgrade.write_bytes(original_manifest)
        write("save_project", {"path": str(upgrade)})
        backups = list(directory.glob("upgrade.emproj.schema4-*.bak"))
        assert len(backups) == 1 and backups[0].read_bytes() == original_manifest
        check("Schema4 upgrade preserves exact old manifest backup")
        before_open = client.state(); write("new_project"); write("open_project", {"path": str(project)})
        assert len(client.state()["tracks"]) == len(before_open["tracks"])
        assert read("get_chord_regions")["items"][0]["label"] == "F#:min"
        check("Schema5 save/new/open retains accepted assets, notes, chords and provenance")
        if args.old_exe:
            old = Client(args.old_exe, timeout=args.timeout, show=False, offline_test=True)
            try:
                old.request({"command": "open_project", "args": {"path": str(legacy_project)}})
                old_state = old.state()
                try: old.request({"command": "open_project", "args": {"path": str(project)}})
                except ControlError: pass
                else: raise AssertionError("0.8.1 unexpectedly accepted schema5")
                assert old.state()["project_id"] == old_state["project_id"]
                check("Preserved 0.8.1 opens ordinary schema4 and explicitly rejects schema5")
            finally: old.close()
        original = client.state()["tracks"][0]["clips"][0]["id"]
        response = write("start_analysis", {"clip_id": original, "kind": "chords", "duration_seconds": 1}, False)
        ready = wait_job(response["result"]["job_id"])
        write("move_clip", {"clip_id": original, "start_seconds": 21})
        failed("accept_analysis_result", {"result_id": ready["result_id"]})
        check("Moved source rejects stale candidate")
        mp3 = directory / "owned-test.mp3"
        shutil.copyfile(ROOT / "tests/fixtures/audio/stereo-cbr-48000.mp3", mp3)
        write("import_audio", {"paths": [str(mp3)]})
        mp3_clip = client.state()["tracks"][-1]["clips"][0]
        original_bytes = mp3.read_bytes()
        mp3.write_bytes(original_bytes + b"external change after import")
        response = write("start_analysis", {"clip_id": mp3_clip["id"], "kind": "chords", "duration_seconds": .2}, False)
        stale = wait_job(response["result"]["job_id"], ("stale",))
        assert "MP3 changed" in stale["error"]
        mp3.write_bytes(original_bytes)
        response = write("start_analysis", {"clip_id": mp3_clip["id"], "kind": "chords", "duration_seconds": .2}, False)
        timings = []
        for _ in range(10):
            began = time.perf_counter(); client.state(); timings.append((time.perf_counter()-began)*1000)
        write("save_project", {"path": str(directory / "save-during-analysis.emproj")})
        ready_mp3 = wait_job(response["result"]["job_id"])
        assert read("get_analysis_result", {"result_id": ready_mp3["result_id"]})["total"] > 0
        write("save_project", {"path": str(directory / "save-ready-candidate.emproj")})
        assert not read("get_analysis_result", {"result_id": ready_mp3["result_id"]})["stale"]
        imported_mp3 = write("accept_analysis_result", {"result_id": ready_mp3["result_id"]}, False)
        wait_job(imported_mp3["result"]["job_id"], ("applied",))
        report["offline_control_snapshot_ms_10_samples"] = timings
        check("MP3 replacement rejected; save during analysis and after ready preserves candidate identity and import")
        response = write("start_analysis", {"clip_id": original, "kind": "separate", "duration_seconds": 4}, False)
        read("cancel_analysis_job", {"job_id": response["result"]["job_id"]})
        wait_job(response["result"]["job_id"], ("cancelled",))
        check("Cancellation terminates owned worker without project edit")
        assert protected() == before
        report["passed"] = True
    finally:
        if client: client.close()
        report["protected_unchanged"] = protected() == before
        (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(directory / "report.json"), **report}, indent=2))

if __name__ == "__main__": main()
