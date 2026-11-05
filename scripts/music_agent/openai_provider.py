"""OpenAI Responses adapter; stateless tool rounds preserve opaque reasoning items."""
from __future__ import annotations
import copy
import re
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener, getproxies
from .provider import KimiProvider, ProviderError, MAX_COMPLETION_TOKENS, _invalid, _NoRedirect

REASONING_EFFORTS = ("low", "medium", "high")
# Explicitly verified model IDs: unknown aliases get the provider default.
REASONING_MODELS = frozenset({"gpt-5", "gpt-5-2025-08-07", "gpt-5-mini", "gpt-5-mini-2025-08-07",
    "gpt-5-nano", "gpt-5-nano-2025-08-07", "gpt-5.4", "gpt-5.5", "o3", "o4-mini",
    "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"})


def _local_https_proxy(proxies):
    """Use an existing loopback proxy only; never configure a new network route.

    urllib discovers Windows system settings or environment settings. Both are
    filtered identically. HTTPS origin verification and CONNECT remain urllib's
    defaults; the proxy URL never replaces the official API endpoint.
    """
    value = proxies.get("https") if isinstance(proxies, dict) else None
    if not isinstance(value, str) or not re.fullmatch(
            r"https?://(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}", value, re.IGNORECASE):
        return {}
    try:
        parsed = urlsplit(value)
        if parsed.port is None or not 1 <= parsed.port <= 65535:
            return {}
    except ValueError:
        return {}
    return {"https": value}


class OpenAIProvider(KimiProvider):
    provider_id = "openai"
    label = "OpenAI"
    allowed_base_urls = {"https://api.openai.com/v1"}

    def __init__(self, model="gpt-5-mini", base_url="https://api.openai.com/v1", timeout=45,
                 *, api_key=None, opener=None, reasoning_effort="medium"):
        if not isinstance(reasoning_effort, str) or reasoning_effort not in REASONING_EFFORTS:
            raise ProviderError("configuration", "推理强度必须是 low、medium 或 high。")
        self.reasoning_effort = reasoning_effort
        super().__init__(model, base_url, timeout, api_key=api_key, opener=opener)

    @property
    def capabilities(self):
        return {**super().capabilities, "reasoning_effort": self.model in REASONING_MODELS}

    def _default_opener(self):
        try:
            proxies = _local_https_proxy(getproxies())
        except OSError:
            proxies = {}
        self.network_mode = "system_loopback_proxy" if proxies else "direct"
        return build_opener(ProxyHandler(proxies), _NoRedirect())

    @staticmethod
    def supports_tools(model):
        return isinstance(model, str) and model.startswith(("gpt-5", "gpt-6", "gpt-4.1", "gpt-4o", "o3", "o4"))

    @staticmethod
    def _text(value, maximum=64000):
        if not isinstance(value, str) or len(value) > maximum:
            raise _invalid()
        return value

    @classmethod
    def _output(cls, output):
        if not isinstance(output, list) or not 1 <= len(output) <= 32:
            raise _invalid()
        texts, calls, seen = [], [], set()
        for item in output:
            if not isinstance(item, dict):
                raise _invalid()
            kind = item.get("type")
            if item.get("status") not in (None, "completed"):
                raise ProviderError("incomplete", "模型输出未完整结束；工程没有被修改。")
            if "id" in item:
                cls._text(item["id"], 256)
            if kind == "reasoning":
                if not isinstance(item.get("summary", []), list):
                    raise _invalid()
                if "encrypted_content" in item and item["encrypted_content"] is not None:
                    cls._text(item["encrypted_content"], 900000)
                # Opaque reasoning is retained for the next API call, not surfaced to UI.
            elif kind == "message":
                if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                    raise _invalid()
                for part in item["content"]:
                    if not isinstance(part, dict):
                        raise _invalid()
                    if part.get("type") == "refusal":
                        raise ProviderError("refusal", "模型未接受此请求；工程没有被修改。")
                    if part.get("type") != "output_text":
                        raise _invalid()
                    texts.append(cls._text(part.get("text")))
            elif kind == "function_call":
                call_id = cls._text(item.get("call_id"), 256)
                name = cls._text(item.get("name"), 80)
                arguments = cls._text(item.get("arguments"))
                if not call_id or call_id in seen or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
                    raise _invalid()
                seen.add(call_id)
                calls.append({"id": call_id, "type": "function",
                              "function": {"name": name, "arguments": arguments}})
            else:
                # Never accept built-in web/shell/custom tools through this adapter.
                raise ProviderError("unsupported_output", "模型返回了未启用的输出类型；未执行修改。")
        if len(calls) > 8 or (not calls and not any(texts)):
            raise _invalid()
        return "\n".join(texts) or None, calls

    def _inputs(self, messages):
        if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
            raise ProviderError("invalid_request", "对话条数超出范围。")
        inputs, pending = [], set()
        for message in messages:
            if not isinstance(message, dict):
                raise ProviderError("invalid_request", "对话格式无效。")
            role = message.get("role")
            state = message.get("_provider_state")
            if state is not None:
                if role != "assistant" or not isinstance(state, dict) or set(state) != {"provider", "model", "output"} or state["provider"] != self.provider_id or state["model"] != self.model:
                    raise ProviderError("provider_mismatch", "工具上下文与当前服务或模型不匹配，请重新开始任务。")
                if pending:
                    raise ProviderError("invalid_request", "上一轮工具结果不完整。")
                text, calls = self._output(state["output"])
                # The normalized surface must correspond to the private replay items.
                if message.get("content") != text or (message.get("tool_calls") or []) != calls:
                    raise ProviderError("invalid_request", "工具上下文已被更改，请重新开始任务。")
                inputs.extend(copy.deepcopy(state["output"]))
                pending.update(call["id"] for call in calls)
            elif role == "tool":
                call_id = message.get("tool_call_id")
                if not isinstance(call_id, str) or call_id not in pending:
                    raise ProviderError("invalid_request", "工具结果缺少对应调用，未发送请求。")
                content = message.get("content")
                if not isinstance(content, str):
                    raise ProviderError("invalid_request", "工具结果格式无效。")
                inputs.append({"type": "function_call_output", "call_id": call_id, "output": content})
                pending.remove(call_id)
            elif role in {"system", "developer", "user", "assistant"}:
                if pending or message.get("tool_calls") or message.get("reasoning_content"):
                    raise ProviderError("invalid_request", "缺少本服务的完整工具上下文，请重新开始任务。")
                content = message.get("content")
                if not isinstance(content, str):
                    raise ProviderError("invalid_request", "对话格式无效。")
                inputs.append({"role": role, "content": content})
            else:
                raise ProviderError("invalid_request", "对话角色无效。")
        if pending:
            raise ProviderError("invalid_request", "工具结果不完整，未发送请求。")
        return inputs

    def complete(self, messages, tools=None):
        if tools and not self.capabilities["tools"]:
            raise ProviderError("unsupported_capability", "当前模型不在已支持的工具调用模型系列中。")
        payload = {"model": self.model, "input": self._inputs(messages), "store": False,
                   "stream": False, "max_output_tokens": MAX_COMPLETION_TOKENS,
                   "include": ["reasoning.encrypted_content"]}
        if self.model in REASONING_MODELS:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if tools is not None:
            if not isinstance(tools, list) or not 1 <= len(tools) <= 32:
                raise ProviderError("invalid_request", "工具数量超出范围。")
            converted = []
            for tool in tools:
                if not isinstance(tool, dict) or tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
                    raise ProviderError("invalid_request", "只支持函数工具。")
                function = tool["function"]
                if not isinstance(function.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", function["name"]) or not isinstance(function.get("parameters"), dict):
                    raise ProviderError("invalid_request", "函数工具定义无效。")
                converted.append({"type": "function", "name": function["name"],
                    "description": function.get("description", ""),
                    "parameters": copy.deepcopy(function["parameters"]), "strict": False})
            payload.update(tools=converted, tool_choice="auto", parallel_tool_calls=False)
        response = self._request("/responses", payload)
        if response.get("status") != "completed" or response.get("incomplete_details") or response.get("error"):
            raise ProviderError("incomplete", "OpenAI 未完整结束此请求；工程没有被修改。")
        output = response.get("output")
        text, calls = self._output(output)
        message = {"role": "assistant", "content": text,
                   "_provider_state": {"provider": self.provider_id, "model": self.model,
                                       "output": copy.deepcopy(output)}}
        if calls:
            message["tool_calls"] = calls
        usage = response.get("usage") or {}
        if not isinstance(usage, dict):
            raise _invalid()
        normalized = {}
        for source, target in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens"), ("total_tokens", "total_tokens")):
            value = usage.get(source)
            if value is not None:
                if type(value) is not int or not 0 <= value <= 1_000_000_000:
                    raise _invalid()
                normalized[target] = value
        model = response.get("model", self.model)
        if not isinstance(model, str) or len(model) > 128:
            raise _invalid()
        return {"message": message, "usage": normalized, "model": model}
