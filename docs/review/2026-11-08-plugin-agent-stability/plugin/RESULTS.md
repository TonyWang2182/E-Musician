# Plug-in compatibility results

2026-11-08. This is a bounded compatibility audit, not a promise that every plug-in, preset, authorization state or native editor works.

## Changes and root-cause boundaries

- The user clarified that **BM-COZY 2.2.1** crashes while adding from Library / Add plugin. The isolated control path did not reproduce that incident.
- A concrete Library callback lifetime defect was found: `WorkspaceBrowser::activate` passed a reference into `filtered`; `activateLibrary` called `showResult` / `refreshSnapshot`, which rebuilt that vector before `kind` was read again. The UI fix copies the item and callback before dispatch. The Add-plugin callback also rechecks its `SafePointer` after third-party initialization and report callbacks, which can process messages or destroy the panel. These are demonstrated ownership defects; they do not prove that the reported crash had exactly this stack.
- VST2 discovery no longer treats a dependency DLL inside a VST3 bundle as a plug-in. Existing erroneous `REX Shared Library.dll` cache data is filtered, without deleting files.
- A recorded Groove Agent SE metadata worker returned the standard `bundle/Contents/x86_64-win/<same-name>.vst3` binary path. The host previously rejected it at scan-time despite accepting that exact alias at runtime. The scanner now accepts only the existing exact alias rule, canonicalizes the catalog to the top-level bundle and retains class IDs/format. This does not enable arbitrary subpaths or name-based substitution.

## Full inventory run

Run `bd46d280f4`, `2026-11-08T06:57:19Z` through `07:13:42Z`: **53 modules discovered and attempted; 42 passed the complete host probe, 11 did not**. Discovery covers the host's five default roots and pre-existing custom catalog paths; unknown custom folders and 32-bit bridging are not covered. Every available module in this run had one descriptor, so no additional classes were silently treated as tested.

The full run used the first 0.13.2 Release EXE, SHA-256 `8ca1cff8826fd8910d8e3e73b92cfb631006de556e00da2a58c49f69a72a9728`, preserved at `build/plugin-compat/installed-0.13.2/E-musician-audited.exe`. Final UI and scan-alias fixes require the focused follow-up below. These are separate executable revisions.

Each probe tested scan → exact identity → add → parameter read → native-state save → reopen → two-second stereo 48 kHz PCM16 export → orderly host exit. There was no hardware playback or visible editor. Forty-two complete passes comprise **37 nonzero renders and 5 silent renders**. The latter are SWAM Cello 3, SWAM Violin 3, Kontakt 7 VST3, HALion Sonic SE and Ample Guitar PF. This verifies host lifecycle/file output only; empty presets, expression controllers, content activation and audible musical output remain unverified.

Initial failures:

| Modules | Observed boundary | Action / limitation |
| --- | --- | --- |
| Groove Agent SE, Padshop, Retrologue VST3 | Scan rejected descriptor path | Exact bundle alias fix; focused final-build retest required. |
| SWAM Double Bass 3 / Viola 3, both 3.8.2 | Export output was successfully produced, then the control host exited before the client received completion | Two matching Windows crashes/dumps preserved; exact failure cause unresolved. See [read-only lifecycle review](../agent/SWAM-READONLY-REVIEW.md). Do not call this a renderer/DSP crash. |
| Ample Bass A VST2 | Scanner exceeded 30 seconds | No subsequent stages ran; timeout is not proof of incompatibility. No automatic retry loop. |
| Ample Guitar SJ VST2 3.3.0.0 | Add/read/save passed; reopened slot became a missing placeholder | Original `.emproj` and 42,491-byte state retained. The saved envelope is valid: program 0, 0-in/2-out, 41,535 native bytes and 232 raw parameters. Catalog path, version and class IDs match. UI exposes 139 automatable parameters; that difference is not data corruption. Loading currently discards the detailed instantiate error, so the exact cause is unconfirmed. |
| Keyscape, Omnisphere, MPC Beats64, Kontakt 7 Portable **VST2** | Host refused the requested mono/stereo bus layout | No crash observed. Do not change DSP routing/state format speculatively. Keyscape and Omnisphere declare 18 outputs; corresponding VST3 versions, and Kontakt VST3, passed this probe. Prefer those tested VST3 builds. |

## BM-COZY-specific evidence

- Baseline 0.13.1 (`a2d9b0f308`): add, 129-parameter read, native-state save/reopen and nonzero export passed.
- First 0.13.2 (`af620bf810`): the same complete path passed. Optional editor construction/hidden-peer ownership/teardown passed, but JUCE may defer `IPlugView::attached` until visible; this is not visible editor or real HWND-attachment acceptance.
- Existing live-device stopped-state add (`0694337853`): **DirectSound / AirPods Pro, 44.1 kHz, actual 2,560-frame buffer**, empty MIDI track, master -60 dB, no playback/editor, 10 seconds of graph settling, orderly close. Settings were restored byte-for-byte to SHA-256 `8aac406f74a9bb7f40221c3b7dbde537db671ca76f98f29263bdc9bb45d7cea8` after normal engine shutdown rewrote them.
- M-Audio M-Track ASIO remains **not verified**: the driver name is installed, but `Get-PnpDevice -PresentOnly` found no matching connected device; nine historical endpoints/devices were `Unknown`. No attempt was made to force-open absent hardware.

## Evidence and repeatability

Raw inventory, per-stage JSON, process exit/deadline data, catalog backup, `.emproj` fixtures, native states, WAVs and isolated logs: `build/plugin-compat/installed-0.13.2/`. Crashes: `crash-evidence/` inside that directory. No plug-in binary, preset library or user project was deleted or modified.

The child supervisor uses one module at a time and a Windows Job Object to terminate only its owned process tree on timeout. Discovery/catalog preservation, actual grandchild timeout cleanup, normal completion and exact-identity quarantine tests passed **4/4** (`7623e6d098`). Initial fixture/probe mistakes and their corrected reruns are retained in [PLAN](PLAN.md), not erased from build history.

## Focused final build and quarantine

Final EXE SHA-256 `06dc0946bb4ff13dc04f99388388064d034ed904035184dfc1b4fa774670b925`: focused run `b52b363926` passed **4/4**, covering Groove Agent SE, Padshop, Retrologue and BM-COZY. All four passed scan/add/state round-trip/export/teardown; Groove Agent SE and Padshop produced silent defaults, while Retrologue and COZY produced nonzero PCM. The strict instantiate identity check did not need loosening.

Cumulative evidence is therefore **45 complete paths out of 53**, comprising **38 nonzero renders and 7 silent defaults**, with **8 unresolved/incomplete/refused paths**. This combines the initial full run and focused follow-up; it is not a 53-module rerun of the final EXE. The [module-by-module matrix](COMPATIBILITY.md) and [machine-readable evidence](COMPATIBILITY.json) retain the tested EXE hash for each entry.

Quarantine run `5fccf26dee` marked only the exact audited IDs of SWAM Double Bass 3 and Viola 3 unavailable. All identities, native state/project files and other entries were preserved. The pre-quarantine catalog is retained in `build/plugin-compat/swam-quarantine/catalog-before.json`; the resulting catalog SHA-256 is `3347b70212cc9579a3a31244ce74351e854b97bcc1c8895e994be881e35fdc56`. The final catalog has 53 descriptors, 50 metadata-available entries, two quarantines and one scan timeout. Metadata availability is not a compatibility pass. Explicitly rescanning a quarantined module clears its local block without establishing that the crash is fixed.

Third-party processing/editors remain in the normal DAW process; validation does not provide realtime crash isolation. Neither SWAM failure nor Ample SJ restoration was speculatively patched or described as fixed.

## Manual verification

1. Launch the final candidate, create a MIDI track, add **BM-COZY VST3** once from Library and once from Add plugin. Wait for loading to finish; check that the device chain and selection remain responsive.
2. Choose a factory sound, draw a short MIDI clip, play, save, reopen and export. Actual mouse/editor operation and listening are still needed.
3. With M-Track connected, select its ASIO driver and repeat the add/play steps at the displayed actual sample rate/buffer. This is a separate hardware acceptance step.
4. Select the **VST3** versions of Keyscape / Omnisphere / Kontakt when duplicates appear in Library. Do not interpret a successful metadata scan as proof of preset playback.
5. Keep the two quarantined SWAM modules out of working projects until their control-host failure is diagnosed. An explicit rescan clears the local quarantine; it does not establish that the crash is fixed.
