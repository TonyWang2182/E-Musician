# MuScriptor original-rate audio dependency correction

Status: **implemented, CPU-verified, deployed by the coordinator, and verified through real MuScriptor/native end-to-end acceptance.** The original repair subtask changed no cloud service, environment or weights; subsequent coordinated deployment and acceptance are recorded below.

The coordinator's actual E2E v2 task `cd31e019663a41f88856c23eaabd2754` failed with `ModuleNotFoundError: No module named 'scipy'`. The retained [cloud failure receipt](evidence/muscriptor-adapter-failure.json) and local experiment report identify the same request. Its outer worker ran for 2.885 seconds and failed before the adapter's `running` phase; the supervisor's `inference_started` field means the worker process was launched and does not establish that model transcription ran.

Root cause: shared `read_audio` imported `scipy.signal.resample_poly` unconditionally. MuScriptor accepts the original waveform/rate and performs its own upstream conversion, so its fixed environment legitimately lacks SciPy. Its previous standalone probe used SoundFile directly and therefore did not expose this new adapter dependency.

The change moves the import into the existing `target is not None and target != rate` branch. Original-rate and already-matching-rate reads no longer need SciPy. SCNet/TransKun requests that actually change rate still use the same polyphase resampler, rational ratio and float32 conversion. No inference setting, source/weight pin or environment dependency changed.

## Checks and records

| Record | Actual outcome |
|---|---|
| `20261106T181626.541293Z-07e4b23ced` | Read-only SSH collection of this failed job's error/attempt/log |
| `20261106T181711.506379Z-c47a512223` | 35 CPU tests: new 3 regression cases passed; 3 existing upload cases failed because default C temporary storage did not meet the existing 3 GiB disk reserve; 2 Linux-only skips. Failure retained. |
| `20261106T181749.784489Z-ffaa7d1b97` | Same 35 tests with explicit E temporary storage: 33 passed, 2 Linux-only skips; no reserve reduction |
| `20261106T181755.516471Z-dfe367ba66` | In the existing cloud MuScriptor environment, executed the corrected adapter source in memory and read the same submitted 8-second stereo 44.1 kHz WAV. SciPy absent and explicitly forbidden by an import guard; 352,800 frames loaded, no SciPy import, no Torch/model import or GPU inference. Live deployed files unchanged. |

New unit coverage in `tests/test_cloud_compute_audio.py` checks original/matching rates without SciPy, the unchanged resample branch and nonfinite sample rejection. Small actual CPU evidence is [muscriptor-audio-fix-cpu.json](evidence/muscriptor-audio-fix-cpu.json). Recorder raw outputs are in ignored `build-logs/`, command summaries in `docs/builds/`, and DEVLOG entries were appended.

Corrected `scripts/cloud/compute/adapters.py` SHA-256: `90304d14bb1c30ddeb36c3264c9ae7bd2eb8049fbd15a157ecc7467ea80410a2`.

The earlier `SOURCE-LOCK.json` remains the historical initial candidate identity. At the CPU-only handoff, coordinated deployment and actual inference were still pending; the subsequent acceptance is recorded below. No failed task was silently replayed and no old result was overwritten.

## Subsequent coordinated deployment and real acceptance

The coordinator included the exact corrected adapter SHA above in final release `ed7d6a920487a651c988`. Its v3 MuScriptor task `c8d75794838d4b9888cc9b1bcfd4835f` passed real inference on the 8-second piano excerpt: one track, 61 notes and the expected export program, followed by candidate acceptance, idempotency, one Undo/Redo, save/close/cloud-disabled reopen and local offline render. Original report: `E:/MusicAgent&DAW/cloud-inference/experiments/hybrid-final-20261107-v3/muscriptor/report.json`; [small seven-model summary](evidence/coordinator-seven-model-e2e-summary.json) retains this result ID and phases. No listening or transcription-accuracy conclusion follows from these checks.

Final read-only audit `20261106T182525.349778Z-84292ed08c` verified the running release's adapter and all other compute source hashes against the deployment manifest. Its queue was empty and the RTX 5090 reported no allocated application memory or compute process. See [final-cloud-audit.json](evidence/final-cloud-audit.json). The failed v2 request and all diagnostic/CPU records remain intact.
