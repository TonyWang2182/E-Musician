# YuE2 original Jungle prompt evaluation

2026-11-06. One candidate only. Cloud weights, source, environment and production DAW remain unchanged. The original [prompt](../prompt.txt) is read as UTF8 and only trailing newline characters are removed. Its entire text is the model `style`; no paraphrase, appended duration text, substituted lyrics or supplied composition is used.

## Fixed request and runtime

- `lyrics=""`, `seed=170611`, `cot="full"`. The model itself generates a chord-annotated ABC plan; this is not a six-section timeline or proof that the structure is followed. The user permits ragga MC fragments but requests no full sung vocals. Empty lyrics and the style condition do not guarantee that result.
- ABC sampling retains official defaults: temperature0.7, top_p0.9, top_k30, repetition_penalty1.005, penalty_window100, min32/max4096tokens.
- Semantic sampling retains official defaults except min2700/max3000tokens: temperature1.0, top_p0.95, top_k100, repetition_penalty1.2, penalty_window50. Full-CoT guidance defaults to1.0. The 25Hz codec gives nominal108–120seconds; the decoder's natural frame count is `1920*T-64`. There is no duration-seconds request field, and early EOS/token truncation are separately reported. No crop, stretch or normalization is added to force120seconds.
- One batch, BF16 generator, FP32 listening VAE; official `torch-eager`, `low_vram=True`, memory_budget8GiB, VAE512-frame cores/16-frame halo, default32-step midpoint ODE, no FP8/vLLM/compilation.
- Models/source/env exactly match the [deployed YuE2](../../2026-11-06-cloud-model-library/yue2/RESULTS.md). Source `1116bea76032bee5668e5f097294d082fa0b84f0`; Torch2.10.0+cu128, Python3.12.3, RTX5090. The existing idle ACE remains resident.

## Execution and evidence

The parent approved these settings before inference and assigns the exclusive GPU slot after ACE finishes. Static preflight checks source revision, untouched prompt hashes, actual tokenizer prefix, worst-case planned context and chunk ranges, protocol validity and uninitialized CUDA. The `run` action refuses to proceed unless its script/prompt hashes match that preflight.

The supervisor uses the shared exclusive flock, requires no active ACE jobs and12GiB free GPU at admission, polls every0.5seconds, and stops only its own process group on ACE activity, freeGPU below1GiB, or1200seconds elapsed. There are no OOM retries or rerolls. A terminal attempt file prevents accidental repeat inference. Health-read failures cause a bounded stop; post-run health failures cannot erase terminal inference evidence.

The worker uses the official public APIs once each: plan → semantic → synthesize → decode. It saves the generated ABC plan before later stages, saves semantic tokens/latents, and constructs the official SongResult with native manifests. The WAV is FLOAT at48kHz stereo; the upstream decoder already clamps samples to[-1,1], which is disclosed rather than hidden by further processing.

Cloud code/prompt/metadata: `/root/autodl-tmp/emusician/workspace/evaluations/jungle_20261106/`. Cloud audio and full artifacts: `/root/autodl-tmp/emusician/results/evaluations/jungle_20261106/yue2-<UTC stamp>/`. Only small JSON receipts return to this repository. The recorded entry is `scripts/cloud/evaluations/jungle_20261106/yue2_record.py`: inspect / upload / check / authorized run / collect.

Receipt fields distinguish playable finite/nonzero audio, actual duration, ABC and semantic truncation, all phase timings, allocator peak memory and wholeGPU headroom. Signal validation cannot establish Amen identity,170BPM, sub-bass quality, MC treatment or six-section adherence; those remain listening criteria. The resulting plan and tokens are diagnostic evidence, not a quality score.
