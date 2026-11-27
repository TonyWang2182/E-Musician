"""Batch 2 plans against an owned offline DAW; optional first-plan live model call.

Run through Recorder. No physical devices, plugins, existing DAW windows or user
projects are opened. Save/open/redo are fixture-driver operations, never tools
exposed to the model. --live permits at most four calls for the first plan only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from MusicAgentIntegration import FakeProvider, MeasuredProvider, protected, proposal, wait
from music_agent.audit import Audit
from music_agent.bridge import DawBridge
from music_agent.plans import CLIP_FIELDS, NOTE_FIELDS, TRACK_FIELDS
from music_agent.providers import create_provider
from music_agent.runtime import AgentRuntime
from music_agent.secrets import redact


class BoundedLiveProvider(MeasuredProvider):
    def complete(self, *args, **kwargs):
        if self.usage["attempts"] >= 4:
            raise ValueError("The first-plan live-call budget is exhausted; no paid retry.")
        return super().complete(*args, **kwargs)


def note(pitch, start, length=1, velocity=80):
    return {"pitch": pitch, "start_beats": start, "length_beats": length,
            "velocity": velocity, "channel": 1}


FIRST_NOTES = [note(pitch, start) for start, pitch in enumerate((60, 62, 64, 67))]
FIRST_ACTIONS = [
    {"type": "create_track", "kind": "instrument", "name": "Batch2 piano", "as": "piano"},
    {"type": "create_midi_clip", "track_id": "@piano", "as": "phrase", "start_beats": 0, "length_beats": 16},
    {"type": "add_notes", "clip_id": "@phrase", "notes": FIRST_NOTES},
]
FIRST_PROMPT = (
    "\u8bf7\u5728\u8fd9\u4e2a\u7a7a\u7684\u6d4b\u8bd5\u5de5\u7a0b\u63d0\u51fa\u6070\u597d\u4e09\u4e2a\u52a8\u4f5c\u7684\u4e00\u4efd\u65b9\u6848\uff0c\u4e0d\u6dfb\u52a0\u5176\u4ed6\u52a8\u4f5c\uff0c\u4e0d\u8c03\u7528\u5916\u90e8\u8d44\u6e90\uff1a1. \u65b0\u5efa\u540d\u4e3a Batch2 piano \u7684 instrument \u8f68\u9053\uff0cas \u4e3a piano\uff1b2. \u5728 @piano \u4e0a\u65b0\u5efa MIDI \u7247\u6bb5\uff0c\u8d77\u70b9\u4e3a\u7b2c0\u4e2a\u56db\u5206\u97f3\u7b26\u62cd\u3001\u957f\u5ea616\u62cd\uff0cas \u4e3a phrase\uff1b3. \u5411 @phrase \u6dfb\u52a0\u6070\u597d\u56db\u4e2a\u97f3\u7b26\u3002\u6309\u987a\u5e8f pitch \u4e3a60\u300162\u300164\u300167\uff0cstart_beats \u4e3a0\u30011\u30012\u30013\uff0c\u6bcf\u4e2a length_beats=1\u3001velocity=80\u3001channel=1\u3002\u4fdd\u6301120 BPM\u53ca4/4\u3002\u4e0d\u8981\u52a0\u8f7d\u4e50\u5668\u6216\u8bd5\u542c\u3002\u4f7f\u7528\u63d0\u4f9b\u7684\u522b\u540d\u529f\u80fd\u76f4\u63a5\u63d0\u51fa\u6574\u4efd\u65b9\u6848\u3002"
)


def complete_snapshot(bridge):
    context = bridge.snapshot()
    assert not any(t.get("clips_truncated") for t in context["tracks"]), "Small fixture unexpectedly truncated"
    for track in context["tracks"]:
        for clip in track.get("clips", []):
            if clip["kind"] == "midi":
                bridge.read_notes(context, clip["id"])
    return context


def content(context):
    """Musical identity/content only; exclude transport, revision and UI selection."""
    return {
        "bpm": context["bpm"], "numerator": context["numerator"], "denominator": context["denominator"],
        "tracks": [{
            **{key: copy.deepcopy(track[key]) for key in ("id", *TRACK_FIELDS) if key in track},
            "clips": [{
                **{key: copy.deepcopy(clip[key]) for key in ("id", *CLIP_FIELDS) if key in clip},
                "notes": sorted([{key: n[key] for key in NOTE_FIELDS}
                                 for n in context["clip_notes"].get(clip["id"], [])], key=lambda n: n["id"]),
            } for clip in track.get("clips", [])],
        } for track in context["tracks"]],
    }


def find_track(context, name):
    found = [track for track in context["tracks"] if track["name"] == name]
    assert len(found) == 1, f"Expected one fixture track named {name}"
    return found[0]


def values(notes):
    return [{key: n[key] for key in NOTE_FIELDS if key != "id"}
            for n in sorted(notes, key=lambda n: (n["start_beats"], n["pitch"], n["id"]))]


def require_close(actual, expected, label):
    assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-8), label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider", choices=("openai", "kimi"), default="kimi")
    parser.add_argument("--model", help="Exact optional model ID; otherwise use configured provider defaults.")
    args = parser.parse_args()
    directory = ROOT / "build" / "music-agent-batch2-integration" / str(uuid.uuid4())
    directory.mkdir(parents=True)
    report = {
        "mode": "live-first-plan-" + args.provider if args.live else "synthetic-provider-real-daw",
        "requested_provider": args.provider, "requested_model": args.model,
        "exe_sha256": hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        "physical_audio": False, "plugins_loaded": False, "existing_windows_touched": False,
        "live_scope": "first three-action create-track/create-clip/add-notes plan only",
        "live_attempt_limit": 4, "checks": [], "passed": False,
    }
    guard = protected()
    bridge = None
    runtime = None
    live_provider = None
    fixtures = []
    started = time.monotonic()

    def checked(label):
        report["checks"].append(label)

    def fixture(actions):
        measured = MeasuredProvider(FakeProvider([proposal(copy.deepcopy(actions))]))
        fixtures.append(measured)
        return measured

    def driver(command, arguments):
        """Explicit harness control; it is not available in the Agent's tool schema."""
        assert not runtime or not runtime.busy(), "Driver cannot race an Agent task"
        snapshot = bridge.snapshot()
        envelope = {"request_id": str(uuid.uuid4()), "project_id": snapshot["project_id"],
                    "expected_revision": snapshot["revision"], "command": command, "args": arguments}
        with bridge.lock:
            reply = bridge.client.request(envelope, wait=True)
        if reply["status"] == "accepted":
            assert reply.get("job_completion", {}).get("status") == "completed", "Accepted file job not completed"
        else:
            assert reply["status"] == "completed", "Driver command failed"
        return reply

    def propose_and_apply(prompt, actions=None, expected_types=None):
        if actions is not None:
            runtime.provider = fixture(actions)
        runtime.plan_request(prompt, scope="project")
        ready = wait(runtime)
        assert ready["phase"] == "ready", ready.get("error") or "Model did not produce a reviewable plan"
        if expected_types:
            actual_types = [action["type"] for action in runtime.plan["actions"]]
            assert actual_types == expected_types, "First live proposal did not match the requested three-action scope"
        before_revision = bridge.snapshot()["revision"]
        runtime.apply(ready["plan"]["id"])
        done = wait(runtime)
        assert done["phase"] == "done", done.get("error") or "Apply did not finish"
        assert done["can_undo"], "Successful batch must expose one guarded Undo"
        snapshot = complete_snapshot(bridge)
        assert snapshot["revision"] == before_revision + 1, "A batch must commit as one project revision"
        return snapshot

    def undo_matches(expected, label):
        runtime.undo()
        result = wait(runtime)
        assert result["phase"] == "done", result.get("error") or "Undo did not finish"
        snapshot = complete_snapshot(bridge)
        actual = content(snapshot)
        if actual != expected:
            report["content_mismatch"] = {"label":label,"expected":expected,"actual":actual}
        assert actual == expected, label
        checked(label)
        return snapshot

    def reject_native(commands, label):
        before = complete_snapshot(bridge)
        envelope = {"request_id": str(uuid.uuid4()), "project_id": before["project_id"],
                    "expected_revision": before["revision"], "command": "batch", "args": {"commands": commands}}
        with bridge.lock:
            response = bridge.client.raw(envelope)
        assert response.get("request_id") == envelope["request_id"], "Native rejection response was mispaired"
        assert response.get("status") in {"failed", "invalid"}, label + " was not rejected by validation"
        after = complete_snapshot(bridge)
        assert after["revision"] == before["revision"] and content(after) == content(before), label + " changed project"
        assert (after.get("can_undo"), after.get("can_redo")) == (before.get("can_undo"), before.get("can_redo")), label + " changed history"
        checked(label)

    try:
        bridge = DawBridge(args.exe, offline=True)
        assert bridge.capabilities().get("batch_result_refs_version") == 1, "Executable lacks batch alias support"
        initial = complete_snapshot(bridge)
        assert initial["tracks"] == [] and initial["bpm"] == 120, "Owned offline fixture must start empty at 120 BPM"
        baseline = content(initial)
        if args.live:
            live_provider = BoundedLiveProvider(create_provider(args.provider, model=args.model))
            provider = live_provider
        else:
            provider = fixture(FIRST_ACTIONS)
        report["configured_model"] = provider.model
        runtime = AgentRuntime(bridge, provider, Audit(directory / "audit.jsonl"))
        first = propose_and_apply(FIRST_PROMPT, expected_types=["create_track", "create_midi_clip", "add_notes"])
        piano = find_track(first, "Batch2 piano")
        assert len(first["tracks"]) == 1 and len(piano["clips"]) == 1, "Initial chain created extra objects"
        phrase = piano["clips"][0]
        piano_id, phrase_id = piano["id"], phrase["id"]
        assert first["bpm"] == 120 and (first["numerator"], first["denominator"]) == (4, 4)
        require_close(phrase["start_beats"], 0, "Initial phrase start")
        require_close(phrase["length_beats"], 16, "Initial phrase length")
        assert values(first["clip_notes"][phrase_id]) == FIRST_NOTES, "Initial chain notes differ from explicit request"
        assert len({n["id"] for n in first["clip_notes"][phrase_id]}) == 4
        assert not piano_id.startswith("@") and not phrase_id.startswith("@"), "Aliases were not resolved to native IDs"
        checked("three-action symbolic creation applies once and native readback matches all four explicit notes")
        first_content = content(first)
        undo_matches(baseline, "one Undo removes the entire first creation chain")
        driver("redo", {})
        first = complete_snapshot(bridge)
        assert content(first) == first_content, "Redo did not restore original IDs and notes"
        checked("fixture-driver Redo restores the first chain including native IDs")
        report["real_provider_phase_complete"] = bool(args.live)

        # From here onward only FakeProvider is used, even with --live.
        duplicate_actions = [
            {"type": "create_track", "kind": "instrument", "name": "Batch2 destination", "as": "dest"},
            {"type": "duplicate_clip", "clip_id": phrase_id, "as": "copy"},
            {"type": "set_note_velocity", "clip_id": "@copy", "velocity": 60},
            {"type": "move_clip", "clip_id": "@copy", "target_track_id": "@dest", "start_seconds": 8},
        ]
        duplicated = propose_and_apply("Synthetic duplicate/velocity/cross-track move fixture", duplicate_actions)
        destination = find_track(duplicated, "Batch2 destination")
        assert len(destination["clips"]) == 1 and len(duplicated["tracks"]) == 2
        copied = destination["clips"][0]
        copied_id = copied["id"]
        require_close(copied["start_seconds"], 8, "Copied phrase move")
        assert values(duplicated["clip_notes"][copied_id]) == [{**n, "velocity": 60} for n in FIRST_NOTES]
        original_ids = {n["id"] for n in first["clip_notes"][phrase_id]}
        assert not original_ids.intersection(n["id"] for n in duplicated["clip_notes"][copied_id]), "Duplicate reused source note IDs"
        assert content(duplicated)["tracks"][0] == first_content["tracks"][0], "Duplicate chain altered the source track"
        checked("duplicate uses fresh note IDs; velocity and destination apply to copy while source remains unchanged")
        duplicate_content = content(duplicated)

        invalid_actions = [
            {"type": "set_track_gain", "track_id": piano_id, "gain_db": -9},
            {"type": "add_notes", "clip_id": phrase_id, "notes": [note(128, 0)]},
        ]
        runtime.provider = fixture(invalid_actions)
        before_invalid = complete_snapshot(bridge)
        runtime.plan_request("Synthetic invalid later action must not publish or mutate", scope="project")
        rejected = wait(runtime)
        assert rejected["phase"] == "error" and rejected["plan"] is None, "Invalid later action produced a plan"
        after_invalid = complete_snapshot(bridge)
        assert after_invalid["revision"] == before_invalid["revision"] and content(after_invalid) == duplicate_content
        checked("invalid later model action rejects the entire proposal before native mutation")
        reject_native([
            {"command": "create_track", "args": {"kind": "instrument", "name": "Must not leak"}, "as": "temporary"},
            {"command": "create_midi_clip", "args": {"track_id": "@missing", "start_beats": 0, "length_beats": 4}},
        ], "native missing later reference leaves no orphan track or undo entry")
        reject_native([
            {"command": "create_midi_clip", "args": {"track_id": piano_id, "start_beats": 20, "length_beats": 4}, "as": "wrongType"},
            {"command": "create_midi_clip", "args": {"track_id": "@wrongType", "start_beats": 0, "length_beats": 4}},
        ], "native reference type mismatch leaves no orphan clip")
        reject_native([
            {"command": "rename_track", "args": {"track_id": piano_id, "name": "Must not rename"}},
            {"command": "create_midi_clip", "args": {"track_id": "@later", "start_beats": 0, "length_beats": 4}},
            {"command": "create_track", "args": {"kind": "instrument", "name": "Future"}, "as": "later"},
        ], "native forward reference rolls back earlier candidate rename")
        reject_native([
            {"command": "set_track_gain", "args": {"track_id": piano_id, "gain_db": -8}},
            {"command": "edit_notes", "args": {"clip_id": phrase_id,
             "upsert": [{"id": "invalid-native-note", **note(200, 0)}], "delete_ids": []}},
        ], "native invalid later note leaves prior gain and history unchanged")
        undo_matches(first_content, "one Undo after all rejected candidates still restores the pre-duplicate project")
        driver("redo", {})
        duplicated = complete_snapshot(bridge)
        assert content(duplicated) == duplicate_content, "Duplicate chain Redo changed IDs/content"

        ids_by_pitch = {n["pitch"]: n["id"] for n in duplicated["clip_notes"][copied_id]}
        edit_actions = [
            {"type": "trim_clip", "clip_id": copied_id, "start_seconds": 8.5, "end_seconds": 10},
            {"type": "delete_notes", "clip_id": copied_id, "note_ids": [ids_by_pitch[64]]},
            {"type": "set_note_length", "clip_id": copied_id, "note_ids": [ids_by_pitch[62]], "length_beats": .5},
            {"type": "move_notes", "clip_id": copied_id, "note_ids": [ids_by_pitch[67]], "delta_beats": -.25},
            {"type": "add_notes", "clip_id": copied_id, "notes": [note(72, 1, .25, 90)]},
            {"type": "delete_clip", "clip_id": phrase_id},
        ]
        edited = propose_and_apply("Synthetic trim/delete/resize/move/add notes and clip-deletion chain", edit_actions)
        assert find_track(edited, "Batch2 piano")["clips"] == [], "Explicit source clip deletion was not applied"
        edited_clip = find_track(edited, "Batch2 destination")["clips"][0]
        require_close(edited_clip["start_seconds"], 8.5, "Trimmed clip start")
        require_close(edited_clip["length_beats"], 3, "Trimmed clip length")
        expected_notes = [note(62, 0, .5, 60), note(72, 1, .25, 90), note(67, 1.75, 1, 60)]
        assert values(edited["clip_notes"][copied_id]) == expected_notes, "Sequential MIDI edit result differs"
        current_ids = {n["pitch"]: n["id"] for n in edited["clip_notes"][copied_id]}
        assert current_ids[62] == ids_by_pitch[62] and current_ids[67] == ids_by_pitch[67]
        assert current_ids[72] not in set(ids_by_pitch.values()), "Added note did not receive a fresh ID"
        checked("trim boundaries, note deletion/length/move/add and clip deletion match one sequential native result")
        edited_content = content(edited)
        undo_matches(duplicate_content, "one Undo restores both deleted clip and all pre-trim note data")
        driver("redo", {})
        assert content(complete_snapshot(bridge)) == edited_content, "Edit-chain Redo differs"

        path = (directory / "batch2-roundtrip.emproj").resolve()
        driver("save_project", {"path": str(path)})
        assert path.is_file() and path.stat().st_size > 0, "Save completion did not produce fixture project"
        driver("rename_track", {"track_id": piano_id, "name": "Unsaved synthetic alteration"})
        assert content(complete_snapshot(bridge)) != edited_content, "Roundtrip control edit did not change fixture"
        driver("open_project", {"path": str(path)})
        reopened = complete_snapshot(bridge)
        assert content(reopened) == edited_content, "Saved fixture did not restore IDs, clip deletion and explicit notes"
        checked("fixture-driver save/open restores persisted chain after an unsaved control edit")
        report["saved_project"] = str(path.relative_to(ROOT))
        report["final_content_sha256"] = hashlib.sha256(json.dumps(edited_content, sort_keys=True).encode()).hexdigest()
        if live_provider:
            assert 1 <= live_provider.usage["attempts"] <= 4, "Live phase exceeded permitted call budget"
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error"] = redact(str(exc))[:1000]
    finally:
        if runtime is not None and runtime.busy():
            try:
                runtime.cancel()
            except ValueError:
                pass  # A submitted atomic batch cannot be cancelled or retried.
        if bridge is not None:
            try:
                bridge.close()  # Only the disposable child created above.
            except Exception as exc:
                report["cleanup_error"] = redact(str(exc))[:300]
                report["passed"] = False
        report["real_model_usage"] = ({**live_provider.usage, "returned_models": sorted(live_provider.returned_models)}
            if live_provider else {"attempts": 0, "completed_responses": 0, "prompt_tokens": 0, "completion_tokens": 0, "returned_models": []})
        report["synthetic_provider_usage"] = {field: sum(provider.usage[field] for provider in fixtures)
            for field in ("attempts", "completed_responses", "prompt_tokens", "completion_tokens")}
        report["usage_note"] = "Only the initial creation chain may call a real provider. Later calls are fixtures. Failed attempts may be billed without usage."
        report["protected_file_count"] = len(guard)
        report["protected_files_unchanged"] = protected() == guard
        report["passed"] = report["passed"] and report["protected_files_unchanged"]
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
