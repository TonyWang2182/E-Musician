# Agent sidebar simplification

Status: implemented and verified with isolated synthetic browser fixtures. Owner: sidebar UI subtask. No native, model-service or Agent command semantics changes in this subtask. Native integration and music inference evidence belong to the parent review.

## Scope and design

Keep the existing paper/teal visual identity and an Operate surface: one clear task, honest progress, a compact review and explicit Apply, followed by visible Undo. Existing scope, stale-state protection, cancellation, generation Preview, provider selection and API-key settings remain available. The parent task has loaded Impeccable context; this subtask read distill/craft-floor and the committed PRODUCT/DESIGN/UI_REFERENCE.

The current surface repeats phase, long conversation replies, plan summary, execution steps, detailed changes and scope reminders. Make historical conversation, item-by-item analysis, model route, usage and diagnostic text expandable instead. Keep the proposed musical changes, their target scope, uncertainty/truncation warnings and a stale-plan warning visible. Do not hide destructive changes behind an accordion.

## Implementation plan

1. Reshape only `scripts/music_agent/web/index.html`, `app.js`, `style.css`, and `i18n.js` into instruction → working → review → applied/Undo.
2. Map real runtime/job stages to short English/Chinese labels. Use an indeterminate progress indicator unless a trustworthy bounded progress value is explicitly supplied; never estimate a percentage from elapsed time.
3. Retain existing authenticated endpoints and payloads. Keep provider/key settings accessible, draft/language behavior and embedded focus ownership unchanged.
4. Add isolated synthetic web-state tests for idle, working, ready, applied, cancelled/error, stale revision, English/Chinese and narrow widths. Run existing relevant webpage regressions; inspect batched screenshots. These are UI evidence, not real music inference or physical audio evidence.

## Verification checklist

- Only Send is primary before a task; only Apply is primary for a reviewable plan.
- Cancel stays available while planning; applying cannot falsely offer cancellation.
- Progress labels come from actual phase/job status. Unknown progress has no fake percentage.
- Result summary is concise; warnings and target scope remain readable.
- Undo is visible after an applied change and enabled only when the runtime permits it.
- Details start collapsed, preserve user-open state during polling, and do not contain API keys or private reasoning.
- No horizontal overflow at 320/400 px; keyboard focus and language switching preserve the draft.
- Existing user DAW, audio devices, live jobs, model configuration and cloud models are not touched by webpage fixtures.

## Evidence

The default sidebar now shows the latest instruction, one actual localized stage, a compact musical result, Preview/Apply and a visible Undo after applying. Full conversation, model route, usage, job IDs and item-by-item review remain available in collapsed details. Key/provider settings, scope control, stale warnings, cancellation and draft/language behavior remain accessible. Long instructions expand inline. Unknown progress has no numeric value; stage changes come from the runtime's actual job phase/status.

Generation choices consume the parent's real `generation_choices` DTO and call `/api/generation/select` with result ID and current scope. Selecting recompiles a review and never applies implicitly. Applied/unavailable/busy choices are disabled. A lone completed result remains recoverable when API quota fails before the model proposes it; an already-selected valid sole result does not add redundant UI. A stale review permits selecting its candidate again. The list scrolls after 176 px to keep the task compact.

One rendering bug found during visual QA was also fixed: the completed Apply/Undo response could be hidden until the next poll because the HTTP mutation's local busy flag had not yet cleared. Final task state now makes the result visible immediately; Undo is still enabled only by the runtime's permission.

All commands used `scripts/dev_agent_demo.py command ...`; raw logs are linked from the build records. No paid model call, real cloud task, real audio device or user project was touched by these tests.

| Verification | Result / build record |
| --- | --- |
| JS syntax | Passed: `docs/builds/20261114T113811.628365Z-3fe85dcf40.json` |
| New task-flow UI suite, 18 cases | Passed: `docs/builds/20261114T113811.629385Z-28d8a071aa.json` |
| Existing hybrid/localization suite, 4 cases | Passed: `docs/builds/20261114T113401.050781Z-0f9d66fd10.json` |
| Existing Preview/Stop generation suite, 3 cases | Passed: `docs/builds/20261114T113538.450312Z-85bd5a98a2.json` |
| Existing analysis/beat review suite, 5 cases | Passed: `docs/builds/20261114T113619.062003Z-5d77ce6e92.json` |
| Existing waiting/output-limit suite, 2 cases | Passed: `docs/builds/20261114T113538.495545Z-71f8a7395e.json` |

The 32 browser cases cover 320/340/400/1000 px, EN/ZH, actual-stage mapping (including native progress=1 while downloads are ongoing), no fake percentage, Cancel/Undo/Preview HTTP payloads, Apply-to-result, stale blocking and reselect, missing DTO, recovered candidates, unavailable choices, preservation of input/project names and settings access. Captures and reports are in ignored `build/agent-task-flow-web`, `build/hybrid-agent-web`, `build/generation-agent-web`, `build/analysis-agent-web`, and `build/agent-mix-web`.

Batched screenshots were inspected for ready EN/ZH, receiving, quota error, generation comparison and applied/Undo. Paper/teal colors, readable controls, visible current scope and no horizontal overflow were confirmed in these fixtures. These are browser rendering checks, not a JUCE/WebView2 physical desktop or audio performance benchmark.

Two historical test expectations were corrected without weakening behavior coverage: HybridAgentWebSmoke now checks model provenance in collapsed Task details, while still asserting musical counts/warnings/localization; AnalysisAgentWebSmoke compares every rendered capability ID with the actual fixture catalog instead of a stale fixed count of 10 (the catalog now has 11 including score). The first analysis run failed only on that stale count, recorded in `docs/builds/20261114T113538.433743Z-c3d2584ad7.json`.

The requested one manual Impeccable detector pass is recorded in `docs/builds/20261114T113619.142146Z-470b8a6d35.json` (exit 2). It flags the indeterminate activity line as a horizontal marquee; this is an intentional pending-task indicator, not auto-scrolling content or an estimated completion fraction. It respects reduced motion and has an ARIA progressbar without a numeric value. The additional flat-type-hierarchy advisory is retained for this compact Operate sidebar: task labels and headings use weight and spacing within the existing DAW identity. Regex-only JS/CSS analysis is not a complete contrast audit; rendered screenshots were inspected separately. No detector suppression or design-system files were changed.

The existing `DemoPromptLiveCheck.py` is parent-owned and was not modified by this UI subtask. No native build was launched here. Manual final integration should confirm a real runtime stage update, cancellation semantics, cached generation selection/preview/apply and Undo in the rebuilt embedded sidebar.

## Follow-up integration findings resolved

The read-only combined review in `UI-FINAL-AUDIT.md` found that the actual pending-cancel DTO can retain `phase=planning` while its worker runs, with `progress.stage=cancelled`. The UI now recognizes that exact shape, shows Stopping/Waiting confirmation, disables repeated Stop/Pause and keeps Apply/result unavailable. A completed cancellation is still described only by the runtime's final result. `stage=checking` now reads Preparing the selected result in EN/ZH, matching the cached-result selection operation. The actual production model ID `ace-step-1.5-xl-turbo` displays as ACE-Step in the comparison list.

The expanded task-flow suite (22 cases) passed in `docs/builds/20261114T114355.351010Z-74b9c6ab4a.json`; JS syntax passed in `docs/builds/20261114T114355.312143Z-c9b4658bda.json`. Four new EN/ZH checks explicitly reject premature success/Apply and repeated cancel requests. The existing comparison fixture now uses the production ACE ID. Together with the earlier 14 relevant regressions, 36 distinct browser cases have passed. New pending-cancel EN and checking ZH screenshots were visually inspected. This follow-up still made no real model, native or user UI calls.
