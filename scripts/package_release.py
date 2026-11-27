"""Stage a Windows runtime package from an existing, real-provider Release build.

Python and the WebView2 Runtime are installed separately. Model weights, API
credentials, user projects, SDKs and replay fixtures never enter this package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from dev import Recorder, ROOT, source_git_head


RUNTIME_FILES = (
    "dev.py", "run_agent.py", "agent_client.py", "runtime_paths.py",
    "setup_analysis.py", "cloud/compute_client.py", "cloud/run_analysis.py",
    "cloud/run_generation.py", "cloud/run_compute_generation.py",
    "cloud/register_compute.py", "cloud/register_generation.py",
)
RUNTIME_TREES = ("music_agent", "audio_analysis")
RUNTIME_SUFFIXES = {".py", ".js", ".css", ".html", ".txt"}
PUBLIC_DOCUMENTS = (
    "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "CONTRIBUTING.md",
    "docs/BUILD.md", "docs/CONFIGURATION.md", "docs/MODELS.md", "docs/MODEL-ASSETS.md",
    "docs/ARCHITECTURE.md", "docs/VALIDATION.md",
    "assets/brand/README.md", "assets/brand/yi-yue-shi-logo.png",
    "cmake/dependencies.json", "cmake/signalsmith.json", "cmake/webview2.json",
    "tests/fixtures/AUDIO-LICENSE.txt",
)


def cache_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith(("#", "//")) and "=" in line:
            key, value = line.split("=", 1)
            values[key.split(":", 1)[0]] = value
    return values


def enabled(value: str) -> bool:
    return value.upper() not in ("", "0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND")


def package(build_dir: Path, destination: Path) -> dict:
    build_dir = build_dir.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Output already exists; choose a new directory. Existing packages are never overwritten.")
    cache = cache_values(build_dir / "CMakeCache.txt")
    if Path(cache.get("CMAKE_HOME_DIRECTORY", "")).resolve() != ROOT.resolve():
        raise ValueError("The build directory belongs to a different source tree.")
    if enabled(cache.get("EMUSICIAN_ENABLE_VST2", "OFF")):
        raise ValueError("Public packaging requires the default VST3 build; VST2 distribution is not handled here.")
    if enabled(cache.get("EMUSICIAN_SHOWCASE", "OFF")):
        raise ValueError("Offline replay builds are not public runtime packages.")
    match = re.search(r"project\(EMusician VERSION ([0-9.]+) ", (ROOT / "CMakeLists.txt").read_text(encoding="utf-8"))
    if not match:
        raise ValueError("Application version is missing from CMakeLists.txt.")
    version = match.group(1)
    executable = Path(cache.get("EMUSICIAN_RUNTIME_OUTPUT_ROOT", str(build_dir / "bin"))) / "Release" / "E-musician.exe"
    if not executable.is_file() or executable.is_symlink():
        raise ValueError("Build the Release executable before packaging.")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("The Release artifact is not a Windows executable.")

    # Assemble the entire allowlist before writing, so a missing source or
    # licence produces no partial output directory.
    copies = [(executable, Path("E-musician.exe"))]
    for relative in RUNTIME_FILES:
        copies.append((ROOT / "scripts" / relative, Path("runtime/scripts") / relative))
    for tree in RUNTIME_TREES:
        for source in sorted((ROOT / "scripts" / tree).rglob("*")):
            if (source.is_file() and source.suffix in RUNTIME_SUFFIXES
                    and "__pycache__" not in source.parts and source.name != "replay_provider.py"):
                copies.append((source, Path("runtime/scripts") / source.relative_to(ROOT / "scripts")))
    for name in PUBLIC_DOCUMENTS:
        copies.append((ROOT / name, Path(name)))
    for source in sorted((ROOT / "docs/licenses").rglob("*")):
        if source.is_file():
            copies.append((source, source.relative_to(ROOT)))
    for source, _ in copies:
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or linked package input: {source}")
        if destination == source or destination in source.parents:
            raise ValueError("The output must not contain a package source input.")

    destination.mkdir(parents=True)
    for source, relative in copies:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    metadata = {"schema_version": 1, "version": version, "platform": "windows-x64",
                "source_revision": source_git_head(), "python": "3.10 or newer, installed separately",
                "providers": "user-configured; no model weights or credentials bundled"}
    (destination / "runtime/package.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    manifest = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            manifest[path.relative_to(destination).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in manifest.items()), encoding="utf-8")
    return {**metadata, "directory": str(destination), "file_count": len(manifest), "executable_sha256": manifest["E-musician.exe"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        return Recorder("package-release", "Release", "Portable runtime staging; does not build or verify device playback").execute(
            [sys.executable, __file__, "--worker", "--build-dir", str(args.build_dir.resolve()), "--output", str(args.output.resolve())]).returncode
    try:
        print(json.dumps(package(args.build_dir, args.output), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Package failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
