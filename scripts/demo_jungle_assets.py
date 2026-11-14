"""Prepare licensed portable source materials, not an arranged demo project.

Run with the existing analysis runtime (numpy + soundfile). No model calls.
Source downloads are bounded, pinned, hashed and kept outside Git.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import soundfile as sf

from demo_jungle_prepare import ROOT, UA, digest, download, open_retry

PACK = ROOT / 'portable-cc0'
MANIFEST = PACK / 'SOURCE-MANIFEST.json'
LMMS_PAGE = 'https://github.com/LMMS/assets'
PRODUCER_PAGE = 'https://producerspace.com/license'
records = []


def github_asset(tree_name, source_path, output_name, role, **extra):
    tree = json.loads((ROOT / 'evidence' / tree_name).read_text(encoding='utf-8'))
    entry = next(x for x in tree['tree'] if x['path'] == source_path)
    source = ROOT / 'sources' / tree_name.removesuffix('-tree.json') / source_path
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        with open_retry(urllib.request.Request(entry['url'], headers={'User-Agent': UA})) as response:
            blob = json.load(response)
        assert blob['encoding'] == 'base64' and blob['size'] < 16 * 1024 * 1024
        data = base64.b64decode(blob['content'])
        assert len(data) == blob['size']
        git_hash = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert git_hash == entry['sha'], 'Git blob checksum mismatch'
        source.write_bytes(data)
    target = PACK / output_name
    target.parent.mkdir(parents=True, exist_ok=True)
    transformation = 'Unmodified source file'
    if source.suffix == '.flac':
        samples, rate = sf.read(source, dtype='float64', always_2d=True)
        assert np.isfinite(samples).all() and np.max(np.abs(samples)) > 0
        sf.write(target, samples, rate, subtype='PCM_24')
        transformation = 'Lossless FLAC decode to PCM_24 WAV; no gain, trim, resample or pitch change'
    else:
        shutil.copyfile(source, target)
    rec = {'file': output_name, 'role': role, 'origin': 'downloaded', 'license': 'CC0-1.0',
           'source_api_url': entry['url'], 'source_repository': tree['url'].split('/git/trees/')[0],
           'source_commit': tree['sha'], 'source_path': source_path, 'source_blob_sha1': entry['sha'],
           'source_sha256': digest(source), 'sha256': digest(target), 'bytes': target.stat().st_size,
           'transformation': transformation, **extra}
    records.append(rec)
    print('Ready ' + output_name, flush=True)


def producer_asset(source_path, output_name, role, **extra):
    metadata = json.loads((ROOT / 'evidence/producer-space-metadata.json').read_text(encoding='utf-8'))
    entry = next(x for x in metadata['files'] if x['name'] == source_path)
    url = 'https://archive.org/download/producer-space-cc0-sample-library/' + urllib.parse.quote(source_path)
    target = PACK / output_name
    receipt = download(url, target, 12 * 1024 * 1024)
    assert target.stat().st_size == int(entry['size'])
    assert hashlib.md5(target.read_bytes()).hexdigest() == entry['md5'], 'Archive source checksum mismatch'
    records.append({'file': output_name, 'role': role, 'origin': 'downloaded', 'license': 'CC0-1.0',
                    'source_page': 'https://producerspace.com/', 'license_url': PRODUCER_PAGE,
                    'source_url': url, 'source_path': source_path, 'source_md5': entry['md5'],
                    'sha256': receipt['sha256'], 'bytes': receipt['bytes'],
                    'transformation': 'Unmodified original source file', **extra})


def vlq(n):
    result = [n & 127]
    while n >> 7:
        n >>= 7
        result.insert(0, (n & 127) | 128)
    return bytes(result)


def drum_building_block():
    """Original four-bar MIDI example + matching WAV loop; explicitly labelled."""
    ppq, bpm, beats = 960, 170, 16
    events = []
    def note(beat, pitch, velocity, duration=0.10):
        start = round(beat * ppq)
        events.extend([(start, bytes([0x99, pitch, velocity])),
                       (start + round(duration * ppq), bytes([0x89, pitch, 0]))])
    for beat in [0, 1.75, 2.5, 4, 5.5, 6.75, 8, 9.75, 10.5, 12, 13.5, 14.75]:
        note(beat, 36, 105 if beat % 4 == 0 else 88)
    for beat in range(1, 16, 2):
        note(beat, 38, 108)
    for beat in [2.75, 3.5, 6.5, 7.75, 10.75, 11.5, 14.5, 15.5, 15.75]:
        note(beat, 38, 40 if beat % 1 else 48)
    for index in range(32):
        if index in [7, 15, 23, 31]:
            note(index / 2, 46, 62)
        else:
            note(index / 2, 42, 70 if index % 2 == 0 else 48)
    for beat in [6.75, 14.75]:
        note(beat, 42, 40)
    events.sort(key=lambda e: (e[0], e[1][0] >> 4 != 8))
    title = b'Original jungle building block - 4 bars - 170 BPM'
    track = b'\0\xff\x03' + vlq(len(title)) + title
    track += b'\0\xff\x51\x03' + round(60000000 / bpm).to_bytes(3, 'big')
    track += b'\0\xff\x58\x04\x04\x02\x18\x08'
    last = 0
    for tick, data in events:
        track += vlq(tick - last) + data
        last = tick
    track += vlq(beats * ppq - last) + b'\xff\x2f\0'
    path = PACK / '03-midi/LOCAL_Jungle_Drums_170BPM_4bars.mid'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ppq)
                     + b'MTrk' + struct.pack('>I', len(track)) + track)
    records.append({'file': str(path.relative_to(PACK)).replace('\\', '/'), 'role': 'Drum Rack test MIDI',
                    'origin': 'locally_authored_not_downloaded', 'license': 'CC0-1.0',
                    'description': 'Four-bar reusable beat pattern; not a complete arrangement or an Amen recording.',
                    'bpm': bpm, 'bars': 4, 'pitches': [36, 38, 42, 46], 'sha256': digest(path),
                    'bytes': path.stat().st_size})
    # A convenient chopping / warp source, rendered only from the downloaded CC0 one-shots.
    rate = 44100
    output = np.zeros((round(beats * 60 / bpm * rate), 2), dtype=np.float64)
    pads = {36: '36_Kick_DnB.wav', 38: '38_Snare_DnB.wav',
            42: '42_Hat_Closed_Jazz.wav', 46: '46_Hat_Open_Jazz.wav'}
    source_samples = {}
    for pitch, name in pads.items():
        y, sr = sf.read(PACK / '01-drum-rack' / name, always_2d=True, dtype='float64')
        if sr != rate:
            raise RuntimeError('Building block expects 44.1 kHz source, no implicit resampling')
        source_samples[pitch] = np.repeat(y, 2, axis=1) if y.shape[1] == 1 else y[:, :2]
    for tick, message in events:
        if message[0] != 0x99:
            continue
        start = round(tick / ppq * 60 / bpm * rate)
        y = source_samples[message[1]] * message[2] / 127
        length = min(len(y), len(output) - start)
        if length > 0:
            output[start:start + length] += y[:length]
    peak = np.max(np.abs(output))
    output *= 10 ** (-6 / 20) / peak
    path = PACK / '05-loops/LOCAL_Jungle_Break_170BPM_4bars.wav'
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, output, rate, subtype='PCM_24')
    records.append({'file': str(path.relative_to(PACK)).replace('\\', '/'), 'role': 'Sampler chopping / warp loop',
                    'origin': 'locally_rendered_from_downloaded_CC0_samples', 'license': 'CC0-1.0',
                    'source_files': ['01-drum-rack/' + name for name in pads.values()],
                    'midi_source': '03-midi/LOCAL_Jungle_Drums_170BPM_4bars.mid',
                    'description': 'Original programmed beat, not a sampled Amen break or model generation.',
                    'transformation': 'Velocity-scaled layering, tail truncation at four bars, peak scaled to -6 dBFS',
                    'bpm': bpm, 'bars': 4, 'sha256': digest(path), 'bytes': path.stat().st_size})


def midi_info(path, include_notes=False):
    data = path.read_bytes()
    assert data[:4] == b'MThd' and len(data) > 14
    header_length = int.from_bytes(data[4:8], 'big')
    fmt, track_count, ppq = struct.unpack('>HHH', data[8:14])
    assert fmt in (0, 1) and ppq > 0 and not ppq & 0x8000
    position = 8 + header_length
    notes, tempo, last_tick = [], [], 0
    for _ in range(track_count):
        assert data[position:position + 4] == b'MTrk'
        size = int.from_bytes(data[position + 4:position + 8], 'big')
        position += 8
        end = position + size
        tick, running, pending = 0, None, {}
        def read_vlq():
            nonlocal position
            value = 0
            for _ in range(4):
                b = data[position]; position += 1; value = (value << 7) | (b & 127)
                if not b & 128:
                    return value
            raise ValueError('Invalid MIDI variable length value')
        while position < end:
            tick += read_vlq()
            status = data[position]
            if status < 128:
                assert running is not None
                status = running
            else:
                position += 1
            if status == 0xff:
                meta = data[position]; position += 1
                length = read_vlq()
                payload = data[position:position + length]; position += length
                if meta == 0x51:
                    tempo.append(round(60000000 / int.from_bytes(payload, 'big'), 5))
                running = None
            elif status in (0xf0, 0xf7):
                length = read_vlq(); position += length; running = None
            else:
                assert 0x80 <= status < 0xf0
                running = status
                command, channel = status >> 4, status & 15
                length = 1 if command in (0xc, 0xd) else 2
                values = data[position:position + length]; position += length
                assert len(values) == length and all(x < 128 for x in values)
                if command in (8, 9):
                    key = channel, values[0]
                    if command == 9 and values[1] > 0:
                        assert key not in pending, 'Overlapping same-pitch notes need manual review'
                        pending[key] = (tick, values[1])
                    else:
                        assert key in pending, 'Unpaired note-off'
                        start, velocity = pending.pop(key)
                        assert tick > start, 'Nonpositive MIDI note duration'
                        notes.append({'pitch': values[0], 'velocity': velocity, 'channel': channel + 1,
                                      'start_ticks': start, 'length_ticks': tick - start})
        assert position == end and not pending, 'Unclosed MIDI notes'
        last_tick = max(last_tick, tick)
    assert position == len(data) and notes
    info = {'format': fmt, 'tracks': track_count, 'ppq': ppq, 'note_count': len(notes),
            'pitches': sorted(set(n['pitch'] for n in notes)), 'tempo_bpm': tempo,
            'length_beats': last_tick / ppq,
            'first_note_beat': min(n['start_ticks'] for n in notes) / ppq,
            'last_note_end_beat': max(n['start_ticks'] + n['length_ticks'] for n in notes) / ppq,
            'all_notes_have_positive_length': True}
    if include_notes:
        info['note_events'] = notes
    return info


def adapt_downloaded_midis():
    for source in sorted((PACK / '03-midi').glob('DOWNLOADED*.mid')):
        original = midi_info(source, include_notes=True)
        ppq = original['ppq']
        offset = min(n['start_ticks'] for n in original['note_events'])
        events = []
        for note in original['note_events']:
            channel = note['channel'] - 1
            start = note['start_ticks'] - offset
            events.extend([(start, bytes([0x90 | channel, note['pitch'], note['velocity']])),
                           (start + note['length_ticks'], bytes([0x80 | channel, note['pitch'], 0]))])
        events.sort(key=lambda e: (e[0], e[1][0] >> 4 != 8))
        title = source.stem.replace('DOWNLOADED', 'ADAPTED').replace('124BPM', '170BPM').encode()
        track = b'\0\xff\x03' + vlq(len(title)) + title
        track += b'\0\xff\x51\x03' + round(60000000 / 170).to_bytes(3, 'big')
        track += b'\0\xff\x58\x04\x04\x02\x18\x08'
        last = 0
        for tick, message in events:
            track += vlq(tick - last) + message
            last = tick
        end = ((last + 4 * ppq - 1) // (4 * ppq)) * 4 * ppq
        track += vlq(end - last) + b'\xff\x2f\0'
        target = source.with_name(source.name.replace('DOWNLOADED', 'ADAPTED').replace('124BPM', '170BPM'))
        target.write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ppq)
                           + b'MTrk' + struct.pack('>I', len(track)) + track)
        adapted = midi_info(target, include_notes=True)
        expected = sorted((n['pitch'], n['channel'], n['velocity'], n['start_ticks'] - offset, n['length_ticks'])
                          for n in original['note_events'])
        actual = sorted((n['pitch'], n['channel'], n['velocity'], n['start_ticks'], n['length_ticks'])
                        for n in adapted['note_events'])
        assert expected == actual and adapted['first_note_beat'] == 0
        records.append({'file': str(target.relative_to(PACK)).replace('\\', '/'),
                        'role': 'Ready-to-import eight-bar MIDI phrase',
                        'origin': 'adapted_from_downloaded_CC0_MIDI', 'license': 'CC0-1.0',
                        'source_file': str(source.relative_to(PACK)).replace('\\', '/'),
                        'source_sha256': digest(source), 'removed_leading_beats': offset / ppq,
                        'transformation': 'Remove shared 352-beat leading silence; tempo 170 BPM; 4/4, eight-bar end; preserve note pitches, channels, velocities, durations and relative onsets. Only note data retained; no source program/controller events.',
                        'note_equivalence_check': 'passed', 'bpm': 170, 'bars': end / ppq / 4,
                        'sha256': digest(target), 'bytes': target.stat().st_size})


def validate_and_zip():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    results = []
    for record in manifest['assets']:
        path = PACK / record['file']
        assert digest(path) == record['sha256']
        result = {'file': record['file'], 'bytes': path.stat().st_size, 'sha256': digest(path)}
        if path.suffix.lower() == '.wav':
            samples, rate = sf.read(path, always_2d=True, dtype='float64')
            assert len(samples) > 0 and np.isfinite(samples).all()
            peak = float(np.max(np.abs(samples)))
            assert 0 < peak <= 1
            result.update({'frames': len(samples), 'sample_rate': rate, 'channels': samples.shape[1],
                           'duration_seconds': round(len(samples) / rate, 6), 'peak_dbfs': round(20 * np.log10(peak), 3),
                           'rms_dbfs': round(20 * np.log10(np.sqrt(np.mean(samples ** 2))), 3),
                           'subtype': sf.info(path).subtype, 'finite_nonzero_decode': True})
        elif path.suffix.lower() == '.mid':
            result.update(midi_info(path))
        results.append(result)
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
              'method': 'Full WAV decode + finite/nonzero/peak checks; independent Standard MIDI parser; SHA256 of every asset; ZIP CRC.',
              'not_validated': ['Human listening', 'DAW import, rack mapping and sound output', 'Full arrangement'],
              'assets': results}
    (PACK / 'VALIDATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    zip_path = ROOT / 'jungle-materials-cc0.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(PACK.rglob('*')):
            if path.is_file():
                z.write(path, path.relative_to(PACK))
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        entries = len(z.infolist())
    zip_report = {'zip': str(zip_path), 'sha256': digest(zip_path), 'bytes': zip_path.stat().st_size,
                  'entries': entries, 'crc_check': 'passed', 'asset_count': len(results)}
    (ROOT / 'evidence/portable-zip-validation.json').write_text(json.dumps(zip_report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(zip_report, ensure_ascii=False), flush=True)


def fetch():
    PACK.mkdir(parents=True, exist_ok=True)
    for source, name, number in [
        ('Drums/Kicks/DnB Kick.flac', '36_Kick_DnB.wav', 36),
        ('Drums/Snares/DnB Snare 1.flac', '38_Snare_DnB.wav', 38),
        ('Drums/Hi-hats/Jazz CHH 1.flac', '42_Hat_Closed_Jazz.wav', 42),
        ('Drums/Hi-hats/Jazz OHH 1.flac', '46_Hat_Open_Jazz.wav', 46),
        ('Drums/Misc/Rim Shot 1.flac', '37_Rim.wav', 37),
        ('Drums/Claps/Short Clap.flac', '39_Clap_Short.wav', 39),
        ('Drums/Crashes/Crash 1.flac', '49_Crash.wav', 49),
        ('Drums/Bells/Cowbell 1.flac', '51_Cowbell.wav', 51)]:
        github_asset('lmms-tree.json', 'Samples/Sample library/' + source, '01-drum-rack/' + name,
                     'Drum Rack one-shot', suggested_midi_note=number,
                     source_page=LMMS_PAGE, license_url=LMMS_PAGE + '/blob/master/LICENSE')
    for source, name, role, note in [
        ('Notes & Chords/Bamboo Flute - A4.flac', 'Flute_A4_root69.wav', 'Sampler melodic texture', 69),
        ('SFXs/Vinyl Rewind.flac', 'Vinyl_Rewind.wav', 'Transition FX', None)]:
        github_asset('lmms-tree.json', 'Samples/Sample library/' + source, '02-sampler/' + name,
                     role, suggested_root_midi_note=note, source_page=LMMS_PAGE)
    github_asset('lmms-tree.json', 'LICENSE', 'LICENSES/LMMS-CC0.txt', 'License text')
    for tree, prefix, note, role, page in [
        ('freepats-bass-tree.json', 'SynthBassLead', 36, 'Sampler bass instrument', 'https://freepats.zenvoid.org/Synthesizer/synth-lead.html'),
        ('freepats-pad-tree.json', 'SynthPadChoir', 60, 'Sampler pad instrument', 'https://freepats.zenvoid.org/Synthesizer/synth-pad.html')]:
        sample = 'C2' if note == 36 else 'C4'
        github_asset(tree, 'samples/' + sample + '.flac', '02-sampler/' + prefix + '_' + sample + '_root' + str(note) + '.wav',
                     role, suggested_root_midi_note=note, source_page=page,
                     source_version='2020-05-22' if note == 36 else '2020-05-16')
        github_asset(tree, 'LICENSE.txt', 'LICENSES/' + prefix + '-LICENSE.txt', 'License text')
        github_asset(tree, 'README.txt', 'LICENSES/' + prefix + '-README.txt', 'Source documentation')
        sfz = 'SynthBassLead 20200522.sfz' if note == 36 else 'SynthPadChoir 20200516.sfz'
        github_asset(tree, sfz, 'LICENSES/' + prefix + '-original.sfz.txt', 'Original root-note and looping metadata; sample references not standalone in this subset')
    for source, name in [
        ('Dance Vocal Shouts/DVS - Lets Go 1.wav', 'Lets_Go.wav'),
        ('Dance Vocal Shouts/DVS - Break it Down 1.wav', 'Break_It_Down.wav'),
        ('Dance Vocal Shouts/DVS - Yeah 1.wav', 'Yeah.wav'),
        ('Counter Culture/CC - Listen Up 1.wav', 'Listen_Up.wav')]:
        producer_asset('Producer Space/Packs/' + source, '04-vocals/' + name, 'Spoken vocal phrase / chop')
    for name in ['Bass Riff', 'Piano Riff', 'Strings']:
        folder = 'Bass' if name == 'Bass Riff' else 'Piano' if name == 'Piano Riff' else 'Strings'
        source = 'Producer Space/Packs/House Piano Riffs/MIDI Files/MIDI Files - ' + folder + '/HPR ' + name + ' - 012 - 124 BPM - F minor.mid'
        producer_asset(source, '03-midi/DOWNLOADED_HPR_' + folder + '_012_Fminor_124BPM.mid',
                       'Existing downloaded MIDI phrase', original_bpm=124, original_key='F minor')
    shutil.copyfile(ROOT / 'evidence/producer-space-license.html', PACK / 'LICENSES/Producer-Space-license.html')
    drum_building_block()
    adapt_downloaded_midis()
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(),
                'description': 'Curated multi-source CC0 materials, with a separately labelled original drum building block. Not a downloaded complete project or finished arrangement.',
                'assets': records}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('FETCH COMPLETE ' + str(len(records)) + ' assets', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['fetch', 'validate'])
    args = parser.parse_args()
    if args.stage == 'fetch':
        fetch()
    else:
        validate_and_zip()
