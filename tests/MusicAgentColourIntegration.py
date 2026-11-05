"""Owned offline DAW + deterministic language fixture: track colour lifecycle.

Run through scripts.dev.Recorder against the new executable. No API calls,
audio devices or user projects are opened. GUI selection is not fabricated:
its local guard fixture and the real headless refusal are labelled separately.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_client import Client
from dev import configure_console_output
from music_agent.bridge import DawBridge
from music_agent.config import DEFAULT_CONFIG
from music_agent.plans import verify_plan
from music_agent.runtime import AgentRuntime
from music_agent.selection import ScopeError, constrain_proposal, freeze_scope
from MusicAgentAnalysisIntegration import Audit, Provider
from MusicAgentTempoIntegration import protected_changes, protected_snapshot


class ObservedBridge(DawBridge):
    """Observe real replies without replacing any native mutation or readback."""
    def __init__(self, client):
        super().__init__(client=client)
        self.applied = []

    def apply(self, plan):
        result = super().apply(plan)
        self.applied.append(deepcopy(result))
        return result


def colours(state):
    return {track["id"]: track["colour"] for track in state["tracks"]}


def content(state, *, omit_colour=False):
    result = {key: deepcopy(state[key]) for key in ("bpm", "numerator", "denominator", "tracks")}
    if omit_colour:
        for track in result["tracks"]:
            track.pop("colour", None)
    return result


def action(track_id, colour):
    return {"type": "set_track_colour", "track_id": track_id, "colour": colour}


def main():
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    directory = ROOT / "build/agent-colour-e2e" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    executable = directory / "E-musician.exe"
    shutil.copy2(args.exe, executable)
    report = {"passed": False, "mode": "owned-offline-native-with-deterministic-language-fixture",
              "physical_audio": False, "external_llm": False, "gui_selection_tested": False,
              "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "checks": []}
    checks = report["checks"]
    protected_before = protected_snapshot()
    client = None

    def wait(runtime, expected="done"):
        runtime.worker.join(args.timeout)
        assert not runtime.busy(), "Agent colour operation timed out"
        assert runtime.phase == expected, runtime.error or f"Unexpected phase: {runtime.phase}"

    try:
        client = Client(executable, timeout=args.timeout, show=False, offline_test=True)
        assert not client.state()["tracks"], "The owned offline fixture must start empty"
        for kind, name in (("instrument", "Colour keys"), ("audio", "Colour audio")):
            client.request({"command": "create_track", "args": {"kind": kind, "name": name}})
        ids = [track["id"] for track in client.state()["tracks"]]
        client.request({"command": "create_midi_clip", "args": {"track_id": ids[0], "start_beats": 0, "length_beats": 4}})
        clip_id = client.state()["tracks"][0]["clips"][0]["id"]
        client.request({"command": "write_notes", "args": {"clip_id": clip_id, "notes": [
            {"id": "colour-fixture-note", "pitch": 60, "start_beats": 0, "length_beats": 1, "velocity": 90, "channel": 1}]}})
        for track_id, colour in zip(ids, ("#1a2b3c", "#D8BEBC")):
            client.request({"command": "set_track_colour", "args": {"track_id": track_id, "colour": colour}})
        bridge = ObservedBridge(client)
        assert "set_track_colour" in bridge.capabilities()["commands"]
        initial = bridge.snapshot()
        initial_notes = client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip_id}}))["notes"]
        assert colours(initial) == dict(zip(ids, ("#1A2B3C", "#D8BEBC")))
        checks.append("Actual native capability and direct lower-case input normalize to canonical uppercase colours")
        provider = Provider("propose_plan", {"summary": "Colour both fixture tracks", "actions": [
            action(ids[0], "#bfd2cf"), action(ids[1], "#91a7c3")]})
        with patch("music_agent.runtime.has_key", return_value=False), patch("music_agent.providers.has_key", return_value=False), \
             patch("music_agent.runtime.load_config", return_value=deepcopy(DEFAULT_CONFIG)):
            runtime = AgentRuntime(bridge, provider=provider, audit=Audit())
            runtime.plan_request("Set the two fixture tracks to #BFD2CF and #91A7C3. Review first.", scope="project")
            wait(runtime, "ready")
            plan = deepcopy(runtime.plan)
            assert len(plan["commands"]) == 2 and all(c["command"] == "set_track_colour" for c in plan["commands"])
            assert [c["args"]["colour"] for c in plan["commands"]] == ["#BFD2CF", "#91A7C3"]
            assert "#1A2B3C → #BFD2CF" in plan["changes"][0]
            assert bridge.snapshot()["revision"] == initial["revision"] and content(bridge.snapshot()) == content(initial)
            assert not bridge.applied
            checks.append("Deterministic proposal creates an exact two-track review without mutating native state")
            runtime.apply(plan["id"])
            wait(runtime)
            applied = bridge.snapshot()
            assert len(bridge.applied) == 1 and bridge.applied[0]["result"]["executed_commands"] == 2
            assert applied["revision"] == initial["revision"] + 1
            assert colours(applied) == dict(zip(ids, ("#BFD2CF", "#91A7C3")))
            assert not verify_plan(plan, initial, applied)
            assert content(applied, omit_colour=True) == content(initial, omit_colour=True)
            assert client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip_id}}))["notes"] == initial_notes
            checks.append("Runtime applies one real native batch, verifies both colours and preserves MIDI notes, tempo and other track content")
            runtime.undo()
            wait(runtime)
            assert content(bridge.snapshot()) == content(initial)
            client.request({"command": "redo"})
            assert content(bridge.snapshot()) == content(applied)
            checks.append("One Agent Undo restores both original colours; one native Redo restores both confirmed colours")
            project = directory / "coloured.emproj"
            client.request({"command": "save_project", "args": {"path": str(project)}})
            client.request({"command": "open_project", "args": {"path": str(project)}})
            reopened = bridge.snapshot()
            assert content(reopened) == content(applied)
            assert client.completed(client.raw({"command": "get_clip_notes", "args": {"clip_id": clip_id}}))["notes"] == initial_notes
            checks.append("Actual asynchronous save/open preserves both colours and original note data")

            # A headless process owns no explicit GUI music selection. Refuse
            # widening this into a whole-project edit, even when a track is
            # automatically active after an open operation.
            assert reopened["selection_context"]["focus"] == "none"
            runtime.provider = Provider("propose_plan", {"summary": "Attempt selection colour", "actions": [action(ids[0], "#ABCDEF")]})
            runtime.plan_request("Colour my current selected track.", scope="selection")
            wait(runtime, "error")
            assert len(bridge.applied) == 1 and bridge.snapshot()["revision"] == reopened["revision"]
            assert content(bridge.snapshot()) == content(reopened)
            checks.append("Real headless selection request is rejected without a write; active track is not treated as explicit selection")

            # Pure authorization fixture over a copy of real IDs/content. It
            # never sends fabricated selection to the native host or provider.
            fixture = deepcopy(reopened)
            fixture["selection_context"] = {"project_id": fixture["project_id"], "project_revision": fixture["revision"],
                "selection_revision": 77, "available": True, "focus": "track", "active_track_id": ids[0],
                "active_clip_id": "", "track_ids": [ids[0]], "clip_ids": [], "note_clip_id": "", "note_ids": [], "note_count": 0,
                "time_range": {"active": False, "start_seconds": 0, "end_seconds": 0}}
            frozen = freeze_scope(fixture, "selection")
            allowed = {"summary": "Selected track only", "actions": [action(ids[0], "#ABCDEF")]}
            assert constrain_proposal(allowed, fixture, frozen) == allowed
            try:
                constrain_proposal({"summary": "Attempt to cross selection", "actions": [action(ids[0], "#ABCDEF"), action(ids[1], "#ABCDEF")]}, fixture, frozen)
            except ScopeError:
                pass
            else:
                raise AssertionError("Explicit single-track fixture improperly authorized the other track")
            checks.append("Labelled synthetic scope guard permits the explicit first track and rejects a mixed plan targeting the second track")
            stale = client.raw({"request_id": str(uuid.uuid4()), "project_id": reopened["project_id"],
                "expected_revision": reopened["revision"], "expected_selection_revision": reopened["selection_context"]["selection_revision"] + 1,
                "command": "batch", "args": {"commands": [{"command": "set_track_colour", "args": {"track_id": ids[0], "colour": "#ABCDEF"}}]}})
            assert stale["status"] == "selection_conflict"
            assert content(bridge.snapshot()) == content(reopened) and bridge.snapshot()["revision"] == reopened["revision"]
            checks.append("Actual native selection-revision guard rejects a stale colour batch without partial edits")
            report["mock_provider_calls"] = provider.calls + runtime.provider.calls
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if client:
            client.close()
        report["protected_file_changes"] = protected_changes(protected_before, protected_snapshot())
        report["protected_settings_unchanged"] = report["protected_file_changes"]["unchanged"]
        report["passed"] = report["passed"] and report["protected_settings_unchanged"]
        output = directory / "result.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(output)
    assert report["passed"]


if __name__ == "__main__":
    main()
