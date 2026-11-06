"""Whole-file MIR evaluation using the previously pinned upstream model loaders.

No cropping, model downloads, CPU fallback, service changes or DAW connection.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path('/root/autodl-tmp/emusician')
GIB = 1024**3


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(source, expected):
    import soundfile as sf
    source = source.resolve()
    if not source.is_relative_to(ROOT) or not source.is_file():
        raise ValueError('Input must be an existing cloud data-root file')
    if source.stat().st_size > 512*1024**2 or digest(source) != expected:
        raise ValueError('Input size or expected SHA does not match')
    info = sf.info(source)
    if info.channels not in (1, 2) or not 8000 <= info.samplerate <= 96000 or not 0 < info.duration <= 1200:
        raise ValueError('Whole-file evaluation admits mono/stereo 8–96kHz up to1200s; rejects rather than truncates')
    # SCNet CPU result/counter/estimated_sources are each four stereo float32
    # arrays, plus mix/padding/resampling. This intentionally conservative
    # admission budget is not a measured peak or a model performance claim.
    pcm = math.ceil(info.duration*48000)*2*4
    return {'path': str(source), 'sha256': expected, 'bytes': source.stat().st_size,
        'frames': info.frames, 'sample_rate': info.samplerate, 'channels': info.channels,
        'duration_seconds': info.duration, 'format': info.format, 'subtype': info.subtype,
        'scope': 'complete_original_file', 'crop_applied': False,
        'required_available_host_bytes': max(8*GIB, 2*GIB+20*pcm+source.stat().st_size*3)}


def wav_stats(path):
    import numpy as np
    import soundfile as sf
    total = 0; squares = 0.0; peak = 0.0; rails = 0
    with sf.SoundFile(path) as audio:
        info = {'frames': len(audio), 'sample_rate': audio.samplerate,
            'channels': audio.channels, 'subtype': audio.subtype,
            'duration_seconds': len(audio)/audio.samplerate}
        for block in audio.blocks(blocksize=65536, dtype='float32', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError('Nonfinite saved stem')
            squares += float(np.sum(block.astype(np.float64)**2))
            peak = max(peak, float(np.abs(block).max(initial=0)))
            rails += int(np.count_nonzero(np.abs(block) >= 1))
            total += block.size
    return {**info, 'finite': True, 'rms': math.sqrt(squares/max(total, 1)),
            'peak': peak, 'at_or_above_unity_fraction': rails/max(total, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=('scnet', 'transkun', 'chordmini'))
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = args.input.resolve()
    metadata = inspect(source, args.sha256)
    if args.inspect:
        print(json.dumps(metadata), flush=True)
        return
    output = args.output.resolve() if args.output else None
    if output is None or not output.is_relative_to(ROOT/'results'):
        raise ValueError('New output must remain under cloud results/')
    output.mkdir(parents=True, exist_ok=False)
    import numpy as np
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly
    sys.path.insert(0, str(ROOT/'tools/models/mir_upgrades'))
    from runtime import load
    torch.set_num_threads(2); torch.set_num_interop_threads(1)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; no implicit CPU retry')
    torch.cuda.set_per_process_memory_fraction(8*GIB/torch.cuda.get_device_properties(0).total_memory)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    model, extras, manifest = load(args.model, 'cuda')
    loaded = time.monotonic()
    result = {'model': args.model, 'status': 'running', 'input': metadata,
        'source_revision': manifest['source_revision'], 'model_revisions': manifest['model_revisions'],
        'script_sha256': digest(__file__), 'model_load_seconds': loaded-started,
        'torch': torch.__version__, 'cuda_runtime': torch.version.cuda,
        'daw_connected': False, 'quality_verified': False, 'outputs': []}
    print(json.dumps({'phase': 'model_loaded', 'model': args.model, 'seconds': loaded-started}), flush=True)
    if args.model in ('scnet', 'transkun'):
        audio, sr = sf.read(source, always_2d=True, dtype='float32')
        if len(audio) != metadata['frames']:
            raise ValueError('Decoded input frames differ from preflight; no truncation allowed')
        target = int(extras['sample_rate'])
        if sr != target:
            factor = math.gcd(sr, target)
            audio = resample_poly(audio, target//factor, sr//factor, axis=0).astype(np.float32)
        if not np.isfinite(audio).all():
            raise ValueError('Input contains nonfinite samples')
        result['decoded_input_frames'] = metadata['frames']
        result['model_input_frames'] = len(audio)
        result['model_sample_rate'] = target
        result['resampling'] = 'scipy.signal.resample_poly' if sr != target else 'none'
    with torch.no_grad():
        if args.model == 'scnet':
            from utils.model_utils import demix
            if audio.shape[1] == 1:
                audio = np.repeat(audio, 2, axis=1)
            config = extras['config']; config.inference.batch_size = 1; config.training.use_amp = True
            stems = demix(config, model, audio.T, torch.device('cuda'), model_type='scnet', pbar=False)
            for name in extras['sources']:
                samples = np.asarray(stems[name], dtype=np.float32).T
                if samples.shape != audio.shape:
                    raise ValueError('Separated stem does not cover whole input')
                path = output/(name+'.wav')
                sf.write(path, samples, target, subtype='FLOAT')
                stats = wav_stats(path)
                if stats['frames'] != len(audio):
                    raise ValueError('Saved stem length differs')
                result['outputs'].append({'path': str(path), **stats})
            result['processing'] = {'upstream': 'utils.model_utils.demix', 'batch_size': 1,
                'chunk_size': config.audio.chunk_size, 'num_overlap': config.inference.num_overlap,
                'amp': True, 'extra_normalization': False, 'output_clipping': False}
        elif args.model == 'transkun':
            from transkun.Data import writeMidi
            import pretty_midi
            events = model.transcribe(torch.from_numpy(audio).to('cuda'), stepInSecond=None,
                segmentSizeInSecond=None, discardSecondHalf=False, mergeIncompleteEvent=True)
            path = output/'piano.mid'; writeMidi(events).write(str(path))
            midi = pretty_midi.PrettyMIDI(str(path))
            notes = [n for i in midi.instruments for n in i.notes]
            controls = [c for i in midi.instruments for c in i.control_changes]
            for note in notes:
                if not (math.isfinite(note.start) and math.isfinite(note.end) and 0 <= note.start < note.end
                        and 0 <= note.pitch <= 127 and 1 <= note.velocity <= 127):
                    raise ValueError('Invalid saved MIDI note')
            for cc in controls:
                if not (math.isfinite(cc.time) and cc.time >= 0 and 0 <= cc.number <= 127 and 0 <= cc.value <= 127):
                    raise ValueError('Invalid saved MIDI control')
            latest = max([n.end for n in notes]+[c.time for c in controls]+[0])
            result['outputs'].append({'path': str(path), 'notes': len(notes), 'control_changes': len(controls),
                'control_numbers': sorted({c.number for c in controls}), 'latest_event_seconds': latest,
                'events_beyond_source_seconds': max(0, latest-metadata['duration_seconds']),
                'structurally_valid': True, 'pedal_events_dropped': False})
            result['processing'] = {'upstream': 'TransKun.transcribe + Data.writeMidi',
                'segment_seconds': model.segmentSizeInSecond, 'hop_seconds': model.segmentHopSizeInSecond,
                'stepInSecond_argument': None, 'segmentSizeInSecond_argument': None,
                'discardSecondHalf': False, 'mergeIncompleteEvent': True,
                'post_trim': False, 'event_times_preserved': True}
        else:
            from src.evaluation.utils.common import extract_song_features
            from src.evaluation.utils.inference import predict_sliding_windows
            config = extras['config']
            features, frame_duration = extract_song_features(str(source), config)
            if not np.isfinite(features).all():
                raise ValueError('Nonfinite CQT features')
            indices = predict_sliding_windows(model, features, extras['mean'], extras['std'],
                int(config.model['seq_len']), 1, 'BTC', 170)
            if len(indices) != len(features):
                raise ValueError('Chord predictions omit feature frames')
            segments = []
            for i, index in enumerate(indices):
                begin = min(metadata['duration_seconds'], i*frame_duration)
                end = min(metadata['duration_seconds'], (i+1)*frame_duration)
                if end <= begin:
                    continue
                label = extras['vocabulary'][int(index)]
                if segments and segments[-1]['label'] == label:
                    segments[-1]['end_seconds'] = end
                else:
                    segments.append({'start_seconds': begin, 'end_seconds': end, 'label': label})
            if not segments or segments[0]['start_seconds'] != 0:
                raise ValueError('Missing chord intervals from complete input')
            trailing_gap = max(0, metadata['duration_seconds']-segments[-1]['end_seconds'])
            if trailing_gap > frame_duration+1/metadata['sample_rate']:
                raise ValueError('Chord feature coverage falls more than one native hop short')
            path = output/'chords.lab'
            path.write_text(''.join(f'{s["start_seconds"]:.6f}\t{s["end_seconds"]:.6f}\t{s["label"]}\n' for s in segments), encoding='utf-8')
            jsonpath = output/'chords.json'; jsonpath.write_text(json.dumps(segments, indent=2)+'\n', encoding='utf-8')
            result['outputs'] += [{'path': str(p), 'segments': len(segments), 'start_seconds': 0,
                'end_seconds': segments[-1]['end_seconds'], 'continuous': True,
                'trailing_uncovered_seconds': trailing_gap,
                'labels_extended_beyond_native_frames': False} for p in (path, jsonpath)]
            result['processing'] = {'upstream': 'extract_song_features + predict_sliding_windows',
                'batch_size': 1, 'vote_aggregation': 'hard', 'smoothing': False,
                'frame_duration_seconds': frame_duration, 'vocabulary_size': 170,
                'feature_frames': len(features), 'prediction_frames': len(indices)}
    torch.cuda.synchronize()
    result.update(status='passed', inference_and_output_seconds=time.monotonic()-loaded,
        total_seconds=time.monotonic()-started, gpu=torch.cuda.get_device_name(),
        peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),
        peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(), allocator_cap_bytes=8*GIB)
    for item in result['outputs']:
        path = Path(item['path']); item.update(bytes=path.stat().st_size, sha256=digest(path))
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
