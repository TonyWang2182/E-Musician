# 音源分离、分轨转 MIDI、和弦识别：第一版方案

2026-11-05 · 状态：**提案，未安装模型、未实现分析功能、未运行推理**。本轮仅核对工程、查询官方来源、归档 0.8.1 和编写计划；不改当前程序、页面或启动入口。

## 1. 当前版本与硬件

0.8.1 保存在 `E:/MusicAgent&DAW/releases/0.8.1-20261105/`：EXE、PDB、source-and-docs.zip、MANIFEST.json。归档内 161 个源码文件逐个核对 SHA-256，源码总指纹 `846b6b2c43d7e35dc046f39f1f879b3af692066c0f9bfcd8b529018c23008a7f`；EXE `c0099db16a428b04e8bda55fef6444658711c8cafa9b784a7b5a127979ab9082`。归档是保留/恢复材料，不是独立安装包；不包含用户工程、音频、凭证、WebView 浏览数据、依赖源码或模型。恢复 Agent 须配套恢复源码里的 scripts，不能只换旧 EXE 却使用新助手代码。

当前候选仍从 `build/device-chain` 和 `Start E-musician 0.8.1.cmd` 打开。后续采用独立分析功能分支/构建目录 `build/audio-analysis`；由于工作树有未提交实现，基线须来自已审查的实际快照，不能仅从旧 Git HEAD 创建分支而丢失这些代码。

本机只读检测：i7-13700H，系统报告内存 31,923,757,056 字节；RTX 3050 Laptop，nvidia-smi 报 4096 MiB、驱动 555.99。C 盘约 12 GB 空余，E 盘约 698 GB 空余。显卡枚举不等于 CUDA/PyTorch 已可用；本轮没有安装或验证推理环境。

## 2. 模型与算法选择

| 能力 | 首选方案 | 来源、版本与部署 | 输出与边界 |
|---|---|---|---|
| 音源分离 | **HTDemucs / htdemucs，先本机评测** | 作者维护仓库 [adefossez/demucs](https://github.com/adefossez/demucs)，候选 4.1.0；[官方权重](https://huggingface.co/adefossez/HTDemucs)。独立 Python 3.10/PyTorch 环境，优先试 CUDA，保留 CPU 路径 | vocals、drums、bass、other 四轨 WAV。other 仍是多乐器混合；不宣称任意乐器各一轨。4GB 下先试 3–4 秒分块和单任务，属待测配置 |
| 有音高分轨 → MIDI | **Spotify Basic Pitch 0.4.0，官方 ONNX 模型** | [项目](https://github.com/spotify/basic-pitch)、[模型打包清单](https://github.com/spotify/basic-pitch/blob/main/MANIFEST.in)、[依赖条件](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml)。独立 Python 3.10 + ONNX Runtime CPU | 优先 bass、主唱旋律和单乐器音频；支持复音但混合乐器/失真/串音需修正。输出可编辑音符；不是歌词识别器或鼓类别识别器 |
| 和弦识别 | **Chroma + 和弦模板 + HMM/Viterbi，自有实现** | [AudioLabs 模板方法](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C5/C5S2_ChordRec_Templates.html)、[HMM 方法](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C5/C5S3_ChordRec_HMM.html)；特征可用 [librosa](https://github.com/librosa/librosa)。CPU，无预训练权重 | 首期 12 大三和弦 + 12 小三和弦 + 无和弦，并单独标“不确定”。输出起止时间与标签，可改标签/边界；七和弦和更大词表后续评测，不声称任意转位/复杂和声都正确 |
| 鼓分轨 → MIDI | **单独的鼓转录 Provider；YourMT3+ 为后续评测候选** | [作者入口](https://github.com/mimbres/YourMT3)、[官方演示实现与权重](https://huggingface.co/spaces/mimbres/YourMT3/tree/main) | 需要验证鼓类别、GM 映射、Windows、显存与许可后才能标可用。第一步可提供 onset 节奏候选和人工分配鼓类，明确是基础算法，不能冒充完整鼓组转录 |

Basic Pitch 在 Windows/Python <3.11 默认选择 ONNX Runtime；较新 Python 的默认依赖路径引入 TensorFlow，因此不直接塞进现有 Agent Python。其仓库标 Apache-2.0，模型随项目打包；实际锁定资产时保存该 revision 的 LICENSE/NOTICE，不能将镜像文件当作已核验来源。

**权重许可是本轮选型的明确未决项。** Demucs 作者当前 [License 说明](https://github.com/adefossez/demucs#license) 区分 MIT 代码和许可不清晰的预训练权重；本提案把它作为本机评测候选，不写成已获商用/随产品分发许可。实施安装前记录权重具体来源与使用范围；若不能满足交付用途，替换权重或 Provider，管线不重写。此处不是对全部模型的法律结论。

备选：`htdemucs_ft` 是更慢的四模型集合，先不默认；BS-RoFormer 需指定具体 checkpoint、任务和权重作者，不能只写架构名称。和弦可后续比较 [ChordMini](https://github.com/ptnghia-j/ChordMini) 的 BTC-CL/2E1D：较新的 170 类实现，但 checkpoint 单独授权尚未确认。旧 [BTC](https://github.com/jayg996/BTC-ISMIR19) 有短片段与时间映射适配问题；[madmom](https://github.com/CPJKU/madmom#license) 代码 BSD、模型 CC BY-NC-SA 4.0，均不列首版发布默认。YourMT3 的 GitHub/HF 发布许可表述也需按选定工件核对。

## 3. 部署位置

建议全部放在 E 盘，目录尚未创建/部署：

```text
E:/MusicAgent&DAW/analysis/
  runtimes/
    separation-py310/       # Demucs / PyTorch 专用
    transcription-py310/    # Basic Pitch / ONNX CPU
    chords-py310/           # Chroma/HMM；兼容后才考虑合并环境
  models/
    demucs/htdemucs/<revision>/
    basic-pitch/0.4.0/<revision>/
    chords/<provider>/<revision>/  # 仅将来神经模型需要
  cache/
    downloads/             # HF/Torch/pip 下载缓存
    jobs/<job-id>/          # 冻结输入、候选结果及中间文件
  manifests/               # 来源、许可、源码/权重 hash、实际运行库版本
  logs/                    # 耗时、资源、错误；不记 API 密钥
```

模型和虚拟环境不进 Git，也不写进 EXE。`HF_HOME`、`TORCH_HOME`、`PIP_CACHE_DIR`、临时目录仅设置在分析子进程，不改用户全局环境。模型安装由显式安装步骤执行，播放/音频回调不会触发下载；离线时仍能使用已经就绪的模型。预留运行库、权重、临时音频空间，实际体积在安装清单记录，本轮不虚报下载量或速度。

确认导入的结果进入工程自身 `.assets` 并随项目保存；未接受候选留任务缓存，可手动清理。被工程、Undo/Redo 引用的文件不能随缓存清理删除。分析缓存不是自动保存、工程恢复或自动继续任务。

## 4. 手动与 Agent 共用的管线

```mermaid
flowchart LR
  UI[手动分析面板] --> API[DAW 统一分析命令]
  Agent[Agent 方案与工具] --> API
  API --> Freeze[冻结来源与选区 / 分配任务]
  Freeze --> Worker[独立本机分析进程 / 任务队列]
  Worker --> Models[分离 / 音高转录 / 鼓 / 和弦 Provider]
  Models --> Candidate[本地不可变结果 / 校验与预览]
  Candidate --> Review[试听、钢琴卷帘修正、和弦标签修正]
  Review --> Accept[用户接受 / 带版本提交]
  Accept --> Project[唯一工程状态 / 保存 / 一次 Undo]
```

独立 Analysis Worker 由 DAW 的分析管理层按需启动，和聊天 Provider 进程、实时引擎分离。**手动功能不依赖 Agent 或 API 密钥**。Agent 使用相同命令与任务 ID；模型只安排任务并读结构化结果摘要，不把音频塞进 GPT/Kimi 的文本上下文。

建议新命令（目前均未实现）：

| 命令 | 责任 |
|---|---|
| `get_analysis_capabilities` | 可用算法、已安装模型、就绪/缺依赖/错误、支持音频类型、鼓/音高限制 |
| `start_analysis` | kind=separate/transcribe/chords；指定已授权 clip/asset/range 与注册 preset，返回 job_id |
| `get_analysis_job` / `cancel_analysis_job` | 进度、实际阶段、错误、取消结果；禁止把 accepted 当 completed |
| `get_analysis_result` | 分页读取 stems/notes/chord_regions、时域来源、分数类型和模型版本 |
| `accept_analysis_result` | 引用不可变 result_id 并再次检查工程/目标，整组导入或拒绝，一次 Undo |

任务阶段：queued → preparing → running → validating → ready；错误、取消和过期有各自终态。接受另有 applying → applied，不与模型推理完成混为一谈。运行中的取消优先协作退出，超时只终止所属分析进程；原子工程提交不做半途取消。

源快照记录 project_id、clip/asset ID、内容 hash、源采样率/采样范围、clip source_offset、时间线位置、参数、模型/运行库版本。源素材准备采用既有解码链，支持 WAV/MP3；默认分析未加轨道效果的选定源范围。不能偷偷离线渲染第三方插件链或改变播放混音；后续渲染输入模式需明确区分。

所有分析先使用**秒与源采样位置**；分块、重采样、padding/延迟与拼接必须可追溯。导入才映射到当前工程拍位；现有默认 120 BPM 不自动更改，不强制量化。Tempo/clip 移动/裁剪导致映射变化时，重新预览确认；源删除、内容改变、工程切换均不得把旧结果错误写回。无关编辑不必重做推理，但应用仍须重新校验当前 revision。

## 5. 结果如何落入工程

- 分离：候选四轨可 solo/试听，接受后在原 clip 时间位置建立对应音频轨；原素材保留。共同重采样/增益策略，避免每 stem 独立归一化后改变相对电平。核对输出长度、有限数值、采样率、通道与内容 hash。
- MIDI：每个已支持分轨形成独立 MIDI 候选，可调阈值、音域、最短音长并回看波形；导入可编辑钢琴卷帘。模型输出力度/弯音不等于原演奏精确复原；首批 notes-only 应明确显示未保留的表达内容，不能静默丢弃。
- 鼓：Basic Pitch 不用于识别 kick/snare/hat；专用模型未就绪时界面显示“鼓转录待支持/节奏候选”，不对 drums 或混合 other 返回貌似完整的音高 MIDI。
- 和弦：原混音/和声分轨均可作为输入选项，先做标签区间和修正，不自动转柱式和弦 MIDI，不扩展到未请求的伴奏编配工具。`N` 表示无和弦，“不确定”单列；模板分数或 softmax 是未校准分数，不写成正确概率。
- 和弦对象及接受后的分析 provenance 需新增版本化工程字段；未来升 schema 时做旧工程迁移和旧版明确拒绝，防止 0.8.1 打开新项目静默丢失和弦数据。原声、clip 和原 MIDI 不被分析结果覆盖。

既有 Agent 每方案 2000 次音符处理/16 动作、原生工程 100000 音符/64 轨等上限继续有效。不能靠把整首转录塞进 LLM JSON 来绕过。新导入动作必须使用受控本地 result_id，经逐页/总体数量校验和有界预览导入；这是独立受控契约，原有编辑动作上限不偷偷放宽。超限明确拒绝或由用户选择范围，不静默截断。

## 6. Agent 页面固定功能清单

现有首页示例按钮和系统提示是手工文字；系统提示仍声明不能分析音频。后续将固定清单、工具 schema、提示词与真实能力注册表联动，避免界面说能做而执行层不知道。

页面建议固定显示：**工程/选区、MIDI 编辑、片段编辑、原生装置、音源分离、分轨转 MIDI、和弦识别**。每项显示“可用 / 未安装模型 / 实验中 / 当前选区不适用”，展开才展示参数与示例；模型未装好时不可伪装已可调用。

示例提示随能力就绪后启用：

- “把选中音频分成人声、鼓、贝斯、其他，先给我试听。”
- “把刚才分出的贝斯转成 MIDI，保持原时间位置。”
- “识别第 9 到 17 小节的和弦，低分结果标出来。”

能力可用条件取 DAW 命令、已实现 Agent 适配、分析进程健康状态、模型安装/许可记录及当前选择的共同结果。提示词改成“通过分析工具获取音频的结构化结果”，不让模型在未分析时凭文件名猜和弦。任务进度独立显示，不为轮询进度反复请求付费模型。

## 7. 实施顺序与验收

1. **保留 0.8.1 / 环境探针**：本轮已归档并核对；下一轮先锁实际 Python、运行库、权重来源与 hash，实测 CPU/CUDA 就绪和短片段资源。权重许可未解决的工件只保留候选，不标发布可用。
2. **任务底座与四轨分离**：输入冻结、队列、取消、worker 崩溃隔离、结果预览/接受、一次 Undo、保存重开；手动和 Agent 同批接入。
3. **有音高分轨 MIDI 与和弦基线**：时间映射、人工修正、持久化与结果分页；同步更新能力清单。处理完成与识别质量分别验收。
4. **鼓/复杂多音与模型升级**：专用鼓模型与 GM 映射、混合 other、扩展和弦词表、较高质量分离；未通过相应测试前保持实验或不可用。

默认一个重推理任务，分块、有界内存/磁盘缓存，CPU 限线程；录音优先，允许暂停/延后分析。模型推理、解码、网络、JSON、文件读写均不进入音频回调；进程隔离不等于资源干扰为零。

自动验收：静音/短片段/MP3/立体声/异常文件、分块边界与重采样时间对齐、无效和极短音符、取消/OOM/worker 崩溃、源改变、工程切换、结果幂等导入、撤销重做、保存重开和 GUI/Agent 一致性。用自己录制或获授权的真实音频评估串音、音符 F1/起止偏差、时长加权和弦准确率/未知占比；合成音只验证管线，不能冒充真实音乐质量。

性能报告记录本机、Release、输入时长/采样率/模型参数、实际硬件路径、RAM/VRAM 峰值、首包和全程耗时；播放/录音共存需记录实际 ASIO rate/buffer 和 xrun。没有测量前不承诺实时或固定秒数。用户继续负责真实界面和听感，我们负责编码、自动检查、构建与可追溯日志。
