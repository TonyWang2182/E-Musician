# Track action labels — investigation and plan

2026-11-14. Scope: the arrangement header's existing M/S/R controls; keep their commands, layout, hover/toggle/focus treatment and track colours. No audio, model or project schema changes.

## Evidence before editing

- Current 0.13.2 source has literal `M`, `S`, `R` labels in `ArrangementView::Impl::TrackControls`. Its `deviceui::ControlLook` inherits `WorkspaceLookAndFeel::drawButtonText`; the latter already uses 2 px horizontal padding at 24 px button width. No localisation path replaces these labels.
- Prior offscreen tests exercised that theme directly and passed. They do not establish which executable a user opens by double-clicking a project.
- The parallel project-icon investigation found the `.emproj` open command still pointing to `E:/E-musician/build/bin/Release/E-musician.exe`, not the final 0.13.2 executable. This is a concrete stale launch entry; it is not proof of an independent DPI failure in the current build. The parent/project-icon task owns its correction.

## Changes to make

1. Keep the three track-action abbreviations on a dedicated compact-label paint path. Draw their one-character labels centred with ellipsis disabled, independently of generic dialog/menu text fitting. Preserve the shared button background and existing click/context handling.
2. Test actual header button snapshots, not only a call into the theme's text method. Require tall, distinct M/S/R ink shapes with the frame excluded. Exercise off/on/disabled states at 100/125/150/200 percent rendering scale.
3. Exercise a deliberately narrow generic-text theme to prove fixed action labels do not fall back into dialog-style truncation. Keep generic device/name buttons on their existing text renderer.
4. Capture a readable scale/state atlas and the existing real-track close-up. Parent runs the recorded Release build and `engine.integration_smoke`; no separate unrecorded build/test is run here.

## Acceptance boundary

Automatic raster checks plus visual inspection demonstrate the actual component painting. The parent will verify the final launch/association path. Actual Windows DPI, mouse interaction and user hardware listening remain the user's manual checks; none is inferred from a bitmap.
