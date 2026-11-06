"""Load the real pinned generator/decoder on CPU; never execute generation."""
import os
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['OMP_NUM_THREADS']='2'
os.environ['OPENBLAS_NUM_THREADS']='2'
import gc
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from stage import ROOT,BASE,META,SOURCE,SOURCE_REV,MODELS,digest,atomic_json,space

def main():
    began=time.monotonic()
    lock=json.loads((META/'model-lock.json').read_text())
    for item in lock['files']:
        path=Path(item['path'])
        if path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:
            raise RuntimeError('Model changed after staging: '+str(path))
    import torch
    from yue2 import YuE2Pipeline
    from yue2.modeling_vae import YuE2VAE
    torch.set_num_threads(2); torch.set_num_interop_threads(1)
    assert torch.__version__=='2.10.0+cu128' and torch.version.cuda=='12.8'
    assert not torch.cuda.is_initialized()
    models={k:ROOT/'models/yue2'/repo.split('/')[-1]/rev for k,(repo,rev) in MODELS.items()}
    report={'status':'checking','python':sys.version,'platform':platform.platform(),'torch':torch.__version__,
            'cuda_runtime':torch.version.cuda,'device':'cpu','cuda_visible_devices':'',
            'inference_executed':False,'source_revision':SOURCE_REV,'files_verified':True}
    pipe=None
    try:
        start=time.monotonic()
        pipe=YuE2Pipeline.from_pretrained(str(models['mot']),vae=str(models['vae']),
             device='cpu',backend='torch-eager',local_files_only=True,progress=False)
        model=pipe._load_model()
        assert all(p.device.type=='cpu' for p in model.parameters())
        report['generator']={'load_seconds':time.monotonic()-start,
            'parameter_count':sum(p.numel() for p in model.parameters()),'dtype':str(next(model.parameters()).dtype)}
        del model;pipe.close();pipe=None;gc.collect()
        start=time.monotonic()
        vae=YuE2VAE.from_pretrained(str(models['vae']),decoder_only=True,device='cpu',local_files_only=True)
        assert all(p.device.type=='cpu' for p in vae.parameters())
        report['decoder']={'load_seconds':time.monotonic()-start,
            'parameter_count':sum(p.numel() for p in vae.parameters()),'dtype':str(next(vae.parameters()).dtype)}
        del vae;gc.collect()
        assert not torch.cuda.is_initialized()
        report.update(status='passed',elapsed_seconds=time.monotonic()-began,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            cuda_initialized=False,free_disk_bytes=space(),
            packages={x.metadata['Name']:x.version for x in importlib.metadata.distributions() if x.metadata.get('Name')})
        atomic_json(META/'cpu-check.json',report)
        doctor=[str(ROOT/'envs/yue2/bin/yue2'),'doctor','--model',str(models['mot']),'--vae',str(models['vae']),
                '--device','cpu','--backend','torch-eager','--offline','--verify-hashes','--output',str(META/'doctor.json')]
        subprocess.run(doctor,check=True,timeout=180)
        deployment={'id':'yue2','task':'music_generation','source_revision':SOURCE_REV,
            'model_revisions':{repo:rev for repo,rev in MODELS.values()},
            'paths':{'model':{key:str(path) for key,path in models.items()},'environment':str(ROOT/'envs/yue2'),
                     'source':str(SOURCE),'cli':str(BASE/'run.sh')},
            'checks':{'files_verified':True,'environment_verified':True,'cpu_load_verified':True,'gpu_inference_verified':False},
            'daw_connected':False,'blockers':['GPU inference has not been run; serialized GPU slot required.'],
            'licenses':{'code':'Apache-2.0','weights':'CC-BY-NC-4.0 plus upstream individual-creator/academic grant; see pinned MODEL_LICENSE'},
            'artifacts':lock['files'],'environment_lock_sha256':digest(META/'environment.lock.txt'),
            'source_lock_sha256':digest(META/'source-lock.json'),
            'runtime_policy':{'backend':'torch-eager','torch':'2.10.0+cu128','vllm_installed':False,
                              'network_during_run':False,'model_audio_backup_download_to_E':False},
            'cpu_report':str(META/'cpu-check.json')}
        atomic_json(META/'deployment.json',deployment)
        print(json.dumps({k:v for k,v in report.items() if k!='packages'}),flush=True)
    except BaseException as error:
        report.update(status='failed',error=type(error).__name__+': '+str(error),elapsed_seconds=time.monotonic()-began)
        atomic_json(META/'cpu-check.json',report)
        raise
    finally:
        if pipe is not None:pipe.close()

if __name__=='__main__':main()
