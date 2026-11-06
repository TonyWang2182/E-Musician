"""Child-local admission policy; no Torch imports, registry writes or GPU loads.

The policy floors are headroom rules, not measured model peak requirements.
Known PCM/output buffers are added from Demucs 4.1.0 apply_model's allocations.
Unknown allocator/workspace peaks still require the parent's runtime guard.
"""
from __future__ import annotations

import ctypes
import math
import sys
from pathlib import Path

from .common import AnalysisError

MIB = 1024 * 1024
GIB = 1024 * MIB
POLICY_FLOORS = {'separate': 4 * GIB, 'transcribe': 2 * GIB, 'beats': 2 * GIB, 'chords': GIB}


def suppress_error_dialogs():
    """Current analysis process only. Native launcher covers pre-Python faults."""
    if sys.platform != 'win32':
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetErrorMode.restype = ctypes.c_uint
    kernel.SetErrorMode.argtypes = [ctypes.c_uint]
    kernel.SetErrorMode.restype = ctypes.c_uint
    kernel.SetErrorMode(kernel.GetErrorMode() | 0x0001 | 0x0002 | 0x8000)


def memory_snapshot():
    if sys.platform == 'win32':
        # GetPerformanceInfo reports pages, not bytes. PhysicalAvailable alone
        # cannot detect exhausted system commit/pagefile (the observed failure).
        class PerformanceInfo(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in (
                'CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
                'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')] + [
                (name, ctypes.c_ulong) for name in ('HandleCount', 'ProcessCount', 'ThreadCount')]
        value = PerformanceInfo()
        value.cb = ctypes.sizeof(value)
        query = ctypes.WinDLL('psapi', use_last_error=True).GetPerformanceInfo
        query.argtypes = [ctypes.POINTER(PerformanceInfo), ctypes.c_ulong]
        query.restype = ctypes.c_int
        if not query(ctypes.byref(value), value.cb):
            raise AnalysisError('resource_probe_failed', 'Cannot check Windows memory headroom. Analysis was not started.')
        return {'available_commit_bytes': max(0, value.CommitLimit-value.CommitTotal) * value.PageSize,
                'available_physical_bytes': value.PhysicalAvailable * value.PageSize,
                'measurement': 'Windows-GetPerformanceInfo'}
    import psutil
    physical = int(psutil.virtual_memory().available)
    return {'available_commit_bytes': physical + int(psutil.swap_memory().free),
            'available_physical_bytes': physical, 'measurement': 'available-RAM-plus-swap-not-Windows-commit'}


def resource_policy(request):
    supplied = request.get('resource_policy', {})
    if not isinstance(supplied, dict) or supplied.get('version', 1) != 1:
        raise AnalysisError('invalid_resource_policy', 'Unsupported analysis resource policy.')
    defaults = {'minimum_available_commit_bytes': POLICY_FLOORS[request['kind']],
                'minimum_available_physical_bytes': 512 * MIB,
                'critical_available_commit_bytes': 512 * MIB, 'critical_grace_ms': 1000}
    for key, default in defaults.items():
        value = supplied.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1024 * GIB:
            raise AnalysisError('invalid_resource_policy', 'Invalid analysis resource policy limit.')
        defaults[key] = max(default, value)  # Requests cannot weaken the child defaults.
    return {'version': 1, **defaults}


def known_buffer_budget(request, entry):
    duration = request['duration_seconds']
    rate = request.get('source', {}).get('sample_rate', 192000)
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 8000 <= rate <= 192000:
        rate = 192000
    decoded = math.ceil(duration * rate) * 2 * 4  # bounded stereo float32 source
    if request['kind'] != 'separate':
        return {'decoded_pcm_bytes': decoded, 'known_buffer_bytes': 2 * decoded}
    frames = math.ceil((duration + 1) * 44100)  # Demucs shift padding up to 1 second
    mix = frames * 2 * 4
    outputs = mix * request['parameters']['stems']
    # split's full CPU output + second retained shift output in quality mode;
    # decoded PCM, resample/contiguous/shift copies and sum_weight are separate.
    copies = 2 if request['parameters']['quality'] == 'quality' else 1
    path = Path(entry.get('model_path', ''))
    weights = path.stat().st_size if path.is_file() else 0
    return {'decoded_pcm_bytes': decoded, 'separation_output_bytes': outputs,
            'simultaneous_output_buffers': copies, 'checkpoint_load_budget_bytes': 2 * weights,
            'known_buffer_bytes': decoded + 4 * mix + copies * outputs + frames * 4 + 2 * weights}


def check_admission(request, entry, snapshot=None):
    policy, buffers = resource_policy(request), known_buffer_budget(request, entry)
    snapshot = memory_snapshot() if snapshot is None else snapshot
    required = policy['minimum_available_commit_bytes'] + buffers['known_buffer_bytes']
    report = {'policy': policy, 'buffers': buffers, 'snapshot': snapshot,
              'required_available_commit_bytes': required, 'model_peak_guaranteed': False}
    if snapshot['available_commit_bytes'] < required or snapshot['available_physical_bytes'] < policy['minimum_available_physical_bytes']:
        error = AnalysisError('insufficient_memory',
            f"Analysis needs {required/GIB:.2f} GiB of available system memory headroom; "
            f"currently {snapshot['available_commit_bytes']/GIB:.2f} GiB commit and "
            f"{snapshot['available_physical_bytes']/GIB:.2f} GiB physical memory are available. "
            'Close other memory-heavy apps and retry a shorter range. The project was not changed.')
        error.resource_report = report
        raise error
    return report


def memory_error(error):
    text = str(error).lower()
    return isinstance(error, MemoryError) or any(term in text for term in (
        'out of memory', 'not enough memory', 'cannot allocate memory', 'defaultcpuallocator',
        'paging file is too small', 'winerror 1455'))


def run_inference_once(operation, task='Analysis'):
    """Never move/reload a model after OOM while its failed frames stay alive."""
    try:
        return operation()
    except (RuntimeError, MemoryError) as error:
        if not memory_error(error):
            raise
        raise AnalysisError('out_of_memory',
            f'{task} stopped because GPU or system memory ran out. No automatic CPU retry was started. '
            'Close other memory-heavy apps and retry. The project was not changed.') from error


def check_gpu_headroom(torch, entry):
    free, total = torch.cuda.mem_get_info()
    observed = entry.get('probe_peak_cuda_reserved_bytes', 0)
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed < 0:
        observed = 0
    # Admission hint from this installation's real probe, plus 256 MiB reserve.
    # It is not a general Demucs guarantee; runtime OOM still terminates the job.
    required = int(observed) + 256 * MIB
    if free < required:
        raise AnalysisError('insufficient_gpu_memory',
            f'GPU memory is low ({free/MIB:.0f} MiB free; admission budget {required/MIB:.0f} MiB). '
            'Close other GPU apps and retry. No CPU retry was started.')
    return {'available_gpu_bytes': free, 'total_gpu_bytes': total, 'gpu_admission_bytes': required,
            'gpu_budget_basis': 'registered-probe-reserved-plus-256MiB-not-a-peak-guarantee'}


class MemoryGuard:
    def __init__(self, request):
        self.policy = resource_policy(request)

    def checkpoint(self):
        snapshot = memory_snapshot()
        if snapshot['available_commit_bytes'] < self.policy['critical_available_commit_bytes']:
            raise AnalysisError('memory_pressure', 'Analysis stopped to protect the DAW: system memory is critically low. '
                                'Close other memory-heavy apps and retry. The project was not changed.')
