"""Compile an untrusted model proposal into one bounded, reviewable DAW batch.

Only this module translates model intent into commands. It never talks to the
DAW, a model, or the filesystem. Context is a read-only snapshot, augmented by
complete note pages in ``clip_notes``. All beat values are quarter-note beats.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
import uuid


class PlanError(ValueError):
    """A proposal cannot safely become an executable plan."""


MAX_ACTIONS = 16
MAX_NOTES = 2000
MAX_SECONDS = 172800
TRACK_FIELDS = ("name", "kind", "gain_db", "pan", "muted", "solo")
CLIP_FIELDS = ("kind", "start_seconds", "duration_seconds", "start_beats", "length_beats", "note_count",
               "asset_id", "source_offset", "fade_in_seconds", "fade_out_seconds", "controller_count")
NOTE_FIELDS = ("id", "pitch", "start_beats", "length_beats", "velocity", "channel")


def _shape(kind: str, fields: dict, optional: tuple = ()) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": {"type": {"const": kind}, **fields},
            "required": ["type", *(key for key in fields if key not in optional)]}


_ID = {"type": "string", "minLength": 1, "maxLength": 200}
_NAME = {"type": "string", "minLength": 1, "maxLength": 200}
_ALIAS = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,39}$", "maxLength": 40}
_NOTE_SCOPE = {"clip_id": _ID, "note_ids": {"type": "array", "minItems": 1,
               "maxItems": MAX_NOTES, "items": _ID, "uniqueItems": True,
               "description": "Explicit existing note IDs. Omit to use the locally authorized GUI note selection or all notes in an authorized clip. For a newly created/duplicated clip omit IDs; the host assigns fresh local UUIDs."}}
_NOTE = {"type": "object", "additionalProperties": False, "required": ["pitch", "start_beats", "length_beats", "velocity", "channel"],
         "properties": {"pitch": {"type": "integer", "minimum": 0, "maximum": 127},
                        "start_beats": {"type": "number", "minimum": 0},
                        "length_beats": {"type": "number", "exclusiveMinimum": 0},
                        "velocity": {"type": "integer", "minimum": 1, "maximum": 127},
                        "channel": {"type": "integer", "minimum": 1, "maximum": 16}}}
_SECONDS = {"type": "number", "minimum": 0, "maximum": MAX_SECONDS}
_ACTIONS = [
    _shape("set_tempo", {"bpm": {"type": "number", "minimum": 20, "maximum": 300}}),
    _shape("rename_track", {"track_id": _ID, "name": _NAME}),
    _shape("create_track", {"kind": {"enum": ["audio", "instrument", "bus"]}, "name": _NAME, "as": _ALIAS}, ("as",)),
    _shape("set_track_gain", {"track_id": _ID, "gain_db": {"type": "number", "minimum": -60, "maximum": 6}}),
    _shape("set_track_pan", {"track_id": _ID, "pan": {"type": "number", "minimum": -1, "maximum": 1}}),
    _shape("set_track_muted", {"track_id": _ID, "muted": {"type": "boolean"}}),
    _shape("set_track_solo", {"track_id": _ID, "solo": {"type": "boolean"}}),
    _shape("create_midi_clip", {"track_id": _ID, "start_beats": {"type": "number", "minimum": 0},
                                "length_beats": {"type": "number", "exclusiveMinimum": 0}, "as": _ALIAS}, ("as",)),
    _shape("duplicate_clip", {"clip_id": _ID, "as": _ALIAS}, ("as",)),
    _shape("move_clip", {"clip_id": _ID, "start_seconds": _SECONDS, "target_track_id": _ID}, ("target_track_id",)),
    _shape("trim_clip", {"clip_id": _ID, "start_seconds": _SECONDS, "end_seconds": _SECONDS}),
    _shape("delete_clip", {"clip_id": _ID}),
    _shape("add_notes", {"clip_id": _ID, "notes": {"type": "array", "minItems": 1, "maxItems": MAX_NOTES, "items": _NOTE}}),
    _shape("delete_notes", _NOTE_SCOPE, ("note_ids",)),
    _shape("set_note_length", {**_NOTE_SCOPE, "length_beats": {"type": "number", "exclusiveMinimum": 0}}, ("note_ids",)),
    _shape("move_notes", {**_NOTE_SCOPE, "delta_beats": {"type": "number"}}, ("note_ids",)),
    _shape("transpose_notes", {**_NOTE_SCOPE, "semitones": {"type": "integer", "minimum": -127, "maximum": 127}}, ("note_ids",)),
    _shape("quantize_notes", {**_NOTE_SCOPE, "grid_denominator": {"type": "integer", "enum": [2 ** i for i in range(15)]}}, ("note_ids",)),
    _shape("set_note_velocity", {**_NOTE_SCOPE, "velocity": {"type": "integer", "minimum": 1, "maximum": 127}}, ("note_ids",)),
]
NOTE_ACTIONS = {"add_notes", "delete_notes", "set_note_length", "move_notes", "transpose_notes", "quantize_notes", "set_note_velocity"}
CREATIONS = {"create_track", "create_midi_clip", "duplicate_clip"}
PLAN_TOOL = {"type": "function", "function": {"name": "propose_plan",
    "description": "Propose one atomic DAW edit batch for user review, NEVER execute. Use exact existing IDs or @alias declared with as on an EARLIER create_track/create_midi_clip/duplicate_clip action. Alias names match [A-Za-z][A-Za-z0-9_-]{0,39}; aliases cannot be reused or referenced forward. Chained creation and explicit MIDI notes are supported; do not invent templates. Duplicate copies one clip immediately after itself, including controllers, and assigns fresh note IDs. trim_clip only shortens within the current clip; MIDI clips containing controllers are not supported for trim in this batch. Beat positions use quarter notes; a bar = numerator * 4 / denominator beats. GUI scope is enforced locally: selected notes never authorize whole-clip changes or unrelated additions; cross-track moves require an authorized destination. New notes require explicit pitch/start/length/velocity/channel. Omit note_ids for all authorized notes of a new clip. Quantization changes starts only and rejects overflow. Do not invent tools or claim you heard audio.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["summary", "actions"],
                   "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                                  "actions": {"type": "array", "minItems": 1, "maxItems": MAX_ACTIONS,
                                              "items": {"oneOf": _ACTIONS}}}}}}

_SCHEMAS = {shape["properties"]["type"]["const"]: shape for shape in _ACTIONS}


def _text(value: object, field: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise PlanError(f"{field} 必须是 1–{maximum} 字符的单行文本。")
    return value.strip()


def _number(value: object, field: str, low: float, high: float, integer: bool = False) -> float:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise PlanError(f"{field} 必须是 {low:g}–{high:g} 内的有限数字。")
    if integer and value != int(value):
        raise PlanError(f"{field} 必须是整数。")
    return int(value) if integer else float(value)


def _same(a: object, b: object, field: str = "") -> bool:
    if type(a) in (int, float) and type(b) in (int, float):
        tolerance = 2e-5 if field in ("gain_db", "pan") else 1e-9
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=tolerance)
    return type(a) is type(b) and a == b


def _projection(value: dict, fields: tuple) -> dict:
    return {field: value[field] for field in fields if field in value}


def _maps(context: dict) -> tuple[dict, dict]:
    tracks, clips = {}, {}
    raw_tracks = context.get("tracks")
    if not isinstance(raw_tracks, list):
        raise PlanError("工程轨道快照缺失。")
    for track in raw_tracks:
        if not isinstance(track, dict) or not isinstance(track.get("id"), str) or track["id"] in tracks:
            raise PlanError("工程轨道快照无效，请刷新。")
        tracks[track["id"]] = track
        if not isinstance(track.get("clips", []), list):
            raise PlanError("工程片段快照无效，请刷新。")
        for clip in track.get("clips", []):
            if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or clip["id"] in clips:
                raise PlanError("工程片段快照无效，请刷新。")
            clips[clip["id"]] = (track, clip)
    return tracks, clips


def _valid_notes(notes: object, clip: dict) -> list[dict]:
    if not isinstance(notes, list) or len(notes) != clip.get("note_count"):
        raise PlanError("该片段的完整音符尚未读取，请刷新后再生成方案。")
    if len(notes) > MAX_NOTES:
        raise PlanError(f"第一版一次最多编辑 {MAX_NOTES} 个音符。")
    result, ids, channels = [], set(), set()
    for raw in notes:
        if not isinstance(raw, dict) or set(raw) != set(NOTE_FIELDS):
            raise PlanError("音符数据字段不完整。")
        note = dict(raw)
        note["id"] = _text(note["id"], "note_id")
        if note["id"] in ids:
            raise PlanError("音符 ID 重复。")
        ids.add(note["id"])
        for field, low, high in (("pitch", 0, 127), ("velocity", 1, 127), ("channel", 1, 16)):
            note[field] = _number(note[field], field, low, high, True)
        note["start_beats"] = _number(note["start_beats"], "start_beats", 0, float(clip["length_beats"]))
        note["length_beats"] = _number(note["length_beats"], "length_beats", 0, float(clip["length_beats"]))
        end = note["start_beats"] + note["length_beats"]
        if end <= note["start_beats"] or end > clip["length_beats"] + 1e-9:
            raise PlanError("音符长度无效或超出片段范围；不会静默截断。")
        channels.add(note["channel"])
        result.append(note)
    if len(channels) > 1:
        raise PlanError("同一 MIDI 片段必须使用同一通道。")
    return result


def _validate_timeline(context: dict) -> None:
    bpm = _number(context.get("bpm"), "bpm", 20, 300)
    for track in context.get("tracks", []):
        for clip in track.get("clips", []):
            if clip["kind"] == "midi":
                start, length = clip["start_beats"], clip["length_beats"]
                _number(start, "start_beats", 0, MAX_SECONDS * bpm / 60)
                _number(length, "length_beats", 0, MAX_SECONDS * bpm / 60)
                if start + length <= start or start + length > MAX_SECONDS * bpm / 60:
                    raise PlanError("MIDI 片段必须有正长度且位于 48 小时时间线内。")
                clip["start_seconds"] = start * 60 / bpm
                clip["duration_seconds"] = length * 60 / bpm
            else:
                start, duration = clip["start_seconds"], clip["duration_seconds"]
                _number(start, "start_seconds", 0, MAX_SECONDS)
                _number(duration, "duration_seconds", 0, MAX_SECONDS)
                if duration <= 0 or start + duration > MAX_SECONDS:
                    raise PlanError("音频片段必须位于 48 小时时间线内。")



def required_note_clip_ids(payload: dict) -> list[str]:
    """Existing targets to preload; caller filters audio clips before read_notes.

    Alias sources are already covered by their earlier duplicate/creation action.
    This does not authorize or validate the proposal.
    """
    return sorted({a["clip_id"] for a in payload.get("actions", [])
                   if isinstance(a, dict) and a.get("type") in NOTE_ACTIONS | {"duplicate_clip", "trim_clip"}
                   and isinstance(a.get("clip_id"), str) and not a["clip_id"].startswith("@")})


def _prepare(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"summary", "actions"}:
        raise PlanError("方案必须只包含 summary 和 actions。")
    result = deepcopy(payload)
    result["summary"] = _text(result["summary"], "summary", 1000)
    actions = result["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise PlanError(f"每份方案需要 1–{MAX_ACTIONS} 个操作。")
    declared = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("type"), str) or action["type"] not in _SCHEMAS:
            raise PlanError("方案包含不支持的操作。")
        shape = _SCHEMAS[action["type"]]
        if not set(shape["required"]) <= set(action) or not set(action) <= set(shape["properties"]):
            raise PlanError(f"{action['type']} 的参数缺失或包含未知字段。")
        if "as" in action:
            alias = action["as"]
            if not isinstance(alias, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", alias) is None or alias in declared:
                raise PlanError("新对象别名无效或重复；必须以字母开头，最多 40 字符。")
            declared.add(alias)
    for index, action in enumerate(actions):
        if action["type"] in CREATIONS and "as" not in action:
            alias = f"agent{index + 1}"
            while alias in declared:
                alias += "x"
            declared.add(alias)
            action["as"] = alias
    return result


def compile_plan(payload: dict, context: dict) -> dict:
    """Compile one immutable, bounded candidate; never execute partial work."""
    return _compile_plan(payload, context)


def _compile_plan(payload: dict, context: dict, authorizer=None, allow_noop=False) -> dict:
    """The scope module uses the SAME sequential candidate semantics.

    authorizer(action, candidate) may narrow note_ids before this action, or fail.
    The candidate is private; neither caller input is mutated. Local UUID5 IDs
    remain stable when the same frozen proposal is scoped and compiled again.
    """
    prepared = _prepare(payload)
    if not isinstance(context, dict) or not isinstance(context.get("project_id"), str) or type(context.get("revision")) is not int or context["revision"] < 0:
        raise PlanError("缺少当前工程身份和版本。")
    if context.get("recording") or context.get("recording_finalizing") or context.get("counting_in"):
        raise PlanError("录音或预备拍期间暂不生成编辑方案。")
    state = deepcopy(context)
    state.setdefault("clip_notes", {})
    tracks, clips = _maps(state)
    original_tracks, original_clips = _maps(context)
    original_ids = set(tracks) | set(clips)
    if any(i.startswith("@") for i in original_ids) or len(tracks) > 64:
        raise PlanError("工程对象身份或轨道数无效。")
    commands, changes, aliases = [], [], {}
    note_previews = []
    touched_notes, preserved_notes, deleted_clips = set(), set(), set()
    total_notes = 0
    known_note_ids = {n.get("id") for notes in state["clip_notes"].values() if isinstance(notes, list)
                      for n in notes if isinstance(n, dict)}
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"emusician:{context['project_id']}:{context['revision']}")

    def fresh_note(index, suffix):
        value = str(uuid.uuid5(namespace, f"action:{index}:note:{suffix}"))
        if value in known_note_ids or value in original_ids:
            raise PlanError("新音符身份与现有对象冲突，请重新生成方案。")
        known_note_ids.add(value)
        return value

    def existing(identifier, mapping, label):
        value = _text(identifier, label)
        if value != identifier or value not in mapping:
            raise PlanError(f"{label} 不存在、已删除，或别名尚未声明。")
        return mapping[value]

    def note_budget(count):
        nonlocal total_notes
        total_notes += count
        if total_notes > MAX_NOTES:
            raise PlanError(f"每份方案最多处理 {MAX_NOTES} 个音符操作。")

    def loaded(clip):
        if clip["kind"] != "midi":
            raise PlanError("音符编辑需要 MIDI 片段。")
        return _valid_notes(state["clip_notes"].get(clip["id"]), clip)

    def count_clip(track, delta):
        track["clip_count"] = track.get("clip_count", len(track.get("clips", []))) + delta

    for index, action in enumerate(prepared["actions"]):
        kind = action["type"]
        if authorizer:
            authorizer(action, state)
        args = {k: deepcopy(v) for k, v in action.items() if k not in ("type", "as")}
        track = existing(args["track_id"], tracks, "track_id") if "track_id" in args else None
        clip = None
        if "clip_id" in args:
            track, clip = existing(args["clip_id"], clips, "clip_id")
        clip_label = (f"「{track['name']}」{clip['start_seconds']:g} 秒起的 "
                      f"{'MIDI' if clip['kind'] == 'midi' else '音频'}片段") if clip is not None else ""
        target = existing(args["target_track_id"], tracks, "target_track_id") if "target_track_id" in args else None
        command = {"command": kind, "args": args}
        extra_commands = []
        changed = True
        if kind in CREATIONS:
            alias = action["as"]
            if alias in aliases or alias in original_ids or "@" + alias in original_ids:
                raise PlanError("新对象别名与已有身份冲突。")
            command["as"] = alias
            new_id = "@" + alias
        if kind == "set_tempo":
            if any(t.get("clips_truncated") for t in tracks.values()):
                raise PlanError("更改速度前需要读取完整片段范围。")
            value = _number(args["bpm"], "bpm", 20, 300)
            old = state["bpm"]
            state["bpm"] = args["bpm"] = value
            changed = not _same(old, value)
            description = f"速度：{old:g} → {value:g} BPM（音频保持原速，MIDI 随速度变化）"
        elif kind == "create_track":
            if args["kind"] not in ("audio", "instrument", "bus"):
                raise PlanError("轨道类型必须是 audio、instrument 或 bus。")
            args["name"] = _text(args["name"], "name")
            if len(tracks) >= 64:
                raise PlanError("工程最多支持 64 条轨道。")
            new = {"id": new_id, **args, "gain_db": 0.0, "pan": 0.0, "muted": False,
                   "solo": False, "clips": [], "clip_count": 0, "clips_truncated": False}
            tracks[new_id] = new
            state["tracks"].append(new)
            aliases[alias] = "track"
            description = f"新建 {args['kind']} 轨道「{args['name']}」（不自动加载插件）"
        elif kind.startswith("set_track_") or kind == "rename_track":
            field = {"rename_track": "name", "set_track_gain": "gain_db", "set_track_pan": "pan",
                     "set_track_muted": "muted", "set_track_solo": "solo"}[kind]
            value = args[field]
            if field == "name":
                value = _text(value, "name")
            elif field in ("muted", "solo"):
                if type(value) is not bool:
                    raise PlanError(f"{field} 必须是布尔值。")
            else:
                value = _number(value, field, *({"gain_db": (-60, 6), "pan": (-1, 1)}[field]))
            old = track[field]
            track[field] = args[field] = value
            changed = not _same(old, value, field)
            description = f"轨道「{track['name']}」{field}：{old} → {value}"
        elif kind in {"create_midi_clip", "duplicate_clip"}:
            if sum(t.get("clip_count", len(t.get("clips", []))) for t in tracks.values()) >= 4096:
                raise PlanError("工程最多支持 4096 个片段。")
            if kind == "create_midi_clip":
                if track["kind"] != "instrument":
                    raise PlanError("MIDI 片段只能建在 instrument 轨道上。")
                start = _number(args["start_beats"], "start_beats", 0, MAX_SECONDS * state["bpm"] / 60)
                length = _number(args["length_beats"], "length_beats", 0, MAX_SECONDS * state["bpm"] / 60)
                args.update(start_beats=start, length_beats=length)
                new = {"id": new_id, "kind": "midi", "start_beats": start, "length_beats": length, "note_count": 0}
                state["clip_notes"][new_id] = []
                bars = length / (state.get("numerator", 4) * 4 / state.get("denominator", 4))
                description = f"「{track['name']}」新建空 MIDI 片段：第 {start:g} 四分音符拍起，{length:g} 拍 / {bars:g} 小节"
            else:
                new = deepcopy(clip)
                new["id"] = new_id
                new["start_seconds"] += new["duration_seconds"]
                command = {"command": "duplicate_clips", "args": {"clip_ids": [clip["id"]]}, "as": alias}
                if new["kind"] == "midi":
                    _number(clip.get("controller_count", 0), "controller_count", 0, MAX_NOTES, True)
                    notes = loaded(clip)
                    note_budget(len(notes))
                    # Source preservation is a readback postcondition, not an
                    # additional edit or another charge to the operation budget.
                    preserved_notes.add(clip["id"])
                    for n, note in enumerate(notes):
                        note["id"] = fresh_note(index, f"clone:{n}")
                    state["clip_notes"][new_id] = notes
                    new["start_beats"] = new["start_seconds"] * state["bpm"] / 60
                    # Native duplicate retains controllers; write_notes only replaces
                    # note sequence, so this establishes locally known UUIDs safely.
                    extra_commands.append({"command": "write_notes", "args": {"clip_id": new_id, "notes": deepcopy(notes)}})
                description = f"复制{clip_label}，放在 {new['start_seconds']:g} 秒处，紧接原片段之后（保留控制器）"
            count_clip(track, 1)
            track.setdefault("clips", []).append(new)
            clips[new_id] = (track, new)
            aliases[alias] = "clip"
            if new["kind"] == "midi":
                touched_notes.add(new_id)
        elif kind == "move_clip":
            value = _number(args["start_seconds"], "start_seconds", 0, MAX_SECONDS)
            old = clip["start_seconds"]
            target = target or track
            if target["kind"] != track["kind"]:
                raise PlanError("跨轨移动需要相同类型的目标轨道。")
            changed = not _same(old, value) or target["id"] != track["id"]
            if target["id"] != track["id"]:
                command = {"command": "move_clips", "args": {"clip_ids": [clip["id"]], "delta_seconds": value-old, "target_track_id": target["id"]}}
                count_clip(track, -1)
                track["clips"].remove(clip)
                count_clip(target, 1)
                target.setdefault("clips", []).append(clip)
                clips[clip["id"]] = (target, clip)
            else:
                command["args"] = {"clip_id": clip["id"], "start_seconds": value}
            clip["start_seconds"] = value
            if clip["kind"] == "midi":
                clip["start_beats"] = value * state["bpm"] / 60
            description = f"{clip_label}：{old:g} → {value:g} 秒，目标「{target['name']}」"
        elif kind == "trim_clip":
            start = _number(args["start_seconds"], "start_seconds", 0, MAX_SECONDS)
            end = _number(args["end_seconds"], "end_seconds", 0, MAX_SECONDS)
            old_start, old_end = clip["start_seconds"], clip["start_seconds"] + clip["duration_seconds"]
            if start < old_start or end > old_end or end <= start:
                raise PlanError("本版裁剪只能在当前片段内部保留正长度区间，不静默扩展。")
            changed = not _same(start, old_start) or not _same(end, old_end)
            args.update(start_seconds=start, end_seconds=end)
            if clip["kind"] == "midi":
                if clip.get("controller_count", 0) != 0:
                    raise PlanError("本批暂不裁剪含 MIDI 控制器的片段；请在 DAW 手工裁剪，以保留并核对边界状态。")
                notes = loaded(clip)
                note_budget(len(notes))
                delta = (start-old_start) * state["bpm"] / 60
                length = (end-start) * state["bpm"] / 60
                remaining = []
                for note in notes:
                    a = note["start_beats"]-delta
                    b = a+note["length_beats"]
                    note["start_beats"] = max(0.0, a)
                    note["length_beats"] = min(length, b)-note["start_beats"]
                    if note["length_beats"] > 0:
                        remaining.append(note)
                clip.update(start_beats=start*state["bpm"]/60, length_beats=length, note_count=len(remaining))
                state["clip_notes"][clip["id"]] = remaining
                touched_notes.add(clip["id"])
            else:
                clip["source_offset"] = clip.get("source_offset", 0.0) + start-old_start
                duration = end-start
                clip["fade_in_seconds"] = min(clip.get("fade_in_seconds", 0.0), duration)
                clip["fade_out_seconds"] = min(clip.get("fade_out_seconds", 0.0), duration-clip["fade_in_seconds"])
            clip.update(start_seconds=start, duration_seconds=end-start)
            description = f"{clip_label}裁剪：[{old_start:g}, {old_end:g}] → [{start:g}, {end:g}] 秒（区间外音符移除，边界音符缩短）"
        elif kind == "delete_clip":
            command = {"command": "delete_clips", "args": {"clip_ids": [clip["id"]]}}
            count_clip(track, -1)
            track["clips"].remove(clip)
            clips.pop(clip["id"])
            state["clip_notes"].pop(clip["id"], None)
            touched_notes.discard(clip["id"])
            preserved_notes.discard(clip["id"])
            deleted_clips.add(clip["id"])
            description = f"删除{clip_label}（可撤销，不删除源文件）"
        else:
            notes = loaded(clip)
            upsert, delete_ids = [], []
            if kind == "add_notes":
                raw_notes = args["notes"]
                if not isinstance(raw_notes, list) or not 1 <= len(raw_notes) <= MAX_NOTES:
                    raise PlanError("新增音符必须是非空且不超过 2000 项的列表。")
                note_budget(len(raw_notes))
                for n, raw in enumerate(raw_notes):
                    if not isinstance(raw, dict) or set(raw) != set(NOTE_FIELDS)-{"id"}:
                        raise PlanError("新增音符必须明确音高、起点、长度、力度、通道，ID 由本地生成。")
                    upsert.append({"id": fresh_note(index, n), **raw})
                notes.extend(upsert)
                clip["note_count"] = len(notes)
                detail = f"新增 {len(upsert)} 个明确音符"
                selected = {n["id"] for n in upsert}
            else:
                selected = args.get("note_ids", [note["id"] for note in notes])
                if not isinstance(selected, list) or not selected or len(selected) > MAX_NOTES or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
                    raise PlanError("需要非空且不重复的音符 ID 列表；空片段没有可编辑音符。")
                selected = set(selected)
                if not selected <= {note["id"] for note in notes}:
                    raise PlanError("指定音符已不存在，请重新读取片段；复制片段拥有新的音符身份。")
                note_budget(len(selected))
                if kind == "delete_notes":
                    delete_ids = sorted(selected)
                    notes = [n for n in notes if n["id"] not in selected]
                    clip["note_count"] = len(notes)
                    detail = f"删除 {len(delete_ids)} 个音符"
                else:
                    if kind == "transpose_notes":
                        amount = _number(args["semitones"], "semitones", -127, 127, True)
                        detail = f"移调 {amount:+d} 半音"
                    elif kind == "set_note_velocity":
                        amount = _number(args["velocity"], "velocity", 1, 127, True)
                        detail = f"力度设为 {amount}"
                    elif kind == "set_note_length":
                        amount = _number(args["length_beats"], "length_beats", 0, clip["length_beats"])
                        detail = f"时长设为 {amount:g} 四分音符拍"
                    elif kind == "move_notes":
                        amount = _number(args["delta_beats"], "delta_beats", -clip["length_beats"], clip["length_beats"])
                        detail = f"音符移动 {amount:+g} 四分音符拍"
                    else:
                        denominator = _number(args["grid_denominator"], "grid_denominator", 1, 16384, True)
                        if denominator & (denominator-1):
                            raise PlanError("网格分母必须是 1–16384 内的 2 的幂。")
                        amount = 4/denominator
                        detail = f"起音量化到 1/{denominator}（保留时长）"
                    for note in notes:
                        if note["id"] not in selected:
                            continue
                        old = dict(note)
                        if kind == "transpose_notes": note["pitch"] += amount
                        elif kind == "set_note_velocity": note["velocity"] = amount
                        elif kind == "set_note_length": note["length_beats"] = amount
                        elif kind == "move_notes": note["start_beats"] += amount
                        else: note["start_beats"] = math.floor(note["start_beats"]/amount + 0.5)*amount
                        if note != old:
                            upsert.append(dict(note))
            validated = _valid_notes(notes, clip)
            if kind == "add_notes":
                note_previews.append({"label": clip_label, "notes": [
                    _projection(n, NOTE_FIELDS[1:]) for n in validated if n["id"] in selected]})
            state["clip_notes"][clip["id"]] = validated
            touched_notes.add(clip["id"])
            command = {"command": "edit_notes", "args": {"clip_id": clip["id"], "upsert": deepcopy(upsert), "delete_ids": delete_ids}}
            changed = bool(upsert or delete_ids)
            description = f"{clip_label}：{detail}；改变 {len(upsert)+len(delete_ids)} / 选定 {len(selected)} 个音符"
        _validate_timeline(state)
        if changed:
            commands.extend([command, *extra_commands])
            changes.append(description)
    # Native result references only bind objects that survive the atomic batch.
    # Reject an otherwise effective proposal before publishing an unusable plan.
    for alias, object_kind in aliases.items():
        if "@" + alias not in (tracks if object_kind == "track" else clips):
            raise PlanError("方案中新建或复制的对象在同一批次被删除；请移除这组相互抵消的操作。")
    effective = set(tracks) != set(original_tracks) or set(clips) != set(original_clips) or not _same(state["bpm"], context["bpm"])
    effective |= any(not _same(track.get(field), original_tracks[tid].get(field), field)
                     for tid, track in tracks.items() if tid in original_tracks for field in TRACK_FIELDS)
    effective |= any(pair[0]["id"] != original_clips[cid][0]["id"] or
                     any(not _same(pair[1].get(field), original_clips[cid][1].get(field), field) for field in CLIP_FIELDS)
                     for cid, pair in clips.items() if cid in original_clips)
    effective |= any(state["clip_notes"].get(cid) != context.get("clip_notes", {}).get(cid) for cid in touched_notes)
    if not allow_noop and (not commands or not effective):
        raise PlanError("所有值已符合要求，没有需要应用的修改。")
    checks = [{"kind": "bpm", "value": state["bpm"]}, {"kind": "track_count", "value": len(tracks)}]
    for tid, track in tracks.items():
        checks.append({"kind": "track", "id": tid, "value": _projection(track, TRACK_FIELDS),
                       "clip_count": track.get("clip_count", len(track.get("clips", [])))})
        for clip in track.get("clips", []):
            checks.append({"kind": "clip", "id": clip["id"], "track_id": tid, "value": _projection(clip, CLIP_FIELDS)})
    for cid in sorted(deleted_clips):
        checks.append({"kind": "absent_clip", "id": cid})
    readback_notes = sorted((touched_notes | preserved_notes) & set(clips))
    for cid in readback_notes:
        checks.append({"kind": "notes", "id": cid, "value": state["clip_notes"][cid]})
    return {"summary": prepared["summary"], "commands": commands, "changes": changes, "checks": checks,
            "actions": prepared["actions"], "aliases": aliases, "baseline_ids": sorted(original_ids),
            "project_id": context["project_id"], "revision": context["revision"], "note_clip_ids": readback_notes,
            "note_previews": note_previews}


def resolve_plan_refs(plan: dict, refs: object) -> dict:
    """Bind postconditions to native result IDs; never rewrite approved commands.

    A missing/extra/colliding binding is verification failure AFTER commit, not
    permission to retry the batch. The runtime must retain the available Undo.
    """
    aliases = plan.get("aliases", {})
    if not aliases:
        if refs not in (None, {}):
            raise PlanError("DAW 返回了方案之外的新对象引用。")
        return deepcopy(plan)
    if not isinstance(refs, dict) or set(refs) != set(aliases):
        raise PlanError("DAW 未返回完整且匹配的新对象引用，修改可能已提交，请检查或撤销。")
    values = list(refs.values())
    if any(not isinstance(v, str) or not v or len(v) > 200 or v.startswith("@") or any(ord(c)<32 for c in v) for v in values) or len(set(values)) != len(values) or set(values) & set(plan.get("baseline_ids", [])):
        raise PlanError("DAW 新对象引用无效、重复或与原对象冲突。")
    result = deepcopy(plan)
    def resolve(value):
        if isinstance(value, str) and value.startswith("@"):
            if value[1:] not in refs:
                raise PlanError("方案包含未解析的对象引用。")
            return refs[value[1:]]
        return value
    for check in result["checks"]:
        for field in ("id", "track_id"):
            if field in check:
                check[field] = resolve(check[field])
    result["note_clip_ids"] = [resolve(cid) for cid in result["note_clip_ids"]]
    result["refs"] = dict(refs)
    return result


def verify_plan(plan: dict, before_context: dict, after_context: dict) -> list[str]:
    """Verify musical state and exact created identities, never listening quality."""
    if plan.get("project_id") != before_context.get("project_id") or plan.get("revision") != before_context.get("revision"):
        return ["校验基线与已批准方案不一致。"]
    if after_context.get("project_id") != plan["project_id"]:
        return ["执行后工程身份改变。"]
    if plan.get("aliases") and set(plan.get("refs", {})) != set(plan["aliases"]):
        return ["执行后缺少新对象引用绑定。"]
    try:
        tracks, clips = _maps(after_context)
    except (PlanError, TypeError):
        return ["执行后快照无效。"]
    errors = []
    def matches(actual, expected):
        return all(key in actual and _same(actual[key], value, key) for key, value in expected.items())
    for check in plan.get("checks", []):
        kind = check["kind"]
        if kind == "bpm" and not _same(after_context.get("bpm"), check["value"]):
            errors.append("速度回读与方案不一致。")
        elif kind == "track_count" and len(tracks) != check["value"]:
            errors.append("轨道数量回读与方案不一致。")
        elif kind == "track":
            track = tracks.get(check["id"])
            if track is None or not matches(track, check["value"]) or track.get("clip_count", len(track.get("clips", []))) != check["clip_count"]:
                errors.append(f"轨道 {check['id']} 回读与方案不一致。")
        elif kind == "clip":
            pair = clips.get(check["id"])
            if pair is None or pair[0]["id"] != check["track_id"] or not matches(pair[1], check["value"]):
                errors.append(f"片段 {check['id']} 回读与方案不一致。")
        elif kind == "absent_clip" and check["id"] in clips:
            errors.append(f"片段 {check['id']} 未按方案删除。")
        elif kind == "notes":
            notes = after_context.get("clip_notes", {}).get(check["id"])
            expected = {n["id"]: n for n in check["value"]}
            if not isinstance(notes, list) or any(not isinstance(n, dict) or not isinstance(n.get("id"), str) for n in notes) or len(notes) != len(expected) or {n.get("id") for n in notes} != set(expected) or any(not matches(n, expected.get(n.get("id"), {})) for n in notes):
                errors.append(f"片段 {check['id']} 的音符回读与方案不一致。")
    return errors
