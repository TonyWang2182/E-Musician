# YuE2 Jungle evaluation evidence

Status: **the single authorized GPU candidate produced119.9987seconds of finite, nonzero audio**. ABC planning ended naturally; semantic generation hit the deliberate3000token cap. This establishes execution, not a naturally completed ending or compliance with the six requested sections. Listening/independent signal checks remain separate. The GPU slot has been released; no retry or second candidate was generated.

The [plan](PLAN.md) fixes the entire original1304-character prompt, empty lyrics, seed170611, full model-generated ABC, semantic2700–3000token budget and8GiB low-memory eager runtime. Input file SHA256 is `5f080976c665d1917c3b9a56d41dcb39f6741237f3a45b57abd9230383834c52`; effective style (only final newlines removed) SHA256 is `d52750d660e226231a13f846b1ac8ceecbcfb11dc446c13456b0d853333e9678`.

## Preparation and audit

- Read-only pinned upstream source inspection: Recorder `20261106T121629.045181Z-14cfda61f7`, `121630.372104Z-a2b7ebbde4`, `121631.454093Z-69de9dc7b3`, `121656.561363Z-ae2edfbeee`, `121657.769787Z-bf743e753d`, `121658.845056Z-6d2a850678`, `121745.349422Z-bbced69230`, `121746.759719Z-ec4c220c6b`. These establish the lack of a hard seconds field, CoT behavior, low-memory policy and natural VAE output length.
- Initial CPU static protocol/tokenizer check passed, with no CUDA initialization: `20261106T122055.327099Z-2642b093cc`.
- Independent review requested guard fixes before inference: process-exit signaling races, preserving failed status if cleanup fails, stdout terminal receipt when disk writing fails, and recording lock/admission failures. These were fixed before any GPU call.
- First local CPU fault suite failed because Windows has no `os.killpg` to patch by default: `20261106T122211.881232Z-2fee5c03bd`. The mock was made explicitly portable; **4/4 passed** in `20261106T122221.113957Z-811d97124a`. This was a test-fixture issue, not a GPU failure.
- Final cloud static preflight passed: `20261106T122234.249777Z-462fe89796`; prefix329tokens, worst planned prefix4427tokens, one acoustic chunk at the3000token cap; CUDA remained uninitialized. [Static receipt](yue2-static.json).
- Actual executed evaluator SHA256: `86d4f24aad6ed822c78e3ab7ced9f89d5044f03a4cdbea46a2193e9b56fec485`.
- Single authorized inference Recorder: `20261106T122252.048283Z-1a49fb6983`. Source, weights, environment, DAW and production ACE remain unchanged.

The cloud output location is `/root/autodl-tmp/emusician/results/evaluations/jungle_20261106/yue2-20261106T122253Z`. The cloud log is its `worker.log`. The original generated ABC plan is retained in `plan-stage/`; official native artifacts exist in `native/`, and the FLOAT WAV is `audio.wav`. Local JSON evidence does not contain audio.

## Actual terminal results

Machine/runtime: NVIDIA GeForce RTX5090, Torch2.10.0+cu128/CUDA12.8, official eager BF16/FP32 low_vram mode with8GiB budget, one request, idle ACE resident. This was a fresh YuE2 process with existing model files/OS cache; it is neither a virgin download timing nor a warmed resident-service benchmark. No device audio, DAW or live monitoring was used.

| Measurement | Observed result |
|---|---|
| Generated waveform | 5,759,936frames,119.9986667s,48kHz stereo FLOAT WAV |
| Whole supervised attempt | 107.9483s |
| Worker lifetime through audio validation | 105.7740s |
| ABC planning | 44.2234s,3259content tokens, `truncated.abc=false` |
| Semantic generation | 40.1497s,3000tokens, `truncated.semantic=true` |
| Acoustic NAR / VAE | 11.1854s /1.4045s |
| Phase sequence elapsed, excluding initial pipeline construction | 99.3899s; includes intermediate evidence saves |
| Resolve/integrity / generator load | 5.8068s /0.3026s |
| Torch peak allocated / reserved | 5,463,789,568 /5,649,727,488bytes |
| WholeGPU minimum free | 8,788MiB; before/after14,774MiB |
| Existing ACE | PID5862 unchanged, active-job queries empty, final health read passed |
| RMS / absolute peak | 0.1514749462 /1.0 |
| Fraction of samples with abs≥0.999 | 0.0000052952; this threshold statistic is not an independent distortion assessment |

The pipeline's budget reserves2GiB and limits its Torch allocator; it does not cap driver memory or other processes. The unmodified upstream decoder clamps audio to[-1,1]. This evaluation added no normalization, crop, stretch, fade or post-processing to force the desired duration. The final duration follows the3000codec-frame cap and natural decoder length; it is not proof of exact-duration control or a naturally completed outro. ABC ending naturally does not mean the audio finished naturally: the evaluation deliberately stopped semantic generation at3000tokens. If the outro is absent or cut off, this capped sample cannot establish that the model itself cannot generate one.

Waveform SHA256: `eb6ed94cabb06043407fa392e83d38b988f023fc7d63caa3f5b179b4ff6ce989`, **46,079,576bytes**. Model request/config identity: `18d8814ea5cbcb7dd93fa39d04385ba01aa3d50941c13cdfae260514d8c234d4`. Generated ABC SHA256: `fa75cf672de48204f4868689ec9e46ab811ff59f01328b6e26ff125ac91d366f`. Exact evidence is in [attempt](yue2-attempt.json), [ABC summary](yue2-plan-summary.json) and [static request/config](yue2-static.json).

No claim is made yet about170BPM adherence, actual Amen timbre/cuts, six-part ordering, heavy sub quality, MC fragments versus sung vocals, or perceptual quality. The ABC is model-generated diagnostic material; it is not an authoritative transcription of the output and does not certify the requested arrangement. One seed/candidate cannot establish general model superiority.
