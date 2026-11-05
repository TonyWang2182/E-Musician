# Interface language implementation and verification

Status: implemented; Agent web fixtures verified. Parent iteration rebuilt the native host and verified UTF-8 output, selection-preserving locale switches and component screenshots; see [RESULTS](RESULTS.md) / [UI-VERIFICATION](UI-VERIFICATION.json). Physical desktop acceptance remains pending.

## Implementation

- `apps/desktop/UiLanguage.h` is header-only and exposes `uiLanguageCode()`, `uiLanguageRevision()`, `setUiLanguage(code, persist)`, `uiText(english)` and `uiText(english, chinese)`.
- Default is English. Supported explicit choices are `en` and `zh-CN`. The setting is stored in the user's application-data `E-musician/ui-language.txt`; it is not part of a music project, an Agent credential, or a model request. This preference is read once, on the UI side; there is no new audio-thread work.
- `uiButton`, `uiLabel` and `uiComboItem` mark authored controls with their canonical copy. `refreshUiButtons` refreshes only these tagged controls. Arbitrary track names, clip names, sample filenames, plugin names, entered values and IDs are not scanned or translated.
- Piano roll, selected-track controls and native instrument/effects panels use explicit static-control tags and translated painted labels. Main-window settings, arrangement and analysis UI integration are in the other owned tasks. Third-party plugin editors remain under the plugin's control. Historical diagnostic prose and some inherited help text remain in their original language; this is not a claim that every third-party or legacy diagnostic has a Chinese translation.
- `AgentSidebar::refreshLanguage()` switches the embedded page without restarting the helper. The initial page carries a `lang` query parameter before the session-token fragment; the existing token validation and memory/session behavior remain intact.
- Agent HTML, controls, statuses, capability list/examples, note-preview labels and deterministic analysis/chord-change summaries have an English/Chinese catalog in `web/i18n.js`. The worker's tool names, payloads and authorization semantics are unchanged. User input, model responses and model-authored summaries retain their original language.
- Tagged JS templates translate literal text only; interpolated names/values remain untouched. UI strings use text nodes, not HTML injection. Switching locale keeps the prompt draft, project data and model-settings fields.
- Analysis capability descriptions and candidate previews use short musical descriptions. Detailed model/version diagnostics remain in the underlying result data and logs rather than the normal preview.

## Verification evidence

All commands below used `scripts/dev.py::Recorder`, with raw output in `build-logs/` and append-only DEVLOG entries.

- Initial syntax checks: `20261105T101822.793427Z-e831826c63` / `20261105T101826.479400Z-f8d3961cbc` passed. Initial three real-page synthetic-host fixtures: `20261105T101827.470901Z-5c9328d64f` passed.
- Final syntax checks: [i18n.js](../../builds/20261105T102055.418464Z-767521f0bf.json) / [app.js](../../builds/20261105T102056.789109Z-3fdd3a1e90.json), both passed.
- [Final headless Edge fixture run](../../builds/20261105T102057.815442Z-96b76bf722.json): all four fixtures passed in 16.704 seconds; source unchanged during that command. English empty/ready at 400×800, English empty at 1000×800, Chinese empty at 400×800. Each checks seven capability entries, unavailable-action disabling, working example insertion, viewport width, zero JS errors, English→Chinese→English labels, preserved draft/project content and untranslated interpolated user values. Ready preview contains the two synthetic notes supplied by the fixture.
- Rendered screenshots were inspected from `build/analysis-agent-web/`; English deterministic plan steps and controls fit the 400px sidebar; Chinese controls preserve the established visual treatment. These are owned headless browser fixtures, not computer-use or native WebView2/physical desktop validation.
- Mechanical Impeccable detector ran once against the changed HTML/JS surface. It reported the existing 11px utility-text warning inherited from `style.css` (unchanged). Main page body remains 13px, controls follow the pre-existing compact sidebar design. This warning is retained rather than called a clean detector pass.

## Remaining acceptance

Use the final native build to change Settings → Language between English and 简体中文. Confirm the current project and selection are retained, the Agent draft survives the switch, and restarting the program retains the chosen language. Actual desktop font fallback/DPI and keyboard/mouse behavior require the user's manual check. Model replies need not change language when only the interface setting changes.

## Follow-up fixes and final web check (2026-11-05)

- Read-only inspection of the pinned JUCE ComboBox implementation found that `changeItemText` updates its menu without refreshing the current label. The shared helper now captures the selected ID **before** changing item strings and restores it with `dontSendNotification`; locale changes cannot fire recording/monitor/input commands. Main-window dropdown refresh was coordinated with the arrangement task.
- Parent visual QA then found mojibake in native two-argument translations. Added explicit `const char*` overloads using `juce::String::fromUTF8` for source literals, including mixed `juce::String`/literal arguments. The existing `juce::String` values are not reinterpreted. This fix needs the parent's rebuilt native screenshot/test evidence; the web checks below do not validate native font rendering.
- Added exact English mappings for the new 4/6-track import wording and editable chord-lane hint. The normal analysis plan already derives its localized short steps from structured `execution_kind`, `analysis.kind`, count and timeline position; it does not translate user-authored summaries.
- [Final i18n syntax check](../../builds/20261105T104052.694256Z-ffe76a891a.json), [app syntax check](../../builds/20261105T104054.082375Z-8ae65d0382.json), and [four final browser fixtures](../../builds/20261105T104055.187269Z-86a76688f0.json) passed. The latter completed in 16.241 seconds, all existing locale/data-preservation checks plus `newAnalysisCopy` true, no JS errors, source unchanged.
- Final web-check whole-source fingerprint: `71e523e782dc1cba27263997bc84a6ca8f725a8dcb59d4e1c07fe90d45365d85`. This is the input to that web check, not an assertion that later native builds have the same complete-source fingerprint.
- Checked web asset SHA-256: `app.js` = `f7a518c16761316ac51198d9e57e49060dfda755bdb40ca0007869cb40fb2cfc`; `i18n.js` = `fa55937c352be257b79ee3ea3f31a991710fbe780c418f4cb7cbc7be569f2de3`; `index.html` = `a1e4da8c978abf48b81d3ee73878b9ad22e4fc7dcd85f3460cd17dcb1103d5b2`.
- [Manual short check](MANUAL-CHECK.md) covers the exact 0.9.1 launcher, Settings language persistence, four rename entry points, 4/6 stems, chord-lane correction, MIDI ranges/instrument playback, save/reopen and Agent equivalents. All user checks remain pending.
