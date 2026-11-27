"""Cloud MIR helper: stream a frozen selection, retrieve verified local candidates."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.cloud import compute_client as client
from scripts.audio_analysis.common import validate_notes


def validate(request, directory):
    if request.get("schema_version") != 1 or request.get("kind") not in {"separate", "transcribe", "chords", "score"}:
        raise client.GenerationError("Unsupported cloud analysis task.")
    job_id = request.get("job_id")
    if not isinstance(job_id, str) or not client.ID.fullmatch(job_id):
        raise client.GenerationError("Invalid analysis task ID.")
    if request.get("execution", "cloud") not in {"cloud", "auto"}:
        raise client.GenerationError("Cloud helper cannot perform a local task.")
    root = request.get("analysis_root")
    source = request.get("source_path")
    if not isinstance(root, str) or not Path(root).is_absolute() or directory != (Path(root) / "cache/jobs" / job_id).resolve():
        raise client.GenerationError("Invalid analysis task directory.")
    if not isinstance(source, str) or not Path(source).is_absolute() or not isinstance(request.get("source"), dict):
        raise client.GenerationError("Invalid source audio reference.")
    client.checked_number(request.get("duration_seconds"), .001, 600, "analysis duration")
    client.checked_number(request.get("source_offset_seconds", 0), 0, 172800, "source offset")
    params = request.get("parameters", {})
    # New cloud models use their pinned inference configuration. Local model
    # knobs cannot be silently accepted when switching to a different model.
    if not isinstance(params, dict) or (params and not (request["kind"] == "separate" and params == {"stems": 4})):
        raise client.GenerationError("This cloud model uses a fixed inference profile. Remove local-only parameters.")
    return request


def freeze(request, directory, cancel, progress):
    import numpy as np
    import soundfile as sf
    path = Path(request["source_path"])
    if not path.is_file():
        raise client.GenerationError("The source audio no longer exists.")
    before = path.stat()
    source_hash = client.digest(path, cancel)
    expected = request["source"].get("source_sha256")
    if expected and expected != source_hash:
        raise client.GenerationError("The source changed before freezing the selected range.")
    destination = directory / "input.wav"
    temporary = directory / "input.partial.wav"
    if destination.is_symlink() or temporary.is_symlink():
        raise client.GenerationError("Unsafe frozen input path.")
    try:
        with sf.SoundFile(path) as audio:
            rate, channels = audio.samplerate, audio.channels
            if channels not in (1, 2) or not 8000 <= rate <= 96000:
                raise client.GenerationError("Cloud analysis accepts mono/stereo audio from 8 to 96 kHz.")
            first = math.floor(request.get("source_offset_seconds", 0) * rate + .5)
            frames = math.floor(request["duration_seconds"] * rate + .5)
            if frames < 1 or first >= audio.frames or first + frames > audio.frames + 1:
                raise client.GenerationError("The selected audio range exceeds the source.")
            frames = min(frames, audio.frames - first)
            if frames * channels * 4 + 4096 > client.MAX_FILE:
                raise client.GenerationError("The selected audio exceeds the upload budget.")
            audio.seek(first)
            remaining = frames
            with sf.SoundFile(temporary, mode="w", samplerate=rate, channels=channels, format="WAV", subtype="FLOAT") as output:
                while remaining:
                    client.check_cancel(cancel)
                    block = audio.read(min(65536, remaining), dtype="float32", always_2d=True)
                    if not len(block) or not np.isfinite(block).all():
                        raise client.GenerationError("Source audio is truncated or contains non-finite samples.")
                    output.write(block)
                    remaining -= len(block)
                    progress("preparing", 1 - remaining / frames)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise client.GenerationError("Source audio changed while freezing its range.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
    return {**request["source"], "source_sha256": source_hash, "source_sample_rate": rate,
        "source_offset_seconds": first / rate, "source_start_sample": first, "source_frames": frames,
        "source_channels": channels, "duration_seconds": frames / rate,
        "frozen_input_sha256": client.digest(destination, cancel)}


def validate_controllers(items, duration):
    if not isinstance(items, list) or len(items) > 100000:
        raise client.GenerationError("Invalid MIDI controller list.")
    for item in items:
        if not isinstance(item, dict):
            raise client.GenerationError("Invalid MIDI controller.")
        client.checked_number(item.get("time_seconds"), 0, duration, "MIDI controller time")
        for key, low, high in (("controller", 0, 127), ("value", 0, 127), ("channel", 1, 16)):
            if type(item.get(key)) is not int or not low <= item[key] <= high:
                raise client.GenerationError("Invalid MIDI controller value.")
    return items


def normalize(result, request, source, artifacts, directory, cancel):
    import numpy as np
    import soundfile as sf
    duration = source["duration_seconds"]
    declared = client.checked_number(result.get("duration_seconds"), .001, 600, "result duration")
    if abs(declared - duration) > .002 or result.get("time_basis") != "input_relative_seconds":
        raise client.GenerationError("Cloud result timing does not match the frozen selection.")
    tracks = result.get("midi_tracks", [])
    if not isinstance(tracks, list) or len(tracks) > 64:
        raise client.GenerationError("Too many transcribed instrument tracks.")
    notes, controllers, track_ids = [], [], set()
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get("id"), str) or not client.ID.fullmatch(track["id"]) or track["id"] in track_ids:
            raise client.GenerationError("Invalid transcribed track identity.")
        track_ids.add(track["id"])
        for field in ("name", "instrument"):
            if not isinstance(track.get(field), str) or len(track[field]) > 128 or any(c in track[field] for c in "\r\n\x00"):
                raise client.GenerationError("Invalid transcribed instrument label.")
        if type(track.get("program")) is not int or not 0 <= track["program"] <= 127 or type(track.get("channel")) is not int or not 1 <= track["channel"] <= 16 or not isinstance(track.get("is_drum"), bool):
            raise client.GenerationError("Invalid transcribed MIDI instrument.")
        if not isinstance(track.get("notes"), list):
            raise client.GenerationError("Missing transcribed notes.")
        track["notes"] = validate_notes(track["notes"], duration)
        track["controllers"] = validate_controllers(track.get("controllers", []), duration)
        notes.extend({**n, "track_id": track["id"], "instrument": track["instrument"], "program": track["program"], "is_drum": track["is_drum"]} for n in track["notes"])
        controllers.extend({**c, "track_id": track["id"]} for c in track["controllers"])
    if not tracks:
        notes = validate_notes(result.get("notes", []), duration)
        controllers = validate_controllers(result.get("controllers", []), duration)
    if len(notes) > 100000 or len(controllers) > 100000:
        raise client.GenerationError("MIDI results exceed the project event budget.")
    chords = result.get("chord_regions", [])
    sections = result.get("structure_regions", [])
    for field, values in (("chord", chords), ("section", sections)):
        if not isinstance(values, list) or len(values) > 10000:
            raise client.GenerationError("Too many analysis regions.")
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not 1 <= len(item["label"]) <= 128 or any(c in item["label"] for c in "\x00\r\n"):
                raise client.GenerationError("Invalid analysis label.")
            start = client.checked_number(item.get("start_seconds"), 0, duration, "region start")
            end = client.checked_number(item.get("end_seconds"), 0, duration, "region end")
            if end <= start:
                raise client.GenerationError("Analysis region must have positive duration.")
            if field == "chord":
                if item.get("score") is not None:
                    client.checked_number(item["score"], 0, 1, "chord score")
                if not isinstance(item.get("uncertain"), bool):
                    raise client.GenerationError("Chord uncertainty must be explicit.")
    beats = result.get("beat_events", [])
    if not isinstance(beats, list) or len(beats) > 10000:
        raise client.GenerationError("Invalid beat event count.")
    previous = -1
    for beat in beats:
        if not isinstance(beat, dict) or not isinstance(beat.get("is_downbeat"), bool):
            raise client.GenerationError("Invalid beat candidate.")
        at = client.checked_number(beat.get("time_seconds"), 0, duration, "beat time")
        if not previous < at < duration:
            raise client.GenerationError("Beat events must be strictly ordered inside the selection.")
        previous = at
    stems = result.get("stems", [])
    if request["kind"] == "separate":
        if not isinstance(stems, list) or {s.get("name") for s in stems} != {"vocals", "drums", "bass", "other"} or len(stems) != 4:
            raise client.GenerationError("SCNet must return four distinct aligned stems.")
        for stem in stems:
            name = stem.get("path")
            if name not in artifacts or stem.get("sha256") != artifacts[name]["sha256"]:
                raise client.GenerationError("Separated audio is not a verified artifact.")
            peaks = [0.] * 128
            with sf.SoundFile(directory / name) as audio:
                rate, channels, frames = audio.samplerate, audio.channels, audio.frames
                if channels not in (1, 2) or not 8000 <= rate <= 96000 or abs(frames / rate - duration) > .002:
                    raise client.GenerationError("Separated audio is misaligned or malformed.")
                if stem.get("sample_rate") != rate or stem.get("channels") != channels or stem.get("frames") != frames:
                    raise client.GenerationError("Separated audio geometry differs from its manifest.")
                boundaries = np.linspace(0, frames, 129, dtype=np.int64)
                for i in range(128):
                    client.check_cancel(cancel)
                    audio.seek(int(boundaries[i]))
                    data = audio.read(int(boundaries[i+1] - boundaries[i]), dtype="float32", always_2d=True)
                    if not np.isfinite(data).all():
                        raise client.GenerationError("Separated audio contains non-finite samples.")
                    peaks[i] = float(np.max(np.abs(data))) if len(data) else 0.
            stem.update(waveform_peaks=peaks, peak=max(peaks), duration_seconds=frames / rate)
    model = dict(result["model"])
    model.setdefault("version", model.get("revision") or model.get("source_revision") or "cloud-protocol-2")
    return {"schema_version": 1, "job_id": request["job_id"], "result_id": request["job_id"], "kind": request["kind"],
        "execution": "cloud", "model": model, "source": source, "duration_seconds": duration,
        "parameters": {"stems": 4} if request["kind"] == "separate" else {},
        "stems": stems, "midi_tracks": tracks, "notes": notes, "controllers": controllers,
        "chord_regions": chords, "beat_events": beats, "tempo": result.get("tempo", {}),
        "structure_regions": sections, "annotations": result.get("annotations", []),
        "summary": {"track_count": len(stems) if stems else len(tracks) or int(bool(notes)), "note_count": len(notes),
            "controller_count": len(controllers), "chord_count": len(chords), "beat_count": len(beats), "annotation_count": len(sections)},
        "score_kind": "uncalibrated_model_output", "limitations": result.get("warnings", []),
        "artifacts": result["artifacts"], "performance": result.get("metrics", {})}


def run(path, config=None, tunnel_factory=client.Tunnel):
    directory = Path(path).resolve().parent
    request = validate(client.read_json(path, 128 * 1024), directory)
    if (directory / "result.json").exists():
        raise client.GenerationError("This immutable candidate already exists.")
    config = config if config is not None else client.registry(request.get("compute_root"))
    model_id = client.select_model(config, request["kind"], request.get("model_id", ""))
    cancel = lambda: (directory / "cancel").exists()
    started = time.monotonic()
    def progress(phase, fraction=None):
        client.atomic_json(directory / "progress.json", {"schema_version": 1, "job_id": request["job_id"], "status": "ready" if phase == "ready" else "running", "phase": phase, "progress": fraction, "elapsed_seconds": time.monotonic() - started})
    progress("preparing")
    source = freeze(request, directory, cancel, progress)
    tunnel = tunnel_factory(config, directory)
    try:
        progress("connecting")
        client.check_cancel(cancel)
        tunnel.open()
        live = tunnel.call("GET", "/capabilities")
        client.select_model(live, request["kind"], model_id)
        payload = {"request_id": request["job_id"], "kind": request["kind"], "model_id": model_id,
            "input": {"sha256": source["frozen_input_sha256"]}, "parameters": {}}
        result = client.task(tunnel, payload, directory, cancel, progress, directory / "input.wav")
        progress("downloading")
        artifacts = client.download_artifacts(tunnel, request["job_id"], result, directory, cancel, progress)
        output = normalize(result, request, source, artifacts, directory, cancel)
        output["performance"]["desktop_elapsed_seconds"] = time.monotonic() - started
        client.check_cancel(cancel)
        client.atomic_json(directory / "result.json", output)
        progress("ready", 1.)
        return output
    finally:
        tunnel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.request)
        return 0
    except Exception as exc:
        (args.request.parent / "worker-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        message = str(exc) if isinstance(exc, client.GenerationError) else f"Cloud analysis failed ({type(exc).__name__}); inspect its task log."
        client.atomic_json(args.request.parent / "error.json", {"message": message, "cancelled": isinstance(exc, client.Cancelled)})
        return 2 if isinstance(exc, client.Cancelled) else 1


if __name__ == "__main__":
    raise SystemExit(main())
