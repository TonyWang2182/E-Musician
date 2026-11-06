"""One original-prompt YuE2 evaluation; all model/audio artifacts stay on cloud."""
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

ROOT=Path('/root/autodl-tmp/emusician')
HERE=Path(__file__).resolve().parent
SOURCE_REV='1116bea76032bee5668e5f097294d082fa0b84f0'
SOURCE=ROOT/'workspace/models/yue2'/('YuE-'+SOURCE_REV)
MODELS={
    'mot':ROOT/'models/yue2/YuE2-3B/8f24312f187763b9854adeec87e437e2b03bbff1',
    'vae':ROOT/'models/yue2/YuE2-Vae/152733a19ad43aa67e367f9b5503ef8075bb5126'}
SEED=170611
DEADLINE=1200


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def request_and_config():
    from yue2.protocol import GenerationConfig,preflight
    prompt=(HERE/'prompt.txt').read_text(encoding='utf-8').rstrip('\r\n')
    request={'id':'jungle-original-yue2-170611','style':prompt,'lyrics':'','cot':'full','seed':SEED}
    config=GenerationConfig.from_dict({'semantic':{'min_tokens':2700,'max_tokens':3000}})
    preflight(request,config)
    return request,config


def static_check():
    import torch
    from yue2.protocol import token_prefixes,preflight,chunk_ranges
    from yue2.tokenization_yue2 import YuE2TextTokenizer
    request,config=request_and_config()
    tokenizer=YuE2TextTokenizer(MODELS['mot']/'qwen.tiktoken')
    prefix=token_prefixes(preflight(request,config),tokenizer)
    # Worst-case full ABC length plus its closing/start tokens.
    worst_prefix=len(prefix)+config.abc.max_tokens+2
    chunks=chunk_ranges(config.semantic.max_tokens,worst_prefix)
    revision=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
    assert revision==SOURCE_REV
    assert config.abc.min_tokens==32 and config.abc.max_tokens==4096 and config.ode_steps==32
    assert worst_prefix+config.semantic.max_tokens<config.context
    assert not torch.cuda.is_initialized()
    report={'status':'passed','inference_executed':False,'cuda_initialized':False,
        'script_sha256':sha(__file__),'prompt_file_sha256':sha(HERE/'prompt.txt'),
        'effective_prompt_sha256':hashlib.sha256(request['style'].encode('utf-8')).hexdigest(),
        'prompt_characters':len(request['style']),'request':request,'generation_config':config.to_dict(),
        'request_prefix_tokens':len(prefix),'worst_planned_prefix_tokens':worst_prefix,
        'worst_case_acoustic_chunk_ranges':chunks,'source_revision':revision,
        'model_paths':{k:str(v) for k,v in MODELS.items()},'torch':torch.__version__,
        'runtime':{'backend':'torch-eager','low_vram':True,'memory_budget_gib':8,
                   'batch_size':1,'quantization':'none','vae_core_frames':512},
        'duration_control':{'kind':'semantic_token_budget','min_tokens':2700,'max_tokens':3000,
            'nominal_seconds':[108,120],'hard_seconds_argument':False,'post_crop':False,
            'description':'Nominal25Hz codec; natural decoded frames=1920*T-64. EOS/truncation recorded.'},
        'supervisor':{'deadline_seconds':DEADLINE,'admission_free_gpu_mib':12288,
                      'stop_free_gpu_mib':1024,'ace_must_be_idle':True,'retry':False}}
    write(HERE/'yue2-static.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'request','generation_config'}},ensure_ascii=False),flush=True)


def health():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro',uri=True,timeout=2) as db:
        active=db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    free=int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True,timeout=5).strip().splitlines()[0])
    return {'active_ace_jobs':active,'free_gpu_mib':free,'ace_pid':(ROOT/'state/gateway.pid').read_text().strip()}


def worker(output):
    import numpy as np
    import soundfile as sf
    import torch
    from yue2 import YuE2Pipeline
    from yue2.pipeline import SongResult
    from yue2.protocol import make_request
    from yue2.storage import identity
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    request,config=request_and_config();typed_request=make_request(**request)
    counters={};last=[0.0];started=time.monotonic()
    def progress(stage,completed,total=None):
        now=time.monotonic()
        if now-last[0]<2 and total is None:return
        last[0]=now
        value={'phase':stage,'completed':completed,'total':total,'elapsed_seconds':now-started}
        write(HERE/'yue2-progress.json',value);print(json.dumps(value),flush=True)
    def on_token(stage,token):
        counters[stage]=counters.get(stage,0)+1;progress(stage,counters[stage])
    torch.cuda.reset_peak_memory_stats()
    with YuE2Pipeline.from_pretrained(str(MODELS['mot']),vae=str(MODELS['vae']),local_files_only=True,
            device='cuda',backend='torch-eager',low_vram=True,memory_budget_gib=8,
            vae_core_frames=512,generation_config=config,progress=False) as pipe:
        effective=pipe.effective_config(typed_request)
        request_id=identity({'request':typed_request.to_dict(),'config':effective,'weights':pipe.weights})
        began=time.perf_counter()
        # Official public phase API, one plan and one synthesis; save evidence before later stages.
        plan=pipe.plan(request=typed_request,on_token=on_token)
        plan.save(output/'plan-stage')
        write(HERE/'yue2-plan-summary.json',{'truncated':plan.truncated,'timing':plan.timing,
            'abc_tokens':len(plan.abc_ids),'prefix_tokens':len(plan.prefix),
            'score_path':str(output/'plan-stage/score.abc'),'score_sha256':sha(output/'plan-stage/score.abc'),
            'warning':'Model ABC is not proof of six-section or no-singing adherence.'})
        semantic=pipe.generate_semantic(plan,on_token=on_token)
        np.save(output/'semantic-stage.npy',np.asarray(semantic.tokens,dtype=np.int32))
        nar_start=time.perf_counter()
        latents=pipe.synthesize(semantic,on_progress=lambda done,total:progress('nar',done,total))
        nar_seconds=time.perf_counter()-nar_start
        np.save(output/'latent-stage.npy',latents.astype(np.float32))
        vae_start=time.perf_counter()
        audio=pipe.decode(latents,on_progress=lambda done,total:progress('vae',done,total))
        timing={'abc':plan.timing,'semantic':semantic.timing,'nar_seconds':nar_seconds,
                'vae_seconds':time.perf_counter()-vae_start,'load':dict(pipe.load_timing),
                'e2e_seconds':time.perf_counter()-began}
        result=SongResult(audio,48000,semantic,latents,effective,pipe.weights,timing,request_id)
        result.save_artifacts(output/'native')
        wav=output/'audio.wav';result.save(wav)
        decoded,rate=sf.read(wav,dtype='float32',always_2d=True)
        assert rate==48000 and decoded.shape[1]==2 and len(decoded)>0 and np.isfinite(decoded).all()
        rms=float(np.sqrt(np.mean(decoded.astype(np.float64)**2)))
        assert rms>1e-7
        torch.cuda.synchronize()
        report={'status':'passed','actual_generated_audio':True,'duration_seconds':len(decoded)/rate,
            'sample_rate':rate,'channels':decoded.shape[1],'frames':len(decoded),'rms':rms,
            'peak':float(np.max(np.abs(decoded))),'at_rail_fraction':float(np.mean(np.abs(decoded)>=.999)),
            'truncated':result.truncated,'semantic_tokens':len(semantic.tokens),'abc_tokens':len(plan.abc_ids),
            'timing':timing,'worker_wall_seconds':time.monotonic()-started,
            'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(),
            'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
            'audio':{'path':str(wav),'bytes':wav.stat().st_size,'sha256':sha(wav),'subtype':'FLOAT'},
            'native_artifacts':str(output/'native'),'request_identity':request_id,
            'effective_prompt_sha256':hashlib.sha256(request['style'].encode('utf-8')).hexdigest(),
            'prompt_file_sha256':sha(HERE/'prompt.txt'),'output_postprocessing':'None; upstream pipeline clamps to[-1,1]; saved FLOAT WAV.',
            'quality_and_structure_adherence':'Not established by signal validation; requires listening.'}
        write(output/'yue2-result.json',report)
        print(json.dumps(report,ensure_ascii=False),flush=True)


def stop(process):
    if process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=5)


def fail_and_stop(report,error,process):
    report.update(status='failed',error=type(error).__name__+': '+str(error))
    if process is not None:
        try:stop(process)
        except Exception as cleanup_error:
            report['cleanup_error']=type(cleanup_error).__name__+': '+str(cleanup_error)


def terminal_receipt(path,report):
    try:write(path,report)
    except Exception as error:
        report['receipt_write_error']=type(error).__name__+': '+str(error)
    # Always emit the terminal receipt, even if the disk or rename failed.
    print(json.dumps(report,ensure_ascii=False),flush=True)


def run():
    import fcntl
    static=json.loads((HERE/'yue2-static.json').read_text())
    assert static['status']=='passed' and static['script_sha256']==sha(__file__)
    assert static['prompt_file_sha256']==sha(HERE/'prompt.txt')
    reportpath=HERE/'yue2-attempt.json'
    report={'status':'admitting','started_utc':time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()),
            'script_sha256':sha(__file__),'prompt_file_sha256':sha(HERE/'prompt.txt'),'deadline_seconds':DEADLINE,
            'static_request':str(HERE/'yue2-static.json'),'daw_connected':False,'attempts':1,'inference_started':False}
    # Exclusive claim before admission: never overwrite an earlier attempt.
    with reportpath.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False)
    process=None;lock=None;log=None;minimum=None;started=time.monotonic()
    try:
        lock=(ROOT/'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=health()
        report['before']=before;minimum=before['free_gpu_mib']
        if before['active_ace_jobs'] or before['free_gpu_mib']<12288:
            raise RuntimeError('Admission refused: ACE busy or GPU free memory below12GiB.')
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        output=ROOT/'results/evaluations/jungle_20261106'/('yue2-'+stamp);output.mkdir(parents=True,exist_ok=False)
        log=output/'worker.log'
        report.update(status='starting',output=str(output),log=str(log))
        write(reportpath,report)
        env=os.environ.copy();env.pop('CUDA_VISIBLE_DEVICES',None)
        env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',YUE2_COMPILE='0')
        with log.open('wb') as stream:
            process=subprocess.Popen([str(ROOT/'envs/yue2/bin/python'),str(Path(__file__).resolve()),'--worker',str(output)],
                stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            report.update(status='running',inference_started=True);write(reportpath,report)
            while process.poll() is None:
                current=health();minimum=min(minimum,current['free_gpu_mib'])
                if current['active_ace_jobs'] or current['free_gpu_mib']<1024 or time.monotonic()-started>=DEADLINE:
                    report.update(status='interrupted',observed=current,reason='ACE activity, GPU reserve, or deadline')
                    stop(process);break
                time.sleep(.5)
        report['exit_code']=process.returncode
        if report['status']=='running':
            report['status']='passed' if process.returncode==0 and (output/'yue2-result.json').is_file() else 'failed'
        if report['status']=='passed':report['result']=json.loads((output/'yue2-result.json').read_text())
    except BaseException as error:fail_and_stop(report,error,process)
    finally:
        report.update(wall_seconds=time.monotonic()-started,minimum_free_gpu_mib=minimum)
        try:report.update(after=health(),after_healthcheck_verified=True)
        except Exception as error:report.update(after_healthcheck_verified=False,after_probe_error=str(error))
        terminal_receipt(reportpath,report)
        if lock is not None:lock.close()
    if report['status']!='passed':
        if log is not None and log.exists():print(log.read_text(errors='replace')[-10000:],flush=True)
        raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser();modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--static-check',action='store_true');modes.add_argument('--approved-gpu-slot',action='store_true')
    modes.add_argument('--worker',type=Path);args=parser.parse_args()
    if args.static_check:
        os.environ['CUDA_VISIBLE_DEVICES']='';os.environ['HF_HUB_OFFLINE']='1';static_check()
    elif args.worker:worker(args.worker)
    else:run()


if __name__=='__main__':main()
