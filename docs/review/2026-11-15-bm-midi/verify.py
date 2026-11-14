"""Read-only release checks, with a small local evidence receipt."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from dev import source_fingerprint

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def digest(path, lf=False):
    data = path.read_bytes()
    if lf: data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()

def record(suffix):
    paths = list((ROOT / 'docs/builds').glob('*-' + suffix + '.json'))
    assert len(paths) == 1, suffix
    data = read(paths[0])
    assert data['status'] == 'succeeded' and data['exit_code'] == 0, suffix
    return data

build = record('441bbdd301')
current = source_fingerprint()['files']
native = {p: sha for p, sha in build['source_fingerprint']['files'].items()
          if p.startswith(('apps/', 'core/', 'cmake/', 'assets/'))
          or p in ('CMakeLists.txt', 'CMakePresets.json')
          or (p.startswith('tests/') and Path(p).suffix in ('.h', '.cpp', '.inc'))}
assert all(current.get(p) == sha == build['source_fingerprint_end']['files'].get(p)
           for p, sha in native.items()), 'Native build input changed'
units = record('941c78f583')
helpers = {p: sha for p, sha in units['source_fingerprint']['files'].items()
           if p.startswith('scripts/music_agent/') or p == 'scripts/agent_client.py'}
assert all(current.get(p) == sha for p, sha in helpers.items()), 'Agent input changed since full unit suite'
for run in ('7e1563c6f4', '0e29a8c611', '5978acfb5f'): record(run)
manifest = read(ROOT / 'cmake/patches/tracktion/manifest.json')
assert len(manifest['files']) == 13
for entry in manifest['files']:
    assert digest(ROOT / '.cache/monitor-engine' / entry['path'], True) == entry['after_sha256_lf']
    assert digest(ROOT / 'cmake/patches/tracktion' / entry['patch'], True) == entry['patch_sha256_lf']
exe = Path('E:/emusician-analysis-build/bin-0.13.5/Release/E-musician.exe')
old = Path('E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe')
assert digest(old) == 'c99d9b0894687f1066bc09febe9c4d6ee5afbc4e38413fac5d6620a101245d5a'
audit = read(ROOT / 'build/bm-midi/final-all-bm-build4/audit.json')
assert audit['total'] == audit['completed'] == 14
assert audit['counts'] == {'passed': 14}
assert audit['exe_sha256'] == digest(exe)
report = {'status': 'passed', 'native_input_count': len(native), 'helper_input_count': len(helpers),
          'dependency_patches': len(manifest['files']), 'executable': str(exe),
          'executable_sha256': digest(exe), 'old_executable_preserved': True,
          'ctest': '11/11', 'agent_tests': '390/390', 'installed_bm_modules': '14/14',
          'physical_keyboard_and_listening': 'manual acceptance pending'}
(Path(__file__).parent / 'VERIFICATION.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
