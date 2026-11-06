# MIR 升级模型：云端部署与短推理结果

三个选定模型已部署到现有 RTX 5090 实例，分别通过依赖检查、严格权重加载和一次 8 秒 GPU 推理。**仅云端命令行可用，未接入 DAW/Agent，没有模型权重或音频结果下载到 E 盘，也没有执行备份。** 这次证明能够实际运行，不构成识别准确率、听感或任意素材速度保证。

## 模型与来源

| ID | 固定源码 | 唯一选定权重 | 字节数 |
|---|---|---|---:|
| scnet | ZFTurbo/Music-Source-Separation-Training `a8a862231de29e6832a26c590e5c29f82f736f66` | v1.0.15 `model_scnet_ep_36_sdr_10.0891.ckpt` | 214,063,778 |
| transkun | Yujia-Yan/Transkun `c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6` | V2 No Pedal Ext `transkun/pretrained/2.0.pt` | 56,408,978 |
| chordmini | ptnghia-j/ChordMini `aa6e3a8d7b017f082fd2aaff9329d5c26af49c03` | `checkpoints/btc_model_best.pth` | 35,942,692 |

合计 **306,415,448 字节（306.42 MB）**。SCNet 权重及配套 YAML 按官方 release SHA-256 校验；另两份按固定提交的 Git blob 校验，再计算 SHA-256。源码按精确提交逐文件下载并验证 Git blob，SCNet 134 文件、TransKun 24 文件、ChordMini 52 文件；未顺带下载其他 checkpoint、训练数据或演示音频。原始上游源码没有修改。

- SCNet 权重 SHA：`ac25975f0f5704f3d1a3c3c251505b7a0f417a22eafe82773440ee4f7e14b74f`。
- TransKun 权重 SHA：`50a80010effc2a59ffcd068a95cd2b29bd7f23a27a3515bc3ccd209c89a3d44c`。
- ChordMini 权重 SHA：`e0a12ca6d881f81e01dfb459b4836ec7dac8d8f87b0170a412b5807256b3a1fc`。

## 独立环境和入口

云端根目录为 `/root/autodl-tmp/emusician`。每个 ID 独立放在 `models/<id>/<revision>`、`envs/<id>`、`workspace/models/<id>-<revision>`；登记在 `manifests/model-library/<id>/deployment.json`，日志在 `logs/model-library/`，结果在 `results/model-library/<id>/`。

三个环境均为 Python 3.12.3、Torch/Torchaudio 2.10.0+cu128，哈希锁和 freeze 已保存。SCNet 40 个包、TransKun 68 个包、ChordMini 69 个包通过 `uv pip check`。只共享不可变下载缓存，没有在 ACE 或基础 MIR 环境安装任何包。

兼容与范围选择：

- SCNet 的通用上游入口会导入训练数据增强及其他架构/GUI 依赖。本批窄 CLI 使用原始 SCNet 类、原始 `utils.model_utils.demix` 和选定 YAML，仅安装该路径所需依赖。batch 从配置的 4 固定为 1，overlap=4、chunk=485100、GPU AMP 开启；normalize=false 与发布配置相同。没有安装所有训练架构或声称完整训练 CLI 可用。
- TransKun 使用原始 `TransKun.transcribe` 与 `Data.writeMidi`，16 秒模型窗口；模型包括钢琴 21–108 和 CC64/67 事件，保留上游输出。上游 `python -m transkun.transcribe --help` 通过；setuptools 固定 80.9.0 以保留其使用的 pkg_resources。
- ChordMini 使用原始 CQT、标准化和 `predict_sliding_windows`，batch=1、hard vote、不开额外平滑。独立环境将其原 requirements 的 Torch 2.9.1 替换为已验证的 2.10.0+cu128，soundfile 0.12.1 替换为 0.13.1；其余顶层依赖按固定输入和最终锁记录。上游评估 CLI `--help` 通过。严格 state_dict 加载通过，没有使用非严格加载掩盖不匹配。

统一窄入口见 [RUNBOOK](RUNBOOK.md)。它不是 DAW Provider，也不自动启动服务或调度任务。

## 实际 GPU 探针

主代理明确分配独占测试时段，2026-11-06 10:17:16–10:17:52 UTC。机器为 NVIDIA RTX 5090 / 32 GB，Torch 2.10+cu128；已有 ACE 驻留但没有运行任务。输入是云端既有 ACE 钢琴三重奏结果的前 8 秒、48 kHz、双声道 PCM WAV；SHA `fc7793b3002302127c0e77df74cb396ebc9a88c92bd0ed9e6c78d0f7921960ea`。所有输入/结果留在云端，无参考真值。

| 模型 | 实际输出 | 推理/处理秒数¹ | 整个受管进程秒数 | CUDA allocated / reserved 峰值 |
|---|---|---:|---:|---:|
| SCNet XL IHF | drums/bass/other/vocals 四个 8 秒 WAV | 2.123 | 5.462 | 1.441 / 2.689 GB |
| TransKun V2 | 40 音符、8 个 CC（64、67）的 MIDI | 3.427 | 6.196 | 0.889 / 1.059 GB |
| ChordMini BTC | 覆盖 0–8 秒的 9 段 LAB + JSON | 9.873 | 12.268 | 0.0256 / 0.0398 GB |

¹ 排除模型加载，包含预处理、结果写出；ChordMini 含首次 CPU CQT/相关编译开销，不能把该值解读成纯 GPU 时间。没有热启动重复试验，不能外推到完整歌曲或并发性能。

每次准入均要求 ACE 无活动任务且空闲显存 ≥8 GiB。每 0.5 秒检查只读 SQLite 活动状态和 nvidia-smi，遇 ACE 新任务、显存 <1 GiB 或 180 秒超时仅终止本次子进程组；三次都一次通过，无重试、无 CPU 回退。空闲显存最小分别 11,596 / 13,150 / 14,130 MiB，结束恢复到 14,774 MiB；已显式释放测试槽。

主代理事后审查发现监控异常分支缺少 SIGKILL 兜底，以及最终健康查询失败可能阻止收据保存。已在 GPU 测试全部结束后修复；3 项纯 CPU 故障注入通过：拒绝 SIGTERM 的自有子进程得到 SIGKILL、监控读取失败会终止子进程并标记 interrupted、最终诊断超时仍落盘终态收据。见 [CPU 记录](../../../builds/20261106T102503.755071Z-fc91eeea5d.json)。GPU 实测使用 guard SHA `6b68695bcd54d73dd7b3d0915ad99d536a9d933a6214ba23a43eaca60ee7d709`；最终 guard SHA 和变更性质另记 deployment，不把旧探针冒充最终脚本重跑结果。模型/推理代码未因此改变，没有再次占用 GPU。

保存后再次读取并校验：四个 WAV 均 44.1 kHz/双声道、8 秒、有限且非零；MIDI 重读仍有 40 音符和 CC64/67，末音符结束 7.99948 秒、末控制事件 8 秒；LAB 连续覆盖 0–8 秒。每个输出大小/SHA、原始进程日志、输入来源和用时均在 `gpu-probe-*.json` 与 deployment 清单中。

## 已知能力边界

SCNet 这里仍是四轨，不区分主/和声人声、主音/节奏吉他、钢琴/电钢琴。TransKun 专用于钢琴，这次真实输出了并保留踏板控制，但没有做音符或踏板准确率评测。ChordMini 是 **170 标签：12 根音×14 类和弦 + X/N**，包括七和弦/减七/半减七/增和弦等；没有显式 9/11/13 或 slash bass 类别，不能称为任意爵士和弦识别。

未做长音频、完整歌曲、多曲目质量对照、人工试听、MIDI/和弦真值评测，也没有 DAW 手动/Agent 路由。云端短推理通过不表示已经达到 AudioJam 的准确率或响应体验。

## 审计与不变项

所有下载直接发生于云端，E 盘只新增脚本、计划、JSON/锁/日志。没有追加本地权重、WAV、MIDI、LAB、源音乐或完整备份。中央 catalog 由主代理维护，本目录不更改本地模型注册或 DAW 文件。

ACE runtime/config/package-freeze SHA 仍分别为 `5d829934…5465` / `c7af3569…a2ee` / `495d4756…e563`；`/health` 保持 `ok`。10:20:48 UTC 全实例数据盘可用 **174,497,505,280 字节**；同时存在其他代理部署，不能把该容量变化全部归因于这三模型。模型目录含配置/目录开销分别为 214,069,855 / 56,409,068 / 35,942,794 字节。

关键记录：下载 [ed5aab25e3](../../../builds/20261106T100855.616261Z-ed5aab25e3.json)；环境/CPU [35b4cc00ad](../../../builds/20261106T101309.905919Z-35b4cc00ad.json)；GPU [SCNet](../../../builds/20261106T101716.000861Z-90aec93d76.json)、[TransKun](../../../builds/20261106T101732.158735Z-46743926e0.json)、[ChordMini](../../../builds/20261106T101739.677562Z-3c1589972b.json)；保存输出审计 [SCNet](../../../builds/20261106T101946.288836Z-c5072037db.json)、[TransKun](../../../builds/20261106T101947.741576Z-a5e4512b81.json)、[ChordMini](../../../builds/20261106T101949.619110Z-588e834266.json)。本轮这些模型命令无失败/重试，弃用方案不作验收。

精确来源、全部文件 SHA、源码、许可文本位置和依赖锁见 `evidence/<id>/`；这里只进行私有云端评估，没有声称权重可公开再分发。官方来源：[SCNet 发布](https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/tag/v1.0.15)、[TransKun](https://github.com/Yujia-Yan/Transkun/tree/c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6)、[ChordMini](https://github.com/ptnghia-j/ChordMini/tree/aa6e3a8d7b017f082fd2aaff9329d5c26af49c03)。
