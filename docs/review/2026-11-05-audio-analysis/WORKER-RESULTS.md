# 本机音频分析 Worker：实现与证据

2026-11-05。状态：三个真实算法/模型已接通，CPU/CUDA Worker、真实公开音乐、边界检查和最终 Worker 回归通过；宿主联测由主任务单独记录。本文不代替 DAW 联测、人工听感或识别质量验收。原 0.8.1 的程序、源码和启动入口未在此子任务中修改。

## 部署和来源

位置为 `E:/MusicAgent&DAW/analysis/`。虚拟环境、下载缓存、模型和候选音频均不入 Git；代码在 `scripts/audio_analysis/`，安装入口在 `scripts/setup_analysis.py`。手动分析不需要聊天模型或 API 密钥。

| 能力 | 真实实现 | 固定来源与关键版本 |
|---|---|---|
| 四轨分离 | HTDemucs；vocals/drums/bass/other；独立进程、4 秒分段、25% 重叠、shifts=0、CPU 两线程 | [作者仓库](https://github.com/adefossez/demucs)、PyPI Demucs 4.1.0；[官方权重](https://huggingface.co/adefossez/HTDemucs/tree/cbc8a9b1a87023b7fd74e7b3412e6321c0eab003) revision `cbc8a9b1a87023b7fd74e7b3412e6321c0eab003` |
| 音高转 MIDI | Spotify Basic Pitch 0.4.0，ONNX Runtime 1.20.1 CPU；输出未量化音符 | [原项目](https://github.com/spotify/basic-pitch)、[0.4.0 PyPI](https://pypi.org/project/basic-pitch/0.4.0/)；模型随官方发行包安装 |
| 和弦标签 | 自有 NumPy/SciPy Hann STFT → Chroma → 24 个大小三和弦模板 → Viterbi，另有 N 和不确定标记 | 方法参考 [AudioLabs 模板](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C5/C5S2_ChordRec_Templates.html) / [HMM](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C5/C5S3_ChordRec_HMM.html)；无预训练权重 |

环境为 Windows CPython 3.10.19、NumPy 1.26.4、SciPy 1.13.1、SoundFile 0.13.1。CPU 分离使用 PyTorch 2.5.1+cpu；额外的 `separation-cuda-py310` 已安装 PyTorch 2.5.1+cu124 并通过真实推理，当前默认注册 CUDA。系统驱动仍为 555.99。版本选择参考 [PyTorch 官方历史安装表](https://pytorch.org/get-started/previous-versions/) 与 [NVIDIA 兼容说明](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)，可用性以本机真实探针为准。

Basic Pitch 仍安装其上游依赖 Librosa 0.10.2.post1，但 Worker 已复用冻结 PCM，经 SciPy 重采样后调用上游 0.4.0 的 window_audio_file/unwrap_output/notes decoder，避免重复文件解码和 JIT 重采样；显式禁用未交付的 pitch bend 计算。和弦特征使用自有 NumPy/SciPy 实现，完全不导入 Librosa/Numba。所有直接和间接发行版本写在 `requirements-*.txt`（CUDA 的 torch 固定替换为 2.5.1+cu124）；实际安装包版本、主包源码文件 SHA、PyPI 发布文件 SHA/URL、LICENSE/NOTICE 写在本机 `manifests/<kind>/installation.json`。可审查副本见 [MODEL-PROVENANCE](worker-evidence/MODEL-PROVENANCE.json)。结果 model 另含 worker_version 和五个执行模块的合并 SHA。

HTDemucs safetensors SHA-256：`d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd`，下载时与官方 HF LFS 元数据一致，推理前重校验。Basic Pitch ONNX SHA-256：`2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`。HTDemucs 代码 MIT；**该 checkpoint 的再分发许可未明确，只按本机评测部署，不能据此宣称可商用分发**。Basic Pitch 官方发行包的 Apache-2.0 LICENSE 和 NOTICE 已保存；其他依赖许可记录按对应安装发行包保留。

## 可重复安装

在新工作树根目录运行（不会改全局 Python、驱动或 Windows 环境变量）：

```powershell
python scripts/setup_analysis.py --root "E:/MusicAgent&DAW/analysis"
# 可选独立 CUDA 12.4 环境；保留 CPU 环境，真实探针通过才切换注册：
python scripts/setup_analysis.py --root "E:/MusicAgent&DAW/analysis" --kind separate --device cuda
# 仅重做已装运行库/模型探针：
python scripts/setup_analysis.py --root "E:/MusicAgent&DAW/analysis" --register-only
```

安装器使用 `uv` 和固定包版本，命令经过 `scripts.dev.Recorder`；原始日志在 `build-logs/`，摘要在 `docs/builds/` 和 append-only DEVLOG。首次安装解析官方 HF revision 后持久化；重跑不会悄悄换 checkpoint。工作进程不执行下载，HF offline/禁用遥测仅对该进程设置。`registry.json` 只有探针通过的 Provider 才标 available；experimental 标记仍保留。

## Worker 契约

宿主按注册的 `python_executable` 启动 `scripts/audio_analysis/run.py --request <job>/request.json`。作业必须位于 `analysis_root/cache/jobs/<job_id>`。没有额外的推理孙进程，宿主超时取消只需处理它拥有的进程。

输入：协议版本 1、任务 ID、kind（separate/transcribe/chords）、注册 preset、已解码音频绝对路径、源偏移/时长、工程/clip/asset/时间线来源和受限参数。输入 1–2 声道、8–192 kHz，单次最多 600 秒；冻结精确采样范围，并保存完整源 SHA、source_start_sample/source_frames、冻结片段 SHA。采样位置采用正数 half-up 取整，结果时长以实际样本数为准。

输出：原子替换 `progress.json`，成功时一次发布不可变 `result.json`；失败/取消写 `error.json` 和终态进度。结果含相对起止秒、分离 WAV/音符/和弦区间、模型和运行库版本、参数、限制、uncalibrated 分数说明、分段/重采样信息以及离线进程耗时和资源计量。JSON 最大 16 MiB，音符最多 100000，和弦区间最多 10000；超限拒绝而不截断。

取消检查覆盖哈希/输入块/模型窗口/分离段和输出发布前；长时间不可中断的第三方调用依靠宿主终止该进程兜底。候选不会写入工程，也不会保存用户工程；接受/撤销/保存由宿主命令层负责。GPU 不可用或显存不足时可退回 CPU，并明确记录实际路径；这不代表两种性能相同。

Basic Pitch 参数：onset_threshold=0.5、frame_threshold=0.3、minimum_note_ms=80、min_pitch=21、max_pitch=108。单独的 drums/other 分轨不冒充完整音高转录；首批没有鼓分类器，没有保留 pitch bend/CC 或原音色。和弦标签为 C:maj…B:maj/C:min…B:min/N；score 是模板相似度，不是正确概率。

## 已测与待测

19 项协议/数值检查在隔离 chord 环境全通过，包括实际 STFT 特征、C 大调→A 小调、静音 N、歧义标记、精确时间边界、无效参数/音符、模型哈希、取消与不可变结果。系统 Python 未装 SciPy，执行其中 15 项并明确跳过 4 项数值检查，不额外污染全局环境；分别见 `20261105T065202.283947Z-a854c5ffbb` 和 `20261105T065159.135733Z-8f1aeaf33c`。

真实子进程的 12 个边界案例通过：静音、5 ms 短片段、越界、缺失、损坏、NaN、源哈希改变、取消、超长、鼓输入误用、5 ms 转录、静音转录；仅返回错误或合法空候选，不修改工程。见 [进程边界证据](worker-evidence/edge-probe-38686e074585.json) 和记录 `20261105T064613.314684Z-79d62ebf3d`。

另在真实 HTDemucs CUDA 推理进入 separating 后发出取消，11.14 秒后以退出码 3 结束，未发布 result.json。第三方当前段和 CUDA 清理不能保证立即退出；宿主须异步等待并保留超时只终止自有 Worker 的兜底。见 [运行中取消](worker-evidence/cancel-probe-c0d0492c2153.json)。CPU 分离和 CUDA 分离均单独跑通过，但尚未刻意耗尽显存验证 OOM→CPU 回退分支。

首次真实 Basic Pitch 管线暴露 resampy 对已删除的 pkg_resources 的依赖，已固定 setuptools 75.8.2 并扩大安装探针至完整音符后处理。首次短片段断言误把非整采样时长要求为精确小数相等，已按源样本数验证。上述失败日志保留；不能用较早的单次 ONNX forward 代替完整 Worker 验证。

本机为 i7-13700H / 系统报告 RAM 31,923,757,056 字节 / RTX 3050 Laptop 4 GB / 驱动 555.99。初测是离线 Python Worker，**无音频设备、无 ASIO buffer，无 DAW 播放/录音负载**；同时存在开发构建和运行库下载，因此这些数值是条件记录，不是实时性能保证。7 秒、44.1 kHz、双声道合成 C 大调→A 小调源，偏移 0.5 秒：

| 检查 | 墙钟 / 采样峰值 RSS | 说明 |
|---|---|---|
| CPU HTDemucs | 81.3 秒 / 1.42 GB | 四轨通过，4 秒分段、两线程；保留回退环境 |
| CUDA HTDemucs | 35.97 秒 / 1.285 GB | 四轨通过，无 CPU 回退；模型推理约 10.48 秒，前期导入约 19.38 秒；CUDA allocated 峰 575.6 MB / reserved 峰 801.1 MB |
| Basic Pitch 原完整路径 | 首次 66.5 秒；热缓存重试 65.7 秒 | 查明主要延迟在重复解码/预处理，不能只靠模型 forward 成功判断完整速度 |
| Basic Pitch PCM 复用路径 | 10.07 秒 / 157 MB | 同一源 6 个音符；ONNX 窗口约 0.52 秒、后处理约 0.73 秒，剩余主要新进程导入 |
| 和弦原 Librosa 路径 | 首次 109.5 秒 / 295 MB | 已替换，不是当前默认 |
| 和弦 NumPy/SciPy 路径 | 8.85 秒 / 100 MB | 特征/解码约 0.18 秒；C:maj→A:min 边界 3.506 秒，合成真值 3.500 秒 |

RSS 每 100 ms 采样，可能漏过更短峰值；CUDA 数据由 PyTorch 分配器统计，不是全系统显存峰值。记录见 [GPU](worker-evidence/probe-d3dd5de34566.json)、[转录](worker-evidence/probe-02aae731fbd4.json)、[和弦](worker-evidence/probe-3b5572814183.json)。

最终执行模块冻结为 `25ecddd7a242e1484441131a70d905b318063282848032374684ee8568a5b40d` 后，再次完成同一 7 秒源的三种真实推理：CUDA 分离 28.62 秒 / RSS 1.285 GB、转录 8.17 秒 / 153 MB / 6 音符、和弦 4.68 秒 / 91 MB / 2 区间；三个结果记录同一 Worker SHA。见 [最终 Worker 证据](worker-evidence/probe-26940c8f521e.json)，命令摘要 `20261105T065207.928250Z-9b7c257b8b`。此轮操作系统缓存已热、后台开发负载有所变化，不能把差值全归因于算法变化。

另从官方 Librosa 样本镜像下载了 Mihai Sorohan 的 trumpet loop 与 Kevin MacLeod 的 Vibe Ace，许可文件均指向 CC-BY 3.0，下载与归属文本 SHA 对照项目固定 0.10.2 registry。只在本机取前最多 8 秒转 PCM16 WAV；文件位于 `analysis/cache/public-fixtures/`，每段有相邻 attribution JSON 和原许可文本，音频不入 Git。真实 trumpet 转录用时约 8.83 秒，Vibe Ace 分离约 34.33 秒、和弦约 4.75 秒；模型确实输出候选，尚无标注真值或听感评分。见 [真实音乐管线证据](worker-evidence/public-probe-7320afeb18dd.json)；来源 [Librosa 固定样本清单](https://github.com/librosa/librosa/blob/0.10.2/librosa/util/example_data/registry.txt)、[Mihai 原作者样本](https://freesound.org/s/77711/)。

合成音只是实际算法运行和时域链路证据；没有真实音乐标注，不计算或宣称 note F1、SDR、和弦准确率。物理 ASIO、录音共存、人工听感、复杂音乐识别质量和长期负载仍待验。
