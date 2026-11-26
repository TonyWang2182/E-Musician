# Recording-enhanced V2 verification

Date: 2026-11-27. Status: implemented and automatically verified; physical audio/VST GUI and listening acceptance remain pending.

## Changes

- Arrangement and piano rulers measure label width first, choose one regular cadence and anchor text to its own tick. The previous centred/clamped label could push bar 1 away from its grid and suppress bar 3 in a 1/3/5 cadence.
- Recording no longer disables the whole Arrangement, piano roll or device panels. Existing device browsing/opening and audited mix/native-effect controls remain usable; recording targets, topology, clip writes and history remain protected.
- Finalization is a separate mutation barrier. Stop closes parameter previews before adopting a complete take; reads and navigation remain available.

## Review

Independent source review found a real limit in generic third-party parameters: a vendor latency change can restart the Tracktion playback graph. `set_plugin_parameter` therefore remains outside the capture allowlist. Native effect previews publish existing atomic state and were not found to rebuild the graph. Existing VST editors still run vendor GUI code on the required message thread; arbitrary third-party GUI responsiveness is not guaranteed.

An initial test review also found that constant-DC samples and a loose length bound could not reliably identify missing/repeated blocks. The regression now uses sequenced stereo PCM from frame zero, measured concurrent Stop boundaries, exact command-gate errors and separate active effect/mixer gesture cases. The earlier implementation is not used as evidence of exact sample preservation.

## Build and test evidence

- Configure `20261126T211512.904886Z-ff05fcd0bc`: passed, 125.34 s.
- First build `20261126T211727.502599Z-3a59d599bd`: deliberately stopped before linking to incorporate stricter tests and switch to two compile jobs. Original receipt remains failed/exit 1; no compiler failure was reported before the interruption.
- Release build `20261126T213101.217942Z-a9903d01e0`: passed, 1602.24 s, unchanged source inputs during the command.
- First CTest `20261126T215751.525341Z-4029eb0108`: 10/11 passed. New recording test failed at the expected adopted-clip count. The two test helpers iterated `fixture.snapshot().tracks.back().clips`; under C++20, the reference returned by `back()` did not keep the temporary Snapshot alive. Both helpers now retain a named Snapshot; count/PCM assertions remain strict, with additional adoption diagnostics and no speculative wait.
- Independent examination of the failed case's actual WAV: 48 kHz, stereo PCM24, 3072 frames; both channels match their encoded sequence from frame zero with zero mismatches. This supports diagnosis of the test helper, not a claim that the remaining assertions already passed.
- Subsequent incremental rebuilds and targeted runtime validation passed, as detailed below. Configure/build/test commands and raw logs use `scripts/dev_showcase.py recording-v2`. No physical audio driver, third-party editor, SSH or model API has been tested in this iteration.

## Reproducibility

- Windows x64, Intel Core i7-13700H (14 cores / 20 logical processors), approximately 29.7 GiB RAM.
- Release, Visual Studio 18 2026, two build jobs after the first intentionally stopped one-job attempt. Exact commands and source-file fingerprints are stored in each receipt.
- Tracktion Engine 3.2.0 at `b0c7dd090a56b27fe01bb394617891906eb34daf` with the repository's verified local patches.
- JUCE 8.0.6 at `19edd538429c93d277bf95b55aaa7e3eb545f951`.
- Offline capture fixture: 48 kHz stereo, 256-sample blocks, fake JUCE device feeding the real recorder/WAV writer. It is functional evidence, not an ASIO latency/CPU or acoustic-quality benchmark.
- Isolated output: `E:/emusician-analysis-build/bin-0.13.6-recording-v2/Release/E-musician.exe`. Earlier binaries are protected by baseline SHA-256 hashes.

## Manual acceptance

Use [MANUAL-CHECK.md](MANUAL-CHECK.md) for the physical microphone, actual M-Audio configuration, other interfaces, long recordings and normal VST windows. Listening, UI stalls and captured file continuity must be assessed separately. No absolute claim of all-plugin stability or measured real-time performance is made.


## Final validation and delivery

- Incremental build `20261126T220426.442191Z-541238ab32` passed (241.67 s); engine integration `20261126T220838.328508Z-084433fbd3` passed (203.47 s native test).
- Visual inspection found three opaque-black Arrangement ruler PNGs: the test encoded before destroying its Graphics context. Only the screenshot fixture was changed to flush drawing before inspection/encoding and require background plus text pixels. The production ruler renderer was unchanged.
- Final Release build `20261126T221550.116842Z-35f6e68369` passed (92.49 s); final targeted engine integration `20261126T221741.062225Z-e4fb920826` passed (182.83 s including recorder overhead). Final build/test fingerprints match across 440 inputs; neither changed during execution.
- The first full CTest run passed 10/11. Its failed engine suite subsequently passed after the two test-only corrections above. This is cumulative coverage of all 11 suites, not a claim of a new single full 11/11 run. The two changed files since that full-tested build contain only those test corrections.
- Final production checks: 1268 passed. Ruler layout and nonempty rendered-pixel cases: 54 passed. Recording-safe Arrangement/Piano/plugin-browser/selected-device checks, Stop/finalization gates, native-effect and mixer Undo isolation passed.
- Fake-device capture and UI work ran concurrently at 48 kHz / 256 frames. The sequenced PCM is checked from frame zero; callbacks continue across Stop and only frames before capture detachment belong in the take. Exact counters are retained in [capture evidence](evidence/recording-interaction-capture.json). This short functional fixture is not a long-recording or real-time benchmark.
- Preserved original 0.13.6 EXE, previous recording-enhanced EXE and previous launcher match all three baseline hashes. New launcher: `E:/MusicAgent&DAW/Start E-musician Recording v2.cmd`. Save and close an older instance first; no forced process termination, file-association change or automatic GUI launch was performed.
- New EXE SHA-256: `772d1a3ddc30c0b8f1b231f9270750301fe6b5c47aca0d44d4a8daf1de0da372`. Fingerprints, preserved files and final report paths: [EVIDENCE.json](EVIDENCE.json). The existing `pwsh.exe is not recognized` post-build output is nonfatal; recorded CMake/MSBuild exit code is zero.
- Actual ruler PNGs in `evidence/` were opened and visually reviewed after the final test: bars show 1/3/5/7…/15 at their ticks; both adds corresponding 4-second increments; seconds shows regular 5-second increments. The far-position piano ruler keeps its labels at their tick anchors without overlap. All four images contain the expected paper/grid/text rather than blank pixels. Existing whole-workspace fixture `build/workspace-smoke/c9a1634592ee/ui-workspace-brand-1440x900.png` was also inspected and aligned.
- No hardware capture, ASIO performance, actual third-party editor launch or audible quality claim is added. Use the manual checklist for these remaining checks.
