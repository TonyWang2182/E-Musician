"""Check portable-package boundaries without building or launching an application."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dev
import package_release as release


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="emusician-package-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "source"
        self.build = self.root / "build"
        self.output = Path(temporary.name) / "output"
        self.build.mkdir(parents=True)
        (self.root / "CMakeLists.txt").write_text("project(EMusician VERSION 0.13.7 LANGUAGES C CXX)\n")
        self.cache()
        self.write("build/bin/Release/E-musician.exe", b"MZ-synthetic-test-only")
        for name in release.RUNTIME_FILES:
            self.write("scripts/" + name, b"# synthetic runtime\n")
        for name in (*release.PUBLIC_DOCUMENTS, "docs/licenses/example.txt"):
            self.write(name, b"Synthetic test fixture\n")
        self.write("scripts/music_agent/web/index.html", b"<p>Agent</p>")
        self.write("scripts/music_agent/replay_provider.py", b"# excluded")
        self.write("scripts/music_agent/.env", b"PRIVATE_FIXTURE")
        self.write("scripts/music_agent/audit.jsonl", b"PRIVATE_FIXTURE")
        self.write("scripts/audio_analysis/common.py", b"# source")
        self.write("scripts/cloud/private-key.pem", b"PRIVATE_FIXTURE")
        self.root_patch = patch.object(release, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def cache(self, extra=""):
        (self.build / "CMakeCache.txt").write_text(
            f"CMAKE_HOME_DIRECTORY:INTERNAL={self.root.as_posix()}\nEMUSICIAN_ENABLE_VST2:BOOL=OFF\n{extra}", encoding="utf-8")

    def test_allowlist_and_manifest_exclude_user_data_and_replay(self):
        with patch.object(release, "source_git_head", return_value="a" * 40):
            result = release.package(self.build, self.output)
        self.assertEqual(result["version"], "0.13.7")
        self.assertTrue((self.output / "runtime/scripts/run_agent.py").is_file())
        self.assertTrue((self.output / "runtime/scripts/music_agent/web/index.html").is_file())
        self.assertTrue((self.output / "runtime/scripts/cloud/register_compute.py").is_file())
        self.assertTrue((self.output / "docs/CONFIGURATION.md").is_file())
        self.assertTrue((self.output / "docs/MODELS.md").is_file())
        self.assertFalse((self.output / "runtime/scripts/music_agent/replay_provider.py").exists())
        self.assertFalse(any(path.name in (".env", "audit.jsonl", "private-key.pem") for path in self.output.rglob("*")))
        self.assertEqual(json.loads((self.output / "runtime/package.json").read_text())["source_revision"], "a" * 40)
        self.assertIn("  E-musician.exe\n", (self.output / "SHA256SUMS").read_text())
        metadata = (self.output / "runtime/package.json").read_text()
        self.assertNotIn(str(self.root), metadata)
        self.assertNotIn(str(self.output), metadata)
        relocated = self.output.with_name("renamed package with spaces")
        self.assertEqual(relocated.parent.resolve(), self.output.parent.resolve())
        self.output.rename(relocated)
        self.assertTrue((relocated / "runtime/scripts/run_agent.py").is_file())
        self.assertEqual((relocated / "runtime/package.json").read_text(), metadata)

    def test_existing_output_is_preserved(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "already exists"):
            release.package(self.build, self.output)
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_private_vst2_and_replay_builds_are_rejected_before_writes(self):
        for extra in ("EMUSICIAN_ENABLE_VST2:BOOL=ON\n", "EMUSICIAN_SHOWCASE:BOOL=ON\n"):
            with self.subTest(extra=extra):
                self.cache(extra)
                with self.assertRaises(ValueError):
                    release.package(self.build, self.output)
                self.assertFalse(self.output.exists())

    def test_missing_license_is_rejected_before_writes(self):
        (self.root / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "package input"):
            release.package(self.build, self.output)
        self.assertFalse(self.output.exists())

    def test_packaged_recorder_uses_per_user_writable_evidence(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "package.json").write_text("{}")
        local_data = self.root / "user-data"
        with patch.object(dev, "ROOT", runtime), patch.dict(os.environ, {"LOCALAPPDATA": str(local_data)}):
            recorder = dev.Recorder("helper-start", "Python", "synthetic fixture")
            _, receipt, log = recorder.new_record(["python", "run_agent.py"])
        self.assertTrue(receipt.is_relative_to(local_data))
        self.assertTrue(log.is_relative_to(local_data))
        self.assertEqual(list(runtime.iterdir()), [runtime / "package.json"])

    def test_public_command_omits_absolute_paths_but_keeps_command_identity(self):
        arguments = [sys.executable, str(self.root / "scripts/run_agent.py"), "--exe", str(self.output / "E-musician.exe")]
        with patch.object(dev, "ROOT", self.root):
            summary = dev.public_command(arguments)
        self.assertIn("python", summary)
        self.assertIn("<repo>/scripts/run_agent.py", summary)
        self.assertIn("<external-path>/E-musician.exe", summary)
        self.assertNotIn(str(self.root), summary)
        self.assertNotIn(str(self.output), summary)
        self.assertEqual(arguments[0], sys.executable)


if __name__ == "__main__":
    unittest.main()
