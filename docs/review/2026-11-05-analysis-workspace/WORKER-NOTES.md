# 分析 Worker 升级记录

2026-11-05。状态：本页列出的 Worker 代码、数值/协议检查及真实进程推理已验证；原生 GUI、Agent、工程导入和真实声卡共存由本轮主任务另行验收。识别准确率和人工听感未由这些测试证明。

## 本轮交付范围

- 分离保持现有 HTDemucs 四轨默认，新增独立的官方 HTDemucs-6s 权重，可输出 vocals / drums / bass / piano / guitar / other。`fast` 使用 25% 分段重叠、无移位平均；`quality` 使用 50% 重叠和两次随机移位平均，固定随机种子 0。两者仍限制每段 3–4 秒、两条 CPU 线程，以照顾本机 4 GB GPU。quality 是更高计算量的推理配置，不代表已证明所有歌曲都更好。
- 每条分轨结果包含 128 个真实波形峰值 `waveform_peaks`。按等时区间取所有声道的绝对最大值，在后台 Worker 计算；不改音频、不做独立分轨归一化。GUI 可直接绘制，不必为下栏概览再读盘解码。分块 abs/max 也避免为完整长分轨额外分配一份绝对值数组。
- Basic Pitch 增加 `auto / piano / bass / guitar / vocals` 音域配置，仍使用同一份真实 ONNX 模型，不能描述成五个专用训练模型。Auto 仅复用已知来源角色，不假装新增乐器识别器。显式 min/max 参数优先于配置默认。
- 自有 Chroma/Viterbi 基线升级为 2.0，可选择原 24 三和弦 + N，或 132 和弦 + N：maj、min、7、maj7、min7、dim、aug、sus2、sus4、hdim7、dim7。仍是确定性模板算法；没有装入训练式爵士模型，没有自动推断转位或 9/11/13 扩展。对同音集合的多重合理解释保留 uncertain 元数据，界面无需显示内部评分。
- Viterbi 的均匀跨状态转移改为精确的线性状态更新；扩展词表使用 int16 回溯，避免 133 状态溢出原 int8。增加明确的静音扩展词表回归。

## 协议

请求 schema_version 仍为 1，原 kind / preset / 候选结果语义不变；新增参数如下，均经 Worker 严格校验：

| kind | 参数 | 默认 |
|---|---|---|
| separate | `stems: 4 或 6`；`quality: fast 或 quality`；原 `segment_seconds: 3..4` | 4 / fast / 4 |
| transcribe | `instrument: auto/piano/bass/guitar/vocals`；原阈值、最短音和音域参数 | auto |
| chords | `vocabulary: extended 或 triads`；原 sensitivity / min_region_seconds | extended |

音域分别为 auto/piano 21–108、bass 23–72、guitar 28–96、vocals 36–96；用户显式音域覆盖配置。混合 other 分轨在 Auto 下拒绝转录；用户显式选择 piano/bass/guitar/vocals 后允许尽力提取音符，仍不声称能区分多乐器。drums 在任何音高配置下均拒绝。旧的 `htdemucs` preset 保持有效，也兼容 `htdemucs_6s` 别名（与 stems=4 冲突时拒绝）。六轨注册在 `registry.providers.separate_6s`，执行时按 stems 选择，未下载的机器明确返回 unavailable，不自动联网下载。

原有不可变结果、取消、来源 SHA、秒级时域、未量化 MIDI、上限和录音线程隔离不变。新结果 `model.worker_version=1.1.0`，和弦结果写真实执行的算法版本 2.0.0，避免沿用旧安装注册表中的 v1 元信息。

## 模型来源与保留

官方模型：[adefossez/HTDemucs-6s](https://huggingface.co/adefossez/HTDemucs-6s/tree/3c5ee475be622df764938de97e4281a7b07ffa58)。Demucs 4.1.0 的 [官方 README](https://github.com/adefossez/demucs) 明确将六轨模型称为实验性，并提示 piano 存在较多串音和伪影；此限制没有被本轮隐藏或当作解决。

- revision：`3c5ee475be622df764938de97e4281a7b07ffa58`
- checkpoint：`5c90dfd2.safetensors`，54,885,744 字节
- SHA-256：`d2a1745f0744721f6b8ca5bf469b67c651ea5ed1b52998cab033b2158609d411`，下载后对照官方 LFS 元信息
- 本机：`E:/MusicAgent&DAW/analysis/models/demucs/htdemucs_6s/<revision>/`
- 运行库复用已有 `separation-cuda-py310` / PyTorch 2.5.1+cu124 / Demucs 4.1.0；未更改全局 Python 或驱动
- 代码 MIT；checkpoint 再分发许可未确认，仅按本机评测部署，不随源码或产品归档发布

安装命令：

```powershell
python scripts/setup_analysis.py --root "E:/MusicAgent&DAW/analysis" --kind separate --register-only --device cuda --stems 6
```

安装器保留 registry 历史副本，写在 `analysis/manifests/registry-history/`。本次比较确认既有 separate / transcribe / chords 三个 entry 内容均未改变，仅新增 separate_6s。新代码在未来重注册和弦时会登记 v2，本轮没有改写旧和弦注册条目。

## 实际验证

| 检查 | 结果 / 记录 |
|---|---|
| 官方权重下载、SHA、真实 CUDA forward 六输出 | 通过；`20261105T100905.925688Z-5203fda088` |
| 初次新增 Worker 契约与算法检查 | 25 项通过；`20261105T101131.786651Z-2856286e19` |
| 波形、扩展 N、七和弦合成音时间边界等最终 Worker 检查 | 27 项通过；`20261105T101407.916317Z-e7da5a2020` |
| 初次六轨 quality / piano 配置 MIDI / 扩展和弦 | 三种真实 Worker 通过；`20261105T101148.569838Z-e3488965bb`，波形元信息之前的中间版本 |
| 最终六轨 quality / 128 点波形 / MIDI / 和弦 | 通过；`20261105T101428.477240Z-192f26fc2d`，本机报告 `analysis/manifests/probe-aefe4d14fedf.json` |
| 真实进程静音、极短、超限、坏文件、NaN、哈希变化、取消、鼓误用等 | 12 项通过；`20261105T101512.680669Z-69457db2d0`，`analysis/manifests/edge-probe-3c3e0e34f435.json` |
| CC-BY 真实音乐：trumpet 转录、Vibe Ace 六轨 fast / 和弦 | 三项通过；`20261105T101623.107525Z-0be22cc31b`，`analysis/manifests/public-probe-bdc835a8f69c.json` |
| 收尾准入修正：other 只在显式音高配置下允许；完整 Worker 回归 | 28 项通过；`20261105T101955.562727Z-5ec8f41b86` |

三个 Worker 结果均记录执行源码合并 SHA `46980dfecf42350672e55d6b52e0ee5b379705d9277b65c62aa2fd13364cc3b8`。随后仅放开 other 的显式音高配置准入，推理、波形、解码实现未改，因此按主任务约定只重跑 28 项回归，没有重复消耗 GPU。该指纹只对应当时五个实际执行模块；原生界面文件仍在并行开发，不能把这些记录当作整个仓库已经冻结或原生构建通过。

准入修正后的五模块合并 SHA 为 `db5e0b93cf4b1d9c3ebfb5389227e1be0776f71e1a02eedef695e6f11fcf2d97`；原生最终联测应使用这个版本或明确记录后续变化。

完整命令、开始/结束时间、退出状态、原始日志路径由 Recorder 写入 `docs/builds/`、`build-logs/` 和 append-only DEVLOG。第一次六轨安装记录的 config 沿用了旧安装脚本的静态 `Python3.10 CPU` 标签；真实命令为 `--device cuda`，forward 和 GPU 计量也确为 CUDA。已修正脚本以后按实参记录 config；原记录保留，此处追加更正。

## 测量条件与限制

同一 Windows 本机 i7-13700H、约 32 GB RAM、RTX 3050 Laptop 4 GB、驱动 555.99，CPython 3.10.19；两条 CPU 线程。这里是离线 Python 进程，**没有声卡、没有 ASIO 缓冲区、没有 DAW 实时播放负载**，并行存在开发工作，系统缓存已热。

7 秒、44.1 kHz、双声道合成 C 大调→A 小调输入，最终六轨 quality 整进程墙钟 28.58 秒；Worker 内 26.47 秒，其中 separating 10.12 秒。采样峰值 RSS 1,284,149,248 字节，CUDA allocated 650,146,304 字节 / reserved 912,261,120 字节，无 CPU 回退。piano 配置 MIDI 整进程 7.26 秒、6 个候选音符；扩展和弦 4.41 秒、2 个区域。CPU/GPU 采样方法沿用前版，RSS 每 100 ms，CUDA 使用 PyTorch 分配器统计。

公开音乐最多 8 秒，Mihai Sorohan trumpet 转录 8.21 秒，Kevin MacLeod Vibe Ace 六轨 fast 26.60 秒、和弦 3.90 秒。音频与署名/许可证继续只保存在本机 `analysis/cache/public-fixtures/`，来源和 SHA 见报告；没有上传音频。它们只证明真实模型路径可运行，没有标注真值，不报告 SDR、音符 F1 或和弦准确率。

仍待后续：真实音乐盲测与人工改错量、物理 ASIO 共存、长曲峰值负载、强制 GPU OOM 回退、爵士训练式识别、真正的分乐器专用转录器、主人声/和声与吉他角色细分。本轮没有从头训练或付费 API 调用。

## 集成复查与 Agent 契约补齐

随后按主任务分配只读检查原生分析、存储、下栏和 Agent，发现六轨候选仍被 Agent 的旧四轨限制拒绝；显式乐器配置也在结果导入/取消重新授权时丢失。主任务转交 `scripts/music_agent/analysis.py` 与对应测试后已修复：

- 四／六轨按真实候选数量计算新增轨数和 64 轨预算，核对完整声部名称、不允许五轨、重名或缺页候选；预览文案使用实际轨数。
- 结果和任务传递经过校验的参数，显式 other 乐器配置贯穿开始、读结果、提出导入和取消；鼓仍拒绝。
- 扩展和弦编辑接受与 Worker/存储相同的标签，原“不支持 C:maj7”测试改为未提供的 C:maj9。
- 乐器配置收到 list/dict/其他错误类型时返回 ValueError，不产生 TypeError；能力列表过滤非列表、嵌套值和未知项。
- 波形峰值只留给原生绘图，不进入模型上下文。

定向 Agent 分析回归 **28 项通过**，记录 `20261105T102541.549783Z-35bfc90c09`；它与上面的 28 项 Worker 测试是两套独立检查。本次没有新增推理或 API 调用。原生 job 参数回传、preset 冲突检查、规范化参数留档和下栏任务列表问题已发给主任务，其最终修复与原生端到端证据以主任务结果为准。

补齐显式乐器和 Auto 已知来源的默认音域交叉校验后，最终定向 Agent 28 项再次通过，记录 `20261105T102808.266541Z-2d62aaf86a`。例如 bass 仅指定 min_pitch=80 时，不再以通用 max_pitch=108 错放行，而按 bass 默认最高 72 在调用模型前拒绝。两次测试之间的差异与原记录均保留。

## 最后回读审查修复

最终只读追踪 Agent 工具→授权→预览→原生导入→回读时，另外发现 `runtime.py::_verify_analysis_import` 仍硬编码分离产生四轨。六轨实际上已提交后，会被 Agent 错报数量不匹配；前面的计划编译测试不能证明这个后置阶段通过。收到主任务转交后，改为使用用户确认过、已经验证的候选轨数，并再次核对候选种类、数量和结果哈希。新增轨道的 `analysis_role` 集合也必须与候选声部集合一致，避免 piano/guitar 等来源标识丢失而影响后续转录配置。

新增四轨／六轨预览→确认→回读成功→一次 Undo 的状态机回归，以及候选总数被改、片段回执缺失、声部标识重复的失败检查。`tests/MusicAgentAnalysisIntegration.py --six-stems` 保留原和弦闭环，并追加真实 HTDemucs 六轨由 Agent 发起→本地等待→确认预览→导入回读→一次 Undo/Redo→保存重开；核对六种角色及轨道/片段 ID，随后只验证 piano/guitar Auto 与 other 显式 piano 的授权，不额外运行转录模型。语言模型仍是明确标识的确定性测试替身，不能将其当作真实模型意图理解验收。

本分工记录化检查：

- Agent 分析 **30 项通过**：`20261105T105322.093521Z-058c4d2a18`。
- 通用 Agent runtime **37 项通过**：`20261105T105337.678180Z-e169508d50`。
- 扩展集成脚本 `--help` 导入/参数检查通过：`20261105T105427.750042Z-ba05eb3eab`；这一步没有启动原生 DAW 或模型，不能当作端到端通过。

本组运行使用 CPython 3.14.0；执行时主任务仍在做原生集成，因此不是全仓库冻结验收。实际 `--six-stems` 集成和全量最终回归交给主任务统一记录执行；此处实现与测试源码已冻结，未修改原生、模型权重或运行库。
