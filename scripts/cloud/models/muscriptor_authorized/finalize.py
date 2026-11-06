"""Promote only verified MuScriptor medium deployment evidence; no service activation."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import time
from library_status import collect

ROOT=Path('/root/autodl-tmp/emusician')

def load(path):
    return json.loads(path.read_text(encoding='utf8'))

def artifact(path):
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(path),'bytes':path.stat().st_size,'sha256':digest}

def write(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8');temporary.replace(path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cpu',type=Path,required=True)
    parser.add_argument('--gpu',type=Path,required=True)
    args=parser.parse_args()
    assert os.name=='posix'
    baseline_catalog=collect(ROOT)
    assert not baseline_catalog['errors'] and baseline_catalog['minimum_free_budget_satisfied']
    access_path=ROOT/'manifests/model-library/muscriptor/authorized-access.json'
    relay_path=ROOT/'manifests/model-library/muscriptor/authorized-relay.json'
    access=load(access_path);relay=load(relay_path)
    assert access['weight_access'] and access['credential_saved'] and relay['status']=='passed'
    assert access['revision']==relay['revision']=='f32236969308476e01fd3aae67357de5feb05a2d'
    for item in relay['files']:
        actual=artifact(Path(item['path']))
        assert all(actual[k]==item[k] for k in ('path','bytes','sha256'))
    results={}
    for mode,path in (('cpu',args.cpu),('gpu',args.gpu)):
        assert path.resolve().is_relative_to(ROOT/'results/muscriptor-authorized')
        parent=load(path/'guard.json');child=load(path/'result.json')
        assert parent['status']==child['status']=='passed' and parent['exit_code']==0
        assert parent['result']==child and child['mode']==mode and child['daw_connected'] is False
        assert artifact(Path(parent['script']['path']))['sha256']==parent['script']['sha256']
        results[mode]=child
        for item in child['artifacts']:
            assert artifact(Path(item['path']))==item
    assert results['cpu']['all_parameters_finite'] and not results['cpu']['cuda_initialized']
    assert results['gpu']['fixture_duration_seconds']==8 and results['gpu']['full_original_test'] is False
    assert results['gpu']['midi_note_on_count']>0
    for key in ('source_revision','model_revision','config','parameter_count'):
        assert results['cpu'][key]==results['gpu'][key]
    assert results['cpu']['source_revision']=='8a1ef88672cc23c26619adaff37ec48d82c0b906'
    assert results['cpu']['model_revision']==relay['revision']
    for item in [results['gpu']['fixture'],*results['gpu']['outputs']]:
        assert artifact(Path(item['path']))==item
    manifest=ROOT/'manifests/model-library/muscriptor/deployment.json'
    previous=load(manifest)
    for item in previous['artifacts']:
        assert artifact(Path(item['path']))==item,'Existing deployment artifact changed'
    assert previous['checks']['environment_verified']
    backup=manifest.with_name('deployment-before-authorized.json')
    if not backup.exists():
        with backup.open('x',encoding='utf8') as stream:
            json.dump(previous,stream,indent=2)
    value=dict(previous)
    value['checks']={key:True for key in ('files_verified','environment_verified','cpu_load_verified','gpu_inference_verified')}
    value['blockers']=[]
    value['authorized_weight_access_verified']=True
    value['authorization_evidence']=str(access_path)
    value['updated_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    value['cloud_free_bytes']=shutil.disk_usage(ROOT).free
    value['gpu_verified_scope']='Exactly first8seconds of Keyboard.mp3, two native5s chunks; structural MIDI checks only, no full-song or accuracy acceptance'
    value['paths'].update(weights=str(ROOT/'models/muscriptor/model.safetensors'),config=str(ROOT/'models/muscriptor/config.json'))
    value['entrypoints'].update(guarded_probe=load(args.gpu/'guard.json')['script']['path'])
    value['cpu_load_seconds']=results['cpu']['load_seconds']
    value['gpu_probe']={'receipt':str(args.gpu/'guard.json'),'result':str(args.gpu/'result.json')}
    value['cpu_probe']={'receipt':str(args.cpu/'guard.json'),'result':str(args.cpu/'result.json')}
    value['parameter_count']=results['cpu']['parameter_count']
    value['retained_limitations']=['Medium only; large not downloaded','One8second fixture only; no real-song transcription accuracy acceptance','MIDI default velocity100 is not measured dynamics; default120BPM metadata is not detected tempo','CC-BY-NC-4.0 model weights; separate commercial permission required','No DAW/Agent integration; existing services unchanged']
    additions=[Path(item['path']) for item in results['cpu']['artifacts']]
    additions += [args.cpu/'guard.json',args.cpu/'result.json',args.gpu/'guard.json',args.gpu/'result.json']
    additions += [access_path,relay_path]
    old={item['path']:item for item in previous['artifacts']}
    old.update({str(path):artifact(path) for path in additions})
    value['artifacts']=list(old.values())
    value['download_route']='Official HF HTTPS through bounded local RAM directly into SSH cloud receiver; no local weights file'
    write(manifest,value)
    catalog=collect(ROOT)
    assert not catalog['errors'] and catalog['minimum_free_budget_satisfied']
    write(ROOT/'manifests/model-library/catalog.json',catalog)
    print(json.dumps({'model':'muscriptor','checks':value['checks'],'free_disk_bytes':value['cloud_free_bytes'],'daw_connected':False,'catalog_errors':catalog['errors']}))

if __name__=='__main__':
    main()
