"""Validate saved cloud probe outputs and finalize per-model manifests, without inference."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/autodl-tmp/emusician')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('id', choices=('scnet', 'transkun', 'chordmini'))
args = parser.parse_args()
folder = ROOT / 'manifests/model-library' / args.id
manifest = json.loads((folder / 'deployment.json').read_text())
for item in manifest['artifacts']:
    path = Path(item['path'])
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != item['sha256'] or path.stat().st_size != item['bytes']:
        raise ValueError(f'Final source/weight/lock integrity changed: {path}')
probe_path = max(folder.glob('gpu-probe-*.json'))
probe = json.loads(probe_path.read_text())
if probe['status'] != 'passed':
    raise ValueError('Latest GPU probe did not pass')
result = probe['result']
validation = []
for item in result['outputs']:
    path = Path(item['path'])
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != item['sha256'] or path.stat().st_size != item['bytes']:
        raise ValueError('Output receipt mismatch')
    if args.id == 'scnet':
        import numpy as np
        import soundfile as sf
        audio, rate = sf.read(path, dtype='float32', always_2d=True)
        assert np.isfinite(audio).all() and np.any(audio != 0)
        assert len(audio) == rate * 8 and audio.shape[1] == 2
        validation.append({'path': str(path), 'duration_seconds': len(audio) / rate,
                           'finite': True, 'nonzero': True, 'channels': 2})
    elif args.id == 'transkun':
        import pretty_midi
        midi = pretty_midi.PrettyMIDI(str(path))
        notes = [note for instrument in midi.instruments for note in instrument.notes]
        controls = [cc for instrument in midi.instruments for cc in instrument.control_changes]
        assert notes and controls and all(0 <= n.start < n.end and 0 <= n.pitch <= 127 for n in notes)
        validation.append({'path': str(path), 'notes': len(notes), 'control_changes': len(controls),
                           'first_note_seconds': min(n.start for n in notes),
                           'last_note_end_seconds': max(n.end for n in notes),
                           'last_control_seconds': max(c.time for c in controls),
                           'control_numbers': sorted({c.number for c in controls})})
    else:
        rows = [line.split() for line in path.read_text().splitlines()]
        assert rows and all(0 <= float(row[0]) < float(row[1]) <= 8.000001 for row in rows)
        assert all(abs(float(a[1]) - float(b[0])) < 0.00001 for a, b in zip(rows, rows[1:]))
        validation.append({'path': str(path), 'segments': len(rows), 'start_seconds': float(rows[0][0]),
                           'end_seconds': float(rows[-1][1]), 'contiguous': True})
manifest['checks']['gpu_inference_verified'] = True
manifest['gpu_probe'] = str(probe_path)
manifest['probe_result'] = result
manifest['output_validation'] = validation
manifest['blockers'] = ['Independent quality/accuracy evaluation and long-audio load tests not performed',
                        'DAW integration not authorized in this phase']
manifest['source_modifications'] = []
manifest['cli'] = {'python': str(ROOT / 'envs' / args.id / 'bin/python'),
                   'script': str(ROOT / 'tools/models/mir_upgrades/infer.py'),
                   'arguments': f'{args.id} --input <cloud audio> --output <new cloud results directory> --device cuda',
                   'constraint': 'Only one root-authorized GPU workload; bounded CLI input <=120s, tested only8s'}
manifest['support_limits'] = {
    'scnet': 'Four stems only: drums, bass, other, vocals; not lead/backing vocals or separate guitars/keyboards.',
    'transkun': 'Piano-specific; this real inference emitted CC64 and CC67 and the MIDI writer preserved them. No ground truth or pedal-accuracy evaluation.',
    'chordmini': '170 labels: 12 roots x14 chord qualities plus X/N. No explicit 9th/11th/13th or slash-bass classes; no jazz-accuracy claim.',
}[args.id]
for path in sorted((ROOT / 'tools/models/mir_upgrades').glob('*.py')):
    manifest['artifacts'].append({'path': str(path), 'bytes': path.stat().st_size,
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
(folder / 'deployment.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'id': args.id, 'checks': manifest['checks'], 'output_validation': validation}), flush=True)
