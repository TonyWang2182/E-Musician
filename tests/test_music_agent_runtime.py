"""Async orchestration and protocol boundaries with deterministic in-memory peers.

No model calls, credentials, user projects, real DAW processes or audio devices.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_client import ControlError
from music_agent.audit import Audit
from music_agent.bridge import BridgeError, DawBridge, identity
from music_agent.runtime import AgentRuntime


def context():
    return {"project_id": "project-1", "revision": 7, "name": "Synthetic fixture",
        "dirty": False, "bpm": 120.0, "numerator": 4, "denominator": 4,
        "recording": False, "recording_finalizing": False, "can_undo": False,
        "tracks": [{"id": "track-1", "name": "Piano", "kind": "instrument",
            "gain_db": 0, "pan": 0, "muted": False, "solo": False,
            "clip_count": 1, "clips_truncated": False,
            "clips": [{"id": "clip-1", "kind": "midi", "start_seconds": 0,
                "duration_seconds": 2, "start_beats": 0, "length_beats": 4, "note_count": 1}]}],
        "clip_notes": {}}


NOTES = [{"id": "note-1", "pitch": 60, "start_beats": 0, "length_beats": 1,
          "velocity": 70, "channel": 1}]


def tool(name, arguments, *, reasoning=None, raw=False):
    message = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call-1", "type": "function", "function": {
            "name": name, "arguments": arguments if raw else json.dumps(arguments)}}]}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"message": message, "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def proposal(*actions):
    return tool("propose_plan", {"summary": "调整已指定的工程内容", "actions": list(actions)})


TEMPO = {"type": "set_tempo", "bpm": 100}


class FakeProvider:
    model = "mock-model"
    base_url = "https://api.moonshot.cn/v1"

    def __init__(self, responses, block=False):
        self.responses = list(responses)
        self.requests = []
        self.entered = threading.Event()
        self.release = threading.Event()
        if not block:
            self.release.set()

    def complete(self, messages, tools):
        self.requests.append(deepcopy(messages))
        self.entered.set()
        if not self.release.wait(3):
            raise RuntimeError("Test provider was not released")
        return deepcopy(self.responses.pop(0))


class FakeBridge:
    def __init__(self):
        self.connected = True
        self.data = context()
        self.notes = deepcopy(NOTES)
        self.calls = []
        self.last_before = None
        self.last_notes = None
        self.corrupt_after_apply = False

    def snapshot(self):
        return deepcopy(self.data)

    def read_notes(self, snapshot, clip_id):
        if identity(snapshot) != identity(self.data) or clip_id != "clip-1":
            raise BridgeError("Stale or unknown test clip")
        snapshot.setdefault("clip_notes", {})[clip_id] = deepcopy(self.notes)
        return deepcopy(self.notes)

    def apply(self, plan):
        self.calls.append(("apply", deepcopy(plan)))
        if identity(self.data) != (plan["project_id"], plan["revision"]):
            raise BridgeError("Stale test identity")
        self.last_before = deepcopy(self.data)
        self.last_notes = deepcopy(self.notes)
        for item in plan["commands"]:
            command, args = item["command"], item["args"]
            if command == "set_tempo":
                self.data["bpm"] = args["bpm"]
                self.data["tracks"][0]["clips"][0]["duration_seconds"] = 240 / args["bpm"]
            elif command == "edit_notes":
                self.notes = deepcopy(args["upsert"])
            elif command == "rename_track":
                self.data["tracks"][0]["name"] = args["name"]
            else:
                raise AssertionError("Fixture does not implement " + command)
        if self.corrupt_after_apply:
            self.data["bpm"] = 95
        self.data.update(revision=self.data["revision"] + 1, dirty=True, can_undo=True)
        return {"project_id": self.data["project_id"], "revision": self.data["revision"], "status": "completed"}

    def undo(self, project_id, revision, request_id):
        if identity(self.data) != (project_id, revision):
            raise BridgeError("Stale test identity")
        self.calls.append(("undo", request_id))
        self.data = deepcopy(self.last_before)
        self.notes = deepcopy(self.last_notes)
        self.data["revision"] = revision + 1
        return {"project_id": project_id, "revision": revision + 1, "status": "completed"}

    def close(self):
        self.connected = False


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="em-agent-runtime-test-")
        self.audit_path = Path(self.directory.name) / "audit.jsonl"
        self.runtimes = []
        self.key_patch = patch("music_agent.runtime.has_key", return_value=False)
        self.key_patch.start()

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.cancel_event.set()
            runtime.provider.release.set()
            if runtime.worker:
                runtime.worker.join(3)
        self.key_patch.stop()
        self.directory.cleanup()

    def make(self, *responses, block=False):
        provider = FakeProvider(responses, block)
        runtime = AgentRuntime(FakeBridge(), provider=provider, audit=Audit(self.audit_path))
        self.runtimes.append(runtime)
        return runtime

    def finish(self, runtime):
        runtime.worker.join(4)
        self.assertFalse(runtime.worker.is_alive(), "Runtime worker did not finish")
        return runtime.state(False)

    def ready(self, runtime):
        runtime.plan_request("将速度改成100 BPM")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "ready", state)
        self.assertFalse(runtime.bridge.calls)
        return state["plan"]["id"]

    def test_full_preview_apply_verify_once_and_undo(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        self.assertEqual(runtime.bridge.data["bpm"], 120)
        self.assertNotIn("commands", runtime.state(False)["plan"])
        runtime.apply(plan_id)
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "done", state)
        self.assertEqual(runtime.bridge.data["bpm"], 100)
        self.assertTrue(state["can_undo"])
        self.assertEqual(len(runtime.bridge.calls), 1)
        submitted = runtime.bridge.calls[0][1]
        self.assertEqual((submitted["project_id"], submitted["revision"]), ("project-1", 7))
        with self.assertRaises(ValueError):
            runtime.apply(plan_id)
        self.assertEqual(len(runtime.bridge.calls), 1)
        runtime.undo()
        state = self.finish(runtime)
        self.assertEqual(runtime.bridge.data["bpm"], 120)
        self.assertFalse(state["can_undo"])
        self.assertEqual([c[0] for c in runtime.bridge.calls], ["apply", "undo"])

    def test_stale_project_or_revision_never_submits_old_plan(self):
        for field, value in (("project_id", "project-2"), ("revision", 8)):
            with self.subTest(field=field):
                runtime = self.make(proposal(TEMPO))
                plan_id = self.ready(runtime)
                runtime.bridge.data[field] = value
                runtime.apply(plan_id)
                state = self.finish(runtime)
                self.assertEqual(state["phase"], "error")
                self.assertFalse(runtime.bridge.calls)

    def test_stale_during_model_request_never_publishes_plan(self):
        runtime = self.make(proposal(TEMPO), block=True)
        runtime.plan_request("Change tempo")
        self.assertTrue(runtime.provider.entered.wait(1))
        runtime.bridge.data["revision"] += 1
        runtime.provider.release.set()
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertIsNone(state["plan"])
        self.assertFalse(runtime.bridge.calls)

    def test_cancel_inflight_model_disposes_late_proposal_without_mutation(self):
        runtime = self.make(proposal(TEMPO), block=True)
        runtime.plan_request("Change tempo")
        self.assertTrue(runtime.provider.entered.wait(1))
        cancelled = runtime.cancel()
        self.assertTrue(cancelled["busy"])
        runtime.provider.release.set()
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "cancelled")
        self.assertIsNone(state["plan"])
        self.assertEqual(runtime.bridge.data["revision"], 7)
        self.assertFalse(runtime.bridge.calls)
        self.assertEqual(state["usage"]["calls"], 1)

    def test_ready_plan_cancel_and_wrong_plan_id(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        with self.assertRaises(ValueError):
            runtime.apply("some-other-plan")
        self.assertEqual(runtime.state(False)["plan"]["id"], plan_id)
        runtime.cancel()
        with self.assertRaises(ValueError):
            runtime.apply(plan_id)
        self.assertFalse(runtime.bridge.calls)

    def test_ready_worker_exit_race_does_not_consume_plan(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        # _propose publishes ready before its worker has returned. A simultaneous
        # Apply must reject busy without destroying the already reviewed plan.
        with patch.object(runtime, "busy", return_value=True):
            with self.assertRaises(ValueError):
                runtime.apply(plan_id)
        self.assertIsNotNone(runtime.plan)
        self.assertEqual(runtime.plan["id"], plan_id)
        self.assertFalse(runtime.bridge.calls)

    def test_atomic_apply_cannot_be_cancelled_halfway(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        entered, release = threading.Event(), threading.Event()
        original = runtime.bridge.apply
        def blocked(plan):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Test apply was not released")
            return original(plan)
        runtime.bridge.apply = blocked
        try:
            runtime.apply(plan_id)
            self.assertTrue(entered.wait(1))
            with self.assertRaises(ValueError):
                runtime.cancel()
            self.assertFalse(runtime.cancel_event.is_set())
        finally:
            release.set()
        self.assertEqual(self.finish(runtime)["phase"], "done")
        self.assertEqual(len(runtime.bridge.calls), 1)

    def test_unknown_tool_duplicate_keys_and_nonfinite_arguments_stop(self):
        cases = [tool("run_shell", {"command": "anything"}),
                 tool("propose_plan", '{"summary":"x","summary":"y","actions":[]}', raw=True),
                 tool("propose_plan", '{"summary":"x","actions":[{"type":"set_tempo","bpm":NaN}]}', raw=True),
                 tool("read_clip_notes", {"clip_id": "clip-1", "path": "not-allowed"}),
                 tool("propose_plan", '[]', raw=True)]
        for response in cases:
            with self.subTest(response=response):
                runtime = self.make(response)
                runtime.plan_request("Test boundary")
                state = self.finish(runtime)
                self.assertEqual(state["phase"], "error")
                self.assertFalse(runtime.bridge.calls)

    def test_mixed_propose_and_read_calls_do_not_apply_or_publish(self):
        response = proposal(TEMPO)
        response["message"]["tool_calls"].extend(tool("read_clip_notes", {"clip_id": "clip-1"})["message"]["tool_calls"])
        runtime = self.make(response)
        runtime.plan_request("Mixed response")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertFalse(runtime.bridge.calls)

    def test_four_call_budget_stops_read_loop(self):
        runtime = self.make(*[tool("read_clip_notes", {"clip_id": "clip-1"}) for _ in range(4)])
        runtime.plan_request("Repeated reads")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertIn("4", state["error"])
        self.assertEqual(len(runtime.provider.requests), 4)
        self.assertEqual(state["usage"], {"calls": 4, "prompt_tokens": 12, "completion_tokens": 8})
        self.assertFalse(runtime.bridge.calls)

    def test_note_read_loop_retains_reasoning_and_actual_notes_remain_local(self):
        reasoning = "synthetic reasoning marker"
        runtime = self.make(tool("read_clip_notes", {"clip_id": "clip-1"}, reasoning=reasoning),
            proposal({"type": "transpose_notes", "clip_id": "clip-1", "semitones": 12}))
        runtime.plan_request("将当前片段提高一个八度")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "ready", state)
        second = runtime.provider.requests[1]
        prior = next(m for m in second if m.get("tool_calls"))
        self.assertEqual(prior["reasoning_content"], reasoning)
        self.assertEqual(json.loads(second[-1]["content"])["note_count"], 1)
        self.assertEqual(second[-1]["tool_call_id"], "call-1")
        self.assertEqual(runtime.bridge.notes[0]["pitch"], 60)
        runtime.apply(state["plan"]["id"])
        after = self.finish(runtime)
        self.assertEqual(after["phase"], "done", after)
        self.assertEqual(runtime.bridge.notes[0]["pitch"], 72)
        self.assertNotIn(reasoning, json.dumps(after))
        self.assertNotIn(reasoning, self.audit_path.read_text(encoding="utf-8"))

    def test_text_answer_is_not_mislabeled_as_an_applied_plan(self):
        runtime = self.make({"message": {"role": "assistant", "content": "请选择具体 MIDI 片段。"}, "usage": {}})
        runtime.plan_request("修改一下")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "done")
        self.assertIsNone(state["plan"])
        self.assertFalse(runtime.bridge.calls)
        self.assertFalse(state["can_undo"])

    def test_postcondition_failure_reports_committed_and_keeps_guarded_undo(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        runtime.bridge.corrupt_after_apply = True
        runtime.apply(plan_id)
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertIn("已提交", state["error"])
        self.assertTrue(state["can_undo"])
        self.assertEqual(len(runtime.bridge.calls), 1)

    def test_later_manual_edit_is_never_undone_by_agent(self):
        runtime = self.make(proposal(TEMPO))
        plan_id = self.ready(runtime)
        runtime.apply(plan_id)
        self.finish(runtime)
        runtime.bridge.data["revision"] += 1
        runtime.undo()
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "error")
        self.assertEqual([c[0] for c in runtime.bridge.calls], ["apply"])
        self.assertFalse(runtime.state()["can_undo"])

    def test_busy_settings_and_second_request_are_rejected(self):
        runtime = self.make(proposal(TEMPO), block=True)
        runtime.plan_request("Test")
        self.assertTrue(runtime.provider.entered.wait(1))
        with patch("music_agent.runtime.save_key") as save:
            with self.assertRaises(ValueError):
                runtime.settings({"model": "kimi-k2.5", "api_key": "synthetic-not-a-real-key"})
            save.assert_not_called()
        with self.assertRaises(ValueError):
            runtime.plan_request("another")
        runtime.cancel()
        runtime.provider.release.set()
        self.finish(runtime)

    def test_recording_refuses_before_any_model_cost(self):
        for field in ("recording", "recording_finalizing", "counting_in"):
            with self.subTest(field=field):
                runtime = self.make(proposal(TEMPO))
                runtime.bridge.data[field] = True
                runtime.plan_request("Change")
                state = self.finish(runtime)
                self.assertEqual(state["phase"], "error")
                self.assertEqual(state["usage"]["calls"], 0)
                self.assertFalse(runtime.provider.requests)

    def test_metadata_audit_never_persists_prompt_notes_names_key_or_reasoning(self):
        marker = "PRIVATE_USER_PROMPT_SENTINEL"
        key = "sk-syntheticNOTaREALcredential1234567890"
        name = "PRIVATE_TRACK_NAME_SENTINEL"
        runtime = self.make(proposal({"type": "rename_track", "track_id": "track-1", "name": name}))
        runtime.plan_request(f"{marker} rename track. {key}")
        state = self.finish(runtime)
        self.assertEqual(state["phase"], "ready")
        runtime.apply(state["plan"]["id"])
        self.finish(runtime)
        audit = self.audit_path.read_text(encoding="utf-8")
        for secret in (marker, key, name, "start_beats", "velocity"):
            self.assertNotIn(secret, audit)
        self.assertIn("commands_sha256", audit)
        self.assertNotIn(key, json.dumps(runtime.state(False)))
        self.assertNotIn(key, json.dumps(runtime.provider.requests))

    def test_close_protects_unsaved_edit(self):
        runtime = self.make(proposal(TEMPO))
        runtime.bridge.data["dirty"] = True
        with self.assertRaises(ValueError):
            runtime.close()
        self.assertTrue(runtime.bridge.connected)
        runtime.bridge.data["dirty"] = False
        runtime.close()
        self.assertFalse(runtime.bridge.connected)

    def test_close_disconnected_live_daw_does_not_close_stdin_or_kill_child(self):
        runtime = self.make(proposal(TEMPO))
        runtime.bridge.connected = False
        runtime.bridge.client = SimpleNamespace(process=SimpleNamespace(poll=lambda: None))
        # Protocol state is unknown: do not trust the stale clean snapshot.
        runtime.snapshot = {"dirty": False}
        with patch.object(runtime.bridge, "close") as close:
            with self.assertRaisesRegex(ValueError, "手动关闭"):
                runtime.close()
            close.assert_not_called()

    def test_close_disconnected_exited_daw_allows_service_cleanup(self):
        runtime = self.make(proposal(TEMPO))
        runtime.bridge.connected = False
        runtime.bridge.client = SimpleNamespace(process=SimpleNamespace(poll=lambda: 0))
        with patch.object(runtime.bridge, "close") as close:
            runtime.close()
            close.assert_called_once_with()


class ScriptedClient:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def raw(self, envelope):
        self.requests.append(deepcopy(envelope))
        return self.handler(envelope)

    def close(self):
        pass


def reply(envelope, result=None, **extra):
    return {"request_id": envelope["request_id"], "status": "completed", "result": result or {}, **extra}


class BridgeProtocolTests(unittest.TestCase):
    def test_apply_preserves_approved_identity_and_request_id_exactly(self):
        client = ScriptedClient(lambda e: reply(e))
        bridge = DawBridge(client=client)
        commands = [{"command": "set_tempo", "args": {"bpm": 100}}]
        plan = {"id": "approved-plan", "project_id": "original-project", "revision": 8, "commands": commands}
        bridge.apply(plan)
        self.assertEqual(client.requests, [{"request_id": "approved-plan", "project_id": "original-project",
            "expected_revision": 8, "command": "batch", "args": {"commands": commands}}])

    def test_timeout_disconnects_and_never_automatically_retries(self):
        def timeout(_):
            raise ControlError("synthetic timeout")
        client = ScriptedClient(timeout)
        bridge = DawBridge(client=client)
        with self.assertRaises(BridgeError):
            bridge.snapshot()
        self.assertFalse(bridge.connected)
        with self.assertRaises(BridgeError):
            bridge.snapshot()
        self.assertEqual(len(client.requests), 1)

    def test_out_of_order_reply_disconnects(self):
        client = ScriptedClient(lambda e: {"request_id": "wrong", "status": "completed", "result": {}})
        bridge = DawBridge(client=client)
        with self.assertRaises(BridgeError):
            bridge.snapshot()
        self.assertFalse(bridge.connected)

    def test_conflict_not_rewritten_or_retried(self):
        client = ScriptedClient(lambda e: reply(e, status="conflict"))
        bridge = DawBridge(client=client)
        with self.assertRaises(BridgeError):
            bridge.apply({"id": "plan", "project_id": "project-1", "revision": 7, "commands": []})
        self.assertEqual(len(client.requests), 1)
        self.assertTrue(bridge.connected)

    def test_note_pagination_changes_rejected(self):
        source = context()
        source["tracks"][0]["clips"][0]["note_count"] = 1001
        def handler(envelope):
            if envelope["command"] == "get_snapshot":
                return reply(envelope, source)
            args = envelope["args"]
            return reply(envelope, {"total": 1001 if args["offset"] == 0 else 1002,
                "offset": args["offset"], "notes": deepcopy(NOTES) * (1000 if args["offset"] == 0 else 1)})
        bridge = DawBridge(client=ScriptedClient(handler))
        with self.assertRaises(BridgeError):
            bridge.read_notes(source, "clip-1")
        self.assertFalse(source["clip_notes"])

    def test_note_read_detects_project_change_after_last_page(self):
        source = context()
        snapshots = 0
        def handler(envelope):
            nonlocal snapshots
            if envelope["command"] == "get_snapshot":
                snapshots += 1
                value = deepcopy(source)
                if snapshots > 1:
                    value["revision"] += 1
                return reply(envelope, value)
            return reply(envelope, {"total": 1, "offset": 0, "notes": deepcopy(NOTES)})
        bridge = DawBridge(client=ScriptedClient(handler))
        with self.assertRaises(BridgeError):
            bridge.read_notes(source, "clip-1")
        self.assertFalse(source["clip_notes"])


if __name__ == "__main__":
    unittest.main()
