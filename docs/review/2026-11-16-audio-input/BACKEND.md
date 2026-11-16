# Audio input backend contract and findings

Status: implemented and verified by the final Release build, 11/11 CTest (1004 production assertions), and the recorded M-Audio input/file lifecycle checks. See [final results and evidence boundaries](RESULTS.md); microphone source, listening, vendor-panel operation and other physical interfaces remain separate acceptance items.

## Confirmed source causes

- `OutputOnlyBehaviour::shouldOpenAudioInputByDefault()` starts JUCE with zero input channels. In the pinned JUCE `AudioDeviceManager::setAudioDeviceSetup`, an explicit mask changes `numInputChansNeeded`; `useDefaultInputChannels=true` subsequently reuses that mutable count, including zero. It does not mean “enable this interface's inputs.”
- Tracktion's wave input enable flag is separate from JUCE's physical channel mask. `WaveInputDevice::setEnabled` updates Tracktion routing only. Visible/enabled In 1/In 2 could therefore deliver no physical samples.
- Standard Tracktion wave IDs hash the channel description. Two-channel cards are renamed Input 1/Input 2, so two different interfaces can have identical native IDs.
- The audit found a separate sparse callback mapping defect: JUCE's active channel pointers are packed, while the pinned Tracktion wave reader indexes physical channels. The dependency patch and null-buffer clearing are owned by the audit/root work; this backend retains physical indices in its metadata.

The fixed dependency source provides the direct evidence: JUCE `audio_io/juce_AudioDeviceManager.cpp` uses `updateSetupChannels` with mutable `numInputChansNeeded` (lines 710–727, 792–794 in the pinned source); Tracktion `playback/devices/tracktion_WaveInputDevice.cpp::setEnabled` only calls `setWaveInChannelsEnabled`. Its constructor derives `wavein_` from `desc.name.hashCode()`, while `DeviceManager::AvailableWaveDeviceList::describeStandardDevices` replaces a two-channel device's names with Input 1/Input 2. None of these paths tests physical input activation before the previous application's arm operation.

## Commands and readback

`configure_audio_device` continues to accept driver/device names, rate and buffer. `input_channels` is an array of distinct finite integer physical indices, validated against the opened device and verified against its actual active mask. Explicit `[]` disables audio input. Arming/monitoring a disabled physical route gives an Audio Settings error and does not enable it implicitly.

`input_stereo_pairs` is an optional array of even zero-based starting indices: `[0,2]` groups 1–2 and 3–4; `[]` exposes independent mono routes. Both channels must exist and be active. Same-input-device omission preserves channels/pairs; disabling half of an existing pair restores its mono routes. A changed input device/backend defaults to the first up to two physical inputs and mono grouping. A changed device resets unspecified rate/buffer for driver selection. Explicit rate/buffer/mask rejection rolls back and verifies the actual previous state; failure to restore is reported separately.

Rollback forces the saved physical masks to explicit mode. Reusing a saved `useDefaultInputChannels=true` flag after an invalid candidate would otherwise reuse that candidate's newly changed JUCE channel count. A fake test covers invalid `[2]` from the initial default-mode/zero-input state.

Backends reporting `hasSeparateInputsAndOutputs=false` reject conflicting nonempty input/output device names with an instruction to use `device_name` or matching names. This is required for identity correctness: the pinned JUCE ASIO `createDevice` only asserts name equality in Debug, then chooses the output name in Release (lines 1519–1527). A stale input name must not identify a different physical card selected by its output name. The fake test confirms rejection preserves the actual card and public input ID.

`get_audio_devices` adds `device_open`, `has_control_panel`, `active_input_channels: number[]`, and `input_stereo_pairs: number[]`; existing `input_channels[{index,name,active}]` remains authoritative actual readback.

`show_audio_driver_panel` has empty arguments, uses the current device's `hasControlPanel/showControlPanel`, and rejects playback, recording and finalization. Its boolean return is treated as JUCE's restart request, not as proof that a window was shown. After the native callback the device is reacquired, the channel graph refreshed, and root returns actual capabilities. No device pointer is retained across the callback. Recorder reentry/polling is guarded while a native driver is changing configuration; the existing root control-operation guard remains in place.

Before either configuration or a native panel, physical audio targets are detached and the silent input graph is synchronously published. Only matching public input identities with active channels regain their prior arm/monitor binding after completion or rollback. This closes the intermediate callback window in which Tracktion could otherwise reuse a colliding native channel hash on a new card. MIDI targets are not detached. The fake driver's open and panel callbacks assert this ordering.

## Input identity and project compatibility

Audio input `id` values now use `audioin_` plus SHA-256 of backend name, input device name, physical indices and their driver names. They persist through the existing `input_device_id` string field without a schema migration. The catalog also includes native `engine_id`, `channels`, `stereo`, `physical_active`, and `available`; `enabled` remains the separate Tracktion routing flag. `get_recording_state.tracks[].input_available` means identity present and `physical_active` reports channel activation separately.

Changing interface/backend cannot bind an old qualified ID to an unrelated Input 1. The saved unavailable selection stays visible for explicit reselection. Legacy physical `wavein_` IDs cannot prove interface identity and require reselection; they are not guessed from labels. Isolated Hosted regression fixtures retain legacy compatibility. MIDI IDs, per-track monitoring and recording isolation are unchanged. Telemetry resolves the qualified identity through `RecordingController::inputForId` on the control thread.

Two physically indistinguishable units exposing the same backend/device/channel names cannot be distinguished beyond what JUCE exposes; no vendor-specific serial-number assumption is introduced.

## Added synthetic evidence path

`EngineSessionAudioInputSmoke.inc` is included in the existing production suite. It installs only fake JUCE device types into an offline in-memory session. It exercises zero-input startup, strict masks and driver refusal/rollback, sparse activation, later stereo pairs, mono/stereo captured WAV PCM, packed and full-slot callbacks, missing input/oversized blocks, same-name native ID collisions, unavailable persisted identity, independent Monitor/Arm, unsupported panels and native callback reentry/readback. Existing Hosted audio/MIDI suites remain registered.

The backend agent did not launch builds or tests; root's [recorded integration run](../../builds/20261116T140509.115591Z-5b4346fc6f.json) reached all six PCM cases. The local `build/smoke/Release/eed445053ca2/audio-input-capture-report.json` reports these exact middle-half means at 48 kHz:

| Physical route and callback | WAV channels | Frames | Expected and measured mean |
| --- | ---: | ---: | --- |
| In 2, packed one-pointer callback | 1 | 16,384 | −0.625 |
| In 2, full physical slots `[null, signal]` | 1 | 16,384 | −0.625 |
| In 2, missing input pointer, 512-sample callback | 1 | 32,768 | 0 |
| In 1 with both physical channels active | 1 | 16,384 | 0.25 |
| In 2 with both physical channels active | 1 | 16,384 | −0.625 |
| Stereo In 1–2 | 2 | 16,384 | 0.25, −0.625 |

That run remained failed overall (10/11 CTest): the final playback guard fixture called `EngineSession::execute("play")`, whereas transport is routed through `togglePlay`/`stop` by the public control wrapper. The fixture now uses those actual transport methods and asserts playback is running before checking the panel guard; the final suite passed, as recorded in [RESULTS](RESULTS.md). PCM tolerance stays 0.001 and has not been weakened.

An earlier run (`build/smoke/Release/ad8d374e87cd`) passed packed In 2 exactly but the second repeated take had 16,128 leading zero samples followed by 16,128 samples of −0.625. The fake clock was stopped between explicit callback injections; its queued seek had not executed before the next take. This is distinct from channel mapping: the native record path posts the preroll position then calls `EditPlaybackContext::blockUntilSyncPointChange` before deriving its punch SyncPoint (`TransportControl.cpp`, around 1535–1555). That method waits for reference-sample advancement for at most 100 ms (`EditPlaybackContext.cpp::blockUntilSyncPointChange`). A synchronously pumped fake cannot advance while that control-thread call waits. The fixture now supplies stopped callbacks before preparing each repeated take and asserts native position is exactly zero; the subsequent six reports all show `settled_position=0` and the correct lengths/means. Continuous hardware callback behavior is validated separately, and this correction is not claimed as a production seek/record change.

These synthetic results cannot establish real microphone signal, vendor panel behavior, another manufacturer's compatibility, or listening quality; root's final result record identifies executed checks and their limits.
