"""Provider contract/security tests use synthetic responses and disposable credentials."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.provider import KimiProvider, ProviderError, MAX_BODY_BYTES, _NoRedirect
from music_agent.secrets import SecretError, save_key, load_key, has_key, redact

TEST_KEY = "sk-test-only-not-a-real-credential"
URL = "https://api.moonshot.cn/v1/chat/completions"


class Response:
    def __init__(self, payload, url=URL, status=200):
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.url = url
        self.status = status
        self.read_limit = None
    def geturl(self):
        return self.url
    def read(self, limit):
        self.read_limit = limit
        return self.data[:limit]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def completion(message=None, finish="stop"):
    return {"model": "kimi-k2.5", "choices": [{"finish_reason": finish,
             "message": message or {"role": "assistant", "content": "可以，先查看工程。"}}],
            "usage": {"prompt_tokens": 31, "completion_tokens": 8, "total_tokens": 39}}


class ProviderTests(unittest.TestCase):
    def client(self, result=None):
        opener = Opener(Response(completion() if result is None else result))
        return KimiProvider(api_key=TEST_KEY, opener=opener), opener

    def test_official_request_and_usage(self):
        client, opener = self.client()
        result = client.complete([{"role": "user", "content": "查看工程"}])
        request, timeout = opener.requests[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TEST_KEY)
        self.assertEqual(payload["model"], "kimi-k2.6")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertFalse(payload["stream"])
        self.assertEqual(timeout, 45)
        self.assertEqual(result["usage"]["total_tokens"], 39)
        self.assertEqual(result["message"]["content"], "可以，先查看工程。")
        self.assertNotIn(TEST_KEY, json.dumps(payload))

    def test_full_tool_message_preserves_reasoning(self):
        msg = {"role": "assistant", "content": None, "reasoning_content": "plan context",
               "tool_calls": [{"id": "t1", "type": "function", "function": {
                   "name": "get_snapshot", "arguments": "{}"}}]}
        client, opener = self.client(completion(msg, "tool_calls"))
        result = client.complete([{"role": "user", "content": "查看"}],
            [{"type": "function", "function": {"name": "get_snapshot", "parameters": {"type": "object"}}}])
        self.assertEqual(result["message"], msg)
        self.assertEqual(json.loads(opener.requests[0][0].data)["tool_choice"], "auto")

    def test_no_thinking_parameter_on_old_model(self):
        client, opener = self.client()
        client.model = "moonshot-v1-8k"
        client.complete([{"role": "user", "content": "hello"}])
        self.assertNotIn("thinking", json.loads(opener.requests[0][0].data))

    def test_k27_omits_unsupported_thinking_switch(self):
        client, opener = self.client()
        client.model = "kimi-k2.7-code"
        client.complete([{"role": "user", "content": "hello"}])
        payload = json.loads(opener.requests[0][0].data)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning_effort", payload)

    def test_k3_uses_low_reasoning(self):
        client, opener = self.client()
        client.model = "kimi-k3.1-pro"
        client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(json.loads(opener.requests[0][0].data)["reasoning_effort"], "low")

    def test_base_url_allowlist(self):
        for url in ["http://api.moonshot.cn/v1", "https://api.moonshot.cn.evil.test/v1",
                    "https://api.moonshot.cn@evil.test/v1", "https://api.moonshot.cn/v1?x=1",
                    "https://api.moonshot.cn:444/v1", "https://evil.test/v1"]:
            with self.subTest(url=url), self.assertRaises(ProviderError):
                KimiProvider(base_url=url)
        self.assertEqual(KimiProvider(base_url="https://api.moonshot.ai/v1/").base_url,
                         "https://api.moonshot.ai/v1")

    def test_redirect_blocked_before_follow(self):
        with self.assertRaises(ProviderError) as caught:
            _NoRedirect().redirect_request(None, None, 302, "reason", {}, "https://evil.test")
        self.assertEqual(caught.exception.code, "redirect")

    def test_unexpected_response_url_rejected(self):
        opener = Opener(Response(completion(), "https://evil.test"))
        client = KimiProvider(api_key=TEST_KEY, opener=opener)
        with self.assertRaises(ProviderError) as caught:
            client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.code, "redirect")

    def test_http_errors_do_not_echo_secret_or_request(self):
        for status, code in [(401, "authentication"), (403, "authentication"), (429, "rate_limit"),
                             (400, "bad_request"), (404, "model_not_found"), (500, "http_error")]:
            error = HTTPError(URL, status, TEST_KEY, {"x-secret": TEST_KEY}, io.BytesIO(TEST_KEY.encode()))
            opener = Opener(error)
            client = KimiProvider(api_key=TEST_KEY, opener=opener)
            with self.subTest(status=status), self.assertRaises(ProviderError) as caught:
                client.complete([{"role": "user", "content": "hello"}])
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.status, status)
            self.assertNotIn(TEST_KEY, str(caught.exception))
            self.assertEqual(len(opener.requests), 1)  # Never automatic paid retry.

    def test_timeout_and_network_errors_sanitized(self):
        for error, code in [(TimeoutError(TEST_KEY), "timeout"), (URLError(TEST_KEY), "network")]:
            client = KimiProvider(api_key=TEST_KEY, opener=Opener(error))
            with self.subTest(code=code), self.assertRaises(ProviderError) as caught:
                client.complete([{"role": "user", "content": "hello"}])
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_invalid_json_and_shape_rejected(self):
        examples = [b"{bad", b'[]', b'{"choices":NaN}', b'{"choices":1e400}', b'{"choices":1,"choices":2}',
                    {"choices": []}, completion({"role": "user", "content": "bad"}),
                    completion({"role": "assistant", "content": []}), completion(finish="length"),
                    completion({"role": "assistant", "content": ""}),
                    completion({"role": "assistant", "content": "x", "tool_calls": []}),
                    completion({"role": "assistant", "content": None}, "tool_calls")]
        for index, data in enumerate(examples):
            client, _ = self.client(data)
            with self.subTest(index=index), self.assertRaises(ProviderError):
                client.complete([{"role": "user", "content": "hello"}])

    def test_repeated_tool_id_rejected(self):
        call = {"id": "t1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        client, _ = self.client(completion({"role": "assistant", "content": None,
                                           "tool_calls": [call, call]}, "tool_calls"))
        with self.assertRaises(ProviderError):
            client.complete([{"role": "user", "content": "hello"}])

    def test_response_limit_enforced(self):
        client, opener = self.client(b" " * (MAX_BODY_BYTES + 10))
        with self.assertRaises(ProviderError) as caught:
            client.complete([{"role": "user", "content": "hello"}])
        self.assertEqual(caught.exception.code, "response_too_large")
        self.assertEqual(opener.response.read_limit, MAX_BODY_BYTES + 1)

    def test_invalid_requests_not_sent(self):
        client, opener = self.client()
        for messages in [[], [{"role": "malicious", "content": "x"}],
                         [{"role": "user", "content": float("inf")}],
                         [{"role": "user", "content": "a" * MAX_BODY_BYTES}]]:
            with self.subTest(messages=str(messages)[:30]), self.assertRaises(ProviderError):
                client.complete(messages)
        self.assertEqual(opener.requests, [])

    def test_list_models(self):
        opener = Opener(Response({"data": [{"id": "kimi-k2.5"}, {"id": "kimi-k3.1-pro"},
                                           {"id": "kimi-k2.5"}]}, "https://api.moonshot.cn/v1/models"))
        client = KimiProvider(api_key=TEST_KEY, opener=opener)
        self.assertEqual(client.list_models(), ["kimi-k2.5", "kimi-k3.1-pro"])
        self.assertIsNone(opener.requests[0][0].data)

    def test_missing_key_actionable(self):
        with patch("music_agent.provider.load_key", side_effect=SecretError(TEST_KEY)):
            client = KimiProvider(opener=Opener(None))
            with self.assertRaises(ProviderError) as caught:
                client.list_models()
        self.assertEqual(caught.exception.code, "missing_key")
        self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_usage_must_be_integer(self):
        for value in [True, -1, "12", float("inf")]:
            data = completion()
            data["usage"]["total_tokens"] = value
            client, _ = self.client(data)
            with self.subTest(value=value), self.assertRaises(ProviderError):
                client.complete([{"role": "user", "content": "hello"}])


class SecretTests(unittest.TestCase):
    def test_redacts_keys_and_authorization(self):
        for text in [f"bad {TEST_KEY}", f"Authorization: Bearer {TEST_KEY}",
                     "authorization=Bearer opaque-token"]:
            redacted = redact(text)
            self.assertNotIn(TEST_KEY, redacted)
            self.assertNotIn("opaque-token", redacted)

    def test_environment_fallback_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.key"
            with patch.dict(os.environ, {"MOONSHOT_API_KEY": TEST_KEY}):
                self.assertEqual(load_key(path=path), TEST_KEY)
                self.assertTrue(has_key(path=path))
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(has_key(path=path))
                with self.assertRaises(SecretError):
                    load_key(path=path)

    def test_malformed_file_is_not_treated_as_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed.key"
            path.write_text(TEST_KEY)
            with patch.dict(os.environ, {"MOONSHOT_API_KEY": TEST_KEY}):
                self.assertFalse(has_key(path=path))
                with self.assertRaises(SecretError):
                    load_key(path=path)

    @unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
    def test_dpapi_roundtrip_and_atomic_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "test.key"
            save_key(TEST_KEY, path=path)
            self.assertNotIn(TEST_KEY.encode(), path.read_bytes())
            self.assertEqual(load_key(path=path), TEST_KEY)
            next_key = "sk-second-fixture-not-a-real-secret"
            save_key(next_key, path=path)
            self.assertEqual(load_key(path=path), next_key)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["test.key"])

    def test_invalid_key_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.key"
            for key in ["short", "bad\nheader: injected", "a" * 4097]:
                with self.subTest(key=key[:8]), self.assertRaises(SecretError):
                    save_key(key, path=path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
