"""Versioned non-secret preferences; provider credentials are always stored separately."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import tempfile
from .audit import data_directory
from .provider import ProviderError
from .providers import create_provider, default_preferences

DEFAULT_CONFIG = {"schema_version": 2, "active_provider": "kimi", "providers": default_preferences()}
MAX_CONFIG_BYTES = 16384


class ConfigError(RuntimeError):
    pass


def config_path():
    return data_directory() / "settings.json"


def _validate(provider_id, model, base_url):
    provider = create_provider(provider_id, model, base_url)
    if provider.model.startswith("sk-"):
        raise ConfigError("模型名称不能填写 API 密钥。")
    return {"model": provider.model, "base_url": provider.base_url}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate config key")
        result[key] = value
    return result


def _normalize(value):
    if not isinstance(value, dict):
        raise ConfigError("设置格式无效。")
    result = copy.deepcopy(DEFAULT_CONFIG)
    if set(value) == {"model", "base_url"}:
        result["providers"]["kimi"] = _validate("kimi", value["model"], value["base_url"])
        return result
    if set(value) != {"schema_version", "active_provider", "providers"} or type(value["schema_version"]) is not int or value["schema_version"] != 2:
        raise ConfigError("设置版本无效。")
    prefs = value["providers"]
    if not isinstance(prefs, dict) or set(prefs) - set(result["providers"]):
        raise ConfigError("设置包含未知服务。")
    for provider_id, settings in prefs.items():
        if not isinstance(settings, dict) or set(settings) != {"model", "base_url"}:
            raise ConfigError("服务设置字段无效。")
        result["providers"][provider_id] = _validate(provider_id, settings["model"], settings["base_url"])
    active = value["active_provider"]
    if not isinstance(active, str) or active not in result["providers"]:
        raise ConfigError("当前服务未适配。")
    result["active_provider"] = active
    return result


def load_config(path=None):
    """Migrate v1 in memory; malformed data never triggers writes or key access."""
    source = Path(path) if path is not None else config_path()
    try:
        with source.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            return copy.deepcopy(DEFAULT_CONFIG)
        return _normalize(json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique))
    except (OSError, ValueError, UnicodeError, ProviderError, ConfigError, RecursionError):
        return copy.deepcopy(DEFAULT_CONFIG)


def active_config(config=None):
    values = load_config() if config is None else _normalize(config)
    provider_id = values["active_provider"]
    return {"provider": provider_id, **values["providers"][provider_id]}


def save_config(model, base_url, path=None, *, provider="kimi"):
    """Update one provider, preserve the others and atomically activate the choice."""
    settings = _validate(provider, model, base_url)
    destination = Path(path) if path is not None else config_path()
    value = load_config(destination)
    value["providers"][provider] = settings
    value["active_provider"] = provider
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".settings-", suffix=".tmp", mode="w", encoding="utf-8",
                newline="\n", dir=destination.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError:
        raise ConfigError("无法保存本机模型设置，请检查本机目录权限。") from None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
