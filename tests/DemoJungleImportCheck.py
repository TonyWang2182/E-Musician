"""Import the real CC0 demo pack in an owned offline native host.

No GUI, device, playback, render, music model, language model or user project.
Original 124 BPM sources use the documented notes_only import policy at 170 BPM.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agent_client import Client
from dev import configure_console_output
from MusicAgentTempoIntegration import protected_changes, protected_snapshot


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    configure_console_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--pack', type=Path, default=Path('E:/MusicAgent&DAW/demo-video/2026-11-14/jungle-materials/portable-cc0'))
    parser.add_argument('--timeout', type=float, default=40)
    args = parser.parse_args()
    assert args.exe.is_file() and args.pack.is_dir()
    directory = ROOT / 'build/demo-jungle-import' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    executable = directory / 'E-musician.exe'
    shutil.copy2(args.exe, executable)
    source_hashes = {str(p): digest(p) for p in args.pack.rglob('*') if p.is_file()}
    expected = json.loads((args.pack / 'VALIDATION.json').read_text(encoding='utf-8'))['assets']
    expected = {item['file']: item for item in expected}
    report = {'passed': False, 'exe_path': str(args.exe), 'exe_sha256': digest(executable),
              'mode': 'real-native-0.13.4-offline-import-save-reopen', 'llm_called': False,
              'music_model_called': False, 'physical_audio': False, 'gui_mouse_tested': False,
              'listening_verified': False, 'rendered': False, 'imports': [], 'checks': []}
    client = None
    before_protected = protected_snapshot()
    started = time.monotonic()

    def write(command, **arguments):
        return client.request({'command': command, 'args': arguments})

    def notes(snapshot):
        return {clip['id']: client.completed(client.raw({'command': 'get_clip_notes', 'args': {
            'clip_id': clip['id'], 'limit': 500}}))['notes']
            for track in snapshot['tracks'] for clip in track['clips'] if clip['kind'] == 'midi'}

    def native(track_id):
        deadline = time.monotonic() + args.timeout
        while True:
            result = client.completed(client.raw({'command': 'get_native_instrument', 'args': {'track_id': track_id}}))
            if result.get('load_status') == 'ready':
                return result
            if time.monotonic() >= deadline:
                raise AssertionError('Native sample did not become ready: ' + json.dumps(result))
            time.sleep(0.03)

    def canonical_instrument(item):
        keep = ['type', 'root_note', 'start', 'end']
        result = {k: item[k] for k in keep if k in item}
        fields = ['index', 'note', 'sample_sha256', 'gain_db', 'muted', 'attack_ms', 'release_ms', 'one_shot']
        result['pads'] = [{k: p[k] for k in fields if k in p} for p in item['pads']]
        return result

    def musical_snapshot(snapshot):
        result = {k: snapshot[k] for k in ['bpm', 'numerator', 'denominator', 'tracks', 'master_gain_db', 'master_plugins']}
        result = json.loads(json.dumps(result))
        for track in result['tracks']:
            for field in ['peak_left_db', 'peak_right_db', 'overloaded']:
                track.pop(field, None)
        return result

    try:
        client = Client(executable, timeout=args.timeout, show=False, offline_test=True)
        assert not client.state()['tracks']
        # First import adopts this file's fixed 170 BPM into the empty project.
        midi_paths = sorted(args.pack.rglob('*.mid'), key=lambda p: (not p.name.startswith('LOCAL_'), p.name))
        assert len(midi_paths) == 7
        imported_tracks = {}
        for path in midi_paths:
            previous = {t['id'] for t in client.state()['tracks']}
            notes_only = not path.name.startswith('LOCAL_')
            write('import_midi', path=str(path), notes_only=notes_only)
            snapshot = client.state()
            tracks = [t for t in snapshot['tracks'] if t['id'] not in previous]
            assert len(tracks) == 1, 'Expected one source MIDI channel/track: ' + path.name
            track = tracks[0]
            imported_tracks[path.name] = track['id']
            assert len(track['clips']) == 1
            clip = track['clips'][0]
            data = client.completed(client.raw({'command': 'get_clip_notes', 'args': {'clip_id': clip['id'], 'limit': 500}}))
            source = expected[path.relative_to(args.pack).as_posix()]
            assert data['total'] == len(data['notes']) == source['note_count']
            assert sorted({n['pitch'] for n in data['notes']}) == source['pitches']
            # Native snapshot clip starts are seconds; note onsets are clip-relative beats.
            first_beat = clip['start_seconds'] * snapshot['bpm'] / 60 + min(n['start_beats'] for n in data['notes'])
            assert abs(first_beat - source['first_note_beat']) < 1e-5, (path.name, first_beat, source['first_note_beat'])
            assert all(n['length_beats'] > 0 for n in data['notes'])
            report['imports'].append({'file': str(path), 'kind': 'midi', 'track_id': track['id'],
                                      'note_count': data['total'], 'first_absolute_beat': first_beat,
                                      'notes_only': notes_only, 'tempo_policy': 'keep project tempo' if notes_only else 'adopt source tempo'})
        assert abs(client.state()['bpm'] - 170) < 0.001
        report['checks'].append('All 7 actual MIDI files imported; counts/pitches/positive lengths/352-beat original offset preserved; explicit notes_only policy for existing tempo')

        wav_paths = sorted(args.pack.rglob('*.wav'))
        assert len(wav_paths) == 17
        for path in wav_paths:
            previous = {t['id'] for t in client.state()['tracks']}
            write('import_audio', paths=[str(path)])
            snapshot = client.state()
            tracks = [t for t in snapshot['tracks'] if t['id'] not in previous]
            assert len(tracks) == 1 and len(tracks[0]['clips']) == 1
            clip = tracks[0]['clips'][0]
            source = expected[path.relative_to(args.pack).as_posix()]
            assert clip['kind'] == 'audio' and abs(clip['duration_seconds'] - source['duration_seconds']) < 0.001
            report['imports'].append({'file': str(path), 'kind': 'audio', 'track_id': tracks[0]['id'], 'clip': clip})
        assert len(client.state()['tracks']) == 24
        report['checks'].append('All 17 actual WAV files imported as audio clips with matching duration; 24 total source tracks')

        rack_id = imported_tracks['LOCAL_Jungle_Drums_170BPM_4bars.mid']
        write('add_native_instrument', track_id=rack_id, type='drum_rack')
        with (args.pack / 'PAD-MAP.csv').open(newline='', encoding='utf-8') as stream:
            pad_map = list(csv.DictReader(stream))
        assert len(pad_map) == 8
        for item in pad_map:
            midi_note = int(item['midi_note'])
            index = midi_note - 36
            assert 0 <= index < 16
            sample = args.pack / item['file']
            write('set_native_sample', track_id=rack_id, pad=index, path=str(sample))
            state = native(rack_id)
            pad = state['pads'][index]
            assert pad['sample_sha256'] == digest(sample) and pad['note'] == midi_note
        sampler_ids = {}
        for name, midi, sample_name, root in [
            ('Bass', 'ADAPTED_HPR_Bass_012_Fminor_170BPM.mid', 'SynthBassLead_C2_root36.wav', 36),
            ('Pad', 'ADAPTED_HPR_Piano_012_Fminor_170BPM.mid', 'SynthPadChoir_C4_root60.wav', 60)]:
            tid = imported_tracks[midi]
            sampler_ids[name] = tid
            write('add_native_instrument', track_id=tid, type='sampler')
            sample = args.pack / '02-sampler' / sample_name
            write('set_native_sample', track_id=tid, pad=0, path=str(sample))
            write('set_native_sampler', track_id=tid, root_note=root, start=0.0, end=1.0)
            state = native(tid)
            assert state['root_note'] == root and state['pads'][0]['sample_sha256'] == digest(sample)
        ids = {'Drum Rack': rack_id, **sampler_ids}
        native_before = {name: canonical_instrument(native(tid)) for name, tid in ids.items()}
        report['checks'].append('Native Rack loads all 8 actual one-shots at notes 36–51; native bass/pad Samplers load with roots 36/60; every loaded sample SHA matches')
        report['native_instruments'] = native_before

        before = client.state()
        before_notes = notes(before)
        project = directory / 'CC0-import-verification.emproj'
        write('save_project', path=str(project))
        assert project.is_file()
        saved = json.loads(project.read_text(encoding='utf-8'))
        bundled = []
        for asset in saved['assets']:
            if asset.get('source'):
                path = project.parent / asset['source']
                assert path.is_file()
                bundled.append({'path': str(path), 'sha256': digest(path)})
        assert {digest(p) for p in wav_paths} <= {i['sha256'] for i in bundled}
        write('open_project', path=str(project))
        reopened = client.state()
        assert musical_snapshot(reopened) == musical_snapshot(before)
        assert notes(reopened) == before_notes
        assert {name: canonical_instrument(native(tid)) for name, tid in ids.items()} == native_before
        assert not reopened['dirty']
        report.update({'saved_project': str(project), 'project_sha256': digest(project), 'bundled_assets': bundled,
                       'track_count': len(reopened['tracks']), 'total_midi_notes': sum(len(n) for n in before_notes.values())})
        report['checks'].append('Real save/reopen preserves all 24 tracks, all 277 MIDI notes, Rack/Sampler settings and sample identities; all 17 audio hashes bundled; reopened clean')
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if client:
            client.close()
        report['protected_file_changes'] = protected_changes(before_protected, protected_snapshot())
        report['source_files_unchanged'] = all(Path(p).is_file() and digest(Path(p)) == sha for p, sha in source_hashes.items())
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['passed'] = report['passed'] and report['source_files_unchanged'] and report['protected_file_changes']['unchanged']
        output = directory / 'report.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: report[k] for k in ['passed', 'checks', 'source_files_unchanged', 'protected_file_changes', 'elapsed_seconds']}, ensure_ascii=False))
        print('Report:', output)
    assert report['passed']


if __name__ == '__main__':
    main()
