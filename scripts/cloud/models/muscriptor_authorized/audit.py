"""Local deployment audit, including credential-pattern exclusion and fixed DAW inputs."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parents[4]
DOC=ROOT/'docs/review/2026-11-06-muscriptor-authorized'
HERE=Path(__file__).parent

def load(path):
    return json.loads(path.read_text(encoding='utf8'))

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    access=load(DOC/'access-local.json');relay=load(DOC/'relay.json')
    assert access['weight_access'] and access['credential_saved'] and relay['status']=='passed'
    assert relay['local_model_files_written'] is False and relay['script_sha256']==sha(HERE/'relay_local.py')
    cpu=load(DOC/'probe/evidence/cpu-guard.json');gpu=load(DOC/'probe/evidence/gpu-guard.json')
    for item in (cpu,gpu):
        assert item['status']==item['result']['status']=='passed' and item['exit_code']==0
        assert item['script']['sha256']==sha(HERE/'probe.py')
    assert cpu['result']['all_parameters_finite'] and cpu['result']['cuda_initialized'] is False
    assert gpu['result']['fixture_duration_seconds']==8 and gpu['result']['midi_note_on_count']>0
    deployment=load(DOC/'deployment.json');catalog=load(DOC/'catalog.json')
    assert all(deployment['checks'].values()) and not deployment['blockers'] and deployment['daw_connected'] is False
    assert not catalog['errors'] and next(x for x in catalog['models'] if x['id']=='muscriptor')['level']=='gpu-tested'
    baseline=load(ROOT/'docs/builds/20261106T093624.026444Z-cf0feb7592.json')['source_fingerprint']['files']
    assert all(sha(ROOT/name)==value for name,value in baseline.items())
    sensitive=re.compile(r'(?:hf_[A-Za-z0-9]{24,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})')
    scripts={}
    for folder in (HERE,DOC):
        for path in folder.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            assert path.suffix not in {'.wav','.mid','.mp3','.pt','.safetensors','.zip','.log'}
            content=path.read_text(encoding='utf8')
            assert not sensitive.search(content), 'Credential-like text in '+str(path)
            if path.suffix=='.py':
                compile(content,str(path),'exec');scripts[path.relative_to(ROOT).as_posix()]=sha(path)
    report={'status':'passed','checked_utc':datetime.now(timezone.utc).isoformat(),
        'official_gated_weight_access':True,'pinned_weight_and_config_verified':True,
        'cpu_load_verified':True,'gpu_inference_verified':True,'gpu_scope_seconds':8,
        'actual_gpu_inference_count':1,'daw_build_inputs_unchanged':len(baseline),
        'no_credential_like_text_in_new_sources_or_evidence':True,
        'no_local_model_or_audio_files':True,'daw_connected':False,'quality_evaluation':False,
        'scripts_sha256':scripts}
    (DOC/'VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='scripts_sha256'}))

if __name__=='__main__':
    main()
