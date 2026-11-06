# Final independent transport and native-pipeline review

Reviewed at **2026-11-06 17:58 UTC** (2026-11-07 01:58 Asia/Shanghai), working-tree base `a6951f3d6cad94f4f274ecbef2b28c5299904e58`. Status: **read-only review complete; no additional blocking correctness issue identified in this scope**. The coordinator owns the ongoing real-model/native/Agent acceptance and the final release decision.

This review examined result loss, duplicate inference, cancellation/reconnection, MIDI preservation and potentially blocking work. It did not change production code, deploy/restart a service, submit GPU work or rerun another agent's tests. It is not a listening, accuracy or performance certification.

## Findings and disposition

- The previously reported short-body download issue is corrected: an early EOF becomes a transport error and retries the artifact download only. A completed body with a bad SHA remains a validation failure. The task identity and remote inference result are not replaced to retry a download.
- Task submission persists `remote-request.json` before network submission and uses a fixed request ID. A lost POST response can replay that same ID; changed content conflicts instead of spawning a replacement under the same identity. Result kind, model, input SHA and conditioning must match before publication.
- Frozen audio is streamed into a local WAV with finite-sample checks and a content SHA. Downloaded artifacts use bounded byte counts, declared sizes, SHA verification and temporary-file publication; a different existing artifact is preserved and rejected. Neither helper sends a DAW project to the model service.
- Analysis/generation accept prepares and verifies assets on a background job, then checks the project revision and source binding again before applying one control-thread transaction. Repeated acceptance returns the existing receipt; acceptance after Undo requires Redo. Validation failures do not intentionally commit a partial candidate.
- MIDI imports retain event channels by splitting native clips where necessary; controllers and program changes are recorded separately from notes. The `>512`-note fast path in `applyTo` does not bypass the later `production::applyGraph` controller restoration. Schema 8 persists clip channel and score annotations; unknown chord confidence remains null rather than a fabricated numeric score.
- Remote calls, model inference and large file hashing/copying are outside the audio callback. Native project application still occurs on the control thread and must be assessed through the coordinator's measured acceptance; static review cannot establish a latency guarantee for the maximum allowed 100,000 events.

One explicit operational boundary remains: reconnection is bounded. A persistent failure of `Tunnel.open()` ends the helper while preserving the remote task and local request record. This is not a complete cross-application-restart task-recovery UI. Do not describe arbitrary prolonged disconnection or application restart as automatically recoverable; do not submit a fresh task merely to retrieve an already-completed result.

The installer natural-exit race was already reported separately and the coordinator has fixed its local maintenance code. This review did not modify the running frozen service release.

## Evidence boundary

Earlier live service evidence in [RESULTS.md](RESULTS.md) covers actual HTTP SHA checks, duplicate upload, request idempotency/409, queued cancellation and interrupted recovery after a controlled restart. `tests/EngineSessionHybridSmoke.inc` explicitly covers synthetic multi-instrument notes, pedal/program/channel retention, null confidence, one Undo/Redo and offline schema-8 reopen. `tests/HybridComputeEndToEnd.py` defines the real-model acceptance checks. Reading these tests does not assert their current run passed; final execution evidence belongs to the coordinator's run records.

## Reviewed file identities

These hashes identify the inspected working-tree contents, not a whole-repository freeze. Subsequent changes require the relevant review/verification to be refreshed.

| File | SHA-256 |
|---|---|
| `scripts/cloud/compute_client.py` | `6e8c3adcb44a9582aee67bd798f64e82c9a9566b877a4cefbb087e3163e131a4` |
| `scripts/cloud/run_analysis.py` | `062236bc34ce1619da0d27a4c47172c90c1c2af61510af489708033801b87312` |
| `scripts/cloud/run_compute_generation.py` | `8ba0b2c73b7a542e822254acb7f1dbf65f166d7ce0a2f7895c3e27d23111b54f` |
| `scripts/cloud/run_generation.py` | `8e4384d3ec6ab2de804ec556ac335f956898779340b1998fb8c8e72bedce5561` |
| `apps/desktop/EngineSessionAnalysis.inc` | `66a6d1e02c07e1319ab5f582ef0556b3f221e2afae2556fb21f14c9f3c263018` |
| `apps/desktop/EngineSessionGeneration.inc` | `2f57de27f407388e04f3487a1d9fc44560001f50aedbd1a47daa31d6f2eb0381` |
| `apps/desktop/EngineSessionHybrid.inc` | `f6ee5bc9ac85b4f924c4affc4b78f9491cf37e2b4a04107a4ba022f3de6074bb` |
| `apps/desktop/EngineSessionModel.inc` | `490049cf155e60c9401627a065141e29d28dac69bc405a6df2c15a851af98518` |
| `apps/desktop/EngineSessionAutomationRouting.inc` | `7774304ba43a55d42f098b4ffe9fc7469eeb6a41e274e11e85850c42f01ee524` |
| `apps/desktop/ProjectStorageHybrid.inc` | `3e7175d02260a771f52dd7d65cb519613d3d0160f11a70550f9d20f650e7d136` |
| `apps/desktop/ProjectStorageAnalysis.inc` | `b71e76fbf9e325397ec1e3f6859bb015adbef4d6abe0c0d81538fd9128a83c3e` |
| `apps/desktop/ProjectStorage.cpp` | `81b3392989dc4045796ea1365d649fd41454d9bc35e8a7cb0be542d2e0a30f46` |
