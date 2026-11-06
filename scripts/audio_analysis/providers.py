"""Heavy dependencies are imported only inside the selected worker provider."""
from __future__ import annotations

from math import gcd
from pathlib import Path

from .common import AnalysisError, sha256_file, validate_notes
from .resources import check_gpu_headroom, run_inference_once


def separation_settings(parameters):
    """Bounded inference profiles; quality uses real shift averaging, not EQ."""
    return {"overlap": .5, "shifts": 2} if parameters["quality"] == "quality" else {"overlap": .25, "shifts": 0}


def waveform_peaks(audio, bins=128):
    """True all-channel absolute maxima; bounded UI envelope, unchanged PCM.

    Process one view at a time to avoid a full-stem abs() allocation for long
    files. Each bin represents the corresponding equal-duration source range.
    """
    import numpy as np
    boundaries = np.linspace(0, len(audio), bins + 1, dtype=np.int64)
    return [float(np.max(np.abs(audio[first:last]))) if last > first else 0.
            for first, last in zip(boundaries, boundaries[1:])]


def checked_model(entry, job):
    path = Path(entry.get("model_path", ""))
    if not path.is_file() or sha256_file(path, job) != entry.get("weight_sha256"):
        raise AnalysisError("model_integrity", "Installed model is missing or its SHA-256 differs from the registry. Re-run explicit setup.")
    return path


def separate(job, audio, sample_rate, entry):
    import numpy as np
    import soundfile as sf
    import torch
    import random
    from scipy.signal import resample_poly
    from demucs.hf import load_safetensors_model
    from demucs.apply import apply_model

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    random.seed(0)
    torch.manual_seed(0)
    device = "cuda" if entry.get("device") == "cuda" and torch.cuda.is_available() else "cpu"
    fallback = entry.get("device") == "cuda" and device == "cpu"
    gpu_admission = {}
    if device == "cuda":
        gpu_admission = check_gpu_headroom(torch, entry)
        torch.cuda.reset_peak_memory_stats()
    path = checked_model(entry, job)
    job.progress("loading_model", .15, f"Loading HTDemucs on {device.upper()}; local evaluation checkpoint.")
    model = load_safetensors_model(path).eval()
    expected_sources = {"vocals", "drums", "bass", "other"}
    if job.request["parameters"]["stems"] == 6:
        expected_sources.update(("piano", "guitar"))
    if set(model.sources) != expected_sources or len(model.sources) != len(expected_sources):
        raise AnalysisError("model_integrity", "The registered separator does not match the requested stem count.")
    target = int(model.samplerate)
    if target != sample_rate:
        common = gcd(sample_rate, target)
        audio = resample_poly(audio, target // common, sample_rate // common, axis=0).astype(np.float32)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    if audio.shape[1] != model.audio_channels:
        raise AnalysisError("unsupported_channels", "HTDemucs requires mono or stereo input.")
    mix = torch.from_numpy(np.ascontiguousarray(audio.T))
    reference = mix.mean(0)
    mean = reference.mean()
    deviation = reference.std()
    segment = job.request["parameters"]["segment_seconds"]
    settings = separation_settings(job.request["parameters"])
    progress_fraction = 0.

    def progress(data):
        nonlocal progress_fraction
        at = float(data.get("segment_offset", 0)) / target
        if data.get("state") == "end":
            at += segment * (1. - settings["overlap"])
        fraction = min(1., at / max(len(audio) / target, .001))
        if settings["shifts"]:
            fraction = (float(data.get("shift_idx", 0)) + fraction) / settings["shifts"]
        progress_fraction = max(progress_fraction, fraction)
        job.progress("separating", .2 + .65 * progress_fraction,
                     f"Separating {len(model.sources)} stems ({device.upper()}, two CPU threads).")

    if float(deviation) <= 1e-8:
        outputs = torch.zeros((len(model.sources), 2, len(audio)), dtype=torch.float32)
    else:
        mix.sub_(mean).div_(deviation)

        def infer_once():
            with torch.inference_mode():
                return apply_model(model, mix[None], split=True, **settings,
                                   segment=segment, device=device, num_workers=0,
                                   progress=False, callback=progress)[0]

        outputs = run_inference_once(infer_once, 'Separation')
        # apply_model returns private full-track output. In-place restoration
        # avoids two additional stem-count × duration float32 allocations.
        with torch.inference_mode():
            outputs.mul_(deviation).add_(mean)
    job.progress("writing_stems", .87, "Writing aligned float WAV stems; no per-stem normalization.")
    stems = []
    for index, name in enumerate(model.sources):
        job.check_cancelled()
        data = outputs[index].cpu().numpy().T
        if len(data) != len(audio) or any(not np.isfinite(data[start:start+65536]).all()
                                        for start in range(0, len(data), 65536)):
            raise AnalysisError("invalid_result", "Separation produced invalid or misaligned audio.")
        destination = job.directory / f"{name}.wav"
        sf.write(destination, data, target, subtype="FLOAT")
        peaks = waveform_peaks(data)
        stems.append({"name": name, "path": destination.name, "sample_rate": target, "channels": 2,
                      "duration_seconds": len(data) / target, "frames": len(data),
                      "sha256": sha256_file(destination, job), "peak": max(peaks), "waveform_peaks": peaks})
    stems.sort(key=lambda stem: ("vocals", "drums", "bass", "piano", "guitar", "other").index(stem["name"]))
    return {"stems": stems, "runtime_metrics": {"device": device, "cpu_fallback": fallback,
            "gpu_name": torch.cuda.get_device_name() if device == "cuda" else "",
            **gpu_admission,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else 0,
            "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved() if device == "cuda" else 0},
            "limitations": ["Other may contain several instruments; lead/backing voices and guitar roles are not separated.",
            *( ["Six-stem piano and guitar are experimental and may contain bleed or artifacts."] if len(stems) == 6 else []),
            "HTDemucs checkpoint is for local evaluation; redistribution rights are not cleared."],
            "timing": {"output_sample_rate": target, "segment_seconds": segment, **settings,
                       "effective_forward_segment_seconds": max(segment, float(model.segment))
                           if getattr(model, "use_train_segment", False) else segment,
                       "random_seed": 0, "global_normalization": "mean_std_restored", "independent_normalization": False,
                       "quantized": False}}


def transcribe(job, audio, sample_rate, entry):
    import numpy as np
    import onnxruntime as ort
    from scipy.signal import resample_poly
    from basic_pitch.inference import Model, window_audio_file, unwrap_output
    from basic_pitch.constants import AUDIO_SAMPLE_RATE, AUDIO_N_SAMPLES, FFT_HOP
    from basic_pitch.note_creation import model_output_to_notes

    path = checked_model(entry, job)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.log_severity_level = 3
    job.progress("loading_model", .15, "Loading Basic Pitch ONNX on CPU.")
    duration = len(audio) / sample_rate
    overlapping_frames = 30
    overlap_samples = overlapping_frames * FFT_HOP
    hop_samples = AUDIO_N_SAMPLES - overlap_samples

    class BoundedOnnx(Model):
        def __init__(self):
            # Use the upstream Model.predict mapping with an explicitly limited
            # CPU session; its default constructor uses uncontrolled thread count.
            self.model_type = Model.MODEL_TYPES.ONNX
            self.model = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
            self.windows = 0

        def predict(self, x):
            job.check_cancelled()
            job.progress("transcribing", .2 + .6 * min(.99, self.windows * hop_samples / AUDIO_SAMPLE_RATE / duration),
                         "Detecting pitched note candidates (ONNX CPU, two threads).")
            output = super().predict(x)
            self.windows += 1
            return output

    params = job.request["parameters"]
    model = BoundedOnnx()
    job.progress("preprocessing_audio", .19, "Preparing bounded mono analysis windows; source remains stereo.")
    mono = np.mean(audio, axis=1, dtype=np.float32)
    if sample_rate != AUDIO_SAMPLE_RATE:
        common = gcd(sample_rate, AUDIO_SAMPLE_RATE)
        mono = resample_poly(mono, AUDIO_SAMPLE_RATE // common, sample_rate // common).astype(np.float32)
    original_length = len(mono)
    padded = np.pad(mono, (overlap_samples // 2, 0))
    batches = {"note": [], "onset": [], "contour": []}
    # Reuse upstream 0.4.0 windowing/unwrapping and decoder. Feeding our already
    # frozen PCM avoids a redundant Librosa file decode and lazy/JIT resampler.
    for window, _ in window_audio_file(padded, hop_samples):
        for key, values in model.predict(window[None]).items():
            batches[key].append(values)
    predictions = {key: unwrap_output(np.concatenate(values), original_length, overlapping_frames)
                   for key, values in batches.items()}
    job.progress("decoding_notes", .82, "Decoding note candidates; pitch bends are explicitly disabled in notes-only mode.")
    if original_length < FFT_HOP:
        events = []
    else:
        _, events = model_output_to_notes(predictions, onset_thresh=params["onset_threshold"],
                                         frame_thresh=params["frame_threshold"],
                                         min_note_len=round(params["minimum_note_ms"] / 1000 * AUDIO_SAMPLE_RATE / FFT_HOP),
                                         min_freq=440. * 2 ** ((params["min_pitch"] - 69) / 12),
                                         max_freq=440. * 2 ** ((params["max_pitch"] - 69) / 12),
                                         include_pitch_bends=False, multiple_pitch_bends=False)
    job.progress("validating_notes", .88, "Clipping padding to the exact input range; preserving unquantized note times.")
    notes = []
    clipped = 0
    for start, end, pitch, amplitude, _ in events:
        if not all(np.isfinite(value) for value in (start, end, pitch, amplitude)):
            raise AnalysisError("invalid_result", "Basic Pitch produced a non-finite note.")
        a, b = max(0., float(start)), min(duration, float(end))
        if a != start or b != end:
            clipped += 1
        if b <= a:
            continue
        notes.append({"pitch": int(pitch), "start_seconds": a, "duration_seconds": b - a,
                      "velocity": max(1, min(127, round(float(amplitude) * 127))), "channel": 1})
    return {"notes": validate_notes(notes, duration), "score_kind": "model_activation_not_calibrated",
            "limitations": ["Pitched instruments only; not drum classification or general mixed-instrument transcription.",
                            "Notes only: pitch bends, expressive controllers and original instrument timbre are not preserved."],
            "timing": {"output_time_unit": "seconds", "quantized": False, "padding_clipped_notes": clipped,
                       "model_sample_rate": AUDIO_SAMPLE_RATE, "resampler": "scipy-resample-poly-default-kaiser",
                       "overlap_frames": overlapping_frames, "hop_samples": hop_samples,
                       "leading_padding_samples": overlap_samples // 2},
            "expression": "notes_only"}
