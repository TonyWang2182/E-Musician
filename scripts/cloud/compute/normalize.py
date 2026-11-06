"""Explicit seconds/channel normalization; originals remain separate artifacts."""
from __future__ import annotations
from bisect import bisect_right
from collections import defaultdict, deque
from fractions import Fraction
import math
from pathlib import Path
import re
from .protocol import digest, number, text, wav_info
from .protocol import canonical
import hashlib


def empty_result(request, manifest, duration):
    model = {'id': request['model_id'], 'model_id': request['model_id'],
             'source_revision': manifest.get('source_revision'),
             'model_revisions': manifest.get('model_revisions', manifest.get('model', {})),
             'provider': 'cloud', 'quality_verified': False}
    model['revision'] = hashlib.sha256(canonical(model['model_revisions']).encode('utf-8')).hexdigest()
    return {'schema_version': 2, 'kind': request['kind'], 'model': model,
            'duration_seconds': duration,
            'time_basis': 'output_relative_seconds' if request['kind'] == 'generate' else 'input_relative_seconds',
            'artifacts': [], 'stems': [], 'notes': [], 'controllers': [], 'midi_tracks': [],
            'chord_regions': [], 'beat_events': [], 'structure_regions': [], 'annotations': [],
            'tempo': None, 'warnings': [], 'metrics': {}, 'parameters': request['parameters']}


def audio_artifact(path, role):
    import numpy as np
    import soundfile as sf
    info = wav_info(path)
    peaks = [0.0] * 128
    squares = 0.0; count = 0; peak = 0.0; offset = 0
    with sf.SoundFile(path) as stream:
        for block in stream.blocks(blocksize=65536, dtype='float32', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError('Nonfinite audio artifact')
            values = np.max(np.abs(block), axis=1)
            peak = max(peak, float(values.max(initial=0)))
            squares += float(np.sum(block.astype(np.float64) ** 2)); count += block.size
            bins = np.minimum(127, ((np.arange(len(block)) + offset) * 128) // info['frames'])
            for bucket in np.unique(bins):
                peaks[int(bucket)] = max(peaks[int(bucket)], float(values[bins == bucket].max(initial=0)))
            offset += len(block)
    return {'id': path.name, 'role': role, 'sha256': digest(path), **info,
            'peak': peak, 'rms': math.sqrt(squares / max(1, count)), 'waveform_peaks': peaks}


def add_artifact(result, path, role):
    path = Path(path)
    item = (audio_artifact(path, role) if path.suffix.lower() == '.wav' else
            {'id': path.name, 'role': role, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    if any(a['id'] == item['id'] for a in result['artifacts']):
        raise ValueError('Duplicate artifact name')
    result['artifacts'].append(item)
    return item


def midi_tracks(path, duration):
    """Read original MIDI tempo map; convert channels 0–15 to DAW 1–16.

    The native MIDI stays unchanged. Candidate edges are clipped only to the
    submitted selection; padding/truncation counts are returned explicitly.
    """
    import mido
    midi = mido.MidiFile(path)
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError('Asynchronous/SMPTE MIDI is not supported')
    tempos = [(0, 500000)]; all_events = []
    for track in midi.tracks:
        tick = 0; events = []
        for message in track:
            tick += message.time
            if message.time < 0:
                raise ValueError('Negative MIDI delta time')
            events.append((tick, message))
            if message.type == 'set_tempo':
                tempos.append((tick, message.tempo))
        all_events.append(events)
    tempo_map = {}
    for tick, tempo in sorted(tempos, key=lambda x: x[0]):
        tempo_map[tick] = tempo
    ticks = sorted(tempo_map); seconds = [0.0]
    for index in range(1, len(ticks)):
        seconds.append(seconds[-1] + (ticks[index] - ticks[index-1]) * tempo_map[ticks[index-1]] / midi.ticks_per_beat / 1e6)
    def to_seconds(tick):
        index = bisect_right(ticks, tick) - 1
        return seconds[index] + (tick-ticks[index]) * tempo_map[ticks[index]] / midi.ticks_per_beat / 1e6
    tracks = []; clipped = dropped = unmatched = 0
    for track_index, events in enumerate(all_events):
        name = next((m.name for _, m in events if m.type == 'track_name'), 'Transcription')
        name = ' '.join(name.split())[:128] or 'Transcription'
        programs = defaultdict(int); active = defaultdict(deque); groups = {}
        def group(channel, program):
            key = (channel, program)
            if key not in groups:
                groups[key] = {'id': f'track-{track_index}-{channel+1}-{program}', 'name': name,
                    'instrument': name, 'program': program, 'is_drum': channel == 9,
                    'channel': channel+1, 'notes': [], 'controllers': []}
            return groups[key]
        for tick, message in events:
            instant = to_seconds(tick)
            if message.type == 'program_change':
                programs[message.channel] = message.program
            elif message.type == 'note_on' and message.velocity:
                active[(message.channel, message.note)].append((instant, message.velocity, programs[message.channel]))
            elif message.type == 'note_off' or (message.type == 'note_on' and not message.velocity):
                key = (message.channel, message.note)
                if not active[key]:
                    unmatched += 1; continue
                start, velocity, program = active[key].popleft()
                end = min(instant, duration)
                if start >= duration or end <= start:
                    dropped += 1; continue
                clipped += instant > duration
                group(message.channel, program)['notes'].append({'pitch': message.note, 'start_seconds': start,
                    'duration_seconds': end-start, 'velocity': velocity, 'channel': message.channel+1})
            elif message.type == 'control_change':
                if instant > duration:
                    dropped += 1; continue
                group(message.channel, programs[message.channel])['controllers'].append({'time_seconds': instant,
                    'controller': message.control, 'value': message.value, 'channel': message.channel+1})
        unmatched += sum(len(values) for values in active.values())
        for item in groups.values():
            item['notes'].sort(key=lambda n: (n['start_seconds'], n['pitch']))
            if item['notes'] or item['controllers']:
                tracks.append(item)
    if unmatched:
        raise ValueError(f'Native MIDI contains {unmatched} unmatched note events')
    return tracks, {'selection_edge_clipped_notes': clipped, 'padding_events_excluded_from_candidate': dropped,
                    'raw_midi_preserved': True}


def set_tracks(result, tracks):
    result['midi_tracks'] = tracks
    result['notes'] = [{**note, 'track_id': track['id']} for track in tracks for note in track['notes']]
    result['controllers'] = [{**control, 'track_id': track['id']} for track in tracks for control in track['controllers']]


def score_events(events, duration):
    """Use actual SheetSage2 decoded field meanings, not notation filler beats."""
    structures = []; chords = []; beats = []; annotations = []; meter = None
    for event in events:
        instant = number(event['time'], 0, duration + 0.15)
        if instant > duration:
            continue
        values = event['values']
        for field, target in (('structure', structures), ('chord', chords)):
            if field in values:
                label = str(values[field])
                text(label, 128, 1)
                if any(c in label for c in '\r\n'):
                    raise ValueError('Multiline symbolic label')
                target.append({'label': label, 'start_seconds': instant, 'end_seconds': duration})
        rhythm = values.get('rhythm', {})
        if rhythm:
            meter = rhythm.get('meter', meter)
            if 'eighth_position' in rhythm and meter is not None:
                position = Fraction(int(rhythm['eighth_position']) * int(meter[1]), 8)
                if position.denominator == 1 and 0 <= position < int(meter[0]):
                    beats.append({'time_seconds': instant, 'is_downbeat': position == 0})
            annotations.append({'type': 'rhythm', 'time_seconds': instant, 'value': rhythm})
        if 'key' in values:
            annotations.append({'type': 'key', 'time_seconds': instant, 'label': str(values['key'])})
    for regions in (structures, chords):
        for index, item in enumerate(regions[:-1]):
            item['end_seconds'] = regions[index+1]['start_seconds']
        regions[:] = [item for item in regions if item['end_seconds'] > item['start_seconds']]
    for item in chords:
        item.update(raw_label=item['label'], score=None, uncertain=True)
    return {'structure_regions': structures, 'chord_regions': chords, 'beat_events': beats, 'annotations': annotations}


def finish_summary(result):
    result['summary'] = {'track_count': len(result['stems']) or len(result['midi_tracks']), 'note_count': len(result['notes']),
        'controller_count': len(result['controllers']), 'chord_count': len(result['chord_regions']),
        'beat_count': len(result['beat_events']), 'annotation_count': len(result['annotations']) + len(result['structure_regions'])}
    return result


def validate_result(result, directory, request):
    """Server-side publication fence; models never get to choose served paths."""
    if result.get('schema_version') != 2 or result.get('kind') != request['kind'] or result.get('model', {}).get('id') != request['model_id']:
        raise ValueError('Worker result identity mismatch')
    duration = number(result.get('duration_seconds'), 0.000001, 600)
    total = 0; names = set()
    artifacts = result.get('artifacts')
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 32:
        raise ValueError('Invalid artifact count')
    for item in artifacts:
        name = item.get('id')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name) or '..' in name or name in names or name in {'request.json', 'result.json', 'input.wav'}:
            raise ValueError('Invalid artifact identifier')
        names.add(name); path = Path(directory) / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(Path(directory).resolve()):
            raise ValueError('Artifact escaped the job output directory')
        if path.stat().st_size <= 0 or path.stat().st_size != item.get('bytes') or digest(path) != item.get('sha256'):
            raise ValueError('Artifact size or hash mismatch')
        total += path.stat().st_size
        if total > 2 * 1024**3:
            raise ValueError('Artifact bytes exceed publication budget')
        if name.endswith('.wav'):
            actual = wav_info(path)
            if any(actual[k] != item.get(k) for k in actual):
                raise ValueError('Audio artifact metadata mismatch')
    notes = result.get('notes', []); controllers = result.get('controllers', [])
    tracks = result.get('midi_tracks', [])
    if not isinstance(tracks, list) or len(tracks) > 256:
        raise ValueError('Invalid MIDI track count')
    track_ids = set()
    flattened_notes = []; flattened_controls = []
    for track in tracks:
        track_id = track.get('id')
        if not isinstance(track_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', track_id) or track_id in track_ids:
            raise ValueError('Invalid or repeated MIDI track identifier')
        track_ids.add(track_id)
        text(track.get('name'), 128, 1); text(track.get('instrument'), 128, 1)
        if type(track.get('program')) is not int or not 0 <= track['program'] <= 127 or type(track.get('is_drum')) is not bool:
            raise ValueError('Invalid MIDI program/drum metadata')
        if type(track.get('channel')) is not int or not 1 <= track['channel'] <= 16:
            raise ValueError('Invalid MIDI track channel')
        flattened_notes += [{**n, 'track_id': track_id} for n in track['notes']]
        flattened_controls += [{**c, 'track_id': track_id} for c in track['controllers']]
    if notes != flattened_notes or controllers != flattened_controls:
        raise ValueError('Preview events differ from authoritative MIDI tracks')
    if len(notes) > 100000 or len(controllers) > 100000:
        raise ValueError('Event count exceeds candidate budget')
    for note in notes:
        number(note['start_seconds'], 0, duration)
        length = number(note['duration_seconds'], 1e-9, duration)
        if note['start_seconds'] + length > duration + 1e-6:
            raise ValueError('Candidate note extends beyond input')
        for field, low, high in (('pitch', 0, 127), ('velocity', 1, 127), ('channel', 1, 16)):
            if type(note.get(field)) is not int or not low <= note[field] <= high:
                raise ValueError('Invalid MIDI note value')
    for control in controllers:
        number(control['time_seconds'], 0, duration)
        for field, low, high in (('controller', 0, 127), ('value', 0, 127), ('channel', 1, 16)):
            if type(control.get(field)) is not int or not low <= control[field] <= high:
                raise ValueError('Invalid MIDI controller value')
    for key in ('chord_regions', 'structure_regions'):
        regions = result.get(key, [])
        if len(regions) > 100000:
            raise ValueError('Too many symbolic regions')
        for region in regions:
            start = number(region['start_seconds'], 0, duration)
            end = number(region['end_seconds'], 0, duration)
            if end <= start or any(c in text(region['label'], 128, 1) for c in '\r\n'):
                raise ValueError('Invalid symbolic region')
    if len(result.get('beat_events', [])) > 100000 or len(result.get('annotations', [])) > 100000:
        raise ValueError('Too many beat or annotation events')
    for beat in result.get('beat_events', []):
        number(beat['time_seconds'], 0, duration)
        if type(beat.get('is_downbeat')) is not bool:
            raise ValueError('Invalid downbeat flag')
    if request['kind'] == 'generate':
        audio = next((a for a in artifacts if a['id'] == 'audio.wav'), None)
        if audio is None or audio.get('sample_format') != 'pcm16':
            raise ValueError('Generated deliverable must be PCM16 audio.wav')
    finish_summary(result)
    return result
