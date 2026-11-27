"""Per-user defaults shared by explicit setup tools and optional worker processes."""
from __future__ import annotations
import os
from pathlib import Path


def user_data() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local and Path(local).is_absolute() else Path.home() / ".local/share") / "E-musician"


def data_root(variable: str, directory: str) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value and Path(value).is_absolute() else user_data() / directory


def analysis_root() -> Path:
    return data_root("EMUSICIAN_ANALYSIS_ROOT", "analysis")


def compute_root() -> Path:
    return data_root("EMUSICIAN_COMPUTE_ROOT", "cloud-inference")


def generation_root() -> Path:
    return data_root("EMUSICIAN_GENERATION_ROOT", "cloud-inference")
