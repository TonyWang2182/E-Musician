"""One explicitly authorized low-VRAM coexistence probe; audio stays in cloud."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from stage import ROOT,BASE,META,MODELS,atomic_json,digest

def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro',uri=True,timeout=2) as db:
        active=db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    output=subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=5)
    return {'active_ace_jobs':active,'free_gpu_mib':int(output.strip().splitlines()[0]),
            'ace_pid':(ROOT/'state/gateway.pid').read_text().strip()}

def worker(output):
    import numpy as np
    import soundfile as sf
    import torch
    from yue2 import YuE2Pipeline
    from yue2.protocol import GenerationConfig
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    models={k:ROOT/'models/yue2'/repo.split('/')[-1]/rev for k,(repo,rev) in MODELS.items()}
    request={'id':'short-low-vram-probe','style':'Instrumental solo nylon-string guitar, gentle fingerpicked arpeggios, warm intimate room, relaxed tempo, no vocals or singing.',
             'lyrics':'','cot':'off','seed':160611}
    # A short codec path test, not a complete song or symbolic-plan acceptance.
    config=GenerationConfig.from_dict({'semantic':{'min_tokens':96,'max_tokens':192}})
    atomic_json(output/'probe-request.json',{'request':request,'generation_config':config.to_dict(),
        'runtime':{'backend':'torch-eager','memory_budget_gib':8,'low_vram':True,'batch_size':1}})
    began=time.monotonic();torch.cuda.reset_peak_memory_stats()
    with YuE2Pipeline.from_pretrained(str(models['mot']),vae=str(models['vae']),local_files_only=True,
            device='cuda',backend='torch-eager',low_vram=True,memory_budget_gib=8,generation_config=config) as pipe:
        result=pipe(**request)
        result.save_artifacts(output)
        # This is the actual generated model audio, encoded as PCM16 on cloud.
        wav=output/'audio.wav'
        sf.write(wav,result.audio,result.sample_rate,subtype='PCM_16')
        audio,rate=sf.read(wav,dtype='float32',always_2d=True)
        assert rate==48000 and audio.shape[1]==2 and len(audio)>0
        assert np.isfinite(audio).all() and float(np.max(np.abs(audio)))>1e-6
        assert float(np.sqrt(np.mean(audio.astype(np.float64)**2)))>1e-7
        torch.cuda.synchronize()
        report={'status':'passed','actual_generated_audio':True,'duration_seconds':len(audio)/rate,
            'sample_rate':rate,'channels':audio.shape[1],'frames':len(audio),
            'rms':float(np.sqrt(np.mean(audio.astype(np.float64)**2))),
            'peak':float(np.max(np.abs(audio))),'truncated':result.truncated,
            'torch':torch.__version__,'cuda_runtime':torch.version.cuda,
            'gpu':torch.cuda.get_device_name(),'compute_capability':list(torch.cuda.get_device_capability()),
            'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
            'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
            'worker_elapsed_seconds':time.monotonic()-began,'timing':result.timing,
            'audio':{'path':str(wav),'bytes':wav.stat().st_size,'sha256':digest(wav)},
            'scope':'one short token-capped low_vram 8GiB coexistence probe; cot off; no listening/default24GiB/long-song claim'}
        atomic_json(output/'probe-result.json',report)
        print(json.dumps(report),flush=True)

def stop_owned(process):
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)

def finish_telemetry(report, began, minimum, observe):
    """Keep the inference outcome even if post-run health telemetry is unavailable."""
    report.update(wall_seconds=time.monotonic()-began,minimum_free_gpu_mib=minimum)
    try:
        report['after']=observe()
        report['after_healthcheck_verified']=True
    except Exception as error:
        report['after_healthcheck_verified']=False
        report['after_probe_error']=type(error).__name__+': '+str(error)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--approved-slot',action='store_true')
    parser.add_argument('--worker',type=Path);args=parser.parse_args()
    if args.worker:return worker(args.worker)
    if not args.approved_slot:raise RuntimeError('A root-authorized serialized GPU slot is required; nothing started.')
    import fcntl
    lock=(ROOT/'state/model-library-gpu-probe.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    before=state()
    if before['active_ace_jobs'] or before['free_gpu_mib']<12288:
        raise RuntimeError('Admission denied: ACE is active or fewer than12GiB GPU memory is free.')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    output=ROOT/'results/model-library/yue2'/('probe-'+stamp);output.mkdir(parents=True,exist_ok=False)
    logpath=ROOT/'logs/model-library/yue2'/('gpu-'+stamp+'.log')
    report={'id':'yue2','status':'running','before':before,'started_utc':stamp,
        'output':str(output),'log':str(logpath),'deadline_seconds':180,
        'guard_script_sha256':digest(Path(__file__).resolve()),
        'preset':'official low_vram, budget8GiB, torch-eager, one short cot-off instrumental request',
        'daw_connected':False,'quality_evaluation':False,'default_24gib_verified':False}
    reportpath=META/('gpu-probe-'+stamp+'.json');atomic_json(reportpath,report)
    env=os.environ.copy();env.pop('CUDA_VISIBLE_DEVICES',None)
    env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',YUE2_COMPILE='0')
    began=time.monotonic();minimum=before['free_gpu_mib'];process=None
    try:
        with logpath.open('wb') as log:
            process=subprocess.Popen([str(ROOT/'envs/yue2/bin/python'),str(Path(__file__).resolve()),'--worker',str(output)],
                env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while process.poll() is None:
                current=state();minimum=min(minimum,current['free_gpu_mib'])
                if current['active_ace_jobs'] or current['free_gpu_mib']<1024 or time.monotonic()-began>=180:
                    report.update(status='interrupted',reason='ACE activity, GPU reserve, or180second deadline',observed=current)
                    stop_owned(process);break
                time.sleep(.5)
        report['exit_code']=process.returncode
        artifact=output/'probe-result.json'
        if report['status']=='running':
            report['status']='passed' if process.returncode==0 and artifact.is_file() else 'failed'
        if report['status']=='passed':report['result']=json.loads(artifact.read_text())
    except BaseException as error:
        if process is not None:stop_owned(process)
        report.update(status='failed',error=type(error).__name__+': '+str(error))
    finally:
        finish_telemetry(report,began,minimum,state)
        atomic_json(reportpath,report)
        deployment=json.loads((META/'deployment.json').read_text())
        deployment['gpu_probe']=str(reportpath)
        deployment['checks']['gpu_inference_verified']=report['status']=='passed'
        deployment['gpu_verified_scope']=report['preset'] if report['status']=='passed' else None
        deployment['blockers']=['Default24GiB/full-song/symbolic-plan GPU path has not been validated.'] if report['status']=='passed' else ['Low-VRAM GPU probe did not produce a validated audio result; inspect gpu_probe.']
        atomic_json(META/'deployment.json',deployment)
        print(json.dumps(report),flush=True)
    if report['status']!='passed':
        print(logpath.read_text(errors='replace')[-8000:],flush=True);raise SystemExit(1)

if __name__=='__main__':main()
