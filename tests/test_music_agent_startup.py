"""Startup restores provider preferences without credentials or network access."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_agent
from music_agent.config import config_path, save_config


class StartupPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {
            'LOCALAPPDATA': self.temp.name,
            'OPENAI_API_KEY': '', 'MOONSHOT_API_KEY': '',
        })
        environment.start()
        self.addCleanup(environment.stop)
        network = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Unexpected network request'))
        self.network = network.start()
        self.addCleanup(network.stop)

    def start(self, *arguments):
        command = ['run_agent.py', '--serve', '--embedded-session', 'unused-session.json', *arguments]
        with patch.object(sys, 'argv', command), patch.object(run_agent, 'embedded_session', return_value=0) as embedded:
            self.assertEqual(run_agent.main(), 0)
        self.network.assert_not_called()
        embedded.assert_called_once()
        return embedded.call_args.args[1]

    def test_saved_openai_effort_survives_helper_restart(self):
        for effort in ('low', 'high'):
            with self.subTest(effort=effort):
                save_config('gpt-5-mini', 'https://api.openai.com/v1', provider='openai', reasoning_effort=effort)
                before = config_path().read_bytes()
                for _ in range(2):
                    provider = self.start()
                    self.assertEqual(provider.provider_id, 'openai')
                    self.assertEqual(provider.reasoning_effort, effort)
                self.assertEqual(config_path().read_bytes(), before)

    def test_openai_without_saved_effort_defaults_to_medium(self):
        path = config_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'schema_version': 2, 'active_provider': 'openai',
            'providers': {'openai': {'model': 'gpt-5-mini', 'base_url': 'https://api.openai.com/v1'}}}), encoding='utf-8')
        self.assertEqual(self.start().reasoning_effort, 'medium')

    def test_fresh_openai_selection_uses_default_without_writing_settings(self):
        self.assertEqual(self.start('--provider', 'openai').reasoning_effort, 'medium')
        self.assertFalse(config_path().exists())

    def test_kimi_startup_does_not_receive_openai_only_option(self):
        provider = self.start()
        self.assertEqual(provider.provider_id, 'kimi')
        self.assertFalse(hasattr(provider, 'reasoning_effort'))


if __name__ == '__main__':
    unittest.main()
