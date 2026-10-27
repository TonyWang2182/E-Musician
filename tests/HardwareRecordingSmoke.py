"""Owned short ASIO input recording. Run only through Recorder; monitoring stays off."""
import argparse, hashlib, json, sys, time, uuid, wave
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'scripts'))
from agent_client import Client

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--exe', type=Path, required=True)
parser.add_argument('--device', required=True, help='Exact installed ASIO device name; captures two seconds of its first audio input')
parser.add_argument('--fallback-default', action='store_true')
args = parser.parse_args()
exe = args.exe.resolve(strict=True)
directory = root / 'build/hardware-smoke' / str(uuid.uuid4())
directory.mkdir(parents=True)
report = {'status':'running', 'workspace':str(directory), 'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
          'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'scope':'Short physical ASIO input capture; no monitoring, physical keyboard performance or listening claim', 'checks':[]}
print(str(directory), flush=True)
try:
    with Client(exe, 90) as client:
        def command(name, args=None):
            return client.request({'command':name, 'args':args or {}})
        before = command('get_audio_devices', {'scan':True})['result']
        report['before'] = before
        drivers = [d for d in before['drivers'] if d['driver_type']=='ASIO']
        if len(drivers)!=1: raise RuntimeError('ASIO driver type unavailable')
        names = [n for n in drivers[0]['outputs'] if n == args.device]
        if len(names)!=1: raise RuntimeError('Expected exactly one matching ASIO endpoint')
        try:
            command('configure_audio_device', {'driver_type':'ASIO', 'device_name':names[0], 'sample_rate':48000, 'buffer_size':256, 'input_channels':[0,1]})
            report['requested_configuration']='accepted'
        except Exception as error:
            report['requested_configuration']='rejected'; report['requested_configuration_error']=str(error)
            if not args.fallback_default: raise
            report['after_rejection']=command('get_audio_devices')['result']
            command('configure_audio_device', {'driver_type':'ASIO', 'device_name':names[0], 'input_channels':[0,1]})
        device = command('get_audio_devices')['result']; report['device'] = device
        if device['driver_type']!='ASIO' or device['sample_rate']<=0 or device['buffer_size']<=0:
            raise RuntimeError('ASIO did not open a real configuration')
        inputs = command('get_recording_inputs')['result']['inputs'];report['inputs'] = inputs
        audio = [i for i in inputs if not i['midi']]
        if not audio: raise RuntimeError('No physical audio input available')
        command('create_track', {'kind':'audio','name':'Owned ASIO capture'})
        tid = client.state()['tracks'][0]['id']
        command('set_track_input', {'track_id':tid, 'input_device_id':audio[0]['id']})
        command('set_input_monitor', {'input_device_id':audio[0]['id'], 'mode':'off'})
        command('set_track_armed', {'track_id':tid, 'armed':True})
        initial = client.state(); started = time.perf_counter()
        command('start_recording'); time.sleep(2)
        during = client.state();report['during'] = {k:during[k] for k in ('recording','position_seconds','xruns','cpu_usage')}
        if not during['recording'] or during['position_seconds']<1:
            raise RuntimeError('Physical recording transport did not advance')
        stopped = time.perf_counter(); command('stop_recording'); ack = time.perf_counter()
        while client.state()['recording_finalizing']:
            if time.perf_counter()-stopped>10: raise RuntimeError('Recording finalization exceeded ten seconds')
            time.sleep(.02)
        state = client.state(); report['stop_ack_ms'] = (ack-stopped)*1000
        report['stop_complete_ms'] = (time.perf_counter()-stopped)*1000
        report['xrun_delta'] = state['xruns']-initial['xruns']
        clips = state['tracks'][0]['clips']
        if len(clips)!=1 or clips[0]['duration_seconds']<1:
            raise RuntimeError('Physical recording clip missing or too short')
        command('set_track_armed', {'track_id':tid,'armed':False})
        project = directory/'Physical.emproj'; command('save_project', {'path':str(project)})
        stored = json.loads(project.read_text(encoding='utf-8-sig'))
        audio_file = directory/stored['assets'][0]['source']
        with wave.open(str(audio_file),'rb') as reader:
            report['recorded_audio'] = {'rate':reader.getframerate(), 'channels':reader.getnchannels(),
                'frames':reader.getnframes(), 'sample_width':reader.getsampwidth(), 'seconds':reader.getnframes()/reader.getframerate()}
        report['checks'].append('Physical ASIO input produced a readable WAV and persisted clip')
        command('open_project', {'path':str(project)})
        if len(client.state()['tracks'][0]['clips'])!=1 or client.state()['dirty']:
            raise RuntimeError('Physical recording failed to reopen cleanly')
        report['checks'].append('Saved physical capture reopens cleanly and disarmed')
        report['status']='passed'
except Exception as error:
    report['status']='failed'; report['error']=str(error)
finally:
    (directory/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'status':report['status'],'report':str(directory/'report.json'),'error':report.get('error')},ensure_ascii=False),flush=True)
raise SystemExit(0 if report['status']=='passed' else 1)
