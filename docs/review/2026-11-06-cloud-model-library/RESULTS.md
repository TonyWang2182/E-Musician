# 云端模型库部署结果

状态：五个新增模型的文件、隔离环境、CPU 加载及真实 GPU 短推理通过；MuScriptor 权重访问受阻，公共源码/环境已验证。本轮分支 `feature/cloud-model-library`，基线 01936fa。遵循用户最新范围：新权重与音频仅留云端，不进行 E 盘模型备份，不接入 DAW。

## 按模型验收

| 模型 | 文件/独立环境/加载 | 实际 GPU 推理 | 当前可用范围 |
|---|---|---|---|
| YuE2 3B＋VAE | 已通过，21 个文件约 7.79 GB | 已生成 7.68 秒实际音频 | 仅测低显存 8 GiB、短语义 token 上限、cot off；完整歌曲/演唱/符号计划未验 |
| SCNet XL IHF | 已通过 | 8 秒输入→四个等长音频 | 云端窄 CLI，四轨模型 |
| TransKun V2 | 已通过 | 8 秒输入→40 音符及8个CC事件 | 钢琴专用，实际保留 CC64/67 |
| ChordMini BTC | 已通过 | 8 秒输入→9 段和弦 | 170 标签词表，不保证词表外爵士扩展 |
| SheetSage2＋MERT2 | 已通过，42 个文件，主权重约 2.76 GB | 8 秒输入→ABC、MIDI、旋律/和弦/节拍等标注 | 默认 BF16/SDPA、原生300秒窗口；谱面 PDF/图片渲染和 paper 解码后端未部署/未验 |
| MuScriptor | 公共源代码/环境/CLI已检查，权重未获得 | 未运行 | 权重下载要求账户访问授权；已记录匿名401，未重试绕过 |

以上新模型均 `daw_connected=false`。已有 ACE 云端生成及基础 MIR 对照环境保持。模型安装/命令行短推理不自动增加桌面或 Agent 工具。

## 最终资源核对

10:45 UTC 汇总：云端数据盘总计 268,435,456,000 字节，可用 **166,708,670,464 字节（166.71 GB / 155.26 GiB）**，超过50 GB保留线。相对本批开始的199.73 GB减少约33.02 GB，包含模型、多个隔离环境、下载缓存与输出，不能全部算作权重大小。六份清单验证无错误，详见 [CATALOG.json](CATALOG.json)。

ACE `/health=ok`，原PID5862仍存在、无活动任务；runtime清单、pyvenv配置和实际包freeze三项SHA与部署前一致。GPU恢复到已驻留ACE的17,337 MiB占用、14,774 MiB空闲；未重跑生产生成。详见 [最终云端复核](FINAL-CLOUD-AUDIT.json)。本地汇总首次因uv提示混在JSON前而解析失败，随后从同一保留日志提取并校验，没有重复模型任务。

## 结构与证据

- 权重：`/root/autodl-tmp/emusician/models/<model>/`；环境：`envs/<model>/`；固定上游源码：`workspace/models/`。
- 每模型独立 `manifests/model-library/<model>/deployment.json`，记录源码/权重版本、SHA、环境锁、各层验证和阻碍；根 `catalog.json` 只是证据汇总，不启动服务或激活 Provider。
- 原始日志在云端 `logs/model-library/` 及本机忽略目录 `build-logs/`。本机 Git 只保存脚本、清单和小型证据；云端结果统一后续进入 `results/model-library/<model>/`。首次 YuE2 已验证结果保留原路径，不移动历史证据。
- [YuE2 结果](yue2/RESULTS.md)、[MIR 升级结果](mir-upgrades/RESULTS.md)、[运行手册](mir-upgrades/RUNBOOK.md)、[SheetSage2 / MuScriptor 结果](scores/RESULTS.md)。精确入口由各模型记录，不能用一个 Python 环境混跑。
- 最终本地审查：原0.12.1构建的257个源码输入逐文件未变；21个部署Python文件解析通过、25份当时证据JSON可解析、六份最终manifest与catalog状态一致。本批84个脚本/小证据文件不含模型或音频，凭证特征扫描零命中；[精确检查](VERIFICATION.json)，Recorder `20261106T104700.293909Z-440584ec22`。本批没有重建桌面，也不以旧CTest结果宣称新增云模型质量。

## 测量范围

机器为现有 AutoDL RTX5090 32 GB 实例。上述短探针为离线文件任务，没有启动本地 DAW/ASIO，因此不存在可引用的音频设备缓冲区数据。模型依赖版本、源采样率/重采样、batch/AMP、线程、输入 SHA、计时范围及峰值显存见各模型结果；已有 ACE 驻留但无任务。每次仅授权一个测试槽，检查 ACE 队列与显存，有新生产任务则仅中止测试进程。

没有独立真值数据，没有人工试听，没有热启动重复测量；不据此声明识别准确率、完整歌曲品质、长期并发稳定性或 AudioJam 等价体验。YuE2 达到人为 token 上限，明确是受限短渲染。后置诊断/取消兜底修正用 CPU 故障测试验证，模型推理代码未更改；原 GPU 测试脚本 SHA 与最终 guard SHA 分开保存，没有冒充重新运行。

## 后续独立任务

本批先把模型部署层整理好。后续需要访问授权的权重、完整歌曲/真实多素材质量评测、统一 GPU 模型调度、远程任务接口、GUI/Agent 路由与本地资产接受分别立项。用户本轮明确暂不做的本地大文件备份和 DAW 接入保持未实施。
