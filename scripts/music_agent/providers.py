"""Explicit provider registry. Reserved adapters are visible but not executable."""
from __future__ import annotations
import copy
from .provider import KimiProvider, ProviderError
from .openai_provider import OpenAIProvider
from .secrets import has_key

PROVIDERS = {
    "kimi": {"label": "Kimi", "adapter": KimiProvider, "default_model": "kimi-k2.6",
             "base_url": "https://api.moonshot.cn/v1", "models": ["kimi-k2.6", "kimi-k3.1-pro"]},
    "openai": {"label": "OpenAI", "adapter": OpenAIProvider, "default_model": "gpt-5-mini",
               "base_url": "https://api.openai.com/v1", "models": ["gpt-5-mini"]},
    "anthropic": {"label": "Anthropic", "adapter": None, "default_model": None, "base_url": None, "models": []},
    "gemini": {"label": "Google Gemini", "adapter": None, "default_model": None, "base_url": None, "models": []},
    "local-compatible": {"label": "Local compatible service", "adapter": None, "default_model": None, "base_url": None, "models": []},
}


def provider_spec(provider_id):
    if not isinstance(provider_id, str) or provider_id not in PROVIDERS:
        raise ProviderError("unknown_provider", "Unknown provider. No credentials were accessed.")
    return dict(PROVIDERS[provider_id])


def create_provider(provider_id="kimi", model=None, base_url=None, *, require_tools=True, **kwargs):
    spec = provider_spec(provider_id)
    if spec["adapter"] is None:
        raise ProviderError("adapter_pending", "This provider adapter is not implemented and cannot make model requests.")
    provider = spec["adapter"](model=model if model is not None else spec["default_model"],
        base_url=base_url if base_url is not None else spec["base_url"], **kwargs)
    if require_tools and not provider.capabilities["tools"]:
        raise ProviderError("unsupported_capability", "This model is outside the tool-calling model families supported by this adapter.")
    return provider


def default_preferences():
    return {key: {"model": value["default_model"], "base_url": value["base_url"], **({"reasoning_effort":"medium"} if key == "openai" else {})}
            for key, value in PROVIDERS.items() if value["adapter"] is not None}


def list_providers(config=None):
    preferences = (config or {}).get("providers", {})
    result = []
    for provider_id, spec in PROVIDERS.items():
        ready = spec["adapter"] is not None
        configured = ready and has_key(provider=provider_id)
        settings = preferences.get(provider_id, {})
        model = settings.get("model", spec["default_model"])
        base_url = settings.get("base_url", spec["base_url"])
        capabilities = (spec["adapter"](model=model, base_url=base_url, **({"reasoning_effort":settings.get("reasoning_effort","medium")} if provider_id == "openai" else {})).capabilities if ready else
                        {"text": False, "tools": False, "streaming": False,
                         "image_input": False, "audio_input": False, "audio_output": False})
        result.append({"id": provider_id, "label": spec["label"], "configured": bool(configured),
            "adapter_ready": ready, "implemented": ready,
            "status": "adapter_pending" if not ready else "available" if configured else "unconfigured",
            "default_model": spec["default_model"], "model": model, "base_url": base_url,
            **({"reasoning_effort":settings.get("reasoning_effort","medium")} if provider_id == "openai" else {}),
            "models": list(spec["models"]), "capabilities": copy.deepcopy(capabilities),
            "availability_note": "Configured status does not verify network connectivity or account access."})
    return result
