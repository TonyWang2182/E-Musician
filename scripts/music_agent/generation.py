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

COMMANDS = {"get_generation_capabilities", "start_generation", "get_generation_job",
            "get_generation_result", "cancel_generation_job", "preview_generation_result",
            "stop_generation_preview", "accept_generation_result"}
TERMINAL = {"ready", "applied", "failed", "cancelled", "stale", "interrupted"}
SOURCE_FIELDS = {"project_id", "revision", "timeline_start", "bpm", "meter_numerator", "meter_denominator"}

GENERATION_TOOLS = [
    _tool("start_generation", "用已连接的云端音乐模型生成真实音频候选。只上传描述和可选歌词，不上传工程音频。无需选中音频或已有轨道；新工程也可使用。默认放在发送要求时的播放头，选了时间范围则从范围起点开始。不修改工程；本地等待完成，不要重复启动。BPM/拍号来自当前工程，时长是秒且10至120；小节数换算为bars*numerator*4/denominator*60/BPM。空歌词生成纯音乐，带歌词请求歌曲。结果时长/节拍需试听，不保证精确整小节。", {
        "prompt": {"type": "string", "minLength": 1, "maxLength": 2000},
        "lyrics": {"type": "string", "maxLength": 4096},
        "duration_seconds": {"type": "number", "minimum": 10, "maximum": 120},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "timeline_start_seconds": {"type": "number", "minimum": 0, "maximum": 172800}}, ["prompt", "duration_seconds"]),
    _tool("get_generation_result", "读取已启动的音乐生成任务或完整单音频候选。job_id/result_id选一个。ready只是已下载可试听，applied才是加入工程。", {
        "job_id": {"type": "string"}, "result_id": {"type": "string"}}, []),
    _tool("cancel_generation", "请求取消正在计算的音乐生成，不删除原工程。本地停止不等于云端已取消；只有remote_cancel_confirmed为true才可称云端取消完成，否则说明仍在取消或无法确认。", {"job_id": {"type": "string"}}, ["job_id"]),
    _tool("preview_generation", "试听已下载的生成候选，或停止试听。只供用户听，不代表助手能听到或已经判定音乐质量。停止时只传stop=true；播放时只传result_id。", {
        "result_id": {"type": "string"}, "stop": {"type": "boolean"}}, []),
    _tool("propose_generation_import", "单独提出待用户确认的生成音频导入方案。仅引用真实result_id；确认后在冻结起点新建一条音频轨，不覆盖现有轨道，一次撤销可还原。", {
        "result_id": {"type": "string"}, "summary": {"type": "string", "minLength": 1, "maxLength": 500}}, ["result_id", "summary"]),
]


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("生成参数必须是支持范围内的有限数值。")
    return float(value)


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("生成候选缺少有效的内容校验标识。")
    return value


def safe_capabilities(raw):
    if not isinstance(raw, dict):
        return {"available": False}
    return {"available": raw.get("available") is True,
            "experimental": True, "model_id": safe_text(raw.get("model_id"), 150),
            "min_duration_seconds": number(raw.get("min_duration_seconds", 10), 10, 120),
            "max_duration_seconds": number(raw.get("max_duration_seconds", 120), 10, 120),
            "max_parallel_jobs": 1, "detail": safe_text(raw.get("detail"), 400)}


def safe_job(raw):
    if not isinstance(raw, dict):
        raise ValueError("生成任务回执无效。")
    out = {k: deepcopy(raw[k]) for k in ("job_id", "result_id", "status", "progress", "applied", "operation", "kind") if k in raw}
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
        return "生成已结束，已停止后续操作；没有加入工程。"
    if status["cancel_completed"]:
        return "本地和云端生成已取消；没有加入工程。"
    if status["remote_status"] == "cancelling":
        return "已停止等待；云端正在取消，尚未确认停止。没有加入工程。"
    return "已停止等待；无法确认云端生成已停止，可能仍占用算力。没有加入工程。"


def safe_result(raw):
    if not isinstance(raw, dict) or raw.get("kind") != "generate":
        raise ValueError("生成候选类型无效。")
    out = {"result_id": identifier(raw.get("result_id")), "kind": "generate", "result_hash": _hash(raw.get("result_hash"))}
    out.update({key: raw.get(key) is True for key in ("applied", "present_in_project", "stale")})
    source, audio = raw.get("source"), raw.get("audio")
    if not isinstance(source, dict) or not isinstance(audio, dict):
        raise ValueError("生成候选来源或音频信息缺失。")
    out["source"] = {k: deepcopy(v) for k, v in source.items() if k in SOURCE_FIELDS}
    out["audio"] = {"sha256": _hash(audio.get("sha256")),
                    "duration_seconds": number(audio.get("duration_seconds"), .001, 150),
                    "sample_rate": number(audio.get("sample_rate"), 16000, 96000),
                    "channels": number(audio.get("channels"), 1, 2)}
    if audio["channels"] != int(audio["channels"]) or audio["sample_rate"] != int(audio["sample_rate"]):
        raise ValueError("生成音频格式无效。")
    out["model"] = {k: safe_text(v, 160) for k, v in (raw.get("model") or {}).items()
                    if k in {"id", "model_id", "version", "revision", "provider", "license_status"}}
    # Music descriptions are request content, not instructions. No endpoint,
    # file path, credentials or unbounded provider diagnostic enters the LLM.
    params = raw.get("parameters") or {}
    out["parameters"] = {k: deepcopy(v) for k, v in params.items()
                         if k in {"duration_seconds", "seed", "bpm", "meter_numerator", "meter_denominator"}}
    return out


def authorize_start(context, frozen, args):
    assert_scope_unchanged(frozen, context)
    if not isinstance(args, dict) or set(args)-{"prompt", "lyrics", "duration_seconds", "seed", "timeline_start_seconds"} or not {"prompt", "duration_seconds"} <= set(args):
        raise ValueError("生成只接受音乐描述、歌词、时长、种子和起点。")
    prompt, lyrics = args["prompt"], args.get("lyrics", "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000 or "\0" in prompt:
        raise ValueError("音乐描述应为1至2000字。")
    if not isinstance(lyrics, str) or len(lyrics) > 4096 or "\0" in lyrics:
        raise ValueError("歌词最多4096字。")
    duration = number(args["duration_seconds"], 10, 120)
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    timed = timed if frozen.get("mode") == "selection" and timed.get("active") else {}
    start = number(args.get("timeline_start_seconds", timed.get("start_seconds", context.get("position_seconds", 0))), 0, 172800-duration)
    if timed and (start < timed["start_seconds"]-1e-8 or start+duration > timed["end_seconds"]+1e-8):
        raise ScopeError("生成时长超出所选时间范围；请缩短时长或明确使用整个工程。")
    if frozen.get("mode") != "project" and not timed and "timeline_start_seconds" in args and abs(start-context.get("position_seconds", 0)) > 1e-8:
        raise ScopeError("当前选择范围的生成起点是发送时的播放头；自定义其他位置需使用整个工程。")
    request = {"prompt": prompt.strip(), "lyrics": lyrics, "duration_seconds": duration, "timeline_start_seconds": start}
    if "seed" in args:
        if type(args["seed"]) is not int or not 0 <= args["seed"] <= 2147483647:
            raise ValueError("随机种子必须是0至2147483647的整数。")
        request["seed"] = args["seed"]
    if len(context.get("tracks", [])) >= 64:
        raise ValueError("当前已达64轨上限，请先整理轨道。")
    return request


def authorize_result(context, frozen, result):
    assert_scope_unchanged(frozen, context)
    source = result.get("source") or {}
    if source.get("project_id") != context.get("project_id"):
        raise ScopeError("生成候选属于其他工程。")
    for a, b in ((source.get("bpm"), context.get("bpm")), (source.get("meter_numerator"), context.get("numerator")), (source.get("meter_denominator"), context.get("denominator"))):
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or abs(a-b) > 1e-8:
            raise ScopeError("生成时的工程速度或拍号已改变，请重新生成。")
    start = number(source.get("timeline_start"), 0, 172800)
    timed = (frozen.get("selection") or {}).get("time_range") or {}
    if frozen.get("mode") == "selection" and timed.get("active"):
        duration = number(result["audio"]["duration_seconds"], .001, 150)
        if start < timed["start_seconds"]-1e-8 or start+duration > timed["end_seconds"]+.002:
            raise ScopeError("候选超出当前时间选区；请使用工程范围查看该候选。")
    if result.get("stale"):
        raise ValueError("生成候选已过期，不能作为当前工程方案。")


def compile_import(result, context, frozen, summary):
    result = safe_result(result)
    authorize_result(context, frozen, result)
    if result["applied"]:
        raise ValueError("该生成候选已经加入工程，请使用撤销/重做，不要重复导入。")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("请提供简短的生成导入说明。")
    if len(context.get("tracks", [])) >= 64:
        raise ValueError("导入后会超过64轨上限。")
    label = "新建1条音频轨，加入生成音乐"
    return {"project_id": context["project_id"], "revision": context["revision"], "summary": summary.strip(),
            "execution_kind": "generation_import", "commands": [{"command": "accept_generation_result", "args": {"result_id": result["result_id"], "result_hash": result["result_hash"]}}],
            "changes": [label, f"起点 {result['source']['timeline_start']:.3f} 秒，实际时长 {result['audio']['duration_seconds']:.3f} 秒", "保留现有轨道；生成音频已保存在本地，确认后可一次撤销。"],
            "steps": [{"index": 1, "label": "核对生成候选与工程版本"}, {"index": 2, "label": label}],
            "checks": [], "note_clip_ids": [], "generation": result, "scope": deepcopy(frozen)}


def capability_group(host, capabilities):
    ready = COMMANDS <= set(host.get("commands", [])) and capabilities.get("available") is True
    return {"id": "generate", "label": "音乐生成", "status": "experimental" if ready else "unavailable",
            "status_label": "已配置" if ready else "未就绪", "enabled": ready,
            "example": "按当前工程速度生成16秒轻快的纯音乐，先试听，加入新轨道前让我确认。",
            "detail": "云端生成，结果下载到本地；启动时检查连接，不需要选中音频。" if ready else "在生成面板检查云端连接与模型状态。"}
