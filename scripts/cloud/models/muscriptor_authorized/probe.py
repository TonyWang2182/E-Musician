"""Offline MuScriptor medium CPU-load / explicit eight-second GPU deployment checks."""
import argparse
import dataclasses
import fcntl
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path('/root/autodl-tmp/emusician')
WEIGHTS = ROOT/'models/muscriptor/model.safetensors'
WEIGHT_SHA = 'ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec'
WEIGHT_BYTES = 1228144472
SOURCE = ROOT/'workspace/evaluations/real_audio_20261106/inputs/piano.mp3'
SOURCE_SHA = '5b425c8fe09cf82f99a530ae529fe7607c0b792e93d0f91455cc338fd95b632f'
CONFIG = {'dim': 1024, 'num_heads': 16, 'num_layers': 24, 'card': 1395}
DEADLINE = 180


def artifact(path):
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    temp.replace(path)


def files():
    weights = artifact(WEIGHTS)
    assert weights['sha256'] == WEIGHT_SHA and weights['bytes'] == WEIGHT_BYTES
    path = WEIGHTS.with_name('config.json')
    config = json.loads(path.read_text())
    assert {key: config[key] for key in CONFIG} == CONFIG, 'Need official medium config next to weights'
    return [weights, artifact(path)]


def finite_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            finite_tree(item)


def worker(mode, output):
    verified = files()
    import torch
    from muscriptor import TranscriptionModel
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    before_cuda = torch.cuda.is_initialized()
    if mode == 'cpu':
        assert os.environ.get('CUDA_VISIBLE_DEVICES') == '-1' and not before_cuda
    else:
        torch.cuda.set_per_process_memory_fraction(10 * 1024**3 / torch.cuda.get_device_properties(0).total_memory)
        torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    model = TranscriptionModel.load_model(weights_path=WEIGHTS, device='cpu' if mode == 'cpu' else 'cuda', dtype='float32')
    loaded = time.monotonic()
    params = list(model._model.parameters())
    assert params and all(p.device.type == ('cpu' if mode == 'cpu' else 'cuda') for p in params)
    parameter_count = sum(p.numel() for p in params)
    report = {'id': 'muscriptor-medium', 'status': 'passed', 'mode': mode,
              'source_revision': '8a1ef88672cc23c26619adaff37ec48d82c0b906',
              'model_revision': 'f32236969308476e01fd3aae67357de5feb05a2d',
              'artifacts': verified, 'config': CONFIG, 'parameter_count': parameter_count,
              'load_seconds': loaded - started, 'network_used': False,
              'packages': {n: importlib.metadata.version(n) for n in ('muscriptor','torch','numpy','soundfile','mido','safetensors')},
              'daw_connected': False, 'quality_evaluation': False}
    if mode == 'cpu':
        assert all(torch.isfinite(p).all().item() for p in params)
        assert not torch.cuda.is_initialized()
        report.update(all_parameters_finite=True, cuda_initialized=False, inference_performed=False)
    else:
        import mido
        import numpy as np
        import soundfile as sf
        from muscriptor.events import NoteStartEvent, NoteEndEvent, ProgressEvent
        source = artifact(SOURCE)
        assert source['sha256'] == SOURCE_SHA
        with sf.SoundFile(str(SOURCE)) as original:
            rate = original.samplerate
            audio = original.read(rate * 8, dtype='float32', always_2d=True)
        assert len(audio) == rate * 8 and np.isfinite(audio).all() and float(np.abs(audio).max()) > 0
        fixture = output/'fixture-first-8-seconds.wav'
        sf.write(str(fixture), audio, rate, subtype='FLOAT')
        waveform = torch.from_numpy(np.ascontiguousarray(audio.T))
        infer_start = time.monotonic()
        # No hidden tempo-model download: use the native event stream directly.
        # All instrument groups remain available; no piano-only constraint.
        events = list(model.transcribe((waveform, rate), use_sampling=False, cfg_coef=1.0,
            instruments=None, batch_size=1, no_eos_is_ok=False, beam_size=1, prelude_forcing=True))
        torch.cuda.synchronize()
        raw_events = [{'type': type(event).__name__, **dataclasses.asdict(event)} for event in events]
        write(output/'events.json', raw_events)
        midi_bytes = model.events_to_midi_bytes(iter(events))
        midi_path = output/'transcription.mid'
        midi_path.write_bytes(midi_bytes)
        finite_tree(raw_events)
        progress = [event for event in events if isinstance(event, ProgressEvent)]
        assert progress and progress[-1].completed == progress[-1].total == 2
        starts = {event.index: event for event in events if isinstance(event, NoteStartEvent)}
        ends = [event for event in events if isinstance(event, NoteEndEvent)]
        assert len(starts) == len(ends) and {e.start_event_index for e in ends} == set(starts)
        # Native model pads its last 5s chunk; retain any tail predictions and
        # report them instead of silently trimming the raw model result.
        for event in starts.values():
            assert 0 <= event.pitch <= 127 and 0 <= event.start_time <= 10.1
        for event in ends:
            assert 0 <= event.start_event.start_time <= event.end_time <= 10.1
        midi = mido.MidiFile(file=io.BytesIO(midi_bytes))
        assert math.isfinite(midi.length) and 0 <= midi.length <= 10.2
        notes = 0
        velocities = set()
        for track in midi.tracks:
            for message in track:
                assert message.time >= 0
                if message.type in ('note_on','note_off'):
                    assert 0 <= message.note <= 127 and 0 <= message.velocity <= 127
                    if message.type == 'note_on' and message.velocity:
                        notes += 1
                        velocities.add(message.velocity)
        assert starts and notes > 0, 'Non-silent Keyboard fixture produced no usable note output'
        report.update(inference_performed=True, input_origin=source, fixture=artifact(fixture),
            fixture_start_seconds=0, fixture_duration_seconds=8, full_original_test=False,
            inference_seconds=time.monotonic() - infer_start, event_count=len(raw_events),
            note_start_count=len(starts), midi_note_on_count=notes, midi_seconds=midi.length,
            instruments=sorted({e.instrument for e in starts.values()}), midi_velocities=sorted(velocities),
            actual_velocity_prediction=False, tempo_detection=False, midi_tempo_placeholder_bpm=120,
            completed_chunks=2, native_chunk_seconds=5, padded_last_chunk_seconds=2,
            note_starts_after_fixture=sum(e.start_time > 8 for e in starts.values()),
            note_ends_after_fixture=sum(e.end_time > 8 for e in ends),
            parameters={'use_sampling':False,'cfg_coef':1.0,'instruments':None,'batch_size':1,
                        'no_eos_is_ok':False,'beam_size':1,'prelude_forcing':True},
            gpu=torch.cuda.get_device_name(), cuda_runtime=torch.version.cuda,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(), peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            allocator_cap_bytes=10 * 1024**3,
            outputs=[artifact(output/'events.json'), artifact(midi_path)])
    report['elapsed_seconds'] = time.monotonic() - started
    write(output/'result.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    free = subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'], text=True, timeout=5)
    return {'active_ace_jobs': active, 'free_gpu_mib': int(free.strip().splitlines()[0])}


def stop_owned(process):
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def interrupt(signum, frame):
    raise KeyboardInterrupt(f'Supervisor signal {signum}')


def run_guard(mode, output, logpath):
    report = {'id':'muscriptor-medium','mode':mode,'status':'running','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'script':artifact(Path(__file__).resolve()),'output':str(output),'log':str(logpath),'deadline_seconds':DEADLINE}
    process, lock, minimum = None, None, None
    started = time.monotonic()
    env = os.environ.copy()
    for name in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN'):
        env.pop(name, None)
    env.update(HF_HOME=str(ROOT/'workspace/models/muscriptor/probe-hf'),HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
        HF_HUB_DISABLE_TELEMETRY='1',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    if mode == 'cpu':
        env['CUDA_VISIBLE_DEVICES'] = '-1'
    else:
        env.pop('CUDA_VISIBLE_DEVICES', None)
    try:
        output.mkdir(parents=True, exist_ok=False)
        if mode == 'gpu':
            lock = (ROOT/'state/model-library-gpu-probe.lock').open('a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report['before'] = before = state()
            minimum = before['free_gpu_mib']
            if before['active_ace_jobs'] or minimum < 12288:
                report.update(status='blocked',reason='ACE active or less than12GiB free; no child started')
                raise RuntimeError('Admission denied')
        logpath.parent.mkdir(parents=True,exist_ok=True)
        with logpath.open('wb') as log:
            process = subprocess.Popen([str(ROOT/'envs/muscriptor/bin/python'),str(Path(__file__).resolve()),
                '--worker',mode,'--output',str(output)],env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while process.poll() is None:
                current = state() if mode == 'gpu' else None
                if current:
                    minimum = min(minimum,current['free_gpu_mib'])
                if time.monotonic()-started > DEADLINE or (current and (current['active_ace_jobs'] or current['free_gpu_mib'] < 1024)):
                    report.update(status='interrupted',reason='Deadline, ACE activity, or VRAM reserve',observed=current)
                    stop_owned(process)
                    break
                time.sleep(0.5)
        if report['status'] == 'running':
            report['status'] = 'passed' if process.returncode == 0 and (output/'result.json').is_file() else 'failed'
    except BaseException as error:
        report['error_type'] = type(error).__name__
        if report['status'] == 'running':
            report['status'] = 'interrupted' if isinstance(error,KeyboardInterrupt) else 'failed'
    finally:
        try:
            stop_owned(process)
        except BaseException as error:
            report.update(status='failed',cleanup_error_type=type(error).__name__)
        if lock is not None:
            try:
                lock.close()
            except OSError as error:
                report.update(status='failed',lock_close_error_type=type(error).__name__)
        if mode == 'gpu':
            try:
                report['after'] = state()
            except BaseException as error:
                report.update(status='failed',after_state_error_type=type(error).__name__)
        report.update(exit_code=None if process is None else process.returncode,
                      elapsed_seconds=time.monotonic()-started,minimum_free_gpu_mib=minimum)
        if (output/'result.json').is_file():
            try:
                report['result'] = json.loads((output/'result.json').read_text())
            except (OSError,UnicodeError,ValueError) as error:
                report.update(status='failed',result_error_type=type(error).__name__)
        try:
            write(output/'guard.json',report)
        except BaseException as error:
            report.update(status='failed',receipt_write_error_type=type(error).__name__)
            print(json.dumps(report),flush=True)
            raise
    print(json.dumps(report),flush=True)
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['cpu','gpu'])
    parser.add_argument('--worker',choices=['cpu','gpu'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--authorized-weights',action='store_true')
    parser.add_argument('--approved-slot',action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only probe')
    if args.worker:
        return worker(args.worker,args.output)
    if not args.authorized_weights or args.mode not in ('cpu','gpu'):
        parser.error('Confirmed authorized weights and mode are required')
    if args.mode == 'gpu' and not args.approved_slot:
        parser.error('Root-authorized exclusive GPU slot is required')
    stamp = time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]
    output = ROOT/'results/muscriptor-authorized'/(args.mode+'-'+stamp)
    logpath = ROOT/'logs/model-library'/('muscriptor-'+args.mode+'-'+stamp+'.log')
    signal.signal(signal.SIGTERM,interrupt)
    signal.signal(signal.SIGHUP,interrupt)
    return run_guard(args.mode,output,logpath)


if __name__ == '__main__':
    sys.exit(main())
