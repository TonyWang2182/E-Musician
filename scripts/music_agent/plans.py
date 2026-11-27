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
from .localization import L, english


class PlanError(ValueError):
    """A proposal cannot safely become an executable plan."""


MAX_ACTIONS = 16
MAX_NOTES = 2000
MAX_SECONDS = 172800
EFFECT_NAMES = {"eq8":"EQ Eight", "compressor":"Compressor", "delay":"Stereo Delay", "reverb":"Reverb", "auto_filter":"Auto Filter"}
EQ_SHAPES = ["bell", "low_shelf", "high_shelf", "high_pass", "low_pass", "notch"]
TRACK_FIELDS = ("name", "kind", "gain_db", "pan", "muted", "solo", "colour")
CLIP_FIELDS = ("kind", "start_seconds", "duration_seconds", "start_beats", "length_beats", "note_count",
               "asset_id", "source_offset", "fade_in_seconds", "fade_out_seconds", "controller_count",
               "warp_enabled", "warp_follow_tempo", "warp_source_bpm", "warp_target_bpm", "warp_speed_ratio", "playback_source_offset")
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
_BAND = {"type":"object", "additionalProperties":False, "required":["enabled","frequency","gain_db","q"],
         "properties":{"enabled":{"type":"boolean"}, "frequency":{"type":"number","minimum":20,"maximum":20000},
                       "gain_db":{"type":"number","minimum":-24,"maximum":24}, "q":{"type":"number","minimum":0.1,"maximum":10},
                       "shape":{"type":"string","enum":EQ_SHAPES}}}
_EFFECT_STATE = {"oneOf":[
    {"type":"object", "additionalProperties":False, "required":["version","type","bands"],
     "properties":{"version":{"enum":[1,2]},"type":{"const":"eq8"},"bands":{"type":"array","minItems":8,"maxItems":8,"items":_BAND}}},
    {"type":"object", "additionalProperties":False, "required":["version","type","threshold_db","ratio","attack_ms","release_ms","makeup_db"],
     "properties":{"version":{"const":1},"type":{"const":"compressor"},
       "threshold_db":{"type":"number","minimum":-60,"maximum":0}, "ratio":{"type":"number","minimum":1,"maximum":20},
       "attack_ms":{"type":"number","minimum":0.1,"maximum":200}, "release_ms":{"type":"number","minimum":10,"maximum":2000},
       "makeup_db":{"type":"number","minimum":-24,"maximum":24}, "dry_wet":{"type":"number","minimum":0,"maximum":1}}},
    {"type":"object", "additionalProperties":False, "required":["version","type","delay_ms","feedback","dry_wet"],
     "properties":{"version":{"const":1},"type":{"const":"delay"},
       "delay_ms":{"type":"number","minimum":1,"maximum":2000},"feedback":{"type":"number","minimum":0,"maximum":0.95},
       "dry_wet":{"type":"number","minimum":0,"maximum":1}}},
    {"type":"object", "additionalProperties":False, "required":["version","type","decay_seconds","damping","dry_wet"],
     "properties":{"version":{"const":1},"type":{"const":"reverb"},
       "decay_seconds":{"type":"number","minimum":0.1,"maximum":8},"damping":{"type":"number","minimum":0,"maximum":1},
       "dry_wet":{"type":"number","minimum":0,"maximum":1}}},
    {"type":"object", "additionalProperties":False, "required":["version","type","mode","frequency_hz","resonance_q","lfo_enabled","lfo_hz","lfo_depth","dry_wet"],
     "properties":{"version":{"const":1},"type":{"const":"auto_filter"},
       "mode":{"type":"string","enum":["low_pass","high_pass"]},"frequency_hz":{"type":"number","minimum":20,"maximum":20000},
       "resonance_q":{"type":"number","minimum":0.5,"maximum":10},"lfo_enabled":{"type":"boolean"},
       "lfo_hz":{"type":"number","minimum":0.05,"maximum":20},"lfo_depth":{"type":"number","minimum":0,"maximum":1},
       "dry_wet":{"type":"number","minimum":0,"maximum":1}}}]}
_ACTIONS = [
    _shape("set_tempo", {"bpm": {"type": "number", "minimum": 20, "maximum": 300}}),
    _shape("rename_track", {"track_id": _ID, "name": _NAME}),
    _shape("create_track", {"kind": {"enum": ["audio", "instrument", "bus"]}, "name": _NAME, "as": _ALIAS}, ("as",)),
    _shape("add_native_effect", {"track_id":_ID, "effect_type":{"enum":["eq8","compressor","delay","reverb","auto_filter"]}, "as":_ALIAS}, ("as",)),
    _shape("set_native_effect", {"track_id":_ID, "device_id":_ID, "state":_EFFECT_STATE}),
    _shape("set_native_effect_parameter", {"track_id":_ID, "device_id":_ID,
           "parameter":{"enum":["frequency","gain_db","q","enabled","shape","threshold_db","ratio","attack_ms","release_ms","makeup_db","dry_wet","delay_ms","feedback","decay_seconds","damping","mode","frequency_hz","resonance_q","lfo_enabled","lfo_hz","lfo_depth"]},
           "value":{"oneOf":[{"type":"number"},{"type":"boolean"},{"type":"string","enum":EQ_SHAPES}]},
           "mode":{"enum":["absolute","delta"]},
           "band":{"type":"integer","minimum":1,"maximum":8}}, ("mode","band")),
    _shape("set_native_pad", {"track_id":_ID,"pad":{"type":"integer","minimum":0,"maximum":15},
           "gain_db":{"type":"number","minimum":-60,"maximum":6},"muted":{"type":"boolean"},
           "attack_ms":{"type":"number","minimum":0.1,"maximum":2000},
           "release_ms":{"type":"number","minimum":1,"maximum":5000},"one_shot":{"type":"boolean"}}, ("gain_db","muted","attack_ms","release_ms","one_shot")),
    _shape("set_native_sampler", {"track_id":_ID,"root_note":{"type":"integer","minimum":0,"maximum":127},
           "start":{"type":"number","minimum":0,"maximum":1},"end":{"type":"number","minimum":0,"maximum":1}}),
    _shape("set_track_gain", {"track_id": _ID, "gain_db": {"type": "number", "minimum": -60, "maximum": 6}}),
    _shape("set_track_pan", {"track_id": _ID, "pan": {"type": "number", "minimum": -1, "maximum": 1}}),
    _shape("set_track_muted", {"track_id": _ID, "muted": {"type": "boolean"}}),
    _shape("set_track_solo", {"track_id": _ID, "solo": {"type": "boolean"}}),
    _shape("set_track_colour", {"track_id": _ID, "colour": {"type": "string", "pattern": "^(|#[0-9A-Fa-f]{6})$",
        "description": "Track colour as #RRGGBB, or an empty string to restore the default. Visual metadata only."}}),
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
CREATIONS = {"create_track", "create_midi_clip", "duplicate_clip", "add_native_effect"}
PLAN_TOOL = {"type": "function", "function": {"name": "propose_plan",
    "description": "Propose one atomic DAW edit batch for user review, NEVER execute. Use exact existing IDs or @alias declared with as on an EARLIER create_track/create_midi_clip/duplicate_clip/add_native_effect. Alias names match [A-Za-z][A-Za-z0-9_-]{0,39}; aliases cannot be reused or referenced forward. EQ8 and compressor state must be complete, retain unchanged parameters and use read_native_effect first for existing devices; to create use add_native_effect then set_native_effect with its @alias. Sampler/Rack edits are not available. Chained creation and explicit MIDI notes are supported; do not invent templates. Duplicate copies one clip immediately after itself, including controllers, and assigns fresh note IDs. trim_clip only shortens within the current clip; MIDI clips containing controllers are not supported for trim in this batch. Beat positions use quarter notes; a bar = numerator * 4 / denominator beats. GUI scope is enforced locally: selected notes never authorize whole-clip changes or unrelated additions; cross-track moves require an authorized destination. New notes require explicit pitch/start/length/velocity/channel. Omit note_ids for all authorized notes of a new clip. Quantization changes starts only and rejects overflow. Do not invent tools or claim you heard audio.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["summary", "actions"],
                   "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                                  "actions": {"type": "array", "minItems": 1, "maxItems": MAX_ACTIONS,
                                              "items": {"oneOf": _ACTIONS}}}}}}

_SCHEMAS = {shape["properties"]["type"]["const"]: shape for shape in _ACTIONS}
PLAN_TOOL["function"]["description"] = PLAN_TOOL["function"]["description"].replace(
    "Sampler/Rack edits are not available.",
    "Sampler/Rack parameter edits require project scope and exactly one set_native_pad or set_native_sampler action per proposal; only already-loaded samples are eligible. No file paths or sample loading.")
PLAN_TOOL["function"]["description"] += " Native EQ/Compressor on the master bus use track_id='master'; this requires project scope."
PLAN_TOOL["function"]["description"] += (" For one effect setting prefer set_native_effect_parameter; the host fills all other values from the authoritative snapshot. "
    "EQ needs band 1 through 8; compressor must omit band. mode absolute sets the stated value; delta adds the stated amount to the current value. "
    "For enabled use a boolean in absolute mode. For a newly added effect refer to its @alias. Multiple parameter actions are allowed in one batch.")
PLAN_TOOL["function"]["description"] += " Stereo Delay uses effect_type='delay', parameters delay_ms (milliseconds), feedback (0 to 0.95) and dry_wet (0 to 1)."
PLAN_TOOL["function"]["description"] += " Reverb uses effect_type='reverb', parameters decay_seconds, damping (0 to 1), and dry_wet (0 to 1)."
PLAN_TOOL["function"]["description"] += " Auto Filter uses effect_type='auto_filter'; mode is low_pass or high_pass, lfo_enabled is boolean, frequency_hz/resonance_q/lfo_hz/lfo_depth/dry_wet are numeric. Mode and lfo_enabled require absolute edits."
PLAN_TOOL["function"]["description"] += " EQ shape is per-band: bell, low_shelf, high_shelf, high_pass, low_pass or notch (absolute only). High/low pass are 12 dB/octave; gain_db is inactive for pass and notch shapes. Sampler/Rack set_native_pad accepts gain_db, muted, attack_ms (0.1..2000), release_ms (1..5000), one_shot (boolean); supply at least one setting, omitted settings preserve the read current values. False one_shot is gate/release on note-off; true plays through note-off. No decay/sustain/loop/slicing controls."
PLAN_TOOL["function"]["description"] += " set_track_colour changes visual track colour without changing sound. Use exact #RRGGBB (muted teal #BFD2CF) or empty string to reset. It requires explicit track selection or project scope, and can follow create_track using its @alias."

def _default_effect(kind):
    if kind == "eq8":
        return {"version":1,"type":"eq8","bands":[{"enabled":True,"frequency":f,"gain_db":0.0,"q":0.7071,
                 "shape":"low_shelf" if i == 0 else "high_shelf" if i == 7 else "bell"}
                for i,f in enumerate((60,120,250,500,1000,2500,6000,12000))]}
    if kind == "compressor":
        return {"version":1,"type":"compressor","threshold_db":-18.0,"ratio":4.0,"attack_ms":10.0,"release_ms":100.0,"makeup_db":0.0,"dry_wet":1.0}
    if kind == "delay":
        return {"version":1,"type":"delay","delay_ms":350.0,"feedback":0.35,"dry_wet":0.35}
    if kind == "reverb":
        return {"version":1,"type":"reverb","decay_seconds":1.8,"damping":0.35,"dry_wet":0.25}
    if kind == "auto_filter":
        return {"version":1,"type":"auto_filter","mode":"low_pass","frequency_hz":1000.0,"resonance_q":0.7071,
                "lfo_enabled":False,"lfo_hz":1.0,"lfo_depth":0.0,"dry_wet":1.0}
    raise PlanError("Unsupported native effect type.")

def validate_effect_state(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") not in (1,2) or (value.get("version")==2 and value.get("type")!="eq8"):
        raise PlanError("Invalid effect state version.")
    kind = value.get("type")
    if kind == "eq8":
        if set(value) != {"version","type","bands"} or not isinstance(value["bands"], list) or len(value["bands"]) != 8:
            raise PlanError("EQ Eight requires all eight bands.")
        bands=[]
        for index,band in enumerate(value["bands"]):
            if not isinstance(band, dict) or not {"enabled","frequency","gain_db","q"} <= set(band) or not set(band) <= {"enabled","frequency","gain_db","q","shape"} or type(band["enabled"]) is not bool:
                raise PlanError("Invalid equalizer band fields.")
            shape = band.get("shape", "low_shelf" if index == 0 else "high_shelf" if index == 7 else "bell")
            if not isinstance(shape,str) or shape not in EQ_SHAPES: raise PlanError("Invalid equalizer filter shape.")
            bands.append({"enabled":band["enabled"], "frequency":_number(band["frequency"],"frequency",20,20000),
                          "gain_db":_number(band["gain_db"],"gain_db",-24,24), "q":_number(band["q"],"q",0.1,10),"shape":shape})
        needs_shapes=any(band["shape"] != ("low_shelf" if i==0 else "high_shelf" if i==7 else "bell") for i,band in enumerate(bands))
        return {"version":2 if needs_shapes else 1,"type":kind,"bands":bands}
    if kind == "compressor":
        ranges={"threshold_db":(-60,0),"ratio":(1,20),"attack_ms":(0.1,200),"release_ms":(10,2000),"makeup_db":(-24,24)}
        if not {"version","type",*ranges} <= set(value) or not set(value) <= {"version","type",*ranges,"dry_wet"}:
            raise PlanError("Compressor parameters are incomplete.")
        return {"version":1,"type":kind,**{key:_number(value[key],key,*limits) for key,limits in ranges.items()},
                "dry_wet":_number(value.get("dry_wet",1),"dry_wet",0,1)}
    if kind == "delay":
        ranges = {"delay_ms":(1,2000), "feedback":(0,0.95), "dry_wet":(0,1)}
        if set(value) != {"version","type",*ranges}:
            raise PlanError("Delay parameters are incomplete.")
        return {"version":1,"type":kind,**{key:_number(value[key],key,*limits) for key,limits in ranges.items()}}
    if kind == "reverb":
        ranges = {"decay_seconds":(0.1,8), "damping":(0,1), "dry_wet":(0,1)}
        if set(value) != {"version","type",*ranges}:
            raise PlanError("Reverb parameters are incomplete.")
        return {"version":1,"type":kind,**{key:_number(value[key],key,*limits) for key,limits in ranges.items()}}
    if kind == "auto_filter":
        ranges={"frequency_hz":(20,20000),"resonance_q":(0.5,10),"lfo_hz":(0.05,20),"lfo_depth":(0,1),"dry_wet":(0,1)}
        if set(value) != {"version","type","mode","lfo_enabled",*ranges}:
            raise PlanError("Filter parameters are incomplete.")
        if not isinstance(value["mode"],str) or value["mode"] not in {"low_pass","high_pass"} or type(value["lfo_enabled"]) is not bool:
            raise PlanError("Invalid filter mode or LFO enable value.")
        return {"version":1,"type":kind,"mode":value["mode"],"lfo_enabled":value["lfo_enabled"],
                **{key:_number(value[key],key,*limits) for key,limits in ranges.items()}}
    raise PlanError("Unsupported native effect type.")

def required_effect_ids(payload):
    return sorted({(a["track_id"],a["device_id"]) for a in payload.get("actions",[])
                   if isinstance(a,dict) and a.get("type") in {"set_native_effect","set_native_effect_parameter"}
                   and isinstance(a.get("track_id"),str) and isinstance(a.get("device_id"),str)
                   and not a["device_id"].startswith("@")})

def required_instrument_track_ids(payload):
    return sorted({a["track_id"] for a in payload.get("actions",[])
                   if isinstance(a,dict) and a.get("type") in {"set_native_pad","set_native_sampler"}
                   and isinstance(a.get("track_id"),str)})


def _text(value: object, field: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise PlanError(f"{field} must be a single-line string containing 1 to {maximum} characters.")
    return value.strip()


def _number(value: object, field: str, low: float, high: float, integer: bool = False) -> float:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise PlanError(f"{field} must be a finite number within {low:g}–{high:g}.")
    if integer and value != int(value):
        raise PlanError(f"{field} must be an integer.")
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
        raise PlanError("Project track snapshot is missing.")
    for track in raw_tracks:
        if not isinstance(track, dict) or not isinstance(track.get("id"), str) or track["id"] in tracks:
            raise PlanError("Invalid project track snapshot. Refresh.")
        tracks[track["id"]] = track
        if not isinstance(track.get("clips", []), list):
            raise PlanError("Invalid project clip snapshot. Refresh.")
        for clip in track.get("clips", []):
            if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or clip["id"] in clips:
                raise PlanError("Invalid project clip snapshot. Refresh.")
            clips[clip["id"]] = (track, clip)
    return tracks, clips


def _valid_notes(notes: object, clip: dict) -> list[dict]:
    if not isinstance(notes, list) or len(notes) != clip.get("note_count"):
        raise PlanError("The complete clip notes have not been read. Refresh before preparing a plan.")
    if len(notes) > MAX_NOTES:
        raise PlanError(f"A request can edit at most {MAX_NOTES} notes.")
    result, ids, channels = [], set(), set()
    for raw in notes:
        if not isinstance(raw, dict) or set(raw) != set(NOTE_FIELDS):
            raise PlanError("Note data fields are incomplete.")
        note = dict(raw)
        note["id"] = _text(note["id"], "note_id")
        if note["id"] in ids:
            raise PlanError("notes ID Duplicate。")
        ids.add(note["id"])
        for field, low, high in (("pitch", 0, 127), ("velocity", 1, 127), ("channel", 1, 16)):
            note[field] = _number(note[field], field, low, high, True)
        note["start_beats"] = _number(note["start_beats"], "start_beats", 0, float(clip["length_beats"]))
        note["length_beats"] = _number(note["length_beats"], "length_beats", 0, float(clip["length_beats"]))
        end = note["start_beats"] + note["length_beats"]
        if end <= note["start_beats"] or end > clip["length_beats"] + 1e-9:
            raise PlanError("Note length is invalid or exceeds clip bounds. It will not be silently truncated.")
        channels.add(note["channel"])
        result.append(note)
    if len(channels) > 1:
        raise PlanError("All notes in one MIDI clip must use the same channel.")
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
                    raise PlanError("A MIDI clip must have positive length and fit within the 48-hour timeline.")
                clip["start_seconds"] = start * 60 / bpm
                clip["duration_seconds"] = length * 60 / bpm
            else:
                start, duration = clip["start_seconds"], clip["duration_seconds"]
                _number(start, "start_seconds", 0, MAX_SECONDS)
                _number(duration, "duration_seconds", 0, MAX_SECONDS)
                if duration <= 0 or start + duration > MAX_SECONDS:
                    raise PlanError("An audio clip must fit within the 48-hour timeline.")



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
        raise PlanError("A plan must contain only summary and actions.")
    result = deepcopy(payload)
    result["summary"] = _text(result["summary"], "summary", 1000)
    actions = result["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise PlanError(f"A plan requires 1 to {MAX_ACTIONS} actions.")
    declared = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("type"), str) or action["type"] not in _SCHEMAS:
            raise PlanError("The plan contains an unsupported action.")
        shape = _SCHEMAS[action["type"]]
        if not set(shape["required"]) <= set(action) or not set(action) <= set(shape["properties"]):
            raise PlanError(f"{action['type']} parameters are missing or contain unknown fields.")
        if "as" in action:
            alias = action["as"]
            if not isinstance(alias, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", alias) is None or alias in declared:
                raise PlanError("A new-object alias is invalid or duplicated. It must start with a letter and contain at most 40 characters.")
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
    native_async = any(a["type"] in {"set_native_pad","set_native_sampler"} for a in prepared["actions"])
    if native_async and len(prepared["actions"]) != 1:
        raise PlanError("Sampler/Drum Rack parameters require a separate asynchronous plan and cannot be mixed with other actions.")
    if not isinstance(context, dict) or not isinstance(context.get("project_id"), str) or type(context.get("revision")) is not int or context["revision"] < 0:
        raise PlanError("Current project identity and revision are missing.")
    if context.get("recording") or context.get("recording_finalizing") or context.get("counting_in"):
        raise PlanError("Edit plans cannot be prepared during recording or count-in.")
    state = deepcopy(context)
    state.setdefault("clip_notes", {})
    tracks, clips = _maps(state)
    original_tracks, original_clips = _maps(context)
    if "master" in tracks: raise PlanError("A track identity conflicts with the reserved master identity.")
    master_track = {"id":"master", "name":"Master", "plugins":state.setdefault("master_plugins",[])}
    if not isinstance(master_track["plugins"],list): raise PlanError("Invalid master device snapshot.")
    effects = {}
    for t in [*tracks.values(), master_track]:
        for p in t.get("plugins", []):
            if not isinstance(p,dict) or not isinstance(p.get("id"),str) or p["id"] in effects:
                raise PlanError("Invalid or duplicate device identity.")
            effects[p["id"]] = (t,p)
    original_ids = set(tracks) | set(clips) | set(effects)
    state.setdefault("native_effects", {})
    touched_effects = set()
    touched_instruments = set()
    state.setdefault("native_instruments", {})
    if any(i.startswith("@") for i in original_ids) or len(tracks) > 64:
        raise PlanError("Invalid project object identity or track count.")
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
            raise PlanError("A new note identity conflicts with an existing object. Prepare a new plan.")
        known_note_ids.add(value)
        return value

    def existing(identifier, mapping, label):
        value = _text(identifier, label)
        if value != identifier or value not in mapping:
            raise PlanError(f"{label} does not exist, was deleted, or its alias was not declared.")
        return mapping[value]

    def note_budget(count):
        nonlocal total_notes
        total_notes += count
        if total_notes > MAX_NOTES:
            raise PlanError(f"A plan supports at most {MAX_NOTES} note operations.")

    def loaded(clip):
        if clip["kind"] != "midi":
            raise PlanError("Note editing requires a MIDI clip.")
        return _valid_notes(state["clip_notes"].get(clip["id"]), clip)

    def count_clip(track, delta):
        track["clip_count"] = track.get("clip_count", len(track.get("clips", []))) + delta

    for index, action in enumerate(prepared["actions"]):
        kind = action["type"]
        if authorizer:
            authorizer(action, state)
        args = {k: deepcopy(v) for k, v in action.items() if k not in ("type", "as")}
        track = None
        if "track_id" in args:
            if args["track_id"] == "master" and kind in {"add_native_effect","set_native_effect","set_native_effect_parameter"}:
                track = master_track
            else:
                track = existing(args["track_id"], tracks, "track_id")
        clip = None
        if "clip_id" in args:
            track, clip = existing(args["clip_id"], clips, "clip_id")
        clip_label = f"{'MIDI' if clip['kind'] == 'midi' else 'Audio'} clip on “{track['name']}” at {clip['start_seconds']:g} s" if clip is not None else ""
        target = existing(args["target_track_id"], tracks, "target_track_id") if "target_track_id" in args else None
        command = {"command": kind, "args": args}
        extra_commands = []
        changed = True
        if kind in CREATIONS:
            alias = action["as"]
            if alias in aliases or alias in original_ids or "@" + alias in original_ids:
                raise PlanError("A new-object alias conflicts with an existing identity.")
            command["as"] = alias
            new_id = "@" + alias
        if kind == "set_tempo":
            if any(t.get("clips_truncated") for t in tracks.values()):
                raise PlanError("Read the full clip range before changing tempo.")
            value = _number(args["bpm"], "bpm", 20, 300)
            old = state["bpm"]
            state["bpm"] = args["bpm"] = value
            changed = not _same(old, value)
            following=0
            for _,audio in clips.values():
                if audio.get("kind")=="audio" and audio.get("warp_enabled") is True and audio.get("warp_follow_tempo") is True:
                    source_bpm=_number(audio.get("warp_source_bpm"),"warp_source_bpm",20,300)
                    scale=old/value;audio["start_seconds"]*=scale;audio["duration_seconds"]*=scale
                    for fade in ("fade_in_seconds","fade_out_seconds"):
                        if fade in audio:audio[fade]*=scale
                    audio.update(warp_target_bpm=value,warp_speed_ratio=value/source_bpm)
                    audio["playback_source_offset"]=audio.get("source_offset",0)/(value/source_bpm)
                    following+=1
            description = f"Tempo: {old:g} → {value:g} BPM. MIDI and {following} tempo-following audio clips update; other audio keeps its speed."
        elif kind == "create_track":
            if args["kind"] not in ("audio", "instrument", "bus"):
                raise PlanError("Track type must be audio, instrument or bus.")
            args["name"] = _text(args["name"], "name")
            if len(tracks) >= 64:
                raise PlanError("A project supports at most 64 tracks.")
            new = {"id": new_id, **args, "gain_db": 0.0, "pan": 0.0, "muted": False,
                   "solo": False, "clips": [], "clip_count": 0, "clips_truncated": False}
            tracks[new_id] = new
            state["tracks"].append(new)
            aliases[alias] = "track"
            description = f"Create {args['kind']} track “{args['name']}” (no plug-in is loaded automatically)"
        elif kind == "add_native_effect":
            effect_type = args.pop("effect_type")
            effect_state = _default_effect(effect_type)
            plugin = {"id":new_id,"name":EFFECT_NAMES[effect_type],
                      "format":"E-musician","is_instrument":False}
            track.setdefault("plugins", []).append(plugin)
            effects[new_id] = (track,plugin)
            state["native_effects"][new_id] = effect_state
            touched_effects.add(new_id)
            aliases[alias] = "effect"
            args["type"] = effect_type
            description = f"Add {plugin['name']} to “{track['name']}” with default settings"
        elif kind in {"set_native_effect", "set_native_effect_parameter"}:
            effect_track, plugin = existing(args["device_id"], effects, "device_id")
            if effect_track["id"] != track["id"] or plugin.get("format") != "E-musician" or plugin.get("is_instrument") is not False:
                raise PlanError("The device does not belong to the specified track or is not an editable native effect.")
            old = validate_effect_state(state["native_effects"].get(args["device_id"]))
            if kind == "set_native_effect_parameter":
                parameter = args["parameter"]
                mode = args.get("mode", "absolute")
                if not isinstance(parameter, str) or not isinstance(mode, str) or mode not in {"absolute", "delta"}:
                    raise PlanError("Parameter edit mode must be absolute or delta.")
                wanted = deepcopy(old)
                if old["type"] == "eq8":
                    if parameter not in {"frequency", "gain_db", "q", "enabled", "shape"}:
                        raise PlanError("This parameter does not belong to EQ Eight.")
                    band = _number(args.get("band"), "band", 1, 8, True)
                    target = wanted["bands"][band - 1]
                else:
                    allowed = {"compressor":{"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db", "dry_wet"},
                               "delay":{"delay_ms","feedback","dry_wet"}, "reverb":{"decay_seconds","damping","dry_wet"},
                               "auto_filter":{"mode","frequency_hz","resonance_q","lfo_enabled","lfo_hz","lfo_depth","dry_wet"}}[old["type"]]
                    if "band" in args or parameter not in allowed:
                        raise PlanError("This parameter does not belong to the current effect or does not support a band index.")
                    target = wanted
                value = args["value"]
                if parameter in {"enabled","lfo_enabled"}:
                    if type(value) is not bool or mode != "absolute":
                        raise PlanError("Band enable edits require absolute mode and a boolean value.")
                    target[parameter] = value
                elif parameter == "shape":
                    if not isinstance(value,str) or value not in EQ_SHAPES or mode != "absolute":
                        raise PlanError("EQ filter shapes require absolute mode and a supported shape.")
                    target[parameter] = value
                elif parameter == "mode":
                    if not isinstance(value,str) or value not in {"low_pass","high_pass"} or mode != "absolute":
                        raise PlanError("Filter mode requires absolute mode and low_pass/high_pass.")
                    target[parameter] = value
                else:
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise PlanError("Effect parameters must be finite numbers.")
                    target[parameter] = target[parameter] + value if mode == "delta" else value
                wanted = validate_effect_state(wanted)
                args = {"track_id": args["track_id"], "device_id": args["device_id"], "state": wanted}
                command = {"command": "set_native_effect", "args": args}
            else:
                wanted = validate_effect_state(args["state"])
            expected_name = EFFECT_NAMES[wanted["type"]]
            if plugin.get("name") != expected_name:
                raise PlanError("The effect type does not match the target device.")
            if old["type"] != wanted["type"]:
                raise PlanError("The effect type cannot be changed.")
            changed = old != wanted
            args["state"] = state["native_effects"][args["device_id"]] = wanted
            touched_effects.add(args["device_id"])
            description = f"Set {expected_name} on “{track['name']}”: {old} → {wanted}"
        elif kind in {"set_native_pad", "set_native_sampler"}:
            inst = state["native_instruments"].get(track["id"])
            if not isinstance(inst,dict) or inst.get("type") not in {"sampler","drum_rack"} or inst.get("load_status") != "ready":
                raise PlanError("Read a ready native sampler or Drum Rack first.")
            if kind == "set_native_sampler":
                if inst["type"] != "sampler": raise PlanError("This device is not a sampler.")
                root = _number(args["root_note"],"root_note",0,127,True)
                start = _number(args["start"],"start",0,1); end = _number(args["end"],"end",0,1)
                if start >= end: raise PlanError("Sample start must be before sample end.")
                pad = 0; old = {k:inst[k] for k in ("root_note","start","end")}
                inst.update(root_note=root,start=start,end=end); args.update(root_note=root,start=start,end=end)
                changed = old != {k:inst[k] for k in old}
                description = f"Sampler root/start/end on “{track['name']}”: {old} → {root}/{start:g}/{end:g}"
            else:
                pad = _number(args["pad"],"pad",0,15,True)
                if inst["type"] == "sampler" and pad != 0: raise PlanError("The sampler has only one sample slot.")
                pads=inst.get("pads",[])
                item=next((p for p in pads if p.get("index") == pad),None)
                if item is None: raise PlanError("The drum pad does not exist.")
                if not set(args) & {"gain_db","muted","attack_ms","release_ms","one_shot"}: raise PlanError("Specify at least one sample parameter.")
                gain = _number(args.get("gain_db",item.get("gain_db")),"gain_db",-60,6)
                muted = args.get("muted",item.get("muted"))
                if type(muted) is not bool: raise PlanError("muted must be a boolean.")
                old={key:item.get(key,default) for key,default in (("gain_db",0.0),("muted",False),("attack_ms",3.0),("release_ms",30.0),("one_shot",inst["type"]=="drum_rack"))}
                desired={**old,"gain_db":gain,"muted":muted}
                for name,low,high in (("attack_ms",0.1,2000),("release_ms",1,5000)):
                    if name in args: desired[name]=_number(args[name],name,low,high)
                if "one_shot" in args:
                    if type(args["one_shot"]) is not bool: raise PlanError("one_shot must be a boolean.")
                    desired["one_shot"]=args["one_shot"]
                item.update(desired); args.update(pad=pad,**desired)
                changed=old != desired
                description=f"Sample slot {pad} on “{track['name']}”: {old} → {desired}"
            if not any(p.get("index") == pad and p.get("sample_sha256") for p in inst.get("pads",[])):
                raise PlanError("Only loaded and ready samples can be edited.")
            touched_instruments.add(track["id"])
        elif kind.startswith("set_track_") or kind == "rename_track":
            field = {"rename_track": "name", "set_track_gain": "gain_db", "set_track_pan": "pan",
                     "set_track_muted": "muted", "set_track_solo": "solo", "set_track_colour": "colour"}[kind]
            value = args[field]
            if field == "name":
                value = _text(value, "name")
            elif field == "colour":
                if not isinstance(value, str) or (value != "" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value)):
                    raise PlanError("Track colour must be a six-digit #RRGGBB value, or an empty string to restore the default.")
                value = value.upper()
            elif field in ("muted", "solo"):
                if type(value) is not bool:
                    raise PlanError(f"{field} must be a boolean.")
            else:
                value = _number(value, field, *({"gain_db": (-60, 6), "pan": (-1, 1)}[field]))
            old = track.get(field, "") if field == "colour" else track[field]
            track[field] = args[field] = value
            changed = not _same(old, value, field)
            description = (f"Track “{track['name']}” colour: {old or 'Default'} → {value or 'Default'} (sound unchanged)" if field == "colour"
                           else f"Track “{track['name']}” {field}: {old} → {value}")
        elif kind in {"create_midi_clip", "duplicate_clip"}:
            if sum(t.get("clip_count", len(t.get("clips", []))) for t in tracks.values()) >= 4096:
                raise PlanError("A project supports at most 4096 clips.")
            if kind == "create_midi_clip":
                if track["kind"] != "instrument":
                    raise PlanError("MIDI clips can only be created on instrument tracks.")
                start = _number(args["start_beats"], "start_beats", 0, MAX_SECONDS * state["bpm"] / 60)
                length = _number(args["length_beats"], "length_beats", 0, MAX_SECONDS * state["bpm"] / 60)
                args.update(start_beats=start, length_beats=length)
                new = {"id": new_id, "kind": "midi", "start_beats": start, "length_beats": length, "note_count": 0}
                state["clip_notes"][new_id] = []
                bars = length / (state.get("numerator", 4) * 4 / state.get("denominator", 4))
                description = f"Create an empty MIDI clip on “{track['name']}” at quarter-note beat {start:g}: {length:g} beats / {bars:g} bars"
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
                description = f"Duplicate {english(clip_label)} at {new['start_seconds']:g} s, directly after the original (controllers preserved)"
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
                raise PlanError("Moving between tracks requires a destination track of the same type.")
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
            description = f"{english(clip_label)}: {old:g} → {value:g} s, destination “{target['name']}”"
        elif kind == "trim_clip":
            start = _number(args["start_seconds"], "start_seconds", 0, MAX_SECONDS)
            end = _number(args["end_seconds"], "end_seconds", 0, MAX_SECONDS)
            old_start, old_end = clip["start_seconds"], clip["start_seconds"] + clip["duration_seconds"]
            if start < old_start or end > old_end or end <= start:
                raise PlanError("Trim can only retain a positive interval within the current clip. It does not silently expand it.")
            changed = not _same(start, old_start) or not _same(end, old_end)
            args.update(start_seconds=start, end_seconds=end)
            if clip["kind"] == "midi":
                if clip.get("controller_count", 0) != 0:
                    raise PlanError("Agent trimming does not support clips containing MIDI controllers. Trim manually in the DAW to preserve and verify boundary state.")
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
                ratio=_number(clip.get("warp_speed_ratio",1.),"warp_speed_ratio",1/15,15)
                clip["source_offset"] = clip.get("source_offset", 0.0) + (start-old_start)*ratio
                if "playback_source_offset" in clip:clip["playback_source_offset"]=clip["source_offset"]/ratio
                duration = end-start
                clip["fade_in_seconds"] = min(clip.get("fade_in_seconds", 0.0), duration)
                clip["fade_out_seconds"] = min(clip.get("fade_out_seconds", 0.0), duration-clip["fade_in_seconds"])
            clip.update(start_seconds=start, duration_seconds=end-start)
            description = f"Trim {english(clip_label)}: [{old_start:g}, {old_end:g}] → [{start:g}, {end:g}] s (notes outside the range removed, boundary notes shortened)"
        elif kind == "delete_clip":
            command = {"command": "delete_clips", "args": {"clip_ids": [clip["id"]]}}
            count_clip(track, -1)
            track["clips"].remove(clip)
            clips.pop(clip["id"])
            state["clip_notes"].pop(clip["id"], None)
            touched_notes.discard(clip["id"])
            preserved_notes.discard(clip["id"])
            deleted_clips.add(clip["id"])
            description = f"Delete {english(clip_label)} (undoable; source file retained)"
        else:
            notes = loaded(clip)
            upsert, delete_ids = [], []
            if kind == "add_notes":
                raw_notes = args["notes"]
                if not isinstance(raw_notes, list) or not 1 <= len(raw_notes) <= MAX_NOTES:
                    raise PlanError("Added notes must be a nonempty list with at most 2000 entries.")
                note_budget(len(raw_notes))
                for n, raw in enumerate(raw_notes):
                    if not isinstance(raw, dict) or set(raw) != set(NOTE_FIELDS)-{"id"}:
                        raise PlanError("Added notes require explicit pitch, start, length, velocity and channel. IDs are generated locally.")
                    upsert.append({"id": fresh_note(index, n), **raw})
                notes.extend(upsert)
                clip["note_count"] = len(notes)
                detail = f"Add {len(upsert)} specified notes"
                selected = {n["id"] for n in upsert}
            else:
                selected = args.get("note_ids", [note["id"] for note in notes])
                if not isinstance(selected, list) or not selected or len(selected) > MAX_NOTES or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
                    raise PlanError("A nonempty list of unique note IDs is required. Empty clips have no editable notes.")
                selected = set(selected)
                if not selected <= {note["id"] for note in notes}:
                    raise PlanError("The specified note no longer exists. Read the clip again; copied clips have new note identities.")
                note_budget(len(selected))
                if kind == "delete_notes":
                    delete_ids = sorted(selected)
                    notes = [n for n in notes if n["id"] not in selected]
                    clip["note_count"] = len(notes)
                    detail = f"Delete {len(delete_ids)} notes"
                else:
                    if kind == "transpose_notes":
                        amount = _number(args["semitones"], "semitones", -127, 127, True)
                        detail = f"Transpose {amount:+d} semitones"
                    elif kind == "set_note_velocity":
                        amount = _number(args["velocity"], "velocity", 1, 127, True)
                        detail = f"Set velocity to {amount}"
                    elif kind == "set_note_length":
                        amount = _number(args["length_beats"], "length_beats", 0, clip["length_beats"])
                        detail = f"Set length to {amount:g} quarter-note beats"
                    elif kind == "move_notes":
                        amount = _number(args["delta_beats"], "delta_beats", -clip["length_beats"], clip["length_beats"])
                        detail = f"Move notes {amount:+g} quarter-note beats"
                    else:
                        denominator = _number(args["grid_denominator"], "grid_denominator", 1, 16384, True)
                        if denominator & (denominator-1):
                            raise PlanError("The grid denominator must be a power of two between 1 and 16384.")
                        amount = 4/denominator
                        detail = f"Quantize starts to 1/{denominator} (lengths preserved)"
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
            description = f"{english(clip_label)}: {english(detail)}; changed {len(upsert)+len(delete_ids)} of {len(selected)} selected notes"
        _validate_timeline(state)
        if changed:
            commands.extend([command, *extra_commands])
            changes.append(description)
    # Native result references only bind objects that survive the atomic batch.
    # Reject an otherwise effective proposal before publishing an unusable plan.
    for alias, object_kind in aliases.items():
        if "@" + alias not in ({"track":tracks, "clip":clips, "effect":effects}[object_kind]):
            raise PlanError("An object created or copied in this plan is deleted in the same batch. Remove the cancelling actions.")
    effective = set(tracks) != set(original_tracks) or set(clips) != set(original_clips) or not _same(state["bpm"], context["bpm"])
    effective |= any(not _same(track.get(field), original_tracks[tid].get(field), field)
                     for tid, track in tracks.items() if tid in original_tracks for field in TRACK_FIELDS)
    effective |= any(pair[0]["id"] != original_clips[cid][0]["id"] or
                     any(not _same(pair[1].get(field), original_clips[cid][1].get(field), field) for field in CLIP_FIELDS)
                     for cid, pair in clips.items() if cid in original_clips)
    effective |= any(state["clip_notes"].get(cid) != context.get("clip_notes", {}).get(cid) for cid in touched_notes)
    effective |= any(did not in context.get("native_effects", {}) or state["native_effects"][did] != context["native_effects"][did] for did in touched_effects)
    effective |= any(state["native_instruments"][tid] != context.get("native_instruments",{}).get(tid) for tid in touched_instruments)
    if not allow_noop and (not commands or not effective):
        raise PlanError("All values already match the request. No changes are needed.")
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
    for did in sorted(touched_effects):
        checks.append({"kind":"effect", "id":did, "track_id":effects[did][0]["id"], "value":state["native_effects"][did]})
    for tid in sorted(touched_instruments):
        checks.append({"kind":"native_instrument", "id":tid, "value":state["native_instruments"][tid]})
    return {"summary": prepared["summary"], "commands": commands, "changes": changes, "checks": checks,
            "actions": prepared["actions"], "aliases": aliases, "baseline_ids": sorted(original_ids),
            "project_id": context["project_id"], "revision": context["revision"], "note_clip_ids": readback_notes,
            "note_previews": note_previews, "execution_kind":"native_async" if native_async else "batch"}


def resolve_plan_refs(plan: dict, refs: object) -> dict:
    """Bind postconditions to native result IDs; never rewrite approved commands.

    A missing/extra/colliding binding is verification failure AFTER commit, not
    permission to retry the batch. The runtime must retain the available Undo.
    """
    aliases = plan.get("aliases", {})
    if not aliases:
        if refs not in (None, {}):
            raise PlanError("The DAW returned new-object references outside the plan.")
        return deepcopy(plan)
    if not isinstance(refs, dict) or set(refs) != set(aliases):
        raise PlanError("The DAW did not return complete matching new-object references. Changes may have been applied. Check or undo them.")
    values = list(refs.values())
    if any(not isinstance(v, str) or not v or len(v) > 200 or v.startswith("@") or any(ord(c)<32 for c in v) for v in values) or len(set(values)) != len(values) or set(values) & set(plan.get("baseline_ids", [])):
        raise PlanError("DAW new-object references are invalid, duplicated or conflict with existing objects.")
    result = deepcopy(plan)
    def resolve(value):
        if isinstance(value, str) and value.startswith("@"):
            if value[1:] not in refs:
                raise PlanError("The plan contains unresolved object references.")
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
        return ["The verification baseline does not match the approved plan."]
    if after_context.get("project_id") != plan["project_id"]:
        return ["Project identity changed after execution."]
    if plan.get("aliases") and set(plan.get("refs", {})) != set(plan["aliases"]):
        return ["New-object reference bindings are missing after execution."]
    try:
        tracks, clips = _maps(after_context)
    except (PlanError, TypeError):
        return ["Invalid snapshot after execution."]
    errors = []
    def matches(actual, expected):
        return all(key in actual and _same(actual[key], value, key) for key, value in expected.items())
    def effect_equal(a,b):
        if isinstance(a,dict) and isinstance(b,dict):
            return a.keys() == b.keys() and all(effect_equal(a[k],b[k]) for k in a)
        if isinstance(a,list) and isinstance(b,list):
            return len(a) == len(b) and all(effect_equal(x,y) for x,y in zip(a,b))
        if type(a) in (int,float) and type(b) in (int,float):
            return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=2e-7,abs_tol=2e-5)
        return _same(a,b,"gain_db")
    for check in plan.get("checks", []):
        kind = check["kind"]
        if kind == "bpm" and not _same(after_context.get("bpm"), check["value"]):
            errors.append("Tempo readback does not match the plan.")
        elif kind == "track_count" and len(tracks) != check["value"]:
            errors.append("Track count readback does not match the plan.")
        elif kind == "track":
            track = tracks.get(check["id"])
            if track is None or not matches(track, check["value"]) or track.get("clip_count", len(track.get("clips", []))) != check["clip_count"]:
                errors.append(f"tracks {check['id']} readback does not match the plan.")
        elif kind == "clip":
            pair = clips.get(check["id"])
            if pair is None or pair[0]["id"] != check["track_id"] or not matches(pair[1], check["value"]):
                errors.append(f"Clip {check['id']} readback does not match the plan.")
        elif kind == "absent_clip" and check["id"] in clips:
            errors.append(f"Clip {check['id']} was not deleted as planned.")
        elif kind == "notes":
            notes = after_context.get("clip_notes", {}).get(check["id"])
            expected = {n["id"]: n for n in check["value"]}
            if not isinstance(notes, list) or any(not isinstance(n, dict) or not isinstance(n.get("id"), str) for n in notes) or len(notes) != len(expected) or {n.get("id") for n in notes} != set(expected) or any(not matches(n, expected.get(n.get("id"), {})) for n in notes):
                errors.append(f"Clip {check['id']} note readback does not match the plan.")
        elif kind == "effect":
            track = tracks.get(check["track_id"])
            plugins = after_context.get("master_plugins",[]) if check["track_id"] == "master" else track.get("plugins", []) if track else []
            actual = after_context.get("native_effects", {}).get(check["id"])
            try:
                actual = validate_effect_state(actual)
                expected = validate_effect_state(check["value"])
                ok = effect_equal(actual, expected)
            except PlanError:
                ok = False
            if not any(p.get("id") == check["id"] and p.get("format") == "E-musician" and p.get("is_instrument") is False
                       and p.get("name") == EFFECT_NAMES.get(check["value"]["type"]) for p in plugins) or not ok:
                errors.append(f"devices {check['id']} type or parameter readback does not match the plan.")
        elif kind == "native_instrument":
            actual = after_context.get("native_instruments", {}).get(check["id"])
            if not effect_equal(actual,check["value"]):
                errors.append(f"tracks {check['id']} sampler/Drum Rack readback does not match the plan.")
    return errors
