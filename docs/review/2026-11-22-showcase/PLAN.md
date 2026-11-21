# Recording display and four-minute showcase

Status: implemented and automatically checked; physical microphone/hearing acceptance remains with the user. Date: 2026-11-22 Asia/Shanghai. Baseline: 0c41caa, branch feature/showcase-recording-v1. Existing DEVLOG edits and pre-existing untracked build receipts are user-owned and preserved. Final artifact inventory and film evidence: [DELIVERY.md](DELIVERY.md). Build/test failures and limits: [RESULTS.md](RESULTS.md).

## Deliverables and ownership

- Recording agent: engine-backed transient live recording thumbnails, arrangement rendering, stop/adoption lifecycle and tests; RECORDING.md.
- Replay agent: isolated native build/profile, fixed English planner and offline workers, original candidate validation/Preview/Apply/Undo, tests; REPLAY.md.
- Film agent: six text-free animated backgrounds, original-logo opener/closer, detailed English storyboard and separate Chinese translation, local speech/subtitles and editable sources.
- Root: three-project/source bundle, build/test evidence, integration, recording/replay validation, capture/edit pipeline, consolidated documentation and delivery.

## Boundaries

No SSH, paid/model APIs, cloud jobs, Jianying, computer-use skill, virtual audio driver installation or edits to original user projects. Preserve original 0.13.6 executable and file associations. New recording and showcase executables use distinct output folders. The user will record the sax scene and provide the performance footage. Until then an abstract, replaceable visual is allowed, but it is not a real recording/performance claim.

The showcase uses real historical model artifacts through real DAW candidate acceptance. It is not a new inference or model-language evaluation. Waits are configurable pacing (YuE2/ACE/SCNet/chords/beats/transcription: 20/15/12/8/6/10 seconds), not benchmark evidence. Provenance and limitations remain in internal delivery/development records. No demo watermark in the app/movie; narration must not assert live computation or measured latency.

## Timeline and packaging

240 seconds: opening 0-18; generation 18-66; separation 66-94; chords 94-122; Warp 122-142; piano transcription 142-168; original production 168-228; close 228-240. Three resettable starting projects only: New ideas (90 BPM), New Light (24 s excerpt, project 120 BPM), Tea for Two (16 s piano, project 120 BPM).

Deliver under E:/MusicAgent&DAW/demo-video/showcase-v1. Source, tests and documentation in Git; large media and confidential source projects remain outside Git. Rendering uses local tools and original procedural artwork. Microsoft Zira supplies replaceable English narration. 1080p30, 48 kHz output audio; subtitles and no-narration version separately.

## Acceptance

Live recording: real single/stereo/In2 and per-track behavior, count-in/nonzero start, monitor independence, finalizing/clip handoff, cancel/error/project lifecycle, save/reopen/undo. Compare deterministic PCM peaks/time; physical microphone listening stays user acceptance. No new audio-callback peak/disk/UI work.

Replay: offline three-project sequence, source identity, Preview/Apply/Undo/Redo, manual chords application, real Warp alignment, MIDI plugin audition, cancellation/stale/missing/corrupt result refusal. No network-provider fallback and no credentials. Test successful and rejected operations separately.

Each actual build/test attempt is recorded via dev_showcase.py/Recorder with raw build-logs and tracked docs/builds summaries. DEVLOG is append-only. Final capture/render waits for prerequisite builds/assets; sax actual-recording shot remains explicitly pending in the edit manifest until supplied by user.
