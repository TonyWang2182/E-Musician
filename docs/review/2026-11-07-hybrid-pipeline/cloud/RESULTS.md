# Cloud compute implementation and validation

Status: **coordinator-deployed final release `ed7d6a920487a651c988` passed real seven-model/native end-to-end acceptance and the final read-only cloud audit.** The sections below preserve the earlier implementation, CPU and service-control evidence; the final addendum records the subsequent real-service acceptance. Musical accuracy, listening and physical audio-device performance remain separate, unverified acceptance items.

Implemented `scripts/cloud/compute/`: protocol validation, immutable streaming WAV uploads, bounded SQLite queue, idempotent requests, atomic cancel/publication, restart interruption, fixed isolated model launchers, per-task GPU/host/disk/time reserves, normalized results, artifact serving and controlled startup. The old ACE service lock is held throughout service life; the evaluation GPU lock is held per task. The startup helper requires an explicit migration marker and never stops legacy ACE itself.

Seven adapters: ACE XL Turbo, YuE2, SCNet XL IHF, TransKun V2, ChordMini BTC, MuScriptor medium and SheetSage2. Inputs are complete submitted selections up to 600 s; generated duration request is 10–120 s. YuE2's token budget and truncation remain explicit. MIDI channels become 1–16, real controllers are preserved, raw MIDI remains intact, and any candidate boundary cropping is counted. Chord labels remain model labels with unknown confidence. SheetSage2 uses original melody MIDI, genuine decoded beat/structure fields and available ABC, not invented beats or playback-derived chord notes. SCNet keeps FLOAT32 stems without clipping peaks above unity.

Workers verify configured code/config/weight SHA before model loading. Subprocesses use a separate session, Linux parent-death signal, and per-launch ownership token. Cleanup also detects a decoder that outlives its Python parent; it does not signal a group based only on a potentially reused PID. Only approved fixed environment/python/script paths are spawned. The HTTP process imports no model framework.

Validation actually performed:

| Evidence | Result |
|---|---|
| `20261106T173712.582927Z-d050988fa0` | Initial 24 CPU tests: 23 pass, one Windows test-shim error (`os.killpg` absent); failure retained |
| `20261106T173742.682911Z-887b27eee9` | Corrected platform mock, 25/25 pass |
| `20261106T173924.495324Z-6d5315e0e4` | Expanded tests: 30 pass, 2 Linux-only tests skipped on Windows |
| `20261106T174003.486932Z-79e95431b0` | 30 pass, 2 Linux-only skipped after excluding optional empty artifacts |
| `20261106T174008.698192Z-0f89ac5466` | Scoped whitespace/diff check passed |
| `20261106T174115.486697Z-4b3b987986` | Linux CPU tests **32/32 pass**, including actual orphan decoder ignoring TERM and worker parent-death cleanup |
| `20261106T174115.517382Z-fdc2be6017` | Actual cloud pinned-file SHA preflight **7/7 pass**; no Torch import/GPU inference/service activation |

All command records are in `docs/builds/`; exact outputs are in ignored `build-logs/`. Earlier checks ran while other agents changed their own files and are not whole-repository final fingerprints. This candidate's file identities are in [SOURCE-LOCK.json](SOURCE-LOCK.json). Small actual integrity evidence is [evidence/integrity.json](evidence/integrity.json). The remote temporary test package is under `workspace/compute-validation/20261107-v1`; existing model directories, environments and ACE service are unchanged.

The preflight verified 37,339,923,805 bytes of pinned model/code/config material across the seven adapters. The existing MIR loader matches reviewed SHA `1ed93b588a631f2692cdcfd8bd59a6fd5c6a768fe38e6708e13e15bc66930c2f`. File hashing is deliberately part of a cold task's loading time, not the capability endpoint; this cost is not included in earlier warm standalone inference benchmarks.

Remaining acceptance: coordinated old-service migration, new-service real inference for each adapter, cancellation/reconnect against actual SSH transport, manual and Agent candidate acceptance, native Undo/Redo and save/reopen/offline playback, plus hardware/listening assessment. No accuracy, musical adherence or final DAW readiness is inferred from these CPU checks.

## Actual service control checks after coordinated deployment

The coordinator activated release `aedaa86c039f4be29770` on loopback port 18082. This subtask then held the shared GPU lock throughout a synthetic 0.25 s / 4044-byte WAV HTTP test and one explicit restart of the identified new compute service. It never started a model worker or changed an environment/model file.

- Initial attempt `20261106T174706.038847Z-482ea6df20` was refused by transient idle-poll lock ownership; it created no jobs/assets and did not stop the service. Its receipt is retained in [evidence/service-check-admission-failed.json](evidence/service-check-admission-failed.json).
- The test's lock admission was changed to bounded ten-second blocking acquisition. No production code or model inference was rerun for this change.
- `20261106T174748.060663Z-8aa899bb82` passed all live groups: SHA mismatch rejection, duplicate content upload, idempotent task submission, conflicting payload HTTP409, fresh TCP connection to the same task, queued cancellation, denied cancelled artifacts, and restart recovery.
- New service PID `28637` was matched to `tools/compute/server.py`, stopped only while its sole pending task belonged to this test, and restarted as PID `28832`. The pending task became `interrupted`, replaying the same request did not execute it, prior cancellation and the immutable asset survived, and the active queue was empty afterward.
- Both test jobs had no worker `attempt.json` or `output` directory. The shared lock was released only after terminal-state checks. The successful raw receipt is [evidence/service-check-passed.json](evidence/service-check-passed.json).

These checks establish real service controls and recovery, not GPU inference, SSH interruption during long artifact transfer, native candidate acceptance or listening quality. Root now owns serialized model/native/Agent end-to-end acceptance. The earlier remaining-acceptance list above describes the pre-deployment boundary; service migration and the HTTP/queue/restart items are now covered by this addendum.

## Final release and actual seven-model acceptance

The coordinator deployed final release `ed7d6a920487a651c988`, including the [MuScriptor dependency correction](MUSCRIPTOR-FIX.md), and ran `hybrid-final-20261107-v3` from 2026-11-06 18:19:21 to 18:23:26 UTC. Its report records **all seven models passed** through real native public commands and the real cloud service. MIR used 8-second excerpts of the user's verified inputs; ACE and YuE2 each received a 12-second generation request. Each model passed candidate creation without an initial project edit, accept-once idempotency, one Undo/Redo, save/close/cloud-disabled reopen with music-state comparison, and local offline render. These were actual music-model calls; Agent request fixtures were deterministic, not a live LLM test.

| Model | Candidate evidence |
|---|---|
| SCNet | Four audio stem tracks |
| TransKun | 62 notes, 14 controllers, one instrument track |
| ChordMini | Six chord regions |
| MuScriptor | 61 notes, one instrument track; velocity/tempo remain export defaults |
| SheetSage2 | 16 melody notes, five chord regions, 17 beat events, two structure annotations |
| ACE XL Turbo | Generated audio candidate accepted and reopened offline |
| YuE2 | Generated audio candidate accepted and reopened offline; token-budget/natural-ending distinction retained |

The small [coordinator report summary](evidence/coordinator-seven-model-e2e-summary.json) records the exact original report path/SHA, executable SHA, result IDs, phases and verification limits. Full original report: `E:/MusicAgent&DAW/cloud-inference/experiments/hybrid-final-20261107-v3/report.json`. Earlier v2 successes and the MuScriptor failure remain preserved; they were not overwritten or relabelled as passes. Short end-to-end probes do not establish full-song quality or every maximum-duration case.

After completion, read-only audit `20261106T182525.349778Z-84292ed08c` confirmed:

- Health `emusician-compute`, protocol 2, ready; active queue empty; identified service PID 30023 retained.
- `tools/compute` and starter resolve to final release `ed7d6a920487a651c988`; all 11 compute Python files, installer and two fixed loader dependencies match the exact local deployment manifest. Current local compute source matches that manifest too.
- RTX 5090 snapshot: 32,607 MiB total, 0 MiB used, 32,110 MiB reported free, 0% utilization; no compute process reported. Total minus reported free need not equal application allocation because driver reservations are distinct.
- Data-disk available bytes: **163,990,282,240** (about 164.0 GB / 152.7 GiB).
- No model invocation, service change, credential access or instance shutdown occurred during this audit. Full small evidence: [final-cloud-audit.json](evidence/final-cloud-audit.json).

The initial `SOURCE-LOCK.json` identifies the historical first candidate. Final deployed identities are in the audit above. The instance remains running; this status is not a shutdown or billing action. Remaining user acceptance includes listening, musical correctness and physical ASIO/MIDI coexistence; bounded reconnect is not a complete cross-application-restart recovery interface.

## YuE2 metadata correction follow-up

The coordinator's final review found that YuE2's stage-level truncation dictionary needed canonical desktop boolean conversion. The desktop helper was corrected to retain both `truncated` and stage flags; cloud compute code remained unchanged. The actual single-model `hybrid-final-20261107-v4-yue2` run passed the same native accept/Undo/save/offline-reopen path. Its candidate now explicitly records `truncated: true`, stages `{abc: false, semantic: true}`, reason `token_budget` and `timing_is_exact: false`. The original v3 seven-model data-path evidence remains valid; the v4 evidence replaces the earlier incomplete YuE2 metadata validation, without implying musical-quality acceptance.

Read-only follow-up `20261106T183017.413164Z-2916902393` confirmed service ready, empty active queue, GPU used 0 MiB/utilization 0% and no compute process. No inference, service change, shutdown or repeated code/model hash scan was performed. [final-cloud-audit-after-yue2.json](evidence/final-cloud-audit-after-yue2.json) retains this snapshot plus the v4 report path/SHA and phase summary.
