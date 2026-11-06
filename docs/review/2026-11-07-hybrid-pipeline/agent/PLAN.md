# Agent hybrid compute integration

2026-11-07 (Asia/Shanghai). Status: Agent implementation, isolated tests and parent-owned frozen native/cloud integration complete within the documented acceptance scope. Final evidence combines the six other models from v3 with the corrected YuE2 run from v4; this agent independently reviewed both reports and saved artifacts. See [RESULTS.md](RESULTS.md) for evidence and remaining listening, hardware and real-LLM evaluation boundaries.

Owned files: `scripts/music_agent/` and Agent-specific tests. The parent owns build, remote deployment and final frozen verification. Native contracts belong to `native_generation`; the queue and model adapters belong to `cloud_ace`.

1. Preserve scope/revision checks and confirmation; add explicit model and execution routing from real host capabilities.
2. Support SCNet, TransKun, ChordMini, MuScriptor, SheetSage2 and YuE2 through the same native task commands. Keep old local providers and project-owned generation defaults.
3. Project only bounded metadata to the language model: note pages, instrument and CC counts, original chord labels, beat and structure summaries. No local paths, service credentials or full audio.
4. Use actual track counts in the import review and readback. Keep automatic polling outside the LLM and audio callback.
5. Update compact English/Chinese capability and confirmation text using the existing design. Test unavailable explicit routes, malformed metadata, scoped multi-track import, cancellation and legacy compatibility.

UI method: Impeccable context and clarify/craft-floor references, Operate mode. No new visual system and no computer-use.

Final evidence and manual test prompts will be recorded alongside this file. All execution uses the repository Recorder; intermediate changing-source tests are not final reproducible-build evidence.
