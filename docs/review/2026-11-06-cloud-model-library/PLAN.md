# 云端模型库部署：独立于 DAW 接入

2026-11-06，状态：实施中。用户明确要求同时部署所需云端模型，暂不把权重/音频/备份下载到 E 盘，也不接入 DAW。代码、配置、精确版本与小型日志摘要仍纳入现有 Git 工程管理。分支 `feature/cloud-model-library`，基线 `01936fa`；此前 0.12.1 修复及基础 MIR 阶段已独立提交、推送并保留版本。

## 部署范围

| 模型 | 目的 | 本轮负责方 | 不扩大宣称的边界 |
|---|---|---|---|
| YuE2 3B＋VAE | 符号规划与歌曲生成 | native_generation | 不接入现有生成界面，不冒充已通过听感 |
| SCNet XL IHF | 四轨分离对照 | cloud_ace | 不替代 HTDemucs 六轨 |
| TransKun V2 No Pedal Ext | 钢琴转 MIDI | cloud_ace | 不冒充通用多乐器转录 |
| ChordMini BTC | 神经和弦识别 | cloud_ace | 词表外扩展/转位不由模型大小补齐 |
| SheetSage2＋MERT2 | 旋律、和弦、节拍等综合分析 | agent_generation | 不是完整多声部总谱编辑器 |
| MuScriptor | 多乐器转录 | agent_generation | 如权重要求账户授权则标受阻，不绕过访问条件 |

已验证的 ACE 服务保持；基础 HTDemucs/Basic Pitch/Beat This 环境保持作为对照。可选 Mel-RoFormer、ACE XL Base 不在本批，避免没有实际评测目标就扩散安装。权重字节与固定版本沿用 [容量清单](../2026-11-06-hybrid-ai/CAPACITY-20261106.json)，新增配置/依赖按实测记录。

## 目录与所有权

云端唯一根 `/root/autodl-tmp/emusician`，部署脚本在本仓库 `scripts/cloud/models/`。禁止重新建立一套用户工程或修改本地模型注册。

```text
models/<model>/<revision>/         权重与配套配置，按版本保留
envs/<model>/                      独立 Python 环境
workspace/models/<model>/          固定 commit 的上游源码及明确兼容补丁
manifests/model-library/<model>/   deployment.json、锁文件、SHA 和验证结果
manifests/model-library/catalog.json  汇总索引，不能自动激活服务
logs/model-library/                每次安装/检查的原始日志，按模型命名或子目录
results/model-library/<model>/     有界推理输入/输出与测量（统一后续入口）
cache/                            可复用下载缓存，不是模型唯一保留位置
```

本机 `docs/review/2026-11-06-cloud-model-library/` 分为 yue2、mir-upgrades、scores 三个独立证据目录。负责人只修改各自脚本/目录；主代理管理顶层架构、汇总索引和状态。现有 ACE 的 gateway、SQLite 队列、envs/ace 和模型不混入本批环境，不改变 DAW 路由。

首次 YuE2 探针已在 `workspace/models/yue2/probes/` 形成验证证据，保持原位置和 SHA，不为整理目录移动历史结果；后续入口统一到 `results/model-library/yue2/`。每次部署脚本上传后按 SHA 冻结，禁止覆盖仍由进程读取的脚本；修复与重试使用新的版本文件并记录差异。

## 验证层次和运行规则

1. 固定上游来源、commit/revision、许可状态与文件 SHA/大小，实际云端下载后逐文件核对。不能用已有 API 元数据替代下载完成证据。
2. 独立安装依赖，保存精确锁和 freeze，记录补丁与失败。可共用经校验的下载缓存，但不原地升级其他环境。
3. 检查导入、CPU 权重加载和可运行入口。此项不等于 GPU 推理、识别质量或 DAW 可用。
4. GPU 实测必须由主代理分配顺序，不能在现有 ACE 工作时启动并发重推理。短探针先只读检查队列和空闲显存，运行中监测新 ACE 任务/显存压力并仅中止自己的探针，保留现有服务；这是临时评测协调，不是已经实现的多模型生产调度器。未获得条件的模型保留 `gpu_inference_verified=false`；没有验证的能力不得标 ready。
5. 本轮全部新模型 `daw_connected=false`，不修改本地 Provider 注册，不开启新公开端口。后续远程 Provider/共享 GPU 调度/选择界面另立任务。

统一 deployment.json 至少记录 id、task、source_revision、model_revisions、paths、checks、blockers 与 artifacts。`checks` 分开表示 files_verified、environment_verified、cpu_load_verified、gpu_inference_verified。汇总工具只展示，不能把“有权重”自动提升成“可以推理”。

部署前云盘可用 199,730,733,056 B；至少保留 50 GB 余量。若网络或授权受阻，保留部分下载/明确断点与失败记录，不改用来源不明权重、不通过本机 E 盘中转模型。

## 交付

交付实际模型清单、云端路径、精确状态、磁盘变化、可复用运行命令及所有未完成/受阻项。用户当前要求没有本地模型备份和 DAW 集成，不能为了证明功能而私自扩展这些工作。每次实际命令由 Recorder 记录，DEVLOG 只追加；最终更新 CONTEXT/DEVELOPMENT/ARCHITECTURE 并推送独立功能分支。
