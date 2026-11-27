"""Explicit one-module stopped live-device add probe; optional native editor."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from agent_client import Client
from PluginHostSmoke import exact_cache_entries
from InstalledPluginAudit import bounded_run


def child(args):
    report={'module':str(args.module),'status':'running','stage':'start_live_device',
            'visible_editor_tested':False,'played_audio':False}
    def save(): (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    def stage(value): report.update(stage=value);save()
    client=None
    try:
        stage('start_live_device')
        client=Client(args.exe,timeout=60,show=args.show,offline_test=False)
        report['main_window_and_timers']=args.show
        report['audio_devices']=client.completed(client.request({'command':'get_audio_devices'}))
        client.request({'command':'stop'})
        if args.driver_type:
            matching=[driver for driver in report['audio_devices']['drivers'] if driver['driver_type']==args.driver_type]
            if not matching or args.device_name not in matching[0]['outputs']:
                report['stage']='configure_device'
                raise RuntimeError('Requested device is not enumerated; no unknown driver was opened.')
            stage('configure_device')
            client.request({'command':'configure_audio_device','args':{
                'driver_type':args.driver_type,'device_name':args.device_name,'input_channels':[]}})
            report['requested_audio_devices']=client.completed(client.request({'command':'get_audio_devices'}))
            if report['requested_audio_devices'].get('driver_type')!=args.driver_type or report['requested_audio_devices'].get('device_name')!=args.device_name:
                raise RuntimeError('Requested device was not active after configuration.')
        client.request({'command':'set_master_gain','args':{'gain_db':-60}})
        descriptor=next(x for x in exact_cache_entries(args.module) if x['available'])
        client.request({'command':'create_track','args':{'kind':'instrument' if descriptor['is_instrument'] else 'audio','name':'Stopped live initialization probe'}})
        track=client.state()['tracks'][-1]['id']
        stage('live_add_plugin')
        client.request({'command':'add_plugin','args':{'track_id':track,'catalog_id':descriptor['id']}})
        if args.open_editor:
            stage('live_open_plugin_editor')
            slot=next(t for t in client.state()['tracks'] if t['id']==track)['plugins'][-1]
            client.request({'command':'open_plugin','args':{'track_id':track,'plugin_id':slot['id']}})
            report['native_editor_open_command']=True
        stage('stopped_graph_settle')
        end=time.monotonic()+10
        while time.monotonic()<end:
            state=client.state()
            slots=[p for t in state['tracks'] for p in t['plugins']]
            if len(slots)!=1 or slots[0].get('missing'):raise RuntimeError('Live instance missing')
            time.sleep(.25)
        if args.lifecycle:
            stage('live_editor_input_monitor_arm_toggles')
            inputs=client.completed(client.request({'command':'get_recording_inputs'}))['inputs']
            midi=next((i for i in inputs if i.get('midi')),None)
            report['midi_input_for_lifecycle']=midi
            if midi:
                client.request({'command':'set_track_input','args':{'track_id':track,'input_device_id':midi['id']}})
                for _ in range(3):
                    for armed,mode in ((True,'on'),(False,'off'),(True,'off'),(False,'on')):
                        client.request({'command':'set_track_armed','args':{'track_id':track,'armed':armed}})
                        client.request({'command':'set_input_monitor','args':{'track_id':track,'mode':mode}})
                        client.state();time.sleep(.05)
                client.request({'command':'set_input_monitor','args':{'track_id':track,'mode':'off'}})
                client.request({'command':'set_track_armed','args':{'track_id':track,'armed':False}})
            stage('live_editor_save_remove_undo')
            project=args.out/'lifecycle.emproj'
            client.request({'command':'save_project','args':{'path':str(project)}})
            slot=next(t for t in client.state()['tracks'] if t['id']==track)['plugins'][-1]
            client.request({'command':'remove_plugin','args':{'track_id':track,'plugin_id':slot['id']}})
            client.request({'command':'undo'})
            slot=next(t for t in client.state()['tracks'] if t['id']==track)['plugins'][-1]
            client.request({'command':'open_plugin','args':{'track_id':track,'plugin_id':slot['id']}})
            stage('live_editor_new_and_reopen')
            client.request({'command':'new_project'})
            client.request({'command':'open_project','args':{'path':str(project)}})
            slot=next(t for t in client.state()['tracks'] if t['id']==track)['plugins'][-1]
            client.request({'command':'open_plugin','args':{'track_id':track,'plugin_id':slot['id']}})
            client.state();time.sleep(.5)
            report['editor_lifecycle_commands']=True
        stage('close')
        client.close()
        report['process_exit_code']=client.process.poll()
        if report['process_exit_code']!=0:raise RuntimeError('Abnormal live host exit')
        client=None;report['status']='passed'
    except Exception as error:
        report.update(status='blocked' if report['stage']=='configure_device' else 'failed',error=type(error).__name__+': '+str(error))
        if client:report['process_exit_code']=client.process.poll()
    finally:
        if client:client.close()
        save()
    return 0 if report['status']=='passed' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--module',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--driver-type')
    parser.add_argument('--device-name')
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--open-editor',action='store_true')
    parser.add_argument('--show',action='store_true',help='Enable the actual MainComponent and its timers')
    parser.add_argument('--lifecycle',action='store_true',help='Stopped input/monitor/arm, save/remove/undo/new/reopen with editor')
    args=parser.parse_args()
    args.out=args.out.resolve()
    if bool(args.driver_type)!=bool(args.device_name):parser.error('Specify both driver type and exact device name.')
    if args.lifecycle and not args.open_editor:parser.error('Lifecycle probe requires --open-editor.')
    if args.child:return child(args)
    args.out.mkdir(parents=True,exist_ok=False)
    settings=Path(os.environ['APPDATA'])/'E-musician/Settings.xml'
    original=settings.read_bytes() if settings.exists() else None
    if original is not None:(args.out/'Settings-before.xml').write_bytes(original)
    report={}
    try:
        command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--child','--exe',str(args.exe),
                 '--module',str(args.module),'--out',str(args.out)]
        if args.driver_type:command.extend(['--driver-type',args.driver_type,'--device-name',args.device_name])
        if args.open_editor:command.append('--open-editor')
        if args.show:command.append('--show')
        if args.lifecycle:command.append('--lifecycle')
        report['process']=bounded_run(command,args.out/'live-host.log',180 if args.lifecycle else 90)
    finally:
        after=settings.read_bytes() if settings.exists() else None
        report['settings_sha256_before']=hashlib.sha256(original).hexdigest() if original is not None else None
        report['settings_sha256_after']=hashlib.sha256(after).hexdigest() if after is not None else None
        report['settings_changed']=after!=original
        if original is not None and after!=original:
            # This command requires exclusive ownership of the hardware-test
            # interval; do not run it alongside the user's DAW or another test.
            temporary=settings.with_suffix('.plugin-audit.tmp')
            temporary.write_bytes(original);os.replace(temporary,settings)
            report['original_settings_restored']=True
        report['settings_preserved']=settings.read_bytes()==original if original is not None else not settings.exists()
        (args.out/'supervisor.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)
    return 0 if report.get('process',{}).get('exit_code')==0 and report['settings_preserved'] else 1


if __name__=='__main__':raise SystemExit(main())
