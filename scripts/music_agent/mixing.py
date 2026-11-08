"""Bounded control-thread mix inspection, never an audio listening claim."""
from copy import deepcopy

from .bridge import BridgeError, identity
from .localization import L
from .plans import EFFECT_NAMES
from .selection import ScopeError, assert_scope_unchanged

MAX_MIX_TRACKS = 16
MAX_MIX_EFFECTS = 16
MIX_TOOL = {"type": "function", "function": {
    "name": "read_mix_context",
    "description": "Read scoped track levels, pan, mute/solo, routing, automation summaries and native effect states in ONE tool round. Use before a basic mix/balance proposal instead of reading devices one by one. Omit track_ids to use authorized tracks (max 16 per read); include_master requires project scope. Includes at most 16 native effect states, with explicit truncation. Peak meters are instantaneous, can be stale/decaying when stopped, and are NOT RMS/LUFS, whole-song analysis or audible quality. No audio playback, no mutation. Propose at most 16 deliberate adjustments with propose_plan; never equalize every track to the same peak or claim to have heard it.",
    "parameters": {"type": "object", "additionalProperties": False, "properties": {
        "track_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_MIX_TRACKS, "uniqueItems": True},
        "include_master": {"type": "boolean"}, "include_effects": {"type": "boolean"}}}}}

MIX_INSTRUCTION = """
Basic mixing workflow: when asked to mix/balance, use read_mix_context once to inspect all authorized tracks and installed native effects. The current model cannot listen, and no whole-song loudness/spectral/reference-matching tool is available. Do not call MIR analysis to pretend to measure a mix. Existing gain/pan/routing/effect settings support a conservative initial settings proposal, not a finished mastering judgment. Current peak meters are transient observations; stopped/decaying meters must not be used to infer source loudness or gain targets. Do not normalize all instruments to one peak. Preserve mute/solo, routing, instrument settings, clips and notes unless specifically requested. Do not add effects merely to appear busy. For a broad 'mix this' request, state assumptions briefly and prepare a limited, reasoned starting proposal using existing authorized gain/pan or native FX. Do not require the user to supply exact dB values before offering this starting point. Explain that audition is needed. A user explicitly asking for advice/questions may receive text without a proposal. Scope is never expanded: if the requested whole mix needs project scope, tell the user to choose Whole project. One plan supports at most 16 actions; for larger work choose a coherent first batch and state what remains, never claim the entire mix is complete. Tool loops have at most 6 model rounds; batch reads and reserve a round for propose_plan. Plans require Apply and can be undone as a batch.
"""


def _authorized_tracks(context, frozen):
    tracks = context.get("tracks", [])
    if frozen["mode"] == "project":
        return {t["id"] for t in tracks}
    selection = frozen["selection"]
    ids = set(selection["track_ids"])
    if not ids and selection["focus"] == "track" and selection["active_track_id"]:
        ids.add(selection["active_track_id"])
    clip_ids = ({selection["active_clip_id"]} if frozen["mode"] == "clip" else
                set(selection["clip_ids"]) | {selection["note_clip_id"]})
    ids.update(t["id"] for t in tracks if any(c.get("id") in clip_ids for c in t.get("clips", [])))
    return ids


def read_mix_context(bridge, context, frozen, args):
    if not isinstance(args, dict) or set(args) - {"track_ids", "include_master", "include_effects"}:
        raise ValueError("Invalid mix inspection arguments.")
    for key in ("include_master", "include_effects"):
        if key in args and type(args[key]) is not bool:
            raise ValueError("Mix inspection switches must be boolean.")
    assert_scope_unchanged(frozen, context)
    current = bridge.snapshot()
    if identity(current) != identity(context):
        raise BridgeError("工程已变化，请重新生成方案。")
    assert_scope_unchanged(frozen, current)
    authorized = _authorized_tracks(context, frozen)
    requested = args.get("track_ids")
    if requested is not None:
        if (not isinstance(requested, list) or not 1 <= len(requested) <= MAX_MIX_TRACKS
                or any(not isinstance(v, str) or not v for v in requested) or len(set(requested)) != len(requested)):
            raise ValueError("Mix inspection needs 1–16 unique existing track IDs.")
        if not set(requested) <= authorized:
            raise ScopeError("混音读取超出当前范围；全工程混音请先选择整个工程。")
    else:
        requested = [t["id"] for t in context.get("tracks", []) if t["id"] in authorized][:MAX_MIX_TRACKS]
    if not requested:
        raise ScopeError("请先选择要混音的轨道，或将范围切换到整个工程。")
    if args.get("include_master") and frozen["mode"] != "project":
        raise ScopeError("主轨效果器只能在工程范围读取和修改，请先切换范围。")
    # Keep only host-owned summaries. No clips, file paths, plugin identifiers,
    # automation point arrays, signal buffers, or credentials are returned.
    fields = {"id", "name", "kind", "gain_db", "pan", "muted", "solo", "plugins",
              "output_target_id", "sends", "automation", "peak_left_db", "peak_right_db", "overloaded"}
    tracks = [{k: deepcopy(v) for k, v in t.items() if k in fields}
              for t in current.get("tracks", []) if t["id"] in requested]
    if len(tracks) != len(requested):
        raise BridgeError("Mix inspection track identity changed.")
    result = {"tracks": tracks, "authorized_track_count": len(authorized),
              "tracks_truncated": len(requested) < len(authorized),
              "observation": {"playing": current.get("playing", False),
                  "position_seconds": current.get("position_seconds"), "kind": "instantaneous_peak_snapshot",
                  "freshness_verified": False, "whole_song_loudness_available": False,
                  "warning": "Meters are transient/possibly decaying, not RMS/LUFS. No audio was listened to. Do not infer gain targets from stopped meters."},
              "native_effects": [], "effects_truncated": False,
              "limits": {"plan_actions": 16, "tracks_per_read": MAX_MIX_TRACKS, "effects_per_read": MAX_MIX_EFFECTS}}
    rows = list(tracks)
    if args.get("include_master"):
        result["master"] = {k: deepcopy(current[k]) for k in ("master_gain_db", "master_peak_left_db", "master_peak_right_db", "master_overloaded", "master_automation", "master_plugins") if k in current}
        rows.append({"id": "master", "plugins": current.get("master_plugins", [])})
    if args.get("include_effects", True):
        targets = [(t["id"], p["id"]) for t in rows for p in t.get("plugins", [])
                   if p.get("format") == "E-musician" and p.get("is_instrument") is False
                   and p.get("name") in EFFECT_NAMES.values()]
        result["effects_truncated"] = len(targets) > MAX_MIX_EFFECTS
        for track_id, device_id in targets[:MAX_MIX_EFFECTS]:
            result["native_effects"].append({"track_id": track_id, "device_id": device_id,
                "state": bridge.read_native_effect(context, track_id, device_id)})
    final = bridge.snapshot()
    if identity(final) != identity(context):
        raise BridgeError("读取效果器期间工程已变化。")
    assert_scope_unchanged(frozen, final)
    return result


def capability_group(host):
    available = {"set_track_gain", "set_track_pan"} <= set(host.get("commands", []))
    return {"id": "mix", "label": L("基础混音", "Basic mix"), "enabled": available,
         "status": "available" if available else "unavailable",
         "status_label": L("可用", "Available") if available else L("宿主未就绪", "Host unavailable"),
         "detail": L("音量、声像、路由与原生装置；需试听确认，不含整曲响度或参考曲匹配。", "Levels, pan, routing and native devices. Audition required; no whole-song loudness or reference matching."),
         "example": L("读取当前范围内轨道的音量、声像、路由和原生效果器，提出一份有理由的、保守的基础混音方案。保留片段、音符、乐器和路由；不要假称听过音频，不要平均拉齐所有轨道。", "Inspect levels, pan, routing and native effects in the current scope. Propose a reasoned, conservative starting mix. Preserve clips, notes, instruments and routing. Do not claim to have heard the audio or equalize every track to the same peak.")}
