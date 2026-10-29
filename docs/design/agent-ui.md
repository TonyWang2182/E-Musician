# Agent companion surface

Mode: Operate. This extends the existing monochrome E-musician workspace into an embedded desktop sidebar. Its target is 340–560 CSS pixels wide, with defensive layout at 260 pixels. The same assets support an optional standalone companion at wider sizes. Native integration owns the connection to the current DAW; the standalone launcher owns its dedicated DAW process.

## Direction contract

THESIS: Keep the composer available while reviewing a conversation, a concrete change list and the active DAW selection. The task and confirmation flow remain within one narrow column.

OWN-WORLD: Inherit white paper, near-black ink, secondary grey and thin dividers from DESIGN.md. Compact mono figures align BPM and track facts; Chinese text uses an installed system face. Text labels, outlined controls and one black primary action carry the hierarchy.

STORY: See which project is connected, ask for an edit, read the concrete proposal, apply, then verify the result. Undo is available only when the backend permits it. Errors remain visible with an actionable recovery.

FIRST VIEWPORT: A compact title and collapsible provider/model settings sit at the top. Settings open as an in-sidebar drawer over the work area, keeping provider, model, key and Save reachable even at 340 pixels; the underlying task area becomes inert until settings close. A collapsed project context summary follows the header. The central transcript scrolls independently, including task progress, full change lists and Apply/Undo. The bottom composer stays visible during task work with an explicit scope selector and real track/clip/note/range chips. A wide standalone window additionally reveals project details in a left column. No fake messages, model progress percentages or chain-of-thought appear.

FORM: Direct task-led extension of the supplied DAW visual system. No alternate visual identity or concept tournament. seed: none (unavailable).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Interaction and boundaries

- All dynamic content is text, never executable HTML or model-provided markup.
- The ephemeral localhost authorization token is removed from the URL fragment and retained in memory and tab-scoped sessionStorage for refresh. Service shutdown removes it. API credentials are sent only through the same-origin authenticated setup request and cleared from the password field afterward; API keys never enter browser storage.
- UI polling is serialized, at most once per second while work is active, and slower when idle. Network loss preserves visible context and disables writes until a fresh state arrives.
- Clicking Apply submits the stored plan ID. The UI does not reconstruct commands or decide revision conflicts.
- New requests default to `scope: selection`; `project` is an explicit user choice and is included in the plan request. The displayed proposal scope is captured from the plan/request, not relabeled when the user changes the next request's selector. Missing selection contracts are labeled unavailable; note selection is never inferred from an active clip.
- Provider options come from the backend registry. Configured means a local key exists, not that a remote request has passed. Pending adapters are visibly disabled; switching providers clears any unsent key so it cannot accidentally follow to another provider.
- Cancel asks the backend to stop further steps. It does not promise to cancel already billed provider work or roll back an already executing DAW command.
- `?embedded=1` hides standalone shutdown. Collapse and non-IME Escape call the native `agentClose` event and retain the composer draft. Escape first dismisses model settings when open. DOM keyboard events are contained in the web surface; native accelerator isolation is separately owned and verified by the host.
- Native `agentVisibility` events pause polling while hidden and refresh on reveal. Hiding preserves the page, conversation and draft; it does not kill the model worker or imply cancellation.
- Closing a standalone browser tab leaves the companion running. Standalone service shutdown has a separate save reminder, explicit confirmation and backend dirty-project rejection.

## Validation

The parent integration record owns final verification. Browser fixtures use synthetic state only and are separate from Kimi connectivity, actual DAW edits, physical keyboard and listening checks. No user desktop computer-use is required.

### Batch 1 sidebar evidence

Final browser fixture: [20261029T110747.894134Z-17f0efd865](../builds/20261029T110747.894134Z-17f0efd865.json), run through Recorder. Captures are local ignored evidence under `build-logs/agent-ui/`: `sidebar-idle-340.png`, `sidebar-ready-340.png`, `sidebar-ready-560.png`, `sidebar-edge-260.png`, `sidebar-settings-340.png`, `sidebar-error-340.png`, `standalone-1280.png`. These depict synthetic content and a fake native event bridge, never a real model result or native integration proof.

| First-batch item | Implemented behavior | Evidence / limit |
|---|---|---|
| Narrow integrated workflow | 340–560px sidebar, bounded header/context, independently scrolling task history, bottom composer | Ready/empty/settings/error captures; 260px overflow and composer visibility guard |
| Review before action | Complete computed changes, captured scope/revision, exact plan ID Apply, permitted Undo | Fixture asserts no apply during proposal; exact ID and Undo request |
| Selection scope | Default selection; explicit project choice; real contract chips for tracks/clips/notes/time | Request payload asserted; unavailable selection does not invent selected notes; >2000 selected notes has an explicit shrink-selection hint; active track fallback matches backend track focus; frozen plan scope/revision does not follow current project or next-request scope changes |
| Provider configuration | Backend registry, pending adapters disabled, per-provider model/address/key, configured status separate from remote verification | Switching provider clears unsent key; 1038-character synthetic key survives input and reaches only authenticated settings POST; no API key in storage |
| Native lifetime | Collapse/Escape emit agentClose; IME Escape preserved; no embedded shutdown endpoint; native visibility pauses polling | Fake bridge asserts retained draft, contained DOM keys, zero shutdown calls, no polls while hidden; native accelerator/WebView2 proof belongs to host tests |
| Visible failures and settings | Sticky error notice, in-sidebar settings drawer, underlying task controls inert | Error geometry and settings inert state asserted; all setup fields and Save visible in 340px capture |
| Standalone compatibility | Optional wide project column, explicit save/close confirmation, backend dirty rejection | Existing close fixture retained and asserted |

The first test run incorrectly used Playwright `isDisabled()` for an option element; the test was changed to inspect the native option.disabled property. Both records remain. The one detector pass found 10px functional metadata and small instruction text; functional metadata was raised to 11px and explanatory text to 12px, then recaptured. The settings layout was changed from a short inline region into a full-height in-sidebar drawer after inspection found the key fields required unnecessary scrolling.

Contract review found runtime now exports `plan.scope` as a frozen object rather than the earlier string. The UI and fixture now use the actual object (`mode`, `project_revision`, `selection_revision`) and explicit `plan.revision`; project-scope review and a changed current revision are tested. This correction is included in the final capture record above.

Independent finish review (provider agent) inspected current web sources plus the ready/settings 340px captures. It found the same frozen-scope contract mismatch and reported those captures legible without clipping. After correction it rechecked the source normalization, pinned revision and explicit scope labels, with no remaining blocking visual issue in those inspected states. The final fixture covers the correction. The independent review did not operate the user's desktop or verify a live model/native DAW session.

Separate host-transport synthetic coverage: [16 loopback tests](../builds/20261029T110233.634458Z-8d449bd182.json), including auth, malformed/duplicate/oversized/non-finite/deep JSON, failed-init cleanup, timeout poison, idle EOF and active reply isolation. [26 HTTP/bridge tests](../builds/20261029T105924.506419Z-d867db1c47.json) include explicit project scope and refusal to shut down an embedded host. These tests do not start or own a DAW process.

### Native focus follow-up

The parent native smoke found that DOM prompt.focus() did not consistently appear as JUCE component keyboard focus in WebView2. DOM propagation checks alone therefore did not protect native Space/Ctrl+4 handling. A read-only `agentFocus` event now sends exactly `{focused: boolean}`; it never includes input text, keys, credentials or music state. Native code rejects other shapes, accepts a true hint only while the panel is showing, and exposes `capturesKeyboard()` as visible browser focus OR that hint. Music-editor callbacks can clear the hint explicitly.

DOM focus-in, pointer-down and window focus establish the hint. Blur, focus-out leaving the page, pagehide and native hide clear it; native hide also blurs the active element while retaining the draft. Native hide, worker loss and actual worker restart clear the stored hint, so reopening does not reuse input ownership from before hiding. Native integration still owns the final shortcut guard and acceptance check.

[20261029T112651.676911Z-a27046e45a](../builds/20261029T112651.676911Z-a27046e45a.json) passes the full synthetic browser fixture plus boolean-only focus payload, DOM/window blur, hidden focus rejection, reveal without stale focus, retained draft and no standalone native events. This fixture tests the browser event contract; the parent native build/smoke supplies the actual WebView2 integration evidence.

`Ctrl+Shift+A` inside the embedded page now invokes the same collapse event as Escape; it preserves the draft and does not invoke shutdown. This dedicated shortcut is exempt from ordinary DAW-key isolation. [20261029T113810.876878Z-03628b470d](../builds/20261029T113810.876878Z-03628b470d.json) adds this check to the full browser fixture.

An offscreen native smoke must distinguish an active DOM element from OS keyboard focus. The [HTML focus model](https://html.spec.whatwg.org/multipage/interaction.html#focus) distinguishes these states, and [WebView2 MoveFocus](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2controller?view=webview2-1.0.2849.39#movefocus) governs native focus entry separately. A synthetic DOM focus event in the real WebView can test the app listener, native bridge and shortcut guard without bringing a user window forward; that result must be described as integration-contract coverage. Actual click, typing, IME and native focus return remain manual acceptance.

## Independent finish review

The following review covers the earlier companion layout, not the new embedded sidebar. Batch 1 sidebar evidence and independent review are recorded separately after implementation.

2026-10-29: a second agent viewed desktop/compact/mobile synthetic captures and read the shipped UI. No blocking issue found in those states. Root additionally fixed the unsaved-project shutdown error to appear inside its confirmation dialog. Final evidence is in docs/verification/2026-10-29-kimi-agent/RESULTS.md; real user GUI/hearing acceptance remains pending. No generated raster ships in the UI.
