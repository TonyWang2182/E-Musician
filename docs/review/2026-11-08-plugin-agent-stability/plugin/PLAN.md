# Installed plug-in compatibility audit

Status: host fixes and diagnostics implemented; full initial audit and focused final-build checks complete. Physical M-Track / editor listening acceptance and eight failed/incomplete/refused module paths remain open; see [RESULTS](RESULTS.md).

The reported “coze” resolves to installed **uJAM BM-COZY 2.2.1 VST3** at `C:/Program Files/Common Files/VST3/uJAM/BM-COZY.vst3`. No recent matching Application Error/WER record or crash dump was found in the first eight-hour check. An old 2026-11-02 dump is unrelated evidence until analysed; it is not treated as this incident.

The user subsequently clarified that the crash occurs while adding BM-COZY from Library / Add plugin. Both GUI paths use `session.execute("add_plugin", ...)`; Add plugin defers the call by 50 ms for its loading indicator and does not automatically open the editor. The matching follow-up is therefore stopped-state add with the user's existing audio device, not visible editor automation.

## Scope and evidence levels

1. Enumerate the host's five default VST2/VST3 roots and existing catalog paths. Discovery found 53 top-level modules. Ten UJAM modules were absent from the old catalog. Unknown arbitrary custom paths and 32-bit bridging are outside scope.
2. Back up the existing catalog before updating it. Exclude VST3 bundle interiors: `REX Shared Library.dll` was incorrectly listed as a separate VST2 plug-in in the old catalog. Host discovery, explicit scan requests, cache reads and child workers now reject such identities.
3. For each module, use a separate offline DAW child for actual scan, exact catalog identity, instantiate, parameter read, save, reopen, two-second stereo 48 kHz PCM16 render, and teardown. An unconfigured instrument may render silence; the report records this separately.
4. Use a second optional diagnostic child for editor creation, hidden native peer ownership and teardown. The user-facing editor is never displayed. JUCE may defer `IPlugView::attached` until visibility changes, so this does not prove a plug-in's native view attached. This is explicitly not a visible GUI interaction, sample-library, authorization, preset, ASIO or listening acceptance test.
5. A Windows Job Object bounds each owned subprocess tree. One module runs at a time; timeout/crash is recorded once, not retried indefinitely. Every stage persists to JSON before entering third-party code, with raw logs retained under ignored `build/plugin-compat/`.

The DAW still loads VST processing/editors in its own process during normal use. An isolated validation pass cannot make arbitrary third-party native code crash-proof. A true realtime plug-in bridge remains separate engineering work.

## Implemented tools

- `tests/InstalledPluginProbe.py`: single-module host/control-path checks without hardware audio or a visible editor.
- `tests/InstalledPluginAudit.py`: discovery, catalog backup, sequential child supervisor, bounded descendant cleanup, durable per-module results.
- `tests/InstalledPluginAuditTests.py`: bundle/dependency discovery, source catalog preservation, and actual timeout/descendant termination regression checks.
- Existing `--plugin-scan-worker FORMAT MODULE OUTPUT --probe-editor`: opt-in isolated editor diagnostic, not added to ordinary scans.
- `tests/InstalledPluginLiveInit.py`: explicitly named plug-in, real existing audio-device initialization, no playback/editor, stopped graph settling, deadline and original device-settings preservation. Must have exclusive hardware-test time.

## Baseline

On 0.13.1, BM-COZY passed instantiate, 129-parameter read, native state save/reopen, non-silent two-second 48 kHz render and process close. Record `20261108T064628.115384Z-a2d9b0f308`. Its reported opening crash has **not yet been reproduced**. The earlier probe failure (`50c98b29da`) was the probe's wrong `.emusician` project extension, corrected to `.emproj`; it was not a host defect.

Supervisor regression checks passed 3/3 in `20261108T065108.438739Z-4f235f39a8`. The first fixture used unescaped `&` in XML (`618666e50f`); ElementTree serialization corrected the fixture and the rerun passed. Neither run loaded an installed plug-in.

Final audit evidence, quarantine, remaining limits and manual checks are recorded in [RESULTS](RESULTS.md) and [COMPATIBILITY](COMPATIBILITY.md).
