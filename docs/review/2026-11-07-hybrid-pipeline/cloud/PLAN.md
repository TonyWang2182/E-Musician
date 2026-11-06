# Unified cloud computation — implementation plan

Status: implementation in progress; source is changing. No new deployment or GPU run is claimed by this document.

1. A new loopback HTTP service on port 18082 owns one SQLite queue for ACE, YuE2, SCNet, TransKun, ChordMini, MuScriptor and SheetSage2. Each model invocation is a separate process in its existing isolated environment; process exit releases its GPU allocations.
2. Acquire the old ACE service lock for the new service's entire lifetime. Deployment must first stop the idle old service explicitly; merely checking its queue is insufficient. Each job additionally owns the existing evaluation GPU lock. Never kill unrelated processes or change existing model environments.
3. Accept only bounded, SHA-addressed WAV uploads and fixed model/task mappings. Never accept caller-selected commands, host paths or arbitrary model downloads. State and artifact publication remain atomic and idempotent; cancellation, supervisor failure and restart have durable terminal states.
4. Adapt pinned upstream inference to complete submitted audio (up to 600 seconds), preserving raw MIDI expression, chord labels and structural evidence. No fixed eight-second fixtures or quality claims are part of this API.
5. CPU tests cover protocol, upload integrity, queue/idempotency, cancellation/publication races, subprocess cleanup and result normalization. Root coordinates deployment, real GPU checks, local transport, native/Agent integration and final acceptance.

Evidence: every actual test command uses `scripts.dev.Recorder`; final results list exact records and unresolved validation separately.
