# Native hybrid pipeline scope

Status: implementation in progress; no build, hardware playback or model-quality acceptance implied.

Owner: native C++ / JUCE UI / project persistence and native tests. Root owns Python transport, registry, version, unified build and release; cloud/Agent work has separate owners. Preserve existing 0.12.1 binary and user projects.

1. Read-only compute registry augments existing local capabilities. Manual and Agent use the same `start_analysis` execution/model fields; explicit routes never silently fall back. Generation selects ACE or YuE2 through the same candidate commands.
2. Canonical candidate MIDI tracks retain notes, instrument/program/channel and controller events. A read-only flat note page is derived for UI/Agent. SCNet audio remains four ordinary stems. Chord labels remain raw, with absent confidence represented as unknown.
3. SheetSage2 score candidates expose notes/chords/beats/structure separately. Explicit import adds ordinary MIDI tracks and annotation metadata in one Undo; it does not silently change project tempo. Saved schema 8 preserves accepted metadata locally and requires no cloud connection to reopen.
4. Keep file/network/model work outside control/audio callbacks. Cloud transfer uses the isolated helper, source/revision validation, cancellation and bounded resources; no user process/device changes.
5. Preserve paper surfaces, compact selectors, visible action errors and graphical candidate previews. UI follows the supplied brief; as a subagent without an interview surface, existing approved PRODUCT/DESIGN are the design authority.

Validation plan: schema 8 round-trip and malformed candidates; mixed MIDI channels/controllers/programs; unknown complex chord labels; score annotations; one accept/Undo/Redo/save/reopen; explicit-route refusal; existing local fixture regression; narrow/wide EN/ZH UI captures. Root executes the recorded build/tests after source freeze. Synthetic fixtures must be labelled and never claimed as real inference or listening.
