"""Transient native read-busy handling; no model/API or physical audio calls."""
import io
import queue
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_client import Client, ControlError, retry_busy_read
from music_agent.bridge import BridgeError, DawBridge
from music_agent.embedded import SocketClient
from test_music_agent_embedded import NativeFixture


class BusyReadTests(unittest.TestCase):
    request = {"command": "get_snapshot", "request_id": "same-read"}
    busy = {"status": "busy", "request_id": "same-read"}

    def exercise(self, responses, request=None, timeout=0.1):
        now = [0.0]
        budgets = []
        def exchange(remaining):
            budgets.append(remaining)
            value = responses[min(len(budgets) - 1, len(responses) - 1)]
            if isinstance(value, Exception): raise value
            return value
        result = retry_busy_read(request or self.request, exchange, timeout,
                                 clock=lambda: now[0], pause=lambda delay: now.__setitem__(0, now[0] + delay))
        return result, budgets, now[0]

    def test_busy_read_repeats_under_original_deadline(self):
        done = {"status": "completed", "request_id": "same-read", "result": {}}
        result, budgets, elapsed = self.exercise([self.busy, self.busy, done])
        self.assertEqual(result, done)
        self.assertEqual(len(budgets), 3)
        self.assertGreater(budgets[0], budgets[1])
        self.assertGreater(budgets[1], budgets[2])
        self.assertLessEqual(elapsed, 0.1)

    def test_exhaustion_returns_definite_busy_without_extending_deadline(self):
        result, budgets, elapsed = self.exercise([self.busy])
        self.assertEqual(result, self.busy)
        self.assertEqual(elapsed, 0.1)
        self.assertEqual(len(budgets), 4)

    def test_native_effect_read_is_explicitly_retryable(self):
        done = {"status": "completed", "request_id": "same-read", "result": {"type": "eq8"}}
        result, budgets, _ = self.exercise([self.busy, done],
            {"command": "get_native_effect", "request_id": "same-read", "args": {"track_id": "t", "device_id": "eq"}})
        self.assertEqual(result, done)
        self.assertEqual(len(budgets), 2)

    def test_writes_and_unknown_commands_never_retry(self):
        for command in ("add_plugin", "set_input_monitor", "save_project", "get_unknown"):
            with self.subTest(command=command):
                result, budgets, _ = self.exercise([self.busy], {"command": command, "request_id": "same-read"})
                self.assertEqual(result, self.busy)
                self.assertEqual(len(budgets), 1)

    def test_mismatched_busy_reply_is_not_discarded(self):
        wrong = {"status": "busy", "request_id": "different-read"}
        result, budgets, _ = self.exercise([wrong])
        self.assertEqual(result, wrong)
        self.assertEqual(len(budgets), 1)

    def test_transport_failure_never_retries(self):
        with self.assertRaisesRegex(ControlError, "ambiguous"):
            self.exercise([ControlError("ambiguous transport timeout")])

    def test_real_stdio_client_uses_same_retry_policy(self):
        client = Client.__new__(Client)
        client.timeout = 0.1
        client.process = types.SimpleNamespace(stdin=io.BytesIO())
        client.responses = queue.Queue()
        client.responses.put(self.busy)
        client.responses.put({"status": "completed", "request_id": "same-read", "result": {}})
        self.assertEqual(client.raw(self.request)["status"], "completed")
        self.assertEqual(len(client.process.stdin.getvalue().splitlines()), 2)

    def test_embedded_bridge_busy_then_success_preserves_request_identity(self):
        count = [0]
        def respond(request):
            if "auth" in request: return NativeFixture.default(request)
            count[0] += 1
            return {"status": "busy" if count[0] < 3 else "completed",
                    "request_id": request["request_id"], "result": {}}
        with NativeFixture(respond) as host:
            client = SocketClient(host.session, timeout=0.2)
            try:
                bridge = DawBridge(client=client, embedded=True)
                self.assertEqual(bridge._request({"command": "get_snapshot"})["status"], "completed")
                self.assertTrue(bridge.connected)
                reads = [r for r in host.requests if "command" in r]
                self.assertEqual(len(reads), 3)
                self.assertEqual(len({r["request_id"] for r in reads}), 1)
            finally: client.close()

    def test_embedded_exhaustion_keeps_stream_usable_and_write_is_not_repeated(self):
        def respond(request):
            if "auth" in request: return NativeFixture.default(request)
            return {"status": "busy", "request_id": request["request_id"], "error": "Device loading"}
        with NativeFixture(respond) as host:
            client = SocketClient(host.session, timeout=0.06)
            try:
                bridge = DawBridge(client=client, embedded=True)
                with self.assertRaises(BridgeError): bridge._request({"command": "get_snapshot"})
                self.assertTrue(bridge.connected)
                self.assertFalse(client.closed)
                with self.assertRaises(BridgeError): bridge._request({"command": "add_plugin"})
                self.assertEqual(sum(r.get("command") == "add_plugin" for r in host.requests), 1)
            finally: client.close()


if __name__ == "__main__": unittest.main()
