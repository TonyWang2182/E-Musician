"""Single GPU owner, bounded resource admission and owned-child termination."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid
from .normalize import validate_result
from .protocol import SPECS, atomic_json, read_json

GIB = 1024**3


def resources():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key == 'MemAvailable':
            values['host_available_bytes'] = int(value.split()[0]) * 1024
    limit = Path('/sys/fs/cgroup/memory.max')
    current = Path('/sys/fs/cgroup/memory.current')
    if limit.is_file() and current.is_file() and limit.read_text().strip() != 'max':
        values['host_available_bytes'] = min(values['host_available_bytes'],
            max(0, int(limit.read_text()) - int(current.read_text())))
    raw = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True, timeout=5)
    values['gpu_free_bytes'] = int(raw.strip().splitlines()[0]) * 1024**2
    return values


def owned_group_remains(process):
    token = getattr(process, 'compute_token', None)
    if not isinstance(token, str):
        return False
    needle = ('EMUSICIAN_COMPUTE_OWNER=' + token).encode()
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == process.pid and int(fields[3]) == process.pid:
                if needle in (entry / 'environ').read_bytes().split(b'\0'):
                    return True
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return False


def stop_owned(process):
    """Only sessions created by this supervisor; tolerate natural-exit races."""
    if process is None:
        return
    alive = process.poll() is None
    # Descendants retain a unique per-launch ownership token. If the leader
    # exited, only a group with that token can be signalled; PID reuse alone is
    # insufficient. This also handles a decoder outliving its Python parent.
    if alive or owned_group_remains(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            if alive:
                process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while owned_group_remains(process) and time.monotonic() < deadline:
            time.sleep(.05)
        if owned_group_remains(process):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class Supervisor:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        self.shutdown = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='single-cloud-compute', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.shutdown.set()
        self.thread.join(timeout=20)
        if self.thread.is_alive():
            raise RuntimeError('Compute supervisor did not stop within cleanup deadline')

    def loop(self):
        import fcntl
        while not self.shutdown.is_set():
            lock = (self.store.state / 'model-library-gpu-probe.lock').open('a')
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.shutdown.wait(.5); continue
                job = self.store.next_job()
                if job is None:
                    self.shutdown.wait(.25); continue
                self.execute(job)
            except Exception as error:
                print('Compute supervisor diagnostic: ' + type(error).__name__, flush=True)
                self.shutdown.wait(.5)
            finally:
                lock.close()

    def execute(self, job):
        job_id = job['id']; request = job['request']; spec = SPECS[request['model_id']]
        directory = self.store.jobs / job_id
        process = None; started = time.monotonic()
        receipt = {'job_id': job_id, 'status': 'loading', 'model_id': request['model_id'],
                   'started_unix': time.time(), 'timeout_seconds': spec['timeout'], 'inference_started': False}
        status = 'failed'; error = None; result = None
        try:
            if not self.catalog.provider(request['model_id'])['available']:
                raise RuntimeError('Requested cloud model is unavailable')
            before = resources(); receipt['before'] = before
            if before['gpu_free_bytes'] < (spec['gpu_gib'] + 1) * GIB or before['host_available_bytes'] < 8 * GIB:
                raise RuntimeError('Insufficient cloud GPU or host-memory headroom; no model started')
            if shutil.disk_usage(directory).free < 3 * GIB:
                raise RuntimeError('Insufficient cloud disk reserve; no model started')
            if self.store.get(job_id)['status'] == 'cancelling' or self.shutdown.is_set():
                status = 'cancelled' if not self.shutdown.is_set() else 'interrupted'
                return
            environment = os.environ.copy()
            # An offline model must not inherit private download credentials.
            for key in list(environment):
                if any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
                    environment.pop(key, None)
            environment.pop('CUDA_VISIBLE_DEVICES', None)
            environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                HF_HUB_DISABLE_TELEMETRY='1', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                TOKENIZERS_PARALLELISM='false', YUE2_COMPILE='0', PYTHONUNBUFFERED='1')
            ownership = uuid.uuid4().hex
            environment['EMUSICIAN_COMPUTE_OWNER'] = ownership
            if request['model_id'] == 'sheetsage2':
                base = self.store.root / 'workspace/models/sheetsage2'
                environment['HF_HOME'] = str(base / 'hf')
                environment['PATH'] = str(base / 'toolchain/bin') + os.pathsep + environment.get('PATH', '')
            logpath = directory / 'worker.log'
            with logpath.open('xb') as log:
                process = subprocess.Popen([str(self.catalog.python(request['model_id'])),
                    str(Path(__file__).with_name('worker.py')), '--root', str(self.store.root),
                    '--job', job_id, '--parent-pid', str(os.getpid())], stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
                process.compute_token = ownership
                receipt.update(pid=process.pid, inference_started=True)
                atomic_json(directory / 'attempt.json', receipt)
                while process.poll() is None:
                    current_status = self.store.get(job_id)['status']
                    if current_status == 'cancelling' or self.shutdown.is_set():
                        status = 'cancelled' if current_status == 'cancelling' else 'interrupted'
                        stop_owned(process); break
                    if time.monotonic() - started > spec['timeout']:
                        raise TimeoutError('Cloud task exceeded its bounded inference deadline')
                    state = resources(); receipt['last_resources'] = state
                    if state['gpu_free_bytes'] < 512 * 1024**2 or state['host_available_bytes'] < 2 * GIB:
                        raise RuntimeError('Cloud GPU/host-memory reserve reached; this task was stopped')
                    if shutil.disk_usage(directory).free < 512 * 1024**2 or logpath.stat().st_size > 64 * 1024**2:
                        raise RuntimeError('Cloud disk/log reserve reached; this task was stopped')
                    progress_path = directory / 'progress.json'
                    if progress_path.is_file():
                        progress = read_json(progress_path, 4096)
                        if progress.get('phase') in ('loading', 'running', 'postprocessing'):
                            self.store.update(job_id, progress['phase'])
                    self.shutdown.wait(.5)
            if status not in ('cancelled', 'interrupted'):
                if process.returncode != 0:
                    worker_error = directory / 'worker-error.json'
                    detail = read_json(worker_error, 8192).get('error', '') if worker_error.is_file() else 'Process exited without a result'
                    raise RuntimeError(str(detail)[:800])
                self.store.update(job_id, 'postprocessing')
                result = validate_result(read_json(directory / 'output/result.json'), directory / 'output', request)
                status = 'ready'
        except BaseException as exc:
            error = type(exc).__name__ + ': ' + str(exc)[:800]
            status = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
        finally:
            try:
                stop_owned(process)
            except BaseException as exc:
                status, error = 'failed', 'Owned worker cleanup failed: ' + type(exc).__name__
            receipt.update(status=status, error=error, elapsed_seconds=time.monotonic()-started,
                exit_code=process.returncode if process is not None else None, finished_unix=time.time())
            try:
                atomic_json(directory / 'attempt.json', receipt)
            except BaseException as exc:
                status, error, result = 'failed', 'Task receipt could not be persisted: ' + type(exc).__name__, None
                print('Terminal compute receipt failure for ' + job_id, flush=True)
            # Store.update serializes cancellation against publication. A late
            # cancellation turns ready/failed into cancelled in the same lock.
            self.store.update(job_id, status, result=result if status == 'ready' else None, error=error)
