"""Real owned-process cleanup only; Linux CPU tests, no model or GPU activity."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/cloud'))
from compute.supervisor import stop_owned


def active(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


@unittest.skipUnless(sys.platform=='linux','Actual process-group tests require Linux')
class LinuxCleanupTests(unittest.TestCase):
    def test_orphan_decoder_ignoring_term_is_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile=Path(temporary)/'child.pid'
            token=uuid.uuid4().hex
            code="""import os,sys,signal,time
child=os.fork()
if child:
    os._exit(0)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
open(sys.argv[1],'w').write(str(os.getpid()))
time.sleep(60)
"""
            process=subprocess.Popen([sys.executable,'-c',code,str(pidfile)],start_new_session=True,
                env={**os.environ,'EMUSICIAN_COMPUTE_OWNER':token},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process.compute_token=token
            try:
                process.wait(timeout=5)
                deadline=time.monotonic()+5
                while (not pidfile.exists() or not pidfile.read_text()) and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(pidfile.is_file())
                child=int(pidfile.read_text())
                stop_owned(process)
                deadline=time.monotonic()+2
                while active(child) and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse(active(child))
            finally:
                stop_owned(process)

    def test_parent_death_stops_worker_group(self):
        import compute.worker
        package_root=str(Path(compute.worker.__file__).resolve().parent.parent)
        with tempfile.TemporaryDirectory() as temporary:
            pidfile=Path(temporary)/'worker.pid'
            child_code="from compute.worker import bind_parent; import os,sys,time; bind_parent(os.getppid()); open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(60)"
            parent_code="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],start_new_session=True); time.sleep(60)"
            parent=subprocess.Popen([sys.executable,'-c',parent_code,child_code,str(pidfile)],start_new_session=True,
                env={**os.environ,'PYTHONPATH':package_root},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child=None
            try:
                deadline=time.monotonic()+5
                while (not pidfile.exists() or not pidfile.read_text()) and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(pidfile.is_file());child=int(pidfile.read_text())
                parent.terminate();parent.wait(timeout=5)
                deadline=time.monotonic()+5
                while active(child) and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse(active(child))
            finally:
                if parent.poll() is None:parent.kill();parent.wait(timeout=5)
                if child is not None and active(child):os.killpg(child,signal.SIGKILL)


if __name__=='__main__':unittest.main()
