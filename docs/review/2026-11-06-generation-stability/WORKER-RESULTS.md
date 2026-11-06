# Python MIR资源安全修复

2026-11-06。状态：**Worker实现及轻量回归已验证；原生整合、真实分离与人工使用待主任务验收**。没有在低内存本机重新加载真实模型，没有改云服务、运行库/注册配置、分页文件或用户工程。

## 故障证据与原因

本机 `nvidia-smi` 确认为 NVIDIA GeForce RTX3050 4GB Laptop GPU。原任务 `e63a101362cd4aebb74791e4eb7b61e2` 是22.4秒四轨fast，出现普通 `RuntimeError: CUDA error: out of memory`；原代码仅捕获特定CUDA OOM类型，未覆盖此形式。`525db3543ff64d8fbadf76dabbd3bdf6` 是同长度四轨quality，CUDA分配失败后又在 `providers.py` 的 `model.cpu()` 触发CPUAllocator无法申请1MiB。错误栈中的failed inference frames仍可能持有模型与中间张量，立即迁移/重跑会扩大压力。75秒六轨quality任务 `b9d2c558386c46edb03297abf9df4908` 只有进度文件、没有error/result；这不足以从Python侧单独确定原生退出原因，需要主任务的进程退出与系统提交量记录。

可用物理内存不等于可继续申请的系统提交量。Windows `GetPerformanceInfo` 的 `(CommitLimit-CommitTotal)*PageSize` 才是本次准入检查使用的commit余量，同时另查PhysicalAvailable。代码按官方结构把pages转换成bytes，没有把GPU空闲数或物理空闲数当作WDDM/系统提交能力。[Microsoft性能结构](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information)、[GetPerformanceInfo](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getperformanceinfo) 支持此区分。

已核对本机安装Demucs4.1.0的 `apply.py`、`htdemucs.py`、`hf.py`、`states.py`，并参考[固定v4.1.0 apply实现](https://github.com/adefossez/demucs/blob/v4.1.0/demucs/apply.py)和[官方说明](https://github.com/adefossez/demucs/blob/v4.1.0/README.md)。split会保留整段CPU输出，quality的shift平均会同时保留两个整段输出；HTDemucs.forward还可能按model.segment补齐前向长度，所以只缩小外层分段参数不能直接当作已降低显存的证据。本轮没有改变模型、权重、精度或推理参数；新增报告effective_forward_segment_seconds说明这一实际行为。

## 实现

- 新增stdlib优先的 `scripts/audio_analysis/resources.py`。在NumPy/SoundFile/Torch导入和音频解码之前先检查可用commit/physical，输出 `resource-budget.json`。失败也保留预算与实测快照。
- 与原生端统一 `request.resource_policy` v1字段：minimum_available_commit_bytes、minimum_available_physical_bytes、critical_available_commit_bytes、critical_grace_ms。分离4GiB、转录/节拍2GiB、和弦1GiB是最低准入headroom规则；physical至少512MiB，运行检查点commit低于512MiB即退出。请求不能降低这些默认值。
- Python在最低规则之上加明确的已知缓冲预算：float32源音频、44100Hz立体声处理缓冲、shift padding、整段stem输出与quality第二输出、checkpoint加载副本。它不是模型峰值预测或性能保证；未知Torch工作区、其他程序并发申请和WDDM情况仍由原生运行期监控和进程隔离兜底。既有7秒六轨quality实测RSS约1.28GB，仅是本机短样本证据，不能推出长曲/同时开DAW时总需求。
- GPU准入使用注册时真实probe的reserved峰值加256MiB政策余量；记录基础和实际free/total，不声明一般峰值保证。低余量明确拒绝；模型推理发生OOM后不再自动切CPU。分离和节拍的同类CPU重跑路径都已删除。
- 捕获Python MemoryError、Torch风格OOM和普通RuntimeError中CUDA/CPUAllocator的内存错误；给出可恢复错误码与简短操作建议。错误处理不迁移模型，释放异常帧，再写error/progress。预留256KiB仅用于失败回执，不是给模型增加内存。
- `prepare()`改成单个预分配PCM数组加65536帧读取块，去掉blocks列表+concatenate的双份整段PCM。分离输出在inference_mode中原地恢复幅度，避免两个完整stems副本；有限值检查也以小块完成。模型数值/质量参数保持。
- `run.py`启动早期只设置当前分析进程的SetErrorMode，防止子进程故障对话阻碍宿主回收；每任务新增 `fault.log`，由faulthandler写异常线程堆栈。Python启动前故障和进程树生命周期由原生launcher负责。没有更改Windows全局错误设置，也没有读取/上传dump。[Microsoft SetErrorMode](https://learn.microsoft.com/en-us/windows/win32/api/errhandlingapi/nf-errhandlingapi-seterrormode)
- Worker版本1.2.1，来源指纹增加resources.py，避免只改变安全策略却沿用旧实现身份。

错误码：`insufficient_memory`、`insufficient_gpu_memory`、`memory_pressure`、`out_of_memory`，以及无法读取系统状态时的`resource_probe_failed`。不发布伪结果，不修改工程。

## 验证与记录

全部通过Recorder保存命令、配置、起止、退出码和原始输出，并由Recorder追加DEVLOG。不同代理仍在改原生/Agent代码，整个仓库的构建状态以主任务为准。

| 记录 | 环境与结果 |
|---|---|
| [093132…06efd395e2](../../builds/20261106T093132.806164Z-06efd395e2.json) | 初轮chords隔离环境43/43通过，随后增加inference tensor上下文专项检查。 |
| [093353…5a32c2a011](../../builds/20261106T093353.979426Z-5a32c2a011.json) | 最终完整Worker回归44项：43通过，1项Torch专用测试因chords环境无Torch跳过。 |
| [093400…5c13eeb232](../../builds/20261106T093400.425484Z-5c13eeb232.json) | CPU分离环境资源专项10/10通过，包括上述Torch专项；没有CUDA推理或真实权重加载。 |

专项包括：physical仍有6GiB但commit只剩2.8GiB时拒绝；预算随时长/轨数/shift增长；请求不可减弱policy；运行压力中止；Typed/普通CUDA OOM与CPUAllocator仅执行一次且不回退；真实Worker子进程在无法满足的准入要求下退出2并写入error/progress/resource-budget/fault，且没有解码输入或加载模型；16帧假模型使用真实CPU Torch inference tensor，验证原地恢复幅度、四份WAV、实际前向长度报告与旧公式一致。该假模型明确只测宿主管线，不是分离效果验证。

最后轻量系统快照：commit可用5,040,910,336字节、physical可用7,290,470,400字节。此瞬时值不是原崩溃时的数值，不用于宣称压力已经解除。对应代码指纹与快照在忽略目录 `build-logs/mir-resource-worker-fingerprint.json`；`git diff --check`通过。

## 后续验收边界

尚未重演原机器的真实OOM，也没有跑长曲、ASIO共存或真实6stem分离。修复首先保证低资源时可拒绝/失败并保护宿主，不能把4GB GPU变成无限容量。原生进程退出/无响应监控、取消回收、错误UI与Agent对应提示由本轮其他任务实现并验证；完成整合后再由用户在足够余量下做短样本人工测试。
