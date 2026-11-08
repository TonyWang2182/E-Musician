# SWAM: read-only host/render lifecycle review

2026-11-08. This review reads existing audit artifacts, minidumps, WAV headers/data and fixed dependency sources. No plugin was launched again; no engine, catalog, user project or device configuration was changed. The existing audit failure remains unresolved and must not be reported as fixed.

## What the artifacts establish

Audit executable: `E:/emusician-analysis-build/bin-0.13.2/Release/E-musician.exe`, SHA-256 `8ca1cff8826fd8910d8e3e73b92cfb631006de556e00da2a58c49f69a72a9728`.

| Artifact under `build/plugin-compat/installed-0.13.2/` | Existing evidence |
| --- | --- |
| `004-b4e6bdd3b2/host/report.json` | SWAM Double Bass 3 / 3.8.2: instantiate, 112-parameter read, state save and reopen passed; `offline_render` stage ends with control stdout closed. |
| `005-c3634b56ae/host/report.json` | SWAM Viola 3 / 3.8.2: same successful checks, same control transport failure. |
| Both folders' `host/render.wav` | Python stdlib `wave` read confirms 48,000 Hz, 2 channels, 16-bit, 96,000 frames, all-zero PCM; file size 384,784 bytes. This verifies an output file, not audible instrument operation. |
| `crash-evidence/E-musician.exe.32936.dmp` | Exception `0xc0000374` in ntdll. UTF-16 `--control-stdio` at byte offset 3,991,876 and `--control-output-probe` at 3,991,908; no UTF-16 `--render-worker` match. |
| `crash-evidence/E-musician.exe.19220.dmp` | Exception `0xc0000005` at `0x7fff3ea6f847`, WER identifies SWAM Viola 3. UTF-16 `--control-stdio` at byte offset 1,932,644 and `--control-output-probe` at 1,932,676; no UTF-16 `--render-worker` match. |

WER's process creation times are 14:57:45.436 (PID 32936) and 14:58:00.688 (PID 19220); respective host report file creation times are 14:57:45.450 and 14:58:00.718. This corroborates the command-line evidence identifying the control host. A string scan is not a symbolized stack or PEB extraction, and does not identify the corrupting instruction.

The audit stage name is too broad to conclude that offline DSP crashed. `EngineSessionJobs.inc:330–331` permits moving the temporary render to the final requested path only after the isolated worker exits with code 0 and reports `completed`. Both fresh probe directories have that final WAV. Together with the dumps, the evidence supports **successful isolated output, followed by the control host failing while the client still awaited export completion**. It does not prove that the failure was specifically in job commit, plugin teardown or an asynchronous plugin callback.

## Lifecycle and block-size review

- `EngineSessionJobs.inc:619`: the live control host captures current plugin state before scheduling export. `PluginHost.cpp:827–876` performs that capture on the message thread; VST3 getState is not deliberately suspended. No evidence here shows that getState caused these failures.
- `EngineSessionJobs.inc:640,659`: the worker constructs a separate `EngineSession(false)`, restores a separate edit/plugin instance, and renders at the requested rate with maximum block size 512. The probe requests 48 kHz, 2 seconds. The worker does not borrow the live host's plugin pointers.
- `EngineSessionJobs.inc:377–402`: export worker retirement joins the completed job and publishes its status; unlike project import/open it has no edit-replacement commit.
- `EngineSession.cpp:338–343,509–517`: host destruction/adoption stops transport, removes plugin watchers and listeners, then destroys/replaces the edit. `PluginHost.cpp:1007` detaches watchers for that edit. Inspection found no export-specific second deletion or shared host/worker plugin ownership.
- Fixed Tracktion `plugins/external/tracktion_ExternalPlugin.cpp:1118–1184` prepares on first initialization or rate/block change. Its normal deinitialization clears the playhead rather than repeatedly calling releaseResources; do not add blanket release calls as a speculative fix, because MIDI bus activation is explicitly discussed in the existing code.
- Fixed JUCE `juce_audio_processors/format_types/juce_VST3PluginFormat.cpp:2785–2856` sets max samples, sample rate and processing mode while preparing. `2946–2952` already guards blocks beyond compatibility-buffer capacity. No artifact demonstrates a >512 block, rate mismatch or buffer overrun in these two cases.

## Separate, source-visible offline-mode risk

Dependencies: Tracktion `b0c7dd090a56b27fe01bb394617891906eb34daf` (3.2.0); JUCE `19edd538429c93d277bf95b55aaa7e3eb545f951` (8.0.6), plus the project's tracked patches. Paths below are inside `_deps/tracktion_engine/modules/`.

1. `tracktion_engine/model/export/tracktion_Renderer.cpp:128–148` constructs the render graph first.
2. `tracktion_engine/playback/graph/tracktion_PluginNode.cpp:49,278` initializes the plugin during node construction, calling ExternalPlugin's prepare path.
3. Only later, `tracktion_engine/playback/graph/tracktion_NodeRenderContext.cpp:136–139` sets `setNonRealtime(true)` for offline export and calls the graph's prepare method. `PluginNode.cpp:88` does not prepare the underlying plugin again.
4. JUCE `juce_audio_processors/format_types/juce_VST3PluginFormat.cpp:2795–2798` skips redundant prepare calls based on active state, rate and block size, without comparing the processing mode. `2811` passes the current mode to setupProcessing, while `2960` reads the current mode again for each process call.

Thus a fresh render instance can be set up as `kRealtime` before the flag changes, then receive `kOffline` process calls. This is a distinct compatibility risk worthy of a small contract-logging test plugin; it is **not an established cause of the two control-host crashes**. No speculative dependency patch was made.

## Next diagnostic boundary

Keep the two failed modules isolated from claims of supported operation. Preserve the successful output and original crash evidence. If a later bounded reproduction is authorized, record the control PID, render-worker PID, export acceptance/completion timestamps and final host exit code (the current report samples `poll()` too early and retains null). Capture a symbolized exception-thread stack before choosing a code fix. A separate purpose-built VST3 fixture can log setup/process mode, maximum/actual block size and lifecycle order without repeatedly crashing these commercial plugins.

The silent SWAM Cello/Violin successes also do not verify their musical output, licenses, expression-controller requirements, presets or live hardware behavior.
