# 云端生成契约与部署记录

2026-11-06。本文件描述接口；真实模型运行证据另见 CLOUD-RESULTS。模型安装中时，不把接口测试当推理完成。

## 边界

`scripts/cloud/gateway.py` 只监听云端 `127.0.0.1:18081`。Windows helper 建立 SSH 隧道；没有开放公网模型端口。`gateway_start.py` 使用 Linux 文件锁与健康检查，幂等启动当前已开机实例上的服务，不创建实例、充值或更改计费。

一个线程顺序处理 GPU 重任务；ACE 模型在首个任务加载并保留，连续请求复用。SQLite WAL 保留请求和状态；进程重新启动时，将未完成任务明确标为 interrupted，不自动再次推理。GUI 和 Agent 不直接调用模型私有 API。

## HTTP v1

| 方法 / 路径 | 意义 |
|---|---|
| GET `/health` | `{service:"emusician-generation", protocol_version:1, status:"ok"}` |
| GET `/capabilities` | providers 列出实际部署模型、available、时长和拍号限制 |
| POST `/jobs` | 创建任务；202 新任务、200 已有同请求、409 同 ID 不同参数 |
| GET `/jobs/{request_id}` | 状态、阶段、错误、完成结果 |
| POST `/jobs/{request_id}/cancel` | 排队立即取消；运行中进入 cancelling，安全检查点停止或丢弃结果 |
| GET `/jobs/{request_id}/artifacts/audio.wav` | 仅 ready 状态允许下载，不接受任意路径 |

提交字段：`request_id`（1–80 位英数字、下划线或连字符）、`kind:"generate"`、`model_id:"ace-step-1.5-xl-turbo"`、`prompt`（1–2000 字符）、`lyrics`（0–4096）、`instrumental` 布尔值、`duration_seconds`（10–120）、`bpm`（30–300）、`time_signature`（2/4、3/4、4/4、6/8）、`seed`（0–2147483647）。纯音乐请求不同时填写歌词。未知字段、非有限数字、超长 JSON 被拒绝。

最多 16 个未完成任务；一次一个 GPU 推理，batch=1。状态为 queued、loading、running、postprocessing、ready、cancelling、cancelled、failed、interrupted。progress 为 null，避免伪造模型没有提供的百分比。取消不是抢断任意 CUDA kernel；LM/模型调用尚未返回时可暂留 cancelling。

ready 的 `result` 含 `artifacts`、`model`、`parameters`、`conditioning`、`metrics`。唯一音频 artifact 为 `audio.wav`，包含 SHA-256、bytes、sample_rate、channels、duration_seconds、sample_format=pcm16。模型有 `id`、`revision`/`weights_revision`（完整权重锁的 SHA-256）、source_commit、language_model、backend、dtype、steps。duration_seconds 是实际音频长度，不用请求值冒充结果。

模型目标 BPM 目前取整到 ACE 接口支持的整数并单独记入 conditioning；BPM/拍号/时长是生成条件，不保证精确节拍。云端不自行裁剪到小节、Warp、创建宿主轨道或覆盖工程。

## 固定来源与适配

- ACE 源码：`https://github.com/ace-step/ACE-Step-1.5`，commit `ca1e85fe9430179831e6bc6be790c332190a3866`，官方 codeload 归档。
- 模型：官方 ACE-Step ModelScope 发布者 XL Turbo、主仓库 VAE、Qwen3-Embedding-0.6B、acestep-5Hz-lm-1.7B。每个文件的 upstream revision、size、SHA-256 在 [CLOUD-MODEL-LOCK.json](CLOUD-MODEL-LOCK.json)。下载到独立实文件，不使用 HF 缓存符号链接。
- Python3.12，Torch2.10.0+cu128，依赖首先使用上游 uv.lock。远端 PyPI 传输受阻时只替换 wheel URL 主机为阿里云镜像，版本与全部 SHA 不变；上游/传输锁哈希在部署 manifests/ace-lock-transport.json，环境实装 freeze 另存。
- 官方 AutoDL `/etc/network_turbo` 只在安装子进程启用，不打印环境/代理凭证；模型计算进程使用本地权重，设置 HF/Transformers offline。
- `PinnedXLHandler` 仅改模型存在性预检：上游初始化 XL 仍要求未使用的默认 2B DiT，我们检查实际 XL/VAE/text/LM，避免用户任务触发额外未固定下载。源码文件未修改。上游按自身规则将对应 XL Python 模型代码同步到 checkpoint；该代码来源是固定 source_commit，权重 SHA 不变。
- PyTorch backend、BF16、SDPA、不 compile、不量化、不 CPU offload。实际资源消耗以 CLOUD-RESULTS 为准。

## 数据与恢复

云端根 `/root/autodl-tmp/emusician`；模型 models/ace/checkpoints、环境 envs/ace、源码 workspace/third_party、任务 jobs/generation、队列 state/generation.sqlite3、记录 manifests、原始日志 logs。服务启动日志按 UTC 时间留存。

本地根 `E:/MusicAgent&DAW/cloud-inference`。源脚本在仓库 scripts/cloud，部署副本在 E 盘 tools 与云端 tools；模型/结果/环境清单最终保存至 E 盘，不进入 Git。

备份前停止提交并完成/取消任务。`backup_data.py` 先用 SQLite online backup API 将 committed WAL 内容写入 manifests/generation-queue.sqlite3，并验证 integrity_check，再归档选中目录；发现活跃任务则拒绝。不要直接 tar 正在写入的 SQLite/WAL。镜像不包含 AutoDL 数据盘；envs 不在此数据包，按固定锁和 freeze 重建。

换实例恢复时：先停止网关，解包并校验文件，在新实例 `state/generation.sqlite3` 不存在时将 manifests/generation-queue.sqlite3 复制到该位置，再启动服务；**不要覆盖仍在运行实例的队列数据库**。重启会保留完成结果并将未结束项标为 interrupted。重新配置本地 SSH alias 指向新实例、检查 host key 后再连接。此说明不是跨实例恢复已验证的声明。
