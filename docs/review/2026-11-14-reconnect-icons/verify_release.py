"""Bounded final evidence check; no inference, audio, UI automation or project edits."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts'))
import register_project_file as association


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(identifier, expected):
    paths = list((ROOT / 'docs/builds').glob('*-' + identifier + '.json'))
    assert len(paths) == 1, identifier
    value = read(paths[0])
    assert value['status'] == expected, (identifier, value['status'])
    return {'id': value['id'], 'status': value['status'], 'command': value['command']}


def main():
    final = read(REVIEW / 'NATIVE-INPUTS.json')['inputs']
    first = read(REVIEW / 'NATIVE-INPUTS-FIRST.json')['inputs']
    assert set(final) == set(first)
    changed = [name for name in final if first[name] != final[name]]
    assert changed == ['tests/MainWorkspaceSmoke.inc'], changed
    for name, digest in final.items():
        assert sha(ROOT / name) == digest, name
    old = read(REVIEW / 'PRESERVED.json')['executables']
    for name, digest in old.items():
        assert sha(Path(name)) == digest, name
    for name, digest in read(REVIEW / 'LAUNCHERS.json').items():
        assert sha(Path(name)) == digest, name
    exe = Path('E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe')
    capabilities = read(REVIEW / 'DESKTOP-CAPABILITIES.json')
    assert capabilities['passed'] and capabilities['exe_sha256'] == sha(exe)
    assert len(capabilities['checked_routes']['cloud']) == 7
    assert len(capabilities['checked_routes']['local']) == 4
    assert capabilities['checked_routes']['six_stem_option']
    current = association.status(association.WindowsRegistry(), exe)
    assert Path(current['effective_executable']).resolve() == exe.resolve(), current['effective_executable']
    assert str(exe).replace('/', '\\').lower() in current['effective_icon'].lower()
    assert current['executable_icon_groups'] > 0
    (REVIEW / 'ASSOCIATION.json').write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    startup = read(REVIEW / 'STARTUP.json')
    assert startup['responding'] and '0.13.3' in startup['window_title']
    assert startup['agent_helpers'][0]['native_authenticated_connection_live']
    cloud = read(REVIEW / 'CLOUD.json')
    assert cloud['inference_performed'] is False
    evidence = [record('e3a71b29ba', 'succeeded'), record('bbc82c6f3e', 'failed'),
                record('7b242e79f9', 'succeeded'), record('277453f89c', 'succeeded'),
                record('9773306b76', 'succeeded'), record('17e8b5ca71', 'succeeded')]
    for src, dest in [
        ('build/smoke/Release/1a0568a12cbd/arrangement-track-actions-dpi.png', 'track-actions-dpi.png'),
        ('build/smoke/Release/1a0568a12cbd/arrangement-report.json', 'ARRANGEMENT.json'),
        ('build/workspace-smoke/6ddd4fed7149/workspace-brand-report.json', 'WORKSPACE.json'),
    ]:
        shutil.copy2(ROOT / src, REVIEW / dest)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'executable': str(exe), 'exe_sha256': sha(exe),
              'native_inputs_verified': len(final), 'second_build_changed_only': changed,
              'old_executables_preserved': list(old), 'launchers_verified': True,
              'effective_association_verified': True, 'records': evidence,
              'validation_scope': 'Initial full CTest 10/11, then test-only wait fix and targeted workspace 1/1. No second full CTest.',
              'cloud_inference_or_audio_tested_this_iteration': False}
    (REVIEW / 'VERIFICATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'native_inputs_verified': len(final), 'effective_association_verified': True}))


if __name__ == '__main__':
    main()
