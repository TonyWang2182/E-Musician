# YuE2 cloud deployment — 2026-11-06

**Verified:** pinned files, isolated environment, actual CPU loading and one short GPU audio render. **Not verified:** complete songs, listening quality, vocals, symbolic planning, the default 24GiB path or DAW integration. This task downloaded no weights, audio or backups to E:; the evidence in this folder contains only small metadata, hashes, dependency locks and logs.

## Deployed inputs

| Item | Exact version / location |
|---|---|
| Official source | `multimodal-art-projection/YuE@1116bea76032bee5668e5f097294d082fa0b84f0`, `yue2-infer==0.1.6` |
| Generator | `m-a-p/YuE2-3B@8f24312f187763b9854adeec87e437e2b03bbff1` |
| Decoder | `m-a-p/YuE2-Vae@152733a19ad43aa67e367f9b5503ef8075bb5126` |
| Environment | `/root/autodl-tmp/emusician/envs/yue2`, Python3.12.3, Torch2.10.0+cu128, Transformers4.57.6 |
| Model storage | `/root/autodl-tmp/emusician/models/yue2/<model>/<revision>` |
| Source + runnable entrypoints | `/root/autodl-tmp/emusician/workspace/models/yue2` |
| Authoritative cloud deployment manifest | `/root/autodl-tmp/emusician/manifests/model-library/yue2/deployment.json` |

The 21 runtime/config/license files total **7,794,656,016 bytes**. Upstream LFS SHA256 or Git blob hashes and independent SHA256 were checked. All 132 tracked upstream source files are fingerprinted in [source-lock.json](source-lock.json); model files are in [model-lock.json](model-lock.json). The environment uses [environment.lock.txt](environment.lock.txt) and [environment-freeze.txt](environment-freeze.txt). Existing CUDA wheels were shared from the cloud cache only after checking their locked hashes; ACE's environment, source, registry and service were unchanged. Optional vLLM is not installed. The official Torch eager route requires no FFmpeg for the tested text-to-audio path.

## Actual checks

| Check | Result / evidence |
|---|---|
| Source checkout | Passed; Recorder `20261106T100941.596064Z-87e6279814` |
| Model transfer + hashes | Passed; `20261106T100954.901121Z-d011b3674b` |
| Isolated install and dependency check | Passed; `20261106T101016.122387Z-4791fdf28e` |
| Official protocol, preflight, storage and CLI tests | **64 passed**, 2.30s, CUDA hidden; `20261106T101537.587072Z-3017ecf096` |
| Actual generator + decoder CPU loading | Passed, no forward or generation; `20261106T101608.455864Z-e8c9be7a97` and [cpu-check.json](cpu-check.json) |
| One authorized GPU audio probe | Passed only within the bounded scope below; `20261106T102322.038961Z-19a5b59536` and [gpu receipt](gpu-probe-20261106T102323Z.json) |
| Post-run telemetry failure handling | **3 CPU-only tests passed on local Windows/Python3.14**; `20261106T102525.748015Z-944a3aa48a` (its generic configuration label said cloud/Linux; the recorded command is the actual local interpreter, and the recorder now labels this action correctly) |
| Final script fingerprint + metadata collection, including future output-path cleanup | `20261106T102852.536978Z-7e416be098`, `20261106T102903.463507Z-833f0e7713` |

CPU loading covered 3,580,352,576 BF16 generator parameters and 66,374,466 FP32 decoder-only parameters. It took 16.25s overall with peak process RSS1,514,627,072bytes. These are mmap loading observations, **not inference peak memory requirements**. CUDA remained uninitialized. The upstream doctor JSON's `validated=false` refers to its hardware acceptance state, not a claim that GPU inference had already run; the later separate GPU receipt is the actual generation evidence.

## GPU test scope and results

Hardware: one NVIDIA RTX5090, compute capability12.0, Torch2.10.0+cu128 / CUDA12.8. Existing ACE stayed resident and idle. Official pipeline: `backend=torch-eager`, `low_vram=true`, memory budget8GiB, batch1, `cot=off`, empty lyrics, seed160611, original instrumental nylon-guitar prompt. Semantic token range96–192; the official ODE32 default was unchanged. No second inference or retry was performed.

- Actual generated WAV: **7.6787s**, 48kHz, stereo, 368,576frames, finite and nonzero; PCM16 peak1.0 and RMS0.15534. Peak1.0 means this is not a clipping-free quality claim.
- Semantic output hit192tokens, `truncated.semantic=true`; symbolic planning was disabled. This is a **bounded audio render**, not a completed song.
- Worker time19.23s; supervisor wall time22.54s. Model-reported semantic5.29s, NAR5.04s, VAE0.72s. This one measurement is not a production latency guarantee.
- Torch peak allocated4,400,219,136bytes; peak reserved4,420,796,416bytes. Memory budget8GiB is an upstream runtime budget, not an OS-enforced hard cap.
- Minimum free GPU memory9,960MiB. Before/after free14,774MiB; ACE PID5862 remained unchanged and active-job queries were empty. The shared probe lock was released after completion.
- Output stayed at `/root/autodl-tmp/emusician/workspace/models/yue2/probes/20261106T102323Z/audio.wav`; SHA256 `a6de203bdcd664b329b51d5facd35e59b799b1f9b01f95d67a07213e3bd9e8b1`, 1,474,348bytes. Official artifact files also remain in that cloud directory.

The successful probe used guard SHA256 `4e5e901d3bb1650e2bd4fd5a8f5ffc96617261a762e4caf3efc670af0abf5add`. Afterwards, post-run health telemetry was made nonfatal to receipt writing, with health status recorded separately from inference success, and future probe output was directed to `/root/autodl-tmp/emusician/results/model-library/yue2/probe-<stamp>`. The verified output above was not moved or deleted. The final guard SHA256 is `77328a5e126bfa526bccbb38aadda97f13535017193a29f682bb8dc92bd4e180`. The telemetry maintenance change had three CPU tests; the later directory-only change had a syntax check and **no repeat GPU run**. [deployment-script-lock.json](deployment-script-lock.json) fingerprints all seven final cloud adapter files; [deployment.json](deployment.json) records both guard hashes and the validation limits.

## Reuse and remaining work

Cloud CPU-only check:

```bash
bash /root/autodl-tmp/emusician/workspace/models/yue2/run.sh doctor
```

`run.sh generate` wraps the official CLI using local pinned files and offline mode. It refuses generation unless `EMUSICIAN_YUE2_GPU_ALLOWED=1` is deliberately supplied after assigning a serialized slot. Its default24GiB configuration was kept unchanged and has **not** been tested alongside resident ACE. The tested short8GiB path lives separately in `gpu_smoke.py`; do not treat the environment flag alone as a multi-user GPU scheduler. No automatic daemon, Agent tools or DAW hook was installed by this task.

Next meaningful acceptance is a separately authorized, suitably provisioned full-song run with listening, duration, stability and quality checks, then vocals and symbolic planning if needed. No additional rented compute is implied by these notes.

Source code is Apache2.0. Checkpoints use CC-BY-NC4.0 with additional individual-creator output monetization and academic grants in the pinned `MODEL_LICENSE`; this is not a declaration of unrestricted commercial hosting rights. Primary pinned sources are linked in [PLAN.md](PLAN.md).
