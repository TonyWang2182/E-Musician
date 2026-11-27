"""Production-sized, bounded inference using the pinned and previously tested APIs.

Imported only by isolated model workers. There is no network or CPU fallback.
"""
from __future__ import annotations
import dataclasses
import math
from pathlib import Path
import shutil
import sys
import time
from .normalize import add_artifact, empty_result, midi_tracks, score_events, set_tracks
from .protocol import atomic_json


def read_audio(source, target=None):
    import numpy as np
    import soundfile as sf
    audio, rate = sf.read(source, dtype='float32', always_2d=True)
    if not np.isfinite(audio).all():
        raise ValueError('Input contains nonfinite audio')
    if target is not None and target != rate:
        # MuScriptor consumes the original rate and performs its own conversion.
        # Its pinned environment does not require SciPy; only the adapters that
        # explicitly request a different rate need this optional dependency.
        from scipy.signal import resample_poly
        divisor = math.gcd(rate, target)
        audio = resample_poly(audio, target // divisor, rate // divisor, axis=0).astype(np.float32)
        rate = target
    return audio, rate


def mir(root, request, source, output, manifest, duration, phase):
    import numpy as np
    import soundfile as sf
    import torch
    sys.path.insert(0, str(root / 'tools/models/mir_upgrades'))
    from runtime import load
    model_id = request['model_id']
    phase('loading')
    model, extras, _ = load(model_id, 'cuda')
    result = empty_result(request, manifest, duration)
    phase('running')
    with torch.inference_mode():
        if model_id in ('scnet', 'transkun'):
            audio, rate = read_audio(source, int(extras['sample_rate']))
        if model_id == 'scnet':
            from utils.model_utils import demix
            if audio.shape[1] == 1:
                audio = np.repeat(audio, 2, axis=1)
            config = extras['config']; config.inference.batch_size = 1; config.training.use_amp = True
            stems = demix(config, model, audio.T, torch.device('cuda'), model_type='scnet', pbar=False)
            phase('postprocessing')
            if set(extras['sources']) != {'vocals', 'drums', 'bass', 'other'}:
                raise ValueError('The configured SCNet weights do not have the expected four stems')
            for name in ('vocals', 'drums', 'bass', 'other'):
                samples = np.asarray(stems[name], dtype=np.float32).T
                if samples.shape != audio.shape or not np.isfinite(samples).all():
                    raise ValueError('Separated stem geometry is invalid')
                path = output / (name + '.wav'); sf.write(path, samples, rate, subtype='FLOAT')
                item = add_artifact(result, path, 'stem')
                result['stems'].append({**item, 'path': item['id'], 'name': name})
            result['processing'] = {'upstream': 'utils.model_utils.demix', 'batch_size': 1,
                'chunk_size': config.audio.chunk_size, 'num_overlap': config.inference.num_overlap,
                'amp': True, 'output_clipping': False, 'complete_input': True}
        elif model_id == 'transkun':
            from transkun.Data import writeMidi
            events = model.transcribe(torch.from_numpy(audio).to('cuda'), stepInSecond=None,
                segmentSizeInSecond=None, discardSecondHalf=False, mergeIncompleteEvent=True)
            phase('postprocessing')
            path = output / 'piano.mid'; writeMidi(events).write(str(path))
            tracks, edges = midi_tracks(path, duration); set_tracks(result, tracks)
            result['selection_boundary_processing'] = edges
            add_artifact(result, path, 'native_midi')
            result['processing'] = {'upstream': 'TransKun.transcribe', 'segment_seconds': model.segmentSizeInSecond,
                'hop_seconds': model.segmentHopSizeInSecond, 'discardSecondHalf': False,
                'mergeIncompleteEvent': True, 'pedal_events_preserved': True}
        else:
            from src.evaluation.utils.common import extract_song_features
            from src.evaluation.utils.inference import predict_sliding_windows
            config = extras['config']
            features, hop = extract_song_features(str(source), config)
            if not np.isfinite(features).all():
                raise ValueError('Nonfinite chord features')
            indices = predict_sliding_windows(model, features, extras['mean'], extras['std'],
                int(config.model['seq_len']), 1, 'BTC', 170)
            if len(indices) != len(features):
                raise ValueError('Chord predictions omit input feature frames')
            segments = []
            for index, label_id in enumerate(indices):
                start, end = min(duration, index*hop), min(duration, (index+1)*hop)
                label = extras['vocabulary'][int(label_id)]
                if end <= start:
                    continue
                if segments and segments[-1]['label'] == label:
                    segments[-1]['end_seconds'] = end
                else:
                    segments.append({'label': label, 'raw_label': label, 'start_seconds': start,
                                     'end_seconds': end, 'score': None, 'uncertain': True})
            result['chord_regions'] = segments
            trailing = max(0, duration - (segments[-1]['end_seconds'] if segments else 0))
            if trailing > hop + 1 / 8000:
                raise ValueError('Chord features omit more than one trailing native hop')
            result['processing'] = {'batch_size': 1, 'vocabulary_size': 170, 'frame_duration_seconds': hop,
                'trailing_uncovered_seconds': trailing, 'smoothing': False, 'confidence_calibrated': False}
            result['warnings'].append('Fixed 170-label vocabulary; arbitrary jazz extensions and inversions are unsupported.')
            atomic_json(output / 'chords.json', segments)
            (output / 'chords.lab').write_text(''.join(f'{s["start_seconds"]:.6f}\t{s["end_seconds"]:.6f}\t{s["label"]}\n' for s in segments), encoding='utf-8')
            add_artifact(result, output / 'chords.json', 'native_chords')
            add_artifact(result, output / 'chords.lab', 'native_chords')
    return result


def muscriptor(root, request, source, output, manifest, duration, phase):
    import numpy as np
    import torch
    from muscriptor import TranscriptionModel
    from muscriptor.events import ProgressEvent
    phase('loading')
    model = TranscriptionModel.load_model(weights_path=root / 'models/muscriptor/model.safetensors',
                                         device='cuda', dtype='float32')
    audio, rate = read_audio(source)
    waveform = torch.from_numpy(np.ascontiguousarray(audio.T))
    phase('running')
    events = list(model.transcribe((waveform, rate), use_sampling=False, cfg_coef=1.0,
        instruments=None, batch_size=1, no_eos_is_ok=False, beam_size=1, prelude_forcing=True))
    progress = [event for event in events if isinstance(event, ProgressEvent)]
    if not progress or progress[-1].completed != progress[-1].total:
        raise ValueError('MuScriptor did not finish all audio chunks')
    phase('postprocessing')
    atomic_json(output / 'events.json', [{'type': type(e).__name__, **dataclasses.asdict(e)} for e in events])
    path = output / 'transcription.mid'; path.write_bytes(model.events_to_midi_bytes(iter(events)))
    result = empty_result(request, manifest, duration)
    tracks, edges = midi_tracks(path, duration); set_tracks(result, tracks)
    result['selection_boundary_processing'] = edges
    result['processing'] = {'use_sampling': False, 'cfg_coef': 1.0, 'instruments': None, 'batch_size': 1,
        'no_eos_is_ok': False, 'beam_size': 1, 'prelude_forcing': True,
        'completed_chunks': progress[-1].completed, 'actual_velocity_prediction': False,
        'midi_tempo_is_export_default': True}
    result['warnings'].append('MuScriptor MIDI velocity and tempo are export defaults, not measured performance or BPM.')
    add_artifact(result, path, 'native_midi'); add_artifact(result, output / 'events.json', 'native_events')
    return result


def sheetsage2(root, request, source, output, manifest, duration, phase):
    from transformers import AutoModel
    phase('loading')
    model = AutoModel.from_pretrained(str(root / 'models/sheetsage2'), trust_remote_code=True,
        local_files_only=True, base_model_path=str(root / 'models/mert2')).eval().to('cuda')
    phase('running')
    native = output / 'native'; last = [0.0]
    def progress(event):
        now = time.monotonic()
        if now - last[0] > 2:
            last[0] = now
            phase('running')
    raw = model.transcribe(source, output_dir=native, dtype='bf16', preset='default', progress=progress)
    if abs(raw['duration_seconds'] - duration) > .15:
        raise ValueError('SheetSage2 duration does not match the complete submitted audio')
    phase('postprocessing')
    result = empty_result(request, manifest, duration)
    result.update(score_events(raw['events'], duration))
    # Melody MIDI contains actual model-predicted melody. Chord playback MIDI is
    # derived from symbolic labels and is not relabelled as note transcription.
    tracks, edges = midi_tracks(native / 'melody.mid', duration); set_tracks(result, tracks)
    result['selection_boundary_processing'] = edges
    for name, role in (('melody.mid', 'native_midi'), ('events.json', 'native_events'),
                       ('score.abc', 'score'), ('chord.lab', 'native_chords'),
                       ('structure.lab', 'native_structure'), ('beat.lab', 'native_beats')):
        path = native / name
        if path.is_file() and path.stat().st_size:
            shutil.copyfile(path, output / name); add_artifact(result, output / name, role)
    result['processing'] = {'preset': 'default', 'dtype': 'bf16', 'window_seconds': raw['window_seconds'],
        'windows': raw['windows'], 'complete_input': True, 'midi_velocity_is_export_default': True,
        'token_limit_reached': any(w['tokens'] >= int(model.max_output_seq_len) for w in raw['windows'])}
    result['warnings'] += [str(w)[:500] for w in raw.get('warnings', [])[:20]]
    if raw.get('abc_error'):
        result['warnings'].append('ABC export unavailable: ' + str(raw['abc_error'])[:300])
    return result


def ace(root, request, output, manifest, phase):
    sys.path.insert(0, str(root / 'tools'))
    from ace_worker import AceGenerator
    generator = AceGenerator(root)
    original = generator(request['parameters'], output, phase, lambda: False)
    artifact = original['artifacts'][0]
    result = empty_result(request, manifest, artifact['duration_seconds'])
    result['model'].update(original['model']); result['model']['id'] = request['model_id']
    result['conditioning'] = original['conditioning']; result['metrics'].update(original['metrics'])
    add_artifact(result, output / 'audio.wav', 'generated_audio')
    result['truncated'] = None
    return result


def yue2(root, request, output, manifest, phase):
    import soundfile as sf
    from yue2 import YuE2Pipeline
    from yue2.pipeline import SongResult
    from yue2.protocol import GenerationConfig, make_request
    from yue2.storage import identity
    parameters = request['parameters']
    maximum = int(math.ceil(parameters['duration_seconds'] * 25))
    minimum = max(32, int(maximum * .9))
    config = GenerationConfig.from_dict({'semantic': {'min_tokens': minimum, 'max_tokens': maximum}})
    style = parameters['prompt'] + '\nRequested tempo: ' + str(parameters['bpm']) + ' BPM. Meter: ' + parameters['time_signature'] + '.'
    if parameters['instrumental']:
        style += ' Instrumental; no full sung vocal.'
    typed = make_request(id=request['request_id'], style=style, lyrics=parameters['lyrics'], cot='full', seed=parameters['seed'])
    model = root / 'models/yue2/YuE2-3B/8f24312f187763b9854adeec87e437e2b03bbff1'
    vae = root / 'models/yue2/YuE2-Vae/152733a19ad43aa67e367f9b5503ef8075bb5126'
    phase('loading')
    with YuE2Pipeline.from_pretrained(str(model), vae=str(vae), local_files_only=True, device='cuda',
            backend='torch-eager', low_vram=True, memory_budget_gib=12, vae_core_frames=512,
            generation_config=config, progress=False) as pipe:
        effective = pipe.effective_config(typed)
        job_identity = identity({'request': typed.to_dict(), 'config': effective, 'weights': pipe.weights})
        phase('running'); began = time.perf_counter()
        plan = pipe.plan(request=typed); plan.save(output / 'plan')
        semantic = pipe.generate_semantic(plan)
        latents = pipe.synthesize(semantic)
        audio = pipe.decode(latents)
        native = SongResult(audio, 48000, semantic, latents, effective, pipe.weights,
            {'e2e_seconds': time.perf_counter()-began}, job_identity)
        phase('postprocessing')
        native.save(output / 'native-audio.wav')
        samples, rate = sf.read(output / 'native-audio.wav', dtype='float32', always_2d=True)
        # Upstream clamps its decoded audio; only encoding changes here. Keep the
        # float original on the cloud and declare the portable PCM16 conversion.
        sf.write(output / 'audio.wav', samples, rate, subtype='PCM_16')
        result = empty_result(request, manifest, len(samples) / rate)
        result['conditioning'] = {'requested_duration_seconds': parameters['duration_seconds'],
            'bpm': parameters['bpm'], 'time_signature': parameters['time_signature'],
            'timing_is_exact': False, 'semantic_min_tokens': minimum, 'semantic_max_tokens': maximum,
            'style_conditioning': style, 'post_crop': False}
        result['truncated'] = native.truncated
        result['processing'] = {'semantic_tokens': len(semantic.tokens), 'abc_tokens': len(plan.abc_ids),
            'effective_generation_config': effective, 'memory_budget_gib': 12,
            'output_conversion': 'upstream FLOAT to PCM16; no duration crop'}
        result['warnings'].append('Duration uses semantic token limits; natural stopping, song structure and tempo adherence require listening.')
        add_artifact(result, output / 'audio.wav', 'generated_audio')
        if (output / 'plan/score.abc').is_file():
            shutil.copyfile(output / 'plan/score.abc', output / 'score.abc')
            add_artifact(result, output / 'score.abc', 'generated_score')
        return result
