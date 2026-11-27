# Release validation

E-musician 0.13.7 was built and checked on Windows x64 on November 28, 2026.
The Release build uses CMake 4.2.3, Visual Studio 2026 / MSVC 19.50, Windows SDK
10.0.26100, JUCE 8.0.6 and Tracktion Engine 3.2.0. Python checks used CPython 3.14.

| Check | Result |
| --- | --- |
| Native CTest suite | 12 passed: DSP, instruments, engine, project storage, workspace and control isolation |
| Recording and arrangement checks within the engine suite | 1,268 passed with generated buffers at 48 kHz / 256 samples |
| Agent unit tests | 394 passed |
| Agent against the real offline DAW | 18 passed: proposals, apply, readback, Undo and stale-state rejection |
| Headless sidebar web checks | 34 passed across analysis, generation, hybrid tasks and task flow |
| Cloud protocol tests | 60 run; two Linux-only cases skipped on Windows |
| Portable runtime configuration | Six passed |
| Relocated package: native window, WebView and helper | 24 passed; packaged helper path confirmed |
| Relocated helper HTTP and settings | Assets loaded; OpenAI reasoning setting survived restart; zero provider calls |
| Public source audit | No Chinese source text, detected credential material or maintainer paths |

The first native build exposed missing UI helper functions; these were restored
before the passing build. Two test harness assumptions were corrected for English
wording and nested launch-log locations. Detailed command records remain local;
the concise [release record](https://github.com/TonyWang2182/E-Musician/blob/main/docs/builds/release-0.13.7.json)
includes build attempts and exact dependency revisions.

Physical audio interfaces, microphones, third-party plugin editors, paid APIs,
GPU model inference and listening quality were not retested for this packaging
release. Cloud transport tests use fixtures; they do not establish model quality.

Executable SHA-256:
`e05dfdd428b0777357462215d1a8327926a677443231e549407f0c2902e11314`.
