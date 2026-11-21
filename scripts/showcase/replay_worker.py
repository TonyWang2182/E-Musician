"""Prepare immutable, previously computed candidates. No model/SSH/HTTP imports."""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from showcase.package import Package, contained, read_json, sha256


def atomic(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    for attempt in range(12):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 11: raise
            time.sleep(.025)


def close_number(actual, expected, tolerance=1e-7):
    return type(actual) in (int, float) and type(expected) in (int, float) and math.isfinite(actual) and math.isfinite(expected) and abs(actual-expected) <= tolerance


def validate_request(scene, request, cancelled):
    if not isinstance(request.get("source"), dict): raise ValueError("Current project context is missing.")
    if request["kind"] == "generate":
        expected = scene.get("parameters", {})
        for key in ("prompt", "lyrics", "seed"):
            if request.get(key, "" if key == "lyrics" else None) != expected.get(key, "" if key == "lyrics" else None):
                raise ValueError("This description does not match the retained music result.")
        for key in ("duration_seconds", "bpm", "meter_numerator", "meter_denominator"):
            if key in expected and not close_number(request.get(key), expected[key]):
                raise ValueError("Project tempo or generation settings do not match this result.")
        if expected.get("time_signature") != str(request.get("meter_numerator"))+"/"+str(request.get("meter_denominator")):
            raise ValueError("Project meter does not match this result.")
        return None
    if request.get("parameters", {}) != scene.get("parameters", {}):
        raise ValueError("Analysis settings do not match the retained result.")
    source = scene.get("source", {})
    file = Path(request.get("source_path", ""))
    if not file.is_absolute() or not file.is_file() or file.is_symlink(): raise ValueError("Select the original prepared audio clip.")
    actual_hash = sha256(file, cancelled)
    if actual_hash != source.get("sha256"): raise ValueError("The selected audio does not match this analysis result.")
    rate = source.get("sample_rate")
    if type(rate) not in (int, float) or rate <= 0: raise ValueError("Source sample rate is missing.")
    if not close_number(request.get("source_offset_seconds"), source.get("offset_seconds"), 1.01/rate) or not close_number(request.get("duration_seconds"), source.get("duration_seconds"), 1.01/rate):
        raise ValueError("Select the matching audio range before preparing this result.")
    if not close_number(request["source"].get("sample_rate"), rate, .01) or not close_number(request["source"].get("warp_speed_ratio", 1), source.get("warp_speed_ratio", 1)):
        raise ValueError("The source rate or Warp state has changed.")
    # Metadata-only source identities are re-bound, musical data is never changed.
    return actual_hash


def prepare(root, request_file, *, clock=time.monotonic, sleep=time.sleep):
    request_file = Path(request_file).resolve()
    package = Package(root)
    directory = request_file.parent
    runtime = package.root / "runtime"
    if not directory.is_relative_to(runtime.resolve()): raise ValueError("Task output must stay in the isolated runtime directory.")
    request = read_json(request_file, 128*1024)
    scene = package.request_scene(request)
    cancelled = lambda: (directory / "cancel").exists()
    source_hash = validate_request(scene, request, cancelled)
    original_file = contained(package.root, scene["result_path"])
    if sha256(original_file, cancelled) != scene["result_sha256"]: raise ValueError("The retained result manifest failed verification.")
    result = read_json(original_file)
    if result.get("kind") != request["kind"] or result.get("model", {}).get("id") != request["model_id"]:
        raise ValueError("The retained result belongs to a different task or model.")
    if request["kind"] != "generate" and not close_number(result.get("duration_seconds"), request["duration_seconds"], .002):
        raise ValueError("The retained analysis duration does not match the audio.")
    media = [result["audio"]] if request["kind"] == "generate" else result.get("stems", [])
    if not isinstance(media, list) or len(media)>6 or len({str(item.get("path", "")).casefold() for item in media if isinstance(item, dict)}) != len(media):
        raise ValueError("Invalid retained media catalog.")
    for item in media:
        if not isinstance(item.get("path"),str) or not item["path"].lower().endswith(".wav"):
            raise ValueError("Retained media must be a WAV asset.")
        path = contained(original_file.parent, item["path"])
        if not path.is_file() or path.stat().st_size > 128*1024*1024 or sha256(path, cancelled) != item.get("sha256"):
            raise ValueError("A retained audio file failed verification.")
    atomic(directory / "progress.json", {"phase": "preparing", "detail": "Preparing...", "progress": 0})
    started = clock()
    while clock() - started < package.wait_seconds(scene):
        if cancelled(): raise InterruptedError("Cancelled.")
        sleep(min(.05, max(0, package.wait_seconds(scene) - (clock()-started))))
    if cancelled(): raise InterruptedError("Cancelled.")
    for item in media:
        target = contained(directory, item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with contained(original_file.parent, item["path"]).open("rb") as src, target.open("wb") as dst:
            while chunk := src.read(1024*1024):
                if cancelled(): raise InterruptedError("Cancelled.")
                dst.write(chunk)
        if sha256(target, cancelled) != item["sha256"]: raise ValueError("The local audio copy failed verification.")
    result = copy.deepcopy(result)
    provenance = {"mode": "retained_result_replay", "scenario_id": scene["id"],
        "original_result_sha256": scene["result_sha256"], "original_job_id": result.get("job_id"),
        "presentation_wait_seconds": package.wait_seconds(scene), "inference_performed": False}
    result["job_id"] = result["result_id"] = request["job_id"]
    result["source"] = copy.deepcopy(request["source"])
    if source_hash: result["source"]["source_sha256"] = source_hash
    result["retained_result"] = provenance
    if cancelled(): raise InterruptedError("Cancelled.")
    atomic(directory / "result.json", result)
    atomic(directory / "replay-receipt.json", provenance)
    atomic(directory / "progress.json", {"phase": "ready", "detail": "Ready", "progress": 1})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    # Even error receipts are forbidden outside the isolated runtime boundary.
    safe_output = args.request.resolve().parent.is_relative_to((args.root.resolve()/"runtime").resolve())
    try:
        prepare(args.root, args.request)
        return 0
    except InterruptedError:
        if safe_output:atomic(args.request.parent / "cancellation.json", {"local_cancel_confirmed": True, "remote_status": "not_started", "remote_cancel_confirmed": False})
        return 2
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "Unable to prepare the local result. Check the package files."
        if safe_output:atomic(args.request.parent / "error.json", {"code": "retained_result_invalid", "message": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
