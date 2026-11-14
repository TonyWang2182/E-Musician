# Per-track MIDI isolation implementation

Status: implemented and verified by the final hosted production run (461 checks, record `0e29a8c611`). Physical MIDI/ASIO and vendor-instrument listening acceptance remain separate. Overall build/CTest/plugin results are recorded in the parent RESULTS.

## Contract

| Monitor | Rec/Arm | Live keyboard | Captured during global recording |
|---|---|---|---|
| Off | Off | Silent | No |
| On | Off | Audible | No |
| Off | On | Silent | Yes |
| On | On | Audible | Yes |

Input must be assigned to the destination track. Two tracks explicitly set to On with the same keyboard intentionally both sound. Selecting another track never grants monitoring or recording. MIDI clips play independently of input monitoring. Recording input/monitor configuration remains protected while a take is active or finalizing; a rejected change must leave the take running.

## Control boundary

`set_input_monitor` writes one track's transient `emMonitorMode`, retains its independent arm flag and rebuilds only that Edit. It never changes the shared physical device monitor mode. The legacy `auto` input is accepted as canonical `off`; the UI exposes Off and On. `monitor_scope` is `track`.

The command dispatches the Edit's pending graph update synchronously before returning. Tracktion's normal restart uses a one-millisecond message timer; that left a reproducible interval in which a key arriving after Off entered the old live-input graph and remained held when that graph disappeared. Graph preparation stays on the control thread and uses Tracktion's existing graph publication mechanism. This does not add work to the audio/MIDI callback or claim that publication is a universal audio-thread barrier.

A legacy device-only request is accepted only when exactly one track is assigned that device. A shared device requires `track_id`. If both IDs are supplied, they must describe the same assigned input. Invalid/ambiguous requests do not broadcast a change.

## Dependency contract

The pinned Tracktion commit remains `b0c7dd090a56b27fe01bb394617891906eb34daf`. The checked-in patch manifest records exact upstream, patched-output and patch hashes.

- `per-track-monitor.patch`: live-node eligibility follows explicit On, including when armed. Native unmanaged Tracktion behavior remains the fallback.
- `per-track-midi-release.patch`: adds a message-thread target-specific cleanup hook, a no-op for non-MIDI inputs.
- `recording-midi-controller-boundary.patch`: preserves its prior controller-boundary fix and adds MIDI cleanup with fixed-capacity source-ID/pedal bookkeeping. Turning a destination Off or removing it releases held notes/pedals on that destination only. Incoming source IDs and the physical-node channel remapping are retained. No device-wide all-notes-off, global note-state clear or blanket plugin reset is used.
- `empty-instrument-midi-injection.patch` and `stable-empty-midi-injection-id.patch`: create a stable MIDI injection path for managed instrument tracks with a synth and no clips. The original engine otherwise drops injected cleanup messages when no clip node exists. The added silent path is excluded from offline rendering and unrelated audio tracks. Stable identity carries queued cleanup across a monitor graph rebuild; existing clip-node identities are unchanged.

The previous removal listener sent note-offs to the remaining destinations, potentially cutting another track's held notes. Cleanup now addresses the removed destination ID. It does not rely on destination-list membership inside the removal callback, because another listener may have removed that list entry already.

## Verification scope

`tests/EngineSessionMidiIsolationSmoke.inc` runs through the real hosted audio graph at 48 kHz / 256 samples with a deterministic diagnostic instrument. It records separate left/right PCM for all 16 combinations of two monitors and two arm flags, including MIDI channels 1 and 16. It also checks destination-only held-note and sustain cleanup, input detachment, rejected ambiguous requests, recordings in both directions, no take on an unarmed track, the active-take guard, Undo, and continued sequence playback after turning live input Off. Existing production tests retain recording, persistence and reopen coverage, with old Auto expectations updated.

The diagnostic instrument is a test fixture, not an installed native device. Hosted PCM/capture verifies graph behavior; it does not replace M-Audio/ASIO, physical keyboard, UJAM or Keyscape listening tests.

Final runtime evidence is preserved in [MIDI-MATRIX.json](MIDI-MATRIX.json) and [MIDI-PRODUCTION-SUMMARY.json](MIDI-PRODUCTION-SUMMARY.json). All 16 combinations passed: each Off side produced exactly zero PCM and each On side produced a 0.025059361 peak, independently of Rec/Arm. Target-only held-note/pedal release, input removal, both recording directions, sequence continuation, and the immediate-Off command-boundary regression passed. The summary's 461 checks cover the complete production suite, not 461 distinct MIDI scenarios.

The note cleanup is still based on input-level held-key state. A target enabled in the middle of a held key may not have received its onset. MIDI 1.0 instruments may also merge a keyboard voice and clip voice with the same channel/pitch. Separate-pitch sequence continuation is explicitly tested; universal same-pitch voice separation and all vendor MPE implementations are not claimed.

## Recorded preparation checks

- `docs/builds/20261114T171049.882961Z-7861eaf3d2.json`: all three MIDI patches applied in memory to their exact pinned sources; upstream, patch and output hashes passed; `git diff --check` passed.
- `docs/builds/20261114T171118.235189Z-c80b9bdeff.json`: after the initial configure rejected stale patched source, verified the old hashes of exactly three cached files, backed up their bytes, restored only those files to the pinned source, then applied/verified the full 11-entry manifest. No whole dependency reset and no user files changed.
- First native matrix attempt (`2857ee4cc5`) failed at case 1 because the diagnostic plugin was allocated directly instead of being registered/created through the Edit plugin cache; the plugin was never attached to the audio graph. The corrected fixture uses a local built-in factory and explicit attachment checks, and now writes detailed graph/PCM/input/probe diagnostics on failure. This was a fixture defect, not evidence of a product routing failure.
- Adding the empty-track injection fixes grew the final manifest to **13 entries**, superseding the earlier 11-entry preparation state. Attempt `697076db51` was rejected before writes by the patcher's old 12-entry limit. The bounded schema-2 limit is now 16; all file/hash/path checks remain. `59cdab8a60` applied and verified all 13 entries; `5015f51e0b` passed 15 patch-integrity tests, including 13 accepted entries and 17 rejected before any write; `70b57237d8` passed exact pinned-source application and all hashes for the final five MIDI patches.
- Native production run `ceefdc7811` passed 458 checks, including the settled 16-way hosted matrix and target release/record/clip cases. Adding a bounded immediate-Off regression then exposed a real product failure in `5d716dce73`: despite left eligibility being false, a new channel-3 key sent without pumping the message timer produced 0.025059 PCM on both sides; the left diagnostic instrument had nine NoteOns and only eight NoteOffs. After the synchronous dispatch fix, final run `0e29a8c611` exited 0 with 461 checks and `immediate_monitor_off_boundary: true`. Physical callback concurrency stress remains separate from this deterministic hosted regression.

Native compile/test evidence is added by the parent build owner. The older configure failure is retained, not overwritten.
