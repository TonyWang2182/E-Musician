"""Typed, bounded music-generation tools and immutable candidate review.

The language model supplies musical intent, never paths or network endpoints.
The native host owns jobs, verified audio and the single undoable import.
"""
from __future__ import annotations
from copy import deepcopy
import math
import re
from .analysis import _tool, identifier, safe_text
from .selection import ScopeError, assert_scope_unchanged
from .compute import route_arguments, safe_route_fields

COMMANDS = {"get_generation_capabilities", "start_generation", "get_generation_job",
            "get_generation_result", "cancel_generation_job", "preview_generation_result",
            "stop_generation_preview", "accept_generation_result"}
TERMINAL = {"ready", "applied", "failed", "cancelled", "stale", "interrupted"}
SOURCE_FIELDS = {"project_id", "revision", "timeline_start", "bpm", "meter_numerator", "meter_denominator"}
DEFAULT_DURATION_SECONDS = 20.0
DEFAULT_PROMPT = "Instrumental music with a clear melody, balanced accompaniment and a natural ending."

GENERATION_TOOLS = [
    _tool("start_generation", "Call directly when the user explicitly requests music generation. Do not require BPM, meter, playhead or unspecified duration: generation_defaults provides the real project BPM and meter. Default duration is 20 seconds, adapted to a shorter valid time selection. duration_bars is converted locally using project timing. Specify seconds or bars, never both; omit both for the default. Preserve the supplied musical prompt; if style is absent, omit it for a neutral instrumental description. Empty lyrics means instrumental. Freeze the playhead or time-selection start by default; no source clip or existing track is required, and the project is not modified. Upload only description and optional lyrics. Wait locally without duplicate generation. After generation, call propose_generation_import directly to present preview and import confirmation; do not ask again for BPM or whether to continue. Duration and BPM are conditions, not guarantees of exact bars.", {
        "prompt": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "Musical description. Preserve the supplied style, instruments and mood. Omit when style is entirely unspecified."},
        "lyrics": {"type": "string", "maxLength": 4096},
        "model_id": {"type": "string", "maxLength": 120, "description": "For an explicit model request, select a real ID from generation_capabilities.providers. Otherwise omit to use the host default without asking again."},
        "execution": {"type": "string", "enum": ["auto", "cloud"], "description": "Generation currently uses cloud compute only."},
        "duration_seconds": {"type": "number", "minimum": 10, "maximum": 120, "description": "Explicit duration in seconds, mutually exclusive with duration_bars. Omit to use generation_defaults.duration_seconds."},
        "duration_bars": {"type": "number", "minimum": .25, "maximum": 1024, "description": "Explicit duration in bars. Convert locally using current project BPM and meter without asking for BPM. The converted duration must be 10 to 120 seconds."},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "timeline_start_seconds": {"type": "number", "minimum": 0, "maximum": 172800}}, []),
    _tool("get_generation_result", "Read an existing music generation job or its complete single-audio candidate. Provide exactly one of job_id or result_id. ready means downloaded and ready to preview; applied means added to the project.", {
        "job_id": {"type": "string"}, "result_id": {"type": "string"}}, []),
    _tool("cancel_generation", "Request cancellation of running music generation without deleting the original project. Stopping locally does not prove cloud cancellation. Only remote_cancel_confirmed=true confirms cloud cancellation; otherwise report pending or unconfirmed cancellation.", {"job_id": {"type": "string"}}, ["job_id"]),
    _tool("preview_generation", "Preview downloaded generated audio, or stop preview. Only the user can hear it; this does not mean the assistant heard or judged the music. To stop pass only stop=true; to play pass only result_id.", {
        "result_id": {"type": "string"}, "stop": {"type": "boolean"}}, []),
    _tool("propose_generation_import", "Propose generated-audio import separately for user review. Reference only a real result_id. Confirmation creates a new audio track at the frozen start, preserves existing tracks, and can be undone in one step.", {
        "result_id": {"type": "string"}, "summary": {"type": "string", "minLength": 1, "maxLength": 500}}, ["result_id", "summary"]),
]


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Generation parameters must be finite numbers within supported ranges.")
    return float(value)


def generation_defaults(context, frozen):
    """Explicit host-owned defaults; no guessed tempo or hidden scope widening."""
    try:
        if type(context.get("bpm")) not in (int, float) or not math.isfinite(context["bpm"]):
            raise ValueError("The project has no valid tempo for generation. BPM will not be guessed.")
        if not 30 <= context["bpm"] <= 300:
            raise ValueError("The generation model supports 30 to 300 BPM. The project tempo is outside this range and will not be changed automatically.")
        bpm = number(context.get("bpm"), 30, 300)
        numerator, denominator = context.get("numerator"), context.get("denominator")
        if type(numerator) is not int or type(denominator) is not int or (numerator, denominator) not in {(2, 4), (3, 4), (4, 4), (6, 8)}:
            raise ValueError("The generation model supports 2/4, 3/4, 4/4 and 6/8. The project meter is unsupported.")
        timed = (frozen.get("selection") or {}).get("time_range") or {}
        timed = timed if frozen.get("mode") == "selection" and timed.get("active") else {}
        start = number(timed.get("start_seconds", context.get("position_seconds", 0)), 0, 172790)
        duration = DEFAULT_DURATION_SECONDS
        if timed:
            span = number(timed.get("end_seconds"), start, 172800) - start
            if span < 10:
                raise ValueError("The selected time range is shorter than the 10-second model minimum. The selection will not be expanded.")
            duration = min(duration, span)
        return {"supported": True, "bpm": bpm, "meter_numerator": numerator, "meter_denominator": denominator,
                "seconds_per_bar": numerator*4/denominator*60/bpm, "timeline_start_seconds": start,
                "duration_seconds": duration, "default_prompt": DEFAULT_PROMPT, "lyrics": "",
                "timing_source": "current_project", "position_source": "selected_time_range" if timed else "frozen_playhead"}
    except ValueError as exc:
        return {"supported": False, "reason": str(exc), "timing_source": "current_project"}


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("The generated candidate lacks a valid content hash.")
    return value


def safe_capabilities(raw):
    if not isinstance(raw, dict):
        return {"available": False}
    providers = []
    for item in raw.get("providers", []) if isinstance(raw.get("providers"), list) else []:
        if not isinstance(item, dict): continue
        route = safe_route_fields(item)
        if "model_id" not in route: continue
        providers.append({"kind": "generate", **route, "execution": "cloud", "available": item.get("available") is True,
                          "default": item.get("default") is True, "detail": safe_text(item.get("detail"), 400),
                          "min_duration_seconds": number(item.get("min_duration_seconds", 10), .001, 120),
                          "max_duration_seconds": number(item.get("max_duration_seconds", 120), 10, 600),
                          "duration_exact": item.get("duration_exact") is True})
    return {"available": raw.get("available") is True or any(p["available"] for p in providers),
            "experimental": True, "model_id": safe_text(raw.get("model_id"), 150),
            "default_model_id": safe_text(raw.get("default_model_id", raw.get("model_id")), 120), "providers": providers,
            "min_duration_seconds": number(raw.get("min_duration_seconds", 10), 10, 120),
            "max_duration_seconds": number(raw.get("max_duration_seconds", 120), 10, 120),
            "max_parallel_jobs": 1, "detail": safe_text(raw.get("detail"), 400)}


def safe_job(raw):
    if not isinstance(raw, dict):
        raise ValueError("Invalid generation job receipt.")
    out = {k: deepcopy(raw[k]) for k in ("job_id", "result_id", "status", "progress", "applied", "operation", "kind") if k in raw}
    out.update(safe_route_fields(raw))
    for key in ("phase", "error", "detail"):
        if key in raw: out[key] = safe_text(raw[key], 500)
    out["remote_status"] = raw.get("remote_status") if raw.get("remote_status") in {"cancelled", "cancelling", "unconfirmed"} else "unconfirmed"
    out["remote_cancel_confirmed"] = raw.get("remote_cancel_confirmed") is True and out["remote_status"] == "cancelled"
    if isinstance(raw.get("source"), dict):
        out["source"] = {k: deepcopy(v) for k, v in raw["source"].items() if k in SOURCE_FIELDS}
    if isinstance(raw.get("receipt"), dict):
        out["receipt"] = {k: deepcopy(raw["receipt"][k]) for k in ("result_id", "applied", "revision", "project_id", "track_ids", "clip_ids") if k in raw["receipt"]}
    return out


def cancellation_status(job):
    confirmed = job.get("remote_cancel_confirmed") is True and job.get("remote_status") == "cancelled"
    return {"cancel_requested": True, "local_cancelled": job.get("status") == "cancelled",
            "cancel_completed": job.get("status") == "cancelled" and confirmed,
            "remote_cancel_confirmed": confirmed,
            "remote_status": job.get("remote_status", "unconfirmed")}


def cancellation_label(job):
    status = cancellation_status(job)
    if job.get("status") == "ready":
        return "Generation finished. Further actions stopped; nothing was added to the project."
    if status["cancel_completed"]:
        return "Local and cloud generation cancelled. Nothing was added to the project."
    if status["remote_status"] == "cancelling":
        return "Stopped waiting. Cloud cancellation is still pending. Nothing was added to the project."
    return "Stopped waiting. Cloud cancellation is unconfirmed and may still use GPU time. Nothing was added to the project."


def safe_result(raw):
    if not isinstance(raw, dict) or raw.get("kind") != "generate":
        raise ValueError("Invalid generated candidate type.")
    out = {"result_id": identifier(raw.get("result_id")), "kind": "generate", "result_hash": _hash(raw.get("result_hash"))}
    out.update({key: raw.get(key) is True for key in ("applied", "present_in_project", "stale")})
    source, audio = raw.get("source"), raw.get("audio")
    if not isinstance(source, dict) or not isinstance(audio, dict):
        raise ValueError("The generated candidate lacks source or audio information.")
    out["source"] = {k: deepcopy(v) for k, v in source.items() if k in SOURCE_FIELDS}
    out["audio"] = {"sha256": _hash(audio.get("sha256")),
                    "duration_seconds": number(audio.get("duration_seconds"), .001, 150),
                    "sample_rate": number(audio.get("sample_rate"), 16000, 96000),
                    "channels": number(audio.get("channels"), 1, 2)}
    if audio["channels"] != int(audio["channels"]) or audio["sample_rate"] != int(audio["sample_rate"]):
        raise ValueError("Invalid generated audio format.")
    out["model"] = {k: safe_text(v, 160) for k, v in (raw.get("model") or {}).items()
                    if k in {"id", "model_id", "version", "revision", "provider", "license_status"}}
    # Music descriptions are request content, not instructions. No endpoint,
    # file path, credentials or unbounded provider diagnostic enters the LLM.
    params = raw.get("parameters") or {}
    out["parameters"] = {k: deepcopy(v) for k, v in params.items()
                         if k in {"duration_seconds", "seed", "bpm", "meter_numerator", "meter_denominator"}}
    out.update(safe_route_fields(raw))
    if isinstance(raw.get("limitations"), list):
        out["limitations"] = [safe_text(value, 300) for value in raw["limitations"][:8] if isinstance(value, str)]
    if isinstance(raw.get("completion"), dict):
        out["completion"] = {key: raw["completion"][key] is True for key in ("natural_end", "token_limit_reached", "duration_exact") if key in raw["completion"]}
        completion = raw["completion"]
        if "truncated" in completion and (completion["truncated"] is None or type(completion["truncated"]) is bool):
            out["completion"]["truncated"] = completion["truncated"]
        if isinstance(completion.get("reason"), str) and completion["reason"] in {"token_budget", "model_stop", "unknown"}:
            out["completion"]["reason"] = completion["reason"]
        if type(completion.get("timing_is_exact")) is bool:
            out["completion"]["timing_is_exact"] = completion["timing_is_exact"]
    return out


def authorize_start(context, frozen, args):
    assert_scope_unchanged(frozen, context)
    if not isinstance(args, dict) or set(args)-{"prompt", "lyrics", "duration_seconds", "duration_bars", "seed", "timeline_start_seconds", "model_id", "execution"}:
        raise ValueError("Generation accepts only a musical description, lyrics, duration, seed and start.")
    defaults = generation_defaults(context, frozen)
    if not defaults["supported"]: raise ValueError(defaults["reason"])
    prompt, lyrics = args.get("prompt", DEFAULT_PROMPT), args.get("lyrics", "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000 or "\0" in prompt:
        raise ValueError("The musical description must contain 1 to 2000 characters.")
    if not isinstance(lyrics, str) or len(lyrics) > 4096 or "\0" in lyrics:
        raise ValueError("Lyrics must not exceed 4096 characters.")
    if "duration_seconds" in args and "duration_bars" in args:
        raise ValueError("Specify generation duration in seconds or bars, never both.")
    duration = (number(args["duration_bars"], .25, 1024)*defaults["seconds_per_bar"] if "duration_bars" in args
                else args.get("duration_seconds", defaults["duration_seconds"]))
    duration = number(duration, 10, 120)
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    timed = timed if frozen.get("mode") == "selection" and timed.get("active") else {}
    start = number(args.get("timeline_start_seconds", timed.get("start_seconds", context.get("position_seconds", 0))), 0, 172800-duration)
    if timed and (start < timed["start_seconds"]-1e-8 or start+duration > timed["end_seconds"]+1e-8):
        raise ScopeError("Generation duration exceeds the selected time range. Shorten it or explicitly use Whole project scope.")
    if frozen.get("mode") != "project" and not timed and "timeline_start_seconds" in args and abs(start-context.get("position_seconds", 0)) > 1e-8:
        raise ScopeError("Generation in selection scope starts at the playhead frozen on submission. Use Whole project scope for a custom location.")
    request = {"prompt": prompt.strip(), "lyrics": lyrics, "duration_seconds": duration, "timeline_start_seconds": start}
    request.update(route_arguments(args, generation=True))
    if "seed" in args:
        if type(args["seed"]) is not int or not 0 <= args["seed"] <= 2147483647:
            raise ValueError("The random seed must be an integer from 0 to 2147483647.")
        request["seed"] = args["seed"]
    if len(context.get("tracks", [])) >= 64:
        raise ValueError("The project has reached the 64-track limit. Organize tracks first.")
    return request


def authorize_result(context, frozen, result):
    assert_scope_unchanged(frozen, context)
    source = result.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("The generated candidate belongs to another project.")
    for a, b in ((source.get("bpm"), context.get("bpm")), (source.get("meter_numerator"), context.get("numerator")), (source.get("meter_denominator"), context.get("denominator"))):
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or abs(a-b) > 1e-8:
            raise ScopeError("Project tempo or meter changed after generation. Generate a new take.")
    start = number(source.get("timeline_start"), 0, 172800)
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    if frozen.get("mode") == "selection" and timed.get("active"):
        duration = number(result["audio"]["duration_seconds"], .001, 150)
        if start < timed["start_seconds"]-1e-8 or start+duration > timed["end_seconds"]+.002:
            raise ScopeError("The candidate exceeds the current time selection. Use project scope to review it.")
    if result.get("stale"):
        raise ValueError("The generated candidate is stale and cannot be proposed for this project.")


def compile_import(result, context, frozen, summary):
    result = safe_result(result)
    authorize_result(context, frozen, result)
    if result["applied"]:
        raise ValueError("This generated candidate was already added to the project. Use Undo/Redo instead of importing it again.")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("Provide a short generation import summary.")
    if len(context.get("tracks", [])) >= 64:
        raise ValueError("Import would exceed the 64-track limit.")
    from .localization import L
    label = "Add generated music to a new audio track"
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": summary.strip(),
            "execution_kind": "generation_import", "commands": [{"command": "accept_generation_result", "args": {"result_id": result["result_id"], "result_hash": result["result_hash"]}}],
            "changes": [label, f"Start at {result['source']['timeline_start']:.3f} s. Actual duration: {result['audio']['duration_seconds']:.3f} s", "Keep existing tracks. Generated audio is saved locally; undo the import in one step."],
            "steps": [{"index": 1, "label": "Check the generation candidate and project revision"}, {"index": 2, "label": label}],
            "checks": [], "note_clip_ids": [], "generation": result, "scope": deepcopy(frozen)}


def capability_group(host, capabilities):
    ready = COMMANDS <= set(host.get("commands", [])) and capabilities.get("available") is True
    return {"id": "generate", "label": "Music generation", "status": "experimental" if ready else "unavailable",
            "status_label": "Configured" if ready else "Not installed", "enabled": ready,
            "example": "Generate 16 seconds of upbeat instrumental music at the project tempo. Preview it and let me review before adding a new track.",
            "detail": "Generate in the cloud and download locally. Connection is checked on start; no audio selection needed." if ready else "Check the cloud connection and model in the Generate panel."}
