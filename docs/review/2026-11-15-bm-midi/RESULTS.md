# 0.13.5 BM plug-in and per-track MIDI results

Status: implemented and automatically verified on the final Release executable. Physical keyboard playing, listening, and manual preset/editor interaction remain pending. The user's original BM crash stack was not reproduced; confirmed host defects and tested compatibility are distinguished below.

Baseline: `bcad8f043a5290a1196fb7fc0d61a07ff14ee077`; branch: `fix/bm-midi-isolation-v0135`. Version 0.13.4 and user projects were preserved. Tests used disposable owned processes, without paid model or cloud calls.

Machine/configuration: Windows 11 x64, Intel Core i7-13700H, Release; generated Hosted MIDI/PCM uses 48 kHz / 256 frames and a diagnostic source-aware instrument. The ASIO run and installed-module rendering have separate configurations below. No real-time latency or maximum-load performance claim is made.

## Changes delivered

- **Plug-in add lifetime:** PluginPanel starts native initialization through a message-thread trampoline after its one-shot timer returns. Vendor nested message loops cannot re-enter that timer and duplicate the add. Safe pointers and catalog/revision checks remain. A 450 ms nested-loop regression requires one completion.
- **Control-operation serialization:** Re-entrant commands cannot replace/delete an Edit during native plug-in calls or job commits. GUI/panel timers avoid intermediate state, close is guarded, and ControlServer queues requests while busy. This is an in-process lifetime fix, not a third-party plug-in sandbox.
- **Bounded busy-read handling:** Stdio and embedded clients retry only an explicit read-only command list after a matching, completed `busy` response, within the original deadline. Writes, unknown commands, mismatched responses, and ambiguous transport failures are not retried.
- **Independent Monitor/Rec:** Each track has Off/On; legacy Auto maps to Off. Rec never enables monitoring. Shared-device monitor changes require a track target; device-only requests require exactly one assigned track. Recording requires that track's Rec and active global recording.
- **Targeted note release and immediate Off:** Input/Monitor changes release only the affected target's held notes/pedals. Empty instrument tracks retain a stable input-injection node through graph rebuilds. Pending graph changes are dispatched before Monitor Off returns, preventing new keys from entering the old live graph.

Input/Monitor/Rec changes during recording/finalization are rejected while the take continues. MIDI 1.0 cannot universally distinguish simultaneous clip/keyboard voices with the same channel and pitch; these fixes do not claim arbitrary per-voice separation or MPE behavior. Details: [plug-in results](plugin/RESULTS.md), [MIDI implementation](MIDI-IMPLEMENTATION.md), [audit](AUDIT.md), [manual checks](MANUAL-CHECK.md).

## Final evidence

| Check | Recorded run | Result |
| --- | --- | --- |
| Final Release build | `441bbdd301` | Passed |
| Production regression | `0e29a8c611` | 461 suite checks passed, including generated PCM/capture and immediate Monitor Off; not 461 MIDI matrix cases |
| CTest | `5978acfb5f` | 11/11 passed, 108.46 seconds |
| Agent suite | `941c78f583` | 390/390 passed, including nine busy-policy tests; no paid requests |
| Installed BM audit | `c26fcd7ab7` | 14/14 native editor/state/render and actual Library/Add/Open/Remove handler checks; all 14 rendered nonzero PCM |
| ASIO lifecycle | `9cbee19f9b` | BM-COZY passed on M-Audio M-Track Solo and Duo ASIO, 44,100 Hz / 512 frames, SL GRAND input selected |
| Artifact verification | `d3be2030a0` | 133 native inputs, 25 helper inputs, 13 dependency patches; final EXE matches BM audit, old EXE preserved |
| Project association/icon | `6b88b3f1b6` | Existing E-musician handler/icon points to 0.13.5; two icon groups; Windows UserChoice preserved |

The 133-input count describes source/dependency verification, not tests or files changed. See [VERIFICATION.json](VERIFICATION.json) and [ASSOCIATION.json](ASSOCIATION.json).

Final EXE: `E:/emusician-analysis-build/bin-0.13.5/Release/E-musician.exe`.
SHA-256: `d7ccb64ef704d1f29a81ce893d66e86ffc379202a3af62b275c68267fdc093eb`.

The installed 2.2.1 audit covered BM-BERSERK, CIRCUITS, COZY, DOPE, EDEN, GLORY, HUSTLE, HYPE, IDOL, KANDY, NEMESIS, RICO, VICE, and VOID. Each passed exact-catalog add, visible native editor attachment/close, saved-state reopen, two-second 48 kHz stereo PCM16 render, and normal exit. A separate real UI-handler harness checked duplicate-add suppression, one slot/revision, and removal. This does not establish every preset, authorization interaction, editor gesture, or future version as compatible. Raw evidence: `build/bm-midi/final-all-bm-build4/audit.json`.

The live ASIO run used the real MainWindow/timers/native editor, 12 Monitor/Arm transitions, and save/remove/undo/new/reopen/editor-open/exit in 25.05 seconds. Transport stayed stopped, master was -60 dB, and no physical playing/listening occurred. Settings.xml was restored byte-for-byte and the catalog was unchanged. Evidence: `build/bm-midi/final-cozy-asio-lifecycle/report.json` and `supervisor.json`. This is lifecycle evidence, not an audible performance or latency benchmark.

## Failure and correction history

1. Configure `a9309fbb24` rejected stale patched dependency sources. `c80b9bdeff` verified old hashes, backed up exactly three cached files, restored their pinned sources, and applied the then-current 11-entry manifest; configure `db4581f247` passed. No whole-cache reset or user-file replacement. Release `cf6bc45158` was an intermediate build, superseded by the final frozen build.
2. Production `2857ee4cc5` failed PCM matrix case 1 because its diagnostic plug-in bypassed Edit PluginCache and was not attached by PluginList. The fixture was corrected to use its registered BuiltInType/cache factory with attachment assertions; this was a fixture error, not proof of a product routing defect. Workspace `4a28e4ef75` passed nested-loop/lifetime checks.
3. Two empty-track injection patches grew the manifest from 11 to 13. `697076db51` rejected it before writes at the old limit of 12. After raising the bounded limit to 16, `59cdab8a60` applied all 13; `5015f51e0b` passed 15 integrity tests, including 13 accepted/17 rejected before writes. `70b57237d8` verified the five MIDI patches against pinned source hashes.
4. Release `28d3a4bdb8` and production `ceefdc7811` passed 458 settled checks. After targeted rebuild `2e12ddff5e`, rapid probe `5d716dce73` exposed a real immediate-Off defect: eligibility was false but a channel-3 key could enter the old graph before a message-loop turn, with nine NoteOns/eight NoteOffs and left PCM 0.025059. Synchronous pending-graph dispatch fixed this; final `0e29a8c611` passed 461 checks including `immediate_monitor_off_boundary`.
5. Actual-UI COZY `6b483bdac5` passed. Initial wider audit `c5c6789db8` hit seven read-`busy` protocol failures at reopen (BERSERK, CIRCUITS, COZY, DOPE, EDEN, GLORY, HUSTLE), not native crashes. The owned supervisor was stopped; HYPE was cancelled and six others were unattempted. See `build/bm-midi/final-all-bm-editors-ui/interruption.json`.
6. Native queueing and bounded read-only retries corrected that integration issue. Focused COZY `48a82737e8` passed state/reopen and UI checks. Agent runs `6cd1e5edf1` (prior 381) and `7e1563c6f4` (new nine) passed; final standard discovery `941c78f583` includes all 390. Final build/audit/ASIO evidence in the table supersedes intermediate passes.

## Launch and remaining acceptance

- Launch: [Start E-musician 0.13.5.cmd](<E:/MusicAgent&DAW/Start E-musician 0.13.5.cmd>).
- VS Code: [E-musician-0.13.5.code-workspace](<E:/MusicAgent&DAW/E-musician-0.13.5.code-workspace>).
- Old EXE remains at `E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe`.
- Next: [MANUAL-CHECK.md](MANUAL-CHECK.md) with the physical keyboard, real presets, and listening; user acceptance is not yet claimed.
- Repository publication/main status is tracked separately in [PUBLISH.md](PUBLISH.md).
