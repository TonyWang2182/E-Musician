# Final runtime / sidebar integration audit

2026-11-14. Read-only review of the current runtime, HTTP server, provider error adapter, web UI and demo guides. No network request, model task, native process or user UI was started. Source may continue to change under the parent task; findings below describe the reviewed state, not a claim that subsequent fixes failed.

## Practical findings

1. **Pending cancellation stage needs the runtime's actual DTO.** `runtime.cancel()` preserves phase `planning` while the worker remains alive, but sets `progress.stage` to `cancelled`. The UI currently chooses its stopping message only from phase `cancelled`. A slow in-flight request can therefore show “Planning your request” after Stop, with Stop/Pause still enabled. Recognize the actual cancelled stage while busy, show “Stopping the task / Waiting for the task to confirm it has stopped”, and disable repeated Stop/Pause. The existing synthetic cancelling fixture used phase cancelled and should gain the real planning+cancelled-stage case. The backend still avoids applying after cancellation; this finding concerns truthful UI state.

2. **Cached-result selection is mislabeled as planning briefly.** `_select_generation` reports stage `checking` with an authored “Preparing the selected result…” label. The simplified frontend ignores that stage and displays “Planning your request”. Map checking to preparing the selected result so the user sees that Review retrieves the cached candidate, rather than triggering a new model request.

3. **The operational guide needs the final version/workflow update.** At audit time `docs/demo/2026-11-14-demo-operations.md` still says 0.13.3, `Apply changes`, and creates separate YuE2/ACE projects after applying both. Those historical steps are usable but cannot demonstrate the new candidate picker, which only lists the current project's results. For 0.13.4: keep one project and 90 BPM/4/4 unchanged; generate each once without applying the first; select Review and Preview either result; apply the chosen result once. The visible control is now `Apply`. Explain that Review can recover an already-finished result after a language-API quota failure without invoking GPT. Keep the historical validation status distinct from this new UI route.

4. **Manual Beats workaround is version-specific.** `MANUAL-FALLBACK.md` explicitly documents the 0.13.3 Cloud-to-Beats route issue as unfixed. The final delivery should mark that as historical and explain the parent's 0.13.4 fix rather than making users perform obsolete routing steps.

## Checks with no additional blocking issue found

- Choosing a cached candidate uses the explicit authenticated POST endpoint and a fresh native snapshot/result, recompiles a plan, and leaves Apply separate. Project, revision, scope, tempo/meter and native candidate identity remain checked. Cache size is bounded to six and the picker filters current project identity.
- A single candidate remains available after a model error before proposal; a stale proposal permits reselecting. Busy/applied/unavailable candidates are not actionable in the UI. Missing DTO preserves older runtime compatibility.
- API quota classification reads at most 8193 bytes and only recognizes the exact allowlisted code/type. Raw provider body/message/headers are neither displayed nor logged by the changed handler. Native/HTTP error output remains redacted.
- Normal runtime errors, cancellation text and preview diagnostics pass through authored localization. Unknown Chinese diagnostics become a generic English failure rather than leaking untranslated Chinese; user filenames, lyrics and track names remain untouched. The quota error's bilingual value is retained by the async guard. A synchronous missing-candidate error loses its precise bilingual text through string conversion, but still receives the generic English fallback; not a normal clickable picker path.
- Web task details render explicit safe fields (model, usage, stage and job ID), not a raw response dump, API key or private reasoning. API-key input is a password field and clears before submitting settings. Request body is not sent to native focus events.
- The review/apply boundary, visible Undo, generation preview, scope warnings and user draft remain available. Progress has no numeric completion value. Completed Apply/Undo result visibility is no longer delayed by the local HTTP mutation flag.

This review does not replace the parent integration/build tests or real-device listening. The findings were reported to the parent before any further edit; this audit itself changes documentation only.

## Follow-up resolution

The parent authorized fixing findings 1–2 after this read-only report. They are now implemented in the owned UI and verified by the 22-case task-flow run `20261114T114355.351010Z-74b9c6ab4a` (including real pending-cancel DTO shape in both languages and cached-result checking). The new `docs/demo/2026-11-14-demo-runbook-v0134.md` was subsequently read: it uses Apply, same-project candidate comparison and the fixed Beats route, and distinguishes unverified real GPT prompts from tested direct model pipelines. A small filming note was sent to the parent: explicitly stop the first Preview before sending the second generation request, since starting a new plan does not itself stop the old audition.
