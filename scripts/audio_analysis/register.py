"""Explicit model setup/probe; this is never called by the real-time engine."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audio_analysis.common import atomic_json, read_json, sha256_file
from scripts.audio_analysis.run import configure_environment


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "E-musician-local-analysis-setup/1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def download(url, destination, expected=None):
    if destination.exists() and (not expected or sha256_file(destination) == expected):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "E-musician-local-analysis-setup/1"})
    print("Downloading", url, "->", destination, flush=True)
    with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)
    if expected and sha256_file(partial) != expected:
        raise ValueError("Downloaded artifact SHA-256 differs from official source metadata")
    os.replace(partial, destination)


def package_manifest(name, destination):
    distribution = importlib.metadata.distribution(name)
    version = distribution.version
    release = fetch_json(f"https://pypi.org/pypi/{name}/{version}/json")
    provenance = {"name": name, "version": version, "source": f"https://pypi.org/project/{name}/{version}/",
                  "published_files": [{"filename": item["filename"], "sha256": item["digests"]["sha256"],
                                       "url": item["url"]} for item in release["urls"]],
                  "installed_files_sha256": {}, "license_files": []}
    for relative in distribution.files or ():
        file = Path(distribution.locate_file(relative))
        if file.suffix in (".py", ".onnx") and file.is_file():
            provenance["installed_files_sha256"][relative.as_posix()] = sha256_file(file)
        if relative.name.lower().split(".")[0] in ("license", "notice", "copying") and file.is_file():
            target = destination / (name + "-" + relative.name)
            shutil.copy2(file, target)
            provenance["license_files"].append({"file": target.name, "sha256": sha256_file(target)})
    return provenance


def register(root, kind, device="cpu", stems=4):
    configure_environment(root)
    provider_key = "separate_6s" if kind == "separate" and stems == 6 else kind
    manifest_dir = root / "manifests" / (provider_key + ("-cuda" if device == "cuda" else ""))
    manifest_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    import numpy as np
    entry = {"available": False, "python_executable": str(Path(sys.executable).resolve()),
             "experimental": True, "device": device, "cpu_threads": 2, "max_duration_seconds": 600,
             "reason": "Not probed", "protocol_version": 1}
    provenance = []
    if kind == "separate":
        import torch
        from demucs.hf import load_safetensors_model
        from demucs.apply import apply_model
        assert importlib.metadata.version("demucs") == "4.1.0"
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        if device == "cuda":
            if not torch.cuda.is_available():
                raise ValueError("CUDA runtime/device is not available; existing CPU registration remains unchanged")
            torch.cuda.reset_peak_memory_stats()
        info_path = manifest_dir / "huggingface-model.json"
        cpu_manifest = root / "manifests" / provider_key / "huggingface-model.json"
        if device == "cuda" and not info_path.exists() and cpu_manifest.exists():
            shutil.copy2(cpu_manifest, info_path)
        model_id = "htdemucs_6s" if stems == 6 else "htdemucs"
        repository = "adefossez/HTDemucs-6s" if stems == 6 else "adefossez/HTDemucs"
        # The first explicit install resolves main once, then saves a permanent
        # revision. Re-running setup never silently upgrades the checkpoint.
        if info_path.exists():
            info = read_json(info_path)
        else:
            info = fetch_json(f"https://huggingface.co/api/models/{repository}/revision/main?blobs=true")
            atomic_json(info_path, info)
        revision = info["sha"]
        directory = root / "models/demucs" / model_id / revision
        weights = [item for item in info["siblings"] if item["rfilename"].endswith(".safetensors")]
        if len(weights) != 1:
            raise ValueError("Expected exactly one HTDemucs checkpoint")
        weight = weights[0]
        model_path = directory / weight["rfilename"]
        expected = weight.get("lfs", {}).get("sha256")
        if not expected:
            raise ValueError("Official model metadata omitted the weight SHA-256")
        download(f"https://huggingface.co/{repository}/resolve/{revision}/{weight['rfilename']}", model_path, expected)
        for filename in ("README.md", model_id + ".yaml"):
            download(f"https://huggingface.co/{repository}/resolve/{revision}/{filename}", directory / filename)
        model = load_safetensors_model(model_path).eval()
        # Tiny zero signal still executes the real network, not the worker's
        # silence fast path. This establishes CPU compatibility, not quality.
        with torch.inference_mode():
            outputs = apply_model(model, torch.zeros(1, 2, 11025), shifts=0, split=False, segment=4, device=device)
        if tuple(outputs.shape) != (1, stems, 2, 11025) or not torch.isfinite(outputs).all():
            raise ValueError("HTDemucs forward probe failed")
        entry.update(model_id=model_id, version="4.1.0", source_revision=revision,
                     source_url="https://huggingface.co/" + repository, model_path=str(model_path),
                     weight_sha256=expected, license_status="code-MIT; checkpoint-redistribution-not-cleared-local-evaluation",
                     sources=list(model.sources),
                     reason=f"Local evaluation checkpoint; {device.upper()} probe passed. {stems} stems.")
        if device == "cuda":
            entry.update(gpu_name=torch.cuda.get_device_name(), cuda_version=torch.version.cuda,
                         probe_peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                         probe_peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(), fallback_device="cpu")
        provenance.append(package_manifest("demucs", manifest_dir))
    elif kind == "beats":
        import torch
        import beat_this
        from beat_this.inference import Audio2Beats
        from scripts.audio_analysis.beats import CODE_REVISION, CHECKPOINT_URL, CHECKPOINT_SHA256
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is not available; existing provider registrations remain unchanged")
        directory = root / "models/beat-this" / CODE_REVISION
        model_path = directory / "final0.ckpt"
        download(CHECKPOINT_URL, model_path, CHECKPOINT_SHA256)
        for filename in ("LICENSE", "README.md"):
            download(f"https://raw.githubusercontent.com/CPJKU/beat_this/{CODE_REVISION}/{filename}", directory / filename)
        distribution = importlib.metadata.distribution("beat-this")
        direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
        if CODE_REVISION not in direct_url.get("url", ""):
            raise ValueError("Beat This code installation must use the pinned official commit archive")
        model = Audio2Beats(str(model_path), device=device, float16=False, dbn=False)
        with torch.inference_mode():
            beats, downbeats = model(np.zeros(22050*2,dtype=np.float32),22050)
        if not np.isfinite(beats).all() or not np.isfinite(downbeats).all():
            raise ValueError("Beat This real forward probe returned invalid timestamps")
        entry.update(model_id="beat-this-final0",version=distribution.version,source_revision=CODE_REVISION,
            source_url="https://github.com/CPJKU/beat_this",model_path=str(model_path),weight_sha256=CHECKPOINT_SHA256,
            license_status="MIT-code-and-published-weights; training-recording-rights-not-transferred",
            reason=f"Official final0 real {device.upper()} forward probe passed; beat/downbeat candidates require review.")
        provenance.append({"source_url":entry["source_url"],"commit":CODE_REVISION,"weight_url":CHECKPOINT_URL,
            "weight_sha256":CHECKPOINT_SHA256,"weight_bytes":model_path.stat().st_size,"direct_url":direct_url,
            "installed_python_sha256":{p.relative_to(Path(beat_this.__file__).parent).as_posix():sha256_file(p)
                for p in Path(beat_this.__file__).parent.rglob("*.py")},"license_sha256":sha256_file(directory/"LICENSE")})
    elif kind == "transcribe":
        import basic_pitch
        import onnxruntime as ort
        from basic_pitch.inference import Model, predict
        from basic_pitch import note_creation
        from basic_pitch.constants import AUDIO_N_SAMPLES
        original = next((Path(basic_pitch.__file__).parent / "saved_models").rglob("*.onnx"))
        directory = root / "models/basic-pitch/0.4.0"
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / original.name
        shutil.copy2(original, model_path)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        outputs = session.run(None, {session.get_inputs()[0].name: np.zeros((1, AUDIO_N_SAMPLES, 1), dtype=np.float32)})
        if len(outputs) != 3 or any(not np.isfinite(value).all() for value in outputs):
            raise ValueError("Basic Pitch ONNX forward probe failed")
        import soundfile as sf
        warmup = manifest_dir / "warmup.wav"
        sf.write(warmup, np.zeros(5513, dtype=np.float32), 22050, subtype="FLOAT")
        model = Model.__new__(Model)
        model.model_type = Model.MODEL_TYPES.ONNX
        model.model = session
        predict(warmup, model)
        entry.update(model_id="basic-pitch", version="0.4.0", source_revision="pypi-basic-pitch-0.4.0",
                     source_url="https://github.com/spotify/basic-pitch", model_path=str(model_path),
                     weight_sha256=sha256_file(model_path), license_status="Apache-2.0-project-bundled-model",
                     reason="ONNX CPU probe passed; pitched instruments, notes only; drum classification unsupported.")
        provenance.append(package_manifest("basic-pitch", manifest_dir))
    else:
        from scripts.audio_analysis.chords import decode_chroma, templates, pitch_class_features
        triad = templates()[0]
        labels = decode_chroma(np.repeat(triad[:, None], 20, axis=1), np.ones(20), .05, 1., .55, .15)
        if len(labels) != 1 or labels[0]["label"] != "C:maj":
            raise ValueError("Chord Viterbi probe failed")
        chroma, energy = pitch_class_features(np.zeros(22050, dtype=np.float32))
        assert chroma.shape[0] == 12 and np.isfinite(energy).all()
        entry.update(model_id="chroma-hmm", version="2.0.0", source_revision="emusician-chroma-hmm-2",
                     source_url="https://www.audiolabs-erlangen.de/resources/MIR/FMP/C5/C5S3_ChordRec_HMM.html",
                     license_status="original-baseline; NumPy/SciPy-BSD", reason="CPU template baseline ready; triad/extended vocabularies, uncalibrated similarity.")
        provenance.append(package_manifest("scipy", manifest_dir))
    entry.update(available=True, probe_elapsed_seconds=time.perf_counter() - started)
    versions = {distribution.metadata["Name"]: distribution.version for distribution in importlib.metadata.distributions()}
    manifest = {"schema_version": 1, "provider": entry, "packages": versions, "provenance": provenance,
                "python": sys.version, "scope": "local forward pass, not recognition quality or audio-device performance"}
    atomic_json(manifest_dir / "installation.json", manifest)
    registry_path = root / "registry.json"
    lock = root / "registry.lock"
    # Independently requested provider installs can finish together; serialize
    # only the small read/merge/replace step, not downloads or inference.
    deadline = time.monotonic() + 30
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError("Another model registration owns registry.lock; check that installer before retrying")
            time.sleep(.1)
    try:
        registry = read_json(registry_path) if registry_path.exists() else {"schema_version": 1, "providers": {}}
        if registry_path.exists():
            backup = root / "manifests/registry-history" / (str(time.time_ns()) + ".json")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(registry_path, backup)
        registry["providers"][provider_key] = entry
        atomic_json(registry_path, registry)
    finally:
        lock.unlink()
    print(json.dumps({"kind": kind, "available": True, "model_id": entry["model_id"],
                      "version": entry["version"], "probe_seconds": entry["probe_elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=("separate", "transcribe", "chords", "beats"), required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--stems", type=int, choices=(4, 6), default=4)
    args = parser.parse_args()
    if args.device == "cuda" and args.kind not in ("separate", "beats"):
        parser.error("CUDA is only supported for separation and beat tracking")
    if args.stems == 6 and args.kind != "separate":
        parser.error("--stems applies only to separation")
    register(args.root.resolve(), args.kind, args.device, args.stems)
