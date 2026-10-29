"""Non-secret preference tests use disposable paths and never call a provider."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from music_agent.config import ConfigError, DEFAULT_CONFIG, MAX_CONFIG_BYTES, load_config, save_config
from music_agent.provider import ProviderError


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
        value["model"] = "changed"
        self.assertEqual(load_config(self.path)["model"], "kimi-k2.6")
        self.assertFalse(self.path.exists())
    def test_valid_roundtrip_and_url_normalization(self):
        save_config("kimi-k3.1-pro", "https://api.moonshot.ai/v1/", self.path)
        self.assertEqual(load_config(self.path), {
            "model": "kimi-k3.1-pro", "base_url": "https://api.moonshot.ai/v1"})
        self.assertEqual(set(json.loads(self.path.read_text(encoding="utf-8"))), {"model", "base_url"})
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], ["settings.json"])
    def test_corrupt_types_keys_and_values_fall_back(self):
        values = [b"{", b"[]", b"\xff", b'{"model":"a","model":"b","base_url":"x"}',
                  b'{"model":"kimi-k2.6"}',
                  json.dumps({**DEFAULT_CONFIG, "api_key": "sk-synthetic-not-a-key"}).encode(),
                  json.dumps({"model": 123, "base_url": DEFAULT_CONFIG["base_url"]}).encode(),
                  json.dumps({"model": "kimi-k2.6", "base_url": "https://attacker.test/v1"}).encode(),
                  json.dumps({"model": "sk-synthetic-not-a-key", "base_url": DEFAULT_CONFIG["base_url"]}).encode()]
        for value in values:
            with self.subTest(value=value[:60]):
                self.write(value)
                self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
                self.assertEqual(self.path.read_bytes(), value)  # Read does not rewrite user files.
    def test_oversized_input_falls_back(self):
        self.write(b" " * (MAX_CONFIG_BYTES + 1))
        self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
    def test_unreadable_file_falls_back(self):
        with patch.object(Path, "open", side_effect=PermissionError("private path")):
            self.assertEqual(load_config(self.path), DEFAULT_CONFIG)
    def test_invalid_save_preserves_previous_bytes(self):
        save_config(**DEFAULT_CONFIG, path=self.path)
        before = self.path.read_bytes()
        for model, base in [("bad model", DEFAULT_CONFIG["base_url"]),
                            ("kimi-k2.6", "http://api.moonshot.cn/v1"),
                            ("sk-synthetic-not-a-key", DEFAULT_CONFIG["base_url"])]:
            with self.subTest(model=model), self.assertRaises((ProviderError, ConfigError)):
                save_config(model, base, self.path)
            self.assertEqual(self.path.read_bytes(), before)
    def test_api_key_argument_not_accepted(self):
        with self.assertRaises(TypeError):
            save_config(**DEFAULT_CONFIG, api_key="sk-synthetic-not-a-key", path=self.path)
        self.assertFalse(self.path.exists())
    def test_failed_replace_keeps_old_file_and_cleans_temp(self):
        save_config(**DEFAULT_CONFIG, path=self.path)
        before = self.path.read_bytes()
        with patch("music_agent.config.os.replace", side_effect=PermissionError("private path")):
            with self.assertRaises(ConfigError) as caught:
                save_config("kimi-k3", DEFAULT_CONFIG["base_url"], self.path)
        self.assertNotIn("private path", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([entry.name for entry in self.path.parent.iterdir()], ["settings.json"])
    def test_no_network_or_key_access(self):
        with patch("music_agent.provider.load_key", side_effect=AssertionError("key access")), \
             patch("music_agent.provider.KimiProvider._request", side_effect=AssertionError("network")):
            save_config(**DEFAULT_CONFIG, path=self.path)
            self.assertEqual(load_config(self.path), DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
