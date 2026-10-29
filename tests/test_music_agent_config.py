"""Non-secret preference migration and isolation; no provider or user-config access."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.config import ConfigError, DEFAULT_CONFIG, MAX_CONFIG_BYTES, load_config, save_config, active_config
from music_agent.provider import ProviderError

KIMI = {"model": "kimi-k2.6", "base_url": "https://api.moonshot.cn/v1"}

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prefs" / "settings.json"
    def tearDown(self):
        self.directory.cleanup()
    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(data)
    def test_missing_returns_independent_defaults(self):
        value = load_config(self.path)
        self.assertEqual(value, DEFAULT_CONFIG)
        value["providers"]["kimi"]["model"] = "changed"
        self.assertEqual(active_config(load_config(self.path))["model"], "kimi-k2.6")
        self.assertFalse(self.path.exists())
    def test_legacy_migration_read_only(self):
        old = {"model": "kimi-k3.1-pro", "base_url": KIMI["base_url"]}
        data = json.dumps(old).encode()
        self.write(data)
        config = load_config(self.path)
        self.assertEqual(config["schema_version"], 2)
        self.assertEqual(active_config(config), {"provider": "kimi", **old})
        self.assertEqual(self.path.read_bytes(), data)
    def test_valid_roundtrip_and_url_normalization(self):
        save_config("kimi-k3.1-pro", "https://api.moonshot.ai/v1/", self.path)
        self.assertEqual(active_config(load_config(self.path)), {
            "provider": "kimi", "model": "kimi-k3.1-pro", "base_url": "https://api.moonshot.ai/v1"})
        self.assertEqual(set(json.loads(self.path.read_text(encoding="utf-8"))), {"schema_version", "active_provider", "providers"})
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["settings.json"])
    def test_switch_preserves_independent_preferences(self):
        save_config("kimi-k3.1-pro", "https://api.moonshot.ai/v1", self.path)
        save_config("gpt-5-mini", "https://api.openai.com/v1", self.path, provider="openai")
        values = load_config(self.path)
        self.assertEqual(active_config(values)["provider"], "openai")
        self.assertEqual(values["providers"]["kimi"]["model"], "kimi-k3.1-pro")
        save_config(**values["providers"]["kimi"], path=self.path, provider="kimi")
        self.assertEqual(load_config(self.path)["providers"]["openai"]["model"], "gpt-5-mini")
    def test_corrupt_types_keys_and_values_fall_back(self):
        values = [b"{", b"[]", b"\xff", b'{"model":"a","model":"b","base_url":"x"}',
                  b'{"model":"kimi-k2.6"}', json.dumps({**KIMI, "api_key": "sk-synthetic-not-a-key"}).encode(),
                  json.dumps({"model": 123, "base_url": KIMI["base_url"]}).encode(),
                  json.dumps({"model": "kimi-k2.6", "base_url": "https://attacker.test/v1"}).encode(),
                  json.dumps({"model": "sk-synthetic-not-a-key", "base_url": KIMI["base_url"]}).encode()]
        unknown = copy.deepcopy(DEFAULT_CONFIG)
        unknown["providers"]["openai"]["api_key"] = "sk-synthetic-not-a-key"
        values.append(json.dumps(unknown).encode())
        for value in values:
            with self.subTest(value=value[:60]):
                self.write(value)
                self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
                self.assertEqual(self.path.read_bytes(), value)
    def test_oversized_input_falls_back(self):
        self.write(b" " * (MAX_CONFIG_BYTES + 1))
        self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
    def test_unreadable_file_falls_back(self):
        with patch.object(Path, "open", side_effect=PermissionError("private path")):
            self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
    def test_invalid_save_preserves_previous_bytes(self):
        save_config(**KIMI, path=self.path)
        before = self.path.read_bytes()
        for model, base in [("bad model", KIMI["base_url"]), ("kimi-k2.6", "http://api.moonshot.cn/v1"),
                            ("sk-synthetic-not-a-key", KIMI["base_url"])]:
            with self.subTest(model=model), self.assertRaises((ProviderError, ConfigError)):
                save_config(model, base, self.path)
            self.assertEqual(self.path.read_bytes(), before)
    def test_api_key_argument_not_accepted(self):
        with self.assertRaises(TypeError):
            save_config(**KIMI, api_key="sk-synthetic-not-a-key", path=self.path)
        self.assertFalse(self.path.exists())
    def test_failed_replace_keeps_old_file_and_cleans_temp(self):
        save_config(**KIMI, path=self.path)
        before = self.path.read_bytes()
        with patch("music_agent.config.os.replace", side_effect=PermissionError("private path")):
            with self.assertRaises(ConfigError) as caught:
                save_config("kimi-k3", KIMI["base_url"], self.path)
        self.assertNotIn("private path", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["settings.json"])
    def test_no_network_or_key_access(self):
        with patch("music_agent.provider.load_key", side_effect=AssertionError("key access")), \
             patch("music_agent.provider.KimiProvider._request", side_effect=AssertionError("network")):
            save_config(**KIMI, path=self.path)
            self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
    def test_pending_provider_cannot_activate(self):
        with self.assertRaises(ProviderError) as caught:
            save_config("x", "https://x", self.path, provider="anthropic")
        self.assertEqual(caught.exception.code, "adapter_pending")
        self.assertFalse(self.path.exists())

if __name__ == "__main__":
    unittest.main()
