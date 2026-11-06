# 云端 MIR 基础模型预部署（2026-11-06）

用户在 0.12.1 稳定性修复期间明确授权并行部署其他模型。本批只准备现有本地模型的云端副本与独立运行环境，不改变 DAW、Agent 或正在服务的 ACE 环境，不将安装成功写成推理或接入成功。

## 范围与顺序

1. 从本地 `E:/MusicAgent&DAW/analysis/registry.json` 读取 HTDemucs 四轨、六轨、BasicPitch ONNX、BeatThis final0 的精确版本、来源、权重 SHA-256 与许可备注；上传前后逐文件校验。
2. 云端数据盘 `/root/autodl-tmp/emusician` 新增 `models/mir`、`envs/mir-torch`、`envs/mir-transcription`。Torch 采用现有 ACE 锁定的 2.10.0+cu128 制品，复用下载缓存；不修改 ACE 包、源码、模型或服务。
3. Linux Python 3.12 独立解析、哈希锁定依赖。BasicPitch 明确安装 ONNX 后端；其上游在 Python ≥3.11 自动要求旧 TensorFlow，因此单独 `--no-deps` 安装 BasicPitch 并显式锁定其余依赖，记录兼容例外。
4. 仅允许文件完整性检查、模块导入和 CPU 模型加载；`CUDA_VISIBLE_DEVICES` 为空，不执行推理，不占用 ACE 的 GPU。登记 `available=false`。
5. 将清单、锁文件、安装记录和验证结果保存回本地 E 盘。原始命令日志在忽略目录 `build-logs`，摘要由 Recorder 写入 `docs/builds` 与追加式 DEVLOG。

## 本批之后的接入验收

先建立 ACE/MIR 共用的单重任务队列和资源释放策略，再做有界音频上传、进度/取消、结果校验下载、真实推理对照，最后增加本地/云端/自动设置与 Agent 同等路由。当前 DAW 仍是本地 MIR + 云端 ACE；本批没有可用的自由切换入口。远程成功后结果仍需下载到 E 盘成为独立候选，经用户确认再导入工程。

不部署 YuE、MuScriptor、其他可选权重，不进行完整云盘备份，不同时开第二个 GPU 推理进程。本批安装不是模型质量升级，准确率和响应时间仍需之后用同素材测量。

## 验收记录

状态：实现中。结果与失败修正将写入本目录 RESULTS.md；不可根据本计划推断部署完成。
