"""Render film sound through the preserved DAW, using copies and authentic plugins.

No playback, recording, device reconfiguration, network or model inference occurs.
Outputs are not substitutes for physical listening acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import uuid
import wave

from agent_client import Client

ROOT = Path('E:/MusicAgent&DAW/demo-video/showcase-v1')
EXE = Path('E:/emusician-analysis-build/bin-0.13.6/Release/E-musician.exe')
DEMO4 = Path('E:/E-musician/test-projects/demo 0&4/test drive.emproj')
D3 = Path('E:/MusicAgent&DAW/demo-video/2026-11-14/rehearsal/D3-Piano-570d980002b6/D3-TeaForTwo-MIDI.emproj')
D2_WARP = ROOT / 'captures/projects/D2-02-Warp.emproj'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_project(source: Path, directory: Path, receipt: dict) -> tuple[Path, dict]:
    project = read(source)
    references = {asset['source'] for asset in project.get('assets', [])}
    owners = [project.get('master_plugins', [])] + [track.get('plugins', []) for track in project['tracks']]
    references.update(plugin['state_file'] for plugins in owners for plugin in plugins if plugin.get('state_file'))
    directory.mkdir(parents=True, exist_ok=False)
    tracked = [{'path': str(source), 'sha256': sha(source), 'bytes': source.stat().st_size}]
    for relative in sorted(references):
        rel = Path(relative)
        src = (source.parent / rel).resolve()
        dst = (directory / rel).resolve()
        if rel.is_absolute() or not src.is_relative_to(source.parent.resolve()) or not dst.is_relative_to(directory.resolve()):
            raise ValueError('Project reference is outside its source directory: ' + relative)
        digest = sha(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha(dst) != digest:
            raise ValueError('Copied reference hash mismatch: ' + relative)
        tracked.append({'path': str(src), 'sha256': digest, 'bytes': src.stat().st_size})
    copied = directory / source.name
    shutil.copy2(source, copied)
    receipt.update(source=str(source), source_files=tracked, copied_project=str(copied), source_project_id=project['project_id'])
    return copied, project


def wav_metrics(path: Path, seconds: float) -> dict:
    with wave.open(str(path), 'rb') as reader:
        rate, channels, width, frames = reader.getframerate(), reader.getnchannels(), reader.getsampwidth(), reader.getnframes()
        if (rate, channels, width) != (48000, 2, 3) or abs(frames - round(seconds * rate)) > 1:
            raise ValueError('Unexpected WAV format or length')
        peak, energy, count, nonzero, clipped = 0, 0, 0, 0, 0
        block_rms = []
        while data := reader.readframes(rate):
            block_energy, block_count = 0, 0
            for offset in range(0, len(data), 3):
                value = int.from_bytes(data[offset:offset + 3], 'little', signed=True)
                absolute = abs(value)
                peak = max(peak, absolute)
                block_energy += value * value
                block_count += 1
                nonzero += value != 0
                clipped += absolute >= 8388607
            energy += block_energy
            count += block_count
            block_rms.append(math.sqrt(block_energy / max(1, block_count)) / 8388608)
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size,
            'sample_rate': rate, 'channels': channels, 'bit_depth': width * 8, 'frames': frames,
            'seconds': frames / rate, 'peak': peak / 8388608, 'rms': math.sqrt(energy / max(1, count)) / 8388608,
            'nonzero_samples': nonzero, 'clipped_samples': clipped, 'one_second_rms': block_rms}


def request(client: Client, receipt: dict, command: str, args: dict | None = None) -> dict:
    entry = {'command': command, 'args': args or {}, 'started_unix': time.time()}
    receipt.setdefault('commands', []).append(entry)
    started = time.monotonic()
    try:
        reply = client.request({'command': command, 'args': args or {}})
        entry['reply'] = reply
        return reply
    except Exception as error:
        entry['error'] = str(error)
        raise
    finally:
        entry['elapsed_seconds'] = round(time.monotonic() - started, 3)


def track_summary(state: dict) -> list:
    return [{key: track.get(key) for key in ('id', 'name', 'kind', 'muted', 'solo', 'plugins')}
            for track in state['tracks']]


def wait_native(client: Client, receipt: dict, state: dict) -> None:
    for track in state['tracks']:
        if not any(plugin.get('format') == 'E-musician' and plugin.get('is_instrument') for plugin in track.get('plugins', [])):
            continue
        deadline = time.monotonic() + 90
        samples = []
        while True:
            info = client.completed(client.raw({'command': 'get_native_instrument', 'args': {'track_id': track['id']}}))
            status = info.get('load_status')
            if not samples or samples[-1]['load_status'] != status:
                samples.append({'load_status': status, 'error': info.get('error', '')})
            if status == 'ready':
                break
            if status in ('error', 'failed') or time.monotonic() >= deadline:
                raise ValueError('Native sample readiness failed: ' + track['name'] + ' ' + str(info))
            time.sleep(0.1)
        receipt.setdefault('native_readiness', []).append({'track': track['name'], 'states': samples})


def export(client: Client, receipt: dict, destination: Path, seconds: float, realtime: bool = False) -> dict:
    if destination.exists():
        raise ValueError('Refusing to overwrite an earlier sound export: ' + str(destination))
    request(client, receipt, 'export_wav', {'path': str(destination), 'start_seconds': 0,
            'end_seconds': seconds, 'sample_rate': 48000, 'bit_depth': 24, 'tail_seconds': 0, 'realtime': realtime})
    return wav_metrics(destination, seconds)


def verify_transcription(project: dict, root: Path) -> dict:
    result_path = root / 'workspace/results/transcribe/result.json'
    result = read(result_path)
    analysis = next(item for item in project['analyses'] if item['kind'] == 'transcribe')
    if analysis['result_sha256'] != sha(result_path):
        raise ValueError('Saved D3 result hash does not match the retained TransKun result')
    track = next(track for track in project['tracks'] if track['name'] == 'MIDI / Transcription')
    clip = track['clips'][0]
    stored, predicted = clip['notes'], result['midi_tracks'][0]['notes']
    if len(stored) != 132 or len(predicted) != 132:
        raise ValueError('Expected exactly 132 genuine TransKun notes')
    stored = sorted(stored, key=lambda n: (round(n['start_beats'] * 60 / project['bpm'], 6), n['pitch']))
    predicted = sorted(predicted, key=lambda n: (round(n['start_seconds'], 6), n['pitch']))
    edits, restored = [], []
    for note, expected in zip(stored, predicted):
        if any(note[key] != expected[key] for key in ('pitch', 'channel')):
            raise ValueError('Pitch or channel differs from retained transcription')
        if (abs(note['start_beats'] * 60 / project['bpm'] - expected['start_seconds']) > 1e-6 or
                abs(note['length_beats'] * 60 / project['bpm'] - expected['duration_seconds']) > 1e-6):
            raise ValueError('MIDI timing differs from retained transcription')
        if note['velocity'] != expected['velocity']:
            edits.append({'pitch': note['pitch'], 'start_seconds': expected['start_seconds'],
                          'saved_velocity': note['velocity'], 'retained_velocity': expected['velocity']})
        restored.append(dict(note, velocity=expected['velocity']))
    source_asset = next(asset for asset in project['assets'] if asset['id'] == analysis['source_asset_id'])
    if sha(D3.parent / source_asset['source']) != analysis['source_sha256']:
        raise ValueError('D3 analysis source audio hash mismatch')
    return {'note_count': len(stored), 'all_saved_notes_match': not edits,
            'saved_velocity_edits': edits, 'restored_notes': restored, 'tolerance_seconds': 1e-6,
            'result_sha256': sha(result_path), 'source_sha256': analysis['source_sha256'],
            'instrument_track_id': track['id'], 'midi_clip_id': clip['id'],
            'saved_plugins': track['plugins']}


def run_one(mode: str, args: argparse.Namespace, run_dir: Path) -> dict:
    receipt = {'mode': mode, 'status': 'running', 'model_inference': False,
               'physical_device_used': False, 'listening_acceptance': 'not performed',
               'exe': str(args.exe), 'exe_sha256': sha(args.exe)}
    receipt_file = run_dir / (mode + '.json')
    try:
        source = DEMO4 if mode == 'demo4' else D2_WARP if mode == 'd2' else D3
        project_path, project = copy_project(source, run_dir / mode, receipt)
        if mode == 'demo4' and len(project['tracks']) != 9:
            raise ValueError('The current Demo4 source no longer contains nine tracks')
        if mode == 'd3':
            receipt['transcription'] = verify_transcription(project, args.root)
        write(receipt_file, receipt)
        with Client(args.exe, timeout=480, show=False, offline_test=True) as client:
            request(client, receipt, 'open_project', {'path': str(project_path)})
            state = client.state()
            receipt['opened_tracks'] = track_summary(state)
            if len(state['tracks']) != len(project['tracks']):
                raise ValueError('Opened track count differs from saved project')
            wait_native(client, receipt, state)
            catalog = client.completed(client.raw({'command': 'get_plugin_catalog', 'args': {'offset': 0, 'limit': 256}}))
            receipt['keyscape_catalog'] = [entry for entry in catalog.get('entries', catalog.get('plugins', [])) if entry.get('name') == 'Keyscape']
            if mode == 'demo4':
                receipt['audio'] = export(client, receipt, args.root / 'audio/demo4-current-mix.wav', 60)
            elif mode == 'd2':
                clips=[clip for track in state['tracks'] for clip in track['clips'] if clip['kind']=='audio']
                if len(clips)!=1 or not clips[0]['warp_enabled'] or not clips[0]['warp_follow_tempo']:
                    raise ValueError('D2 must be the actual accepted Warp stage with one tempo-following audio clip')
                if not any(analysis['kind']=='beats' for analysis in project.get('analyses', [])):
                    raise ValueError('D2 project contains no applied beat-analysis provenance')
                receipt['warp_state']=client.completed(client.raw({'command':'get_audio_warp','args':{'clip_ids':[clips[0]['id']]}}))
                receipt['chords']=client.completed(client.raw({'command':'get_chord_regions','args':{'limit':100}}))
                seconds=clips[0]['start_seconds']+clips[0]['duration_seconds']
                receipt['audio']=export(client,receipt,args.root/'audio/d2-new-light-warp.wav',seconds)
            else:
                if receipt['transcription']['saved_velocity_edits']:
                    request(client, receipt, 'write_notes', {'clip_id': receipt['transcription']['midi_clip_id'],
                            'notes': receipt['transcription']['restored_notes']})
                for track in state['tracks']:
                    request(client, receipt, 'set_track_muted', {'track_id': track['id'], 'muted': track['id'] != receipt['transcription']['instrument_track_id']})
                receipt['audition_tracks'] = track_summary(client.state())
                request(client, receipt, 'save_project', {'path': str(run_dir / 'D3-Keyscape-MIDI-only.emproj')})
                filename = 'd3-keyscape-midi-only-realtime.wav' if args.realtime else 'd3-keyscape-midi-only.wav'
                receipt['audio'] = export(client, receipt, args.root / 'audio' / filename, 16, args.realtime)
                # A no-notes clip still sends recorded pedal CCs; those can make
                # authentic pedal/mechanical sounds in Keyscape. Remove the entire
                # MIDI clip for the strict no-input negative control.
                request(client, receipt, 'delete_clips', {'clip_ids': [receipt['transcription']['midi_clip_id']]})
                receipt['negative_control'] = export(client, receipt, run_dir / 'd3-no-midi-control.wav', 16, args.realtime)
                request(client, receipt, 'undo')
                notes = client.completed(client.raw({'command': 'get_clip_notes', 'args': {'clip_id': receipt['transcription']['midi_clip_id']}}))
                if notes.get('total') != 132:
                    raise ValueError('Undo did not restore 132 notes after no-note control')
                if receipt['negative_control']['peak'] > 1e-5:
                    raise ValueError('No-MIDI control was audible; cannot attribute exported sound solely to MIDI')
            if receipt['audio']['peak'] < 1e-4 or receipt['audio']['rms'] < 1e-5:
                raise ValueError('Actual DAW export is silent or effectively silent; no substitute was produced')
        receipt['status'] = 'passed'
    except Exception as error:
        receipt.update(status='failed', error=type(error).__name__ + ': ' + str(error))
    finally:
        receipt['source_unchanged'] = all(sha(Path(item['path'])) == item['sha256'] for item in receipt.get('source_files', []))
        if not receipt['source_unchanged']:
            receipt.update(status='failed', source_error='A source file hash changed during export')
        receipt['exe_unchanged'] = sha(args.exe) == receipt['exe_sha256']
        write(receipt_file, receipt)
    print(json.dumps({'task': mode, 'status': receipt['status'], 'receipt': str(receipt_file),
                      'error': receipt.get('error'), 'audio': receipt.get('audio', {}).get('path')}, ensure_ascii=False), flush=True)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('all', 'demo4', 'd3', 'd2'), default='all')
    parser.add_argument('--exe', type=Path, default=EXE)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--realtime', action=argparse.BooleanOptionalAction, default=True,
                        help='Pace D3 render blocks in its isolated render worker, without an audio device; disable only for diagnosis')
    args = parser.parse_args()
    if args.exe.resolve() != EXE.resolve():
        parser.error('This rendering task must use the preserved 0.13.6 binary')
    run_dir = args.root / 'audio/evidence' / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True)
    modes = ('demo4', 'd3') if args.mode == 'all' else (args.mode,)
    receipts = [run_one(mode, args, run_dir) for mode in modes]
    write(run_dir / 'summary.json', {'runs': receipts, 'new_model_inference': False, 'old_mix_reused': False})
    return 0 if all(receipt['status'] == 'passed' for receipt in receipts) else 1


if __name__ == '__main__':
    raise SystemExit(main())
