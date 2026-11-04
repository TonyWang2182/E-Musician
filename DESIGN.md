---
name: E-musician Focus + Mix
description: Native Windows DAW with a dark editing canvas and persistent selected-track and Master channels.
colors:
  base: "#17191d"
  canvas: "#1c1f23"
  panel: "#25292e"
  raised: "#2d3238"
  line: "#3b4046"
  strong: "#606872"
  text: "#eceeea"
  muted: "#abb2bb"
  dim: "#8e98a3"
  accent: "#d8b879"
  danger: "#e28780"
  green: "#86b6a1"
  track-midi: "#b7a6ce"
  track-bus: "#a6acb5"
  track-audio-0: "#89b5c3"
  track-audio-1: "#c9a68c"
  track-audio-2: "#a4ba94"
  track-audio-3: "#88aaa5"
  mixer-master: "#afb8c1"
  piano-white-key: "#b5bcc3"
typography:
  title:
    fontFamily: "Segoe UI"
    fontSize: "17.25px"
    fontWeight: 700
  object:
    fontFamily: "Segoe UI"
    fontSize: "16.1px"
    fontWeight: 700
  control:
    fontFamily: "Segoe UI"
    fontSize: "14.95px"
    fontWeight: 400
  section:
    fontFamily: "Segoe UI"
    fontSize: "14.95px"
    fontWeight: 700
  label:
    fontFamily: "Segoe UI"
    fontSize: "13.8px"
    fontWeight: 400
  metadata:
    fontFamily: "Segoe UI"
    fontSize: "12.65px"
    fontWeight: 400
  detail:
    fontFamily: "Segoe UI"
    fontSize: "11.5px"
    fontWeight: 400
  position:
    fontFamily: "Segoe UI"
    fontSize: "19.55px"
    fontWeight: 700
rounded:
  control: "3px"
  clip: "0px"
  note: "1.5px"
  fader-thumb: "1px"
spacing:
  control-gap: "3px"
  panel-inset: "8px"
  workspace-margin: "12px"
components:
  button:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  button-hover:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
  button-active:
    backgroundColor: "rgba(216, 184, 121, 0.17)"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
  button-disabled:
    textColor: "{colors.dim}"
  navigation:
    backgroundColor: "{colors.base}"
    textColor: "{colors.text}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    height: "32px"
  text-input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
  clip-label-selected:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.base}"
    typography: "{typography.label}"
    rounded: "{rounded.clip}"
    height: "24px"
  note-selected:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.base}"
    rounded: "{rounded.note}"
  fader-thumb:
    backgroundColor: "{colors.text}"
    rounded: "{rounded.fader-thumb}"
    width: "22px"
    height: "8px"
  mixer-strip:
    backgroundColor: "{colors.panel}"
    width: "142px"
---

# Design System: E-musician Focus + Mix

## Overview

**Creative North Star: "Focus + Mix"**

A quiet, dark working instrument: music occupies the canvas, while selection, transport and channel controls remain easy to locate. The approved Focus + Mix direction replaces the earlier paper-and-ink appearance in the native 0.7.0 desktop application. It uses flat charcoal surfaces, warm amber states and restrained track colours.

Arrangement, full Piano roll and Mixer are views of the same project. The selected-track and Master rail stays visible across all three. Existing editing, recording, plugin, routing and automation operations keep their production semantics; the HTML design prototype supplies visual direction, not a replacement music model.

**Key Characteristics:**

- Dark tonal layers and fine boundaries separate tools from musical content.
- Clips fill their track lanes; time determines their horizontal geometry.
- Segoe UI, readable control text and sparse ruler labels support dense editing.
- Persistent channel controls display the same engine state as the full Mixer.

This is a scan of the frozen 0.7.0 native source. [FocusTheme.h](apps/desktop/FocusTheme.h), [MainComponent.cpp](apps/desktop/MainComponent.cpp), [ArrangementView.cpp](apps/desktop/ArrangementView.cpp), [PianoRoll.cpp](apps/desktop/PianoRoll.cpp), [MixerView.cpp](apps/desktop/MixerView.cpp) and [SelectedTrackPanel.cpp](apps/desktop/SelectedTrackPanel.cpp) define the implementation. The [approved prototype](../MusicAgent&DAW/designs/2026-11-02-focus-mix-v2/DESIGN.md) records the direction; differences below are records of native code. Current build, rendering and acceptance evidence belongs in [docs/CONTEXT.md](docs/CONTEXT.md). This specification does not certify device playback, listening, DPI or accessibility testing.

## Colors

Charcoal surfaces recede behind musical objects; amber identifies interaction state. The frontmatter owns exact colour values.

### Primary

- `accent` identifies selected clips and notes, toggled controls, active page underlines and keyboard-focus contours. Button fills use its low-opacity form; selected clip label bands use its opaque form.

### Secondary

- `green` identifies active Play and actual stereo meter levels below overload.
- `danger` identifies active Record, overload and error text. M/S/R text and control state remain visible; colour is not their only label.

### Neutral

- `base` is the shell and black-key background; `canvas` is the editing field and text-input background.
- `panel` carries headers, channels, ordinary buttons and popup surfaces; `raised` supplies hover/press and selected track-header contrast.
- `line` provides ordinary dividers and outlines; `strong` provides fader tracks, prominent grid lines and scrollbar thumbs.
- `text`, `muted` and `dim` separate principal content, metadata and disabled button text. Disabled states do not uniformly fade entire components.
- `piano-white-key` distinguishes white keys from the dark pitch grid.

### Object identity

`track-midi` is the instrument/MIDI colour, including Piano roll notes. `track-bus` is the shared theme colour for bus/master kinds. Audio colours cycle through `track-audio-0` to `track-audio-3` using the current track index; they are not persisted per-object colour assignments. `mixer-master` is the explicit Master strip accent in MixerView. Keep this existing distinction until the source deliberately unifies it.

**The State Rule.** Track colour identifies content; amber, labelled controls and focus contours express interaction state. Do not infer selection, record readiness or output destination from track colour alone.

## Typography

The native helper constructs `juce::FontOptions("Segoe UI", height * 1.15f, style)`. Frontmatter `fontSize` values record that resulting JUCE logical height using portable `px` notation; they are not CSS em sizes or measured glyph heights. Do not apply the multiplier twice. The old local function name `mono()` forwards to this proportional font and does not imply a monospace face. There is no downloaded font or explicit tabular-numeral feature in the native code.

| Role | Helper input | Application |
|---|---|---|
| `title` | 15, bold | Project name. Transport labels use the same nominal size with plain weight. |
| `object` | 14, bold | Arrangement track names. |
| `control` | 13, plain | Text buttons and ComboBox text; Mixer channel names are text buttons. |
| `section` | 13, bold | Mixer headings, selected clip name and main bar labels. |
| `label` | 12, plain | Clip captions, Piano roll ruler and panel descriptions. |
| `metadata` | 11, plain | Track types, routes, secondary time and meter context. |
| `detail` | 10, plain | Fader scale, sufficiently large note labels and dense pitch labels. |
| `position` | 17, bold | Bottom transport position. |

The native logo uses nominal 25 bold and empty-state headings use nominal 20–22; these are local display treatments, not a second body scale. Fit text to the actual rectangle and omit labels when they cannot remain legible. Short faders remove some scale labels; tiny notes do not force note names.

**The Readable Scale Rule.** Reduce grid and ruler label density before reducing the established control typography. Fine snap resolution must not require a label for every subdivision.

## Layout

Dimensions are JUCE logical pixels. The initial main window is 1280 × 800, with native resize limits of 1000 × 650 to 2400 × 1600. A 56px project header sits above page navigation and actions; the page-specific toolbar ends at y=128. The bottom region occupies 98px, including a 74px transport/control panel and the status/task row. The workspace uses a 12px horizontal margin.

| Window width | Persistent rail |
|---|---:|
| Below 1150 | 224px |
| 1150–1649 | 248px |
| 1650 and above | 284px |

The rail begins at y=96 and ends at the transport. It always contains the selected-track slot and Master; an empty project shows an explicit no-track slot. Complete Mixer strips are 142px wide and scroll horizontally when needed. Both Mixer forms retain at least 450px channel content height and use internal vertical scrolling in short windows. Their heading is 33px high; the compact rail divides the available width between its two strips, accounting for the scrollbar.

Arrangement has a 54px ruler and 12px horizontal scrollbar. Track headers are 192px wide when the internal canvas is at least 560px wide, otherwise 160px. Standard rows are 104px; compact rows are 64px when an open dock leaves less than 258px for Arrangement. Clip height is exactly `rowHeight - 1`, reserving the row divider. The optional clip inspector uses 40px height, or 28px below 760px window height.

Double-clicking a MIDI clip opens the lower editor while Arrangement remains above. The Piano roll tab uses the full central workspace; the same editor and clip are retained. Source and selected-track Devices / I/O + sends / Automation use the existing lower dock. Dock height is calculated from available space, not freely resizable. The MIDI/source dock is bounded to 180–340px; the track dock is at most 300px and leaves at least 100px above it. A 28px dock title row precedes its content.

Piano roll keeps two control rows. Below 300px height it uses a compact layout; enabling drum steps there shows the step editor in place of the pitch grid. Its 0–127 pitch range and time scrolling are production features, not the prototype's fixed C3–C5 view. Native layout rules do not define a mobile or browser mode.

**The Time Geometry Rule.** Clip and note positions derive from musical time. Selection borders, page switching and ruler-unit changes must not alter duration, snap precision or stored music.

## Elevation & Depth

The custom workbench uses flat surface changes, one-pixel dividers and explicit selection/focus contours. It adds no decorative shadows or gradients. Native OS chrome, standard JUCE popups and third-party plugin editor surfaces retain their own rendering; do not treat them as authored workbench shadow tokens.

Controls update directly on input. There is no authored transition or easing vocabulary. Playheads and meters update from live transport/telemetry rather than decorative animation. Meter refresh is not a screen-latency or device-performance guarantee.

## Shapes

Buttons and transport symbol tiles use the control radius; clips are rectangular, and notes have the lighter note radius. Transport symbols sit in 32 × 32px tiles within larger labelled controls. Ordinary top controls are commonly 28–32px high; Arrangement M/S/R buttons are 28 × 27px, while Mixer M/S/R buttons are up to 30 × 28px. Do not copy the prototype's universal 32px minimum into this native implementation record.

Clip label bands are 24px high within the same full-height object. Normal borders are 0.7px; selected borders are 1.8px. Selection adds edge and audio fade handles without changing musical geometry. The waveform source view retains open-corner framing from its existing native component.

Button keyboard focus adds a 1.5px amber contour on its existing bounds. Piano roll and Mixer use inset focus rectangles. These are the implemented treatments, not the prototype's external 2px ring with a 3px gap; native keyboard and display-scaling acceptance remains separately recorded.

## Components

### Controls and navigation

Text buttons use a panel fill, subtle outline and control typography. Hover or press uses the raised surface; toggled buttons use translucent amber, an amber outline and amber text. Flat buttons start on the shell colour and gain a 2px lower amber line when selected. Arrangement, Piano roll and Mixer navigation use this flat variant. Text is inset 8px horizontally and 2px vertically.

Text inputs use the canvas, text, line and focused amber colours supplied by InstrumentLook. Selection uses amber with base-colour text. ComboBoxes and popup menus use the panel palette. Do not invent a custom input radius: inherited JUCE drawing still owns that geometry. Save state, task progress and actionable errors remain visible in the header/status areas.

### Arrangement and ruler

The translucent clip body preserves the shared grid. Its caption band, real waveform or cached MIDI summary and selection handles belong to one rectangle. The selected caption uses amber with dark text; unselected captions blend the track colour with the canvas. Muted content has reduced opacity. Captions appear only when a clip is wide enough.

Bars, beats and subdivisions use distinct line strength; Snap on draws solid lines and Snap off draws dashed lines. The fixed/adaptive grid retains the 1/16384 lower bound and triplet options. Visible grid density and musical ruler labels are reduced independently of editing precision. Painting stays viewport-local and uses existing waveform caches and MIDI summaries.

### Piano roll

Dark pitch rows, a contrasting piano-key gutter and a separate velocity region orient the editor. Unselected notes use the MIDI colour with a darker fill; selected notes and their velocity bars use amber. Note labels require sufficient width and height. The real editor preserves pitch fit/scroll, pencil, box/multiple selection, move/resize, clipboard, quantize, transpose, velocity and drum-step editing. The velocity bars visualise the values; the slider/text control is the editing entry point.

### Persistent channels and full Mixer

Each strip presents name, type, output, device entry, pan/balance, gain fader, stereo meter, peak reset, M/S/R and Details. Master omits pan and M/S/R. Output and Details lead to the selected-track panel; an empty device chain opens the plugin browser. Routing, sends and automation continue in that panel rather than being replaced by decorative slots.

Gain ranges from −60 to +6 dB in 0.1 dB steps, with an editable readout. Double-click resets a track to 0 dB and Master to −6 dB. Pan ranges from −1 to +1 in 0.01 steps and uses C / L / R text. One drag groups into the shared Undo history; commands and subsequent readback use the same EngineSession as every other view. Meter bars show actual left/right peak snapshots and a separate retained overload state; they are not the prototype's fixed bars.

### Supporting native panels

Devices, I/O + sends and Automation inherit the same palette and typography while retaining their original controls. Automation is an editable native curve, with double-click insertion, drag, Alt-drag curvature and deletion. Plugin windows remain separate native editors. State-dependent disabling during recording/finalization and missing-object handling are functional requirements, not optional visual variants.

`.impeccable/design.json` extends these tokens with native source excerpts, breakpoints and state geometry. Its component samples are C++/JUCE excerpts with source paths; they are not runnable HTML/CSS previews. Do not introduce browser runtime dependencies to render the DAW.

## Do's and Don'ts

### Do:

- Do retain the dark Focus palette and the persistent selected-track / Master rail across all workspaces.
- Do derive clip geometry, ruler marks and playheads from the shared time model.
- Do use the native font helper once and preserve readable text when the window becomes smaller.
- Do bind repeated controls to the same EngineSession commands, snapshots and Undo history.
- Do keep Source, exact clip properties, recording, plugin management, routing and automation reachable.
- Do record native GUI, device, listening and DPI acceptance separately from source and offline-test evidence.

### Don't:

- Don't reintroduce floating clip cards, decorative shadows or a browser shell around the native editor.
- Don't copy prototype demo data, font metrics, limited pitch ranges or simulated controls into production.
- Don't let a hidden editing page receive destructive clip or note shortcuts.
- Don't treat a colour token, screenshot or successful build as proof of hardware or accessibility acceptance.
