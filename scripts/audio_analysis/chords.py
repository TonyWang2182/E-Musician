"""Original 24-triad + no-chord chroma/template/Viterbi baseline (not a neural model)."""
from __future__ import annotations

from .common import AnalysisError, MAX_CHORDS

PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
LABELS = tuple(f"{root}:{quality}" for quality in ("maj", "min") for root in PITCH_CLASSES) + ("N",)


def templates():
    import numpy as np
    result = np.zeros((24, 12), dtype=np.float32)
    for quality, third in enumerate((4, 3)):
        for root in range(12):
            result[quality * 12 + root, [(root + step) % 12 for step in (0, third, 7)]] = 1.
    return result / np.linalg.norm(result, axis=1, keepdims=True)


def decode_chroma(chroma, rms, hop_seconds: float, duration: float, sensitivity: float,
                  minimum_region: float, checkpoint=None):
    import numpy as np
    chroma = np.asarray(chroma, dtype=np.float32)
    if chroma.ndim != 2 or chroma.shape[0] != 12 or chroma.shape[1] == 0:
        raise AnalysisError("invalid_features", "Chord feature matrix is empty or has invalid dimensions.")
    if not np.isfinite(chroma).all() or not np.isfinite(rms).all():
        raise AnalysisError("invalid_features", "Chord feature extraction returned non-finite values.")
    frames = chroma.shape[1]
    energy = np.asarray(rms)[:frames]
    if len(energy) != frames:
        raise AnalysisError("invalid_features", "Chord energy/feature frame alignment mismatch.")
    unit = chroma / np.maximum(np.linalg.norm(chroma, axis=0, keepdims=True), 1e-9)
    scores = templates() @ unit
    # N is reserved for measured near-silence; ambiguous harmony keeps its best
    # triad plus an explicit uncertainty flag. Scores are NOT probabilities.
    silence = energy < max(1e-5, float(np.max(energy)) * .005)
    emissions = np.empty((25, frames), dtype=np.float64)
    emissions[:24] = scores * 10.
    emissions[24] = -8.
    emissions[:24, silence] = -12.
    emissions[24, silence] = 10.
    stay = .98
    transition = np.full((25, 25), np.log((1. - stay) / 24.))
    np.fill_diagonal(transition, np.log(stay))
    previous = emissions[:, 0].copy()
    back = np.empty((frames, 25), dtype=np.int8)
    back[0] = 0
    for frame in range(1, frames):
        candidates = previous[:, None] + transition
        back[frame] = np.argmax(candidates, axis=0)
        previous = candidates[back[frame], np.arange(25)] + emissions[:, frame]
        if checkpoint and frame % 500 == 0:
            checkpoint(frame / frames)
    path = np.empty(frames, dtype=np.int8)
    path[-1] = np.argmax(previous)
    for frame in range(frames - 1, 0, -1):
        path[frame - 1] = back[frame, path[frame]]
    regions = []
    first = 0
    for frame in range(1, frames + 1):
        if frame < frames and path[frame] == path[first]:
            continue
        start = min(duration, first * hop_seconds)
        end = min(duration, frame * hop_seconds) if frame < frames else duration
        state = int(path[first])
        if end > start:
            score = float(np.mean(scores[state, first:frame])) if state != 24 else 0.
            # A very small best-vs-next margin remains ambiguous even with a
            # high cosine similarity, e.g. relative-major/minor mixtures.
            margin = 1.
            if state != 24:
                selected = scores[:, first:frame].copy()
                selected[state] = -1.
                margin = float(np.mean(scores[state, first:frame] - np.max(selected, axis=0)))
            regions.append({"start_seconds": start, "end_seconds": end, "label": LABELS[state],
                            "score": max(0., min(1., score)),
                            "uncertain": state != 24 and (score < sensitivity or margin < .04 or end - start < minimum_region)})
        first = frame
    if len(regions) > MAX_CHORDS:
        raise AnalysisError("result_limit", "More than 10000 chord regions; choose a shorter range.")
    return regions


def pitch_class_features(mono, sample_rate=22050, fft=4096, hop=512):
    """Centered Hann STFT folded through smooth semitone filters, C first.

    This original implementation deliberately has no Librosa/Numba import or
    first-job JIT. It is a fixed-tuning baseline, not a trained chord network.
    """
    import numpy as np
    from scipy.signal import stft
    if len(mono) < fft:
        # Keep the FFT size stable for very short clips. Padding is discarded
        # by the final duration clamp, not exposed as extra chord regions.
        mono = np.pad(mono, (0, fft - len(mono)))
    frequencies, _, spectrum = stft(mono, fs=sample_rate, window="hann", nperseg=fft,
                                    noverlap=fft - hop, nfft=fft, boundary="zeros", padded=True)
    power = np.abs(spectrum) ** 2
    active = (frequencies >= 55.) & (frequencies <= 3500.)
    midi = 69. + 12. * np.log2(np.maximum(frequencies, 1.) / 440.)
    distance = (midi[None, :] - np.arange(12)[:, None] + 6.) % 12. - 6.
    filters = np.exp(-.5 * (distance / .5) ** 2)
    filters *= active[None, :] * (np.maximum(frequencies, 55.) / 440.) ** -.25
    filters /= np.maximum(np.linalg.norm(filters, axis=1, keepdims=True), 1e-9)
    chroma = (filters @ power).astype(np.float32)
    energy = np.sqrt(np.sum(power, axis=0))
    return chroma, energy


def analyze(job, audio, sample_rate, entry):
    import numpy as np
    from scipy.signal import resample_poly
    from math import gcd
    mono = np.mean(audio, axis=1)
    target = 22050
    if sample_rate != target:
        common = gcd(sample_rate, target)
        mono = resample_poly(mono, target // common, sample_rate // common).astype(np.float32)
    # A centered STFT has its frame at t=frame*hop/sr. No unreported FFT
    # half-window delay is added to the exported label regions.
    job.progress("features", .25, "Computing harmonic pitch classes (CPU baseline).")
    fft = 4096
    hop = 512
    chroma, rms = pitch_class_features(mono, target, fft, hop)
    job.progress("decoding", .65, "Smoothing 24 triad labels and no-chord regions.")
    params = job.request["parameters"]
    regions = decode_chroma(chroma, rms, hop / target, len(audio) / sample_rate,
                            params["sensitivity"], params["min_region_seconds"],
                            lambda progress: job.progress("decoding", .65 + progress * .25))
    return {"chord_regions": regions, "score_kind": "uncalibrated_chroma_cosine_similarity",
            "limitations": ["24 major/minor triads and N only; inversions and extended chords need manual review.",
                            "Scores are similarities, not calibrated correctness probabilities."],
            "timing": {"feature_sample_rate": target, "fft_samples": fft, "hop_samples": hop,
                       "frame_origin_seconds": 0, "quantized": False, "centered_fft": True}}
