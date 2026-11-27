"""Freeze the user's explicit edit scope and constrain untrusted model actions.

This is authorization for musical scope, not music state. No model inference is
used to enlarge the scope. Time ranges select note ONSETS, using [start, end).
"""
from __future__ import annotations
from copy import deepcopy
import math


class ScopeError(ValueError):
    pass


NOTE_ACTIONS = {"transpose_notes", "quantize_notes", "set_note_velocity", "set_note_length", "move_notes", "delete_notes", "add_notes"}
TRACK_ACTIONS = {"rename_track", "set_track_gain", "set_track_pan", "set_track_muted", "set_track_solo", "set_track_colour", "add_native_effect", "set_native_effect", "set_native_effect_parameter"}
MODES = {"selection", "clip", "project"}


def _integer(value):
    return type(value) is int and value >= 0


def _finite(value):
    return type(value) in (int, float) and -1e9 <= value <= 1e9 and math.isfinite(value)


def _ids(values, maximum):
    if not isinstance(values, list) or len(values) > maximum or any(not isinstance(v, str) or not v or len(v) > 200 for v in values) or len(set(values)) != len(values):
        raise ScopeError("The selection contains invalid or duplicate IDs. Select again.")
    return sorted(values)


def freeze_scope(context: dict, scope: str = "selection") -> dict:
    if scope not in MODES:
        raise ScopeError("Scope must be selection, clip or project.")
    if not isinstance(context, dict) or not isinstance(context.get("project_id"), str) or not _integer(context.get("revision")):
        raise ScopeError("Project identity and revision are missing.")
    frozen = {"mode": scope, "project_id": context["project_id"], "project_revision": context["revision"]}
    if scope == "project":
        return frozen
    value = context.get("selection_context")
    if not isinstance(value, dict) or value.get("available") is not True:
        raise ScopeError("The selection is unavailable or exceeds 2000 notes. Select fewer notes or explicitly choose Whole project scope.")
    if value.get("project_id") != context["project_id"] or value.get("project_revision") != context["revision"] or not _integer(value.get("selection_revision")):
        raise ScopeError("The selection snapshot is stale. Read it again.")
    normalized = deepcopy(value)
    for key, maximum in (("track_ids", 64), ("clip_ids", 4096), ("note_ids", 2000)):
        normalized[key] = _ids(value.get(key, []), maximum)
    if value.get("notes_truncated") or value.get("note_count", len(normalized["note_ids"])) != len(normalized["note_ids"]):
        raise ScopeError("The selected notes were not fully retrieved. A subset cannot represent the complete selection.")
    for key in ("active_track_id", "active_clip_id", "note_clip_id"):
        if not isinstance(value.get(key, ""), str):
            raise ScopeError("Invalid selected object identity.")
        normalized[key] = value.get(key, "")
    if value.get("focus") not in {"arrangement", "piano_roll", "track", "none"}:
        raise ScopeError("Invalid music editing focus.")
    time_range = value.get("time_range", {"active": False, "start_seconds": 0, "end_seconds": 0})
    if not isinstance(time_range, dict) or type(time_range.get("active")) is not bool:
        raise ScopeError("Invalid time selection.")
    if time_range["active"]:
        a, b = time_range.get("start_seconds"), time_range.get("end_seconds")
        if not _finite(a) or not _finite(b) or not 0 <= a < b <= 172800:
            raise ScopeError("The time selection must be a valid positive interval.")
    normalized["time_range"] = deepcopy(time_range)
    frozen.update(selection_revision=value["selection_revision"], selection=normalized)
    if scope == "clip" and not normalized["active_clip_id"]:
        raise ScopeError("Select a clip in the DAW before using Entire clip scope.")
    return frozen


def assert_scope_unchanged(frozen: dict, context: dict) -> None:
    if context.get("project_id") != frozen.get("project_id") or context.get("revision") != frozen.get("project_revision"):
        raise ScopeError("The project changed. Create a new plan.")
    if frozen["mode"] != "project":
        current = freeze_scope(context, frozen["mode"])
        if current != frozen:
            raise ScopeError("The music selection changed. The old plan will not target the new selection; create a new plan.")


def constrain_proposal(payload: dict, context: dict, frozen: dict) -> dict:
    """Scope each action against the same sequential candidate as compilation.

    Earlier authorized creations/clones may be referenced; they never authorize
    unrelated original objects. No DAW state or caller payload is changed.
    """
    from .plans import PlanError, _compile_plan
    assert_scope_unchanged(frozen, context)
    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ScopeError("The edit plan has no action list.")
    if frozen["mode"] == "project":
        return deepcopy(payload)
    selection = frozen["selection"]
    note_focus = frozen["mode"] == "selection" and selection["focus"] == "piano_roll" and bool(selection["note_ids"])
    selected_clips = ({selection["active_clip_id"]} if frozen["mode"] == "clip" else
                      {selection["note_clip_id"]} if note_focus else set(selection["clip_ids"]))
    selected_tracks = set(selection["track_ids"])
    if not selected_tracks and selection["focus"] == "track" and selection["active_track_id"]:
        selected_tracks.add(selection["active_track_id"])
    time_range = selection["time_range"]
    timed = frozen["mode"] == "selection" and not note_focus and time_range["active"]
    track_only = frozen["mode"] == "selection" and not note_focus and not selected_clips and not timed
    derived_clips = set()

    def contained(start, end):
        return not timed or (time_range["start_seconds"] <= start and end <= time_range["end_seconds"])

    def authorize(action, state):
        tracks = {t["id"]: t for t in state.get("tracks", [])}
        clips = {c["id"]: (t, c) for t in tracks.values() for c in t.get("clips", [])}
        kind = action["type"]
        if kind in {"add_native_effect", "set_native_effect", "set_native_effect_parameter"} and action.get("track_id") == "master":
            raise ScopeError("Master effects affect the whole project. Choose Whole project scope.")
        if kind in {"set_native_pad", "set_native_sampler"}:
            raise ScopeError("Sampler and Drum Rack parameters require a separate plan in Whole project scope.")
        bpm = state.get("bpm")
        if not _finite(bpm) or not 20 <= bpm <= 300:
            raise ScopeError("The current tempo is invalid, so the selection range cannot be computed.")

        def clip_allowed(cid):
            if cid not in clips:
                raise ScopeError("The target clip was not read, was deleted, or its alias was not declared. Its scope cannot be guessed.")
            owner, clip = clips[cid]
            if cid not in selected_clips | derived_clips and not (timed and not selected_clips and owner["id"] in selected_tracks):
                raise ScopeError("The plan target is outside the confirmed clip selection.")
            if timed and not (clip["start_seconds"] < time_range["end_seconds"] and clip["start_seconds"] + clip["duration_seconds"] > time_range["start_seconds"]):
                raise ScopeError("The clip does not intersect the time selection.")
            return owner, clip

        if kind in {"set_tempo", "create_track"}:
            raise ScopeError("This operation affects the whole project. Choose Whole project scope before creating a plan.")
        if kind in TRACK_ACTIONS:
            tid = action.get("track_id")
            if not track_only or tid not in selected_tracks or tid not in tracks:
                raise ScopeError("Select the whole track for a track-wide edit. A note, clip or time selection does not authorize it.")
        elif kind == "create_midi_clip":
            tid = action.get("track_id")
            start, length = action.get("start_beats"), action.get("length_beats")
            if note_focus or tid not in selected_tracks or tid not in tracks or not (track_only or timed):
                raise ScopeError("Select a track or a time range on that track before creating a clip.")
            if not _finite(start) or not _finite(length) or length <= 0 or not contained(start*60/bpm, (start+length)*60/bpm):
                raise ScopeError("The new clip exceeds the confirmed time selection.")
            derived_clips.add("@"+action["as"])
        elif kind in NOTE_ACTIONS:
            cid = action.get("clip_id")
            _, clip = clip_allowed(cid)
            notes = state.get("clip_notes", {}).get(cid)
            if clip.get("kind") != "midi" or not isinstance(notes, list) or len(notes) != clip.get("note_count") or len(notes)>2000:
                raise ScopeError("Read the complete target MIDI clip first, up to 2000 notes.")
            if kind == "add_notes":
                if note_focus:
                    raise ScopeError("Selected notes cannot authorize unrelated new notes. Explicitly use clip or time-range scope.")
                new_notes = action.get("notes")
                if not isinstance(new_notes, list):
                    raise ScopeError("Invalid added note list.")
                for note in new_notes:
                    if not isinstance(note, dict) or not _finite(note.get("start_beats")) or not _finite(note.get("length_beats")):
                        raise ScopeError("Invalid added note timing.")
                    at = clip["start_seconds"] + note["start_beats"]*60/bpm
                    end = at + note["length_beats"]*60/bpm
                    if not contained(at, end) or (timed and at >= time_range["end_seconds"]):
                        raise ScopeError("Added notes exceed the confirmed time range.")
                return
            allowed = set(selection["note_ids"]) if note_focus else {n["id"] for n in notes}
            if timed:
                allowed &= {n["id"] for n in notes if time_range["start_seconds"] <= clip["start_seconds"]+n["start_beats"]*60/bpm < time_range["end_seconds"]}
            requested = _ids(action["note_ids"], 2000) if "note_ids" in action else sorted(allowed)
            if not requested or not set(requested) <= allowed:
                raise ScopeError("The note edit exceeds the frozen selection or no note starts are inside it.")
            action["note_ids"] = requested
            if timed and kind in {"quantize_notes", "move_notes", "set_note_length"}:
                for note in notes:
                    if note["id"] not in requested:
                        continue
                    start, length = note["start_beats"], note["length_beats"]
                    if kind == "quantize_notes":
                        denominator = action.get("grid_denominator")
                        if type(denominator) is not int or not 1<=denominator<=16384 or denominator & (denominator-1):
                            raise ScopeError("Invalid quantization grid.")
                        step = 4/denominator
                        start = math.floor(start/step+0.5)*step
                    elif kind == "move_notes":
                        if not _finite(action.get("delta_beats")):
                            raise ScopeError("Invalid note shift amount.")
                        start += action["delta_beats"]
                    else:
                        if not _finite(action.get("length_beats")):
                            raise ScopeError("Invalid note length.")
                        length = action["length_beats"]
                    at = clip["start_seconds"]+start*60/bpm
                    if not time_range["start_seconds"] <= at < time_range["end_seconds"] or (kind=="set_note_length" and not contained(at, at+length*60/bpm)):
                        raise ScopeError("Note edits would exceed the confirmed time selection.")
        elif kind in {"move_clip", "trim_clip", "delete_clip", "duplicate_clip"}:
            if note_focus:
                raise ScopeError("A note selection cannot authorize editing the entire clip.")
            owner, clip = clip_allowed(action.get("clip_id"))
            start, end = clip["start_seconds"], clip["start_seconds"]+clip["duration_seconds"]
            if not contained(start, end):
                raise ScopeError("Editing the complete clip would affect content outside the confirmed time range.")
            if kind == "move_clip":
                at = action.get("start_seconds")
                target = action.get("target_track_id", owner["id"])
                if target != owner["id"] and (target not in selected_tracks or target not in tracks):
                    raise ScopeError("Moving between tracks requires selecting the destination track or Whole project scope.")
                if not _finite(at) or not contained(at, at+clip["duration_seconds"]):
                    raise ScopeError("Moving the whole clip would exceed the confirmed time selection.")
            elif kind == "duplicate_clip":
                if not contained(end, end+clip["duration_seconds"]):
                    raise ScopeError("Copying the clip would exceed the confirmed time selection.")
                derived_clips.add("@"+action["as"])
            elif kind == "trim_clip":
                a,b=action.get("start_seconds"),action.get("end_seconds")
                if not _finite(a) or not _finite(b) or not contained(a,b):
                    raise ScopeError("The trim range exceeds the confirmed time selection.")
        else:
            raise ScopeError("This operation is outside the selected scope.")
    try:
        plan = _compile_plan(payload, context, authorizer=authorize, allow_noop=True)
    except PlanError as exc:
        raise ScopeError(str(exc)) from exc
    return {"summary": plan["summary"], "actions": plan["actions"]}
