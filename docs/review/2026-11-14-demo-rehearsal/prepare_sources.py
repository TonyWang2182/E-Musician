"""Read bounded excerpts from supplied originals; write only new demo assets."""
from pathlib import Path
import hashlib
import json
import soundfile as sf
import numpy as np

destination = Path('E:/MusicAgent&DAW/demo-video/2026-11-14/sources')
destination.mkdir(parents=True, exist_ok=True)
specs = [
    ('New Light Source', Path('E:/E-musician/test-projects/test9-newlight/New Light()/New Light.mp3'), 60, 24, 'new-light-60-84.wav'),
    ('Tea Piano Source', Path('E:/E-musician/test-projects/test7-MIR task 2/T42-2.assets/a3ae0af6ad564f97a02099b556276e7c/2376f6baa7fe420d9f084da3379dfc2d.wav'), 20, 16, 'tea-piano-20-36.wav'),
]
records = []
for name, source, start, duration, filename in specs:
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = destination / filename
    if output.exists():
        raise RuntimeError('Refusing to overwrite an existing demo source: ' + str(output))
    with sf.SoundFile(source) as reader:
        rate = reader.samplerate
        reader.seek(int(start * rate))
        data = reader.read(int(duration * rate), dtype='float32', always_2d=True)
    assert len(data) == duration * rate and np.isfinite(data).all() and np.max(np.abs(data)) > 0
    sf.write(output, data, rate, subtype='FLOAT')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    records.append({'track_name': name, 'original': str(source), 'original_sha256': before,
        'source_start_seconds': start, 'duration_seconds': duration, 'output': str(output),
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'sample_rate': rate,
        'peak': float(np.max(np.abs(data))), 'source_unchanged': True, 'listening_verified': False})
report = Path(__file__).with_name('SOURCES.json')
report.write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'excerpts': len(records), 'source_unchanged': True, 'receipt': str(report)}))
