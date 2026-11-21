# E-musician · 4-minute investor film — English production script

Date: 2026-11-22. Master: **04:00 / 240 seconds**, 16:9, 1920×1080, 30fps. English DAW interface throughout. The timings below are final edit time, not processing duration.

## Timing

| Section | Time | Duration |
|---|---|---|
| Opening | 00:00–00:18 | 18s |
| D1 · Two musical ideas | 00:18–01:06 | 48s |
| D1 · SCNet separation | 01:06–01:34 | 28s |
| D2 · Chord analysis | 01:34–02:02 | 28s |
| D2 · Beat and Warp | 02:02–02:22 | 20s |
| D3 · Piano to MIDI | 02:22–02:48 | 26s |
| D4 · Making music | 02:48–03:48 | 60s |
| Closing | 03:48–04:00 | 12s |

## Preparation

- Use the isolated showcase-v1 English build for New ideas, New Light and Tea for Two. Film the final production chapter in 0.13.6 from a copy of test drive, preserving the original.
- Rehearse Preview → Apply → Undo/Redo, project reset, source selection, and no doubled playback before recording.
- Capture at least 1080p30; higher-resolution capture gives room for crops. Record DAW output and microphone separately. Review a 10-second test: hearing ASIO output does not prove the screen recorder captured it.
- Preload Keyscape, BM-VOID and BM-HUSTLE. Do not scan plug-ins during the take. Configure the recording input, Arm and Monitor beforehand; only the intended track may record.
- Hide notifications, desktop overlays and floating pets. Keep real cursor/control states. Never reveal API keys, SSH credentials or personal files.
- Six chapter backgrounds occupy 0.6–1.0 seconds within the assigned slots. The eight-second opener is followed by ten seconds of actual UI preview; the closer is twelve seconds.
- Offline Microsoft Zira narration, per-shot WAVs, the 240-second voice track, English SRT and aligned Chinese SRT are editable. Keep marked audition shots free of voice and extra BGM.

## Shot-by-shot script

### O01 · 00:00–00:08

**Voice-over:** Meet E-musician: an open-source music workspace with an assistant built into the creative process.

**Action / picture:** Play opener-1080p30.mp4. Keep the approved tree-musician logo, product name and repository URL readable.

**Edit / sound:** Brand reveal; restrained slow light, no fast cuts.

### O02 · 00:08–00:18

**Voice-over:** Generate ideas, explore audio, and shape every detail. The software helps; the musical decisions remain yours.

**Action / picture:** Cut between the English arrangement, Agent result, chord track and piano roll. Use actual screen recordings from later chapters.

**Edit / sound:** Four 2–3-second previews; gentle instrumental bed under voice.

### G01 · 00:18–00:25

**Voice-over:** I start with a neo-soul idea and ask YuE2 for a vocal sketch.

**Action / picture:** Open New ideas, open Agent, paste P1 and send once. Keep the project at 90 BPM, 4/4, playhead zero.

**Edit / sound:** Use chapter-01-generation for 0.6 seconds, then zoom to prompt; trim typing pauses.

### G02 · 00:25–00:31

**Voice-over:** The result stays separate from my project until I choose to use it.

**Action / picture:** Hold on the working state; jump-cut or speed up the middle of the wait. End on the YuE2 result and Preview control.

**Edit / sound:** No stopwatch or speed claim. Keep cursor still after the click.

### G03 · 00:31–00:37

**Voice-over:** — Audition only; no narration —

**Action / picture:** Click Preview on YuE2 and listen for six seconds; stop preview before applying.

**Edit / sound:** No narration or extra music; retain actual candidate audio.

### G04 · 00:37–00:42

**Voice-over:** I apply this version, then request another interpretation with ACE.

**Action / picture:** Click Apply changes. Show the newly added YuE2 track. Paste P2 and send once without renaming the first track.

**Edit / sound:** Track insertion gets a brief emphasis; keep workflow in one project.

### G05 · 00:42–00:49

**Voice-over:** Both options use the same workspace, so I can compare them directly.

**Action / picture:** Show ACE processing and its result card. Do not apply until after audition.

**Edit / sound:** Compress only the wait; preserve Preview → Apply order.

### G06 · 00:49–00:55

**Voice-over:** — Audition only; no narration —

**Action / picture:** Click ACE Preview and listen for six seconds; stop preview.

**Edit / sound:** Match audition loudness in editing without changing the project result.

### G07 · 00:55–01:06

**Voice-over:** I prefer this one. I add it to the arrangement, then remove the first track myself.

**Action / picture:** Apply ACE. Select the YuE2 track header and delete that track, not the ACE clip. Leave ACE's existing name unchanged; select its audio clip.

**Edit / sound:** Show both tracks briefly, then the manual deletion and the remaining selected clip.

### S01 · 01:06–01:14

**Voice-over:** Next, I ask SCNet to separate the selected track into vocals, drums, bass, and other.

**Action / picture:** Keep the ACE source selected and its name unchanged. Send P3. Capture the working state and four-result proposal.

**Edit / sound:** 0.6-second chapter-02-separation transition, then the source selection and prompt.

### S02 · 01:14–01:20

**Voice-over:** I apply the four stems and mute the original.

**Action / picture:** Click Apply changes. Mute the original ACE track. Make sure no other source is audible. Enable Solo on drums first.

**Edit / sound:** Frame all four track headers; emphasize the original M button once.

### S03 · 01:20–01:34

**Voice-over:** — Audition only; no narration —

**Action / picture:** Audition drums, then add bass Solo, other Solo, and vocals Solo while retaining previous Solo states. Use roughly 3.5 seconds per layer.

**Edit / sound:** Continuous audio; no voice. Verify additive Solo behaviour before recording, and return all Solo switches off at the end.

### C01 · 01:34–01:39

**Voice-over:** — Audition only; no narration —

**Action / picture:** Open New Light, with its 24-second excerpt already imported. Play five seconds of the source.

**Edit / sound:** 0.6-second chapter-03-harmony transition included in this slot; source audio comes forward.

### C02 · 01:39–01:47

**Voice-over:** With an existing song, the assistant can estimate its harmony. I ask it to analyze New Light.

**Action / picture:** Stop playback, select the source clip, and send P4. Wait for the prepared chord analysis.

**Edit / sound:** Focus follows selection → prompt → result; do not claim perfect recognition.

### C03 · 01:47–01:54

**Voice-over:** Then I open Analysis and apply the result as an editable chord track.

**Action / picture:** Open the lower Analysis panel, choose the latest completed Chords result in Recent analyses, and apply it to a chord track. After rerunning analysis, close and reopen the list to refresh it.

**Edit / sound:** Keep the manual panel application visible; do not replace it with an Agent Apply shot.

### C04 · 01:54–02:02

**Voice-over:** The chords follow the timeline, so I can inspect them in the context of the music.

**Action / picture:** Play the source with the chord lane visible. Frame readable chord labels and the moving playhead.

**Edit / sound:** One slow crop that follows the relevant bars; no invented chord labels in post.

### W01 · 02:02–02:10

**Voice-over:** Next, I ask it to detect the beat and align this audio to the project's tempo.

**Action / picture:** Keep the same New Light project and source. Send P5; retain the 120 BPM project tempo and review the source tempo of 125 BPM.

**Edit / sound:** 0.6-second chapter-04-timing transition; emphasize 125 → 120 only after actual values appear.

### W02 · 02:10–02:15

**Voice-over:** I review the alignment and apply pitch-preserving Warp.

**Action / picture:** Click Apply changes. Open Source if needed and show Warp enabled, with source and target tempo visible.

**Edit / sound:** Do not say lossless or perfect. Keep the real changed clip alignment on screen.

### W03 · 02:15–02:22

**Voice-over:** — Audition only; no narration —

**Action / picture:** Audition the warped audio against the grid. Keep the chord track visible if it follows the accepted mapping.

**Edit / sound:** Seven seconds of audio, no narration; do not add a fake metronome or grid animation.

### T01 · 02:22–02:28

**Voice-over:** Here is an isolated piano performance from Tea for Two.

**Action / picture:** Open Tea for Two with the existing 16-second piano source. Briefly play the source, then select its clip.

**Edit / sound:** 0.6-second chapter-05-transcription transition; let the last two seconds be source audio.

### T02 · 02:28–02:35

**Voice-over:** I ask TransKun to turn the performance into editable MIDI.

**Action / picture:** Send P6. Capture working state and the completed MIDI proposal.

**Edit / sound:** Show the operation, not logs; no note-accuracy claim.

### T03 · 02:35–02:41

**Voice-over:** I apply the notes and load a piano instrument.

**Action / picture:** Apply changes, select the new MIDI track, and add the installed Keyscape piano through Library/Add plugin. Mute the source audio before the MIDI audition.

**Edit / sound:** Cut the instrument's loading wait; show actual loaded editor/preset and piano roll.

### T04 · 02:41–02:48

**Voice-over:** — Audition only; no narration —

**Action / picture:** Play the MIDI through the loaded piano. Frame the 132-note piano-roll result without implying perfect transcription.

**Edit / sound:** Seven seconds of MIDI piano audio only. Never substitute source audio for the MIDI output.

### D401 · 02:48–02:53

**Voice-over:** This is my own production, playing inside E-musician.

**Action / picture:** In production version 0.13.6, open a filming copy of test drive and start at project time zero. Music now continues through the entire chapter.

**Edit / sound:** 0.6-second chapter-06-workspace transition; use one continuous DAW audio recording underneath.

### D402 · 02:53–03:01

**Voice-over:** The piano roll exposes the notes, while VST support brings my existing instruments into the same project.

**Action / picture:** Show MAIN DRUM's piano roll with BM-VOID, then EP's notes with Keyscape. Preload both instruments before the take.

**Edit / sound:** Use short detail inserts captured separately at matched project times; return to arrangement before project time 13.031 seconds.

### D403 · 03:01–03:10

**Voice-over:** Audio recording keeps the performance inside the arrangement.

**Action / picture:** At project time 13.031 seconds, show the configured recording target and genuine incoming signal. Pair it with the same performance video when provided; otherwise use the abstract sax motion insert.

**Edit / sound:** 55% DAW / 45% performer or abstract insert. Never fabricate a growing recording waveform. The abstract asset is not a person or proof of a live take.

### D404 · 03:10–03:17

**Voice-over:** Samples become playable instruments, with direct control over the sound.

**Action / picture:** Open SAMPLE-RISE's Sampler and its waveform/trim controls while playback continues. Its arrangement trigger was at project time 15–18 seconds.

**Edit / sound:** This is a device-detail shot, not an assertion that the sampler is sounding at this moment. Use a synchronized earlier insert if highlighting its audible rise.

### D405 · 03:17–03:26

**Voice-over:** The Drum Rack puts individual sounds and their controls within reach.

**Action / picture:** Open RACK, frame the four populated pads, and select one pad to show its sample. The MIDI part is active between project time 18.75 and 44.413 seconds.

**Edit / sound:** Crop to pads → waveform; do not trigger extra pads over the continuous soundtrack unless that audition is intentionally recorded.

### D406 · 03:26–03:38

**Voice-over:** An ordered effects chain keeps equalization, dynamics, filtering, and space close to the track.

**Action / picture:** Show DRUM 2 EQ Eight, then RACK Compressor/Auto Filter and sax_player Reverb/Delay. Only demonstrate an audible adjustment if its actual output is captured.

**Edit / sound:** Three close-ups, 3–4 seconds each; let the response graph, gain reduction or knob be the focus. Keep transport audio unbroken.

### D407 · 03:38–03:48

**Voice-over:** The assistant and the editor share one workspace. I can work by instruction, by hand, or move between them.

**Action / picture:** Return to the full arrangement. Let the original track approach its ending; do not restart playback or open an unrelated project.

**Edit / sound:** Widen slowly; retain the project's real master fade. Narration ends before the closing invitation.

### E01 · 03:48–04:00

**Voice-over:** E-musician is built around the musician. Explore the open-source project, try it, and help shape what comes next.

**Action / picture:** Play closer-1080p30.mp4. Hold the logo and full repository URL long enough to read. Fade music with the final frame.

**Edit / sound:** Keep the final URL static for at least five seconds; no feature list or metrics on the closing card.

## Copy-ready prompts

### P1

```text
Use YuE2 to create a short neo-soul idea at 90 BPM in 4/4, with warm Rhodes, mellow electric guitar, rounded bass, laid-back drums, and intimate female vocals. Include a short intro, verse, and chorus. Let me preview it before adding it.
```

### P2

```text
Use ACE-Step for another take of the same neo-soul brief at 90 BPM in 4/4. Keep the warm Rhodes, mellow guitar, rounded bass, laid-back drums, and intimate female vocal. Let me preview it before adding it.
```

### P3

```text
Use SCNet to separate the selected audio into vocals, drums, bass, and other. Keep the original track and its name. Let me apply all four stems together.
```

### P4

```text
Analyze the chords in the selected New Light clip with ChordMini. Let me review them in Analysis before adding a chord track.
```

### P5

```text
Detect the beats in the selected audio and align it to this 120 BPM project with pitch-preserving Warp. Keep the chord track aligned.
```

### P6

```text
Transcribe the selected Tea for Two piano stem to MIDI with TransKun. Let me review it before adding a MIDI track.
```

## Demo4 alignment and acceptance

- test drive is a nine-track, 160 BPM, 4/4 project. Its zero corresponds to film 02:48. Sax enters at project 13.03125 seconds (film about 03:01.031), ending around 47.973 seconds; source offset is 13.367045 seconds. Align performer footage by matching audio transients, not file start time.
- The saved sax_player track has no audio input assigned. Configure one before filming. Use a filming copy and a separate record target to avoid overwriting or doubling the existing sax clip. Playback alone is not evidence that a new performance has been recorded.
- The performer-video path is currently unavailable. The nine-second abstract sax insert is a replaceable visual asset, not a person or a live-performance claim. Genuine recording footage on the DAW side is still supplied by the user.
- Sampler triggers only at project 15–18 seconds; its later shot explains the device controls. RACK sounds at 18.75–44.413 seconds and contains four populated pads.
- test drive.wav lasts 62 seconds but predates the saved project. Record one continuous output from the current project for the film. If a new sax take is recorded, use that same take in the soundtrack.
- Check by shot: P1/P2 each Preview/Apply; delete only YuE2. P3 returns four tracks without renaming the source. P4 is accepted through Analysis. P5 maps 125 BPM source to the 120 BPM project while preserving pitch. P6 uses the existing 132-note TransKun result; piano audition must be MIDI plus the plug-in. D4 requires an actual recording.

## Internal production facts and boundaries

The first three project workflows reuse existing model artifacts with repeatable presentation waits. This production makes no SSH connection, API call or new cloud inference. The UI stays clean; narration does not represent the staged wait as measured inference latency or claim the outputs were regenerated during filming. Generation is described as a short excerpt, not a complete 64-bar song or guaranteed structure. This fixed workflow does not establish model quality, broad natural-language reliability or general performance. The asset manifest records provenance and hashes.

This is a filming/editing kit, not the final four-minute screen-recorded film. New Light / Tea for Two source credits remain in internal materials; the user confirms the intended public-use scope. These recordings are not described as original compositions or redistributed as part of the open-source code.
