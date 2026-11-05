"""Track colour is a scoped, reviewable metadata edit; synthetic peers only."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.audit import Audit
from music_agent.bridge import public_snapshot
from music_agent.config import DEFAULT_CONFIG
from music_agent.plans import PlanError, compile_plan, resolve_plan_refs, verify_plan
from music_agent.runtime import AgentRuntime
from music_agent.selection import ScopeError, constrain_proposal, freeze_scope
from test_music_agent_plans import fixture, propose
from test_music_agent_runtime import FakeBridge, FakeProvider, proposal
from test_music_agent_selection import context as selection_context


def action(track_id="midi-1", colour="#bfd2cf"):
    return {"type": "set_track_colour", "track_id": track_id, "colour": colour}


class ColourPlanTests(unittest.TestCase):
    def test_strict_colour_normalized_and_review_contains_actual_before_after(self):
        before = fixture()
        before["tracks"][0]["colour"] = "#D8BEBC"
        frozen = deepcopy(before)
        plan = compile_plan(propose(action()), before)
        self.assertEqual(plan["commands"], [{"command": "set_track_colour", "args": {"track_id": "midi-1", "colour": "#BFD2CF"}}])
        self.assertIn("#D8BEBC → #BFD2CF", plan["changes"][0])
        self.assertIn("不改变声音", plan["changes"][0])
        self.assertEqual(before, frozen)
        after = deepcopy(before)
        after["tracks"][0]["colour"] = "#BFD2CF"
        self.assertEqual(verify_plan(plan, before, after), [])
        after["tracks"][0]["colour"] = "#000000"
        self.assertTrue(verify_plan(plan, before, after))
        del after["tracks"][0]["colour"]
        self.assertTrue(verify_plan(plan, before, after))

    def test_invalid_colour_is_rejected_before_any_command(self):
        for colour in (None, 0, True, "#abc", "#001122FF", "001122", "#GG1122", "red", " #001122", "#001122\n"):
            with self.subTest(colour=colour), self.assertRaises(PlanError):
                compile_plan(propose(action(colour=colour)), fixture())

    def test_reset_and_noop(self):
        before = fixture()
        before["tracks"][0]["colour"] = "#BFD2CF"
        plan = compile_plan(propose(action(colour="")), before)
        self.assertIn("#BFD2CF → 默认", plan["changes"][0])
        with self.assertRaises(PlanError):
            compile_plan(propose(action()), before)
        before["tracks"][0]["colour"] = ""
        with self.assertRaises(PlanError):
            compile_plan(propose(action(colour="")), before)

    def test_new_track_alias_has_colour_postcondition(self):
        before = fixture()
        plan = compile_plan(propose({"type": "create_track", "kind": "instrument", "name": "Coloured keys", "as": "keys"}, action("@keys")), before)
        bound = resolve_plan_refs(plan, {"keys": "new-track"})
        check = next(c for c in bound["checks"] if c.get("id") == "new-track")
        self.assertEqual(check["value"]["colour"], "#BFD2CF")
        self.assertEqual(plan["commands"][1]["args"]["track_id"], "@keys")

    def test_public_snapshot_preserves_colour_without_adding_private_fields(self):
        before = fixture()
        before["tracks"][0].update(colour="#BFD2CF", secret_path="never-export")
        public = public_snapshot(before)
        self.assertEqual(public["tracks"][0]["colour"], "#BFD2CF")
        self.assertNotIn("secret_path", public["tracks"][0])

    def test_note_clip_and_range_selection_cannot_authorize_whole_track_colour(self):
        for focus, mode in (("piano_roll", "selection"), ("arrangement", "selection"), ("arrangement", "clip")):
            before = selection_context()
            before["selection_context"]["focus"] = focus
            with self.subTest(focus=focus, mode=mode), self.assertRaises(ScopeError):
                constrain_proposal(propose(action("t")), before, freeze_scope(before, mode))
        before = selection_context()
        before["selection_context"].update(focus="arrangement", clip_ids=[], note_ids=[], note_clip_id="", note_count=0,
                                            time_range={"active": True, "start_seconds": 0, "end_seconds": 4})
        with self.assertRaises(ScopeError):
            constrain_proposal(propose(action("t")), before, freeze_scope(before))
        before = selection_context()
        selection = before["selection_context"]
        selection.update(focus="track", clip_ids=[], note_ids=[], note_clip_id="", note_count=0)
        result = constrain_proposal(propose(action("t")), before, freeze_scope(before))
        self.assertEqual(result["actions"][0]["colour"], "#bfd2cf")
        selection["track_ids"] = []
        selection["active_track_id"] = "unrelated"
        with self.assertRaises(ScopeError):
            constrain_proposal(propose(action("t")), before, freeze_scope(before))


class ColourBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.data["tracks"][0]["colour"] = "#D8BEBC"
        self.supported = True
        self.bad_colour = False

    def capabilities(self):
        return {"commands": ["set_track_colour"] if self.supported else []}

    def apply(self, plan):
        # Keep all normal transaction/revision/undo behavior in the existing
        # fixture, replacing its supported edit with the colour metadata edit.
        synthetic = deepcopy(plan)
        target = synthetic["commands"][0]["args"]["colour"]
        synthetic["commands"] = [{"command": "rename_track", "args": {"track_id": "track-1", "name": self.data["tracks"][0]["name"]}}]
        result = super().apply(synthetic)
        self.calls[-1] = ("apply", deepcopy(plan))
        self.data["tracks"][0]["colour"] = "#000000" if self.bad_colour else target
        return result


class ColourRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="em-track-colour-")
        self.addCleanup(self.directory.cleanup)
        for target, value in (("music_agent.runtime.has_key", False), ("music_agent.providers.has_key", False),
                              ("music_agent.runtime.load_config", deepcopy(DEFAULT_CONFIG))):
            current = patch(target, return_value=value)
            current.start()
            self.addCleanup(current.stop)
        self.bridge = ColourBridge()
        self.runtime = AgentRuntime(self.bridge, FakeProvider([proposal(action("track-1"))]), Audit(Path(self.directory.name) / "audit.jsonl"))

    def finish(self):
        self.runtime.worker.join(4)
        self.assertFalse(self.runtime.busy())
        return self.runtime.state(False)

    def plan(self):
        self.runtime.plan_request("把钢琴轨设为灰绿色 #BFD2CF", scope="project")
        return self.finish()

    def test_preview_apply_exact_readback_and_single_undo(self):
        ready = self.plan()
        self.assertEqual(ready["phase"], "ready")
        self.assertEqual(self.bridge.data["tracks"][0]["colour"], "#D8BEBC")
        self.runtime.apply(ready["plan"]["id"])
        done = self.finish()
        self.assertEqual(done["phase"], "done")
        self.assertEqual(self.bridge.data["tracks"][0]["colour"], "#BFD2CF")
        self.assertTrue(done["can_undo"])
        self.runtime.undo()
        self.finish()
        self.assertEqual(self.bridge.data["tracks"][0]["colour"], "#D8BEBC")
        self.assertEqual([call[0] for call in self.bridge.calls], ["apply", "undo"])

    def test_wrong_readback_reports_error_and_preserves_available_undo(self):
        ready = self.plan()
        self.bridge.bad_colour = True
        self.runtime.apply(ready["plan"]["id"])
        done = self.finish()
        self.assertEqual(done["phase"], "error")
        self.assertTrue(done["can_undo"])
        self.assertEqual(len(self.bridge.calls), 1)

    def test_older_host_rejected_before_plan_or_write(self):
        self.bridge.supported = False
        result = self.plan()
        self.assertEqual(result["phase"], "error")
        self.assertIn("轨道颜色", result["error"])
        self.assertFalse(self.bridge.calls)
        self.assertIsNone(result["plan"])


if __name__ == "__main__":
    unittest.main()
