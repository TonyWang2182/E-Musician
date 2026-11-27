"""Fetch only pinned MuScriptor medium weights and matching config after authorization."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import time

ROOT=Path('/root/autodl-tmp/emusician')
BASE=ROOT/'workspace/models/muscriptor'
REPO='MuScriptor/muscriptor-medium'
REV='f32236969308476e01fd3aae67357de5feb05a2d'
SIZE=1228144472
SHA='ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8');temp.replace(path)

def main():
    if os.name!='posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only model download')
    os.environ.update(HF_HOME=str(BASE/'hf'),HF_ENDPOINT='https://huggingface.co',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_PROGRESS_BARS='1',HF_HUB_DOWNLOAD_TIMEOUT='90',HF_HUB_ETAG_TIMEOUT='30')
    started=time.monotonic()
    report={'model':REPO,'revision':REV,'status':'running','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'script_sha256':sha(Path(__file__)),'files':[],'credentials_logged':False,'cpu_load_verified':False,'gpu_inference_verified':False}
    receipt=ROOT/'manifests/model-library/muscriptor/authorized-download.json'
    token=None
    try:
        from huggingface_hub import HfApi,hf_hub_download
        from huggingface_hub.utils import logging
        logging.set_verbosity_error()
        report['phase']='authenticated_metadata'
        token=(BASE/'hf/token').read_text(encoding='utf8').strip()
        info=HfApi().model_info(REPO,revision=REV,files_metadata=True,token=token)
        if info.sha!=REV:
            raise ValueError('Model revision mismatch')
        pinned={entry.rfilename:entry for entry in info.siblings}
        config=pinned['config.json'];weight=pinned['model.safetensors']
        if weight.size!=SIZE or weight.lfs.sha256!=SHA or config.size>65536:
            raise ValueError('Model metadata mismatch')
        if shutil.disk_usage(ROOT).free-SIZE<50_000_000_000:
            raise RuntimeError('Cloud disk reserve insufficient')
        directory=ROOT/'models/muscriptor'
        if directory.is_symlink():
            raise ValueError('Model directory cannot be a symlink')
        directory.mkdir(parents=True,exist_ok=True)
        for name in ('config.json','model.safetensors'):
            target=directory/name;item=pinned[name]
            report['phase']=name
            if target.is_symlink():
                raise ValueError('Model file cannot be a symlink')
            expected=SHA if name.endswith('.safetensors') else None
            if target.exists():
                if target.stat().st_size!=item.size or (expected is not None and sha(target)!=expected):
                    raise ValueError('Existing model artifact differs')
            else:
                print(json.dumps({'phase':'download','filename':name,'expected_bytes':item.size}),flush=True)
                downloaded=hf_hub_download(REPO,name,revision=REV,local_dir=str(directory),token=token)
                if Path(downloaded).resolve()!=target.resolve():
                    raise ValueError('Unexpected destination')
            if target.stat().st_size!=item.size:
                raise ValueError('Downloaded size mismatch')
            digest=sha(target)
            if expected and digest!=expected:
                raise ValueError('Weight SHA mismatch')
            if name=='config.json':
                data=target.read_bytes()
                blob=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest()
                if blob!=config.blob_id:
                    raise ValueError('Config git blob mismatch')
                values=json.loads(data)
                if any(values.get(key)!=value for key,value in {'dim':1024,'num_heads':16,'num_layers':24,'card':1395}.items()):
                    raise ValueError('Unexpected medium architecture')
                report['config']=values
            report['files'].append({'path':str(target),'bytes':target.stat().st_size,'sha256':digest,'git_blob':item.blob_id})
            save(receipt,report)
            print(json.dumps({'phase':'verified','filename':name,'bytes':item.size,'sha256':digest}),flush=True)
        report['status']='passed'
    except Exception as error:
        response=getattr(error,'response',None)
        report.update(status='failed',error_type=type(error).__name__,http_status=getattr(response,'status_code',None))
    finally:
        token=None
        report['elapsed_seconds']=time.monotonic()-started
        try:
            report['free_disk_bytes']=shutil.disk_usage(ROOT).free
        except Exception as error:
            report['disk_diagnostic_error_type']=type(error).__name__
        try:
            save(receipt,report)
        except Exception as error:
            report.update(status='failed',receipt_error_type=type(error).__name__)
    print(json.dumps(report),flush=True)
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':
    raise SystemExit(main())
