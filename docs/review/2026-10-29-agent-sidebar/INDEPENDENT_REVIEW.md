# Agent sidebar batch 1 — review notes

Date: 2026-10-29. Reviewer: `kimi_provider` child. This is an independent source review of MainComponent, selection projection, Python task/scope handling, and the UI contract. The provider and native service portions were implemented by this reviewer and received a self-review, not a second independent implementation review. Final native build/integration evidence is owned by the root task.

## Findings and disposition

1. **P2 — track-header selection still authorized a clip instead of a track.** Before correction, a header click called `EngineSession::selectTrack`, which retained the engine's first active clip; `ArrangementView::update` then projected that clip as selected. MainComponent had no explicit track focus. Consequently a normal request to change the clicked track's volume could be rejected by the selection compiler. Corrected in `ArrangementView.cpp` with a distinct `explicitTrackSelection`, `onTrackFocus`, and `explicitSelectedTrackId`. Header selection clears UI clip/time selection and survives refresh; clip/timeline/ruler selection clears the track marker. Engine active-clip semantics remain unchanged. MainComponent wiring is owned by root. Existing native arrangement smoke now checks track-only persistence, unchanged musical revision, preserved engine active clip, and restoration of clip/timeline selection. **Implementation complete; final native build/test must include this correction.**

2. **P2 — proposal scope label did not match the actual runtime contract.** `runtime.py` stores `plan.scope` as a frozen object, while the previous web renderer compared it directly to strings. A project-wide proposal therefore displayed a generic selection label. UI owner corrected `app.js` to read `scope.mode`, retain the proposal revision, and handle project/selection/clip modes. The reviewer re-read the correction at `app.js:190–194`; synthetic UI fixture now uses the actual object shape. **Source correction verified.**

3. **P2 — native smoke emitted duplicate check names.** The two viewport sizes originally both emitted `minimum_layout` and `native_parent_capture`; the integration wrapper intentionally rejects duplicate names. Root added viewport-width suffixes. **Source correction verified.**

4. **P2 — OpenAI inherited an incorrect Kimi network error.** Shared transport now names `self.label`. OpenAI uses an existing HTTPS proxy route only when it is an explicitly addressed loopback listener (`127.0.0.1`, `localhost`, or `[::1]`, valid port, no credentials/path/query/fragment). Other proxy routes are ignored, Kimi remains direct, and API origin/TLS verification/redirect rejection remain unchanged. No new proxy is installed. HTTPError streams are closed without reading so deferred resource warnings cannot echo the raw error reason. **46 synthetic provider/credential/proxy tests passed**, with no source change during the command: [record](../../builds/20261029T111041.123340Z-3bd38a7ccf.json). The child made no real API requests.

## Remaining non-blocking observations

- **P3 — selection projection has dense-project costs that need measurement.** `MainComponent::synchronizeAgentSelection` checks selected clip IDs while scanning project clips; `EngineSessionSelection.inc` validates each supplied clip ID using the linear `findClip` in `EngineSession.cpp:343`. At the 4,096-ID limit this can perform many repeated comparisons on the message thread. Note validation caches an index, but rebuilds the index of the entire MIDI clip when its note snapshot changes. This is a source-derived cost concern, not a reproduced stall. Use ID-indexed lookup or generation caching if the bounded benchmark demonstrates an issue; do not infer large-project performance from the small native fixture.
- **P3 — a concurrent GET can briefly overwrite the public cached snapshot.** `AgentRuntime.state` checks idle under the lock, reads the bridge outside that lock, then stores the snapshot. A new task can start between those steps. The old GET result can therefore temporarily replace the newer UI cache and hide Undo until a later refresh. Apply and Undo independently read native state and enforce revisions, so this does not authorize a stale edit. If hardening further, capture a task generation and only publish an idle read when that generation is unchanged.

## Reviewed invariants

- GUI projection and native edits run on the control/message thread; model/network work stays in the helper. No provider call was added to the audio callback.
- Native helper dispatch checks a shared lifetime flag before queued work, and marks timed-out work abandoned. Accepted unauthenticated connections have a deadline. Read/write waits are bounded and sockets are explicitly nonblocking; helper shutdown joins cooperatively rather than force-terminating a C++ thread. Local OS process/file calls are not claimed to have a hard realtime upper bound.
- Embedded shutdown detaches the helper rather than closing the musical project. Retry owns only its Python helper. WebView navigation stays on the local service origin, and native callbacks retain safe component pointers.
- A ready plan retains its exact project revision and frozen scope. Apply re-reads those facts; the native batch receives the selection revision as well as the music revision. Duplicate application consumes the plan before dispatch. Undo is restricted to the known resulting revision.
- Model/provider settings are rejected while a task worker is alive. Provider credential namespaces and private Responses replay metadata are not shared across providers. Browser state contains no API credential. The UI clears an unsent key on provider changes.
- Missing/truncated selection is rejected rather than silently widened. The current tool budget still limits complete note reads to 2,000 notes per clip; this is a product limit, not a claim to arbitrary dense MIDI editing.

## Visual evidence and limits

Inspected synthetic `sidebar-ready-340.png` and `sidebar-settings-340.png` plus the shipped web source and design brief. In those states the bottom composer, concrete Apply/Discard controls, selected-object context, provider/model settings, and configured/pending distinctions were readable without visible clipping. The scope contract issue above was corrected after review.

This does not establish native WebView input acceptance, Chinese IME behavior, physical MIDI/audio operation, or long-session performance. A JUCE component snapshot may omit the WebView child HWND and is not sufficient visual proof by itself.

## Final integration checklist for root

- Include the final track-header change in native component smoke and sidebar scope smoke.
- Verify selection context, same-project/single-engine identity, hidden-page draft preservation, helper stop/restart, actual native page load, and input focus isolation.
- Keep offline synthetic/native results separate from the separately authorized real-provider request record and subsequent human audio/keyboard acceptance.
- Record dense selection projection timing before making a broad responsiveness claim.


## Final root disposition (2026-10-29)

The dense-selection observation was addressed after the original review: indexed clip membership and reserved hash-based note membership, with no full note index for empty note selection. Final Release CPU-only measurement: 4,096-clip rebuild+lookup P95 8.906 ms; 100,000-note cold index 11.421 ms; cached 2,000-ID query P95 0.109 ms. No claim about full project/UI/audio latency. The concurrent public GET cache observation remains a non-blocking UI issue; guarded writes read fresh native state.

Final frozen-source CTest5/5, Python178 and native sidebar23 passed. The track-header scope/clip restoration regression passed. Actual WebView page, same-project identity, draft visibility, helper loss/restart and no music mutation passed. Offscreen Windows focus was absent; the input bridge check uses a synthetic DOM focusin through the real WebView, not physical keyboard input. Real OpenAI/Kimi tests and all remaining manual limits are recorded in ../../verification/2026-10-29-agent-sidebar/RESULTS.md.
