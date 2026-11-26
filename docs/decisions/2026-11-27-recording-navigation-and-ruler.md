# Recording navigation and deterministic rulers

Date: 2026-11-27. Status: implemented and automatically verified; physical hardware and vendor GUI acceptance pending.

## Problem

The workspace used `recording || finalizing` as a blanket component-disable flag. This prevented selecting tracks, opening existing devices and browsing the piano roll even when those actions did not change capture targets. Ruler text was centred and clamped inside the viewport; collision suppression then omitted individual labels, producing an apparent irregular bar cadence.

## Decision

Separate navigation, audited scalar edits and capture-graph changes. Track/clip selection, scroll, zoom and existing device editors remain available during recording. Gain, pan, mute/solo, colour/name and native effect parameters use the existing common command pipeline. Recording input bindings, device lifecycle/routing, clip edits, project/history operations and transport relocation remain protected. Finalization allows navigation and reads, but blocks musical mutations until the complete take has been adopted into its own Undo transaction. Stop closes mixer/effect drafts before that transaction begins.

Do not allow generic third-party `set_plugin_parameter` during capture. A seemingly scalar vendor control can alter latency and trigger Tracktion playback graph reconstruction. Existing VST editors still open on the JUCE message thread, as required by their UI contract; vendor code may block that thread or initiate its own latency changes. This revision does not introduce plugin-process isolation or promise every vendor GUI is nonblocking.

Keep ruler labels independent from the edit/snap grid. Measure labels before enumerating a uniform cadence; musical overview strides are 1, 2, 4, 8… bars anchored to the song origin. Closer zoom retains the three existing bar/beat/subdivision naming tiers. Seconds use 1/2/5 decimal strides. Place each label four pixels to the right of its own tick, clipping at the viewport instead of shifting it onto a different time. Wider labels increase the whole cadence, never skip arbitrary interior labels.

## Evidence and limits

The integration plan includes drawing fixtures, layout assertions, guarded command tests and a concurrent fake-device producer feeding the real recorder/writer while the message thread operates controls and pauses. This checks recorded PCM continuity, ownership and Undo boundaries, not physical ASIO timing or acoustic quality. Build/test outcomes belong in the [iteration record](../review/2026-11-27-recording-interaction/RESULTS.md); hardware and vendor-editor testing remain in the [manual checklist](../review/2026-11-27-recording-interaction/MANUAL-CHECK.md).

The new output directory is `E:/emusician-analysis-build/bin-0.13.6-recording-v2`; original 0.13.6 and recording-enhanced binaries remain unchanged. GUI and Agent still share authoritative state and command gates; no network/model/file work is added to the audio callback.
