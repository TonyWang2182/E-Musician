"""Explicitly authorized SheetSage2 coexistence smoke; cloud-only artifacts."""
import argparse
import fcntl
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
import wave
from stage import ROOT, artifact, deployment, save_deployment, write

BASE = ROOT/'workspace/models/sheetsage2'
FIXTURE = ROOT/'jobs/generation/gateway-20261106T075755Z-120s/audio.wav'


def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    free = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True, timeout=5)
    return {'active_ace_jobs': active, 'free_gpu_mib': int(free.strip().splitlines()[0])}


def finite_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for v in value.values():
            finite_tree(v)
    elif isinstance(value, list):
        for v in value:
            finite_tree(v)


def worker(output):
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoModel
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(10*1024**3/torch.cuda.get_device_properties(0).total_memory)
    torch.cuda.reset_peak_memory_stats()
    source = output/'input.wav'
    with wave.open(str(FIXTURE), 'rb') as original, wave.open(str(source), 'wb') as clip:
        clip.setparams(original.getparams())
        clip.writeframes(original.readframes(original.getframerate()*8))
    audio, rate = sf.read(source, always_2d=True, dtype='float32')
    assert np.isfinite(audio).all() and 7.9 <= len(audio)/rate <= 8.1
    assert float(np.abs(audio).max()) > 0
    started = time.monotonic()
    model = AutoModel.from_pretrained(str(ROOT/'models/sheetsage2'), trust_remote_code=True,
        local_files_only=True, base_model_path=str(ROOT/'models/mert2')).eval().to('cuda')
    result = model.transcribe(source, output_dir=output/'transcription', dtype='bf16', preset='default')
    torch.cuda.synchronize()
    finite_tree(result)
    assert isinstance(result, dict) and abs(result['duration_seconds']-8) < 0.1
    assert isinstance(result['events'], list)
    for event in result['events']:
        assert isinstance(event, dict) and 0 <= event['time'] <= 8.1
    for tokens in result.get('tokens', []):
        assert torch.isfinite(tokens).all().item()
    # Verify actual exported MIDI readability and bounded notes rather than
    # treating a process exit as model success. Empty music remains a limitation.
    import mido
    midi_files = list((output/'transcription').glob('*.mid'))
    assert midi_files
    midi_notes = 0
    for path in midi_files:
        midi = mido.MidiFile(path)
        assert math.isfinite(midi.length) and 0 <= midi.length <= 8.5
        for track in midi.tracks:
            for message in track:
                assert message.time >= 0
                if message.type in ('note_on', 'note_off'):
                    assert 0 <= message.note <= 127 and 0 <= message.velocity <= 127
                    midi_notes += message.type == 'note_on' and message.velocity > 0
    files = [artifact(p) for p in (output/'transcription').iterdir() if p.is_file()]
    report = {'status': 'passed', 'actual_model_inference': True, 'input': artifact(source),
        'input_origin': str(FIXTURE), 'input_duration_seconds': len(audio)/rate,
        'elapsed_seconds': time.monotonic()-started, 'gpu': torch.cuda.get_device_name(),
        'torch': torch.__version__, 'cuda_runtime': torch.version.cuda,
        'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
        'peak_reserved_bytes': torch.cuda.max_memory_reserved(), 'allocator_cap_bytes': 10*1024**3,
        'upstream_window_seconds': 300, 'preset': 'default', 'dtype': 'bf16',
        'full_task_prompts': True, 'quality_evaluation': False, 'daw_connected': False,
        'abc_present': bool(result.get('abc')), 'abc_error': result.get('abc_error'),
        'result_keys': sorted(result), 'midi_note_on_count': midi_notes, 'artifacts': files}
    write(output/'probe-result.json', report)
    print(json.dumps(report), flush=True)


def stop_owned(process):
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # The owned child may have exited between poll and killpg.
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-slot', action='store_true')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only probe')
    if args.worker:
        return worker(args.worker)
    if not args.approved_slot:
        raise RuntimeError('Explicit root-authorized serialized GPU slot required')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+uuid.uuid4().hex[:8]
    output = ROOT/'results/model-library/sheetsage2'/stamp
    logpath = ROOT/'logs/model-library'/('sheetsage2-gpu-'+stamp+'.log')
    report = {'id': 'sheetsage2', 'status': 'running', 'started_utc': stamp, 'before': None,
              'output': str(output), 'log': str(logpath), 'deadline_seconds': 180,
              'guard_script': artifact(Path(__file__).resolve())}
    env = os.environ.copy()
    env.pop('CUDA_VISIBLE_DEVICES', None)
    env.update(HF_HOME=str(BASE/'hf'), HF_HUB_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
        OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', HF_HUB_DISABLE_TELEMETRY='1')
    env['PATH'] = str(BASE/'toolchain/bin')+os.pathsep+env.get('PATH', '')
    minimum = None
    started = time.monotonic()
    process = None
    lock = None
    try:
        lock = (ROOT/'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = state()
        report['before'] = before
        minimum = before['free_gpu_mib']
        if before['active_ace_jobs'] or minimum < 12288:
            report.update(status='blocked', reason='ACE active or less than12GiB free')
            raise RuntimeError('Admission denied; no child started')
        output.mkdir(parents=True, exist_ok=False)
        logpath.parent.mkdir(parents=True, exist_ok=True)
        with logpath.open('wb') as log:
            process = subprocess.Popen([str(ROOT/'envs/sheetsage2/bin/python'), str(Path(__file__).resolve()),
                '--worker', str(output)], env=env, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                current = state()
                minimum = min(minimum, current['free_gpu_mib'])
                if current['active_ace_jobs'] or current['free_gpu_mib'] < 1024 or time.monotonic()-started > 180:
                    report.update(status='interrupted', reason='ACE activity, VRAM reserve, or180-second deadline', observed=current)
                    stop_owned(process)
                    break
                time.sleep(0.5)
        if report['status'] == 'running':
            report['status'] = 'passed' if process.returncode == 0 and (output/'probe-result.json').is_file() else 'failed'
    except BaseException as error:
        report.update(error_type=type(error).__name__)
        if report['status'] == 'running':
            report['status'] = 'failed'
    finally:
        try:
            if process is not None:
                stop_owned(process)
        except BaseException as error:
            report.update(status='failed', cleanup_error_type=type(error).__name__)
        if lock is not None:
            try:
                lock.close()
            except OSError as error:
                report.update(status='failed', lock_close_error_type=type(error).__name__)
        report.update(exit_code=None if process is None else process.returncode,
                      elapsed_seconds=time.monotonic()-started, minimum_free_gpu_mib=minimum)
        try:
            report['after'] = state()
        except BaseException as error:
            report.update(status='failed', after_state_error_type=type(error).__name__)
        if (output/'probe-result.json').is_file():
            try:
                report['result'] = json.loads((output/'probe-result.json').read_text())
            except (OSError, UnicodeError, ValueError) as error:
                report.update(status='failed', result_error_type=type(error).__name__)
        path = ROOT/'manifests/model-library/sheetsage2'/('gpu-probe-'+stamp+'.json')
        try:
            write(path, report)
        except BaseException as error:
            report.update(status='failed', receipt_write_error_type=type(error).__name__)
            # Preserve the complete terminal record in the caller's raw log
            # even if a full/read-only disk prevents the JSON file write.
            print(json.dumps(report), flush=True)
            raise
    plan = json.loads((Path(__file__).parent/'artifacts.json').read_text())
    deployed = deployment('sheetsage2', plan)
    # Failed/blocked later attempts do not erase the immutable evidence of an
    # earlier successful deployment probe. Keep latest attempt separately.
    if report['status'] == 'passed':
        deployed['checks']['gpu_inference_verified'] = True
        deployed['gpu_probe'] = str(path)
    deployed['last_gpu_attempt'] = str(path)
    save_deployment('sheetsage2', deployed)
    print(json.dumps(report), flush=True)
    if report['status'] != 'passed':
        if logpath.is_file():
            print(logpath.read_text(errors='replace')[-6000:], flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
