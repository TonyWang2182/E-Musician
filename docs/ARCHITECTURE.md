# Architecture

## Desktop

`apps/desktop` contains the JUCE workspace, device panels, plugin host, and Tracktion session. `core` contains project types, editing rules, time/grid logic, and native DSP.

`EngineSession` owns the active project. Interface actions and assistant requests enter its command layer, which resolves targets, validates values and revisions, applies changes, and exposes a new snapshot. Undo groups belong to that layer rather than to individual clients.

The audio callback processes prepared audio and MIDI state. UI navigation and model work run separately. Recording permits selection, zoom, existing device editors, and supported scalar controls; input and graph changes wait until the take is complete.

## Assistant

`scripts/music_agent` serves the embedded sidebar from a local Python process. A provider adapter calls the user's configured language model. The assistant reads project and selection snapshots, proposes tool actions, and prepares a preview for approval.

The host validates the proposal against the current project before execution. Applying a proposal uses the same commands as manual editing. A model response cannot write directly into the audio engine or project files.

## Music models

Analysis and generation workers create candidate files and metadata. A local worker runs on the user's computer; cloud transport submits jobs to the configured server over SSH. Heavy models run in their own environments.

The application downloads or locates the candidate, supports preview where available, and imports it only after the user applies it. Accepted media is saved with the project so playback does not require the original cloud instance.

## Storage

Project documents reference managed audio, MIDI, plugin state, and analysis results. Save and export jobs run outside the audio callback. API credentials remain in local user storage and SSH credentials remain in the user's SSH configuration.
