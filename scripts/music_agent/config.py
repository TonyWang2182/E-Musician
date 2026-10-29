"""Non-secret local model preferences; credentials remain in separate DPAPI storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .audit import data_directory
from .provider import KimiProvider, ProviderError

DEFAULT_CONFIG = {"model": "kimi-k2.6", "base_url": "https://api.moonshot.cn/v1"}
MAX_CONFIG_BYTES = 4096


class ConfigError(RuntimeError):
    pass


def config_path() -> Path:
    return data_directory() / "settings.json"


def _validate(model, base_url) -> dict:
    # Provider construction performs local validation only: no key read/network.
    provider = KimiProvider(model=model, base_url=base_url)
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


def load_config(path: Path | None = None) -> dict:
    """Return validated preferences or safe defaults; never load arbitrary fields."""
    source = Path(path) if path is not None else config_path()
    try:
        with source.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            return dict(DEFAULT_CONFIG)
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != {"model", "base_url"}:
            return dict(DEFAULT_CONFIG)
        return _validate(value["model"], value["base_url"])
    except (OSError, ValueError, UnicodeError, ProviderError, ConfigError, RecursionError):
        return dict(DEFAULT_CONFIG)


def save_config(model: str, base_url: str, path: Path | None = None) -> None:
    """Validate first, then atomically replace two non-secret fields only."""
    value = _validate(model, base_url)
    destination = Path(path) if path is not None else config_path()
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".settings-", suffix=".tmp", mode="w",
                encoding="utf-8", newline="\n", dir=destination.parent, delete=False) as stream:
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
