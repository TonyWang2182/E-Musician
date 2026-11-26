"""Validate and package the November 27 script/title revision, without editing a film."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path('E:/MusicAgent&DAW/demo-video/application-script-2026-11-27')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deliver() -> None:
    script = ROOT / 'docs/demo/2026-11-27-application-script.md'
    text = script.read_text(encoding='utf-8')
    assert text == (KIT / 'SCRIPT.md').read_text(encoding='utf-8')
    parts = re.split(r'^## Part ', text, flags=re.M)[1:]
    assert len(parts) == 14
    assert text.startswith('## Part 1')
    expected = [14, 4, 42, 4, 24, 4, 23, 4, 17, 4, 22, 4, 60, 14]
    cursor = words = 0
    timing = []
    for i, (part, seconds) in enumerate(zip(parts, expected), 1):
        assert part.startswith(f'{i}｜')
        m = re.search(r'时长：(\d+) 秒｜(\d\d):(\d\d)–(\d\d):(\d\d)', part)
        assert m, i
        length, sm, ss, em, es = map(int, m.groups())
        start, end = sm * 60 + ss, em * 60 + es
        assert start == cursor and end - start == seconds == length
        assert part.count('**展示画面和操作：**') == 1
        assert part.count('**中文翻译：**') == 1
        if '**英文台词：**' in part:
            spoken = part.split('**英文台词：**', 1)[1].split('**中文翻译：**', 1)[0]
            count = len(re.findall(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*", re.sub(r'\d\d:\d\d–\d\d:\d\d：', '', spoken)))
            words += count
        else:
            count = 0
            assert '**英文台词（画面文字；无旁白）：**' in part
        timing.append(dict(part=i, start=start, end=end, seconds=seconds, spoken_words=count))
        cursor = end
    assert cursor == 240

    motion = KIT / 'motion'
    manifest = json.loads((motion / 'MANIFEST.json').read_text(encoding='utf-8'))
    validation = json.loads((motion / 'VALIDATION.json').read_text(encoding='utf-8'))
    assert validation['status'] == 'passed' and len(validation['assets']) == 8
    assets = manifest['assets']
    assert [a['part'] for a in assets] == [1, 2, 4, 6, 8, 10, 12, 14]
    assert sum(a['seconds'] for a in assets) == 52
    for item in assets:
        assert digest(motion / item['file']) == item['sha256']
        assert digest(Path(item['source'])) == item['source_sha256']
        assert item['seconds'] == expected[item['part'] - 1]
        assert item['title'] in parts[item['part'] - 1]
    assert digest(ROOT / 'assets/brand/yi-yue-shi-logo.png') == manifest['logo_sha256']
    refs = json.loads((KIT / 'reference-review/extraction-receipt.json').read_text(encoding='utf-8'))
    assert len(refs['references']) == 5
    for ref in refs['references']:
        assert digest(Path(ref['source'])) == ref['sha256']

    archive = KIT / 'Title-transitions.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        for item in assets:
            z.write(motion / item['file'], item['file'])
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.namelist() == [a['file'] for a in assets]
        for item in assets:
            assert hashlib.sha256(z.read(item['file'])).hexdigest() == item['sha256']
    result = dict(
        checked_at=datetime.now(timezone.utc).isoformat(), status='passed',
        script_sha256=digest(script), script_seconds=cursor, script_parts=14,
        spoken_english_words=words, timing=timing,
        original_references_unchanged=True, original_backgrounds_and_logo_unchanged=True,
        archive=archive.name, archive_bytes=archive.stat().st_size,
        archive_sha256=digest(archive), archive_entries=8, archive_crc_passed=True,
        assets=[{k: a[k] for k in ('part', 'file', 'seconds', 'sha256')} for a in assets],
        boundary='Script and motion assets only. No new finished film, narration, DAW build, inference, GUI or device test.',
    )
    (KIT / 'DELIVERY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'script_seconds', 'script_parts', 'spoken_english_words', 'archive_entries', 'archive_bytes', 'archive_sha256')}))


if __name__ == '__main__':
    if '--record' in sys.argv:
        from dev import Recorder
        Recorder('application-film-package', '240s-script; 8x1080p30-titles',
                 'Validate timeline, bilingual structure, title mapping, unchanged inputs and ZIP CRC; package new title videos only.').execute(
                     [sys.executable, str(Path(__file__).resolve())])
    else:
        deliver()
