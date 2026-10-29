"""Synthetic loopback security and serialized DAW transport tests; no provider/audio."""
from __future__ import annotations
import copy
import http.client
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from agent_client import ControlError
from music_agent.bridge import DawBridge, BridgeError, public_snapshot
from music_agent.server import AgentServer


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.dirty = False
        self.fail_state = False
        self.fail_plan = False
        self.closed = False
        self.bridge = SimpleNamespace(embedded=False)
    def state(self):
        self.calls.append("state")
        if self.fail_state:
            raise Exception("private internal traceback and file path")
        return {"phase": "idle", "snapshot": {"name": "Synthetic"}}
    def plan_request(self, prompt, scope="selection"):
        if self.fail_plan:
            raise Exception("private internal traceback and file path")
        if scope not in ("selection", "project"):
            raise ValueError("Invalid scope")
        self.calls.append(("plan", prompt, scope))
        return {"phase": "planning"}
    def apply(self, plan_id):
        self.calls.append(("apply", plan_id))
        return {"phase": "applying"}
    def cancel(self):
        self.calls.append("cancel")
        return {"phase": "cancelled"}
    def undo(self):
        self.calls.append("undo")
        return {"phase": "applying"}
    def settings(self, value):
        self.calls.append(("settings", value))
        return {"phase": "idle"}
    def close(self):
        self.calls.append("close")
        if self.dirty:
            raise ValueError("工程仍未保存。请先在 DAW 保存，再关闭助手。")
        self.closed = True


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.server = AgentServer(self.runtime)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
    def request(self, method="GET", path="/api/state", data=None, headers=None, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        values = {"Host": self.server.authority}
        if authenticated:
            values["X-Agent-Token"] = self.server.token
        if data is not None:
            values["Content-Type"] = "application/json"
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
        values.update(headers or {})
        try:
            connection.request(method, path, body=data, headers=values)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()
    def test_bound_only_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.server.launch_url.startswith(self.server.origin + "/#token="))
    def test_no_unauthenticated_state(self):
        status, _, _ = self.request(authenticated=False)
        self.assertEqual(status, 403)
        self.assertEqual(self.runtime.calls, [])
    def test_wrong_token_never_dispatches(self):
        status, _, _ = self.request("POST", "/api/plan", {"prompt": "x"}, {"X-Agent-Token": "wrong"})
        self.assertEqual(status, 403)
        self.assertEqual(self.runtime.calls, [])
    def test_nonascii_token_rejected_cleanly(self):
        status, _, _ = self.request(headers={"X-Agent-Token": "caf\xe9"})
        self.assertEqual(status, 403)
        self.assertEqual(self.runtime.calls, [])
    def test_host_and_origin_checked_even_with_token(self):
        for headers in ({"Host": "localhost:" + str(self.server.server_port)},
                        {"Host": "attacker.test"}, {"Origin": "https://attacker.test"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                status, _, _ = self.request(headers=headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.runtime.calls, [])
    def test_same_origin_state_and_security_headers(self):
        status, headers, body = self.request(headers={"Origin": self.server.origin})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["snapshot"]["name"], "Synthetic")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn(self.server.token.encode(), body)
    def test_cross_origin_preflight_gets_no_cors(self):
        status, headers, _ = self.request("OPTIONS", headers={"Origin": "https://attacker.test"})
        self.assertIn(status, (403, 405, 501))
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.runtime.calls, [])
    def test_json_only_and_no_transfer_encoding(self):
        for headers in ({"Content-Type": "text/plain"}, {"Content-Type": "application/x-www-form-urlencoded"},
                        {"Transfer-Encoding": "chunked"}):
            with self.subTest(headers=headers):
                status, _, _ = self.request("POST", "/api/cancel", b"{}", headers)
                self.assertEqual(status, 415)
        self.assertEqual(self.runtime.calls, [])
    def test_size_limit(self):
        for content_length in ("0", "-1", "32769"):
            with self.subTest(length=content_length):
                status, _, _ = self.request("POST", "/api/cancel", b"{}", {"Content-Length": content_length})
                self.assertEqual(status, 413)
        self.assertEqual(self.runtime.calls, [])
    def test_invalid_json_duplicate_keys_and_numbers(self):
        for data in (b"[]", b"{", b'{"prompt":"a","prompt":"b"}',
                     b'{"model":NaN}', b'{"model":Infinity}', b'{"model":1e400}', b"\xff"):
            with self.subTest(data=data):
                status, _, _ = self.request("POST", "/api/settings", data)
                self.assertEqual(status, 400)
        self.assertEqual(self.runtime.calls, [])
    def test_unknown_path_and_fields(self):
        status, _, _ = self.request(path="/api/missing")
        self.assertEqual(status, 404)
        for path, data in (("/api/missing", {}), ("/api/cancel", {"extra": 1}),
                           ("/api/plan", {"prompt": "x", "shell": "ignored"})):
            with self.subTest(path=path, data=data):
                status, _, _ = self.request("POST", path, data)
                self.assertEqual(status, 400)
        self.assertEqual(self.runtime.calls, [])
    def test_plan_dispatch_is_exact(self):
        status, _, body = self.request("POST", "/api/plan", {"prompt": "把当前片段升高两半音"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["phase"], "planning")
        self.assertEqual(self.runtime.calls, [("plan", "把当前片段升高两半音", "selection")])
    def test_explicit_project_scope_is_forwarded(self):
        status, _, _ = self.request("POST", "/api/plan", {"prompt": "把工程速度改为100", "scope": "project"})
        self.assertEqual(status, 200)
        self.assertEqual(self.runtime.calls, [("plan", "把工程速度改为100", "project")])
    def test_invalid_scope_is_rejected(self):
        for scope in (None, True, [], "all"):
            with self.subTest(scope=scope):
                self.assertEqual(self.request("POST", "/api/plan", {"prompt": "x", "scope": scope})[0], 400)
        self.assertEqual(self.runtime.calls, [])
    def test_unexpected_post_exception_is_generic(self):
        self.runtime.fail_plan = True
        status, _, body = self.request("POST", "/api/plan", {"prompt": "x"})
        self.assertEqual(status, 500)
        self.assertNotIn(b"private internal", body)
        self.assertIn("error", json.loads(body))
    def test_unexpected_state_exception_is_generic(self):
        self.runtime.fail_state = True
        status, _, body = self.request()
        self.assertEqual(status, 500)
        self.assertNotIn(b"private internal", body)
        self.assertIn("error", json.loads(body))
    def test_dirty_project_refuses_shutdown(self):
        self.runtime.dirty = True
        status, _, body = self.request("POST", "/api/shutdown", {"confirm": True})
        self.assertEqual(status, 400)
        self.assertFalse(self.runtime.closed)
        self.assertIn("未保存", json.loads(body)["error"])
        self.assertEqual(self.request()[0], 200)
    def test_shutdown_requires_confirmation(self):
        status, _, _ = self.request("POST", "/api/shutdown", {})
        self.assertEqual(status, 400)
        self.assertFalse(self.runtime.closed)
    def test_embedded_shutdown_never_closes_daw(self):
        self.runtime.bridge.embedded = True
        status, _, body = self.request("POST", "/api/shutdown", {"confirm": True})
        self.assertEqual(status, 400)
        self.assertIn("侧栏", json.loads(body)["error"])
        self.assertFalse(self.runtime.closed)
        self.assertNotIn("close", self.runtime.calls)
        self.assertEqual(self.request()[0], 200)


STATE = {"project_id": "p", "revision": 10, "dirty": False, "bpm": 120,
         "tracks": [{"id": "t", "name": "MIDI", "kind": "instrument", "clips": [
             {"id": "c", "kind": "midi", "note_count": 2}]}]}


class FakeClient:
    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler
        self.closed = False
        self.active = 0
        self.max_active = 0
    def raw(self, request):
        self.calls.append(copy.deepcopy(request))
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            time.sleep(0.002)
            if self.handler:
                return self.handler(request)
            return {"request_id": request["request_id"], "status": "completed", "result": copy.deepcopy(STATE)}
        finally:
            self.active -= 1
    def close(self):
        self.closed = True


class BridgeTests(unittest.TestCase):
    def test_serializes_concurrent_requests(self):
        client = FakeClient()
        bridge = DawBridge(client=client)
        errors = []
        def read():
            try:
                self.assertEqual(bridge.snapshot()["revision"], 10)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=read) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(len(client.calls), 8)
        self.assertEqual(client.max_active, 1)
        self.assertEqual(len({r["request_id"] for r in client.calls}), 8)
    def test_timeout_poison_prevents_next_request(self):
        def fail(_):
            raise ControlError("timeout with private raw_prefix")
        client = FakeClient(fail)
        bridge = DawBridge(client=client)
        with self.assertRaises(BridgeError) as caught:
            bridge.snapshot()
        self.assertNotIn("private raw_prefix", str(caught.exception))
        self.assertFalse(bridge.connected)
        with self.assertRaises(BridgeError):
            bridge.snapshot()
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(client.closed)
    def test_mismatched_or_nondict_response_poisoned(self):
        for result in ({"request_id": "wrong", "status": "completed", "result": STATE}, []):
            with self.subTest(result=result):
                client = FakeClient(lambda _: result)
                bridge = DawBridge(client=client)
                with self.assertRaises(BridgeError):
                    bridge.snapshot()
                self.assertFalse(bridge.connected)
                with self.assertRaises(BridgeError):
                    bridge.snapshot()
                self.assertEqual(len(client.calls), 1)
    def test_conflict_does_not_retry_or_poison_protocol(self):
        def conflict(request):
            return {"request_id": request["request_id"], "status": "conflict", "result": {}}
        client = FakeClient(conflict)
        bridge = DawBridge(client=client)
        with self.assertRaises(BridgeError):
            bridge.apply({"id": "plan", "project_id": "p", "revision": 9, "commands": []})
        self.assertTrue(bridge.connected)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["expected_revision"], 9)
        self.assertEqual(client.calls[0]["request_id"], "plan")
    def test_read_notes_rechecks_revision_and_paginates(self):
        notes = [{"id": "a", "pitch": 60}, {"id": "b", "pitch": 64}]
        def handler(request):
            result = copy.deepcopy(STATE) if request["command"] == "get_snapshot" else {
                "total": 2, "offset": 0, "notes": notes}
            return {"request_id": request["request_id"], "status": "completed", "result": result}
        client = FakeClient(handler)
        bridge = DawBridge(client=client)
        context = public_snapshot(STATE)
        self.assertEqual(bridge.read_notes(context, "c"), notes)
        self.assertEqual(context["clip_notes"]["c"], notes)
        self.assertEqual([r["command"] for r in client.calls], ["get_snapshot", "get_clip_notes", "get_snapshot"])
    def test_read_notes_rejects_stale_context_before_data(self):
        client = FakeClient()
        bridge = DawBridge(client=client)
        context = public_snapshot(STATE)
        context["revision"] = 9
        with self.assertRaises(BridgeError):
            bridge.read_notes(context, "c")
        self.assertEqual([r["command"] for r in client.calls], ["get_snapshot"])
        self.assertEqual(context["clip_notes"], {})
    def test_snapshot_filters_unneeded_root_and_track_fields(self):
        raw = copy.deepcopy(STATE)
        raw["plugin_catalog"] = [{"path": "private"}]
        raw["tracks"][0]["input_device_id"] = "private-device"
        result = public_snapshot(raw)
        self.assertNotIn("plugin_catalog", result)
        self.assertNotIn("input_device_id", result["tracks"][0])
        result["tracks"][0]["name"] = "changed"
        self.assertEqual(raw["tracks"][0]["name"], "MIDI")


if __name__ == "__main__":
    unittest.main()
