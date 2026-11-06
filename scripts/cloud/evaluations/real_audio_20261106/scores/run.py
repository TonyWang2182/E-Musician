"""Whole original New Light analysis; explicit serialized GPU admission only."""
import argparse
import fcntl
import hashlib
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
SOURCE = ROOT/'workspace/evaluations/real_audio_20261106/inputs/newlight.mp3'
SOURCE_SHA = '885891e2076ca629d3e60685a68df3be07e20da00f0ee45038b5da547519826b'
SOURCE_SECONDS = 9627241 / 44100
BASE = ROOT/'workspace/models/sheetsage2'
DEADLINE = 600


def artifact(path):
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf8')
    temporary.replace(path)


def state():
    with sqlite3.connect(f'file:{ROOT}/state/generation.sqlite3?mode=ro', uri=True, timeout=2) as db:
        active = db.execute("SELECT status,COUNT(*) FROM jobs WHERE status NOT IN ('ready','failed','cancelled','interrupted') GROUP BY status").fetchall()
    free = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True, timeout=5)
    return {'active_ace_jobs': active, 'free_gpu_mib': int(free.strip().splitlines()[0])}


def finite_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite_tree(item)


def worker(output):
    import mido
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoModel
    source = artifact(SOURCE)
    assert source['sha256'] == SOURCE_SHA, 'Original input changed'
    info = sf.info(str(SOURCE))
    assert info.frames == 9627241 and info.samplerate == 44100 and info.channels == 2
    # Validate the complete MP3 without retaining an extra full-song array.
    with sf.SoundFile(str(SOURCE)) as audio:
        decoded_frames = 0
        for block in audio.blocks(blocksize=44100 * 10, dtype='float32', always_2d=True):
            assert np.isfinite(block).all()
            decoded_frames += len(block)
    assert decoded_frames == info.frames
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(10 * 1024**3 / torch.cuda.get_device_properties(0).total_memory)
    started = time.monotonic()
    model = AutoModel.from_pretrained(str(ROOT/'models/sheetsage2'), trust_remote_code=True,
        local_files_only=True, base_model_path=str(ROOT/'models/mert2')).eval().to('cuda')
    # Deliberately no max_seconds, source slicing, task subset or smaller window.
    result = model.transcribe(SOURCE, output_dir=output/'transcription', dtype='bf16', preset='default',
        progress=lambda event: print(json.dumps(event, ensure_ascii=False, default=str), flush=True))
    torch.cuda.synchronize()
    finite_tree(result)
    assert abs(result['duration_seconds'] - SOURCE_SECONDS) < 0.15, 'Model did not analyze whole input'
    windows = result['windows']
    assert len(windows) == 1 and windows[0]['start'] == 0
    assert abs(windows[0]['accept_end'] - result['duration_seconds']) < 0.001
    events = result['events']
    assert isinstance(events, list)
    for event in events:
        assert isinstance(event, dict) and 0 <= event['time'] <= result['duration_seconds'] + 0.1
    for tokens in result.get('tokens', []):
        assert torch.isfinite(tokens).all().item()
    midi_files = list((output/'transcription').glob('*.mid'))
    assert midi_files, 'No MIDI export'
    midis = []
    for path in midi_files:
        midi = mido.MidiFile(path)
        assert math.isfinite(midi.length) and 0 <= midi.length <= SOURCE_SECONDS + 2
        notes = 0
        for track in midi.tracks:
            for message in track:
                assert message.time >= 0
                if message.type in ('note_on', 'note_off'):
                    assert 0 <= message.note <= 127 and 0 <= message.velocity <= 127
                    notes += message.type == 'note_on' and message.velocity > 0
        midis.append({'path': str(path), 'seconds': midi.length, 'note_on_count': notes})
    limit = int(model.max_output_seq_len)
    warnings = list(result.get('warnings', []))
    reached_limit = any(w['tokens'] >= limit for w in windows)
    report = {
        'status': 'passed', 'actual_model_inference': True, 'input': source,
        'input_frames': info.frames, 'input_sample_rate': info.samplerate, 'input_channels': info.channels,
        'input_duration_seconds': SOURCE_SECONDS, 'model_duration_seconds': result['duration_seconds'],
        'whole_input_decoded': True, 'max_seconds': None, 'input_cropped': False,
        'elapsed_seconds': time.monotonic() - started, 'gpu': torch.cuda.get_device_name(),
        'torch': torch.__version__, 'cuda_runtime': torch.version.cuda,
        'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'peak_reserved_bytes': torch.cuda.max_memory_reserved(),
        'allocator_cap_bytes': 10 * 1024**3, 'window_seconds': result['window_seconds'],
        'preset': 'default', 'dtype': 'bf16', 'prompts': result['prompts'],
        'full_task_prompts': True, 'quality_evaluation': False, 'daw_connected': False,
        'abc_present': bool(result.get('abc')), 'abc_error': result.get('abc_error'),
        'event_count': len(events), 'first_event_seconds': min((e['time'] for e in events), default=None),
        'last_event_seconds': max((e['time'] for e in events), default=None),
        'windows': windows, 'max_output_sequence_length': limit, 'token_limit_reached': reached_limit,
        'warnings': warnings, 'midi': midis,
        'artifacts': [artifact(p) for p in sorted((output/'transcription').rglob('*')) if p.is_file()],
        'source_revisions': {'sheetsage2': 'b83c3d79a6d98bcffaf8f9ed112c90aa887887bc',
                             'mert2': 'd8ba1c745e733b3908ce6ad16ebeb17ac7600a42'},
    }
    write(output/'result-receipt.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


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


def run_guard(output, logpath):
    report = {'model': 'sheetsage2', 'status': 'running', 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'before': None, 'output': str(output), 'log': str(logpath), 'deadline_seconds': DEADLINE,
              'guard_script': artifact(Path(__file__).resolve()), 'input_sha256': SOURCE_SHA}
    env = os.environ.copy()
    env.pop('CUDA_VISIBLE_DEVICES', None)
    env.update(HF_HOME=str(BASE/'hf'), HF_HUB_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
        OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', HF_HUB_DISABLE_TELEMETRY='1')
    env['PATH'] = str(BASE/'toolchain/bin') + os.pathsep + env.get('PATH', '')
    minimum, process, lock = None, None, None
    started = time.monotonic()
    try:
        output.mkdir(parents=True, exist_ok=False)
        lock = (ROOT/'state/model-library-gpu-probe.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report['before'] = before = state()
        minimum = before['free_gpu_mib']
        if before['active_ace_jobs'] or minimum < 12288:
            report.update(status='blocked', reason='ACE active or less than12GiB free; no child started')
            raise RuntimeError('Admission denied')
        logpath.parent.mkdir(parents=True, exist_ok=True)
        with logpath.open('wb') as log:
            process = subprocess.Popen([str(ROOT/'envs/sheetsage2/bin/python'), str(Path(__file__).resolve()),
                '--worker', str(output)], env=env, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                current = state()
                minimum = min(minimum, current['free_gpu_mib'])
                if current['active_ace_jobs'] or current['free_gpu_mib'] < 1024 or time.monotonic() - started > DEADLINE:
                    report.update(status='interrupted', reason='ACE activity, VRAM reserve, or deadline', observed=current)
                    stop_owned(process)
                    break
                time.sleep(0.5)
        if report['status'] == 'running':
            report['status'] = 'passed' if process.returncode == 0 and (output/'result-receipt.json').is_file() else 'failed'
    except BaseException as error:
        report['error_type'] = type(error).__name__
        if report['status'] == 'running':
            report['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
    finally:
        try:
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
        if (output/'result-receipt.json').is_file():
            try:
                report['result'] = json.loads((output/'result-receipt.json').read_text())
            except (OSError, UnicodeError, ValueError) as error:
                report.update(status='failed', result_error_type=type(error).__name__)
        try:
            write(output/'guard-receipt.json', report)
        except BaseException as error:
            report.update(status='failed', receipt_write_error_type=type(error).__name__)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            raise
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-slot', action='store_true')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if os.name != 'posix' or not ROOT.is_dir():
        raise RuntimeError('Cloud-only evaluation')
    if args.worker:
        return worker(args.worker)
    if not args.approved_slot:
        raise RuntimeError('Parent-authorized exclusive GPU slot required')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8]
    output = ROOT/'results/evaluations/real_audio_20261106'/('sheetsage2-' + stamp)
    logpath = ROOT/'logs/evaluations/real_audio_20261106'/('sheetsage2-' + stamp + '.log')
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGHUP, interrupt)
    return run_guard(output, logpath)


if __name__ == '__main__':
    sys.exit(main())
