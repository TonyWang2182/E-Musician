# 架构 2–4：统一计算管线与最终候选

2026-11-07（Asia/Shanghai）。状态：已实现，自动化与七模型整链验证通过，用户人工验收待完成；结果见 [RESULTS](RESULTS.md)。基线 `a6951f3`，分支 `feature/hybrid-pipeline-v0130`。用户要求完成后统一验收；本批将此前部署好的模型接入可操作的完整管线。保留旧 0.12.1 程序、模型环境及用户工程，不自动合并 main。

## 范围与验收

1. 已有模型部署是基线：ACE、YuE2、SCNet、TransKun、ChordMini、MuScriptor medium、SheetSage2；不重新训练或下载另一套权重。
2. 云端统一服务：有界音频上传、内容校验、持久幂等任务、单 GPU 串行调度、各模型隔离进程、取消与重连、结果原子发布。旧 ACE 驻留服务须在确认无任务后迁移，不能与新队列竞争显存。
3. 本地适配与契约：本地/云端/自动及明确模型选择；冻结源片段；仅上传所需音频；下载校验候选。钢琴 CC、多乐器、复杂和弦原标签、综合旋律/和弦/拍点/结构不得静默丢弃。模型未预测的力度、速度、可信度不得冒充预测。
4. DAW 与 Agent：共用命令、范围与修订校验、试听/明确接受、一次 Undo/Redo、保存重开且云端离线可用；最终独立 0.13.0 构建和人工验收清单。生成沿用工程默认速度，不重复追问已知参数。

不包含新训练、MuScriptor large、新增人声专项模型、完整五线谱编辑器、自动租卡/关机。新模型权重继续只在云端；本批接入后实际用户结果必须按原架构落本地工程资产，不把模型备份与结果下载混淆。

## 文件归属

| 负责人 | 文件 |
|---|---|
| root | 本地传输与模型路由、audio_analysis common、构建/部署入口、顶层文档、最终整链验证 |
| cloud_ace | scripts/cloud/compute、test_cloud_compute*、本档案 cloud 子目录 |
| native_generation | apps/desktop 原生 UI/分析/生成/存储契约及原生相关测试、本档案 native 子目录 |
| agent_compute | scripts/music_agent、test_music_agent*、本档案 agent 子目录 |

三方先固定协议再实现。运行中的云端脚本上传到版本目录后冻结；实际命令均用 Recorder，失败和中断保留，DEVLOG 仅追加。既有六份未跟踪 build records 保持。

## 结果协议

本地 start_analysis 增加顶层 execution=local/cloud/auto 与 model_id；新增 kind=score。compute-registry.json 独立于本地 registry，记录配置和已探测能力；每个任务重新确认远端能力。旧命令兼容。

云端 loopback 18082 提供 health/capabilities、PUT/HEAD assets/{sha256}、POST jobs、GET jobs/{id}、POST jobs/{id}/cancel、GET jobs/{id}/artifacts/{id}。分析上传冻结 WAV，任务仅引用服务端资产 ID；不接受任意路径或 shell。

原生候选继续 schema_version=1，增加 midi_tracks（秒、音符、CC）、structure_regions 与综合分项；存储 schema 根据实际新增数据升级。云端协议与原生协议在本地适配器转换，时间相对冻结片段，保存源映射。旧本地模型保持原有语义；明确模型不得静默替换。

## 验证顺序

- 契约及故障单测：坏输入/路径/超限/取消/断流/幂等/不丢 CC 与标签；模拟测试明确标注。
- 云端真实多模型任务：串行运行、原始输出及固定版本收据，含上传下载 SHA；恢复旧连接时不重复推理。
- 冻结源码 Release 构建/CTest/Python 回归；原生公共命令与 Agent 完成真实候选接受、Undo/Redo、保存重开、离线渲染。
- UI 渲染验证中英文及窄窗口；不使用 computer-use。物理 ASIO/键盘/听感留用户最终验收，自动检查不得代替。
- 成功后独立功能分支同步，完整结果、未解决项、程序入口及人工清单一并交付。
