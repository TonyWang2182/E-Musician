"""One job in one existing model environment. The parent owns its process group."""
from __future__ import annotations
import argparse
import ctypes
import os
from pathlib import Path
import signal
import sys
import time
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compute import adapters
from compute.catalog import Catalog
from compute.normalize import finish_summary, validate_result
from compute.protocol import SPECS, atomic_json, digest, identifier, read_json, validate_request, wav_info


def bind_parent(parent_pid):
    if sys.platform != 'linux' or os.getpgrp() != os.getpid():
        raise RuntimeError('Workers require a dedicated Linux process group')
    # This is our own newly created process group, never a service/user group.
    signal.signal(signal.SIGTERM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Unable to establish parent-death cleanup')
    if os.getppid() != parent_pid:
        raise RuntimeError('Supervisor exited before worker admission')


def run(root, job_id):
    root = Path(root).resolve(); identifier(job_id)
    directory = root / 'jobs/compute' / job_id
    request = validate_request(read_json(directory / 'request.json', 32768))
    if request['request_id'] != job_id:
        raise ValueError('Worker job identity mismatch')
    output = directory / 'output'; output.mkdir(exist_ok=False)
    started = time.monotonic()
    def phase(value):
        atomic_json(directory / 'progress.json', {'phase': value, 'elapsed_seconds': time.monotonic()-started})
    phase('loading')
    catalog = Catalog(root)
    manifest = catalog.manifest(request['model_id'])
    integrity = catalog.verify_files(request['model_id'])
    source = None; duration = request['parameters'].get('duration_seconds', 0)
    if 'input' in request:
        source = root / 'assets/compute' / (request['input']['sha256'] + '.wav')
        if source.is_symlink() or digest(source) != request['input']['sha256']:
            raise ValueError('Submitted audio changed before inference')
        info = wav_info(source); duration = info['duration_seconds']
        # A finite streaming validation precedes model loading, retaining no full
        # duplicate waveform merely to check it.
        import numpy as np
        import soundfile as sf
        with sf.SoundFile(source) as stream:
            count = 0
            for block in stream.blocks(blocksize=65536, dtype='float32', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError('Input audio contains NaN or infinity')
                count += len(block)
        if count != info['frames']:
            raise ValueError('Audio decoder did not read all input frames')
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; no implicit CPU retry')
    torch.set_num_threads(2); torch.set_num_interop_threads(1)
    torch.manual_seed(request['parameters'].get('seed', 0))
    budget = SPECS[request['model_id']]['gpu_gib'] * 1024**3
    torch.cuda.set_per_process_memory_fraction(min(.9, budget / torch.cuda.get_device_properties(0).total_memory))
    torch.cuda.reset_peak_memory_stats()
    if request['model_id'] in ('scnet', 'transkun', 'chordmini'):
        result = adapters.mir(root, request, source, output, manifest, duration, phase)
    elif request['model_id'] in ('muscriptor', 'sheetsage2'):
        result = getattr(adapters, request['model_id'])(root, request, source, output, manifest, duration, phase)
    else:
        result = getattr(adapters, 'ace' if request['model_id'].startswith('ace-') else 'yue2')(root, request, output, manifest, phase)
    torch.cuda.synchronize()
    result['metrics'].update(worker_wall_seconds=time.monotonic()-started,
        gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(), gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        gpu=torch.cuda.get_device_name(), torch=torch.__version__, cuda=torch.version.cuda)
    result['worker_script_sha256'] = digest(__file__)
    result['deployment_integrity'] = integrity
    if source:
        result['input'] = {'sha256': request['input']['sha256'], **info}
    edges = result.get('selection_boundary_processing', {})
    if edges.get('selection_edge_clipped_notes') or edges.get('padding_events_excluded_from_candidate'):
        result['warnings'].append('Candidate events were cropped to the submitted selection; original MIDI/events remain unchanged.')
    finish_summary(result); validate_result(result, output, request)
    atomic_json(output / 'result.json', result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    args = parser.parse_args()
    bind_parent(args.parent_pid)
    try:
        run(args.root, args.job)
    except BaseException as error:
        # These are model/runtime errors; no credentials or request prompt are
        # interpolated. Keep the class and bounded message in private job logs.
        receipt = {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)[:1500]}
        try:
            atomic_json(args.root / 'jobs/compute' / identifier(args.job) / 'worker-error.json', receipt)
        finally:
            print(type(error).__name__ + ': ' + str(error)[:1500], file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
