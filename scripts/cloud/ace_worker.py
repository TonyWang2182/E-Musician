"""ACE-Step adapter: lazy resident model, one invocation at a time via gateway.

Only text-to-music is exposed. Native model tensors are validated, converted to
portable PCM16 WAV, and published atomically. The DAW remains a local audio host.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path


class AceGenerator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest = json.loads(self.root.joinpath("manifests/ace-runtime.json").read_text(encoding="utf-8"))
        source = Path(self.manifest["source_directory"])
        if not source.is_dir() or not source.resolve().is_relative_to(self.root):
            raise RuntimeError("ACE source is missing from the configured cloud data root.")
        sys.path.insert(0, str(source))
        os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(self.root / "models/ace/checkpoints")
        os.environ["HF_HOME"] = str(self.root / "cache/huggingface")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        self.dit = self.lm = None

    def load(self):
        if self.dit is not None and self.lm is not None:
            return
        import torch
        from acestep.handler import AceStepHandler
        from acestep.llm_inference import LLMHandler
        if not torch.cuda.is_available():
            raise RuntimeError("The configured generation CUDA device is unavailable.")
        torch.set_num_threads(4)
        class PinnedXLHandler(AceStepHandler):
            def _ensure_models_present(inner_self, *, checkpoint_path, config_path, prefer_source, vae_variant=None):
                # Upstream checks the unused default 2B DiT even for XL. Check
                # exactly our deployed components instead; never auto-download
                # an unpinned extra model during a user request.
                required = (config_path, "vae", "Qwen3-Embedding-0.6B", "acestep-5Hz-lm-1.7B")
                for component in required:
                    if not any(Path(checkpoint_path, component).glob("*.safetensors")):
                        return f"Pinned model component is missing: {component}", False
                return None

        dit = PinnedXLHandler()
        status, success = dit.initialize_service(project_root=str(self.root / "models/ace"), config_path="acestep-v15-xl-turbo",
            device="cuda", use_flash_attention=False, compile_model=False, offload_to_cpu=False, offload_dit_to_cpu=False,
            quantization=None, prefer_source="modelscope", use_mlx_dit=False)
        if not success:
            raise RuntimeError(f"ACE diffusion initialization failed: {status}")
        lm = LLMHandler()
        status, success = lm.initialize(checkpoint_dir=str(self.root / "models/ace/checkpoints"),
            lm_model_path="acestep-5Hz-lm-1.7B", backend="pt", device="cuda", offload_to_cpu=False, dtype=torch.bfloat16)
        if not success:
            raise RuntimeError(f"ACE language model initialization failed: {status}")
        self.dit, self.lm = dit, lm

    def __call__(self, request, directory, phase, cancelled):
        import numpy as np
        import soundfile as sf
        import torch
        from acestep.inference import GenerationConfig, GenerationParams, generate_music
        started = time.monotonic()
        cold = self.dit is None
        if cancelled():
            raise RuntimeError("Generation cancelled before model loading.")
        phase("loading")
        self.load()
        loaded = time.monotonic()
        if cancelled():
            raise RuntimeError("Generation cancelled before inference.")
        torch.cuda.reset_peak_memory_stats()
        phase("running")

        def progress(*args, **kwargs):
            if cancelled():
                raise RuntimeError("Generation cancelled.")

        actual_bpm = int(round(request["bpm"]))
        params = GenerationParams(caption=request["prompt"], lyrics="[Instrumental]" if request["instrumental"] else request["lyrics"],
            instrumental=request["instrumental"], duration=float(request["duration_seconds"]), bpm=actual_bpm,
            timesignature=request["time_signature"].split("/")[0], seed=request["seed"], inference_steps=8, thinking=True,
            use_cot_metas=False, use_cot_caption=False, use_cot_language=True,
            enable_normalization=True, normalization_db=-1.0)
        config = GenerationConfig(batch_size=1, allow_lm_batch=False, use_random_seed=False, seeds=[request["seed"]], audio_format="wav")
        with torch.inference_mode():
            generated = generate_music(self.dit, self.lm, params, config, save_dir=None, progress=progress)
        if cancelled():
            raise RuntimeError("Generation cancelled.")
        if not generated.success or len(generated.audios) != 1:
            raise RuntimeError(f"ACE generation failed: {generated.error}")
        inference_finished = time.monotonic()
        phase("postprocessing")
        audio = generated.audios[0]
        rate = int(audio.get("sample_rate", 0))
        tensor = audio.get("tensor")
        if tensor is None or rate < 8000 or rate > 192000 or tensor.ndim != 2 or tensor.shape[0] not in (1, 2):
            raise RuntimeError("ACE produced invalid audio geometry.")
        pcm = tensor.detach().float().cpu().numpy().T
        duration = len(pcm) / rate
        if not 0 < duration <= 125 or not np.isfinite(pcm).all():
            raise RuntimeError("ACE produced invalid audio samples or duration.")
        peak = float(np.max(np.abs(pcm)))
        rms = float(np.sqrt(np.mean(np.square(pcm, dtype=np.float64))))
        if peak < 1e-6 or rms < 1e-8:
            raise RuntimeError("ACE produced silent audio.")
        if peak > 1.0001:
            raise RuntimeError("ACE normalized output is above the supported PCM range.")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "audio.wav.partial"
        sf.write(str(temporary), pcm, rate, format="WAV", subtype="PCM_16")
        output = directory / "audio.wav"
        temporary.replace(output)
        model = dict(self.manifest["model"])
        model["revision"] = model["weights_revision"]
        model.update({"language_model": "acestep-5Hz-lm-1.7B", "backend": "pytorch", "dtype": "bfloat16", "steps": 8})
        result = {"schema_version": 1, "kind": "generate", "model": model, "parameters": request,
            "conditioning": {"bpm": actual_bpm, "time_signature": request["time_signature"], "duration_seconds": request["duration_seconds"],
                             "timing_is_exact": False},
            "artifacts": [{"id": "audio.wav", "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "bytes": output.stat().st_size,
                           "sample_rate": rate, "channels": int(pcm.shape[1]), "duration_seconds": duration, "sample_format": "pcm16"}],
            "metrics": {"cold_load": cold, "load_seconds": loaded-started, "inference_seconds": inference_finished-loaded,
                        "total_seconds": time.monotonic()-started, "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                        "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(), "peak": peak, "rms": rms,
                        "gpu": torch.cuda.get_device_name(), "torch": torch.__version__, "cuda": torch.version.cuda}}
        directory.joinpath("result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
