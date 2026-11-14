# BM native editor and host lifetime investigation

Date: 2026-11-15 Asia/Shanghai (raw records use UTC on 2026-11-14).

## Scope and ownership

- User reports BM family plug-ins crash when opening/adding. Audit the restored 14 UJAM BM VST3 modules, especially BM-COZY.
- Preserve all installed binaries, sample libraries, user projects, credentials and settings. Use fresh disposable projects and supervised owned processes. No GUI automation or paid/model service calls.
- Plugin investigation owns the PluginPanel block in MainComponent.cpp and installed-plugin probe scripts. Root owns shared session reentrancy protection, version/build orchestration and top-level documents. MIDI isolation is a separate coordinated change.

## Sequence

1. Read previous 2026-11-08 compatibility evidence and inspect installed modules, content references and available crash evidence.
2. Establish 0.13.4 baseline using exact catalog identities: add, read parameters, actual production open_plugin window, save, new/reopen, two-second offline render, normal teardown. One module per bounded process tree.
3. Exercise COZY with real MainComponent/timers and the current M-Audio ASIO device. Keep transport stopped and master at -60 dB; do not claim playback/hearing acceptance. Exercise input/monitor/arm changes, editor-visible removal, undo, new and reopen. Restore Settings.xml byte-for-byte.
4. Fix concrete host reentrancy/lifetime defects only. Add a synthetic nested-message-loop regression and keep exact reported-crash attribution separate from host defect evidence.
5. Build through the root recorder, run relevant UI/engine checks, then repeat all 14 actual-window probes on the final executable. Report each phase, limitations and remaining manual tests.

## Test fixtures and retained attempts

- `build/bm-midi/baseline-cozy/`: initial relative output path failed at save (`An absolute file path is required.`), without a crash. Corrected test utility normalizes output paths. Record `20261114T165730.435961Z-7e6ea1711b`.
- `baseline-cozy-absolute/`: corrected non-editor baseline, record `20261114T165750.971010Z-042f86daa7`.
- `baseline-cozy-editor/`: actual open_plugin baseline, record `20261114T165924.904297Z-2a60ef24d2`.
- `baseline-other-bm-editors/`: remaining 13 actual-window baselines, record `20261114T170052.863404Z-69cacd06c3`.
- `baseline-cozy-live-editor/`: real ASIO/editor stopped probe, record `20261114T170158.025615Z-5299340f4f`.
- `baseline-cozy-gui-lifecycle/`: MainComponent/ASIO/editor lifetime probe, record `20261114T170737.103697Z-aea179374c`.

Every command is recorded by `scripts/dev_bm_midi.py command ...`; raw reports/logs are ignored local artifacts. No failed attempt is deleted or relabeled as a product crash.
