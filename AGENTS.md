# Repository workflow

Read `docs/CONTEXT.md` before changing the project. Use `docs/ARCHITECTURE.md` for module boundaries and `docs/BUILD.md` for reproducible commands.

- Keep source, comments, documentation, and authored interface copy in English. Preserve Unicode in user content and file paths.
- Route project edits through the common command interface. GUI and assistant clients consume snapshots and events.
- Keep network requests, model inference, JSON parsing, and blocking control work outside the audio callback.
- Record build and test commands with `scripts/dev.py`. Keep raw output in `build-logs/` and append outcomes to the local `docs/DEVLOG.md`. Publish a concise release record in `docs/builds/` and link it from `docs/VALIDATION.md`.
- Distinguish compilation, automated tests, device tests, and listening results. Update `docs/CONTEXT.md` when the working state changes.
- Do not commit credentials, local settings, model weights, user projects, SDK downloads, or generated media.
- Keep the default branch focused on the current version. Historical working records belong in the maintainer's local archive.
