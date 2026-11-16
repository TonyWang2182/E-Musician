# 0.13.6 publication record

- Code, tests, build evidence and development documents: `9e12f659d3fa2db57714b16d056fa13ab35bd62f`.
- Branch: [fix/audio-input-v0136](https://github.com/TonyWang2182/E-Musician/tree/fix/audio-input-v0136).
- Push succeeded on 2026-11-16; independent `git ls-remote` matched the code commit. No main merge. This publication note and the DAW-owned helper launch receipt are documentation/evidence follow-up only.
- EXE: `E:/emusician-analysis-build/bin-0.13.6/Release/E-musician.exe`.
- SHA-256: `81020b783de6540746de5a81215ea8a62cc133f4d8202a30d40add3b98940699`.
- Launcher: `E:/MusicAgent&DAW/Start E-musician 0.13.6.cmd`; VS Code workspace: `E:/MusicAgent&DAW/E-musician-0.13.6.code-workspace`.
- Final Release `755f123b2d`, CTest `023018ac4f` 11/11, Agent `2795a51de1` 390/390 with unchanged relevant inputs, M-Audio physical lifecycle `3f4d571d0c`, source/old-EXE proof `b279e4be86`. Detailed scope and failures: [RESULTS.md](RESULTS.md).
- App launch `633e6a75ea`: PID71532, correct executable/title, Responding=True. DAW-owned embedded Python helper launch receipt: `9ed6035f1e`; no model request was made by this task.
- Included 16 `audio-input-*` command/launch records plus that one embedded-helper receipt. Earlier user DEVLOG edits and 30 previously untracked build records remain local; none were folded into this release. Workfile history was preserved while staging only this iteration's entries.
- 0.13.5 executable hash verified unchanged. Original projects and driver settings retained; the probe restored Settings.xml byte-for-byte. Project association backup is `build-logs/audio-input-association-before.json`; protected Windows UserChoice remains unchanged.
- No recorded microphone WAVs, project bundles, settings backups, private credentials, model weights, caches or raw logs were added to Git. Seven synthetic UI PNGs are the only added image artifacts.

Physical voice/source identity, listening, vendor control-panel interaction, other physical interfaces, real DPI and longer recordings remain [manual acceptance](MANUAL-CHECK.md).
