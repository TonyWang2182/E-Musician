"""Bounded cloud evaluation CLI using pinned upstream inference functions.

Execute only in the model's own environment and a root-scheduled GPU test slot.
This CLI does not connect to the DAW, download models, or alter any service.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

from runtime import ROOT, load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id', choices=('scnet', 'transkun', 'chordmini'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory under cloud results/')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = parser.parse_args()
    import numpy as np
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly

    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT / 'results'):
        raise ValueError('Evaluation audio and output must stay on the authorized cloud data disk')
    info = sf.info(source)
    if info.channels not in (1, 2) or not 0 < info.duration <= 120 or not 8000 <= info.samplerate <= 96000:
        raise ValueError('Evaluation supports 0–120 seconds, mono/stereo, 8–96 kHz')
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    if args.device == 'cuda':
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA requested but unavailable; no implicit CPU retry')
        torch.cuda.reset_peak_memory_stats()
    start = time.monotonic()
    model, extras, manifest = load(args.id, args.device)
    loaded = time.monotonic()
    result = {'id': args.id, 'device': args.device, 'input': str(source),
              'input_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
              'input_duration_seconds': info.duration, 'sample_rate': info.samplerate,
              'source_revision': manifest['source_revision'], 'model_revisions': manifest['model_revisions'],
              'model_load_seconds': loaded - start, 'outputs': [], 'daw_connected': False}
    if args.id in ('scnet', 'transkun'):
        audio, sr = sf.read(source, always_2d=True, dtype='float32')
        target = int(extras['sample_rate'])
        if sr != target:
            factor = math.gcd(sr, target)
            audio = resample_poly(audio, target // factor, sr // factor, axis=0).astype(np.float32)
        if not np.isfinite(audio).all():
            raise ValueError('Non-finite input audio')
    with torch.no_grad():
        if args.id == 'scnet':
            from utils.model_utils import demix
            if audio.shape[1] == 1:
                audio = np.repeat(audio, 2, axis=1)
            config = extras['config']
            config.inference.batch_size = 1
            config.training.use_amp = args.device == 'cuda'
            stems = demix(config, model, audio.T, torch.device(args.device), model_type='scnet', pbar=False)
            for name in extras['sources']:
                samples = np.asarray(stems[name], dtype=np.float32).T
                if not np.isfinite(samples).all() or samples.shape != audio.shape:
                    raise ValueError('Invalid stem samples or duration')
                path = output / f'{name}.wav'
                sf.write(path, samples, target, subtype='FLOAT')
                result['outputs'].append({'path': str(path), 'frames': len(samples),
                    'sample_rate': target, 'channels': samples.shape[1],
                    'rms': float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))})
            result['processing'] = {'upstream_function': 'utils.model_utils.demix',
                'batch_size': 1, 'num_overlap': config.inference.num_overlap,
                'chunk_size': config.audio.chunk_size, 'amp': config.training.use_amp}
        elif args.id == 'transkun':
            from transkun.Data import writeMidi
            events = model.transcribe(torch.from_numpy(audio).to(args.device),
                                      stepInSecond=None, segmentSizeInSecond=None, discardSecondHalf=False)
            midi = writeMidi(events)
            path = output / 'piano.mid'
            midi.write(str(path))
            result['outputs'].append({'path': str(path),
                'notes': sum(len(i.notes) for i in midi.instruments),
                'control_changes': sum(len(i.control_changes) for i in midi.instruments),
                'control_numbers': sorted({cc.number for i in midi.instruments for cc in i.control_changes})})
            result['processing'] = {'upstream_function': 'TransKun.transcribe + Data.writeMidi',
                'segment_seconds': model.segmentSizeInSecond, 'pedal_events_dropped': False}
        else:
            from src.evaluation.utils.common import extract_song_features
            from src.evaluation.utils.inference import predict_sliding_windows
            config = extras['config']
            features, frame_duration = extract_song_features(str(source), config)
            indices = predict_sliding_windows(model, features, extras['mean'], extras['std'],
                int(config.model['seq_len']), 1, 'BTC', 170)
            vocabulary = extras['vocabulary']
            segments = []
            for frame, index in enumerate(indices):
                begin = min(info.duration, frame * frame_duration)
                end = min(info.duration, (frame + 1) * frame_duration)
                label = vocabulary[int(index)]
                if end <= begin:
                    continue
                if segments and segments[-1]['label'] == label:
                    segments[-1]['end_seconds'] = end
                else:
                    segments.append({'start_seconds': begin, 'end_seconds': end, 'label': label})
            path = output / 'chords.lab'
            path.write_text(''.join(f'{s["start_seconds"]:.6f}\t{s["end_seconds"]:.6f}\t{s["label"]}\n' for s in segments))
            (output / 'chords.json').write_text(json.dumps(segments, indent=2) + '\n')
            result['outputs'].append({'path': str(path), 'segments': len(segments),
                                      'frame_duration_seconds': frame_duration, 'vocabulary_size': 170})
            result['processing'] = {'upstream_function': 'extract_song_features + predict_sliding_windows',
                                     'batch_size': 1, 'vote_aggregation': 'hard', 'smoothing': False}
    if args.device == 'cuda':
        torch.cuda.synchronize()
        result['gpu_name'] = torch.cuda.get_device_name()
        result['peak_cuda_allocated_bytes'] = torch.cuda.max_memory_allocated()
        result['peak_cuda_reserved_bytes'] = torch.cuda.max_memory_reserved()
    result['inference_seconds'] = time.monotonic() - loaded
    result['total_seconds'] = time.monotonic() - start
    for item in result['outputs']:
        path = Path(item['path'])
        with path.open('rb') as stream:
            item.update(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
