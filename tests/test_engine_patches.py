"""Patch-integrity tests using owned synthetic checkouts, never the real _deps."""
from __future__ import annotations

import difflib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("emusician_engine_patches", ROOT / "scripts/apply_engine_patches.py")
assert SPEC is not None and SPEC.loader is not None
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)
PINNED = "b0c7dd090a56b27fe01bb394617891906eb34daf"


class EnginePatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="emusician-patch-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "synthetic-checkout"
        (self.checkout / ".git").mkdir(parents=True)
        (self.checkout / ".git/HEAD").write_text(PINNED + "\n", encoding="utf-8")
        self.relative = "modules/fixture/reader.cpp"
        self.target = self.checkout / self.relative
        self.target.parent.mkdir(parents=True)
        self.before = b"// synthetic test source\nint phase = 0;\nint unchanged = 7;\n"
        self.after = b"// synthetic test source\nint phase = 1;\nbool valid = true;\nint unchanged = 7;\n"
        self.target.write_bytes(self.before)
        self.extra = self.checkout / "untouched.bin"
        self.extra.write_bytes(b"\x00\xffpreserve\r\n")
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.patch_file = self.bundle / "fixture.patch"
        patch = "".join(difflib.unified_diff(self.before.decode().splitlines(keepends=True),
            self.after.decode().splitlines(keepends=True), fromfile="a/"+self.relative, tofile="b/"+self.relative))
        self.patch_file.write_bytes(patch.encode())
        self.manifest = self.bundle / "manifest.json"
        self.data = {"schema": 1, "upstream_commit": PINNED, "hash_normalization": "utf8-lf", "files": [{
            "path": self.relative, "patch": "fixture.patch",
            "before_sha256_lf": patcher.digest(self.before), "after_sha256_lf": patcher.digest(self.after),
            "patch_sha256_lf": patcher.digest(patch.encode())}]}
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")

    def run_mode(self, mode):
        return patcher.run(mode, self.checkout, self.manifest)

    def add_second_source(self):
        self.data["schema"] = 2
        relative = "modules/fixture/parameter.h"
        target = self.checkout / relative
        before, after = b"void notify() { explicitValue = current; }\n", b"void notify() { if (echo) return; explicitValue = current; }\n"
        target.write_bytes(before)
        patch = "".join(difflib.unified_diff(before.decode().splitlines(keepends=True),
            after.decode().splitlines(keepends=True), fromfile="a/"+relative, tofile="b/"+relative)).encode()
        (self.bundle / "parameter.patch").write_bytes(patch)
        self.data["files"].append({"path": relative, "patch": "parameter.patch",
            "before_sha256_lf": patcher.digest(before), "after_sha256_lf": patcher.digest(after),
            "patch_sha256_lf": patcher.digest(patch)})
        self.write_manifest()
        return target, before, after

    def test_schema2_applies_all_sources_and_resumes_verified_subset(self):
        other, before, after = self.add_second_source()
        self.target.write_bytes(self.after)  # A prior interrupted run completed this file.
        result = self.run_mode("apply")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertEqual(other.read_bytes(), after)
        self.assertEqual(self.run_mode("verify")["status"], "verified")
        self.assertEqual(self.run_mode("apply")["status"], "verified")

    def test_schema2_accepts_thirteen_and_rejects_over_sixteen_before_writes(self):
        self.data["schema"] = 2
        targets = [self.target]
        for index in range(1, 13):
            relative = f"modules/fixture/reader-{index}.cpp"
            target = self.checkout / relative
            target.write_bytes(self.before)
            targets.append(target)
            name = f"reader-{index}.patch"
            patch = "".join(difflib.unified_diff(self.before.decode().splitlines(keepends=True),
                self.after.decode().splitlines(keepends=True), "a/" + relative, "b/" + relative)).encode()
            (self.bundle / name).write_bytes(patch)
            self.data["files"].append({"path": relative, "patch": name,
                "before_sha256_lf": patcher.digest(self.before), "after_sha256_lf": patcher.digest(self.after),
                "patch_sha256_lf": patcher.digest(patch)})
        thirteen = list(self.data["files"])
        self.data["files"].extend(dict(thirteen[0]) for _ in range(4))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, r"1\.\.16"):
            self.run_mode("apply")
        self.assertTrue(all(target.read_bytes() == self.before for target in targets))
        self.data["files"] = thirteen
        self.write_manifest()
        result = self.run_mode("apply")
        self.assertEqual(len(result["files"]), 13)
        self.assertTrue(all(target.read_bytes() == self.after for target in targets))
        self.assertEqual(self.run_mode("verify")["status"], "verified")

    def test_schema2_preflights_later_source_before_writing_first(self):
        other, before, _ = self.add_second_source()
        other.write_bytes(before + b"// preserve local edit\n")
        modified = other.read_bytes()
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(other.read_bytes(), modified)

    def test_schema2_preflights_later_patch_output_before_writing_first(self):
        other, before, _ = self.add_second_source()
        self.data["files"][1]["after_sha256_lf"] = "0" * 64
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "output hash"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(other.read_bytes(), before)

    def test_schema2_rejects_duplicate_paths_and_schema1_stays_single_source(self):
        self.add_second_source()
        self.data["schema"] = 1
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "requires one source"):
            self.run_mode("apply")
        self.data["schema"] = 2
        self.data["files"][1] = dict(self.data["files"][0])
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_exact_apply_verify_idempotency_and_unrelated_bytes(self):
        paths_before = {p.relative_to(self.checkout) for p in self.checkout.rglob("*") if p.is_file()}
        extra_before = self.extra.read_bytes()
        self.assertEqual(self.run_mode("apply")["status"], "applied")
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertEqual(self.run_mode("verify")["status"], "verified")
        self.assertEqual(self.run_mode("apply")["status"], "verified")
        self.assertEqual(self.extra.read_bytes(), extra_before)
        self.assertEqual({p.relative_to(self.checkout) for p in self.checkout.rglob("*") if p.is_file()}, paths_before)

    def test_verify_refuses_unpatched_without_changing_it(self):
        with self.assertRaisesRegex(ValueError, "has not been applied"):
            self.run_mode("verify")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_unknown_modifications_are_never_overwritten(self):
        self.target.write_bytes(self.before + b"// local change\n")
        modified = self.target.read_bytes()
        for mode in ("apply", "verify"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "refusing overwrite"):
                self.run_mode(mode)
            self.assertEqual(self.target.read_bytes(), modified)

    def test_patch_hash_mismatch_refuses_before_source_write(self):
        self.patch_file.write_bytes(self.patch_file.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Patch file hash"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_wrong_upstream_head_refuses_before_source_write(self):
        (self.checkout / ".git/HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "HEAD does not match"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_context_and_declared_output_are_both_checked(self):
        patch = self.patch_file.read_bytes().replace(b"-int phase = 0;", b"-int phase = 9;")
        self.patch_file.write_bytes(patch)
        self.data["files"][0]["patch_sha256_lf"] = patcher.digest(patch)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "context differs"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_wrong_declared_output_hash_refuses_before_source_write(self):
        self.data["files"][0]["after_sha256_lf"] = "0" * 64
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "output hash"):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_crlf_source_preserves_checkout_line_endings(self):
        self.target.write_bytes(self.before.replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_mode("apply")["status"], "applied")
        self.assertEqual(self.target.read_bytes(), self.after.replace(b"\n", b"\r\n"))
        self.assertEqual(self.run_mode("verify")["status"], "verified")

    def test_escaped_path_and_extra_patch_file_are_rejected(self):
        self.data["files"][0]["path"] = "../outside.cpp"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Unsafe relative path"):
            self.run_mode("apply")
        self.data["files"][0]["path"] = self.relative
        patch = self.patch_file.read_bytes() + b"--- a/other.cpp\n+++ b/other.cpp\n@@ -1 +1 @@\n-old\n+new\n"
        self.patch_file.write_bytes(patch)
        self.data["files"][0]["patch_sha256_lf"] = patcher.digest(patch)
        self.write_manifest()
        with self.assertRaises(ValueError):
            self.run_mode("apply")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertFalse((self.checkout / "other.cpp").exists())


class RecordedPatchTests(unittest.TestCase):
    def test_formal_patch_hash_and_base_commit_match_recorded_dependencies(self):
        manifest_file = ROOT / "cmake/patches/tracktion/manifest.json"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        dependencies = json.loads((ROOT / "cmake/dependencies.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["upstream_commit"], dependencies["tracktion"]["commit"])
        self.assertEqual(manifest["hash_normalization"], "utf8-lf")
        self.assertEqual(manifest["schema"], 2)
        self.assertEqual({entry["path"] for entry in manifest["files"]}, {
            "modules/tracktion_engine/playback/graph/tracktion_WaveNode.cpp",
            "modules/tracktion_engine/plugins/external/tracktion_ExternalAutomatableParameter.h",
            "modules/juce/modules/juce_audio_processors/format_types/juce_VST3Common.h",
            "modules/juce/modules/juce_audio_processors/format_types/juce_VST3PluginFormat.cpp",
            "modules/tracktion_engine/model/edit/tracktion_Edit.h",
            "modules/tracktion_engine/model/edit/tracktion_Edit.cpp",
            "modules/tracktion_engine/playback/graph/tracktion_ClickNode.cpp",
            "modules/tracktion_engine/playback/tracktion_TransportControl.cpp",
            "modules/tracktion_engine/playback/devices/tracktion_MidiInputDevice.cpp",
            "modules/tracktion_engine/playback/devices/tracktion_InputDevice.cpp",
            "modules/tracktion_engine/playback/devices/tracktion_InputDevice.h",
            "modules/tracktion_engine/playback/graph/tracktion_EditNodeBuilder.cpp",
            "modules/tracktion_engine/playback/graph/tracktion_LiveMidiInjectingNode.cpp"})
        self.assertEqual(len(manifest["files"]), 13)
        for entry in manifest["files"]:
            patch = patcher.inside(manifest_file.parent, entry["patch"]).read_bytes()
            self.assertEqual(patcher.digest(patch), entry["patch_sha256_lf"])
            self.assertNotEqual(entry["before_sha256_lf"], entry["after_sha256_lf"])
            self.assertTrue(patcher.normalized(patch).startswith(("--- a/" + entry["path"] + "\n+++ b/" + entry["path"] + "\n").encode()))


if __name__ == "__main__":
    unittest.main()
