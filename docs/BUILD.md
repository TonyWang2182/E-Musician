# Build and package

The current source builds E-musician 0.13.7, including the latest recording and
ruler changes. It runs real local or user-configured remote providers. No fixed
replay package or private model service is required for ordinary DAW use.

## Windows prerequisites

- Windows x64 and Visual Studio 2022 or 2026 with Desktop development with C++
  and a Windows SDK. Other platforms have not been verified for this release.
- CMake 3.25 or newer; Visual Studio 2026 requires a CMake version that lists
  `Visual Studio 18 2026` in `cmake --help`.
- Git and Python 3.10 or newer on PATH.
- Microsoft Edge WebView2 Runtime for the embedded Agent interface. Bootstrap
  downloads the pinned development SDK; it does not install this runtime.

Use a short source/build path if the Windows toolchain encounters path limits.
The default `windows-msvc` preset lets CMake select an installed supported
Visual Studio generator. Explicit `windows-vs2022` and `windows-vs2026` presets
use separate directories under `build/`.

## Build and test

Run from the repository root:

```powershell
python scripts/dev.py bootstrap
python scripts/dev.py check --config Release
python scripts/check_agent.py --exe build/bin/Release/E-musician.exe
python scripts/dev.py run --config Release
```

To select a toolchain and a shorter build directory, use the same options for
each configure, build, test and run command:

```powershell
python scripts/dev.py check --config Release --preset windows-vs2026 --build-dir C:/emusician-build
python scripts/dev.py run --config Release --preset windows-vs2026 --build-dir C:/emusician-build
```

If a local directory junction provides a shorter source path, pass
`--source-dir C:/emusician-source` to configure/check. The script verifies that
the alias resolves to this source tree. Configure/build/test processes use
`<build-dir>/temp` for `TEMP` and `TMP`, keeping compiler scratch files on the
selected build drive.

`check` configures, builds and runs CTest. Commands, timestamps, exit status,
source fingerprints and raw output are recorded locally in `docs/builds/`,
`docs/DEVLOG.md` and `build-logs/`; all three are excluded from Git. Public release
results are summarized in [Validation](VALIDATION.md). Launching an application
is recorded separately from passing a test. Physical devices, third-party plugin
editors and listening require separate manual acceptance.

Bootstrap fetches the exact Tracktion/JUCE commits in `cmake/dependencies.json`,
applies the patches in `cmake/patches/`, verifies Signalsmith dependencies from
`cmake/signalsmith.json`, and installs the pinned ASIO headers and WebView2 SDK.
Dependency sources and SDK binaries stay in ignored `.cache/` and `_deps/`.
Existing unrecognized dependency changes are not overwritten.
To check an already prepared dependency tree without downloads or dependency
writes, run `python scripts/dev.py bootstrap --verify-only`. This is also the
appropriate check when deliberately reusing dependencies through local directory
junctions; ordinary bootstrap can write dependency configuration and unpack SDKs.

VST3 and ASIO are enabled by default. Legacy VST2 is disabled and no VST2 SDK
is downloaded. Users with their own licensed SDK can configure
`EMUSICIAN_ENABLE_VST2=ON` and `EMUSICIAN_VST2_SDK=<SDK root>` through a local
`CMakeUserPresets.json`. The SDK root must contain `pluginterfaces/vst2.x/`.
The public packaging command rejects VST2 builds. Review `THIRD_PARTY_NOTICES.md`
and the original dependency terms for distribution.

## Portable runtime package

After a successful Release build and tests:

```powershell
python scripts/package_release.py --build-dir build --output dist/E-musician-0.13.7-windows-x64
```

The command refuses to overwrite an existing directory. It stages the executable,
an explicit allowlist of Python helpers/web assets under `runtime/scripts/`,
license notices, build documentation and `SHA256SUMS`. It excludes model weights,
credentials, user projects, plugins, SDKs, debug symbols and old replay material.
Publish the corresponding source revision alongside any distributed binary.

Copy the whole resulting directory to the destination machine. Install Python
3.10+ and WebView2 Runtime there, then run `E-musician.exe`. The Agent resolves
the packaged scripts next to the executable. Set `EMUSICIAN_PYTHON` to an absolute
Python executable path if Python is not available on PATH. The package also
supports a separately supplied interpreter at `runtime/python/python.exe`.
No Python installer or model environment is included.

Agent preferences and credentials remain per-user. Packaged helper launch logs
are written to `%LOCALAPPDATA%/E-musician/runtime-logs/`; the package itself can
be read-only. Optional local analysis setup installs isolated environments and
weights separately. Remote model execution requires the user's own configured
endpoint. A successful package operation does not establish provider availability
or audio-device acceptance on another machine.
