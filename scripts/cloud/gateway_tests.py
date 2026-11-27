"""Isolated queue/HTTP contract tests; fake worker is NOT an inference test."""
import hashlib
import json
import math
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from gateway import Queue, handler_for, validate_request
from backup_data import snapshot_generation_queue


def request(job_id="sample"):
    return {"request_id": job_id, "kind": "generate", "model_id": "ace-step-1.5-xl-turbo", "prompt": "piano",
            "lyrics": "", "instrumental": True, "duration_seconds": 12, "bpm": 120, "time_signature": "4/4", "seed": 1}


def fake_worker(item, directory, phase, cancelled):
    phase("running")
    audio = directory / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x01\x00" * 800)
    return {"artifacts": [{"id": "audio.wav", "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(), "bytes": audio.stat().st_size,
                           "sample_rate": 8000, "channels": 1, "duration_seconds": 0.1}], "model": {"id": "explicit-test-fake"}, "parameters": item}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = Queue(self.temp.name, fake_worker)

    def tearDown(self):
        self.queue.close()
        self.queue.db.close()
        self.temp.cleanup()

    def wait_terminal(self, job_id):
        for _ in range(100):
            job = self.queue.get(job_id)
            if job["status"] in ("ready", "failed", "cancelled"):
                return job
            time.sleep(0.02)
        self.fail("Worker did not finish")

    def test_idempotency_survives_restart_and_rejects_changed_parameters(self):
        self.assertEqual(self.queue.submit(request())[0], 202)
        self.assertEqual(self.queue.submit(request())[0], 200)
        changed = request()
        changed["seed"] = 2
        self.assertEqual(self.queue.submit(changed)[0], 409)
        other = Queue(self.temp.name, fake_worker)
        try:
            self.assertEqual(other.get("sample")["status"], "interrupted")
            self.assertEqual(other.submit(request())[1]["status"], "interrupted")
        finally:
            other.close()
            other.db.close()

    def test_queue_limit_and_queued_cancel(self):
        for i in range(16):
            self.assertEqual(self.queue.submit(request(f"job-{i}"))[0], 202)
        self.assertEqual(self.queue.submit(request("overflow"))[0], 429)
        self.assertEqual(self.queue.cancel("job-0")["status"], "cancelled")
        self.assertEqual(self.queue.submit(request("overflow"))[0], 202)

    def test_cancel_running_never_publishes_ready(self):
        started, released = threading.Event(), threading.Event()
        def blocking_worker(*args):
            started.set()
            released.wait(2)
            return fake_worker(*args)
        self.queue.generator = blocking_worker
        self.queue.start()
        self.queue.submit(request())
        self.assertTrue(started.wait(2))
        self.assertEqual(self.queue.cancel("sample")["status"], "cancelling")
        released.set()
        result = self.wait_terminal("sample")
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["result"])

    def test_complete_persists_checked_artifact(self):
        self.queue.start()
        self.queue.submit(request())
        result = self.wait_terminal("sample")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.queue.cancel("sample")["status"], "ready")
        self.assertTrue((Path(self.temp.name) / "jobs/generation/sample/result.json").is_file())

    def test_failure_is_visible_and_next_job_runs(self):
        def worker(item, *args):
            if item["request_id"] == "bad":
                raise RuntimeError("test failure")
            return fake_worker(item, *args)
        self.queue.generator = worker
        self.queue.start()
        self.queue.submit(request("bad"))
        self.queue.submit(request("good"))
        self.assertEqual(self.wait_terminal("bad")["status"], "failed")
        self.assertEqual(self.wait_terminal("good")["status"], "ready")

    def test_invalid_values_rejected(self):
        invalid = [("duration_seconds", float("nan")), ("bpm", float("inf")), ("seed", True),
                   ("request_id", "../path"), ("time_signature", "7/8"), ("model_id", "anything"), ("prompt", " "),
                   ("duration_seconds", 121), ("lyrics", "contradicts instrumental"), ("src_audio", "/etc/passwd")]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                item = request()
                item[key] = value
                with self.assertRaises(ValueError):
                    validate_request(item)

    def test_unwritable_job_directory_does_not_kill_worker(self):
        Path(self.temp.name, 'jobs/generation/bad').write_text('blocks directory')
        self.queue.start()
        self.queue.submit(request('bad'))
        self.queue.submit(request('good'))
        self.assertEqual(self.wait_terminal('bad')['status'], 'failed')
        self.assertEqual(self.wait_terminal('good')['status'], 'ready')

    def test_backup_includes_wal_and_rejects_active_jobs(self):
        import sqlite3
        from contextlib import closing
        self.queue.submit(request())
        with self.assertRaisesRegex(RuntimeError, "Finish or cancel"):
            snapshot_generation_queue(Path(self.temp.name))
        self.queue.cancel("sample")
        snapshot_generation_queue(Path(self.temp.name))
        with closing(sqlite3.connect(Path(self.temp.name) / "manifests/generation-queue.sqlite3")) as saved:
            self.assertEqual(saved.execute("SELECT id,status FROM jobs").fetchall(), [("sample", "cancelled")])
            self.assertEqual(saved.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_http_protocol_and_artifact_download(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.queue))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.queue.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(url + "/health") as response:
                self.assertEqual(json.load(response)["service"], "emusician-generation")
            post = urllib.request.Request(url + "/jobs", data=json.dumps(request()).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(post) as response:
                self.assertEqual(response.status, 202)
            ready = self.wait_terminal("sample")
            with urllib.request.urlopen(url + "/jobs/sample/artifacts/audio.wav") as response:
                self.assertEqual(hashlib.sha256(response.read()).hexdigest(), ready["result"]["artifacts"][0]["sha256"])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url + "/jobs/sample/artifacts/../../state/generation.sqlite3")
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
