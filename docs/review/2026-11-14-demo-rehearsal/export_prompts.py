"""Export verbatim tested prompt inputs for manual copy/paste."""
import hashlib
import json
from pathlib import Path

review = Path(__file__).resolve().parent
cases = json.loads((review/'cases.json').read_text(encoding='utf-8'))
destination = Path('E:/MusicAgent&DAW/demo-video/2026-11-14/prompts')
destination.mkdir(parents=True, exist_ok=True)
receipt = []
for case in cases:
    data = (case['prompt']+'\n').encode('utf-8')
    path = destination/(case['id']+'.txt')
    if path.exists() and path.read_bytes() != data:
        raise RuntimeError('Existing prompt differs; preserve it before updating: '+str(path))
    path.write_bytes(data)
    receipt.append({'id': case['id'], 'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()})
(review/'PROMPT-FILES.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'exported': len(receipt), 'directory': str(destination)}))
