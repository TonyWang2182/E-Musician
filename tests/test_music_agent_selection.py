"""Explicit user scope cannot be widened by model output or changed selection."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.selection import ScopeError, freeze_scope, assert_scope_unchanged, constrain_proposal


def context():
    notes = [{"id": "n1", "pitch": 60, "start_beats": 0, "length_beats": 0.5, "velocity": 80, "channel": 1},
             {"id": "n2", "pitch": 62, "start_beats": 2, "length_beats": 0.5, "velocity": 80, "channel": 1},
             {"id": "n3", "pitch": 64, "start_beats": 4, "length_beats": 0.5, "velocity": 80, "channel": 1}]
    return {"project_id": "p", "revision": 4, "bpm": 120, "numerator": 6, "denominator": 8,
            "tracks": [{"id": "t", "kind": "instrument", "clips": [
                {"id": "c", "kind": "midi", "start_seconds": 3, "duration_seconds": 3, "note_count": 3},
                {"id": "outside", "kind": "midi", "start_seconds": 8, "duration_seconds": 1, "note_count": 0}]}],
            "clip_notes": {"c": notes}, "selection_context": {
                "project_id": "p", "project_revision": 4, "selection_revision": 8,
                "active_track_id": "t", "active_clip_id": "c", "track_ids": ["t"], "clip_ids": ["c"],
                "note_clip_id": "c", "note_ids": ["n2"], "note_count": 1, "notes_truncated": False,
                "time_range": {"active": False, "start_seconds": 0, "end_seconds": 0},
                "focus": "piano_roll", "available": True}}


def proposal(action=None):
    return {"summary": "edit", "actions": [action or {"type": "transpose_notes", "clip_id": "c", "semitones": 12}]}


class SelectionTests(unittest.TestCase):
    def test_selected_notes_constrain_all_notes_model_action(self):
        before = context()
        original = deepcopy(before)
        payload = proposal()
        result = constrain_proposal(payload, before, freeze_scope(before))
        self.assertEqual(result["actions"][0]["note_ids"], ["n2"])
        self.assertNotIn("note_ids", payload["actions"][0])
        self.assertEqual(before, original)

    def test_explicit_model_scope_widening_rejected(self):
        before = context()
        payload = proposal()
        payload["actions"][0]["note_ids"] = ["n1", "n2"]
        with self.assertRaises(ScopeError):
            constrain_proposal(payload, before, freeze_scope(before))

    def test_explicit_whole_clip_overrides_note_subset(self):
        before = context()
        frozen = freeze_scope(before, "clip")
        self.assertEqual(constrain_proposal(proposal(), before, frozen)["actions"][0]["note_ids"], ["n1", "n2", "n3"])

    def test_explicit_project_allows_global_edit_without_selection(self):
        before = context()
        del before["selection_context"]
        frozen = freeze_scope(before, "project")
        payload = proposal({"type": "set_tempo", "bpm": 100})
        self.assertEqual(constrain_proposal(payload, before, frozen), payload)
        self.assertNotIn("selection_revision", frozen)

    def test_global_edit_refused_in_selection_and_clip_scope(self):
        before = context()
        for mode in ("selection", "clip"):
            for action in ({"type": "set_tempo", "bpm": 100}, {"type": "create_track", "kind": "audio", "name": "new"}):
                with self.subTest(mode=mode, action=action), self.assertRaises(ScopeError):
                    constrain_proposal(proposal(action), before, freeze_scope(before, mode))

    def test_stale_selection_project_and_music_revision_are_distinct_guards(self):
        before = context()
        frozen = freeze_scope(before)
        for field, value in (("project_id", "other"), ("revision", 5)):
            after = deepcopy(before)
            after[field] = value
            with self.subTest(field=field), self.assertRaises(ScopeError):
                assert_scope_unchanged(frozen, after)
        after = deepcopy(before)
        after["selection_context"]["selection_revision"] += 1
        with self.assertRaises(ScopeError):
            assert_scope_unchanged(frozen, after)
        after = deepcopy(before)
        after["selection_context"]["note_ids"] = ["n1"]
        with self.assertRaises(ScopeError):
            assert_scope_unchanged(frozen, after)

    def test_project_scope_ignores_later_selection_only(self):
        before = context()
        frozen = freeze_scope(before, "project")
        before["selection_context"]["selection_revision"] += 10
        assert_scope_unchanged(frozen, before)

    def test_no_selection_metadata_never_infers_from_active_ids(self):
        before = context()
        del before["selection_context"]
        before["selected_clip_id"] = "c"
        with self.assertRaises(ScopeError):
            freeze_scope(before)

    def test_partial_large_malformed_selection_refused(self):
        for update in ({"available": False}, {"notes_truncated": True}, {"note_count": 2001},
                       {"note_ids": ["n2", "n2"]}, {"selection_revision": True}, {"project_revision": 3}):
            before = context()
            before["selection_context"].update(update)
            with self.subTest(update=update), self.assertRaises(ScopeError):
                freeze_scope(before)

    def test_time_range_uses_absolute_seconds_and_half_open_note_onsets(self):
        before = context()
        before["selection_context"].update(focus="arrangement", note_ids=[], note_count=0,
            time_range={"active": True, "start_seconds": 4, "end_seconds": 5})
        result = constrain_proposal(proposal(), before, freeze_scope(before))
        self.assertEqual(result["actions"][0]["note_ids"], ["n2"])
        # 6/8 does not alter quarter-beat -> second conversion.
        before["numerator"], before["denominator"] = 4, 4
        self.assertEqual(constrain_proposal(proposal(), before, freeze_scope(before))["actions"][0]["note_ids"], ["n2"])

    def test_time_range_zero_hit_refuses_instead_of_all_notes(self):
        before = context()
        before["selection_context"].update(focus="arrangement", note_ids=[], note_count=0,
            time_range={"active": True, "start_seconds": 4.5, "end_seconds": 4.9})
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal(), before, freeze_scope(before))

    def test_quantization_cannot_escape_time_selection(self):
        before = context()
        before["clip_notes"]["c"][1]["start_beats"] = 2.9
        before["selection_context"].update(focus="arrangement", note_ids=[], note_count=0,
            time_range={"active": True, "start_seconds": 4.4, "end_seconds": 4.49})
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal({"type": "quantize_notes", "clip_id": "c", "grid_denominator": 4}), before, freeze_scope(before))

    def test_note_scope_cannot_move_clip_or_change_whole_track(self):
        before = context()
        for action in ({"type": "move_clip", "clip_id": "c", "start_seconds": 2},
                       {"type": "set_track_gain", "track_id": "t", "gain_db": -6}):
            with self.subTest(action=action), self.assertRaises(ScopeError):
                constrain_proposal(proposal(action), before, freeze_scope(before))

    def test_track_only_scope_can_change_that_track(self):
        before = context()
        before["selection_context"].update(focus="track", clip_ids=[], note_ids=[], note_count=0)
        payload = proposal({"type": "set_track_gain", "track_id": "t", "gain_db": -6})
        self.assertEqual(constrain_proposal(payload, before, freeze_scope(before)), payload)
        payload["actions"][0]["track_id"] = "other"
        with self.assertRaises(ScopeError):
            constrain_proposal(payload, before, freeze_scope(before))

    def test_clip_scope_rejects_other_clip(self):
        before = context()
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal({"type": "move_clip", "clip_id": "outside", "start_seconds": 2}), before, freeze_scope(before, "clip"))

    def test_time_range_cannot_move_partially_selected_clip(self):
        before = context()
        before["selection_context"].update(focus="arrangement", note_ids=[], note_count=0,
            time_range={"active": True, "start_seconds": 4, "end_seconds": 5})
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal({"type": "move_clip", "clip_id": "c", "start_seconds": 4}), before, freeze_scope(before))

    def test_empty_selection_never_falls_back_to_whole_project(self):
        before = context()
        before["selection_context"].update(focus="none", clip_ids=[], track_ids=[], note_ids=[], note_count=0)
        with self.assertRaises(ScopeError):
            constrain_proposal(proposal(), before, freeze_scope(before))


if __name__ == "__main__":
    unittest.main()
