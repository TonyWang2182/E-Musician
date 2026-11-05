"""Real local Beat This process tests; no musical accuracy or device claim."""
from pathlib import Path
import argparse
import json
import math
import random
import array
from statistics import median
import subprocess
import sys
import time
import uuid
import wave
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.audio_analysis.common import atomic_json,read_json,sha256_file

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path('E:/MusicAgent&DAW/analysis'));parser.add_argument('--case',choices=('all','grid'),default='all');args=parser.parse_args()
    root=args.root.resolve();provider=read_json(root/'registry.json')['providers']['beats']
    report={'passed':False,'scope':'Real Beat This checkpoint, cached public CC-BY music and silence. No ground truth or audio device; not accuracy/ASIO validation.','observations':[]}
    directory=root/'cache/probe-fixtures'/('beats-'+uuid.uuid4().hex[:12]);directory.mkdir(parents=True)
    silence=directory/'silence.wav'
    with wave.open(str(silence),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(22050);out.writeframes(bytes(22050*2*2))
    grid=directory/'synthetic-120bpm-4-4.wav';samples=array.array('h');rng=random.Random(120)
    for i in range(16*22050):
        at=i/22050-.25
        if at<0:value=0.
        else:
            beat=int(at/.5);phase=at% .5;half=at% .25
            kick=(.55 if beat%4==0 else .35)*math.sin(2*math.pi*65*phase)*math.exp(-phase*35)
            snare=.22*rng.uniform(-1,1)*math.exp(-phase*40) if beat%4 in (1,3) else 0
            hat=.1*rng.uniform(-1,1)*math.exp(-half*130)
            bass=.12*math.sin(2*math.pi*(130.8128 if beat%8<4 else 110)*phase)*math.exp(-phase*4)
            value=kick+snare+hat+bass
        samples.append(round(max(-1,min(1,value))*32767))
    with wave.open(str(grid),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(22050);out.writeframes(samples.tobytes())
    cases=[('grid',grid,16.,False)] if args.case=='grid' else [('public-vibeace',root/'cache/public-fixtures/vibeace-excerpt.wav',8.,False),('grid',grid,16.,False),('silence',silence,2.,False),('too-short',silence,.01,False),('cancel',silence,2.,True)]
    try:
        for name,path,duration,cancel in cases:
            jid='beat-probe-'+uuid.uuid4().hex[:12];job=root/'cache/jobs'/jid;job.mkdir(parents=True)
            atomic_json(job/'request.json',{'schema_version':1,'job_id':jid,'kind':'beats','preset':'beat_this','analysis_root':str(root),'source_path':str(path),'source_offset_seconds':0,'duration_seconds':duration,'source':{'project_id':'beat-probe','clip_id':'source','timeline_start':0,'bpm':120},'parameters':{'meter':'auto'}})
            if cancel:(job/'cancel').touch()
            started=time.perf_counter();run=subprocess.run([provider['python_executable'],str(Path(__file__).with_name('run.py')),'--request',str(job/'request.json')],timeout=240)
            progress=read_json(job/'progress.json')
            if cancel:
                assert run.returncode==3 and progress['status']=='cancelled' and not (job/'result.json').exists()
                observation={'name':name,'job_id':jid,'status':'cancelled'}
            else:
                if run.returncode:raise AssertionError((job/'worker.log').read_text(encoding='utf-8'))
                result=read_json(job/'result.json');events=result['beat_events'];tempo=result['tempo']
                assert progress['status']=='ready' and result['source']['source_sha256']==sha256_file(path)
                assert len(result['waveform_peaks'])==128 and all(math.isfinite(v) and v>=0 for v in result['waveform_peaks'])
                assert all(0<=event['time_seconds']<duration and type(event['is_downbeat']) is bool for event in events)
                assert all(a['time_seconds']<b['time_seconds'] for a,b in zip(events,events[1:]))
                if name in ('public-vibeace','grid'):assert len(events)>3 and tempo['bpm'] is not None
                else:assert not events and tempo['bpm'] is None and tempo['first_downbeat_seconds'] is None
                observation={'name':name,'job_id':jid,'model':result['model'],'tempo':tempo,'events':len(events),'performance':result['performance'],'result_sha256':sha256_file(job/'result.json')}
                if name=='grid':
                    error=median(min(abs(e['time_seconds']-(.25+.5*i)) for i in range(32)) for e in events)
                    observation.update(synthetic_reference_bpm=120,median_nearest_reference_beat_error_seconds=error)
                    assert any(abs(v-120)<6 for v in tempo['tempo_candidates']) and error<.08
            observation['wall_seconds']=time.perf_counter()-started;report['observations'].append(observation);print(json.dumps(observation,indent=2),flush=True)
        report['passed']=True
    finally:
        output=root/'manifests'/('beat-probe-'+uuid.uuid4().hex[:12]+'.json');atomic_json(output,report);print(output,flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
