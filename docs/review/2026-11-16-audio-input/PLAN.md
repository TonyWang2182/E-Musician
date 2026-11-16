# 0.13.6 audio input and driver settings

Status: implemented; Release, CTest 11/11, six exact PCM cases, settings interaction/captures and M-Audio short capture/persistence checks passed. Voice/listening, vendor panel gestures, other physical interfaces and longer sessions remain manual acceptance. See RESULTS.md and VERIFICATION.json for evidence, failed attempts and boundaries.

Baseline: 6a822251bed996a927d575881b05f93a32125457; branch fix/audio-input-v0136.
Worktree: E:/MusicAgent&DAW/worktrees/audio-analysis. Preserve 0.13.5, user projects, existing DEVLOG edits and 30 pre-existing untracked build records.

## Scope

1. Diagnose physical driver input channels separately from Tracktion's logical input routes. A visible In 1/In 2 label is not proof that the driver is delivering input.
2. Add usable channel activation and mono/stereo grouping controls with draft Apply and actual readback. ASIO uses one duplex device; separate-device backends retain independent input/output selection.
3. Expose the active driver's native control panel where supported, keep native dialog lifetime out of timers, reject changes during playback/recording, reacquire current device after the callback.
4. Support driver/interface replacement without retaining incompatible masks/timing, preserve explicit same-device settings, surface unavailable track inputs, and keep per-track Monitor/Rec independent.
5. Build isolated 0.13.6, validate synthetic audio capture, bad configuration rollback, settings interactions, existing MIDI regressions, and available M-Audio device lifecycle. Physical microphone signal/listening remains a separate user check.

## Ownership

- audio_input_backend: EngineSessionRecording.inc, portable configuration helper and dedicated native audio-input smoke; BACKEND.md.
- audio_input_ui: AudioSettingsPanel and showAudioSettings only in MainComponent.cpp, required UiLanguage strings, UI.md and UI smoke/captures.
- audio_input_audit: independent source audit, owned hardware-probe script, AUDIT.md. No unsolicited user-GUI interaction.
- root: public command registration, version/build runner, integration, recorded builds/tests, documentation, source review and publication.

Every build/test command uses scripts/dev_audio_input.py, raw logs under ignored build-logs and summaries under docs/builds. Tests and API configuration success are not listening acceptance. No model service or cloud changes are included.
