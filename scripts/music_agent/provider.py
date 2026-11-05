"""Bounded, synchronous Moonshot client. Call from the Agent worker, never audio/UI."""
from __future__ import annotations

import json
import math
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from .secrets import SecretError, load_key

MAX_BODY_BYTES = 1024 * 1024
MAX_COMPLETION_TOKENS = 4096
ALLOWED_BASE_URLS = {"https://api.moonshot.cn/v1", "https://api.moonshot.ai/v1"}


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(message)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("redirect", "模型服务返回了重定向；为保护密钥，连接已停止。", code)


def _invalid() -> ProviderError:
    return ProviderError("invalid_response", "模型返回了无效或不完整的数据；工程没有被修改。")


def _finite(value: str):
    raise ValueError("Non-finite JSON number")


def _number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class KimiProvider:
    provider_id = "kimi"
    label = "Kimi"
    allowed_base_urls = ALLOWED_BASE_URLS

    @property
    def capabilities(self):
        return {"text": True, "tools": self.supports_tools(self.model), "streaming": False,
                "image_input": False, "audio_input": False, "audio_output": False}

    @staticmethod
    def supports_tools(model):
        return isinstance(model, str) and model.startswith(("kimi-", "moonshot-v1-"))

    def __init__(self, model: str = "kimi-k2.6", base_url: str = "https://api.moonshot.cn/v1",
                 timeout: float = 45, *, api_key: str | None = None, opener=None):
        if not isinstance(base_url, str) or base_url.rstrip("/") not in self.allowed_base_urls:
            raise ProviderError("configuration", "只允许连接所选服务的官方 HTTPS API 地址。")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", model):
            raise ProviderError("configuration", "模型名称无效。")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
            raise ProviderError("configuration", "模型请求超时须为 1–120 秒。")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key
        self.network_mode = "injected" if opener is not None else "direct"
        self._opener = opener if opener is not None else self._default_opener()

    def _default_opener(self):
        # Kimi stays direct. Adapters may explicitly permit a bounded local proxy;
        # no arbitrary environment proxy is inherited here.
        return build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, payload: dict | None = None) -> dict:
        try:
            key = self._api_key if self._api_key is not None else load_key(provider=self.provider_id)
        except SecretError:
            raise ProviderError("missing_key", "模型服务 密钥尚未配置或无法解密，请重新配置。") from None
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{12,4096}", key):
            raise ProviderError("missing_key", "模型服务 API 密钥格式无效，请重新配置。")
        try:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False,
                        allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ProviderError("invalid_request", "请求包含无效数据。") from None
        if body is not None and len(body) > MAX_BODY_BYTES:
            raise ProviderError("request_too_large", "工程上下文过大，请缩小选择范围。")
        request = Request(self.base_url + path, data=body, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "E-musician-agent/0.1",
        }, method="GET" if body is None else "POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                # Also defend injected/nonstandard openers that follow redirects.
                if response.geturl() != request.full_url:
                    raise ProviderError("redirect", "模型连接地址发生变化，连接已停止。")
                if response.status != 200:
                    raise self._http_error(response.status)
                raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ProviderError("response_too_large", "模型响应超过大小上限，已停止处理。")
            result = json.loads(raw.decode("utf-8"), parse_constant=_finite, parse_float=_number,
                                object_pairs_hook=_duplicates)
            if not isinstance(result, dict):
                raise _invalid()
            return result
        except ProviderError:
            raise
        except HTTPError as error:
            # Never include response body/reason/headers: providers can echo input.
            # Close without reading: deferred urllib cleanup can otherwise emit
            # a ResourceWarning containing the raw HTTPError repr.
            try:
                error.close()
            except OSError:
                pass
            raise self._http_error(error.code) from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("timeout", "模型服务 请求超时。可稍后重试；不会自动重复收费请求。") from None
        except (URLError, OSError):
            raise ProviderError("network", f"无法连接 {self.label}，请检查网络后重试。") from None
        except (UnicodeError, ValueError, TypeError, RecursionError):
            raise _invalid() from None

    @staticmethod
    def _http_error(status: int) -> ProviderError:
        if status in (301, 302, 303, 307, 308):
            return ProviderError("redirect", "模型服务返回了重定向，连接已停止。", status)
        if status in (401, 403):
            return ProviderError("authentication", "模型服务 拒绝了当前密钥或访问权限，请检查本机配置。", status)
        if status == 429:
            return ProviderError("rate_limit", "模型服务 额度不足或请求过于频繁，请检查平台用量后重试。", status)
        if status == 400:
            return ProviderError("bad_request", "模型服务 拒绝了请求，请检查模型名称与参数支持情况。", status)
        if status == 404:
            return ProviderError("model_not_found", "模型服务 模型或接口不可用，请检查模型名称。", status)
        return ProviderError("http_error", "模型服务 服务暂时不可用，请稍后重试。", status)

    def list_models(self) -> list[str]:
        data = self._request("/models").get("data")
        if not isinstance(data, list) or len(data) > 512:
            raise _invalid()
        models = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item["id"]):
                raise _invalid()
            if item["id"] not in models:
                models.append(item["id"])
        return models

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if tools and not self.capabilities["tools"]:
            raise ProviderError("unsupported_capability", "当前模型不在已支持的工具调用模型系列中。")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
            raise ProviderError("invalid_request", "对话条数超出范围。")
        if any(not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"} for message in messages):
            raise ProviderError("invalid_request", "对话格式无效。")
        if any("_provider_state" in message for message in messages):
            raise ProviderError("provider_mismatch", "工具上下文属于其他模型服务，请重新开始任务。")
        payload = {"model": self.model, "messages": messages,
                   "max_tokens": MAX_COMPLETION_TOKENS, "stream": False}
        if self.model in {"kimi-k2.5", "kimi-k2.6"}:
            payload["thinking"] = {"type": "disabled"}
        elif self.model.startswith("kimi-k3"):
            payload["reasoning_effort"] = "low"
        if tools is not None:
            if not isinstance(tools, list) or not 1 <= len(tools) <= 32:
                raise ProviderError("invalid_request", "工具数量超出范围。")
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        result = self._request("/chat/completions", payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise _invalid()
        choice = choices[0]
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ProviderError("incomplete", "模型输出未完整结束，请缩小任务后重新生成；工程没有被修改。")
        source = choice.get("message")
        if not isinstance(source, dict) or source.get("role") != "assistant":
            raise _invalid()
        content = source.get("content")
        if content is not None and not isinstance(content, str):
            raise _invalid()
        message = {"role": "assistant", "content": content}
        if "reasoning_content" in source:
            reasoning = source["reasoning_content"]
            if reasoning is not None and not isinstance(reasoning, str):
                raise _invalid()
            message["reasoning_content"] = reasoning
        calls = source.get("tool_calls")
        if calls is not None:
            if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
                raise _invalid()
            normalized = []
            seen = set()
            for call in calls:
                if not isinstance(call, dict) or call.get("type") != "function":
                    raise _invalid()
                call_id = call.get("id")
                function = call.get("function")
                if not isinstance(call_id, str) or not 1 <= len(call_id) <= 256 or call_id in seen or not isinstance(function, dict):
                    raise _invalid()
                name, arguments = function.get("name"), function.get("arguments")
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name) or not isinstance(arguments, str):
                    raise _invalid()
                seen.add(call_id)
                normalized.append({"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}})
            message["tool_calls"] = normalized
        if choice["finish_reason"] == "tool_calls" and not calls:
            raise _invalid()
        if not calls and not content:
            raise _invalid()
        usage = result.get("usage") or {}
        if not isinstance(usage, dict):
            raise _invalid()
        counters = {}
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(field)
            if value is not None:
                if type(value) is not int or not 0 <= value <= 1_000_000_000:
                    raise _invalid()
                counters[field] = value
        returned_model = result.get("model", self.model)
        if not isinstance(returned_model, str) or len(returned_model) > 128:
            raise _invalid()
        return {"message": message, "usage": counters, "model": returned_model}
