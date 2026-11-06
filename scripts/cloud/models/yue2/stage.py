"""Cloud-only, pinned YuE2 files. Never transfers model data to the desktop."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

ROOT = Path('/root/autodl-tmp/emusician')
BASE = ROOT/'workspace/models/yue2'
META = ROOT/'manifests/model-library/yue2'
SOURCE_REV = '1116bea76032bee5668e5f097294d082fa0b84f0'
SOURCE = BASE/('YuE-'+SOURCE_REV)
MODELS = {
    'mot': ('m-a-p/YuE2-3B','8f24312f187763b9854adeec87e437e2b03bbff1'),
    'vae': ('m-a-p/YuE2-Vae','152733a19ad43aa67e367f9b5503ef8075bb5126'),
}
MINIMUM_FREE = 50_000_000_000

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def space(extra=0):
    free = shutil.disk_usage(ROOT).free
    if free < MINIMUM_FREE+extra:
        raise RuntimeError(f'Cloud disk reserve: {free} free, need {MINIMUM_FREE+extra} bytes')
    return free

def selected(name):
    # Runtime/config/license only; no example songs, legacy decoder or wheel duplicates.
    p=Path(name)
    return (len(p.parts)==1 and (p.suffix in {'.safetensors','.json','.py','.tiktoken'}
            or p.name in {'LICENSE','README.md','THIRD_PARTY_NOTICES.md'})) or name.startswith('licenses/')

def url_json(url):
    with urllib.request.urlopen(url,timeout=90) as response:
        return json.load(response)

def download_file(repo, rev, item, target):
    name=item['rfilename']; path=target/name
    if not path.resolve().is_relative_to(target.resolve()) or path.is_symlink():
        raise RuntimeError('Unsafe model target')
    size=int(item['size']); upstream=(item.get('lfs') or {}).get('sha256')
    blob=item.get('blobId')
    def verified(p):
        if not p.is_file() or p.stat().st_size!=size: return False
        if upstream: return digest(p)==upstream
        git=hashlib.sha1(f'blob {size}\0'.encode())
        with p.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):git.update(chunk)
        return git.hexdigest()==blob
    if not verified(path):
        path.parent.mkdir(parents=True,exist_ok=True)
        part=path.with_name(path.name+'.partial')
        for attempt in range(3):
            try:
                offset=part.stat().st_size if part.exists() else 0
                space(max(0,size-offset))
                headers={'User-Agent':'E-musician-YuE2-deployment/1'}
                if offset:headers['Range']=f'bytes={offset}-'
                # Pinned official publisher URL; TLS verification is never disabled.
                url=f'https://huggingface.co/{repo}/resolve/{rev}/{name}'
                with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=120) as response:
                    append=offset>0 and response.status==206
                    written=offset if append else 0
                    with part.open('ab' if append else 'wb') as stream:
                        for chunk in iter(lambda:response.read(4*1024*1024),b''):
                            written+=len(chunk)
                            if written>size:raise RuntimeError('Download exceeds pinned size')
                            space()
                            stream.write(chunk)
                if not verified(part):raise RuntimeError('Pinned model hash/size mismatch')
                part.replace(path);break
            except Exception as error:
                print(json.dumps({'file':name,'attempt':attempt+1,'error':str(error)}),flush=True)
                if attempt==2:raise
                time.sleep(2)
    print(json.dumps({'verified':name,'bytes':size}),flush=True)
    return {'path':str(path),'bytes':size,'sha256':digest(path),'repository':repo,
            'revision':rev,'upstream_sha256':upstream,'upstream_git_blob':blob}

def source():
    BASE.mkdir(parents=True,exist_ok=True); META.mkdir(parents=True,exist_ok=True); space()
    if not SOURCE.exists():
        subprocess.run(['git','init',str(SOURCE)],check=True)
        subprocess.run(['git','-C',str(SOURCE),'remote','add','origin','https://github.com/multimodal-art-projection/YuE.git'],check=True)
    actual=subprocess.run(['git','-C',str(SOURCE),'rev-parse','HEAD'],capture_output=True,text=True)
    if actual.returncode or actual.stdout.strip()!=SOURCE_REV:
        subprocess.run(['git','-C',str(SOURCE),'fetch','--depth','1','origin',SOURCE_REV],check=True,timeout=180)
        subprocess.run(['git','-C',str(SOURCE),'checkout','--detach',SOURCE_REV],check=True)
    if subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()!=SOURCE_REV:
        raise RuntimeError('Unexpected source commit')
    paths=subprocess.check_output(['git','-C',str(SOURCE),'ls-files','-z']).decode().split('\0')
    files=[{'path':name,'bytes':(SOURCE/name).stat().st_size,'sha256':digest(SOURCE/name)} for name in paths if name and (SOURCE/name).is_file()]
    atomic_json(META/'source-lock.json',{'repository':'https://github.com/multimodal-art-projection/YuE','revision':SOURCE_REV,'files':files})
    print(json.dumps({'source_revision':SOURCE_REV,'files':len(files)}),flush=True)

def weights():
    artifacts=[]
    for role,(repo,rev) in MODELS.items():
        data=url_json(f'https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true')
        if data['sha']!=rev:raise RuntimeError('HF returned another revision')
        files=[x for x in data['siblings'] if selected(x['rfilename'])]
        target=ROOT/'models/yue2'/repo.split('/')[-1]/rev
        target.mkdir(parents=True,exist_ok=True)
        atomic_json(META/(role+'-upstream.json'),data)
        for item in files:artifacts.append(download_file(repo,rev,item,target))
    atomic_json(META/'model-lock.json',{'schema_version':1,'revisions':{k:v[1] for k,v in MODELS.items()},'files':artifacts,'total_bytes':sum(x['bytes'] for x in artifacts)})
    print(json.dumps({'status':'files_verified','count':len(artifacts),'bytes':sum(x['bytes'] for x in artifacts),'free_bytes':space()}),flush=True)

def requirements():
    import tomllib
    upstream=tomllib.loads((SOURCE/'pyproject.toml').read_text())
    lock_path=ROOT/'workspace/third_party/ACE-Step-1.5-ca1e85fe9430179831e6bc6be790c332190a3866/uv.lock'
    lock=tomllib.loads(lock_path.read_text())
    package=next(p for p in lock['package'] if p['name']=='torch' and p['version']=='2.10.0+cu128')
    wheel=next(w for w in package['wheels'] if 'cp312-cp312-manylinux_2_28_x86_64' in w['url'])
    lines=[f'torch @ {wheel["url"]}#{wheel["hash"].replace(":","=",1)}']
    reused=[]
    for path in sorted((ROOT/'cache/wheels').glob('nvidia_*.whl')):
        found=next((w for p in lock['package'] for w in p.get('wheels',[]) if Path(w['url']).name==path.name),None)
        actual=digest(path)
        if not found or found['hash']!='sha256:'+actual:raise RuntimeError('Shared CUDA wheel does not match pinned ACE lock: '+path.name)
        name=path.name.split('-')[0].replace('_','-')
        lines.append(f'{name} @ {path.as_uri()}#sha256={actual}')
        reused.append({'path':str(path),'sha256':actual,'bytes':path.stat().st_size})
    lines.extend(d for d in upstream['project']['dependencies'] if not d.startswith('torch'))
    lines.extend(['setuptools==80.9.0','wheel==0.45.1','pytest==9.0.3'])
    (BASE/'requirements.in').write_text('\n'.join(lines)+'\n')
    atomic_json(META/'reused-wheel-lock.json',{'source_lock':str(lock_path),'source_lock_sha256':digest(lock_path),'read_only_reused_files':reused})
    print('Generated isolated YuE2 inputs; reused wheels verified, ACE unchanged.',flush=True)

if __name__=='__main__':
    action=argparse.ArgumentParser();action.add_argument('action',choices=['source','weights','requirements']);args=action.parse_args()
    globals()[args.action]()
