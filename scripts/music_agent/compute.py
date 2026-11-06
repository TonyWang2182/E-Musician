"""Small capability-based routing shared by Agent analysis and generation.

The host owns defaults and live readiness. This module validates user intent;
it never invents a ready model, contacts a service or supplies a filesystem path.
"""
from __future__ import annotations

import re

EXECUTIONS = {"local", "cloud", "auto"}
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def model_id(value):
    if not isinstance(value, str) or not MODEL_ID.fullmatch(value):
        raise ValueError("模型标识无效；请选择宿主能力清单中的模型。")
    return value


def route_arguments(args, *, generation=False):
    result = {}
    if "execution" in args:
        execution = args["execution"]
        if not isinstance(execution, str) or execution not in EXECUTIONS:
            raise ValueError("执行位置须为 local、cloud 或 auto。")
        if generation and execution == "local":
            raise ValueError("当前音乐生成只提供已部署的云端模型。")
        result["execution"] = execution
    if "model_id" in args:
        result["model_id"] = model_id(args["model_id"])
    return result


def available_routes(capabilities, kind):
    """Keep unavailable siblings from masking another ready model of a kind."""
    providers = capabilities.get("providers", []) if isinstance(capabilities, dict) else []
    return [p for p in providers if isinstance(p, dict) and p.get("kind", "generate") == kind
            and p.get("available") is True]


def require_route(capabilities, kind, args):
    routes = available_routes(capabilities, kind)
    # Pre-hybrid generation capabilities exposed only a single model.
    if kind == "generate" and not capabilities.get("providers") and capabilities.get("available") is True:
        routes = [{"kind": kind, "model_id": capabilities.get("model_id"), "execution": "cloud", "available": True}]
    requested = route_arguments(args, generation=kind == "generate")
    execution = requested.get("execution", "auto")
    if execution != "auto":
        routes = [p for p in routes if p.get("execution", "cloud" if kind == "generate" else "local") == execution]
    if "model_id" in requested:
        routes = [p for p in routes if p.get("model_id") == requested["model_id"]]
    if not routes:
        raise ValueError("所选任务、模型和执行位置尚未就绪；请在 DAW 分析或生成面板检查连接。不会自动换用其他模型。")
    return routes


def safe_route_fields(raw):
    result = {}
    if isinstance(raw.get("execution"), str) and raw["execution"] in EXECUTIONS:
        result["execution"] = raw["execution"]
    value = raw.get("model_id")
    if isinstance(value, str) and MODEL_ID.fullmatch(value):
        result["model_id"] = value
    return result
