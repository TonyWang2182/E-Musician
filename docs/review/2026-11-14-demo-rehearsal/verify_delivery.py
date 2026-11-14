"""Offline verification of the delivered prompts, saved assets and evidence."""
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
cases = json.loads((HERE/'cases.json').read_text(encoding='utf-8'))
operations = REPO/'docs/demo/2026-11-14-demo-operations.md'
text = operations.read_text(encoding='utf-8')
blocks = re.findall(r'```text\n(.*?)\n```', text, re.S)
assert blocks == [c['prompt'] for c in cases], 'Displayed prompts differ from tested inputs'
assert '实测进行中' not in text, 'Unfinalized operation statuses'
exports = json.loads((HERE/'PROMPT-FILES.json').read_text(encoding='utf-8'))
for case, item in zip(cases, exports):
    raw = Path(item['path']).read_bytes()
    assert item['id'] == case['id'] and raw == (case['prompt']+'\n').encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == item['sha256']

receipts = json.loads((HERE/'RECEIPTS.json').read_text(encoding='utf-8'))
passed = [r for r in receipts['cases'] if r['passed']]
assert len(passed) == 6 and {r['case_id'] for r in passed} == {c['id'] for c in cases}
assert sum(r['exact_prompt_verified'] for r in passed) == 1
assert receipts['api_diagnostic']['classification'] == 'insufficient_quota'
audio = []
for receipt in passed:
    assert receipt['input_files_unchanged'] and receipt['small_settings_unchanged']
    assert hashlib.sha256(Path(receipt['report_path']).read_bytes()).hexdigest() == receipt['report_sha256']
    assert hashlib.sha256(Path(receipt['project']).read_bytes()).hexdigest() == receipt['project_sha256']
    for item in receipt['accepted_audio_paths']:
        path = Path(item['path'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
        peak, frames = 0.0, 0
        with sf.SoundFile(path) as sound:
            rate, channels = sound.samplerate, sound.channels
            for block in sound.blocks(blocksize=65536, dtype='float32', always_2d=True):
                assert np.isfinite(block).all(), 'Audio contains NaN/Inf'
                peak = max(peak, float(np.max(np.abs(block))))
                frames += len(block)
        assert frames > 0 and peak > 1e-8, 'Saved audio is empty or digitally silent'
        audio.append({'case_id': receipt['case_id'], 'path': str(path), 'sample_rate': rate,
                      'channels': channels, 'frames': frames, 'peak': peak,
                      'listening_verified': False})

links = []
documents = [operations, REPO/'docs/demo/2026-11-12-four-minute-demo.md', HERE/'RESULTS.md', HERE/'MANUAL-FALLBACK.md']
for path in documents:
    for link in re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)', path.read_text(encoding='utf-8')):
        link = link.strip('<>')
        if re.match(r'https?://', link): continue
        target = Path(link) if Path(link).is_absolute() else path.parent/link
        assert target.exists(), f'Broken local link in {path.name}: {link}'
        links.append({'document': path.name, 'target': link})
result = {'passed': True, 'exact_prompt_live_passes': 1, 'direct_pipeline_passes': 5,
          'prompt_txt_pairs_verified': 6, 'saved_projects_verified': 6,
          'audio': audio, 'local_links_checked': len(links),
          'scope': 'Offline artifact checks; not GUI, physical playback, model accuracy or listening.'}
(HERE/'DELIVERY-CHECK.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k: result[k] for k in ('passed','exact_prompt_live_passes','direct_pipeline_passes','prompt_txt_pairs_verified','saved_projects_verified','local_links_checked')}, ensure_ascii=False))
