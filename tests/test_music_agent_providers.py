"""OpenAI Responses and registry contracts; synthetic payloads only, never a live key."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import io
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.openai_provider import OpenAIProvider, _local_https_proxy
from music_agent.provider import KimiProvider, ProviderError
from music_agent.providers import create_provider, list_providers
from music_agent.secrets import SecretError, save_key, load_key, key_path, redact, _crypt, _PREFIX

KEY = "sk-proj_synthetic_only_not_a_credential"
URL = "https://api.openai.com/v1/responses"
TOOL = {"type": "function", "function": {"name": "read_notes", "description": "Read notes",
        "parameters": {"type": "object", "properties": {"clip_id": {"type": "string"}}, "required": []}}}

class Response:
    status = 200
    def __init__(self, data, url=URL):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.url = url
    def geturl(self): return self.url
    def read(self, limit): return self.data[:limit]
    def __enter__(self): return self
    def __exit__(self, *args): pass

class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception): raise item
        return item

def text_response(text="已读取工程。"):
    return {"status": "completed", "model": "gpt-5-mini-2025-08-07", "output": [
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 22, "output_tokens": 7, "total_tokens": 29}}

def tool_response():
    result = text_response()
    result["output"] = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-encrypted-fixture"},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_notes",
         "arguments": '{"clip_id":"c"}', "status": "completed"}]
    return result

class ResponsesTests(unittest.TestCase):
    def test_reasoning_output_budget_exhaustion_is_distinct_from_generic_incomplete(self):
        response={"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},"output":[]}
        opener=Opener([Response(response)])
        provider=OpenAIProvider(reasoning_effort="high",api_key=KEY,opener=opener)
        with self.assertRaises(ProviderError) as caught:
            provider.complete([{"role":"user","content":"Synthetic bounded planning"}],[TOOL])
        self.assertEqual(caught.exception.code,"output_limit")
        self.assertEqual(len(opener.requests),1)
        payload=json.loads(opener.requests[0].data)
        self.assertEqual(payload["reasoning"],{"effort":"high"})
        self.assertEqual(payload["max_output_tokens"],4096)

    def test_network_failure_names_selected_provider_without_leaking_reason(self):
        with self.assertRaises(ProviderError) as caught:
            OpenAIProvider(api_key=KEY, opener=Opener([URLError(KEY)])).list_models()
        self.assertEqual(caught.exception.code, "network")
        self.assertIn("OpenAI", str(caught.exception))
        self.assertNotIn("Kimi", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
    def test_http_error_stream_closed_without_reading_or_echoing(self):
        stream = io.BytesIO(KEY.encode())
        with self.assertRaises(ProviderError) as caught:
            OpenAIProvider(api_key=KEY, opener=Opener([HTTPError(URL, 401, KEY, {}, stream)])).list_models()
        self.assertTrue(stream.closed)
        self.assertNotIn(KEY, str(caught.exception))
    def test_request_mapping_store_false_and_usage(self):
        opener = Opener([Response(text_response())])
        provider = OpenAIProvider(api_key=KEY, opener=opener)
        result = provider.complete([{"role": "system", "content": "System"}, {"role": "user", "content": "Read"}], [TOOL])
        request = opener.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        self.assertFalse(body["store"])
        self.assertFalse(body["stream"])
        self.assertFalse(body["parallel_tool_calls"])
        self.assertFalse(body["tools"][0]["strict"])
        self.assertEqual(body["tools"][0]["parameters"], TOOL["function"]["parameters"])
        self.assertNotIn("function", body["tools"][0])
        self.assertEqual(body["reasoning"], {"effort": "medium"})
        self.assertEqual(body["max_output_tokens"], 4096)
        self.assertEqual(result["usage"], {"prompt_tokens": 22, "completion_tokens": 7, "total_tokens": 29})
        self.assertEqual(result["message"]["content"], "已读取工程。")
    def test_reasoning_and_call_ids_roundtrip(self):
        first = tool_response()
        opener = Opener([Response(first), Response(text_response())])
        provider = OpenAIProvider(api_key=KEY, opener=opener)
        messages = [{"role": "user", "content": "read c"}]
        returned = provider.complete(messages, [TOOL])["message"]
        self.assertEqual(returned["tool_calls"][0]["id"], "call_1")
        self.assertNotIn("reasoning_content", returned)
        messages += [returned, {"role": "tool", "tool_call_id": "call_1", "content": '{"notes":2}'}]
        provider.complete(messages, [TOOL])
        body = json.loads(opener.requests[1].data)
        self.assertEqual(body["input"][1:3], first["output"])
        self.assertEqual(body["input"][-1], {"type": "function_call_output", "call_id": "call_1", "output": '{"notes":2}'})
        self.assertNotIn("previous_response_id", body)
        self.assertNotIn("_provider_state", json.dumps(body))
        self.assertFalse(body["store"])
    def test_nonreasoning_model_omits_reasoning_effort(self):
        opener = Opener([Response(text_response())])
        OpenAIProvider(model="gpt-4.1-mini", api_key=KEY, opener=opener).complete([{"role": "user", "content": "hi"}])
        self.assertNotIn("reasoning", json.loads(opener.requests[0].data))
    def test_configured_effort_only_for_known_compatible_models(self):
        for effort in ("low","medium","high"):
            opener=Opener([Response(text_response())])
            p=OpenAIProvider(model="gpt-5-mini",api_key=KEY,opener=opener,reasoning_effort=effort)
            self.assertTrue(p.capabilities["reasoning_effort"])
            p.complete([{"role":"user","content":"hi"}])
            self.assertEqual(json.loads(opener.requests[0].data)["reasoning"],{"effort":effort})
        for model in ("gpt-4.1-mini","gpt-5-chat-latest","gpt-5-unknown-model"):
            opener=Opener([Response(text_response())])
            p=OpenAIProvider(model=model,api_key=KEY,opener=opener,reasoning_effort="high")
            self.assertFalse(p.capabilities["reasoning_effort"])
            p.complete([{"role":"user","content":"hi"}])
            self.assertNotIn("reasoning",json.loads(opener.requests[0].data))
        for effort in (None, 2, False, "xhigh", ""):
            with self.subTest(effort=effort),self.assertRaises(ProviderError): OpenAIProvider(reasoning_effort=effort)
    def test_incomplete_and_unsupported_output_rejected(self):
        cases = []
        for status in ("incomplete", "failed", "in_progress", None):
            value = text_response(); value["status"] = status; cases.append(value)
        for bad in ([{"type": "web_search_call"}], [{"type": "reasoning", "summary": []}], [],
                    [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "No"}]}]):
            value = text_response(); value["output"] = bad; cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                provider = OpenAIProvider(api_key=KEY, opener=Opener([Response(value)]))
                with self.assertRaises(ProviderError): provider.complete([{"role": "user", "content": "hi"}])
    def test_duplicate_call_ids_rejected(self):
        value = tool_response(); value["output"].append(copy.deepcopy(value["output"][-1]))
        provider = OpenAIProvider(api_key=KEY, opener=Opener([Response(value)]))
        with self.assertRaises(ProviderError): provider.complete([{"role": "user", "content": "hi"}])
    def test_orphan_missing_duplicate_results_not_sent(self):
        initial = OpenAIProvider(api_key=KEY, opener=Opener([Response(tool_response())])).complete([{"role": "user", "content": "hi"}])["message"]
        result = {"role": "tool", "tool_call_id": "call_1", "content": "{}"}
        cases = [[result], [initial], [initial, result, result], [initial, {**result, "tool_call_id": "bad"}]]
        for messages in cases:
            opener = Opener([])
            with self.subTest(messages=messages), self.assertRaises(ProviderError):
                OpenAIProvider(api_key=KEY, opener=opener).complete(messages)
            self.assertEqual(opener.requests, [])
    def test_tampered_or_cross_provider_private_state_not_sent(self):
        initial = OpenAIProvider(api_key=KEY, opener=Opener([Response(tool_response())])).complete([{"role": "user", "content": "hi"}])["message"]
        changed = copy.deepcopy(initial); changed["tool_calls"][0]["function"]["name"] = "different"
        foreign = copy.deepcopy(initial); foreign["_provider_state"]["provider"] = "kimi"
        other_model = copy.deepcopy(initial); other_model["_provider_state"]["model"] = "gpt-5"
        for message in (changed, foreign, other_model):
            with self.subTest(message=message), self.assertRaises(ProviderError):
                OpenAIProvider(api_key=KEY, opener=Opener([])).complete([message])
        with self.assertRaises(ProviderError) as caught:
            KimiProvider(api_key=KEY, opener=Opener([])).complete([initial])
        self.assertEqual(caught.exception.code, "provider_mismatch")
    def test_auth_and_nonfinite_protocol_errors(self):
        for reply in (HTTPError(URL, 401, KEY, {}, io.BytesIO(KEY.encode())),
                      Response(b'{"status":"completed","usage":{"input_tokens":1e400}}'),
                      Response(b'{"status":"completed","status":"failed"}')):
            with self.subTest(reply=type(reply).__name__), self.assertRaises(ProviderError) as caught:
                OpenAIProvider(api_key=KEY, opener=Opener([reply])).complete([{"role": "user", "content": "x"}])
            self.assertNotIn(KEY, str(caught.exception))
    def test_official_endpoint_and_tool_capability_gates(self):
        with self.assertRaises(ProviderError): OpenAIProvider(base_url="https://api.moonshot.cn/v1")
        with self.assertRaises(ProviderError): KimiProvider(base_url="https://api.openai.com/v1")
        with self.assertRaises(ProviderError) as caught:
            create_provider("openai", "text-embedding-3-small")
        self.assertEqual(caught.exception.code, "unsupported_capability")
    def test_provider_specific_key_loader(self):
        with patch("music_agent.provider.load_key", return_value=KEY) as load:
            OpenAIProvider(opener=Opener([Response(text_response())])).complete([{"role": "user", "content": "hi"}])
            load.assert_called_once_with(provider="openai")
    def test_list_models_uses_openai_path(self):
        opener = Opener([Response({"data": [{"id": "gpt-5-mini"}]}, "https://api.openai.com/v1/models")])
        self.assertEqual(OpenAIProvider(api_key=KEY, opener=opener).list_models(), ["gpt-5-mini"])

class ProxySelectionTests(unittest.TestCase):
    def test_only_explicit_loopback_https_routes_are_accepted(self):
        for proxy in ("http://127.0.0.1:7890", "http://localhost:3128", "http://[::1]:8080", "https://localhost:443"):
            with self.subTest(proxy=proxy):
                self.assertEqual(_local_https_proxy({"https": proxy}), {"https": proxy})
        for proxy in ("http://example.com:7890", "http://127.0.0.2:7890", "http://127.0.0.1.evil:7890",
                      "http://user:password@localhost:7890", "http://localhost:7890/", "http://localhost:7890/a",
                      "http://localhost:7890?route=elsewhere", "http://localhost:7890#fragment",
                      "socks5://localhost:7890", "http://localhost", "http://localhost:0", "http://localhost:65536",
                      "http://localhost:7890\n", "http://%6cocalhost:7890", "http://[::ffff:127.0.0.1]:7890", None):
            with self.subTest(proxy=proxy):
                self.assertEqual(_local_https_proxy({"https": proxy}), {})
        self.assertEqual(_local_https_proxy({"http": "http://localhost:7890", "all": "http://localhost:7890"}), {})

    def test_openai_discovers_filtered_proxy_without_changing_origin_or_redirect_guard(self):
        opener = Opener([Response(text_response())])
        with patch("music_agent.openai_provider.getproxies", return_value={"https": "http://127.0.0.1:7890"}), \
             patch("music_agent.openai_provider.build_opener", return_value=opener) as build:
            provider = OpenAIProvider(api_key=KEY)
        self.assertEqual(provider.network_mode, "system_loopback_proxy")
        self.assertEqual(build.call_args.args[0].proxies, {"https": "http://127.0.0.1:7890"})
        self.assertEqual(type(build.call_args.args[1]).__name__, "_NoRedirect")
        provider.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(opener.requests[0].full_url, URL)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + KEY)

    def test_remote_environment_proxy_ignored_and_kimi_keeps_direct(self):
        with patch("music_agent.openai_provider.getproxies", return_value={"https": "http://remote.invalid:8080"}), \
             patch("music_agent.openai_provider.build_opener") as build:
            self.assertEqual(OpenAIProvider().network_mode, "direct")
            self.assertEqual(build.call_args.args[0].proxies, {})
        with patch("music_agent.provider.build_opener") as build:
            self.assertEqual(KimiProvider().network_mode, "direct")
            self.assertEqual(build.call_args.args[0].proxies, {})

    def test_injected_opener_skips_proxy_discovery(self):
        with patch("music_agent.openai_provider.getproxies") as discover:
            self.assertEqual(OpenAIProvider(opener=Opener([])).network_mode, "injected")
            discover.assert_not_called()


class RegistryTests(unittest.TestCase):
    def test_statuses_and_pending_not_executable(self):
        with patch("music_agent.providers.has_key", side_effect=lambda provider: provider == "kimi"):
            entries = {entry["id"]: entry for entry in list_providers()}
        self.assertEqual(entries["kimi"]["status"], "available")
        self.assertEqual(entries["openai"]["status"], "unconfigured")
        for provider in ("anthropic", "gemini", "local-compatible"):
            self.assertEqual(entries[provider]["status"], "adapter_pending")
            self.assertFalse(entries[provider]["adapter_ready"])
            with self.assertRaises(ProviderError) as caught: create_provider(provider)
            self.assertEqual(caught.exception.code, "adapter_pending")
    def test_factory_has_independent_defaults(self):
        self.assertEqual(create_provider("openai").model, "gpt-5-mini")
        self.assertEqual(create_provider().model, "kimi-k2.6")
        with self.assertRaises(ProviderError): create_provider("unknown")

class CredentialIsolationTests(unittest.TestCase):
    def test_env_namespaces_do_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"MOONSHOT_API_KEY": "sk-kimi-fixture-value"}, clear=True):
            missing = Path(temp) / "absent.key"
            self.assertEqual(load_key(path=missing), "sk-kimi-fixture-value")
            with self.assertRaises(SecretError): load_key(provider="openai", path=missing)
            with patch.dict(os.environ, {"OPENAI_API_KEY": KEY}):
                self.assertEqual(load_key(provider="openai", path=missing), KEY)
                self.assertEqual(load_key(provider="kimi", path=missing), "sk-kimi-fixture-value")
    def test_paths_keep_legacy_moonshot_and_separate_openai(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/synthetic-only"}):
            self.assertEqual(key_path().name, "moonshot.key")
            self.assertEqual(key_path("openai").name, "openai.key")
            self.assertNotEqual(key_path(), key_path("openai"))
    @unittest.skipUnless(os.name == "nt", "DPAPI needs Windows")
    def test_encrypted_key_bound_to_provider_even_if_copied(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "credential.key"
            save_key(KEY, provider="openai", path=path)
            self.assertNotIn(KEY.encode(), path.read_bytes())
            self.assertEqual(load_key(provider="openai", path=path), KEY)
            with self.assertRaises(SecretError): load_key(provider="kimi", path=path)
    @unittest.skipUnless(os.name == "nt", "DPAPI needs Windows")
    def test_legacy_kimi_cipher_only_usable_for_kimi(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.key"
            path.write_bytes(_PREFIX + _crypt(b"sk-old-kimi-fixture", decrypt=False))
            self.assertEqual(load_key(provider="kimi", path=path), "sk-old-kimi-fixture")
            with self.assertRaises(SecretError): load_key(provider="openai", path=path)
    def test_long_underscored_keys_and_exact_redaction(self):
        long_key = "sk-proj_" + "x_" * 300
        opaque = "AIza_synthetic_only_credential"
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"OPENAI_API_KEY": long_key, "GEMINI_API_KEY": opaque}):
            path = Path(temp) / "missing.key"
            self.assertEqual(load_key(provider="openai", path=path), long_key)
            self.assertEqual(load_key(provider="gemini", path=path), opaque)
            self.assertNotIn(long_key, redact("bad: " + long_key))
            self.assertNotIn(opaque, redact("bad: " + opaque))
            self.assertEqual(redact(long_key), "[API key redacted]")

if __name__ == "__main__":
    unittest.main()
