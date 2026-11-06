"""Freeze evidence for the hybrid candidate; never invokes a model or mutates projects."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from dev import ROOT, source_fingerprint, write_json


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', required=True)
    parser.add_argument('--ctest', required=True)
    parser.add_argument('--e2e', required=True, nargs='+', type=Path)
    args = parser.parse_args()
    output = ROOT / 'docs/review/2026-11-07-hybrid-pipeline'
    evidence = output / 'evidence'
    evidence.mkdir(exist_ok=True)
    executable = Path('E:/emusician-analysis-build/bin-0.13.0/Release/E-musician.exe')
    executable_hash = sha(executable)
    current = source_fingerprint()
    assert not current['errors']
    records = []
    for identifier in (args.build, args.ctest):
        record = read(ROOT / 'docs/builds' / (identifier + '.json'))
        assert record['status'] == 'succeeded', identifier
        native = {name: digest for name, digest in current['files'].items()
            if name.startswith(('apps/', 'core/', 'cmake/', 'assets/'))
            or name in ('CMakeLists.txt', 'CMakePresets.json') or name.endswith(('.cpp', '.h', '.hpp', '.inc'))}
        for name, digest in native.items():
            assert record['source_fingerprint']['files'].get(name) == digest, (identifier, name)
            assert record['source_fingerprint_end']['files'].get(name) == digest, (identifier, name)
        records.append({'id': identifier, 'elapsed_seconds': record['elapsed_seconds'], 'native_inputs_match': True})
    models = {}
    reports = []
    for index, path in enumerate(args.e2e):
        value = read(path)
        assert value['protected_unchanged'] and value['frozen_exe_unchanged'], str(path)
        assert value['exe_sha256'] == executable_hash, str(path)
        for item in value['inputs'].values():
            assert sha(item['path']) == item['sha256']
        copied = evidence / ('native-e2e-' + str(index + 1) + '.json')
        shutil.copyfile(path, copied)
        reports.append({'path': str(path), 'evidence': copied.relative_to(ROOT).as_posix(), 'sha256': sha(copied), 'passed': value['passed']})
        for item in value['models']:
            if item['passed']:
                assert all(phase['passed'] for phase in item['phases'])
                project = item['project']
                assert sha(project['path']) == project['sha256']
                models[item['model_id']] = {'passed': True, 'kind': item['kind'], 'project': project,
                    'summary': item.get('candidate', {}).get('summary'), 'phases': item['phases'],
                    'completion': item.get('candidate', {}).get('completion')}
    assert set(models) == {'scnet','transkun','chordmini','muscriptor','sheetsage2','ace-step-1.5-xl-turbo','yue2'}, set(models)
    for item in models.values():
        if item['kind'] == 'generate':
            completion = item['completion']
            assert isinstance(completion, dict)
            assert completion['truncated'] is None or type(completion['truncated']) is bool
            assert completion['reason'] == ('token_budget' if completion['truncated'] is True else 'model_stop' if completion['truncated'] is False else 'unknown')
    deployment = read(output / 'DEPLOYMENT.json')
    assert deployment['status'] == 'ready'
    for relative, digest in deployment['files_verified'].items():
        # Installer is an activation receipt, not running service code.
        if relative.startswith('compute/'):
            assert sha(ROOT / 'scripts/cloud' / relative) == digest, relative
    preserved = read(ROOT / 'docs/review/2026-11-06-generation-stability/VERIFICATION.json')['executables']
    for item in preserved:
        assert sha(item['path']) == item['sha256'], item['version']
    result = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'status': 'automated pipeline acceptance passed; manual audio and music quality pending',
        'executable': {'path': str(executable), 'bytes': executable.stat().st_size, 'sha256': executable_hash},
        'source_fingerprint': current, 'native_build_test_records': records,
        'e2e_reports': reports, 'models': models, 'cloud_release': deployment['release'],
        'cloud_runtime_matches_deployment': True, 'preserved_executables': preserved,
        'physical_audio_verified': False, 'musical_accuracy_verified': False, 'real_llm_called_this_iteration': False,
        'performance_scope': 'Native tests use offline devices. E2E control timing is request round-trip, not GUI frame rate or ASIO latency.'}
    write_json(output / 'VERIFICATION.json', result)
    print(json.dumps({'status': result['status'], 'models': len(models), 'exe_sha256': executable_hash, 'source_files': len(current['files'])}))


if __name__ == '__main__':
    main()
