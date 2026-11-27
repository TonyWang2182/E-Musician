"""CPU-only contract/queue/HTTP tests; no model import or cloud access."""
from copy import deepcopy
import hashlib
import http.client
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch, Mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/cloud'))
from compute.protocol import validate_request, wav_info, atomic_json, digest
from compute.store import Store, Conflict, QueueFull
from compute.catalog import Catalog
from compute.normalize import empty_result, finish_summary, validate_result, midi_tracks, set_tracks, score_events
from compute.server import ComputeHTTPServer
from compute.supervisor import Supervisor, stop_owned


def wav_bytes(seconds=.1, rate=8000):
    result = io.BytesIO()
    with wave.open(result, 'wb') as out:
        out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\x01\x00' * int(seconds*rate))
    return result.getvalue()


def generation(job='sample', model='ace-step-1.5-xl-turbo'):
    return {'request_id': job, 'kind': 'generate', 'model_id': model,
            'parameters': {'prompt': 'A piano melody', 'lyrics': '', 'instrumental': True,
                'duration_seconds': 10, 'bpm': 120, 'time_signature': '4/4', 'seed': 3}}


class ProtocolTests(unittest.TestCase):
    def test_known_generation(self):
        for model in ('ace-step-1.5-xl-turbo', 'yue2'):
            self.assertEqual(validate_request(generation(model=model))['model_id'], model)

    def test_no_arbitrary_command_path_or_model(self):
        for field in ('command', 'path', 'python'):
            with self.assertRaises(ValueError):
                validate_request({**generation(), field: '/tmp/evil'})
        request = generation(); request['model_id'] = '../model'
        with self.assertRaises(ValueError): validate_request(request)

    def test_invalid_generation_ranges(self):
        for key, value in (('duration_seconds', 121), ('seed', True), ('bpm', float('nan')),
                           ('time_signature', '7/8'), ('prompt', 'x'*2001), ('lyrics', 'words')):
            request = generation(); request['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_request(request)

    def test_score_singular_and_fixed_mir_parameters(self):
        request = {'request_id': 'score1', 'kind': 'score', 'model_id': 'sheetsage2',
                   'input': {'sha256': '1'*64}, 'parameters': {}}
        self.assertEqual(validate_request(request), request)
        request['kind'] = 'scores'
        with self.assertRaises(ValueError): validate_request(request)
        request['kind'] = 'score'; request['parameters'] = {'segment_seconds': 8}
        with self.assertRaises(ValueError): validate_request(request)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = Store(self.root)

    def test_upload_hash_then_idempotent(self):
        data = wav_bytes(); sha = hashlib.sha256(data).hexdigest()
        item = self.store.upload(sha, len(data), io.BytesIO(data))
        self.assertEqual(item['frames'], 800)
        self.assertEqual(self.store.upload(sha, len(data), io.BytesIO(data)), item)
        self.assertEqual(len(list(self.store.assets.glob('*.wav'))), 1)

    def test_failed_upload_never_published(self):
        data = wav_bytes()
        for body, length, sha in ((data, len(data), '0'*64), (data[:-3], len(data), hashlib.sha256(data).hexdigest())):
            with self.assertRaises(ValueError): self.store.upload(sha, length, io.BytesIO(body))
        self.assertEqual(list(self.store.assets.iterdir()), [])

    def test_reject_geometry_and_truncation(self):
        data = bytearray(wav_bytes())
        struct.pack_into('<I', data, 24, 1)
        with self.assertRaises(ValueError):
            self.store.upload(hashlib.sha256(data).hexdigest(), len(data), io.BytesIO(data))

    def test_float32_riff_is_supported(self):
        fmt = struct.pack('<HHIIHH', 3, 2, 48000, 48000*8, 8, 32)
        body = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', 80) + b'\0'*80
        data = b'RIFF'+struct.pack('<I', len(body)+4)+b'WAVE'+body
        item = self.store.upload(hashlib.sha256(data).hexdigest(), len(data), io.BytesIO(data))
        self.assertEqual(item['sample_format'], 'float32'); self.assertEqual(item['frames'], 10)

    def test_duplicate_request_and_conflicting_reuse(self):
        self.assertTrue(self.store.submit(generation())[1])
        self.assertFalse(self.store.submit(generation())[1])
        changed = generation(); changed['parameters']['seed'] = 9
        with self.assertRaises(Conflict): self.store.submit(changed)

    def test_queue_bound(self):
        for i in range(16): self.store.submit(generation('job'+str(i)))
        with self.assertRaises(QueueFull): self.store.submit(generation('extra'))

    def test_missing_input_rejected(self):
        with self.assertRaises(KeyError):
            self.store.submit({'request_id': 'a', 'kind': 'separate', 'model_id': 'scnet',
                               'input': {'sha256': '1'*64}, 'parameters': {}})

    def test_queued_cancel_and_running_publish_race(self):
        self.store.submit(generation('queued')); self.store.cancel('queued')
        self.assertIsNone(self.store.next_job())
        self.store.submit(generation('running')); self.store.next_job()
        self.store.cancel('running'); self.store.update('running', 'running')
        self.assertEqual(self.store.get('running')['status'], 'cancelling')
        self.store.update('running', 'ready', result={'should_not_publish': True})
        self.assertEqual(self.store.get('running')['status'], 'cancelled')
        self.assertIsNone(self.store.get('running')['result'])

    def test_recovery_does_not_rerun_or_erase_ready(self):
        self.store.submit(generation('a')); self.store.submit(generation('b'))
        self.store.update('b', 'ready', result={'ok': True})
        self.store.recover()
        self.assertEqual(self.store.get('a')['status'], 'interrupted')
        self.assertEqual(self.store.get('b')['result'], {'ok': True})

    def test_resource_failure_retains_terminal_receipt(self):
        self.store.submit(generation()); job = self.store.next_job()
        catalog = Mock(); catalog.provider.return_value = {'available': True}
        supervisor = Supervisor(self.store, catalog)
        with patch('compute.supervisor.resources', side_effect=OSError('diagnostic unavailable')):
            supervisor.execute(job)
        self.assertEqual(self.store.get('sample')['status'], 'failed')
        self.assertEqual(json.loads((self.store.jobs/'sample/attempt.json').read_text())['status'], 'failed')

    def test_model_weights_verified_before_load(self):
        base=self.root/'models/chordmini';base.mkdir(parents=True)
        source=self.root/'workspace/chordmini';source.mkdir(parents=True)
        weights=base/'model.pth';weights.write_bytes(b'pinned fixture, not a model')
        config=source/'model.yaml';config.write_text('example: true')
        manifest={'paths':{'source':str(source)},'artifacts':[
            {'path':str(p),'sha256':digest(p)} for p in (weights,config)]}
        atomic_json(self.root/'manifests/model-library/chordmini/deployment.json',manifest)
        self.assertEqual(Catalog(self.root).verify_files('chordmini')['files'],2)
        weights.write_bytes(b'changed')
        with self.assertRaises(ValueError):Catalog(self.root).verify_files('chordmini')

    def test_cancellation_wins_failed_worker_race(self):
        self.store.submit(generation());self.store.next_job();self.store.cancel('sample')
        self.store.update('sample','failed',error='late worker failure')
        self.assertEqual(self.store.get('sample')['status'],'cancelled')

    def test_artifacts_unavailable_until_ready(self):
        self.store.submit(generation())
        with self.assertRaises(Conflict):self.store.artifact('sample','audio.wav')

    def test_result_receipt_failure_prevents_ready(self):
        self.store.submit(generation());job=self.store.next_job()
        catalog=Mock();catalog.provider.return_value={'available':False}
        with patch('compute.supervisor.atomic_json',side_effect=OSError('disk full')):
            Supervisor(self.store,catalog).execute(job)
        state=self.store.get('sample')
        self.assertEqual(state['status'],'failed');self.assertIn('could not be persisted',state['error'])

    def test_admission_cancel_cannot_start_process(self):
        self.store.submit(generation()); job = self.store.next_job(); self.store.cancel('sample')
        catalog = Mock(); catalog.provider.return_value = {'available': True}
        supervisor = Supervisor(self.store, catalog)
        with patch('compute.supervisor.resources', return_value={'gpu_free_bytes': 32*1024**3, 'host_available_bytes': 32*1024**3}), patch('compute.supervisor.subprocess.Popen') as launch:
            supervisor.execute(job)
        launch.assert_not_called(); self.assertEqual(self.store.get('sample')['status'], 'cancelled')


class NormalizationTests(unittest.TestCase):
    def test_raw_score_chords_structures_and_real_beats(self):
        events = [
            {'time': 0, 'values': {'chord': 'C:maj7', 'structure': 'intro', 'key': 'C:maj', 'rhythm': {'meter': [4,4], 'eighth_position': 0}}},
            {'time': .5, 'values': {'rhythm': {'eighth_position': 2}}},
            {'time': 1, 'values': {'chord': 'X', 'structure': 'verse'}}]
        result = score_events(events, 2)
        self.assertEqual(result['chord_regions'][0]['raw_label'], 'C:maj7')
        self.assertIsNone(result['chord_regions'][0]['score'])
        self.assertEqual(result['beat_events'], [{'time_seconds': 0, 'is_downbeat': True}, {'time_seconds': .5, 'is_downbeat': False}])
        self.assertEqual(result['structure_regions'][1]['end_seconds'], 2)

    def test_midi_tempo_map_channel_pedal_and_padding(self):
        def message(kind, delta, **kwargs): return types.SimpleNamespace(type=kind, time=delta, **kwargs)
        midi = types.SimpleNamespace(type=1, ticks_per_beat=480, tracks=[
            [message('set_tempo',0,tempo=500000),message('set_tempo',480,tempo=1000000)],
            [message('track_name',0,name='Piano'), message('program_change',0,channel=0,program=0),
             message('note_on',0,channel=0,note=60,velocity=82), message('control_change',240,channel=0,control=64,value=127),
             message('note_off',720,channel=0,note=60,velocity=0)]])
        module = types.SimpleNamespace(MidiFile=lambda path: midi)
        with patch.dict(sys.modules, {'mido': module}): tracks, edge = midi_tracks('ignored.mid', 1.2)
        self.assertEqual(tracks[0]['notes'][0]['duration_seconds'], 1.2)
        self.assertEqual(tracks[0]['notes'][0]['channel'], 1)
        self.assertEqual(tracks[0]['controllers'][0], {'time_seconds': .25, 'controller': 64, 'value':127, 'channel':1})
        self.assertEqual(edge['selection_edge_clipped_notes'], 1)

    def test_no_structures_or_beats_are_invented(self):
        self.assertEqual(score_events([], 10), {'chord_regions': [], 'structure_regions': [], 'beat_events': [], 'annotations': []})

    def test_artifact_fence_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); path = directory / 'audio.wav'; path.write_bytes(wav_bytes())
            request = generation(); result = empty_result(request, {}, .1)
            result['artifacts'] = [{'id':'audio.wav', 'role':'generated_audio', 'sha256':digest(path), **wav_info(path)}]
            self.assertEqual(validate_result(result, directory, request)['summary']['note_count'], 0)
            result['artifacts'][0]['sha256'] = '0'*64
            with self.assertRaises(ValueError): validate_result(result, directory, request)

    def test_tracks_and_flat_previews_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); path=directory/'audio.wav';path.write_bytes(wav_bytes())
            request=generation(); result=empty_result(request,{},.1)
            result['artifacts']=[{'id':'audio.wav','sha256':digest(path),**wav_info(path)}]
            result['notes']=[{'pitch':60,'start_seconds':0,'duration_seconds':.05,'velocity':80,'channel':1,'track_id':'missing'}]
            with self.assertRaises(ValueError):validate_result(result,directory,request)

    def test_kill_race_and_forced_fallback(self):
        import subprocess
        process=Mock(pid=999); process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('test',5),0]
        with patch('compute.supervisor.os.killpg',side_effect=ProcessLookupError,create=True) as kill, patch('compute.supervisor.signal.SIGKILL',9,create=True):
            stop_owned(process)
        self.assertEqual(kill.call_count,2)

    def test_descendant_cleanup_after_leader_exits(self):
        process=Mock(pid=999);process.poll.return_value=0;process.compute_token='unique-launch'
        with patch('compute.supervisor.owned_group_remains',side_effect=[True,False,False]), patch('compute.supervisor.os.killpg',create=True) as kill:
            stop_owned(process)
        kill.assert_called_once()
        process.wait.assert_not_called()


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        store=Store(self.temp.name);catalog=Mock();catalog.provider.return_value={'available':True}
        catalog.capabilities.return_value={'providers':[],'protocol_version':2}
        self.server=ComputeHTTPServer(('127.0.0.1',0),store,catalog)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)

    def call(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request(method,path,body=body,headers=headers or {})
        response=connection.getresponse();data=response.read();status=response.status
        connection.close();return status,data

    def test_health_identity(self):
        status,data=self.call('GET','/health')
        self.assertEqual(status,200);self.assertEqual(json.loads(data)['service'],'emusician-compute')

    def test_upload_submit_poll_and_cancel(self):
        data=wav_bytes();sha=hashlib.sha256(data).hexdigest()
        self.assertEqual(self.call('PUT','/assets/'+sha,data)[0],200)
        self.assertEqual(self.call('HEAD','/assets/'+sha)[0],200)
        request={'request_id':'sc','kind':'separate','model_id':'scnet','input':{'sha256':sha},'parameters':{}}
        self.assertEqual(self.call('POST','/jobs',json.dumps(request))[0],202)
        self.assertEqual(self.call('POST','/jobs',json.dumps(request))[0],200)
        self.assertEqual(json.loads(self.call('GET','/jobs/sc')[1])['status'],'queued')
        self.assertEqual(json.loads(self.call('POST','/jobs/sc/cancel',b'')[1])['status'],'cancelled')

    def test_origin_and_path_fences(self):
        self.assertEqual(self.call('POST','/jobs',json.dumps(generation()),{'Origin':'https://example.invalid'})[0],403)
        self.assertEqual(self.call('GET','/jobs/%2e%2e/artifacts/x')[0],400)

    def test_download_exact_manifest_bytes(self):
        store=self.server.store;store.submit(generation('publish'))
        output=store.jobs/'publish/output';output.mkdir()
        path=output/'audio.wav';path.write_bytes(wav_bytes())
        result=empty_result(generation('publish'),{},.1)
        result['artifacts']=[{'id':'audio.wav','role':'generated_audio','sha256':digest(path),**wav_info(path)}]
        store.update('publish','ready',result=result)
        status,data=self.call('GET','/jobs/publish/artifacts/audio.wav')
        self.assertEqual(status,200);self.assertEqual(data,path.read_bytes())
        self.assertEqual(self.call('GET','/jobs/publish/artifacts/request.json')[0],404)


if __name__=='__main__':unittest.main()
