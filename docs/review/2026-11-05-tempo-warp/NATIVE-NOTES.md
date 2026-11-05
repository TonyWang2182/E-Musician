# 0.10.0 原生固定比例 Warp 实现笔记

状态：**已实现，中央构建/自动测试及人工听感验收待完成**。本文件描述实现与待验证边界，不将源码存在等同于验证通过。最终构建、失败修复和测试结果由本轮 RESULTS / `docs/builds/` 记录覆盖。本子任务未启动单独 native build，也未操作用户的两个启动记录。

## 来源与部署

- Signalsmith Stretch 1.3.2：`https://github.com/Signalsmith-Audio/signalsmith-stretch`，固定 commit `88061fd4eda56a2353c5d65c74aa3f4ccf76f9da`。
- Signalsmith Linear 0.6.6：`https://github.com/Signalsmith-Audio/linear`，固定 commit `7bb1c8f36794d6980080ce817c91f8da8fe56a66`。
- 两者 MIT 原文保存在 `docs/licenses/signalsmith/`；完整头文件与许可证 SHA256 和上游地址保存在 `cmake/signalsmith.json`。
- 本地依赖为被忽略的 `_deps/signalsmith-stretch`、`_deps/signalsmith-linear`。`scripts/bootstrap_stretch.py` 仅克隆缺失仓库并 checkout 固定提交；不会重置现有仓库。`--verify-only` 校验 Git HEAD 和清单文件 SHA256，CMake 配置阶段调用。
- 固定 renderer ID：`signalsmith-1.3.2-88061fd4-linear-0.6.6-v1`。缓存位于用户应用数据目录 `E-musician/cache/warp-v1/`，按准备后的 PCM SHA256、17 位速度比例和 renderer ID 生成 key。

## 管线和时域

原音频是永久来源；WaveAudioClip 播放后台渲染出来的 PCM，实时回调不初始化拉伸器、不访问网络、不解析 JSON，也不执行此处的文件读取/哈希。渲染保持原准备音频的采样率、通道数；硬件/离线导出采样率由已有 Tracktion `sincMedium` 路径转换，不在 Warp 中额外重采样。

权威存储中的 `sourceOffset`、`sourceDuration` 始终是原音频秒数。令 `r = targetBpm / sourceBpm`：

```text
originalSourceAt(projectTime) = sourceOffset + (projectTime - timelineStart) * r
playbackSourceOffset = sourceOffset / r
audibleDuration = originalSourceSpan / r
```

关闭 Warp 时 `r = 1`；裁剪/切分保留同一原文件区间。波形快照引用真实播放 PCM，另给出原始波形来源及两个时域的 offset/duration，避免绘制和声音不同步。分析 worker 读取当前听到的 dry PCM，因此新和弦/MIDI 候选按其实际播放时域落位。已有、附着于来源 clip 的和弦区间在 Warp 提交中使用同一仿射映射；已经接受到独立音轨的 MIDI/分离轨保持独立编辑语义，不因来源 Warp 隐式覆盖用户后续编辑。

Signalsmith 渲染采用有界缓冲区、固定随机种子、零移调，使用 `seek(inputLatency)`、提前读取输入、丢弃 `outputLatency` 前导输出、`flush(outputLatency)` 尾部补偿。输出总帧数严格为 `round(inputFrames / r)`。输入/输出有限数值、文件长度、通道、采样率和哈希在发布前校验；临时文件原子发布后才返回可提交资产。缓存命中必须通过输出 SHA 校验；缓存坏了会重渲染，不能把原文件假装成成功拉伸结果。输出限于标准 WAV 的 4 GiB 边界，超出明确失败。

## 命令契约

读取：`get_audio_warp`，参数 `clip_ids` 数组（也接受单个 `clip_id`）；省略时读取全部音频片段。返回 `items` 和 `fixed_ratio_only: true`。每项：

```text
clip_id, enabled, source_bpm, target_bpm, follow_tempo, mode,
warp_speed_ratio, source_offset_seconds, playback_source_offset_seconds,
timeline_start_seconds, duration_seconds,
source_duration_seconds, playback_duration_seconds
```

未启用的默认值为 BPM 120/120、比例 1、follow=false、mode=preserve_pitch。读取不暴露文件系统路径。

写入：`set_audio_warp`。`operation` 默认为 `warp`；要求 1–64 个不同的音频 `clip_ids` 和布尔 `enabled`。启用时 `source_bpm` 是**永久原文件的 BPM**，必填且 20–300；`target_bpm` 默认工程 BPM，范围相同；`follow_tempo` 默认 true；仅支持 `mode: preserve_pitch`。跟随时目标 BPM 必须等于本事务的工程 BPM。

可选 `project_bpm`、`numerator`、`denominator` 与 Warp 同一个事务提交。可选成对的 `first_beat_seconds` / `align_start_seconds` 分别表示**操作前听到的 clip 相对首拍秒数**和目标工程绝对秒数。新的开始位置为 `alignStart - firstBeat * oldRatio / newRatio`，不允许移动到零之前。`operation: align_only` 冻结选中片段当前速度/关闭其跟随，调整工程速度时其他已跟随片段仍正确重渲染，再按指定首拍定位。

返回 `status: accepted` 和 `result.job_id`。使用现有 `get_job` 等待完成，成功结果 `result` 包含 `job_id / project_id / revision`，并保留调用方 receipt。一次请求对应一次 Undo 和一次 revision。普通 `set_tempo` 或原生 batch 若改变了跟随音频的比例，也进入相同后台管线；原 batch 的 `executed_commands / refs` 保存在最终任务回执。`set_audio_warp` 本身不嵌套在 batch 内；其多片段/工程参数已经覆盖同一事务需求。

内部 `beginAudioWarp(args, out, validateFiles, provenance, onApplied)` 供 `apply_beat_analysis` 复用：可信来源哈希校验在 worker 提交前执行两次，provenance 随候选工程一起保存，成功控制线程提交后才执行回调。首拍分析的听到 BPM 要先除以当前比例，转换为永久原文件 BPM，避免重复拉伸。

## 事务、保存与保护

- 活工程在后台准备期间继续使用原 graph、原 BPM；所有来源、渲染和候选工程验证成功后才在控制线程一次提交。
- 取消、来源变化、渲染失败、revision/project 过期或录音冲突均不提交候选。此前已经启用 Warp 的原文件 SHA 必须保持一致，修改别的 clip 或关闭 Warp 都不能悄悄吸收外部替换的原文件。
- schema 6 存储 Warp 元数据、原资产/渲染资产 ID、二者 SHA 和 beats 来源记录。普通工程仍使用所需最小 schema；旧 schema 1–5 的读取兼容保持，旧程序对更高 schema 明确拒绝。
- Save 将原文件和渲染 PCM 都纳入工程资产并验证绑定哈希；重开验证并直接使用已保存的渲染，不要求重新推理/拉伸。Undo/Redo 恢复对应资产映射。
- 依旧沿用既有命令 → DTO 候选 → 单一 Edit 的边界，没有第二份可写音乐模型。`AudioTimeMap.h` 明确原文件/工程/播放映射；公开 ClipSnapshot 增补不可变映射字段。

## 自动验证入口及人工边界

新增 `EngineSession::runAudioWarpSmokeTest()`，由现有 clip smoke 调用，不增加独立 CMake target。只使用测试自己生成的媒体和工程。检查包括：

1. 44.1 kHz 双声道 440/660 Hz 音频，0.8、1.25、2.0 比例的精确长度、能量、有限数、音高及缓存重复读取。
2. 开头/中间/结尾的确定性宽带瞬态，0.8、1.0、1.25、2.0 比例，共 12 项能量重心时序检查，误差目标低于 20 ms；用于检出 `seek` / `outputLatency` / `flush` 残留位移，并不等于样本级瞬态保真承诺。
3. 原来源偏移、首拍定位、裁剪、切分、跟随 BPM、准备期间保持旧状态、一次 Undo/Redo、schema 6 保存重开。
4. 提交前取消、revision 冲突、外部改写原文件拒绝及原文件字节不被拉伸覆盖。
5. 真实 `export_wav` 隔离子进程导出裁剪后的 Warp WAV，以及已有自制 CBR 48 kHz 双声道 / VBR 44.1 kHz 单声道 MP3；与真实 Warp PCM 对应源窗口比较，允许已有混音增益但相对残差 RMS 必须低于 0.002，检查导出帧数和工程不被修改。两种 MP3 都验证 Warp 保存重开和原字节不变。

报告为测试输出目录的 `warp-report.json`。**写下这些断言不是测试通过的证据**；中央 runner 的实际日志为准。ASIO 硬件、长音乐/极端拉伸听感、CPU 与长期并发负载需要单独人工与性能验证。本批仅固定比例，未实现局部 Warp 点、完整 Tempo Map、任意拍号识别或自动改写独立 MIDI 派生轨；不得在 UI/文档声称已完成这些能力。


## 最终执行结果

最终Release构建17681fb951及CTest a0dca19eac通过，warp-report.json记录188项检查。0.8/1.25/2倍下测得440.008–440.020Hz与660.012–660.030Hz；12个合成瞬态能量重心最大误差约0.430ms。三种实际导出对应PCM的相对RMS残差分别约1.37e-6、1.77e-6、2.89e-6。全部为i7-13700H/Windows11/MSVC Release的离线44.1/48kHz夹具，无实际ASIO缓冲；并非歌曲听感或长期实时性能结论。冻结源码、EXE、报告和范围见RESULTS/VERIFICATION。
