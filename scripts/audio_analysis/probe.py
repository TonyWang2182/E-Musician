"""Real-model synthetic pipeline probes, explicitly not musical-quality acceptance."""
from __future__ import annotations

import argparse
import array
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
import wave

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audio_analysis.common import atomic_json, read_json, sha256_file


def write_fixture(path, duration=8., rate=44100, silence=False):
    samples = array.array("h")
    for frame in range(round(duration * rate)):
        second = frame / rate
        pitches = (60, 64, 67) if second < duration / 2 else (57, 60, 64)
        envelope = min(1., second * 30, (duration - second) * 30)
        value = 0. if silence else .12 * envelope * sum(math.sin(2 * math.pi * 440 * 2 ** ((pitch - 69) / 12) * second) for pitch in pitches)
        samples.append(round(value * 32767))
        samples.append(round(value * 32767))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("E:/MusicAgent&DAW/analysis"))
    parser.add_argument("--kind", choices=("all", "separate", "transcribe", "chords"), default="all")
    parser.add_argument("--duration", type=float, default=8.)
    parser.add_argument("--stems", type=int, choices=(4, 6), default=4)
    parser.add_argument("--quality", choices=("fast", "quality"), default="fast")
    parser.add_argument("--instrument", choices=("auto", "piano", "bass", "guitar", "vocals"), default="auto")
    parser.add_argument("--vocabulary", choices=("triads", "extended"), default="extended")
    args = parser.parse_args()
    root = args.root.resolve()
    fixtures = root / "cache/probe-fixtures" / uuid.uuid4().hex[:12]
    fixtures.mkdir(parents=True, exist_ok=True)
    audio = fixtures / "synthetic-c-major-a-minor.wav"
    write_fixture(audio, args.duration)
    registry = read_json(root / "registry.json")
    observations = []
    for kind in ("separate", "transcribe", "chords") if args.kind == "all" else (args.kind,):
        job_id = "probe-" + kind + "-" + uuid.uuid4().hex[:12]
        directory = root / "cache/jobs" / job_id
        directory.mkdir(parents=True)
        request = {"schema_version": 1, "job_id": job_id, "kind": kind, "analysis_root": str(root),
                   "source_path": str(audio), "source_offset_seconds": .5, "duration_seconds": args.duration - 1.,
                   "source": {"project_id": "synthetic-probe", "clip_id": "synthetic-clip", "bpm": 120,
                              "timeline_start": 3., "input_role": "instrument"}}
        request["parameters"] = {"separate": {"stems": args.stems, "quality": args.quality},
                                  "transcribe": {"instrument": args.instrument},
                                  "chords": {"vocabulary": args.vocabulary}}[kind]
        atomic_json(directory / "request.json", request)
        key = "separate_6s" if kind == "separate" and args.stems == 6 else kind
        command = [registry["providers"][key]["python_executable"], str(Path(__file__).with_name("run.py")),
                   "--request", str(directory / "request.json")]
        print("RUN", subprocess.list2cmdline(command), flush=True)
        started = time.perf_counter()
        process = subprocess.run(command, timeout=600, check=False)
        if process.returncode:
            print((directory / "worker.log").read_text(encoding="utf-8"), flush=True)
            raise RuntimeError(f"{kind} probe failed: {read_json(directory / 'error.json')}")
        result = read_json(directory / "result.json")
        assert result["source"]["source_start_sample"] == 22050
        assert result["source"]["source_sha256"] == sha256_file(audio)
        assert abs(result["duration_seconds"] - (args.duration - 1.)) < 1e-8
        assert read_json(directory / "progress.json")["status"] == "ready"
        if kind == "separate":
            expected = {"vocals", "drums", "bass", "other"} | ({"piano", "guitar"} if args.stems == 6 else set())
            assert {item["name"] for item in result["stems"]} == expected
            for item in result["stems"]:
                assert item["sha256"] == sha256_file(directory / item["path"])
                assert item["frames"] == round((args.duration - 1.) * item["sample_rate"])
                assert len(item["waveform_peaks"]) == 128
                assert max(item["waveform_peaks"]) == item["peak"]
                assert all(math.isfinite(peak) and peak >= 0 for peak in item["waveform_peaks"])
        if kind == "transcribe":
            assert len(result["notes"]) > 0, "Synthetic pitched fixture should yield note candidates"
            assert all(note["start_seconds"] + note["duration_seconds"] <= result["duration_seconds"] + 1e-8 for note in result["notes"])
        if kind == "chords":
            assert result["chord_regions"][0]["start_seconds"] == 0
            assert result["chord_regions"][-1]["end_seconds"] == result["duration_seconds"]
        observation = {"kind": kind, "job_id": job_id, "elapsed_wall_seconds": time.perf_counter() - started,
                       "model": result["model"], "performance": result["performance"],
                       "stems": len(result["stems"]), "notes": len(result["notes"]),
                       "chord_regions": result["chord_regions"], "result_sha256": sha256_file(directory / "result.json")}
        observations.append(observation)
        print(json.dumps(observation, indent=2), flush=True)
    report = {"scope": "Actual model/algorithm inference on synthetic tones. Not real-music quality or ASIO stability.",
              "machine": platform.platform(), "processor": platform.processor(), "audio_device": "none-offline",
              "fixture": str(audio), "fixture_sha256": sha256_file(audio), "observations": observations}
    output = root / "manifests" / ("probe-" + uuid.uuid4().hex[:12] + ".json")
    atomic_json(output, report)
    print("Report:", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
