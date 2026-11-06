"""Optional two-thread CPU BeatThis estimate; no octave normalization to the prompt."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import time
import numpy as np
import soundfile as sf
from analyze import ROOT, digest, write_json

WEIGHT = ROOT/'models/mir/beat-this/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c/final0.ckpt'
WEIGHT_SHA = '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331'


def tempo(beats):
    if len(beats) < 5:
        return None
    span = 8 if len(beats) >= 17 else 1
    intervals = (beats[span:]-beats[:-span])/span
    return float(60/np.median(intervals)) if len(intervals) and np.all(intervals > 0) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix' or os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('CPU worker requires CUDA_VISIBLE_DEVICES empty before startup')
    if not WEIGHT.is_file() or digest(WEIGHT) != WEIGHT_SHA:
        raise RuntimeError('Pinned local BeatThis weight missing or changed; never download fallback')
    import torch
    from beat_this.inference import Audio2Beats
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    assert not torch.cuda.is_initialized()
    info = sf.info(args.input)
    if not 0 < info.duration <= 600:
        raise ValueError('Beat estimate bounded to at most600seconds')
    audio, rate = sf.read(args.input, dtype='float32', always_2d=True)
    if not np.isfinite(audio).all():
        raise ValueError('Beat model does not receive nonfinite samples')
    started = time.monotonic()
    tracker = Audio2Beats(checkpoint_path=str(WEIGHT), device='cpu', float16=False, dbn=False)
    with torch.inference_mode():
        beats, downbeats = tracker(audio, rate)
    beats, downbeats = np.asarray(beats), np.asarray(downbeats)
    for values in (beats, downbeats):
        if not np.isfinite(values).all() or not np.all(np.diff(values) > 0) or np.any(values < 0) or np.any(values > info.duration+.04):
            raise ValueError('Invalid estimated beat positions')
    assert not torch.cuda.is_initialized()
    raw = tempo(beats)
    intervals = np.diff(beats)
    variability = float((np.percentile(intervals,75)-np.percentile(intervals,25))/np.median(intervals)) if len(intervals) >= 4 else None
    # This is a descriptive heuristic, not model confidence or a quality grade.
    stability = 'insufficient_beats' if raw is None else 'variable_intervals' if variability is not None and variability > .2 else 'relatively_consistent_intervals'
    windows = []
    for start in np.arange(0, info.duration, 20):
        end = min(float(start+20), info.duration)
        local = beats[(beats >= start) & (beats < end)]
        windows.append({'start_seconds':float(start),'end_seconds':end,'beat_count':len(local),'raw_bpm':tempo(local)})
    report = {'status':'estimated','model':'BeatThis final0','source_revision':'b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c',
        'weight_sha256':WEIGHT_SHA,'input_sha256':digest(args.input),'device':'cpu','torch_threads':2,
        'cuda_initialized':False,'package':importlib.metadata.version('beat-this'),'torch':torch.__version__,
        'postprocessor':'upstream minimal; no DBN; no target-BPM constraint','raw_bpm':raw,
        'raw_bpm_method':'60 / median duration per beat over8-beat spans when >=17beats, else median single IBI; no half/double correction',
        'median_single_interval_bpm':float(60/np.median(intervals)) if len(intervals) >=4 else None,
        'half_raw_double_bpm':[] if raw is None else [raw/2,raw,raw*2],
        'prompt_reference_half_raw_double_bpm':[85,170,340],
        'interval_iqr_over_median':variability,'stability':stability,
        'stability_method':'Insufficient <5beats; variable when IBI IQR/median >0.2; heuristic only, not calibrated confidence',
        'beat_times_seconds':beats.tolist(),'downbeat_times_seconds':downbeats.tolist(),
        'windows_20_seconds':windows,'elapsed_seconds':time.monotonic()-started,
        'limitation':'Estimated beat track, not ground truth. Half/double-time ambiguity and missing/extra beats remain. Does not establish170BPM, style, instruments or six sections.'}
    write_json(args.output, report)
    print(json.dumps({'status':report['status'],'raw_bpm':raw,'beat_count':len(beats),'elapsed_seconds':report['elapsed_seconds']}))


if __name__ == '__main__':
    main()
