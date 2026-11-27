"""Original chroma/template/Viterbi baseline with selectable chord vocabulary.

The extended vocabulary is a deterministic recognizer, not a trained jazz model.
Enharmonic/voicing ambiguities retain uncertainty instead of claiming a probability.
"""
from __future__ import annotations

from .common import AnalysisError, MAX_CHORDS

PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
LABELS = tuple(f"{root}:{quality}" for quality in ("maj", "min") for root in PITCH_CLASSES) + ("N",)
QUALITIES = {"maj": (0, 4, 7), "min": (0, 3, 7), "7": (0, 4, 7, 10),
             "maj7": (0, 4, 7, 11), "min7": (0, 3, 7, 10), "dim": (0, 3, 6),
             "aug": (0, 4, 8), "sus2": (0, 2, 7), "sus4": (0, 5, 7),
             "hdim7": (0, 3, 6, 10), "dim7": (0, 3, 6, 9)}


def chord_labels(vocabulary="triads"):
    if vocabulary not in ("triads", "extended"):
        raise AnalysisError("invalid_parameter", "Unsupported chord vocabulary.")
    qualities = ("maj", "min") if vocabulary == "triads" else tuple(QUALITIES)
    return tuple(f"{root}:{quality}" for quality in qualities for root in PITCH_CLASSES) + ("N",)


def templates(vocabulary="triads"):
    import numpy as np
    labels = chord_labels(vocabulary)[:-1]
    result = np.zeros((len(labels), 12), dtype=np.float32)
    for index, label in enumerate(labels):
        name, quality = label.split(":")
        root = PITCH_CLASSES.index(name)
        result[index, [(root + step) % 12 for step in QUALITIES[quality]]] = 1.
    return result / np.linalg.norm(result, axis=1, keepdims=True)


def decode_chroma(chroma, rms, hop_seconds: float, duration: float, sensitivity: float,
                  minimum_region: float, checkpoint=None, vocabulary="triads"):
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
    labels = chord_labels(vocabulary)
    no_chord = len(labels) - 1
    states = len(labels)
    scores = templates(vocabulary) @ unit
    # N is reserved for measured near-silence; ambiguous harmony keeps its best
    # chord plus an explicit uncertainty flag. Scores are NOT probabilities.
    silence = energy < max(1e-5, float(np.max(energy)) * .005)
    emissions = np.empty((states, frames), dtype=np.float64)
    emissions[:no_chord] = scores * 10.
    emissions[no_chord] = -8.
    emissions[:no_chord, silence] = -12.
    emissions[no_chord, silence] = 10.
    stay = .98
    log_stay, log_change = np.log(stay), np.log((1. - stay) / no_chord)
    previous = emissions[:, 0].copy()
    # 133 states exceed int8. Uniform off-diagonal transition probabilities
    # permit an exact O(states) update instead of O(states**2) per audio frame.
    back = np.empty((frames, states), dtype=np.int16)
    back[0] = 0
    indices = np.arange(states, dtype=np.int16)
    for frame in range(1, frames):
        best = int(np.argmax(previous))
        excluding_best = previous.copy()
        excluding_best[best] = -np.inf
        second = int(np.argmax(excluding_best))
        from_other = np.full(states, best, dtype=np.int16)
        from_other[best] = second
        changes = previous[from_other] + log_change
        holds = previous + log_stay
        choose_hold = (holds > changes) | ((holds == changes) & (indices < from_other))
        back[frame] = np.where(choose_hold, indices, from_other)
        previous = np.maximum(holds, changes) + emissions[:, frame]
        if checkpoint and frame % 500 == 0:
            checkpoint(frame / frames)
    path = np.empty(frames, dtype=np.int16)
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
            score = float(np.mean(scores[state, first:frame])) if state != no_chord else 0.
            # A very small best-vs-next margin remains ambiguous even with a
            # high cosine similarity, e.g. relative-major/minor mixtures.
            margin = 1.
            if state != no_chord:
                selected = scores[:, first:frame].copy()
                selected[state] = -1.
                margin = float(np.mean(scores[state, first:frame] - np.max(selected, axis=0)))
            regions.append({"start_seconds": start, "end_seconds": end, "label": labels[state],
                            "score": max(0., min(1., score)),
                            "uncertain": state != no_chord and (score < sensitivity or margin < .04 or end - start < minimum_region)})
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
    params = job.request["parameters"]
    vocabulary = params["vocabulary"]
    job.progress("decoding", .65, "Smoothing chord regions.")
    regions = decode_chroma(chroma, rms, hop / target, len(audio) / sample_rate,
                            params["sensitivity"], params["min_region_seconds"],
                            lambda progress: job.progress("decoding", .65 + progress * .25), vocabulary)
    return {"chord_regions": regions, "score_kind": "uncalibrated_chroma_cosine_similarity",
            "limitations": ["Original template baseline; not a trained jazz-harmony model.",
                            "Inversions, omitted roots and 9/11/13 extensions are not inferred; some pitch-class sets have multiple valid names.",
                            "Scores are similarities, not calibrated correctness probabilities."],
            "timing": {"feature_sample_rate": target, "fft_samples": fft, "hop_samples": hop,
                       "frame_origin_seconds": 0, "quantized": False, "centered_fft": True,
                       "vocabulary": vocabulary, "chord_classes": len(chord_labels(vocabulary))}}
