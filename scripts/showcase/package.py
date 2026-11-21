"""Strict local package lookup shared by the planner and retained-result worker."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re

KINDS = {"generate", "separate", "chords", "beats", "transcribe"}
DEFAULT_WAITS = {"yue2": 20, "ace": 15, "separate": 12, "chords": 8, "beats": 6, "transcribe": 10}


def read_json(path, limit=16*1024*1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("A required local result is missing or invalid.")
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value: raise ValueError("Duplicate package field.")
            value[k] = v
        return value
    def finite(value): raise ValueError("Non-finite package number.")
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed): raise ValueError("Non-finite package number.")
        return parsed
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique, parse_constant=finite, parse_float=number)


def sha256(path, cancelled=lambda: False):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024*1024):
            if cancelled(): raise InterruptedError("Cancelled.")
            digest.update(chunk)
    return digest.hexdigest()


def contained(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Invalid package asset location.")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Package asset escaped its directory.")
    return path


def normalize(text):
    return re.sub(r"\s+", " ", str(text).strip()).casefold().rstrip(".!?")


class Package:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.value = read_json(self.root / "manifest.json", 256*1024)
        if not isinstance(self.value, dict) or self.value.get("schema_version") != 1:
            raise ValueError("Unsupported local package version.")
        projects = self.value.get("projects")
        if not isinstance(projects, list) or len(projects) != 3 or any(not isinstance(p,dict) or not isinstance(p.get("id"),str) for p in projects) or len({p.get("id") for p in projects}) != 3:
            raise ValueError("The package must contain three starting projects.")
        self.projects = {p["id"]: p for p in projects}
        self.scenes = self.value.get("scenarios", [])
        if not isinstance(self.scenes, list) or not 1 <= len(self.scenes) <= 12:
            raise ValueError("Invalid local task catalog.")
        ids = set()
        for scene in self.scenes:
            if not isinstance(scene, dict) or scene.get("kind") not in KINDS or scene.get("project_id") not in self.projects:
                raise ValueError("Invalid local task identity.")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", scene.get("id", "")) or scene["id"] in ids:
                raise ValueError("Duplicate or invalid task identity.")
            ids.add(scene["id"])
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,120}", scene.get("model_id", "")):
                raise ValueError("Invalid retained model identity.")
            if not re.fullmatch(r"[a-f0-9]{64}", scene.get("result_sha256", "")):
                raise ValueError("Retained result checksum is required.")
            contained(self.root, scene.get("result_path"))
            if not isinstance(scene.get("parameters", {}), dict): raise ValueError("Invalid task parameters.")
            prompts = scene.get("prompts", [])
            if not isinstance(prompts, list) or not prompts or any(not isinstance(p, str) or not 0 < len(p) <= 6000 for p in prompts):
                raise ValueError("Prepared instructions are missing.")
            delay = self.wait_seconds(scene)
            if not math.isfinite(delay) or not 0 <= delay <= 180: raise ValueError("Preparation duration is outside limits.")
            if scene.get("application", "import") not in {"import", "manual", "warp"}: raise ValueError("Invalid result review action.")

    @staticmethod
    def wait_seconds(scene):
        key = ("yue2" if scene["model_id"].startswith("yue2") else "ace") if scene["kind"] == "generate" else scene["kind"]
        value = scene.get("wait_seconds", DEFAULT_WAITS[key])
        if type(value) not in (int, float): raise ValueError("Preparation duration must be a number.")
        return float(value)

    def instruction(self, prompt, project_id):
        matches = [s for s in self.scenes if s["project_id"] == project_id and normalize(prompt) in {normalize(p) for p in s["prompts"]}]
        if len(matches) != 1:
            raise ValueError("Choose the matching project and use one of its prepared instructions.")
        return matches[0]

    def request_scene(self, request):
        project_id = request.get("source", {}).get("project_id")
        scenes = [s for s in self.scenes if s["project_id"] == project_id and s["kind"] == request.get("kind") and s["model_id"] == request.get("model_id")]
        if len(scenes) != 1: raise ValueError("This task does not match the current project and model.")
        return scenes[0]
