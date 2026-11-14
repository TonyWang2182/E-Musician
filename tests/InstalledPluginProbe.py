"""One installed module in a disposable offline DAW.

Run from the compatibility supervisor with a bounded per-module deadline. This
does not test licences, preset libraries or hardware I/O. --open-editor exercises
the production native editor opening path, without clicking its controls.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agent_client import Client
from PluginHostSmoke import exact_cache_entries, page, tone

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--skip-scan', action='store_true')
    parser.add_argument('--open-editor', action='store_true')
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    report = {'module':str(args.module), 'status':'running', 'stage':'start', 'checks':[],
              'native_editor_tested':False, 'hardware_audio_tested':False, 'default_program_only':True}
    def save():
        report['elapsed_seconds'] = time.monotonic() - start
        (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def stage(name): report.update(stage=name); save()
    client = None
    try:
        client = Client(args.exe, timeout=70, offline_test=True)
        stage('scan')
        if not args.skip_scan:
            client.request({'command':'scan_plugins','args':{'include_default_paths':False,'paths':[], 'modules':[str(args.module)]}})
        entries = exact_cache_entries(args.module)
        report['descriptors'] = entries
        good = [p for p in entries if p['available']]
        if not good: raise RuntimeError('No available exact module descriptor: '+str(entries))
        descriptor = good[0]
        report['untested_descriptors'] = good[1:]
        stage('create_track')
        client.request({'command':'create_track','args':{'kind':'instrument' if descriptor['is_instrument'] else 'audio','name':'Compatibility probe'}})
        track = client.state()['tracks'][-1]['id']
        if descriptor['is_instrument']:
            client.request({'command':'create_midi_clip','args':{'track_id':track,'start_beats':0,'length_beats':4}})
            clip = client.state()['tracks'][-1]['clips'][0]['id']
            client.request({'command':'write_notes','args':{'clip_id':clip,'notes':[
                {'id':'probe-low','pitch':36,'start_beats':0,'length_beats':0.5,'velocity':50,'channel':1},
                {'id':'probe-high','pitch':60,'start_beats':2,'length_beats':0.5,'velocity':50,'channel':1}]}})
        else:
            sample=args.out/'quiet.wav'; tone(sample)
            client.request({'command':'import_audio','args':{'paths':[str(sample)]}})
            track=client.state()['tracks'][-1]['id']
        stage('instantiate')
        client.request({'command':'add_plugin','args':{'track_id':track,'catalog_id':descriptor['id']}})
        slot = next(t for t in client.state()['tracks'] if t['id']==track)['plugins'][-1]
        assert not slot.get('missing'), slot
        report['plugin']={'name':descriptor['name'],'id':slot['id'],'version':descriptor['version']}
        report['checks'].append('instantiate exact catalog identity')
        stage('parameter_read')
        report['parameter_count']=len(page(client,'get_plugin_parameters','parameters',{'plugin_id':slot['id']}))
        report['checks'].append('read parameters')
        if args.open_editor:
            stage('open_native_editor')
            client.request({'command':'open_plugin','args':{'track_id':track,'plugin_id':slot['id']}})
            stage('native_editor_settle')
            until=time.monotonic()+3.0
            while time.monotonic()<until:
                client.state()
                time.sleep(.1)
            report['native_editor_tested']=True
            report['checks'].append('production open_plugin and three-second event loop (no editor gestures)')
        stage('save_state')
        project=args.out/'project.emproj'
        client.request({'command':'save_project','args':{'path':str(project)}})
        report['checks'].append('save native state')
        stage('reopen_state')
        client.request({'command':'new_project'})
        client.request({'command':'open_project','args':{'path':str(project)}})
        slots=[p for t in client.state()['tracks'] for p in t['plugins']]
        assert len(slots)==1 and not slots[0].get('missing'), slots
        report['checks'].append('reopen native state')
        stage('offline_render')
        rendered=args.out/'render.wav'
        client.request({'command':'export_wav','args':{'path':str(rendered),'start_seconds':0,'end_seconds':2,
            'sample_rate':48000,'bit_depth':16,'tail_seconds':0}})
        with wave.open(str(rendered),'rb') as wav:
            pcm=wav.readframes(wav.getnframes())
            report['render']={'sample_rate':wav.getframerate(),'channels':wav.getnchannels(),'frames':wav.getnframes(),
                'nonzero':any(pcm),'bytes':len(pcm),'sha256':hashlib.sha256(pcm).hexdigest()}
            if wav.getframerate()!=48000 or wav.getnchannels()!=2 or wav.getnframes()!=96000:
                raise RuntimeError('Offline render did not produce the requested stereo 48 kHz / two-second result.')
        report['checks'].append('two-second offline render (silence allowed for unconfigured instrument)')
        stage('close')
        client.close()
        report['process_exit_code']=client.process.poll()
        if report['process_exit_code']!=0:
            raise RuntimeError('Plugin host exited abnormally during teardown: '+str(report['process_exit_code']))
        client=None
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',error=type(error).__name__+': '+str(error))
        if client is not None: report['process_exit_code']=client.process.poll()
    finally:
        if client is not None: client.close()
        save()
    print(json.dumps({'status':report['status'],'stage':report['stage'],'report':str(args.out/'report.json')},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__': raise SystemExit(main())
