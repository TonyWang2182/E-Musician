# BM host results

## State

Implemented and validated on final 0.13.5: all 14 installed BM modules passed actual GUI handlers, native editor lifecycle, state round-trip and offline PCM output. COZY also passed a real ASIO stopped-state/editor lifecycle probe. User's exact earlier crash stack was not reproduced; arbitrary editor gestures/presets and physical playing/listening remain manual acceptance.

## Confirmed host defect and fix

`PluginPanel::beginAdd` previously invoked native plug-in initialization directly inside JUCE `Timer::callAfterDelay`. In pinned JUCE 8.0.6, `LambdaInvoker::timerCallback` invokes the callback and only then deletes the timer. The timer remains registered during the call; `TimerThread` retries messages after 300 ms. A third-party nested message loop can therefore re-enter a nominally one-shot add before the outer callback returns. The same hazard was already documented and avoided by Main.cpp's smoke-test `after` helper, but the plug-in panel still used the unsafe form.

The panel now uses the delay only to queue a normal message callback and returns from the timer before native code runs. Existing SafePointer checks, copied catalog identity and optimistic project/revision checks remain. A regression exercises the actual delayed panel add with a 450 ms nested dispatcher and requires exactly one result callback. Root's companion session guard protects the shared command boundary from nested mutations; the panel timer also avoids snapshots while that control operation is busy.

This is a concrete host lifetime hazard and targeted fix, not proof that every user's BM crash had that stack. No speculative bus layout, state serialization, plug-in binary or authorization changes were made. Editors and realtime plug-ins still run in-process; bounded test processes are not a runtime sandbox.

## Baseline 0.13.4

Executable: `E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe`.
SHA-256: `c99d9b0894687f1066bc09febe9c4d6ee5afbc4e38413fac5d6620a101245d5a`.
Machine: Windows x64, Intel Core i7-13700H. All tested BM modules report version 2.2.1.

**14/14 completed** exact-identity add → parameter enumeration → actual production native window opening → three-second message loop → native-state save → new/reopen → two-second stereo 48 kHz PCM16 export → normal process exit. All 14 exports contain nonzero PCM; this does not establish musical quality or audible hardware playback. This baseline bypassed Library/Add-panel click handlers and therefore does not exercise their delayed callback.

Modules: BM-BERSERK, BM-CIRCUITS, BM-COZY, BM-DOPE, BM-EDEN, BM-GLORY, BM-HUSTLE, BM-HYPE, BM-IDOL, BM-KANDY, BM-NEMESIS, BM-RICO, BM-VICE, BM-VOID.

Actual native window creation is stronger evidence than the old hidden-parent/editor-construction probe. No editor mouse gestures, arbitrary factory presets or prolonged performance were tested. Initial editor initialization was visibly slow in the first COZY run; no precise per-stage latency instrumentation was recorded, so this is not a benchmark and not a proven crash cause.

## Real device and editor lifecycle baseline

COZY passed both stopped live-device probes. Actual device: **M-Audio M-Track Solo and Duo ASIO, 44,100 Hz, 512 frames**. Master -60 dB, no transport playback and no physical keyboard performance claim.

The broader probe enabled the actual MainComponent/timers, opened the native editor, assigned **SL GRAND** MIDI input, cycled 12 Arm/Monitor combinations, saved, removed the plug-in while the editor was open, undid removal, reopened the editor, created a new project, reopened the saved project/editor and exited normally. Its complete owned-process duration was 28.48 s; this includes startup, deliberate 10 s settle and native state loads, not an audio latency measurement.

Each live probe backed up Settings.xml, allowed normal shutdown, restored original bytes and verified SHA-256 `08049cfabe4ccb6a79157fb6b04b69fbe81ae98c9397cc643f14b3761f5cf38a`. Plug-in binaries and sample content were not edited or deleted. COZY's referenced part1/part2 content files existed. No matching E-musician/BM crash event was found in the inspected recent Application log window; this does not prove no crash occurred outside that window.

## Acceptance checklist

1. Verified: UI smoke reported `plugin_delayed_add_survives_nested_dispatch_once=true`, alongside existing lifetime/duplicate-click checks; root's final full CTest run passed.
2. Verified: final all-14 actual native window/state/render and GUI-handler probes; COZY GUI/ASIO lifecycle retest. Exact evidence follows below.
3. Manual acceptance: add BM-COZY from Library and Add plugin, choose a factory preset, play a clip and physical MIDI keyboard, then save/reopen. Repeat representative other BM devices. Human editor gesture and audible acceptance cannot be inferred from automated windows/PCM output.
4. Conditional follow-up: if the reported crash persists, preserve the exact phase, module version, fresh Windows crash module/offset and dump. Do not claim blanket compatibility or mask it by blacklisting every BM module.

## Actual GUI handler harness and intermediate protocol regression

The new `--plugin-ui-test <catalogId> <fresh-absolute-directory> --offline` harness uses no ControlStdio. It invokes the actual `activateLibrary` handler, opens/removes the installed native editor, then invokes Add-plugin panel Add twice, requires one committed slot/revision, and invokes panel Open/Remove with the editor open. MainComponent is attached to an offscreen visible native peer. No editor controls are clicked and no physical audio plays.

COZY passed this actual GUI path in intermediate 0.13.5 build 2, record `20261114T173008.688177Z-6b483bdac5`, 14.85 seconds, normal exit 0. The following full audit `20261114T173037.480873Z-c5c6789db8` exposed a **protocol regression**, not a plug-in crash: BERSERK, CIRCUITS, COZY, DOPE, EDEN, GLORY and HUSTLE each received a definite `busy` reply to a read during the reopen stage. After the seventh identical result, only the exact owned audit supervisor PID 53088 was stopped; Job Object closure cancelled HYPE's in-progress child. The remaining six modules were not attempted. Raw audit and `interruption.json` preserve these distinctions.

The native session's reentrancy guard correctly refuses reads of an intermediate Edit, but the transport was consuming queued polls too early. Root corrected ControlServer to leave requests queued while that operation is active. Both real Python transports now share bounded retry handling for a **fully consumed, matching `busy` read reply**: only explicit read-command whitelist entries, one original deadline, same request identity. Writes, unknown commands, mismatched replies and ambiguous transport failures are never retried. Permanent busy remains a refusal without poisoning an otherwise synchronized connection. This covers the embedded Agent as well as the CLI client and does not loosen native mutation protection.

Read-busy policy tests: 8/8 passed (`20261114T173529.652951Z-640d9bd67f`), including original-deadline exhaustion, no write retry, matching identity and both transport adapters. Existing embedded protocol/lifetime tests: 19/19 passed (`20261114T173535.999343Z-0f623948aa`). These are local fixtures, not provider/API calls. Final installed-module retest remains pending below.

Follow-up: the exact supported native-effect/selection/clipboard/analysis-annotation/recording-preference/warp reads were added to the whitelist. The new native-effect regression expands this to **9/9 passing** (`20261114T173707.442518Z-b7936621e8`). COZY's build-3 focused full control/native-editor/state/render plus actual Library/Add-panel callbacks passed (`20261114T173609.613158Z-48a82737e8`); the all-module final-build pass is still separate.

## Final 0.13.5 evidence

Final executable SHA-256: `d7ccb64ef704d1f29a81ce893d66e86ffc379202a3af62b275c68267fdc093eb`.

Full focused audit `20261114T174045.347487Z-c26fcd7ab7`, **2026-11-14 17:40:46Z–17:47:26Z**: **14/14 passed, 14 nonzero renders, 14 separate actual-GUI handler passes**, no deadlines exceeded and normal owned host exits. All modules listed in the baseline section were retested against this one final executable. Artifacts: `build/bm-midi/final-all-bm-build4/audit.json` and each module's host/GUI reports, logs, saved project/native state and rendered WAV. The versioned [compatibility matrix](COMPATIBILITY.json) retains baseline and final outcomes separately.

Final COZY live-device probe `20261114T174811.212163Z-9cbee19f9b`: **passed**, 25.05 s overall, actual M-Audio M-Track Solo and Duo ASIO / 44,100 Hz / 512 frames. The actual MainComponent/timers and native editor remained present during SL GRAND input assignment, twelve Arm/Monitor transitions, save, remove/undo, new/reopen and editor reopening. This test deliberately kept transport stopped/master -60 dB and did not perform physical keyboard playing or auditory evaluation. Artifacts: `build/bm-midi/final-cozy-asio-lifecycle/report.json`, `supervisor.json`, `live-host.log` and the owned project. Settings.xml was restored byte-for-byte; final catalog equals the audit's catalog-before bytes.

Final shared read-busy policy tests passed 9/9 after tightening the deadline check (`20261114T173757.952267Z-dd148447b4`). Root moved the test into default Agent discovery as `tests/test_music_agent_control_busy.py` and reran it successfully (`7e1563c6f4`). Existing embedded transport tests passed 19/19. No provider/API, model, paid service or cloud call was used for this investigation.
