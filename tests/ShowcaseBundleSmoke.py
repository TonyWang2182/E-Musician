"""Verify the real project loader and all bundled historical artifact bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_client import Client

def digest(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def run(exe, root, report):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['projects'])==3 and len(manifest['scenarios'])==6
    assertions=[]
    with Client(exe, offline_test=True) as client:
        for i,p in enumerate(manifest['projects']):
            project=root/p['path']
            before=digest(project)
            client.request({'command':'open_project','args':{'path':str(project)}})
            state=client.state()
            assert state['project_id']==p['id'],state
            assert len(state['tracks'])==(0 if i==0 else 1)
            assert abs(state['bpm']-p['bpm'])<1e-6
            assert not state.get('recording')
            assert digest(project)==before
            assertions.append({'project':p['title'],'id':p['id'],'tracks':len(state['tracks']),'opened':True,'unchanged':True})
    for s in manifest['scenarios']:
        path=root/s['result_path']
        assert digest(path)==s['result_sha256']
        d=json.loads(path.read_text(encoding='utf-8'))
        for a in d.get('artifacts',[]):
            f=path.parent/(a.get('path') or a['id'])
            assert f.is_file() and digest(f)==a['sha256']
        if 'source' in s: assert s['source']['sha256']==d['source']['source_sha256']
        assertions.append({'scenario':s['id'],'result_hash_matches':True,'artifact_hashes_match':True})
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({'status':'passed','checks':assertions,'inference':False,'listening_verified':False},indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','projects':3,'scenarios':6,'report':str(report)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();run(a.exe,a.root,a.report)
