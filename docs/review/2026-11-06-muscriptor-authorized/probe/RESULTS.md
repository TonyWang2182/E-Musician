# MuScriptor 部署探针记录

状态：代码、纯 CPU 守护测试、真实授权权重 CPU 加载及一次8秒 GPU 部署探针均通过。没有整曲或识别质量验收。

精确API已从固定源码核对：`TranscriptionModel.load_model(weights_path=本地Path, device='cpu'或'cuda', dtype='float32')`。权重与邻接官方 `config.json` 必须同时存在，避免默认 large 架构。事件经原生 `events_to_midi_bytes` 导出，不启动 BeatThis 或其他隐式下载。8秒fixture、原生2个5秒chunk、默认力度与占位120BPM限制见 [PLAN](PLAN.md)。

8项纯CPU生命周期测试通过：CPU隐藏CUDA且不查询GPU、准入拒绝不启动子进程、初始/末态诊断失败、无效结果JSON、清理异常、SIGTERM异常路径、owned-child退出竞争。测试是明确模拟进程，不证明模型已加载。记录 `20261106T132522.456237Z-66cc327634`。

最终执行脚本冻结 SHA256 `00dc3c7064715059fef1c02a2a01f1a7d892aec8ccbb81109a51f53ef3c4d007`；测试脚本 `617d5794aac865662c0bf805560e558d04dce443867427494f626136dcf9651d`。最终不可变目录 `workspace/models/muscriptor/probes/authorized-4e17cf2f94b6/`；完整清单见 [SOURCE-LOCK](SOURCE-LOCK.json)。原准备版本 `2ca1ca...` 未执行真实模型；独立审查后新增非空音符事件/MIDI断言，避免有声fixture输出空MIDI仍报告成功。最终版本8项CPU守护复测通过，记录 `20261106T133120.478693Z-ddfd0a8f63`。

准备过程更正：最初上传glob纳入同目录其他代理的3份认证/下载源码文件（只复制同台云端，不执行，不读取凭据文件）；已改为显式 `probe.py/tests.py` 白名单，新目录仅此两文件。旧owned staging内误复制的3份源码已按精确路径移除，原件与任何凭据位置均未改。修正记录 `20261106T132554.984513Z-abf7ba8053` 至 `20261106T132604.398270Z-cc45b58de8`，范围更正阶段两份探针文件SHA不变；随后审查补强非空音符检查并重新执行最终8项测试，见上方最终记录。

## 真实 CPU 加载

在 root 确认权重及官方配置通过后执行。模型306,503,680个参数，均在CPU且有限，CUDA未初始化。显式本地Path、离线环境，没有模型下载。加载1.353秒，加载与全部参数有限值检查共1.709秒；守护外层5.002秒，含SSH的Recorder命令7秒级。该步骤没有执行转录。

官方 `config.json` 为126字节，SHA256 `43e13a70fc9ae0af36b7447c06f3eac2282daeb69d79c1ff840ede7fdaa26a3b`，与root权重接收校验对应。模型权重SHA/大小同计划。

- 原始结果目录：`/root/autodl-tmp/emusician/results/muscriptor-authorized/cpu-20261106T134345Z-a573f284/`。
- 命令记录：`20261106T134344.284285Z-34337b82ce`；[CPU守护收据](evidence/cpu-guard.json)。

## 一次8秒 GPU 探针

原始Keyboard SHA已核对，仅明确截取前8秒作为新fixture；不是279秒完整歌曲评测。采用原生所有乐器、greedy/CFG1/batch1/prelude forcing/beam1，`no_eos_is_ok=False`；两块都完成，未因token上限静默结束。输出125个流事件，其中61对音符开始/结束，MIDI有61个note-on，时长8.0秒。模型自行输出 `acoustic_piano`，没有硬约束钢琴；补零末尾8–10秒没有新增note-start/end。

音符和MIDI数值有限且边界有效；MIDI力度全部100，来自上游默认值，不是真实演奏力度。没有启动节拍模型，MIDI120BPM为占位，不能视作BPM识别。没有渲染音频、PDF五线谱或人工音乐质量评价。

NVIDIA RTX5090，Python3.11独立环境，MuScriptor0.4.0 / Torch2.10.0+cu128 / CUDA12.8 / NumPy2.5.4 / soundfile0.14.0 / mido1.3.3 / safetensors0.8.0；float32权重与上游CUDA autocast。加载0.455秒，推理/事件序列化/MIDI检查1.297秒，工作进程主体共1.799秒，守护外层4.691秒。峰值allocated2,456,909,824字节、reserved2,474,639,360字节；ACE保持驻留，最低空闲11,808MiB，退出恢复14,774MiB，前后ACE无活动任务。这是单机器单短样本数据，不外推任意歌曲性能。

- 原始结果目录：`/root/autodl-tmp/emusician/results/muscriptor-authorized/gpu-20261106T134439Z-c8402e6a/`。
- `fixture-first-8-seconds.wav`、`events.json`、`transcription.mid`、`result.json`、`guard.json` 均留云端。
- MIDI SHA256：`5b24c411a90652d2e62d088a320e86e077ff2a4f91a7714dd5584f00d0251099`；465字节。
- 命令记录：`20261106T134438.033519Z-6910b6dbaa`；[GPU守护收据](evidence/gpu-guard.json)。
- CPU/GPU小证据复制记录：`20261106T134528.380788Z-e1a33144aa`、`20261106T134530.252161Z-b8d25d1814`。

GPU已释放，无重跑。没有读取令牌/私有认证文件，没有安装新依赖、变更ACE或接DAW。模型/音频/原始MIDI没有下载到E盘；root负责中央catalog和最终部署状态汇总。
