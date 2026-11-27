"""Portable configuration regression; no SSH, API or music-model requests."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import runtime_paths
from scripts.cloud import register_compute


class RuntimePathsTests(unittest.TestCase):
    def test_desktop_script_import_mode_outside_source_working_directory(self):
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        code = 'import sys; sys.path.insert(0, sys.argv[1]); import cloud.run_generation, cloud.compute_client'
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', code, str(scripts)], cwd=directory,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_fresh_user_defaults_do_not_use_developer_drive(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'LOCALAPPDATA': directory, 'EMUSICIAN_ANALYSIS_ROOT': '',
            'EMUSICIAN_COMPUTE_ROOT': '', 'EMUSICIAN_GENERATION_ROOT': ''
        }):
            self.assertEqual(runtime_paths.analysis_root(), Path(directory) / 'E-musician/analysis')
            self.assertEqual(runtime_paths.compute_root(), Path(directory) / 'E-musician/cloud-inference')
            self.assertEqual(runtime_paths.generation_root(), runtime_paths.compute_root())

    def test_absolute_override_preserves_existing_user_storage(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'EMUSICIAN_ANALYSIS_ROOT': directory}):
            marker = Path(directory) / 'existing-user-data'
            marker.write_text('preserve', encoding='utf-8')
            self.assertEqual(runtime_paths.analysis_root(), Path(directory))
            self.assertEqual(marker.read_text(encoding='utf-8'), 'preserve')

    def test_relative_override_cannot_redirect_into_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'LOCALAPPDATA': directory, 'EMUSICIAN_COMPUTE_ROOT': 'relative/cache'
        }):
            self.assertEqual(runtime_paths.compute_root(), Path(directory) / 'E-musician/cloud-inference')


class RegistrationTests(unittest.TestCase):
    def test_own_host_and_partial_catalog_keep_unavailable_models_disabled(self):
        providers = [
            {'model_id': 'scnet', 'kind': 'separate', 'execution': 'cloud', 'available': True},
            {'model_id': 'muscriptor', 'kind': 'transcribe', 'execution': 'cloud', 'available': False},
        ]
        observed = {}

        class LocalTunnel:
            def __init__(self, config, directory):
                observed.update(config)
            def open(self):
                return {'service': 'emusician-compute', 'protocol_version': 2}
            def call(self, method, path):
                return {'protocol_version': 2, 'providers': providers}
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {'schema_version': 1, 'available': False, 'ssh_alias': 'old-host',
                   'remote_port': 18082, 'compute_protocol': 2, 'start_service': True,
                   'operator_note': 'preserve custom metadata'}
            (root / 'compute-registry.json').write_text(json.dumps(old), encoding='utf-8')
            command = ['register_compute.py', '--root', directory, '--register', '--python', sys.executable,
                       '--ssh-alias', 'my-music-host', '--remote-port', '18090', '--no-start-service']
            with patch.object(sys, 'argv', command), patch.object(register_compute.client, 'Tunnel', LocalTunnel), \
                 patch.object(register_compute.subprocess, 'run') as local_probe, contextlib.redirect_stdout(io.StringIO()):
                register_compute.main()
            result = json.loads((root / 'compute-registry.json').read_text(encoding='utf-8'))
            self.assertEqual(observed['ssh_alias'], 'my-music-host')
            self.assertEqual(result['remote_port'], 18090)
            self.assertFalse(result['start_service'])
            self.assertTrue(result['providers'][0]['available'])
            self.assertFalse(result['providers'][1]['available'])
            self.assertEqual(result['operator_note'], old['operator_note'])
            self.assertEqual(local_probe.call_count, 1)
            backups = list((root / 'experiments').glob('*/previous-registry.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8')), old)

    def test_invalid_local_interpreter_prevents_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            command = ['register_compute.py', '--root', directory, '--register', '--python', 'relative/python.exe']
            with patch.object(sys, 'argv', command), patch.object(register_compute.client, 'Tunnel') as tunnel:
                with self.assertRaises(RuntimeError):
                    register_compute.main()
                tunnel.assert_not_called()
            self.assertFalse((Path(directory) / 'compute-registry.json').exists())


if __name__ == '__main__':
    unittest.main()
