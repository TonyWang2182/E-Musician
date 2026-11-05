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
TRACK_ACTIONS = {"rename_track", "set_track_gain", "set_track_pan", "set_track_muted", "set_track_solo", "add_native_effect", "set_native_effect", "set_native_effect_parameter"}
MODES = {"selection", "clip", "project"}


def _integer(value):
    return type(value) is int and value >= 0


def _finite(value):
    return type(value) in (int, float) and -1e9 <= value <= 1e9 and math.isfinite(value)


def _ids(values, maximum):
    if not isinstance(values, list) or len(values) > maximum or any(not isinstance(v, str) or not v or len(v) > 200 for v in values) or len(set(values)) != len(values):
        raise ScopeError("选择范围包含无效或重复 ID，请重新选择。")
    return sorted(values)


def freeze_scope(context: dict, scope: str = "selection") -> dict:
    if scope not in MODES:
        raise ScopeError("范围必须是 selection、clip 或 project。")
    if not isinstance(context, dict) or not isinstance(context.get("project_id"), str) or not _integer(context.get("revision")):
        raise ScopeError("缺少工程身份和版本。")
    frozen = {"mode": scope, "project_id": context["project_id"], "project_revision": context["revision"]}
    if scope == "project":
        return frozen
    value = context.get("selection_context")
    if not isinstance(value, dict) or value.get("available") is not True:
        raise ScopeError("当前选择不可用或超出 2000 音符范围；请缩小选择，或明确切换到工程范围。")
    if value.get("project_id") != context["project_id"] or value.get("project_revision") != context["revision"] or not _integer(value.get("selection_revision")):
        raise ScopeError("选择快照已过期，请重新读取。")
    normalized = deepcopy(value)
    for key, maximum in (("track_ids", 64), ("clip_ids", 4096), ("note_ids", 2000)):
        normalized[key] = _ids(value.get(key, []), maximum)
    if value.get("notes_truncated") or value.get("note_count", len(normalized["note_ids"])) != len(normalized["note_ids"]):
        raise ScopeError("选择音符没有完整取得，不能缩减后冒充全部选择。")
    for key in ("active_track_id", "active_clip_id", "note_clip_id"):
        if not isinstance(value.get(key, ""), str):
            raise ScopeError("选择对象身份无效。")
        normalized[key] = value.get(key, "")
    if value.get("focus") not in {"arrangement", "piano_roll", "track", "none"}:
        raise ScopeError("音乐编辑焦点无效。")
    time_range = value.get("time_range", {"active": False, "start_seconds": 0, "end_seconds": 0})
    if not isinstance(time_range, dict) or type(time_range.get("active")) is not bool:
        raise ScopeError("时间选区无效。")
    if time_range["active"]:
        a, b = time_range.get("start_seconds"), time_range.get("end_seconds")
        if not _finite(a) or not _finite(b) or not 0 <= a < b <= 172800:
            raise ScopeError("时间选区必须是有效的正区间。")
    normalized["time_range"] = deepcopy(time_range)
    frozen.update(selection_revision=value["selection_revision"], selection=normalized)
    if scope == "clip" and not normalized["active_clip_id"]:
        raise ScopeError("请先在 DAW 选择一个片段，再使用整段范围。")
    return frozen


def assert_scope_unchanged(frozen: dict, context: dict) -> None:
    if context.get("project_id") != frozen.get("project_id") or context.get("revision") != frozen.get("project_revision"):
        raise ScopeError("工程已变化，请重新生成方案。")
    if frozen["mode"] != "project":
        current = freeze_scope(context, frozen["mode"])
        if current != frozen:
            raise ScopeError("音乐选择已变化，旧方案不会改用新的选择。请重新生成方案。")


def constrain_proposal(payload: dict, context: dict, frozen: dict) -> dict:
    """Scope each action against the same sequential candidate as compilation.

    Earlier authorized creations/clones may be referenced; they never authorize
    unrelated original objects. No DAW state or caller payload is changed.
    """
    from .plans import PlanError, _compile_plan
    assert_scope_unchanged(frozen, context)
    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ScopeError("修改方案缺少操作列表。")
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
            raise ScopeError("主轨效果器会影响整个工程；请切换到工程范围。")
        if kind in {"set_native_pad", "set_native_sampler"}:
            raise ScopeError("采样器和鼓组参数目前只能在整个工程范围使用单独方案；请切换到工程范围。")
        bpm = state.get("bpm")
        if not _finite(bpm) or not 20 <= bpm <= 300:
            raise ScopeError("当前速度无效，无法计算选择范围。")

        def clip_allowed(cid):
            if cid not in clips:
                raise ScopeError("目标片段未读取、已删除或别名尚未声明，不能猜测范围。")
            owner, clip = clips[cid]
            if cid not in selected_clips | derived_clips and not (timed and not selected_clips and owner["id"] in selected_tracks):
                raise ScopeError("方案目标不在已确认的片段选择内。")
            if timed and not (clip["start_seconds"] < time_range["end_seconds"] and clip["start_seconds"] + clip["duration_seconds"] > time_range["start_seconds"]):
                raise ScopeError("片段与时间选区不相交。")
            return owner, clip

        if kind in {"set_tempo", "create_track"}:
            raise ScopeError("此操作会影响整个工程；请明确切换到工程范围后再生成方案。")
        if kind in TRACK_ACTIONS:
            tid = action.get("track_id")
            if not track_only or tid not in selected_tracks or tid not in tracks:
                raise ScopeError("整轨操作需要明确选择轨道；音符、片段或时间选区不能授权整轨修改。")
        elif kind == "create_midi_clip":
            tid = action.get("track_id")
            start, length = action.get("start_beats"), action.get("length_beats")
            if note_focus or tid not in selected_tracks or tid not in tracks or not (track_only or timed):
                raise ScopeError("新建片段需要已选轨道或该轨道上的时间范围。")
            if not _finite(start) or not _finite(length) or length <= 0 or not contained(start*60/bpm, (start+length)*60/bpm):
                raise ScopeError("新片段超出已确认的时间选区。")
            derived_clips.add("@"+action["as"])
        elif kind in NOTE_ACTIONS:
            cid = action.get("clip_id")
            _, clip = clip_allowed(cid)
            notes = state.get("clip_notes", {}).get(cid)
            if clip.get("kind") != "midi" or not isinstance(notes, list) or len(notes) != clip.get("note_count") or len(notes)>2000:
                raise ScopeError("需要先完整读取目标 MIDI 片段，最多 2000 个音符。")
            if kind == "add_notes":
                if note_focus:
                    raise ScopeError("已选音符不能授权新增无关音符；请明确使用整段或时间范围。")
                new_notes = action.get("notes")
                if not isinstance(new_notes, list):
                    raise ScopeError("新增音符列表无效。")
                for note in new_notes:
                    if not isinstance(note, dict) or not _finite(note.get("start_beats")) or not _finite(note.get("length_beats")):
                        raise ScopeError("新增音符时间无效。")
                    at = clip["start_seconds"] + note["start_beats"]*60/bpm
                    end = at + note["length_beats"]*60/bpm
                    if not contained(at, end) or (timed and at >= time_range["end_seconds"]):
                        raise ScopeError("新增音符超出已确认的时间区间。")
                return
            allowed = set(selection["note_ids"]) if note_focus else {n["id"] for n in notes}
            if timed:
                allowed &= {n["id"] for n in notes if time_range["start_seconds"] <= clip["start_seconds"]+n["start_beats"]*60/bpm < time_range["end_seconds"]}
            requested = _ids(action["note_ids"], 2000) if "note_ids" in action else sorted(allowed)
            if not requested or not set(requested) <= allowed:
                raise ScopeError("音符操作超出冻结选择，或选区内没有音符起点。")
            action["note_ids"] = requested
            if timed and kind in {"quantize_notes", "move_notes", "set_note_length"}:
                for note in notes:
                    if note["id"] not in requested:
                        continue
                    start, length = note["start_beats"], note["length_beats"]
                    if kind == "quantize_notes":
                        denominator = action.get("grid_denominator")
                        if type(denominator) is not int or not 1<=denominator<=16384 or denominator & (denominator-1):
                            raise ScopeError("量化网格无效。")
                        step = 4/denominator
                        start = math.floor(start/step+0.5)*step
                    elif kind == "move_notes":
                        if not _finite(action.get("delta_beats")):
                            raise ScopeError("音符移动量无效。")
                        start += action["delta_beats"]
                    else:
                        if not _finite(action.get("length_beats")):
                            raise ScopeError("音符长度无效。")
                        length = action["length_beats"]
                    at = clip["start_seconds"]+start*60/bpm
                    if not time_range["start_seconds"] <= at < time_range["end_seconds"] or (kind=="set_note_length" and not contained(at, at+length*60/bpm)):
                        raise ScopeError("音符修改会超出已确认的时间选区。")
        elif kind in {"move_clip", "trim_clip", "delete_clip", "duplicate_clip"}:
            if note_focus:
                raise ScopeError("音符选择不能授权修改整个片段。")
            owner, clip = clip_allowed(action.get("clip_id"))
            start, end = clip["start_seconds"], clip["start_seconds"]+clip["duration_seconds"]
            if not contained(start, end):
                raise ScopeError("修改完整片段会影响已确认时间区间之外的内容。")
            if kind == "move_clip":
                at = action.get("start_seconds")
                target = action.get("target_track_id", owner["id"])
                if target != owner["id"] and (target not in selected_tracks or target not in tracks):
                    raise ScopeError("跨轨移动需要明确选择目标轨道，或切换到整个工程范围。")
                if not _finite(at) or not contained(at, at+clip["duration_seconds"]):
                    raise ScopeError("移动整个片段会超出已确认的时间选区。")
            elif kind == "duplicate_clip":
                if not contained(end, end+clip["duration_seconds"]):
                    raise ScopeError("复制片段会超出已确认的时间选区。")
                derived_clips.add("@"+action["as"])
            elif kind == "trim_clip":
                a,b=action.get("start_seconds"),action.get("end_seconds")
                if not _finite(a) or not _finite(b) or not contained(a,b):
                    raise ScopeError("裁剪区间超出已确认的时间选区。")
        else:
            raise ScopeError("当前范围不允许此操作。")
    try:
        plan = _compile_plan(payload, context, authorizer=authorize, allow_noop=True)
    except PlanError as exc:
        raise ScopeError(str(exc)) from exc
    return {"summary": plan["summary"], "actions": plan["actions"]}
