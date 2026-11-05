"""Pinned Beat This! inference and conservative beat/meter summaries.

Beat timestamps are measured by the official pretrained network. Meter and
tempo are summaries of those predictions, not a separate trained classifier.
"""
from __future__ import annotations
import math
from pathlib import Path
from statistics import median
from .common import AnalysisError, sha256_file

CODE_REVISION = "b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c"
CHECKPOINT_URL = "https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt"
# Filled from the recorded official download; registration never silently
# upgrades this checkpoint when the remote filename changes.
CHECKPOINT_SHA256 = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
MAX_BEATS = 10000


def summarize(beats, downbeats, duration, meter="auto"):
    if meter not in ("auto", "3/4", "4/4"):
        raise AnalysisError("invalid_parameter", "Unsupported beat meter option.")
    def times(values):
        if len(values) > MAX_BEATS:
            raise AnalysisError("result_limit", "Too many beat candidates; select a shorter range.")
        if any(not math.isfinite(float(v)) for v in values):
            raise AnalysisError("invalid_result", "Non-finite beat prediction.")
        return sorted(set(float(v) for v in values if 0 <= float(v) < duration))
    beat_times, down_times = times(beats), times(downbeats)
    # Official minimal postprocessing promotes every detected downbeat to a
    # beat; this union also preserves that invariant across model updates.
    beat_times = sorted(set(beat_times) | set(down_times))
    if len(beat_times) > MAX_BEATS:
        raise AnalysisError("result_limit", "Too many beat candidates.")
    down_set = set(down_times)
    events = [{"time_seconds": t, "is_downbeat": t in down_set} for t in beat_times]
    intervals = [b-a for a,b in zip(beat_times, beat_times[1:]) if b > a]
    period = median(intervals) if len(intervals) >= 3 else None
    bpm = 60/period if period and 20 <= 60/period <= 300 else None
    variable = bool(period and (median(abs(v-period) for v in intervals)/period > .08
                               or sum(abs(v-period)/period > .15 for v in intervals)/len(intervals) > .25))
    indices = [i for i,event in enumerate(events) if event["is_downbeat"]]
    counts = [b-a for a,b in zip(indices, indices[1:])]
    numerator = 0
    if meter != "auto":
        numerator = int(meter[0])
    elif len(counts) >= 2:
        votes = {n: counts.count(n) for n in (3,4)}
        winner = max(votes, key=votes.get)
        if votes[winner]/len(counts) >= .75:
            numerator = winner
    tempo = {"bpm": bpm, "first_beat_seconds": beat_times[0] if beat_times else None,
             "first_downbeat_seconds": down_times[0] if down_times else None,
             "meter_numerator": numerator, "meter_denominator": 4,
             "meter_supported": numerator in (3,4), "meter_source": "manual" if meter != "auto" else "downbeat_spacing",
             "tempo_candidates": [bpm*factor for factor in (.5,1,2) if 20 <= bpm*factor <= 300] if bpm else [],
             "variable_tempo": variable, "confidence_kind": "uncalibrated_beat_consistency"}
    return {"beat_events": events, "tempo": tempo,
            "limitations": ["Beat/downbeat predictions may be wrong; review the first downbeat and tempo before applying.",
                "Meter is inferred from predicted downbeat spacing; only 3/4 and 4/4 are supported. Compound or changing meter requires manual correction.",
                "Warp currently uses one fixed ratio; variable-tempo performances are not automatically straightened."]}


def analyze(job, audio, rate, entry):
    import numpy as np
    from .providers import waveform_peaks
    if len(audio)/rate < .25:
        job.progress("insufficient_audio",.8,"This range is too short to establish a pulse.")
        result=summarize([],[],len(audio)/rate,job.request["parameters"]["meter"])
        result["waveform_peaks"]=waveform_peaks(audio)
        result["runtime_metrics"]={"device":"none-insufficient-audio","cpu_fallback":False}
        return result
    import torch
    from beat_this.inference import Audio2Beats
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    path = Path(entry["model_path"])
    if not path.is_file() or sha256_file(path, job) != entry.get("weight_sha256"):
        raise AnalysisError("model_changed", "Beat This! checkpoint is missing or changed; rerun explicit setup.")
    duration = len(audio)/rate
    job.progress("loading_model", .15, "Loading local Beat This! checkpoint.")
    device = entry.get("device", "cpu")
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    if device == "cuda":torch.cuda.reset_peak_memory_stats()
    fallback = False
    def infer(selected_device):
        model = Audio2Beats(str(path), device=selected_device, float16=False, dbn=False)
        chunks = max(1, math.ceil(duration/29.76));done = 0
        def progress(module, inputs):
            nonlocal done
            job.progress("tracking_beats", .25 + .6*min(done/chunks,1), "Tracking beats and downbeats locally.")
            done += 1
        model.model.register_forward_pre_hook(progress)
        with torch.inference_mode():
            return model(np.asarray(audio, dtype=np.float32), rate)
    try:
        beats, downbeats = infer(device)
    except torch.cuda.OutOfMemoryError:
        if device != "cuda":raise
        torch.cuda.empty_cache();device="cpu";fallback=True
        job.progress("cpu_fallback", .2, "GPU memory busy; retrying beat tracking on CPU.")
        beats, downbeats = infer(device)
    job.check_cancelled()
    # Silence is not a tempo source even if a network emits isolated guesses.
    if float(np.max(np.abs(audio), initial=0)) < 1e-7:
        beats, downbeats = [], []
    result = summarize(beats, downbeats, duration, job.request["parameters"]["meter"])
    result["waveform_peaks"] = waveform_peaks(audio)
    result["runtime_metrics"] = {"device": device, "cpu_fallback": fallback}
    if device == "cuda":
        result["runtime_metrics"].update(peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
                                         peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved())
    return result
