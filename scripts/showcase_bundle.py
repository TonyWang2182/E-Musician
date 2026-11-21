"""Package verified historical results and three clean starting projects, offline."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import uuid

DATA = Path('E:/MusicAgent&DAW')
OLD = DATA / 'demo-video/2026-11-14'
DEFAULT = DATA / 'demo-video/showcase-v1/workspace'
PROMPTS = {
 'yue': 'Use YuE2 to create a short neo-soul idea at 90 BPM in 4/4, with warm Rhodes, mellow electric guitar, rounded bass, laid-back drums, and intimate female vocals. Include a short intro, verse, and chorus. Let me preview it before adding it.',
 'ace': 'Use ACE-Step for another take of the same neo-soul brief at 90 BPM in 4/4. Keep the warm Rhodes, mellow guitar, rounded bass, laid-back drums, and intimate female vocal. Let me preview it before adding it.',
 'separate': 'Use SCNet to separate the selected audio into vocals, drums, bass, and other. Keep the original track and its name. Let me apply all four stems together.',
 'chords': 'Analyze the chords in the selected New Light clip with ChordMini. Let me review them in Analysis before adding a chord track.',
 'beats': 'Detect the beats in the selected audio and align it to this 120 BPM project with pitch-preserving Warp. Keep the chord track aligned.',
 'transcribe': 'Transcribe the selected Tea for Two piano stem to MIDI with TransKun. Let me review it before adding a MIDI track.',
}
JOBS = [
 ('yue', 'generate', 'cloud-inference/jobs/c81c397a6acb4bdcbe130c1f4921a19c', 20, 'New ideas', 'import'),
 ('ace', 'generate', 'cloud-inference/jobs/5858e7af3a0d478c86a92e7d7b070327', 15, 'New ideas', 'import'),
 ('separate', 'separate', 'analysis/cache/jobs/8f9fa8a53f1b4b79a12243e93ee5be55', 12, 'New ideas', 'import'),
 ('chords', 'chords', 'analysis/cache/jobs/322c0be7bf824c14bf4dace532be36f7', 8, 'New Light', 'manual'),
 ('beats', 'beats', 'analysis/cache/jobs/1370e32087f24143bd45a009a6e610ed', 6, 'New Light', 'warp'),
 ('transcribe', 'transcribe', 'analysis/cache/jobs/c00214d0883642c0b8fdbe484a1f32fa', 10, 'Tea for Two', 'import'),
]

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def verified_copy(source, target, expected=None):
    digest = sha(source)
    if expected and digest != expected:
        raise ValueError(f'Historical artifact hash mismatch: {source.name}')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or sha(target) != digest:
        shutil.copyfile(source, target)
    if sha(target) != digest:
        raise ValueError(f'Copy verification failed: {target.name}')
    return digest

def build(root: Path, reset=False):
    root.mkdir(parents=True, exist_ok=True)
    inputs = {
      'New ideas': OLD/'rehearsal/D1-ACE-4e9201887e84/D1-ACE.emproj',
      'New Light': OLD/'rehearsal/D2-Chords-cd1141a8302f/D2-NewLight-Chords.emproj',
      'Tea for Two': OLD/'rehearsal/D3-Piano-570d980002b6/D3-TeaForTwo-MIDI.emproj',
    }
    projects=[]
    evidence=[]
    for name, source in inputs.items():
        d=json.loads(source.read_text(encoding='utf-8'))
        d['project_id']=uuid.uuid5(uuid.NAMESPACE_URL, 'emusician-showcase-v1/'+name).hex
        d['revision']=0
        for key in ('generations','analyses','chord_regions','master_plugins','master_automation'):
            d[key]=[]
        d['looping']=False
        d['loop_start']=0.0
        d['loop_end']=32.0 if name=='New ideas' else 24.0 if name=='New Light' else 16.0
        if name=='New ideas':
            d['tracks']=[];d['assets']=[];d['bpm']=90.0
        else:
            d['tracks']=[t for t in d['tracks'] if t['kind']=='audio'][:1]
            d['tracks'][0]['colour']='#A9BCCF' if name=='New Light' else '#ADC6BC'
            wanted={c['asset_id'] for t in d['tracks'] for c in t['clips']}
            d['assets']=[a for a in d['assets'] if a['id'] in wanted]
            for a in d['assets']:
                src=source.parent/a['source']
                generation=uuid.uuid5(uuid.NAMESPACE_URL, 'emusician-showcase-v1/assets/'+name).hex
                relative=f'{name}.assets/{generation}/{a["id"]}.wav'
                target=root/'projects'/relative
                digest=verified_copy(src,target)
                a['source']=relative
                evidence.append({'role':'source','path':str(target.relative_to(root)).replace('\\','/'),'sha256':digest})
        path=root/'projects'/(name+'.emproj')
        template=root/'templates'/(name+'.json')
        write(template,d)
        if reset or not path.exists():
            write(path,d)
        projects.append({'id':d['project_id'],'title':name,'path':str(path.relative_to(root)).replace('\\','/'),
                         'template':str(template.relative_to(root)).replace('\\','/'),'bpm':d['bpm']})
    ids={p['title']:p['id'] for p in projects}
    scenarios=[]
    for key, kind, rel, seconds, project, application in JOBS:
        directory=DATA/rel
        src=directory/'result.json'
        result=json.loads(src.read_text(encoding='utf-8'))
        target=root/'results'/key
        result_digest=verified_copy(src,target/'result.json')
        files={}
        for item in result.get('artifacts',[]):
            name=item.get('path') or item['id']
            if Path(name).name!=name: raise ValueError('Unsafe artifact path')
            files[name]=item.get('sha256')
        if result.get('audio'):
            files[result['audio']['path']]=result['audio']['sha256']
        for stem in result.get('stems',[]): files[stem['path']]=stem['sha256']
        for name, digest in files.items():
            if Path(name).name!=name: raise ValueError('Unsafe media path')
            verified_copy(directory/name,target/name,digest)
        item={'id':key,'project_id':ids[project],'kind':kind,
              'model_id':result['model'].get('id',result['model'].get('model_id')),
              'prompts':[PROMPTS[key]],'wait_seconds':seconds,
              'result_path':f'results/{key}/result.json','result_sha256':result_digest,
              'parameters':copy.deepcopy(result['parameters']),'application':application}
        if kind!='generate':
            s=result['source']
            item['source']={'sha256':s['source_sha256'],'offset_seconds':s.get('source_offset_seconds',0),
                'duration_seconds':s['duration_seconds'],'sample_rate':s.get('source_sample_rate',s['sample_rate']),
                'warp_speed_ratio':s.get('warp_speed_ratio',1)}
        scenarios.append(item)
        evidence.append({'role':'historical-model-result','scenario':key,'original_job':src.parent.name,
                         'sha256':result_digest,'files':files,'new_inference':False})
    manifest={'schema_version':1,'projects':projects,'scenarios':scenarios}
    write(root/'manifest.json',manifest)
    write(root/'provenance.json',{'schema_version':1,'new_inference':False,
        'waiting_is_configured_pacing_not_measured_latency':True,
        'limitations':['YuE2 historical result reached token budget.','Chord labels are estimates, not verified ground truth.',
                       'No new model-language or cloud performance test is claimed.'], 'assets':evidence})
    prompt_dir=root.parent/'scripts'
    prompt_dir.mkdir(exist_ok=True)
    (prompt_dir/'agent-prompts.txt').write_text('\n\n'.join(key.upper()+'\n'+PROMPTS[key] for key in PROMPTS)+'\n',encoding='utf-8')
    print(json.dumps({'root':str(root),'projects':len(projects),'scenarios':len(scenarios),
                      'verified_media':sum(len(e.get('files',{})) for e in evidence),'manifest_sha256':sha(root/'manifest.json')}))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=DEFAULT)
    p.add_argument('--reset-projects',action='store_true',help='Explicitly restore ONLY this package\'s three working projects to templates.')
    a=p.parse_args();build(a.out.resolve(),a.reset_projects)
