# Design context — 0.11 workspace

The current direction is the user-approved [workspace reference](docs/review/2026-11-06-workspace-brand/approved-workspace.png), interpreted through the actual product and [UiDesign.h](apps/desktop/UiDesign.h). The earlier source images remain in [UI_REFERENCE](docs/UI_REFERENCE.md). The previous 0.5 design text is preserved [as historical context](docs/review/2026-11-06-workspace-brand/DESIGN-before-v0110.md), not as a competing specification.

**Status, 2026-11-06: implementation, Release build, automated integration and component captures passed; physical acceptance pending.** Evidence and limitations are in [RESULTS](docs/review/2026-11-06-workspace-brand/RESULTS.md). Physical ASIO, mouse/IME, DPI and listening remain manual checks. The reference's example music, section names, conversation, presets and spectrum are illustrative; only real project data and supported actions belong in the application.

## Identity and visual language

Use the approved bearded tree musician with glasses for the upper-left application mark, Windows icon and startup presentation. The Chinese brand is **易乐师**, while application/project compatibility retains E-musician. Startup motion should be brief, independent of audio processing and absent from test/background modes; it must not fabricate load progress. Do not substitute the reference's placeholder mark for the approved logo.

The workspace is light paper with fine dividers, slight 3 px control corners and rectangular musical objects. The shared tokens are:

| Role | Value | Purpose |
| --- | --- | --- |
| Paper | `#FEFEFD` | Main working surface |
| Panel | `#F1F2EE` | Quiet secondary surfaces |
| Ink | `#171817` | Primary labels, notes, selection outlines |
| Secondary | `#626560` | Supporting labels |
| Rule | `#C6C9C3` | Dividers and inactive tracks |
| Accent | `#BFD2CF` | Restrained active-control fill |
| Focus | `#527D7A` | Keyboard/active-control emphasis |

Use clear sans-serif labels and monospaced numbers for positions, pitches, timings and parameter values. This supersedes the old all-monospace treatment. Avoid decorative cables, dashboard cards, gradients, heavy shadows and invented waveform data. Keep labels readable at small sizes; use tooltips for supporting explanations, not as the only source of important state or errors.

The ten track identity colours are Sage, Blue, Lavender, Rose, Sand, Moss, Teal, Clay, Slate and Plum, defined in UiDesign. Uncoloured tracks stay neutral. Identity projects as a thin header stripe plus a light fill and clip title band; it must not cover the waveform or note preview. Selection uses its own ink outline and focus cue, so a track's identity colour never means “selected”, “recording” or “failed”. Muting reduces visual emphasis without deleting identity. Save/Undo preserve the actual colour through the unified command path.

## Workspace hierarchy

Popup surfaces follow the same tokens (0.13.1): 28 px menu rows, separate label and shortcut columns, paper backgrounds, 3 px corners and fine rule borders. Use a restrained accent fill for selection and a clear focus outline. Options callouts retain their anchor and use an opaque paper shell. Confirmation dialogs use a quiet footer and 32 px buttons; keep Save/Discard/Cancel semantics and keyboard order. Avoid oversized decorative question marks or heavy stock shadows. The app owns a shared default look so detached menus and alerts receive these rules; OS file pickers and external plug-in windows remain outside this theme.

Top controls keep project identity and save state near File/Save, followed by one transport, exact position, BPM/meter, metronome and count-in. Settings and Agent remain easy to reach. The editing row groups Library, add/edit/device/source/analysis actions with Undo/Redo, ruler, snap, grid, follow and zoom. Bottom status exposes jobs, device/resource information and master output; it does not repeat the transport.

The left Library is a compact searchable catalogue of native devices, scanned plug-ins and existing project audio. A device can activate on the current appropriate target or be dropped onto a track; project audio entries locate the existing clip. Search and category controls remain usable by keyboard. Do not imply a managed sample collection, cloud catalogue, favourites or preset browser where none exists.

The arrangement stays central. Its overview is a bounded projection of actual clip positions and the visible time range, with no fabricated Intro/Verse/Outro sections. Overview navigation scrolls without seeking or changing selection. Standard track rows are 88 px, compact rows 64 px; headers reserve space for rename, meters and Mute/Solo/Arm/Devices without overlap. Musical clip bodies and piano-roll notes are rectangular and occupy their actual time/pitch geometry. Titles use sans labels, exact timing uses mono values. Existing source waveform/MIDI summaries and non-destructive editing remain intact.

Grid lines are solid with snap enabled and dashed with snap disabled; Ctrl+4 changes that state. Zoom reveals bar, beat and subdivision names through three levels, then uses unnamed finer ticks. Fine logical grid resolution does not require drawing every subdivision at every scale. Visible-row rendering, bounded peak/summary caches and existing coordinate transforms must survive styling changes.

## Lower dock, devices and Agent

The lower dock can be resized vertically and closed without losing the selected musical object. Piano roll can expand; source, analysis and selected-track/device views share the dock rather than opening duplicate copies of project state. Keep an arrangement area visible in ordinary dock mode. One compact chain shows the selected track's actual ordered devices, left/right navigation and one Add action. The editor header identifies its track/device or explicit Master target.

EQ's wide layout prioritises a large response graph with selected-band controls below; narrower layouts retain usable controls instead of shrinking text. Knobs expose names, units and editable numeric values. Graph drags and knob drags audition the actual DSP through transient engine parameters; release commits one Undo, Escape cancels. Focus loss, hiding the panel, target changes and conflicting edits cancel safely. Saving/exporting or another musical command must not leave uncommitted audible state behind. The visual draft stays local while committed snapshots remain authoritative.

EQ spectrum comes from bounded audio-thread samples and UI-thread FFT, not animation or model output. Its current mono L/R sum can cancel antiphase material; stale data clears. Compressor gain reduction is measured. A/B slots are a panel-local comparison aid, not persisted project presets. Sampler and Drum Rack use the same surface/typography/knobs, pads and actual sample waveform, but their sample/state replacement does not promise uninterrupted held voices. Do not imply parity with the full Ableton device catalogue.

The right Agent sidebar uses the same paper surfaces and restrained typography. Conversations, selected scope, proposed changes and confirmation must remain distinct. Hiding/reopening the panel must preserve useful context. At narrow widths it can overlay the workspace and temporarily hide the Library; the arrangement/piano roll must retain a usable width. Capability text must match registered tools, and a structural readback must not be presented as listening-based musical evaluation.

## Verification boundary

Source waveforms load on background paths; paints do not decode files. Effect preview publishes bounded parameters without rebuilding the graph on every mouse move. Neither property proves smooth operation on a physical machine. Check the native workbench at 1000 × 650, 1280 × 800 and a wider layout, with Chinese/English, Library and Agent open/closed, compact rows, each dock and expanded piano roll. Check Windows 100%, 150% and 200% scaling separately, including long names, keyboard focus, popup menus and visible errors.

Manual acceptance must cover actual ASIO playback, held notes while tuning, cancellation, one-gesture Undo/Redo, plugin changes and listening for discontinuities. Record sample rate, real buffer size, workload and machine for performance claims. Automatic render/smoke tests, application launch and physical listening remain separate results. The current evidence and remaining checks belong in [CONTEXT](docs/CONTEXT.md) and the iteration's [device notes](docs/review/2026-11-06-workspace-brand/DEVICES-NOTES.md).
