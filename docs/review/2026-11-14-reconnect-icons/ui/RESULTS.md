# Track action labels — result and verification boundary

2026-11-14. Status: implemented; parent-recorded build/test and final image review pending.

## Diagnosis

The current 0.13.2 source already contains the earlier narrow-padding correction. The actual arrangement uses `deviceui::ControlLook`, which inherits that corrected text renderer; M/S/R remain literal one-character strings and are not translated. The old 200% offscreen actual-track image was re-opened and visually inspected: M/S/R are readable there.

The project-icon investigation found the user's `.emproj` open command still targets `E:/E-musician/build/bin/Release/E-musician.exe`. That is a concrete stale launch entry and explains how a project opened from Explorer can bypass the current candidate. It does not prove the current executable has a physical DPI bug. Parent owns verification of the corrected project association and final running executable.

## Implementation

Only `apps/desktop/ArrangementView.cpp` was edited by this task. The three fixed track-action buttons use a compact text paint path with ellipsis disabled. Their 24 px geometry, shared background/focus treatment and existing Mute/Solo/Arm/context-menu commands are unchanged. Devices and Rename still use generic themed text.

The arrangement smoke now snapshots the actual component rather than calling only `LookAndFeel::drawButtonText`. It crops the surrounding frame, requires full-height ink and pairwise-distinct letter shapes, and checks 72 cases: three buttons × three states × four rendering scales × two themes. Scales are 100/125/150/200%; states are off/on/disabled. A deliberately narrow generic theme confirms fixed labels avoid its truncating method while a normal Devices button still uses it.

Parent should run the recorded Release build and `engine.integration_smoke` (included in full CTest). New report fields:

- `track_action_component_raster_cases = 72`
- `track_action_labels_bypass_generic_ellipsis = true`
- `actual_compact_track_button_glyphs_readable = true`

New image: `arrangement-track-actions-dpi.png`, alongside the existing actual-track `arrangement-track-buttons-200.png`. These are rendering-scale fixtures, not a claim that physical Windows DPI or user mouse interaction was exercised.

No build, test, GUI automation, audio playback, cloud inference or Git commit was executed by this task. Final evidence will be appended after the parent's recorded run.

## First recorded build and component verification

Parent build `20261114T092441.359891Z-e3a71b29ba` succeeded. In the subsequent recorded CTest run `20261114T092733.460766Z-bbc82c6f3e`, `engine.integration_smoke` passed; the separate workspace test failed at the newly added project-open fixture, which the project-icon task is correcting. This is not a full-suite pass claim.

Read `build/smoke/Release/1a0568a12cbd/arrangement-report.json`: `status=passed`, `track_action_component_raster_cases=72`, `track_action_labels_bypass_generic_ellipsis=true`, and `actual_compact_track_button_glyphs_readable=true`.

Opened and visually inspected both `arrangement-track-actions-dpi.png` and `arrangement-track-buttons-200.png` from that same directory. All four rendering scales show distinct M/S/R letters in the normal and intentionally narrow themes, for off/on/disabled states. Labels remain centred; active fill and disabled text remain distinguishable. The actual two-track close-up shows readable M/S/R, Devices and Rename with no overlap or truncation of the action abbreviations.

This task's painting and image checks therefore pass for the first candidate build. No additional source changes were needed. Final binary/association checks and the corrected full-suite result belong to the parent. Physical Windows DPI/input and audio hardware remain manual checks.

## Independent final source and verification review

Compared `NATIVE-INPUTS-FIRST.json` with `NATIVE-INPUTS.json`: both contain the same 128 paths; the only changed hash is `tests/MainWorkspaceSmoke.inc`. Re-hashed all final files from disk; all 128 match the final manifest. The arrangement renderer and all other production native inputs are unchanged between the successful first and second Release builds.

To verify the exact test-only change, removed the new open-job waiting/report block from the final test file **in memory only**. The reconstructed SHA-256 is `ac41e389d88f5c6400ef7a1d6122d49ff00f6d55f9dab6c7bb0f832cae06ee41`, exactly the first-build manifest value. Thus the second build changes only the test's asynchronous wait/diagnostic block, not the project-open production path or the track-label fix.

Second build `20261114T093158.608270Z-7b242e79f9` succeeded. Targeted workspace rerun `20261114T093317.874276Z-277453f89c` succeeded. Its `build/workspace-smoke/6ddd4fed7149/workspace-brand-report.json` reports `status=passed` and external open job `seen=true`, `status=completed`, with empty engine/UI errors. The original 72-case arrangement pass and inspected atlas remain applicable to unchanged production rendering inputs; this is a first full run plus targeted failed-test rerun, not a claim of a second full CTest execution.

Also inspected the final-build `ui-workspace-brand-1440x900.png`: real track-header M/S/R labels remain readable in the full workspace, with Devices/Rename and coloured clips in their existing layout. Re-reviewed the patch: only compact abbreviations bypass generic fitted text; background/focus, disabled text, context-click suppression and existing command callbacks remain intact. No new source issue found, no additional builds or source edits performed by this review.
