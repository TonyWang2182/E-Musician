# Recording-enhanced V2 — 2026-11-27

Branch: `fix/recording-ruler-interaction-v2`. Baseline: `000bda0`. Begin after the sax animation task. Preserve the original 0.13.6 and recording-enhanced binaries, user projects and unrelated local changes.

## Scope and ownership

- Ruler agent: EditGrid, core tests, ArrangementView and PianoRoll. Deterministic cadence, tick alignment and recording-safe selection/navigation.
- Recording agent: MainComponent, track/plugin/native panels, EngineSession command permissions and capture tests. Separate navigation, audited scalar controls and protected graph changes.
- Independent reviewer: read-only engine/thread and ruler review. Flagged third-party latency changes and initial PCM test limitations; both inform the implementation and tests.
- Root: integration, isolated output, recorded builds/tests, rendered fixture review, documentation and delivery. Never configure/build the shared cache concurrently.

## Acceptance

1. Musical ruler cadence uses 1/2/4/8… bars anchored to the origin; closer zoom keeps three naming tiers. Labels stay attached to ticks through pan/resize. Seconds use 1/2/5 decimal intervals. Snap and project coordinates remain unchanged.
2. Recording permits track/clip selection, scroll/zoom, existing VST/native editors and audited native-effect/mixer controls. Target/input/graph changes, clip writes and history remain protected. Finalization allows reads/navigation while the complete take enters one Undo transaction.
3. A bounded independent fake-device producer feeds the real recorder/writer during UI work and a deliberate message-thread pause. Check PCM, target identity, finalization guards and Stop/Undo/Redo, without presenting this as hardware latency or listening evidence.
4. Run Release configuration/build and CTest through `scripts/dev_showcase.py recording-v2`. Preserve every attempt, raw log, source fingerprint and dependency revision. Review actual rendered ruler fixtures and protected binary hashes.
5. Deliver `bin-0.13.6-recording-v2` through a separate launch entry after checks pass. Physical M-Audio, other interfaces, long takes, VST GUI behavior and listening remain in MANUAL-CHECK.md.

## Boundaries

VST editors stay on the required JUCE message thread. Vendor code or latency-changing controls may block/reconfigure their processing path; this revision adds no plugin-process isolation. Generic third-party parameter writes are not classified as safe recording edits. No network/model/file work enters the audio callback. No SSH/API, Jianying or computer-use is required. See the recording-navigation ADR and RESULTS.md.

## Iteration outcome

Implementation, recorded Release builds, corrected offline integration tests, four rendered-image reviews, protected-file hashes and the isolated launcher are complete. Original failed/interrupted receipts remain preserved. Results and exact scope are in RESULTS.md and EVIDENCE.json. Physical audio, long-take and vendor-window acceptance remain open in MANUAL-CHECK.md.
