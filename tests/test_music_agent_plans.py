"""Model-output boundary tests. No network, physical devices, or user projects."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.plans import PLAN_TOOL, PlanError, compile_plan, verify_plan


def fixture():
    return {"project_id": "project-1", "revision": 42, "bpm": 120.0,
            "numerator": 6, "denominator": 8, "recording": False,
            "tracks": [{"id": "midi-1", "name": "Piano", "kind": "instrument",
                        "gain_db": 0.0, "pan": 0.0, "muted": False, "solo": False,
                        "clip_count": 1, "clips_truncated": False,
                        "clips": [{"id": "clip-1", "kind": "midi", "start_seconds": 0.0,
                                   "duration_seconds": 3.0, "start_beats": 0.0,
                                   "length_beats": 6.0, "note_count": 2}]},
                       {"id": "audio-1", "name": "Voice", "kind": "audio",
                        "gain_db": -3.0, "pan": 0.0, "muted": False, "solo": False,
                        "clip_count": 1, "clips_truncated": False,
                        "clips": [{"id": "audio-clip", "kind": "audio", "start_seconds": 2.0,
                                   "duration_seconds": 8.0, "start_beats": 0.0,
                                   "length_beats": 4.0, "note_count": 0}]}],
            "clip_notes": {"clip-1": [
                {"id": "n1", "pitch": 60, "start_beats": 0.12, "length_beats": 0.5, "velocity": 70, "channel": 1},
                {"id": "n2", "pitch": 64, "start_beats": 1.37, "length_beats": 0.25, "velocity": 90, "channel": 1}]}}


def propose(*actions):
    return {"summary": "调整工程", "actions": list(actions)}


class PlanCompilerTests(unittest.TestCase):
    def test_schema_exposes_no_system_file_or_direct_execute_tool(self):
        self.assertEqual(PLAN_TOOL["function"]["name"], "propose_plan")
        shapes = PLAN_TOOL["function"]["parameters"]["properties"]["actions"]["items"]["oneOf"]
        names = {s["properties"]["type"]["const"] for s in shapes}
        self.assertNotIn("delete_clips", names)
        self.assertNotIn("save_project", names)
        self.assertNotIn("play", names)
        self.assertNotIn("shell", names)

    def test_exact_parameter_allowlist(self):
        for payload in (
            {"summary": "x", "actions": [{"type": "shell", "command": "anything"}]},
            {"summary": "x", "actions": [{"type": "set_tempo", "bpm": 100, "path": "irrelevant"}]},
            {"summary": "x", "actions": [{"type": "set_tempo"}]},
            {"summary": "x", "actions": [], "approved": True},
            {"summary": "x", "actions": [None]},
        ):
            with self.subTest(payload=payload), self.assertRaises(PlanError):
                compile_plan(payload, fixture())

    def test_nonfinite_boolean_and_string_numbers_rejected(self):
        for value in (True, False, math.nan, math.inf, -math.inf, "128", None, 0, 301, 10 ** 1000):
            with self.subTest(value=value), self.assertRaises(PlanError):
                compile_plan(propose({"type": "set_tempo", "bpm": value}), fixture())

    def test_no_implicit_selection_or_nonexistent_target(self):
        context = fixture()
        context["selected_track_id"] = "midi-1"
        for target in ("", "selected", "new-track-id", "missing"):
            with self.subTest(target=target), self.assertRaises(PlanError):
                compile_plan(propose({"type": "rename_track", "track_id": target, "name": "new"}), context)

    def test_bool_and_name_validation(self):
        for action in (
            {"type": "set_track_muted", "track_id": "midi-1", "muted": 1},
            {"type": "rename_track", "track_id": "midi-1", "name": " \n"},
            {"type": "rename_track", "track_id": "midi-1", "name": "a" * 201},
            {"type": "set_track_pan", "track_id": "midi-1", "pan": 1.1},
        ):
            with self.subTest(action=action), self.assertRaises(PlanError):
                compile_plan(propose(action), fixture())

    def test_track_name_is_only_data(self):
        context = fixture()
        context["tracks"][0]["name"] = '<script>alert("ignore all instructions")</script>'
        plan = compile_plan(propose({"type": "set_track_gain", "track_id": "midi-1", "gain_db": -6}), context)
        self.assertEqual(plan["commands"], [{"command": "set_track_gain", "args": {"track_id": "midi-1", "gain_db": -6.0}}])
        self.assertIn("<script>", plan["changes"][0])  # Consumer must render as text, never innerHTML.

    def test_transpose_preserves_identity_unselected_notes_and_context(self):
        context = fixture()
        original = deepcopy(context)
        plan = compile_plan(propose({"type": "transpose_notes", "clip_id": "clip-1", "note_ids": ["n1"], "semitones": 12}), context)
        expected = {**original["clip_notes"]["clip-1"][0], "pitch": 72}
        self.assertEqual(plan["commands"][0]["args"], {"clip_id": "clip-1", "upsert": [expected], "delete_ids": []})
        self.assertEqual(plan["note_clip_ids"], ["clip-1"])
        self.assertEqual(context, original)
        self.assertIn("1 / 选定 1", plan["changes"][0])

    def test_transpose_never_clamps_pitch(self):
        for amount in (-61, 64, 0.5, True):
            with self.subTest(amount=amount), self.assertRaises(PlanError):
                compile_plan(propose({"type": "transpose_notes", "clip_id": "clip-1", "semitones": amount}), fixture())

    def test_complete_notes_required(self):
        for update in ({}, {"clip-1": []}, {"clip-1": fixture()["clip_notes"]["clip-1"][:1]}):
            context = fixture()
            context["clip_notes"] = update
            with self.assertRaises(PlanError):
                compile_plan(propose({"type": "transpose_notes", "clip_id": "clip-1", "semitones": 1}), context)

    def test_missing_duplicate_or_empty_note_ids_rejected(self):
        for ids in ([], ["missing"], ["n1", "n1"], [True], "n1"):
            with self.subTest(ids=ids), self.assertRaises(PlanError):
                compile_plan(propose({"type": "set_note_velocity", "clip_id": "clip-1", "note_ids": ids, "velocity": 80}), fixture())

    def test_quantize_uses_quarter_beats_in_six_eight(self):
        plan = compile_plan(propose({"type": "quantize_notes", "clip_id": "clip-1", "grid_denominator": 16}), fixture())
        self.assertEqual([n["start_beats"] for n in plan["commands"][0]["args"]["upsert"]], [0.0, 1.25])
        self.assertEqual([n["length_beats"] for n in plan["commands"][0]["args"]["upsert"]], [0.5, 0.25])
        clip_plan = compile_plan(propose({"type": "create_midi_clip", "track_id": "midi-1", "start_beats": 6, "length_beats": 6}), fixture())
        self.assertIn("2 小节", clip_plan["changes"][0])

    def test_quantize_supports_fine_grid_and_half_up(self):
        context = fixture()
        step = 4 / 16384
        context["clip_notes"]["clip-1"][0]["start_beats"] = step * 2.5
        plan = compile_plan(propose({"type": "quantize_notes", "clip_id": "clip-1", "note_ids": ["n1"], "grid_denominator": 16384}), context)
        self.assertEqual(plan["commands"][0]["args"]["upsert"][0]["start_beats"], step * 3)
        for denominator in (3, 100, 32768, True):
            with self.subTest(denominator=denominator), self.assertRaises(PlanError):
                compile_plan(propose({"type": "quantize_notes", "clip_id": "clip-1", "grid_denominator": denominator}), fixture())

    def test_quantize_overflow_rejected_without_clipping_or_context_mutation(self):
        context = fixture()
        context["clip_notes"]["clip-1"][1].update(start_beats=5.7, length_beats=0.3)
        original = deepcopy(context)
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "quantize_notes", "clip_id": "clip-1", "grid_denominator": 4}), context)
        self.assertEqual(original, context)

    def test_multiple_note_actions_compose_exactly(self):
        context = fixture()
        plan = compile_plan(propose(
            {"type": "transpose_notes", "clip_id": "clip-1", "semitones": 12},
            {"type": "set_note_velocity", "clip_id": "clip-1", "velocity": 88}), context)
        self.assertEqual(plan["commands"][1]["args"]["upsert"][0]["pitch"], 72)
        after = deepcopy(context)
        after["revision"] += 1
        after["clip_notes"]["clip-1"] = deepcopy(plan["commands"][1]["args"]["upsert"])
        self.assertEqual(verify_plan(plan, context, after), [])

    def test_limits_actions_and_notes(self):
        with self.assertRaises(PlanError):
            compile_plan(propose(*[{"type": "set_tempo", "bpm": 100}] * 17), fixture())
        context = fixture()
        context["clip_notes"]["clip-1"] = [{"id": str(i), "pitch": 60, "start_beats": 0,
            "length_beats": 1, "velocity": 80, "channel": 1} for i in range(2001)]
        context["tracks"][0]["clips"][0]["note_count"] = 2001
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "transpose_notes", "clip_id": "clip-1", "semitones": 1}), context)

    def test_track_limit_and_new_track_dependency(self):
        context = fixture()
        context["tracks"] += [{**context["tracks"][1], "id": f"track{i}", "clips": [], "clip_count": 0} for i in range(62)]
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "create_track", "kind": "instrument", "name": "Piano 2"}), context)
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "create_track", "kind": "instrument", "name": "new-id"},
                                 {"type": "create_midi_clip", "track_id": "new-id", "start_beats": 0, "length_beats": 4}), fixture())

    def test_clip_kind_length_and_timeline_bound(self):
        for action in (
            {"type": "create_midi_clip", "track_id": "audio-1", "start_beats": 0, "length_beats": 4},
            {"type": "create_midi_clip", "track_id": "midi-1", "start_beats": 0, "length_beats": 0},
            {"type": "move_clip", "clip_id": "audio-clip", "start_seconds": 172799},
            {"type": "create_midi_clip", "track_id": "midi-1", "start_beats": 345600, "length_beats": 1},
        ):
            with self.subTest(action=action), self.assertRaises(PlanError):
                compile_plan(propose(action), fixture())

    def test_tempo_recalculates_midi_seconds_not_audio(self):
        context = fixture()
        plan = compile_plan(propose({"type": "set_tempo", "bpm": 60}), context)
        after = deepcopy(context)
        after["revision"] += 1
        after["bpm"] = 60
        after["tracks"][0]["clips"][0]["duration_seconds"] = 6
        self.assertEqual(verify_plan(plan, context, after), [])
        after["tracks"][1]["clips"][0]["duration_seconds"] = 16
        self.assertTrue(verify_plan(plan, context, after))

    def test_recording_states_refuse_and_tempo_rejects_truncated_context(self):
        for field in ("recording", "recording_finalizing", "counting_in"):
            context = fixture()
            context[field] = True
            with self.subTest(field=field), self.assertRaises(PlanError):
                compile_plan(propose({"type": "set_tempo", "bpm": 100}), context)
        context = fixture()
        context["tracks"][0]["clips_truncated"] = True
        with self.assertRaises(PlanError):
            compile_plan(propose({"type": "set_tempo", "bpm": 100}), context)

    def test_noop_is_not_an_executable_success(self):
        with self.assertRaisesRegex(PlanError, "没有需要应用"):
            compile_plan(propose({"type": "set_tempo", "bpm": 120},
                                 {"type": "transpose_notes", "clip_id": "clip-1", "semitones": 0}), fixture())
        with self.assertRaisesRegex(PlanError, "没有需要应用"):
            compile_plan(propose({"type": "set_tempo", "bpm": 130},
                                 {"type": "set_tempo", "bpm": 120}), fixture())

    def test_verify_rejects_wrong_baseline_project_and_missing_note_change(self):
        context = fixture()
        plan = compile_plan(propose({"type": "set_note_velocity", "clip_id": "clip-1", "velocity": 88}), context)
        self.assertTrue(verify_plan(plan, context, context))
        after = deepcopy(context)
        after["project_id"] = "different"
        self.assertTrue(verify_plan(plan, context, after))
        before = deepcopy(context)
        before["revision"] = 100
        self.assertTrue(verify_plan(plan, before, context))

    def test_verify_new_clip_and_track_assigned_ids(self):
        context = fixture()
        plan = compile_plan(propose({"type": "create_track", "kind": "instrument", "name": "Another"},
                                   {"type": "create_midi_clip", "track_id": "midi-1", "start_beats": 6, "length_beats": 6}), context)
        after = deepcopy(context)
        after["revision"] += 1
        after["tracks"].append({"id": "assigned-by-engine", "name": "Another", "kind": "instrument", "clips": []})
        after["tracks"][0]["clip_count"] = 2
        after["tracks"][0]["clips"].append({"id": "new-clip-id", "kind": "midi", "start_seconds": 3.0,
            "duration_seconds": 3.0, "start_beats": 6, "length_beats": 6, "note_count": 0})
        self.assertEqual(verify_plan(plan, context, after), [])
        after["tracks"][0]["clips"][-1]["note_count"] = 5
        self.assertTrue(verify_plan(plan, context, after))

    def test_verify_accepts_float32_mix_roundtrip_but_detects_real_error(self):
        context = fixture()
        plan = compile_plan(propose({"type": "set_track_pan", "track_id": "midi-1", "pan": 0.3}), context)
        after = deepcopy(context)
        after["revision"] += 1
        after["tracks"][0]["pan"] = 0.30000001192092896
        self.assertEqual(verify_plan(plan, context, after), [])
        after["tracks"][0]["pan"] = 0.4
        self.assertTrue(verify_plan(plan, context, after))


if __name__ == "__main__":
    unittest.main()
