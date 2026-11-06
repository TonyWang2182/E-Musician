# Native first compile handoff

Status: implemented, waiting for the root agent's recorded build and tests. No model, hardware or listening result is inferred from source changes.

## Contracts and boundaries

- `start_analysis` accepts `execution` (`auto`, `local`, `cloud`) and optional `model_id`. Capabilities combine the existing local registry with the independent compute registry. Selection resolves once; explicit unavailable routes are rejected before launch. Cloud fixed models reject local-only parameter knobs. Manual controls and Agent use the same commands.
- `score` exposes paged `notes`, `chords`, `beats`, `structure`. The note page derives instrument identity from canonical `midi_tracks`. Summary counts CC separately from injected GM program events: `controller_count` is model CC, `program_change_count` is one program event per imported MIDI track. Tracktion stores CC/program values shifted left seven bits; public existing controller events retain that native representation (`type=4097` is program).
- Every distinct source instrument/channel becomes an ordinary MIDI track. Notes, pedal events, program, channel and drum identity survive explicit import. Source audio remains unchanged. Candidate tempo/beat estimates are annotations and never silently set project tempo.
- Complex chord strings are preserved. Unknown confidence is internal `-1` with `uncertain=true`, mapped back to JSON `null` at public chord APIs. No jazz-extension reduction is performed.
- Accepted beat, section and instrument metadata are retained in schema 8 `annotations_json`. `get_analysis_annotations` returns bounded pages for `structure`, `beats` or `midi_tracks`; section/beat times are project absolute. Its `notes` and `chords` views derive current events from the authoritative Edit and accept optional `kind` filtering. `Score → Saved score` exposes the same four graphics after offline reopen. MIDI and chords use normal arrangement tracks/lanes; there is no notation engraving or separate section timeline lane.
- Schema 8 is used only when its fields are needed. Existing generation schema 7 and ordinary separation schema 5 remain loadable. Saving over an existing schema 8 file is allowed. New audio remains packaged as local project assets.
- Generation selects ACE or YuE2; actual duration and truncation are shown. Immutable result metadata (`completion`, `limitations`, `truncated`, `conditioning`, `processing`, `warnings`) is exposed and retained in saved provenance alongside the original request.

## Tests prepared, not yet executed here

`tests/EngineSessionHybridSmoke.inc` runs within the existing isolated generation smoke session. The source is synthetic PCM, the score fixture is explicitly synthetic. It checks nullable tempo/confidence, malformed pedals/sections, paged instrument identity, native import, range placement, channels/programs/pedals, controller-only MIDI export channel, one Undo/Redo, repeated save and offline reopen, saved score projections and explicit-route refusal. It does not call a model, network or physical device.

Existing Analysis/Generation panel screenshot tests remain the UI baseline. Added eight score captures cover candidate/saved projections, EN/ZH, 600/930-pixel widths. They are labelled synthetic. Root owns unified compilation, CTest, actual cloud end-to-end tests and final release evidence. Two static `git diff --check` calls passed; normal CRLF-to-LF Git notices were emitted.
