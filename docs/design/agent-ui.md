# Agent companion surface

Mode: Operate. This is an extension of the existing monochrome E-musician workspace. The first use is a musician beside the DAW asking for a small edit, reviewing its exact effects and applying once. It controls only the DAW process launched with this service. It does not imply that an unrelated running window is connected.

## Direction contract

THESIS: Keep the conversation next to visible project facts; put the computed changes and Apply in the same reading path. No dashboard of decorative metrics or hidden automatic edits.

OWN-WORLD: Inherit white paper, near-black ink, secondary grey and thin dividers from DESIGN.md. Compact mono figures align BPM and track facts; Chinese text uses an installed system face. Text labels, outlined controls and one black primary action carry the hierarchy.

STORY: See which project is connected, ask for an edit, read the concrete proposal, apply, then verify the result. Undo is available only when the backend permits it. Errors remain visible with an actionable recovery.

FIRST VIEWPORT: A compact project header spans the page. A narrow project column shows selected object and tracks; the wide conversation column contains the composer, transcript and proposed changes. Settings expand below the header. The footer contains measured token use and the deliberate service-close action.

FORM: Direct task-led extension of the supplied DAW visual system. No alternate visual identity or concept tournament. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Interaction and boundaries

- All dynamic content is text, never executable HTML or model-provided markup.
- The ephemeral localhost authorization token is removed from the URL fragment and retained in memory and tab-scoped sessionStorage for refresh. Service shutdown removes it. API credentials are sent only through the same-origin authenticated setup request and cleared from the password field afterward; API keys never enter browser storage.
- UI polling is serialized, at most once per second while work is active, and slower when idle. Network loss preserves visible context and disables writes until a fresh state arrives.
- Clicking Apply submits the stored plan ID. The UI does not reconstruct commands or decide revision conflicts.
- Cancel asks the backend to stop further steps. It does not promise to cancel already billed provider work or roll back an already executing DAW command.
- Closing a browser tab leaves the companion running. Service shutdown has a separate save reminder and explicit confirmation.

## Validation

The parent integration record owns final verification. Browser fixtures use synthetic state only and are separate from Kimi connectivity, actual DAW edits, physical keyboard and listening checks. No user desktop computer-use is required.

## Independent finish review

2026-10-29: a second agent viewed desktop/compact/mobile synthetic captures and read the shipped UI. No blocking issue found in those states. Root additionally fixed the unsaved-project shutdown error to appear inside its confirmation dialog. Final evidence is in docs/verification/2026-10-29-kimi-agent/RESULTS.md; real user GUI/hearing acceptance remains pending. No generated raster ships in the UI.
