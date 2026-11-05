"""Local pipeline check on attributed CC-BY audio; no recognition-quality ground truth."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audio_analysis.common import atomic_json, read_json, sha256_file
from scripts.audio_analysis.register import download

FIXTURES = (
    ("trumpet", "sorohanro_-_solo-trumpet-06", "8374466fd3951d24509da6e799b132a0db0bdeda69d99c69d989a6888d3d727d",
     "750a191b9d0cc94b2f19cfbf11acc13783f75bedcccfcf562f5b076efd068aba", "transcribe", "Mihai Sorohan", "CC-BY-3.0"),
    ("vibeace", "Kevin_MacLeod_-_Vibe_Ace", "6c23aed3dd5aa57f2b1652ecab68d15d9b82ad257f54e639eb2880ca09bc118a",
     "6c71e0525cb0452ea74c6d6f5fde6fa1e221223db7b2aa35b9914b98367ee7b9", "separate", "Kevin MacLeod", "CC-BY-3.0"),
)


def main():
    import soundfile as sf
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("E:/MusicAgent&DAW/analysis"))
    parser.add_argument("--stems", type=int, choices=(4, 6), default=4)
    parser.add_argument("--quality", choices=("fast", "quality"), default="fast")
    args = parser.parse_args()
    root = args.root.resolve()
    registry = read_json(root / "registry.json")
    directory = root / "cache/public-fixtures"
    directory.mkdir(parents=True, exist_ok=True)
    observations = []
    for name, original, audio_hash, license_hash, kind, author, license_name in FIXTURES:
        license_file = directory / (name + "-license.txt")
        audio_file = directory / (name + ".ogg")
        base = "https://librosa.org/data/audio/" + original
        download(base + ".txt", license_file, license_hash)
        license_text = license_file.read_text(encoding="utf-8")
        if "creativecommons.org/licenses/by/3.0" not in license_text:
            raise RuntimeError("Source attribution did not contain the expected CC-BY-3.0 URL; inspect before using fixture")
        download(base + ".ogg", audio_file, audio_hash)
        data, rate = sf.read(audio_file, always_2d=True, dtype="float32")
        # Keep these preview fixtures short, with attribution beside them; never
        # include downloaded audio in the repository or a product distribution.
        data = data[:min(len(data), 8 * rate)]
        wave_file = directory / (name + "-excerpt.wav")
        sf.write(wave_file, data, rate, subtype="PCM_16")
        attribution = {"author": author, "title": original, "source_url": base + ".ogg", "license": license_name,
                       "license_url": "https://creativecommons.org/licenses/by/3.0/", "source_sha256": audio_hash,
                       "attribution_sha256": license_hash, "transformation": "decode to PCM16 WAV and take first <=8 seconds",
                       "derived_sha256": sha256_file(wave_file), "sample_rate": rate, "channels": data.shape[1],
                       "duration_seconds": len(data) / rate, "usage": "local pipeline evaluation; audio not committed"}
        atomic_json(directory / (name + "-attribution.json"), attribution)
        for job_kind in ((kind, "chords") if kind == "separate" else (kind,)):
            job_id = "public-" + name + "-" + job_kind + "-" + uuid.uuid4().hex[:10]
            job_dir = root / "cache/jobs" / job_id
            job_dir.mkdir(parents=True)
            request = {"schema_version": 1, "job_id": job_id, "kind": job_kind, "analysis_root": str(root),
                       "source_path": str(wave_file), "source_offset_seconds": 0, "duration_seconds": len(data) / rate,
                       "source": {"project_id": "public-fixture-probe", "clip_id": name, "input_role": "instrument" if job_kind == "transcribe" else "mix"}}
            if job_kind == "separate":
                request["parameters"] = {"stems": args.stems, "quality": args.quality}
            atomic_json(job_dir / "request.json", request)
            provider_key = "separate_6s" if job_kind == "separate" and args.stems == 6 else job_kind
            command = [registry["providers"][provider_key]["python_executable"], str(Path(__file__).with_name("run.py")),
                       "--request", str(job_dir / "request.json")]
            print("RUN", subprocess.list2cmdline(command), flush=True)
            start = time.perf_counter()
            result = subprocess.run(command, timeout=600)
            if result.returncode:
                print((job_dir / "worker.log").read_text(encoding="utf-8"), flush=True)
                raise RuntimeError(read_json(job_dir / "error.json"))
            output = read_json(job_dir / "result.json")
            if job_kind == "separate":
                assert len(output["stems"]) == args.stems
                assert all(len(stem["waveform_peaks"]) == 128 and stem["sha256"] == sha256_file(job_dir / stem["path"])
                           for stem in output["stems"])
            observation = {"fixture": name, "kind": job_kind, "job_id": job_id, "attribution": attribution,
                           "model": output["model"], "parameters": output["parameters"],
                           "elapsed_wall_seconds": time.perf_counter() - start, "performance": output["performance"],
                           "notes": len(output["notes"]), "stems": len(output["stems"]), "chord_regions": len(output["chord_regions"]),
                           "result_sha256": sha256_file(job_dir / "result.json")}
            observations.append(observation)
            print("PASS", name, job_kind, "seconds", round(observation["elapsed_wall_seconds"], 2), flush=True)
    destination = root / "manifests" / ("public-probe-" + uuid.uuid4().hex[:12] + ".json")
    atomic_json(destination, {"scope": "Actual model pipeline on public attributed musical audio; no ground-truth metrics or listening acceptance",
                              "observations": observations})
    print("Report:", destination)


if __name__ == "__main__":
    main()
