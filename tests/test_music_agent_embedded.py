"""Strict host-owned loopback transport fixtures; no DAW, provider or real key."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_client import ControlError
from music_agent.embedded import MAX_BYTES, SocketClient, load_session
from music_agent.bridge import DawBridge, BridgeError

TOKEN = "ab" * 32  # Synthetic protocol capability, never a provider credential.


class NativeFixture:
    """Listening host remains alive when a client disconnects."""
    def __init__(self, responder=None):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.responder = responder or self.default
        self.requests = []
        self.errors = []
        self.connections = []
        self.stop = threading.Event()
        self.disconnected = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    @staticmethod
    def default(request):
        if "auth" in request:
            return {"status": "authenticated" if request["auth"] == TOKEN else "denied"}
        return {"request_id": request.get("request_id"), "status": "completed", "result": {"value": request.get("value")}}

    def serve(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections.append(connection)
            try:
                with connection, connection.makefile("rb") as stream:
                    while not self.stop.is_set():
                        line = stream.readline(MAX_BYTES + 2)
                        if not line:
                            break
                        request = json.loads(line)
                        self.requests.append(request)
                        response = self.responder(request)
                        if response is None:
                            continue  # Deliberately unanswered request for timeout tests.
                        encoded = response if isinstance(response, bytes) else (json.dumps(response) + "\n").encode()
                        connection.sendall(encoded)
                        if not encoded.endswith(b"\n"):
                            break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            except Exception as exc:
                self.errors.append(exc)
            finally:
                self.disconnected.set()

    @property
    def session(self):
        return {"protocol": 1, "port": self.port, "token": TOKEN}

    def close(self):
        self.stop.set()
        for connection in self.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise AssertionError("Synthetic host did not terminate")
        if self.errors:
            raise AssertionError(self.errors)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="em-agent-session-test-")
        self.path = Path(self.directory.name) / "host.session.json"
        self.valid = {"protocol": 1, "port": 12345, "token": TOKEN,
                      "ready_path": str(self.path.with_name("host.session.ready.json"))}

    def tearDown(self):
        self.directory.cleanup()

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8-sig")

    def test_valid_bom_session(self):
        self.write(self.valid)
        self.assertEqual(load_session(self.path), self.valid)

    def test_protocol_port_and_capability_types_strict(self):
        cases = [("protocol", True), ("protocol", 1.0), ("protocol", 2),
                 ("port", True), ("port", 0), ("port", 65536), ("port", "12345"),
                 ("token", None), ("token", "ab"), ("token", "x" * 64),
                 ("ready_path", None), ("ready_path", "")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.write({**self.valid, key: value})
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_missing_extra_and_nonobject_rejected(self):
        for value in (None, [], 1, "session", {**self.valid, "extra": 1},
                      {k: v for k, v in self.valid.items() if k != "token"}):
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_readiness_cannot_escape_or_change_name(self):
        for value in (str(self.path.parent / "other.ready.json"),
                      str(self.path.parent.parent / "host.session.ready.json")):
            with self.subTest(value=value):
                self.write({**self.valid, "ready_path": value})
                with self.assertRaises(ValueError):
                    load_session(self.path)

    def test_size_duplicate_and_invalid_json_rejected(self):
        duplicate = json.dumps(self.valid)[:-1] + ',"protocol":1}'
        for value in ("", " " * 4097, "{", duplicate,
                      json.dumps(self.valid).replace('"protocol": 1', '"protocol": NaN'),
                      json.dumps(self.valid).replace('"port": 12345', '"port": 1e400')):
            with self.subTest(size=len(value)):
                self.path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_session(self.path)


class SocketTests(unittest.TestCase):
    def test_authenticated_roundtrip_then_close_leaves_host_alive(self):
        with NativeFixture() as host:
            client = SocketClient(host.session)
            self.assertTrue(client.embedded)
            self.assertEqual(client.raw({"request_id": "one", "value": "音符"})["result"]["value"], "音符")
            client.close()
            client.close()
            self.assertTrue(host.disconnected.wait(1))
            self.assertTrue(host.thread.is_alive())
            self.assertNotEqual(host.listener.fileno(), -1)
            with self.assertRaises(ControlError):
                client.raw({"request_id": "after-close"})
            second = SocketClient(host.session)
            try:
                self.assertEqual(second.raw({"request_id": "two"})["request_id"], "two")
            finally:
                second.close()
            self.assertEqual(host.requests[0], {"auth": TOKEN})
            self.assertFalse(any(r.get("command") in ("shutdown", "close", "quit") for r in host.requests))

    def test_auth_rejection_and_failed_init_cleanup(self):
        with NativeFixture() as host:
            client = SocketClient.__new__(SocketClient)
            with self.assertRaisesRegex(ControlError, "authentication failed"):
                client.__init__({**host.session, "token": "cd" * 32})
            client.close()
            self.assertTrue(client.closed)
            self.assertTrue(host.disconnected.wait(1))
            self.assertEqual(len(host.requests), 1)

    def test_duplicate_auth_status_cannot_override_denied(self):
        with NativeFixture(lambda _: b'{"status":"denied","status":"authenticated"}\n') as host:
            with self.assertRaises(ControlError):
                SocketClient(host.session)
            self.assertTrue(host.disconnected.wait(1))

    def test_invalid_reply_poisoned_and_never_reused(self):
        replies = [b'[]\n', b'{"status":\n', b'\xff\n',
                   b'{"value":NaN}\n', b'{"value":Infinity}\n', b'{"value":1e400}\n',
                   b'{"status":"failed","status":"completed"}\n',
                   b'{"status":"completed"}', b'{"padding":"' + b'x' * MAX_BYTES + b'"}\n',
                   b'{"value":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}\n']
        for reply in replies:
            with self.subTest(prefix=reply[:40], size=len(reply)):
                with NativeFixture(lambda request: NativeFixture.default(request) if "auth" in request else reply) as host:
                    client = SocketClient(host.session)
                    with self.assertRaisesRegex(ControlError, "no automatic retry"):
                        client.raw({"request_id": "first"})
                    self.assertTrue(client.closed)
                    with self.assertRaises(ControlError):
                        client.raw({"request_id": "second"})
                    client.close()
                    self.assertTrue(host.disconnected.wait(1))
                    self.assertEqual([r.get("request_id") for r in host.requests], [None, "first"])

    def test_timeout_poison_and_bridge_remains_disconnected(self):
        with NativeFixture(lambda request: NativeFixture.default(request) if "auth" in request else None) as host:
            client = SocketClient(host.session, timeout=0.06)
            bridge = DawBridge(client=client)
            self.assertTrue(bridge.embedded)
            started = time.monotonic()
            with self.assertRaises(BridgeError):
                bridge.snapshot()
            self.assertLess(time.monotonic() - started, 1)
            self.assertFalse(bridge.connected)
            self.assertTrue(client.closed)
            with self.assertRaises(BridgeError):
                bridge.snapshot()
            self.assertTrue(host.disconnected.wait(1))
            self.assertEqual(len(host.requests), 2)  # One auth and one request, never a retry.
            client.close()

    def test_locally_invalid_request_does_not_send_or_poison(self):
        with NativeFixture() as host:
            client = SocketClient(host.session)
            try:
                for request in ({"padding": "x" * MAX_BYTES}, {"value": float("nan")}, {"value": object()}):
                    with self.assertRaises(ControlError):
                        client.raw(request)
                self.assertFalse(client.closed)
                self.assertEqual(host.requests, [{"auth": TOKEN}])
                self.assertEqual(client.raw({"request_id": "valid"})["status"], "completed")
            finally:
                client.close()

    def test_brackets_and_escaped_quotes_in_text_are_not_nesting(self):
        with NativeFixture() as host:
            client = SocketClient(host.session)
            try:
                value = '[[["quoted"\\]]]音符' * 1000
                self.assertEqual(client.raw({"request_id": "text", "value": value})["result"]["value"], value)
            finally:
                client.close()

    def test_concurrent_raw_calls_preserve_response_pairing(self):
        with NativeFixture() as host:
            client = SocketClient(host.session)
            results, errors = [], []
            def call(index):
                try:
                    result = client.raw({"request_id": str(index), "value": index})
                    results.append((result["request_id"], result["result"]["value"]))
                except Exception as exc:
                    errors.append(exc)
            workers = [threading.Thread(target=call, args=(i,)) for i in range(8)]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=2)
                self.assertFalse(any(worker.is_alive() for worker in workers))
                self.assertEqual(errors, [])
                self.assertEqual(sorted(results), [(str(i), i) for i in range(8)])
            finally:
                client.close()

    def test_invalid_timeouts_fail_before_connect(self):
        for timeout in (0, -1, True, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                client = SocketClient.__new__(SocketClient)
                with self.assertRaises(ValueError):
                    client.__init__({"port": 1, "token": TOKEN}, timeout=timeout)
                client.close()

    def test_idle_native_eof_is_detected_without_rpc(self):
        with NativeFixture() as host:
            client = SocketClient(host.session)
            self.assertTrue(client.is_alive())
            for connection in host.connections:
                connection.shutdown(socket.SHUT_RDWR)
            deadline = time.monotonic() + 1
            while client.is_alive() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertFalse(client.is_alive())
            self.assertTrue(client.closed)
            self.assertEqual(host.requests, [{"auth": TOKEN}])
            self.assertTrue(host.thread.is_alive())
            client.close()

    def test_liveness_probe_does_not_block_or_consume_active_reply(self):
        received, release = threading.Event(), threading.Event()
        def respond(request):
            if "auth" not in request:
                received.set()
                if not release.wait(2):
                    raise AssertionError("Active reply fixture was not released")
            return NativeFixture.default(request)
        with NativeFixture(respond) as host:
            client = SocketClient(host.session)
            replies, errors = [], []
            def call():
                try:
                    replies.append(client.raw({"request_id": "active", "value": 42}))
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=call)
            thread.start()
            try:
                self.assertTrue(received.wait(1))
                started = time.monotonic()
                for _ in range(10):
                    self.assertTrue(client.is_alive())
                self.assertLess(time.monotonic() - started, 0.5)
                release.set()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(replies, [{"request_id": "active", "status": "completed", "result": {"value": 42}}])
                self.assertTrue(client.is_alive())
            finally:
                release.set()
                client.close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
