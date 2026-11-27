"""Bounded hybrid-analysis tools, scopes and review plans.

The LLM sees identities and small summaries, never local filenames or PCM. A
candidate is immutable; only the host may turn it into authoritative music.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re
from .selection import ScopeError, assert_scope_unchanged
from .compute import route_arguments, available_routes, safe_route_fields, MODEL_ID
from audio_analysis.common import PARAMETERS as ANALYSIS_PARAMETERS
from audio_analysis.common import OPTIONS as ANALYSIS_OPTIONS
from audio_analysis.common import INSTRUMENT_RANGES

from .localization import L

KINDS = {"separate": "Separate", "transcribe": "Audio to MIDI", "chords": "Chord detection", "beats": "Beats / Tempo", "score": "Music analysis"}
COMMANDS = {"get_analysis_capabilities", "start_analysis", "get_analysis_job",
            "get_analysis_result", "cancel_analysis_job", "accept_analysis_result"}
TERMINAL = {"ready", "applied", "failed", "cancelled", "stale", "interrupted"}
SOURCE_FIELDS = {"project_id", "clip_id", "asset_id", "track_id", "clip_timeline_start",
                 "clip_source_offset", "clip_duration", "bpm", "range_start_seconds",
                 "duration_seconds", "timeline_start", "sample_rate", "source_sha256", "input_role", "warp_speed_ratio"}
ITEM_FIELDS = {"name", "sample_rate", "channels", "duration_seconds", "sha256", "pitch",
               "start_seconds", "duration_seconds", "end_seconds", "velocity", "channel", "label", "raw_label", "score", "uncertain", "time_seconds", "is_downbeat",
               "track_id", "instrument", "program", "is_drum", "type"}
COMPONENTS = {"notes", "chords", "beats", "structure"}
SUMMARY_LIMITS = {"track_count": 64, "note_count": 100000, "controller_count": 100000, "program_change_count": 64,
                  "chord_count": 10000, "beat_count": 10000, "annotation_count": 10000}

def _tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
                       "additionalProperties": False}}}

ANALYSIS_TOOLS = [
    _tool("start_audio_analysis", "Analyze the selected real audio using the ready host default model and execution location; do not ask again for BPM or model. execution can specify local/cloud; model_id must come from analysis_capabilities and an explicit choice must not be silently replaced. Cloud uploads only selected audio. separate returns four/six stems according to model capability; transcribe uses Basic Pitch, piano TransKun or multi-instrument MuScriptor; chords returns chords; score returns SheetSage2 melody/chord/beat/structure candidates. For beats use propose_beat_application; otherwise propose_analysis_import. This does not modify the project or BPM. Times are clip-relative seconds. Wait locally without starting duplicate jobs.",
          {"clip_id": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
           "execution": {"type": "string", "enum": ["auto", "local", "cloud"], "description": "Omit to use the host default. Preserve an explicit local or cloud request."},
           "model_id": {"type": "string", "maxLength": 120, "description": "Use only a real model_id from the capability list. Omit when unspecified."},
           "start_seconds": {"type": "number", "minimum": 0},
           "duration_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 600},
           "parameters": {"type": "object", "description": "Omit or pass {} for cloud models with fixed parameters. Local options depend on type: separate supports stems=4/6, quality=fast/quality and segment_seconds; transcribe supports instrument=auto/piano/bass/guitar/vocals and pitch bounds; chords supports vocabulary=triads/extended; beats supports meter=auto/3/4/4/4. instrument is only a local pitch-range preset.",
               "properties": {**{key: {"type": "integer" if key in {"min_pitch", "max_pitch", "stems"} else "number", "minimum": bounds[0], "maximum": bounds[1], **({"enum": [4, 6]} if key == "stems" else {})}
                              for parameters in ANALYSIS_PARAMETERS.values() for key, bounds in parameters.items()},
                              **{key: {"type": "string", "enum": list(choices)} for options in ANALYSIS_OPTIONS.values() for key, choices in options.items()}}, "additionalProperties": False}}, ["clip_id", "kind"]),
    _tool("read_audio_analysis", "Read a real analysis job and up to 100 candidate items. Provide exactly one of job_id or result_id; offset paginates results. ready means a candidate is complete; applied means it was added to the project.", {
        "job_id": {"type": "string"}, "result_id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "component": {"type": "string", "enum": sorted(COMPONENTS), "description": "Choose the score-analysis component to paginate: notes by default, or chords/beats/structure."}}, []),
    _tool("cancel_audio_analysis", "Cancel a running local or cloud analysis job. This does not delete source audio or project data. Cloud cancellation is complete only when remote_cancel_confirmed is true.", {"job_id": {"type": "string"}}, ["job_id"]),
    _tool("propose_analysis_import", "Propose a candidate import for user review in a separate call. Reference only a completed real result_id, never arbitrary paths or note arrays. Preserve source audio. Separation creates audio tracks, transcription creates MIDI tracks, and chords create label regions.", {
        "result_id": {"type": "string"}, "summary": {"type": "string", "maxLength": 500}}, ["result_id", "summary"]),
    _tool("read_chord_regions", "Read up to 100 chord labels already imported into the project. clip_id filters by real analysis source. Selection scope requires the selected source audio clip_id; only project scope may omit it. Use read_audio_analysis for candidates not yet imported.", {
        "clip_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, []),
    _tool("propose_chord_edit", "Propose an existing chord-label edit separately for confirmation. Times are absolute project seconds. Preserve original model labels or explicit user corrections, including extended/slash chords and unknown labels. Maximum 128 characters without control characters. Missing confidence is not high confidence. This does not generate MIDI. Selection scope requires source clip_id; obtain region_id with read_chord_regions first.", {
        "region_id": {"type": "string"}, "clip_id": {"type": "string"}, "label": {"type": "string"},
        "start_seconds": {"type": "number", "minimum": 0}, "end_seconds": {"type": "number", "exclusiveMinimum": 0},
        "summary": {"type": "string", "maxLength": 500}}, ["region_id", "summary"]),
]

def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 200 or value.startswith("@") or any(ord(c) < 32 for c in value) or "/" in value or "\\" in value:
        raise ValueError("Invalid analysis object ID.")
    return value

def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Invalid analysis time range.")
    return float(value)

def safe_text(value, maximum=300):
    value = str(value or "")[:maximum]
    # Paths may occur in runtime errors. Neither providers nor the web page need
    # environment locations; the local worker log retains the precise detail.
    value = re.sub(r"(?i)[a-z]:[\\/][^\r\n]*", "[local path]", value)
    value = re.sub(r"(?:\\\\|/home/|/Users/|/tmp/|/root/|/mnt/|/var/)[^\s]*", "[local path]", value)
    value = re.sub(r"(?:hf_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9_-]{12,})", "[credential hidden]", value)
    return value

def safe_capabilities(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), list):
        return {"providers": [], "available": False}
    providers = []
    for item in raw["providers"]:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or item["kind"] not in KINDS:
            continue
        provider = {"kind": item["kind"], "available": item.get("available") is True,
            "model_id": safe_text(item.get("model_id"), 100), "version": safe_text(item.get("version"), 80),
            "detail": safe_text(item.get("detail")), "experimental": item.get("experimental", True) is True,
            "execution": item.get("execution") if isinstance(item.get("execution"), str) and item["execution"] in {"local", "cloud"} else "local",
            "default": item.get("default") is True}
        for field in ("multi_instrument", "controllers", "drums"):
            if field in item: provider[field] = item[field] is True
        if type(item.get("max_duration_seconds")) in (int, float):
            provider["max_duration_seconds"] = min(600, number(item["max_duration_seconds"], .001, 172800))
        if isinstance(item.get("stems"), list):
            provider["stems"] = [n for n in item["stems"] if type(n) is int and n in (4, 6)]
        providers.append(provider)
    def options(key, allowed):
        values = raw.get(key, [])
        if not isinstance(values, list): return []
        return list(dict.fromkeys(v for v in values[:32] if isinstance(v, str) and v in allowed))
    return {"providers": providers, "available": any(p["available"] for p in providers),
            "separation_six_stems": raw.get("separation_six_stems") is True,
            "separation_quality_modes": options("separation_quality_modes", {"fast", "quality"}),
            "transcription_instruments": options("transcription_instruments", ANALYSIS_OPTIONS["transcribe"]["instrument"]),
            "chord_vocabularies": options("chord_vocabularies", {"triads", "extended"}),
            "max_duration_seconds": min(600, number(raw.get("max_duration_seconds", 600), 1, 172800)),
            "execution_modes": options("execution_modes", {"local", "cloud", "auto"})}

def safe_summary(raw):
    if not isinstance(raw, dict): return {}
    result = {}
    for key, maximum in SUMMARY_LIMITS.items():
        if key in raw:
            value = raw[key]
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("Candidate summary counts are invalid or exceed the project budget.")
            result[key] = value
    return result

def safe_item(item):
    strings = {"name", "label", "raw_label", "instrument", "track_id", "type", "sha256"}
    booleans = {"uncertain", "is_downbeat", "is_drum"}
    result = {}
    for key, value in item.items():
        if key not in ITEM_FIELDS: continue
        if key in strings:
            if not isinstance(value, str): raise ValueError("Invalid analysis candidate text field.")
            result[key] = safe_text(value, 128)
        elif key in booleans:
            if type(value) is not bool: raise ValueError("Invalid analysis candidate state field.")
            result[key] = value
        elif key == "score" and value is None:
            result[key] = None
        else:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid analysis candidate numeric field.")
            result[key] = value
    return result

def import_track_count(result):
    if result["kind"] == "separate": return result["total"]
    if result["kind"] in {"transcribe", "score"}:
        return safe_summary(result.get("summary")).get("track_count", 1 if result["kind"] == "transcribe" else 0)
    return 0

def safe_job(raw):
    if not isinstance(raw, dict):
        raise ValueError("Invalid analysis job receipt.")
    result = {key: deepcopy(raw[key]) for key in ("job_id", "id", "result_id", "clip_id", "kind", "status", "progress", "receipt", "operation") if key in raw}
    for field in ("phase", "detail", "error", "summary"):
        if field in raw:
            result[field] = safe_text(raw[field], 500)
    if isinstance(result.get("receipt"), dict):
        result["receipt"] = {k: deepcopy(result["receipt"][k]) for k in ("result_id", "applied", "track_ids", "clip_ids", "chord_ids", "revision") if k in result["receipt"]}
    if isinstance(raw.get("source"), dict):
        result["source"] = {k: deepcopy(v) for k, v in raw["source"].items() if k in SOURCE_FIELDS}
    if isinstance(raw.get("summary"), dict):
        result["summary"] = {k: deepcopy(v) for k, v in raw["summary"].items() if k in {"kind", "total"}}
        result["summary"].update(safe_summary(raw["summary"]))
    result.update(safe_route_fields(raw))
    result["remote_status"] = raw.get("remote_status") if isinstance(raw.get("remote_status"), str) and raw["remote_status"] in {"cancelled", "cancelling", "unconfirmed"} else "unconfirmed"
    result["remote_cancel_confirmed"] = raw.get("remote_cancel_confirmed") is True and result["remote_status"] == "cancelled"
    if "parameters" in raw:
        result["parameters"] = validate_parameters(raw.get("kind"), raw["parameters"])
    return result

def safe_result(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str) or raw["kind"] not in KINDS:
        raise ValueError("Invalid analysis result type.")
    result = {key: deepcopy(raw[key]) for key in ("result_id", "kind", "total", "offset", "result_hash", "applied", "present_in_project", "score_kind", "stale") if key in raw}
    identifier(result.get("result_id"))
    if type(result.get("total")) is not int or not 0 <= result["total"] <= 100000:
        raise ValueError("Analysis candidate count is invalid or exceeds the project budget.")
    result["source"] = {k: deepcopy(v) for k, v in (raw.get("source") or {}).items() if k in SOURCE_FIELDS}
    result["model"] = {k: safe_text(v, 150) for k, v in (raw.get("model") or {}).items()
                       if k in {"id", "model_id", "version", "weight_sha256", "provider", "license_status"}}
    items = raw.get("items", [])
    if not isinstance(items, list) or len(items) > 100 or any(not isinstance(i, dict) for i in items):
        raise ValueError("Analysis candidate pagination exceeds the budget.")
    result["items"] = [safe_item(item) for item in items]
    result["summary"] = safe_summary(raw.get("summary"))
    result.update(safe_route_fields(raw))
    if isinstance(raw.get("component"), str) and raw["component"] in COMPONENTS: result["component"] = raw["component"]
    tracks = raw.get("midi_tracks", [])
    if not isinstance(tracks, list) or len(tracks) > 64 or any(not isinstance(t, dict) for t in tracks):
        raise ValueError("Invalid MIDI track summary.")
    result["midi_tracks"] = []
    for track in tracks:
        clean = {k: safe_text(v, 128) for k, v in track.items() if k in {"id", "track_id", "name", "instrument", "velocity_source"}}
        for key, maximum in (("note_count", 100000), ("controller_count", 100000), ("program", 127)):
            if key in track:
                if type(track[key]) is not int or not 0 <= track[key] <= maximum:
                    raise ValueError("Invalid MIDI track summary count.")
                clean[key] = track[key]
        if "channel" in track:
            if type(track["channel"]) is not int or not 1 <= track["channel"] <= 16:
                raise ValueError("Invalid MIDI track summary channel.")
            clean["channel"] = track["channel"]
        if "is_drum" in track: clean["is_drum"] = track["is_drum"] is True
        result["midi_tracks"].append(clean)
    result["notes_only"] = result["kind"] == "transcribe" and not result["summary"].get("controller_count", 0)
    result["parameters"] = validate_parameters(result["kind"], raw.get("parameters", {}))
    if isinstance(raw.get("limitations"), list):
        result["limitations"] = [safe_text(value, 300) for value in raw["limitations"][:8] if isinstance(value, str)]
    if result["kind"] == "beats":
        from .tempo import safe_tempo
        result["tempo"] = safe_tempo(raw.get("tempo"))
    return result

def validate_parameters(kind, parameters):
    if not isinstance(kind, str) or kind not in KINDS or not isinstance(parameters, dict) or set(parameters)-(set(ANALYSIS_PARAMETERS.get(kind, {})) | set(ANALYSIS_OPTIONS.get(kind, {}))):
        raise ValueError("These parameters are not supported for this analysis type.")
    values = {}
    for key, value in parameters.items():
        if key in ANALYSIS_OPTIONS[kind]:
            if not isinstance(value, str) or value not in ANALYSIS_OPTIONS[kind][key]:
                raise ValueError("Unsupported analysis option.")
            values[key] = value
            continue
        bounds = ANALYSIS_PARAMETERS[kind][key]
        values[key] = number(value, bounds[0], bounds[1])
        if key in {"min_pitch", "max_pitch", "stems"}:
            if value != int(value): raise ValueError("Pitch bounds must be integer MIDI pitches.")
            values[key] = int(value)
        if key == "stems" and value not in (4, 6):
            raise ValueError("Separation supports four or six stems.")
    if kind == "transcribe":
        low, high = INSTRUMENT_RANGES[values.get("instrument", "auto")]
        if values.get("min_pitch", low) > values.get("max_pitch", high):
            raise ValueError("Minimum pitch cannot exceed maximum pitch.")
    return values

def authorize_start(context, frozen, args):
    """Resolve omitted range to intersection of source clip and frozen scope."""
    assert_scope_unchanged(frozen, context)
    if not isinstance(args, dict) or set(args) - {"clip_id", "kind", "start_seconds", "duration_seconds", "parameters", "execution", "model_id"} or not {"clip_id", "kind"} <= set(args):
        raise ValueError("Invalid analysis parameters; only selected clips, analysis type and time range are accepted.")
    cid = identifier(args["clip_id"])
    kind = args["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Unsupported analysis type. Read the host capability list.")
    parameters = validate_parameters(kind, args.get("parameters", {}))
    route = route_arguments(args)
    cloud_model = route.get("model_id", "").startswith(("scnet", "transkun", "chordmini", "muscriptor", "sheetsage2"))
    if (route.get("execution") == "cloud" or cloud_model) and parameters and not (kind == "separate" and parameters == {"stems": 4}):
        raise ValueError("Cloud models use fixed validated parameters. Omit local pitch-range, threshold and quality parameters.")
    owner, clip = next(((t, c) for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("id") == cid), (None, None))
    if not clip or clip.get("kind") != "audio":
        raise ScopeError("Select a real audio clip. MIDI clips cannot be used as audio analysis input.")
    explicit_instrument = "piano" if route.get("model_id", "").startswith("transkun") else parameters.get("instrument")
    role = clip.get("analysis_role")
    if kind == "transcribe" and explicit_instrument in (None, "auto") and isinstance(role, str) and role in INSTRUMENT_RANGES:
        validate_parameters(kind, {**parameters, "instrument": role})
    multi_instrument = route.get("model_id", "").startswith("muscriptor") and route.get("execution") != "local"
    if kind == "transcribe" and not multi_instrument and (clip.get("analysis_role") == "drums" or (clip.get("analysis_role") == "other" and explicit_instrument not in {"piano", "bass", "guitar", "vocals"})):
        raise ScopeError("Pitched transcription does not support drums. Select an instrument range for a mixed other stem first.")
    clip_start = number(clip.get("start_seconds"), 0, 172800)
    clip_length = number(clip.get("duration_seconds"), 0.000001, 172800)
    lower, upper = 0.0, clip_length
    if frozen["mode"] != "project":
        selection = frozen["selection"]
        if selection.get("focus") == "piano_roll":
            raise ScopeError("A note selection cannot authorize audio analysis. Select an audio clip first.")
        if frozen["mode"] == "clip":
            allowed = cid == selection.get("active_clip_id")
        else:
            chosen = selection.get("clip_ids", [])
            tracks = selection.get("track_ids", [])
            if not tracks and selection.get("focus") == "track":
                tracks = [selection.get("active_track_id")]
            allowed = cid in chosen or (not chosen and owner["id"] in tracks)
            timed = selection.get("time_range") or {}
            if timed.get("active"):
                lower = max(0, timed["start_seconds"] - clip_start)
                upper = min(clip_length, timed["end_seconds"] - clip_start)
        if not allowed or upper <= lower:
            raise ScopeError("The audio analysis target is outside the authorized selection.")
    start = number(args.get("start_seconds", lower), 0, 172800)
    length = number(args.get("duration_seconds", upper-start), 0.000001, 600)
    if start < lower - 1e-9 or start + length > upper + 1e-9:
        raise ScopeError("The analysis range exceeds the clip or confirmed time selection.")
    request = {"clip_id": cid, "kind": kind, "start_seconds": start, "duration_seconds": length}
    request.update(route)
    if "parameters" in args: request["parameters"] = parameters
    return request

def authorize_result(context, frozen, result):
    source = result.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("The candidate belongs to another project and cannot be imported.")
    request = {"clip_id": source.get("clip_id"), "kind": result["kind"],
               "start_seconds": source.get("range_start_seconds"), "duration_seconds": source.get("duration_seconds"),
               "parameters": result.get("parameters", {})}
    request.update(safe_route_fields(result))
    if "model_id" not in request and isinstance(result.get("model"), dict):
        candidate_id = result["model"].get("id", result["model"].get("model_id", ""))
        if isinstance(candidate_id, str) and MODEL_ID.fullmatch(candidate_id): request["model_id"] = candidate_id
    authorize_start(context, frozen, request)
    clip = next(c for t in context["tracks"] for c in t.get("clips", []) if c["id"] == source["clip_id"])
    for a, b in ((context.get("bpm"), source.get("bpm")), (clip.get("start_seconds"), source.get("clip_timeline_start")),
                 (clip.get("duration_seconds"), source.get("clip_duration"))):
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > 1e-8:
            raise ScopeError("The candidate source position, length or tempo changed. Analyze again in the DAW.")
    if "asset_id" in clip and clip["asset_id"] != source.get("asset_id"):
        raise ScopeError("The candidate source asset was replaced. Analyze again.")
    offset_key="playback_source_offset" if "warp_speed_ratio" in source and "playback_source_offset" in clip else "source_offset"
    if offset_key in clip and abs(number(clip[offset_key], 0, 172800) - number(source.get("clip_source_offset"), 0, 172800)) > 1e-8:
        raise ScopeError("The candidate source trim changed. Analyze again.")
    if "warp_speed_ratio" in source and abs(number(clip.get("warp_speed_ratio",1),1/15,15)-number(source["warp_speed_ratio"],1/15,15))>1e-8:
        raise ScopeError("The candidate source Warp changed. Analyze again.")

def authorize_cancel(context, frozen, job):
    """GUI and Agent jobs share scope, but completed/import operations do not."""
    assert_scope_unchanged(frozen, context)
    if not isinstance(job, dict) or not isinstance(job.get("kind"), str) or job["kind"] not in KINDS or job.get("status") not in {"queued", "preparing", "uploading", "loading", "running", "postprocessing", "downloading", "validating", "cancelling"} or job.get("operation") == "import":
        raise ValueError("The task has ended or entered import and can no longer be cancelled as analysis.")
    source = job.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("This analysis task does not belong to the current project.")
    if frozen["mode"] != "project":
        authorize_start(context, frozen, {"clip_id": source.get("clip_id"), "kind": job["kind"],
            "start_seconds": source.get("range_start_seconds"), "duration_seconds": source.get("duration_seconds"),
            "parameters": job.get("parameters", {}), **safe_route_fields(job)})
    return identifier(job.get("job_id", job.get("id")))

def compile_import(result, context, frozen, summary):
    authorize_result(context, frozen, result)
    if result["kind"] == "beats":
        raise ValueError("Beat candidates require a tempo or alignment plan and do not create tracks. Use propose_beat_application.")
    if result.get("stale"):
        raise ValueError("The candidate source changed. Analyze again in the DAW.")
    if result.get("applied"):
        raise ValueError("This candidate was already imported. Use Undo/Redo instead of importing it again.")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("Provide a short import summary.")
    kind, total = result["kind"], result["total"]
    counts = safe_summary(result.get("summary"))
    if not total and not (kind == "score" and any(counts.get(k, 0) for k in ("note_count", "chord_count", "beat_count", "annotation_count"))):
        raise ValueError("The candidate is empty and has nothing to import.")
    if kind == "separate":
        expected = result.get("parameters", {}).get("stems", 4)
        names = {"vocals", "drums", "bass", "other"} | ({"piano", "guitar"} if expected == 6 else set())
        items = result.get("items", [])
        if total not in (4, 6) or total != expected or result.get("offset", 0) != 0 or not isinstance(items, list) or len(items) != total or any(not isinstance(item, dict) for item in items):
            raise ValueError("The separated-track count is incomplete. Read the complete candidate again.")
        actual = [item.get("name") for item in items]
        if any(not isinstance(name, str) for name in actual) or len(set(actual)) != total or set(actual) != names:
            raise ValueError("Separated-track stem names do not match.")
    new_tracks = import_track_count(result)
    if len(context.get("tracks", [])) + new_tracks > 64:
        raise ValueError("Import would exceed the 64-track limit. Organize the project first.")
    result_hash = result.get("result_hash")
    if not isinstance(result_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", result_hash):
        raise ValueError("The candidate lacks an immutable content identifier and cannot be imported.")
    source = result["source"]
    label = {"separate": f"Create {total} audio tracks and add the separated stems", "transcribe": f"Create {new_tracks} MIDI tracks with {counts.get('note_count', total)} candidate notes",
             "chords": f"Add {total} chord regions",
             "score": f"Add music analysis: {new_tracks} MIDI tracks and {counts.get('chord_count', 0)} chords"}[kind]
    changes = [label, f"Keep the source position at {source['timeline_start']:.3f} s and retain the original audio"]
    if kind in {"transcribe", "score"}:
        changes.append(f"Preserve {counts.get('controller_count', 0)} controller events. Select an instrument on each new MIDI track to hear it." if counts else "Import notes only, without the original plug-in sound, pitch bends or pedal events. Select an instrument on each new MIDI track to hear it.")
    if kind == "score":
        changes.append("Keep beats and structure as analysis markers. Project tempo and meter stay unchanged.")
    elif kind == "chords":
        changes.append("Add a chord lane with editable labels and timing.")
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": summary.strip(),
            "execution_kind": "analysis_import", "commands": [{"command": "accept_analysis_result", "args": {"result_id": result["result_id"]}}],
            "changes": changes, "steps": [{"index": 1, "label": "Check the source, candidate and project revision"}, {"index": 2, "label": label}],
            "checks": [], "note_clip_ids": [], "analysis": deepcopy(result), "scope": deepcopy(frozen)}

def authorize_chord_read(context, frozen, clip_id):
    assert_scope_unchanged(frozen, context)
    if frozen["mode"] == "project" and not clip_id:
        return ""
    cid = identifier(clip_id)
    # Reuse clip/range scope validation but cap this authorization probe at one
    # second. Reading labels may span a long source; inference's 600s budget is
    # not a restriction on the length of existing project objects.
    clip = next((c for t in context.get("tracks", []) for c in t.get("clips", []) if c.get("id") == cid), None)
    if not clip:
        if frozen["mode"] == "project": return cid  # Provenance may outlive its source clip.
        raise ScopeError("The chord source is outside the current selection.")
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    lower = max(0, timed.get("start_seconds", 0)-clip["start_seconds"]) if frozen["mode"] == "selection" and timed.get("active") else 0
    upper = min(clip["duration_seconds"], timed.get("end_seconds", 0)-clip["start_seconds"]) if frozen["mode"] == "selection" and timed.get("active") else clip["duration_seconds"]
    authorize_start(context, frozen, {"clip_id": cid, "kind": "chords", "start_seconds": lower, "duration_seconds": min(1, upper-lower)})
    return cid

def compile_chord_edit(args, region, context, frozen):
    if not isinstance(args, dict) or set(args)-{"region_id", "clip_id", "label", "start_seconds", "end_seconds", "summary"}:
        raise ValueError("Invalid chord edit parameters.")
    if identifier(args.get("region_id")) != region.get("id"):
        raise ValueError("Chord identity mismatch.")
    cid = authorize_chord_read(context, frozen, args.get("clip_id", ""))
    if not isinstance(args.get("summary"), str) or not args["summary"].strip() or len(args["summary"]) > 500:
        raise ValueError("Provide a short chord edit summary.")
    changes = {k: args[k] for k in ("label", "start_seconds", "end_seconds") if k in args}
    if not changes:
        raise ValueError("No chord edits were proposed.")
    after = deepcopy(region); after.update(changes)
    if not isinstance(after.get("label"), str) or not 1 <= len(after["label"]) <= 128 or any(ord(c) < 32 for c in after["label"]):
        raise ValueError("Chord labels must contain 1 to 128 characters without control characters. Preserve the model label or user correction.")
    start, end = number(after.get("start_seconds"), 0, 172800), number(after.get("end_seconds"), 0, 172800)
    if start >= end:
        raise ValueError("The chord end must be after its start.")
    if frozen["mode"] != "project":
        clip = next(c for t in context["tracks"] for c in t.get("clips", []) if c["id"] == cid)
        for item in (region, after):
            authorize_start(context, frozen, {"clip_id": cid, "kind": "chords",
                "start_seconds": item["start_seconds"]-clip["start_seconds"], "duration_seconds": item["end_seconds"]-item["start_seconds"]})
    if all(region.get(k) == v for k, v in changes.items()):
        raise ValueError("The chord already has these values. No edit is needed.")
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": args["summary"].strip(),
        "execution_kind": "chord_edit", "commands": [{"command": "edit_chord_region", "args": {"id": region["id"], **changes}}],
        "changes": [f"Chord {region['label']} → {after['label']}", f"Time {region['start_seconds']:.3f}–{region['end_seconds']:.3f} s → {start:.3f}–{end:.3f} s"],
        "checks": [], "note_clip_ids": [], "chord_before": deepcopy(region), "chord_after": after, "chord_clip_id": cid, "scope": deepcopy(frozen)}

def capability_groups(context, host, analysis):
    """Conservative adapter AND host AND current selection capability list."""
    commands = set(host.get("commands", [])) if isinstance(host, dict) else set()
    selected = set((context.get("selection_context") or {}).get("clip_ids", []))
    selected.add((context.get("selection_context") or {}).get("active_clip_id", ""))
    clips = [c for t in context.get("tracks", []) for c in t.get("clips", [])]
    audio = any(c.get("kind") == "audio" and c.get("id") in selected for c in clips)
    groups = []
    for key, label, needed, example in (
        ("project", "Project and selection", {"get_snapshot", "get_selection_context"}, "Summarize the current selection."),
        ("track_colour", "Track colour", {"set_track_colour"}, "Set the selected track colour to muted teal #BFD2CF. Show the change first."),
        ("midi", "MIDI editing", {"get_clip_notes", "edit_notes"}, "Transpose the selected MIDI notes up one octave."),
        ("clips", "Clip editing", {"move_clip", "duplicate_clips", "trim_clip"}, "Duplicate the selected clips after their current positions. Show the changes first."),
        ("devices", "Native devices", {"get_native_effect", "set_native_effect", "get_native_instrument"}, "Show the native devices on this track and their editable controls.")):
        ok = needed <= commands
        if key == "devices" and ok:
            from .native_catalog import validate_effect_catalog, validate_instrument_catalog, NativeCatalogError
            try:
                validate_effect_catalog(host.get("native_effect_catalog"))
                validate_instrument_catalog(host.get("native_instrument_catalog"))
            except NativeCatalogError:
                ok = False
        groups.append({"id": key, "label": label, "status": "available" if ok else "unavailable",
                       "status_label": "Available" if ok else "Host unavailable", "enabled": ok, "example": example,
                       "detail": "Select a whole track or choose Whole project scope. Colour changes do not affect sound." if key == "track_colour" else "Reads the project and proposes changes for your approval."})
    for kind, label in KINDS.items():
        providers = available_routes(analysis, kind)
        p = next((item for item in providers if item.get("default")), providers[0] if providers else {})
        installed = COMMANDS <= commands and bool(providers)
        drums = any(item.get("drums") is True or str(item.get("model_id", "")).startswith("muscriptor") for item in providers)
        applicable = audio and (kind != "transcribe" or drums or any(c.get("id") in selected and c.get("kind") == "audio" and c.get("analysis_role") != "drums" for c in clips))
        status = "experimental" if installed and applicable else "not_applicable" if installed else "unavailable"
        example = {"separate": "Separate the selected audio into vocals, drums, bass, piano, guitar and other. Show a preview." if analysis.get("separation_six_stems") else "Separate the selected audio into stems and show the result.",
                   "transcribe": "Transcribe the selected pitched audio to MIDI, keeping its timing. Show a preview.",
                   "chords": "Detect common chords in the selected audio. Let me review before adding the chord lane.",
                   "beats": "Analyze beats and tempo in the selected audio. Let me review the first downbeat before aligning it.",
                   "score": "Analyze the selected audio's melody, chords, beats and structure. Preview before adding to the project."}[kind]
        detail = p.get("detail") or "Install the local analysis models first."
        if kind == "chords": detail = "Detect triads, seventh and suspended chords. Edit them in the chord lane."
        if kind == "separate": detail = "Add separated stems as individual audio tracks."
        if kind == "transcribe": detail = "Transcribe piano or multiple instruments, preserving notes and available controller events."
        if kind == "beats": detail = "Find beats and downbeats. Review before aligning audio or adopting its tempo."
        if kind == "score": detail = "Review melody, chords, beats and structure before adding. Tempo stays unchanged."
        groups.append({"id": kind, "label": label, "status": status,
                       "status_label": "Available" if status == "experimental" else "Select audio" if status == "not_applicable" else "Not installed",
                       "enabled": installed and applicable, "example": example, "detail": detail})
    warp_ready={"get_audio_warp","set_audio_warp"} <= commands
    groups.append({"id":"warp","label":"Audio Warp","status":"available" if warp_ready and audio else "not_applicable" if warp_ready else "unavailable",
        "status_label":"Available" if warp_ready and audio else "Select audio" if warp_ready else "Not installed","enabled":warp_ready and audio,
        "example":"Read Warp settings for the selected audio and propose alignment to the current project.","detail":"Stretch without changing pitch, set source tempo and toggle tempo follow."})
    return groups
