# Part 10 revision — 2026-11-27

User requested a new Part 10 transition. The new 4-second/120-frame silent 1080p30 H.264 movie keeps the original silver background, exact title and type palette. A compact waveform preserves horizontal time positions while becoming seven rectangular MIDI notes beneath fixed text. Title resolves by 1.16 seconds; morph settles by 2.28 seconds, then holds. This is illustrative motion artwork, not a captured or inferred DAW result.

Root and independent visual review passed for layout, intermediate morph and settled hold. All eight videos passed full decoding and stream/frame-count validation; unchanged siblings were checked against the revision baseline (7/7 identical SHA256). Script remains unchanged at 240 seconds. Package CRC/member SHA passed. Previous Part 10, ZIP and receipts are retained at `revisions/part10-v1` within the delivery directory.

Current direct clip: `E:/MusicAgent&DAW/demo-video/application-script-2026-11-27/part-10-transcription-v2-1080p30.mp4`; SHA256 `03e7f55dd4ce037f4e590f5ae69570a1feb523e9bfee5480af6cd92d95279769`. The canonical motion file and `Title-transitions.zip` are updated. Current ZIP SHA256 `00ecf3e79748a7eb23e522ad9b2463539ed8851ab41e4beb3572a0f797233e90`; 19,511,771 bytes. Use [current delivery hashes](DELIVERY.json) and [revision receipt](PART10-V2.json), not the initial hashes below.

Recorded commands: [render](../../builds/20261126T173313.435853Z-9a8d73a36d.json), [verify](../../builds/20261126T173409.277042Z-f4affab137.json), [package](../../builds/20261126T173417.643793Z-1b260a1898.json). All succeeded. No other movie, script, original background, logo, DAW or user project changed.

# Initial delivery — superseded for Part 10 and ZIP hashes below

## Implemented and verified

The [new script](../../demo/2026-11-27-application-script.md) contains only the requested fourteen Parts: duration/time range, picture and operations, spoken English or silent transition text, and corresponding Chinese. Continuous timeline: 240 seconds. Automated count: 320 English spoken tokens/words under the recorded regex (model/product names count as words); no narration audio was created. First-person wording describes musical choices and specific actions, not investor slogans. Independent second review found no blocking timing, translation or operation-order issues.

Original operations retained: YuE2 Preview/Apply, ACE Preview/Apply, manual removal of YuE2; SCNet four stems then original mute/additive solo; New Light chord analysis and manual Analysis apply; beat/Warp apply; Tea for Two TransKun MIDI then piano instrument; continuous sixty-second original test drive with MIDI/VST, real sax recording, sampler, rack and effects. The script is a future recording plan. Its sax shot must be captured by the user; this iteration does not supply a new physical recording or verify its hardware. The preceding showcase still replays existing results, not new inference.

Six four-second title transitions and matching fourteen-second opener/closer are new, separate MP4 assets. The opener supplies extra editing handles: Part 1 uses its first five seconds, followed by nine seconds of actual UI shots. Part 13 begins music at 02:46, with the sax entry around 02:59 matching the existing project's 13.03125-second entry. This is an editing plan, not a newly assembled film.

## Five-video reference analysis and visual review

Read all five supplied `11月25日-1.mp4` through `-5.mp4` as reference only; extracted twelve actual frames each. [Reference analysis](REFERENCE-ANALYSIS.json) distinguishes measured pixel regions from approximate timing/font observations. Adapted centered typewriter/caret, selective left-to-right focus, sequential phrase reveal, one whole-card recession/stack, and a held brand lockup. Exported frames reuse the six existing original backgrounds and approved logo; no reference-video pixels, audio or third-party marks are incorporated.

Renderer and root both inspected all eight entrance/intermediate/hold contact sheets. Text and logo are legible, titles finish before final holds, closing URL holds more than ten seconds, and final title bounds have no clipping. Typewriter caret stops by 2.3 seconds; opener is fully legible by 1.9 seconds. This is sampled visual QA plus complete decode, not a claim of subjective audience acceptance. Original five references, six background files and logo SHA256s remain unchanged.

## Output

Delivery directory: `E:/MusicAgent&DAW/demo-video/application-script-2026-11-27`.

- `SCRIPT.md`: same bytes as the tracked final script.
- `Title-transitions.zip`: only the eight ready-to-use MP4 files, 19,577,285 bytes; SHA256 `90fa92c01478eaa9a736015a1f0b515304ddc98779ee074c2cd571903512dfcf`. CRC and every archived member SHA256 passed.
- `motion/`: individual movies, `MANIFEST.json`, `VALIDATION.json`, `VISUAL-REVIEW.json`, sampled frames and editable `source/`.
- [Delivery receipt](DELIVERY.json): exact part timing, final hashes and checks.

All assets: 1920×1080, 30 fps, silent H.264; 1,560 frames/52 seconds total. Complete decoding, stream format and exact frame counts passed for all eight. The user will add narration, music and their recorded operations later.

| Part | File | Duration | SHA256 |
| --- | --- | --- | --- |
| 1 | `part-01-opening-1080p30.mp4` | 14 s | `b298ad87639ef2fc0f099107ed9cc1635a835fab73da23483e6225744ade13ba` |
| 2 | `part-02-generation-1080p30.mp4` | 4 s | `86c8c3e616964810361ed01bed50ad20ca4ea20ce836b1879666415e423adfcc` |
| 4 | `part-04-separation-1080p30.mp4` | 4 s | `3cdf6c44d75cd555ebb5b489008391e62ec9725ed086328dcc720ab94edc3f11` |
| 6 | `part-06-harmony-1080p30.mp4` | 4 s | `3d98aa69ca62a89bd5f2d6b32f6568baf8e8ef2e0ee3788d79c68478022e190c` |
| 8 | `part-08-pulse-1080p30.mp4` | 4 s | `511cc9a6cb3156ea49452203623c7802faf7ba6028e3e055c82203c1da5589f4` |
| 10 | `part-10-transcription-1080p30.mp4` | 4 s | `fc8502eee8bd62e08976cde91cf37d7ca4850eae6cf25024c8e2214460749c76` |
| 12 | `part-12-workspace-1080p30.mp4` | 4 s | `5bd91a2a31231b2e57aca8161e05f196c2fcb93f36eaa0e7ae922e368f3f0834` |
| 14 | `part-14-closing-1080p30.mp4` | 14 s | `75f7642908ad07a9c936f1e1c6a51746cc496c04640e97a54922f4a8ea8e9ae8` |

## Traceability and scope

- Render: [b421a3bec7](../../builds/20261126T171056.340279Z-b421a3bec7.json), succeeded.
- Full asset verification: [c9e5d0af2f](../../builds/20261126T171429.284295Z-c9e5d0af2f.json), succeeded.
- Script/package verification: [b9bfbc535e](../../builds/20261126T171622.663273Z-b9bfbc535e.json), succeeded.
- Editable renderer: `scripts/application_title_motion.py`; package verifier: `scripts/application_film_delivery.py`. Local FFmpeg 7.1, Pillow/NumPy, system Arial; exact font/input hashes and encode commands recorded in the media manifest. No new dependencies installed.

No DAW source, EXE, project, architecture, model, API, SSH, file association, Jianying project, prior film or prior background changed. No new native build/test or performance claim. Existing unstaged DEVLOG history and 38 older untracked build receipts are kept out of this iteration's selective commit. New work is on `docs/application-film-20261127`; main is unchanged. Next step: user records the indicated actions and uses the new script/titles in their own edit.
