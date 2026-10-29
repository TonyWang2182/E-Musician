"""Dependent edits, native result refs, exact note changes and frozen scope.

Synthetic DTOs only. Native atomicity/CC preservation is verified separately by
EngineSession smoke; these tests make no claim about model or audio quality.
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.plans import PlanError, compile_plan, verify_plan, resolve_plan_refs, required_note_clip_ids
from music_agent.selection import ScopeError, constrain_proposal, freeze_scope
from test_music_agent_plans import fixture, propose
from test_music_agent_selection import context as selected_context


def note(**overrides):
    return {"pitch": 67, "start_beats": 1, "length_beats": 0.5, "velocity": 85, "channel": 1, **overrides}


def creation():
    return propose({"type": "create_track", "kind": "instrument", "name": "New keys", "as": "keys"},
                   {"type": "create_midi_clip", "track_id": "@keys", "start_beats": 6, "length_beats": 6, "as": "part"},
                   {"type": "add_notes", "clip_id": "@part", "notes": [note(), note(pitch=72, start_beats=2)]},
                   {"type": "set_note_length", "clip_id": "@part", "length_beats": 0.25})


class Batch2PlanTests(unittest.TestCase):
    def test_dependent_creation_is_single_review_with_native_refs_and_exact_notes(self):
        baseline = fixture()
        plan = compile_plan(creation(), baseline)
        self.assertEqual(plan["aliases"], {"keys": "track", "part": "clip"})
        self.assertEqual([c["command"] for c in plan["commands"]], ["create_track", "create_midi_clip", "edit_notes", "edit_notes"])
        self.assertEqual(plan["commands"][1]["args"]["track_id"], "@keys")
        self.assertEqual(plan["commands"][0]["as"], "keys")
        notes = plan["commands"][2]["args"]["upsert"]
        self.assertEqual([n["pitch"] for n in notes], [67, 72])
        self.assertEqual(len({uuid.UUID(n["id"]) for n in notes}), 2)
        self.assertEqual([n["length_beats"] for n in plan["commands"][3]["args"]["upsert"]], [0.25, 0.25])
        self.assertEqual(plan, compile_plan(creation(), baseline))
        self.assertEqual(baseline, fixture())

    def test_exact_ref_readback_checks_created_track_clip_and_note_content(self):
        before = fixture()
        plan = compile_plan(creation(), before)
        bound = resolve_plan_refs(plan, {"keys": "native-track", "part": "native-clip"})
        after = deepcopy(before)
        after["revision"] += 1
        after["tracks"].append({"id": "native-track", "name": "New keys", "kind": "instrument", "gain_db": 0.0,
            "pan": 0.0, "muted": False, "solo": False, "clip_count": 1, "clips": [{"id": "native-clip", "kind": "midi",
            "start_seconds": 3.0, "duration_seconds": 3.0, "start_beats": 6.0, "length_beats": 6.0, "note_count": 2}]})
        after["clip_notes"]["native-clip"] = deepcopy(plan["commands"][3]["args"]["upsert"])
        self.assertEqual(verify_plan(bound, before, after), [])
        self.assertEqual(bound["commands"], plan["commands"])
        self.assertEqual(bound["note_clip_ids"], ["native-clip"])
        after["clip_notes"]["native-clip"][0]["pitch"] -= 1
        self.assertTrue(verify_plan(bound, before, after))
        self.assertTrue(verify_plan(plan, before, after))  # Never guess by name.

    def test_ref_missing_extra_colliding_and_invalid_rejected_without_plan_mutation(self):
        plan = compile_plan(creation(), fixture())
        original = deepcopy(plan)
        for refs in (None, {}, {"keys": "a"}, {"keys": "a", "part": "a"},
                     {"keys": "midi-1", "part": "b"}, {"keys": "@new", "part": "b"},
                     {"keys": "a", "part": "b", "extra": "c"}, {"keys": True, "part": "b"}):
            with self.subTest(refs=refs), self.assertRaises(PlanError):
                resolve_plan_refs(plan, refs)
        self.assertEqual(plan, original)

    def test_forward_wrong_type_deleted_and_duplicate_aliases_rejected(self):
        variants = [
            propose({"type": "create_midi_clip", "track_id": "@later", "start_beats": 0, "length_beats": 4, "as": "c"},
                    {"type": "create_track", "kind": "instrument", "name": "late", "as": "later"}),
            propose({"type": "create_track", "kind": "instrument", "name": "one", "as": "same"},
                    {"type": "create_track", "kind": "instrument", "name": "two", "as": "same"}),
            propose({"type": "create_track", "kind": "instrument", "name": "one", "as": "track"},
                    {"type": "add_notes", "clip_id": "@track", "notes": [note()]}),
            propose({"type": "duplicate_clip", "clip_id": "clip-1", "as": "copy"},
                    {"type": "delete_clip", "clip_id": "@copy"}, {"type": "move_clip", "clip_id": "@copy", "start_seconds": 0}),
        ]
        for value in variants:
            before = fixture()
            with self.subTest(value=value), self.assertRaises(PlanError):
                compile_plan(value, before)
            self.assertEqual(before, fixture())
        for alias in ("", "@foo", "2bad", "has space", "a"*41, True, "midi-1"):
            with self.subTest(alias=alias), self.assertRaises(PlanError):
                compile_plan(propose({"type": "create_track", "kind": "audio", "name": "n", "as": alias}), fixture())

    def test_midi_duplicate_preserves_native_controller_path_and_rekeys_notes(self):
        before = fixture()
        before["tracks"][0]["clips"][0]["controller_count"] = 3
        plan = compile_plan(propose({"type": "duplicate_clip", "clip_id": "clip-1", "as": "copy"},
                                    {"type": "transpose_notes", "clip_id": "@copy", "semitones": 12}), before)
        self.assertEqual([c["command"] for c in plan["commands"]], ["duplicate_clips", "write_notes", "edit_notes"])
        self.assertEqual(plan["commands"][0], {"command": "duplicate_clips", "args": {"clip_ids": ["clip-1"]}, "as": "copy"})
        original_ids = {n["id"] for n in before["clip_notes"]["clip-1"]}
        self.assertFalse(original_ids & {n["id"] for n in plan["commands"][1]["args"]["notes"]})
        copied = next(c for c in plan["checks"] if c.get("id")=="@copy" and c["kind"]=="clip")
        self.assertEqual(copied["value"]["controller_count"], 3)
        self.assertEqual(copied["value"]["start_beats"], 6)
        self.assertEqual(plan["note_clip_ids"], ["@copy", "clip-1"])
        self.assertEqual([n["pitch"] for n in plan["commands"][2]["args"]["upsert"]], [72, 76])

    def test_alias_must_survive_even_when_other_actions_change_the_project(self):
        variants = [
            propose({"type":"create_track","kind":"instrument","name":"New","as":"t"},
                    {"type":"create_midi_clip","track_id":"@t","start_beats":0,"length_beats":4,"as":"c"},
                    {"type":"delete_clip","clip_id":"@c"}),
            propose({"type":"duplicate_clip","clip_id":"clip-1","as":"copy"},
                    {"type":"delete_clip","clip_id":"@copy"}, {"type":"set_tempo","bpm":100}),
        ]
        for payload in variants:
            before = fixture()
            with self.subTest(payload=payload), self.assertRaisesRegex(PlanError, "同一批次被删除"):
                compile_plan(payload, before)
            self.assertEqual(before, fixture())

    def test_duplicate_verifies_source_notes_even_when_clone_is_correct(self):
        before = fixture()
        plan = compile_plan(propose({"type":"duplicate_clip","clip_id":"clip-1","as":"copy"}), before)
        bound = resolve_plan_refs(plan, {"copy":"native-copy"})
        after = deepcopy(before)
        after["revision"] += 1
        copied = deepcopy(after["tracks"][0]["clips"][0])
        copied.update(id="native-copy", start_seconds=3.0, start_beats=6.0)
        after["tracks"][0]["clips"].append(copied)
        after["tracks"][0]["clip_count"] = 2
        after["clip_notes"]["native-copy"] = deepcopy(plan["commands"][1]["args"]["notes"])
        self.assertEqual(verify_plan(bound, before, after), [])
        after["clip_notes"]["clip-1"][0]["pitch"] += 1
        self.assertTrue(verify_plan(bound, before, after))

    def test_source_preservation_does_not_double_charge_note_budget(self):
        before = fixture()
        before["clip_notes"]["clip-1"] = [{"id":f"n{i}",**note(start_beats=0)} for i in range(2000)]
        before["tracks"][0]["clips"][0]["note_count"] = 2000
        plan = compile_plan(propose({"type":"duplicate_clip","clip_id":"clip-1","as":"copy"}), before)
        self.assertEqual(plan["note_clip_ids"], ["@copy", "clip-1"])
        self.assertEqual(len(plan["commands"]), 2)

    def test_explicit_note_preview_contains_all_values_but_no_internal_ids(self):
        plan = compile_plan(creation(), fixture())
        self.assertEqual(len(plan["note_previews"]), 1)
        preview = plan["note_previews"][0]
        self.assertIn("New keys", preview["label"])
        self.assertIn("3 秒", preview["label"])
        self.assertNotIn("@part", preview["label"])
        self.assertEqual(preview["notes"], [note(), note(pitch=72, start_beats=2)])
        for value in preview["notes"]:
            self.assertEqual(set(value), {"pitch","start_beats","length_beats","velocity","channel"})
        copy_plan = compile_plan(propose({"type":"duplicate_clip","clip_id":"clip-1","as":"copy"}), fixture())
        self.assertEqual(copy_plan["note_previews"], [])
        bound = resolve_plan_refs(plan, {"keys":"native-track","part":"native-clip"})
        self.assertEqual(bound["note_previews"], plan["note_previews"])

    def test_note_preview_obeys_total_existing_operation_budget(self):
        payload = propose({"type":"create_midi_clip","track_id":"midi-1","start_beats":0,"length_beats":4,"as":"part"},
                          {"type":"add_notes","clip_id":"@part","notes":[note(start_beats=0) for _ in range(2000)]})
        plan = compile_plan(payload, fixture())
        self.assertEqual(sum(len(p["notes"]) for p in plan["note_previews"]), 2000)
        payload["actions"].append({"type":"add_notes","clip_id":"@part","notes":[note()]})
        with self.assertRaises(PlanError):
            compile_plan(payload, fixture())

    def test_duplicate_cannot_reuse_source_note_ids(self):
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "duplicate_clip", "clip_id": "clip-1", "as": "copy"},
                                 {"type": "delete_notes", "clip_id": "@copy", "note_ids": ["n1"]}), fixture())

    def test_hidden_controller_work_is_bounded_and_midi_trim_is_explicitly_limited(self):
        before = fixture()
        before["tracks"][0]["clips"][0]["controller_count"] = 1
        with self.assertRaisesRegex(PlanError, "控制器"):
            compile_plan(propose({"type":"trim_clip","clip_id":"clip-1","start_seconds":0,"end_seconds":1}), before)
        before["tracks"][0]["clips"][0]["controller_count"] = 2001
        with self.assertRaises(PlanError):
            compile_plan(propose({"type":"duplicate_clip","clip_id":"clip-1","as":"copy"}), before)

    def test_audio_duplicate_does_not_reconstruct_or_read_notes(self):
        plan = compile_plan(propose({"type": "duplicate_clip", "clip_id": "audio-clip", "as": "audio"}), fixture())
        self.assertEqual(len(plan["commands"]), 1)
        self.assertEqual(plan["note_clip_ids"], [])

    def test_trim_matches_native_clipping_and_add_uses_new_relative_coordinates(self):
        before = fixture()
        plan = compile_plan(propose({"type": "trim_clip", "clip_id": "clip-1", "start_seconds": 0.25, "end_seconds": 1},
                                    {"type": "add_notes", "clip_id": "clip-1", "notes": [note(start_beats=0.25, length_beats=0.25)]}), before)
        notes = next(c["value"] for c in plan["checks"] if c["kind"]=="notes")
        self.assertAlmostEqual(notes[0]["start_beats"], 0)
        self.assertAlmostEqual(notes[0]["length_beats"], 0.12)
        self.assertAlmostEqual(notes[1]["start_beats"], 0.87)
        self.assertEqual(notes[2]["start_beats"], 0.25)
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "trim_clip", "clip_id": "clip-1", "start_seconds": 0, "end_seconds": 4}), fixture())

    def test_audio_trim_preserves_asset_and_updates_source_and_fades(self):
        before = fixture()
        before["tracks"][1]["clips"][0].update(source_offset=4.0, asset_id="asset", fade_in_seconds=4, fade_out_seconds=3)
        plan = compile_plan(propose({"type": "trim_clip", "clip_id": "audio-clip", "start_seconds": 3, "end_seconds": 5}), before)
        value = next(c["value"] for c in plan["checks"] if c.get("id")=="audio-clip")
        self.assertEqual((value["source_offset"],value["duration_seconds"],value["fade_in_seconds"],value["fade_out_seconds"]), (5,2,2,0))
        self.assertEqual(value["asset_id"], "asset")

    def test_cross_track_move_uses_native_group_move_and_owner_readback(self):
        before = fixture()
        before["tracks"].append({**deepcopy(before["tracks"][0]), "id": "midi-2", "name": "Other", "clips": [], "clip_count": 0})
        plan = compile_plan(propose({"type": "move_clip", "clip_id": "clip-1", "start_seconds": 4, "target_track_id": "midi-2"}), before)
        self.assertEqual(plan["commands"][0], {"command": "move_clips", "args": {"clip_ids": ["clip-1"], "delta_seconds": 4.0, "target_track_id": "midi-2"}})
        self.assertEqual(next(c["track_id"] for c in plan["checks"] if c.get("id")=="clip-1"), "midi-2")
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "move_clip", "clip_id": "clip-1", "start_seconds": 4, "target_track_id": "audio-1"}), fixture())

    def test_delete_readback_requires_absence_and_does_not_read_deleted_notes(self):
        before = fixture()
        plan = compile_plan(propose({"type": "set_note_velocity", "clip_id": "clip-1", "velocity": 80},
                                    {"type": "delete_clip", "clip_id": "clip-1"}), before)
        self.assertEqual(plan["note_clip_ids"], [])
        after = deepcopy(before)
        after["tracks"][0]["clips"] = []
        after["tracks"][0]["clip_count"] = 0
        self.assertEqual(verify_plan(plan,before,after), [])
        self.assertTrue(verify_plan(plan,before,before))

    def test_note_delete_length_move_preserve_other_notes_and_refuse_overflow(self):
        plan = compile_plan(propose({"type": "delete_notes", "clip_id": "clip-1", "note_ids": ["n2"]},
                                    {"type": "set_note_length", "clip_id": "clip-1", "length_beats": 1},
                                    {"type": "move_notes", "clip_id": "clip-1", "delta_beats": 1}), fixture())
        self.assertEqual(plan["commands"][0]["args"]["delete_ids"], ["n2"])
        self.assertEqual(plan["commands"][2]["args"]["upsert"][0]["id"], "n1")
        self.assertAlmostEqual(plan["commands"][2]["args"]["upsert"][0]["start_beats"], 1.12)
        for action in ({"type": "set_note_length", "clip_id": "clip-1", "length_beats": 0},
                       {"type": "set_note_length", "clip_id": "clip-1", "length_beats": 6},
                       {"type": "move_notes", "clip_id": "clip-1", "delta_beats": -1}):
            with self.subTest(action=action), self.assertRaises(PlanError):
                compile_plan(propose(action), fixture())

    def test_new_notes_validate_complete_fields_channel_bounds_and_id_ownership(self):
        for raw in (note(id="invented"), note(pitch=128), note(length_beats=0), note(start_beats=5.9),
                    note(channel=2), note(velocity=True), {"pitch":60}):
            with self.subTest(raw=raw), self.assertRaises(PlanError):
                compile_plan(propose({"type": "add_notes", "clip_id": "clip-1", "notes": [raw]}), fixture())
        value = fixture()
        value["clip_notes"]["clip-1"][0]["id"] = "00000000-0000-0000-0000-000000000001"
        with patch("music_agent.plans.uuid.uuid5", return_value=uuid.UUID(value["clip_notes"]["clip-1"][0]["id"])), self.assertRaises(PlanError):
            compile_plan(propose({"type": "add_notes", "clip_id": "clip-1", "notes": [note()]}), value)

    def test_preload_ignores_future_aliases_but_covers_source_trim_and_notes(self):
        actions = propose({"type": "duplicate_clip", "clip_id": "clip-1", "as": "copy"},
                          {"type": "set_note_length", "clip_id": "@copy", "length_beats": 1},
                          {"type": "trim_clip", "clip_id": "audio-clip", "start_seconds": 2, "end_seconds": 3})
        self.assertEqual(required_note_clip_ids(actions), ["audio-clip", "clip-1"])


class Batch2ScopeTests(unittest.TestCase):
    def test_note_selection_rejects_whole_clip_and_add_operations(self):
        before = selected_context()
        for action in ({"type": "delete_clip", "clip_id": "c"}, {"type": "duplicate_clip", "clip_id": "c", "as": "copy"},
                       {"type": "trim_clip", "clip_id": "c", "start_seconds": 4, "end_seconds": 5},
                       {"type": "add_notes", "clip_id": "c", "notes": [note()]}):
            with self.subTest(action=action), self.assertRaises(ScopeError):
                constrain_proposal(propose(action), before, freeze_scope(before))

    def test_note_subset_can_delete_length_and_move_only_authorized_ids(self):
        before = selected_context()
        for action in ({"type": "delete_notes", "clip_id": "c"}, {"type": "set_note_length", "clip_id": "c", "length_beats": 0.25},
                       {"type": "move_notes", "clip_id": "c", "delta_beats": 0.25}):
            result = constrain_proposal(propose(action),before,freeze_scope(before))
            self.assertEqual(result["actions"][0]["note_ids"], ["n2"])
            with self.assertRaises(ScopeError):
                constrain_proposal(propose({**action,"note_ids":["n1"]}),before,freeze_scope(before))

    def test_clip_scope_add_and_derived_clone_stay_authorized(self):
        before = selected_context()
        payload = propose({"type": "duplicate_clip", "clip_id": "c", "as": "copy"},
                          {"type": "add_notes", "clip_id": "@copy", "notes": [note()]},
                          {"type": "set_note_length", "clip_id": "@copy", "length_beats": 0.25})
        result = constrain_proposal(payload,before,freeze_scope(before,"clip"))
        self.assertEqual(len(result["actions"][2]["note_ids"]),4)
        plan = compile_plan(result,before)
        self.assertEqual(len(plan["commands"]),4)
        with self.assertRaises(ScopeError):
            constrain_proposal(propose(*payload["actions"],{"type":"delete_clip","clip_id":"outside"}),before,freeze_scope(before,"clip"))

    def test_track_creation_alias_can_add_notes_without_widening_other_clip(self):
        before = selected_context()
        before["selection_context"].update(focus="track",clip_ids=[],note_ids=[],note_count=0)
        payload = propose({"type":"create_midi_clip","track_id":"t","start_beats":20,"length_beats":4,"as":"new"},
                          {"type":"add_notes","clip_id":"@new","notes":[note()]})
        result = constrain_proposal(payload,before,freeze_scope(before))
        self.assertEqual(compile_plan(result,before)["note_clip_ids"],["@new"])
        with self.assertRaises(ScopeError):
            constrain_proposal(propose(*payload["actions"],{"type":"delete_clip","clip_id":"outside"}),before,freeze_scope(before))

    def test_cross_track_requires_selected_destination(self):
        before = selected_context()
        before["tracks"].append({**deepcopy(before["tracks"][0]), "id":"other","clips":[]})
        before["selection_context"].update(focus="arrangement",note_ids=[],note_count=0)
        action = {"type":"move_clip","clip_id":"c","start_seconds":3,"target_track_id":"other"}
        with self.assertRaises(ScopeError):
            constrain_proposal(propose(action),before,freeze_scope(before))
        before["selection_context"]["track_ids"].append("other")
        self.assertEqual(constrain_proposal(propose(action),before,freeze_scope(before))["actions"],[action])

    def test_time_add_requires_full_new_note_interval(self):
        before = selected_context()
        before["selection_context"].update(focus="arrangement",note_ids=[],note_count=0,
            time_range={"active":True,"start_seconds":4,"end_seconds":5})
        valid = {"type":"add_notes","clip_id":"c","notes":[note(start_beats=2,length_beats=1)]}
        constrain_proposal(propose(valid),before,freeze_scope(before))
        for raw in (note(start_beats=1.5),note(start_beats=3.75,length_beats=0.5),note(start_beats=4)):
            with self.subTest(raw=raw),self.assertRaises(ScopeError):
                constrain_proposal(propose({**valid,"notes":[raw]}),before,freeze_scope(before))

    def test_time_scope_uses_candidate_after_prior_clip_move(self):
        before = selected_context()
        before["selection_context"].update(focus="arrangement",note_ids=[],note_count=0,
            time_range={"active":True,"start_seconds":3,"end_seconds":7})
        payload = propose({"type":"move_clip","clip_id":"c","start_seconds":4},
                          {"type":"add_notes","clip_id":"c","notes":[note(start_beats=5.5,length_beats=0.25)]})
        constrain_proposal(payload,before,freeze_scope(before))
        payload["actions"][1]["notes"][0]["length_beats"] = 1
        with self.assertRaises(ScopeError):
            constrain_proposal(payload,before,freeze_scope(before))

    def test_time_partial_clip_cannot_delete_trim_or_duplicate(self):
        before = selected_context()
        before["selection_context"].update(focus="arrangement",note_ids=[],note_count=0,
            time_range={"active":True,"start_seconds":4,"end_seconds":5})
        for action in ({"type":"delete_clip","clip_id":"c"},{"type":"duplicate_clip","clip_id":"c","as":"copy"},
                       {"type":"trim_clip","clip_id":"c","start_seconds":4,"end_seconds":5}):
            with self.subTest(action=action),self.assertRaises(ScopeError):
                constrain_proposal(propose(action),before,freeze_scope(before))


if __name__ == "__main__":
    unittest.main()
