"""Final read-only artifact/native compatibility checks; no LLM or music jobs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
from agent_client import Client
from music_agent.bridge import DawBridge
from DemoPromptLiveCheck import music_state

HERE = Path(__file__).resolve().parent
DELIVERY = Path('E:/MusicAgent&DAW/demo-video/2026-11-14')
EXE = Path('E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    report = {'passed': False, 'started_at': datetime.now(timezone.utc).isoformat(),
              'external_llm': False, 'music_model_called': False, 'physical_audio': False,
              'exe_sha256': sha(EXE), 'reopened_projects': [], 'archives': [], 'checks': []}
    try:
        assert sha('E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe') == '90c7a476618bccc01e581b47d46b3880422143b8382e000bb915e94108c9baa3'
        build = json.loads((ROOT / 'docs/builds/20261114T113636.433801Z-a6c0ed02d5.json').read_text(encoding='utf-8'))
        native = {name: value for name, value in build['source_fingerprint']['files'].items()
                  if Path(name).suffix.lower() in {'.cpp', '.h', '.hpp', '.inc', '.cmake'} or name in {'CMakeLists.txt', 'CMakePresets.json'}}
        for name, digest in native.items():
            assert sha(ROOT / name) == digest, 'Native build input changed: ' + name
        report['checks'].append(f'{len(native)} native/build inputs still match the successful Release record; 0.13.3 EXE preserved')
        directory = ROOT / 'build/demo-delivery-final' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        owned_exe = directory / 'E-musician.exe'; shutil.copy2(EXE, owned_exe)
        receipt = json.loads((HERE.parent / '2026-11-14-demo-rehearsal/RECEIPTS.json').read_text(encoding='utf-8'))
        with Client(owned_exe, timeout=90, show=False, offline_test=True) as client:
            bridge = DawBridge(client=client)
            for case in receipt['cases']:
                if not case.get('passed'): continue
                full = json.loads(Path(case['report_path']).read_text(encoding='utf-8'))
                project = Path(case['project']); before = sha(project)
                assert before == case['project_sha256']
                client.request({'command': 'open_project', 'args': {'path': str(project)}})
                assert music_state(client, bridge) == full['accepted_musical_state'], case['case_id']
                assert sha(project) == before
                for asset in case['accepted_audio_paths']:
                    assert sha(asset['path']) == asset['sha256']
                report['reopened_projects'].append({'case_id': case['case_id'], 'path': str(project), 'sha256': before,
                                                    'musical_state_equal': True, 'assets_unchanged': True})
        assert len(report['reopened_projects']) == 6
        for name in ('D4-MIX-en.txt', 'D4-MIX-zh.txt'):
            assert sha(HERE / name) == sha(DELIVERY / 'prompts' / name)
        for path in [DELIVERY / 'jungle-materials/jungle-materials-cc0.zip',
                     DELIVERY / 'jungle-materials/personal-reference/Antidote Audio - Jungle in Ableton Project.zip',
                     DELIVERY / 'motion/E-musician-motion-1080p30.zip']:
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
                members = len(archive.infolist())
            report['archives'].append({'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size, 'members': members})
        files = [*HERE.glob('*.md'), ROOT / 'docs/demo/2026-11-14-demo-runbook-v0134.md', DELIVERY / 'OPEN-FIRST.md']
        link_count = 0
        for path in files:
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                target = target.strip('<>').split('#')[0]
                if not target or target.startswith(('http:', 'https:')): continue
                if re.match(r'^[A-Za-z]:[\\/]', target): resolved = Path(target)
                else: resolved = path.parent / target
                assert resolved.exists(), f'Broken link in {path.name}: {target}'
                link_count += 1
        report['checks'].append(f'{link_count} local document links exist')
        report['passed'] = True
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (HERE / 'DELIVERY-CHECK.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'projects': len(report['reopened_projects']), 'archives': len(report['archives'])}))

if __name__ == '__main__':
    main()
