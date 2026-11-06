# 云端部署与验证记录

状态：**ACE-Step 真实推理、队列和文件下载已验证**。2026-11-06，以下时间均为 UTC。人工听感、完整音乐条件遵循仍待用户验收；不把非静音测试当作音乐质量通过。桌面和 Agent 全链路证据由本轮主任务记录。

## 实际配置

- 已有 AutoDL 实例，RTX 5090，32607MiB，驱动580.76.05；16 vCPU，容器内存限制90GiB，数据盘250GB。没有新增、释放或关闭计费实例。
- 独立数据盘环境 `envs/ace`：Python3.12.3、Torch2.10.0+cu128、CUDA runtime12.8；实际 BF16 矩阵运算通过，GPU compute capability 12.0。原 base Torch2.5.1 保留。
- ACE 源码 commit `ca1e85fe9430179831e6bc6be790c332190a3866`；XL Turbo + 5Hz LM1.7B、Qwen3-Embedding-0.6B、VAE。BF16、PyTorch/SDPA、8 diffusion steps、batch1、不量化、不 compile、不 CPU offload。
- 官方 ModelScope ACE-Step 发布者的32文件，总计25,253,694,578字节，全部 size+SHA 检查完成。锁见 [CLOUD-MODEL-LOCK.json](CLOUD-MODEL-LOCK.json)，整体权重锁 revision 为 `4228da3a418e1f1a04d9799e8040b62860d26b7a8c4e80ce374a17e5418cc4bf`。
- 上游初始化会把两个 XL Python 模型文件从固定源码同步到 checkpoints；实际 SHA 单列于 `ace-runtime-model-files.json`。非Python模型文件在真实推理后再次验证 SHA，未改变。

## 真实推理

方法：固定自编 prompt/短歌词和 seed，在上述 GPU、单任务下调用真实模型；输出检查有限样本、非静音、峰值、实际长度、PCM16文件几何与SHA。表内耗时为 adapter 的 monotonic 时钟，含音频传回 CPU 后的同步结果；显存峰值在模型加载后重置，表示推理阶段的 resident+temporary 内存，不是加载阶段峰值，也不是全实例总用量。

| 探针 | 模型加载 | 推理 | adapter总耗时 | 输出 | allocated / reserved峰值 |
|---|---:|---:|---:|---|---|
| 12秒纯音乐，seed120，冷 | 31.746s | 3.100s | 34.871s | 12.0s / 48kHz / 双声道 / PCM16 | 15.16 / 18.74GiB |
| 12秒人声，seed121，热 | <0.001s | 2.198s | 2.221s | 12.0s / 48kHz / 双声道 / PCM16 | 15.16 / 16.36GiB |
| 120秒纯音乐，seed122，网关冷启动 | 27.119s | 13.838s | 41.171s | 120.0s / 48kHz / 双声道 / PCM16 | 15.38 / 18.76GiB |

120秒网关探针从提交、2秒轮询到下载校验的云端本机 wall time 为42.631s，不含 Windows SSH建连或公网传输；上限在这一个固定样本上通过，不代表任意歌词/prompt都具有相同耗时。两分钟输出23,040,044字节；12秒各2,304,044字节。峰值均0.89125（模型归一化-1dBFS）；RMS分别0.15134、0.11232、0.21612。

证据：

- `results/ace-smoke-20261106T075618Z/`：两个音频、原请求、结果和 smoke-results.json。
- `results/gateway-20261106T075755Z-120s/`：下载音频、请求、回执、probe.json。
- 原始日志 `logs/ace-real-smoke-attempt1.log`、`logs/ace-gateway-120s.log`。
- 真实探针成功后才将 `manifests/ace-runtime.json` 的 ready 设为 true；没有用模拟音频或静态示例冒充模型输出。

## 网关验证

- 真实120秒任务：同一 request_id/参数返回200旧任务，不重算；同ID不同参数409；完成结果的SHA与HTTP下载匹配；标准库 wave 读出正确的PCM16、双声道、48kHz、120.0s。
- 真实取消：`cancel-running-20261106T080000Z` 在 running 后取消，11.108s后进入 cancelled；排队 follower 立即 cancelled。两个取消任务均拒绝音频下载（409）。这是模型安全检查点取消，不承诺立即抢断 LM/CUDA kernel。证据 `logs/ace-gateway-cancel.log`、`results/cancel-20261106T080000Z.json`。
- 本地隔离队列/HTTP回归9/9：幂等、重启interrupted、参数冲突、队列限额、运行取消、完成artifact、失败后下一任务、非法字段/路径、SQLite WAL一致快照/活跃任务拒绝、输出目录失败不杀死worker。测试使用明确的 fake worker；仅用于控制逻辑，不能代表真实推理。日志 `logs/gateway-unit-tests-final-9.log`。
- loopback-only `127.0.0.1:18081`，startup/service两级文件锁避免重复进程。模型驻留复用，单GPU工作线程；CLI、Agent、手动任务均进入同一服务队列。没有开放公网端口。

## 安装与失败过程

原始日志保留在云端 `/root/autodl-tmp/emusician/logs`，并同步本地 `E:/MusicAgent&DAW/cloud-inference/logs`。

| 记录 | 开始/结束或结果 |
|---|---|
| `ace-clone.log` | 远端GitHub clone因网络失败；git已清理失败目录。改用本地官方codeload固定commit归档传入云端，未运行不完整clone。 |
| `ace-uv-install.log` | base只安装uv0.9.7工具，模型依赖写独立envs/ace。 |
| `ace-env-sync-attempt1.log` | 官方wheel下载连接/速度受限，主动中断，复用已完成缓存。 |
| `ace-env-sync-attempt2.log` | AutoDL开发网络加速后Torch wheel完成；NVIDIA PyPI依赖停滞，主动中断。 |
| `ace-env-sync-attempt3.log` | 07:23:28起，wheel URL传输域名替换Aliyun，版本/hash不变。141包最终装好；运行中的shell脚本被更新，末尾验证行偏移而报错，故本次整体不记为成功。 |
| `ace-env-final-validation.log` | 07:56:16–07:56:18，固定依赖复验成功（141包），真实BF16 CUDA运算成功并输出freeze；完整脚本exit0。 |
| `ace-wheel-relay.log`（本地） | 15个相同上游NVIDIA wheel，共3,001,998,484字节，在E盘下载/SHA校验并传云端作为复用缓存。原安装已完成，没有再替换为file URL或重复安装。 |
| `ace-model-download.log` | 2391.724s，32个文件全部验证；网络Timeout/RemoteDisconnected按Range续传，未重下已完成shard，单文件最多3次。 |
| `ace-real-smoke-attempt1.log` | 07:56:18起，两个12秒真实样本均通过，进程正常exit0后才允许网关加载，避免两个进程重复占GPU。 |

上游uv.lock SHA：`adf2f456d0497a3903c0c870bd2321b48bf3cfb00bfcdee2008936631bf8176a`；Aliyun传输锁SHA：`2213ec2d925471f5e9d34304d52562e23ae88413bd9e1407bb1e761cc20daf79`。环境实际包版本保存在 `manifests/ace-environment-freeze.txt`；硬件/驱动/包版本/真实CUDA探针在 `manifests/ace-cuda-probe.json`。

## 数据位置与未完成验收

- 云端源码、模型和任务均在 `/root/autodl-tmp/emusician`；源脚本见仓库 `scripts/cloud`。部署副本在云端tools和本地E盘tools。临时cache/envs也在数据盘，不写满30GB系统盘。
- 本轮模型探针样本和证据在本地 `E:/MusicAgent&DAW/cloud-inference/results/`。DAW实际生成候选由Windows helper写 `cloud-inference/jobs/<result-id>/audio.wav`，接受后复制为工程资产；这与探针results目录是不同用途。
- 完整模型数据包由主任务在任务空闲后统一备份；本子任务没有重复触发25GB全量归档。备份工具先在线备份SQLite（包括WAL）到manifests，再归档；gzip level1减少权重压缩CPU开销。跨实例恢复仍需单独验收，不能从生成成功推断。
- 待人工验证：音色/歌词/风格、真实节拍与拍号符合程度、长曲结构，以及DAW音频设备播放听感。BPM/拍号是模型生成条件，不是保证严格对齐的音乐事实。
- 未部署YuE2、MIR升级、多GPU或多任务并发；不以ACE已跑通代替这些后续能力。
