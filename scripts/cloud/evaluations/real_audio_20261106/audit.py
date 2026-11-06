"""Final local evidence audit; does not load models or copy result audio."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[4]
DOC = ROOT / 'docs/review/2026-11-06-real-audio'
HERE = Path(__file__).parent

def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    baseline = load(ROOT/'docs/builds/20261106T093624.026444Z-cf0feb7592.json')['source_fingerprint']['files']
    changed = [name for name, expected in baseline.items() if sha(ROOT/name) != expected]
    assert not changed, changed
    scripts = {}
    for path in sorted(HERE.rglob('*.py')):
        compile(path.read_text(encoding='utf8'), str(path), 'exec')
        scripts[path.relative_to(ROOT).as_posix()] = sha(path)
    inputs = {name: load(DOC/(name+'-input.json')) for name in ('newlight','piano')}
    for item in inputs.values():
        assert sha(item['source']) == item['sha256'] and item['trimmed'] is False
    outcomes = {}
    for model in ('scnet','chordmini','transkun'):
        parent = load(DOC/'mir/evidence'/model/'attempt.json')
        result = load(DOC/'mir/evidence'/model/'result.json')
        assert parent['status'] == result['status'] == 'passed'
        assert parent['exit_code'] == 0 and parent['result'] == result
        assert sha(HERE/'mir/whole_file.py') == result['script_sha256']
        assert sha(HERE/'mir/guard.py') == parent['guard_sha256']
        expected = inputs['piano' if model == 'transkun' else 'newlight']
        assert result['input']['sha256'] == expected['sha256']
        assert result['input']['frames'] == expected['frames']
        if model != 'chordmini':
            assert result['decoded_input_frames'] == expected['frames']
        else:
            assert all(abs(item['end_seconds']-expected['duration_seconds']) < 1e-6 for item in result['outputs'])
        outcomes[model] = {'output': parent['output'], 'wall_seconds': parent['wall_seconds'], 'input_sha256': expected['sha256'], 'actual_inference_count': 1}
    parent = load(DOC/'scores/evidence/guard-receipt.json')
    result = load(DOC/'scores/evidence/result-receipt.json')
    assert parent['status'] == result['status'] == 'passed' and parent['exit_code'] == 0
    assert parent['result'] == result
    assert parent['guard_script']['sha256'] == sha(HERE/'scores/run.py')
    assert result['input']['sha256'] == inputs['newlight']['sha256'] and result['input_cropped'] is False
    assert result['whole_input_decoded'] is True and result['token_limit_reached'] is False
    outcomes['sheetsage2'] = {'output': parent['output'], 'wall_seconds': parent['elapsed_seconds'], 'input_sha256': result['input']['sha256'], 'actual_inference_count': 1}
    delivery = load(DOC/'delivery.json')
    assert delivery['status'] == 'passed' and delivery['audio_downloaded_to_e'] is False
    archive = load(DOC/'archive.json')
    assert delivery['sha256'] == archive['sha256'] and delivery['bytes'] == archive['bytes']
    assert delivery['crc_and_member_sha_verified'] is True and delivery['whole_archive_sha_verified'] is True
    assert set(archive['selected_directories']) == {Path(item['output']).name for item in outcomes.values()}
    sensitive = re.compile(r'(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{24,})')
    for folder in (DOC,HERE):
        for path in folder.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            assert path.suffix.lower() not in {'.wav','.mp3','.flac','.pt','.safetensors','.mid','.zip'}
            assert not sensitive.search(path.read_text(encoding='utf8')), 'Credential-like value: '+str(path)
    report = {'checked_utc': datetime.now(timezone.utc).isoformat(), 'status':'passed',
        'original_inputs_unchanged':True, 'complete_original_inputs_processed':True,
        'daw_build_source_files_unchanged':len(baseline), 'executed_model_scripts_match_final_source':True,
        'results':outcomes, 'scripts_sha256':scripts, 'delivery':delivery,
        'quality_or_listening_verified':False, 'muscriptor_weights_authorized':False,
        'no_model_or_audio_download_to_e':True}
    (DOC/'VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'passed','models':list(outcomes),'unchanged_daw_files':len(baseline),'archive':delivery['archive']}))

if __name__ == '__main__':
    main()
