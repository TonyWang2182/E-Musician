# 云端 MIR 预部署结果（2026-11-06）

**已完成文件、独立环境和 CPU 模型加载检查；未完成推理、性能评估或 DAW 接入。** 这次复制的是现有本地模型，提供后续可选的云端计算位置，不是识别质量升级，也没有搬走或禁用本地模型。DAW 仍维持本地 MIR + 云端 ACE。

## 实际部署

| 模型 | 固定版本 / 修订 | 权重字节数 | 本轮结果 |
|---|---|---:|---|
| HTDemucs 四轨 | Demucs 4.1.0；权重 `cbc8a9b1a87023b7fd74e7b3412e6321c0eab003` | 84,025,440 | CPU 加载通过，四个 stem 名称符合预期 |
| HTDemucs 六轨 | Demucs 4.1.0；权重 `3c5ee475be622df764938de97e4281a7b07ffa58` | 54,885,744 | CPU 加载通过，六个 stem 名称符合预期 |
| BasicPitch ONNX | 0.4.0；`pypi-basic-pitch-0.4.0` | 230,444 | 上游 Model 包装器加载通过，仅 CPUExecutionProvider |
| BeatThis final0 | 1.1.0；源码 `b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c` | 81,058,141 | CPU 权重加载通过 |

权重共 **220,199,769 字节**。上传前与云端解包后均逐项比较本地登记 SHA；共 10 个模型/辅助/源码文件校验通过。BeatThis 源码 ZIP SHA 为 `b01cb9f5001080f577394b502de487fcb57b3fe755c0603d543afc46cd8cc5cf`。HTDemucs 的许可备注沿用现有个人评估记录，不据此声称获得公开再分发许可。

云端根目录 `/root/autodl-tmp/emusician`：

- `models/mir/`：四个模型的独立副本，保留来源版本子目录。
- `envs/mir-torch/`：Python 3.12.3、Torch/Torchaudio 2.10.0+cu128、Demucs 4.1.0、BeatThis 1.1.0；56 个包的哈希锁定与依赖检查通过。
- `envs/mir-transcription/`：Python 3.12.3、BasicPitch 0.4.0、ONNX Runtime 1.20.1；41 个显式依赖加 BasicPitch 独立 overlay。其元数据在 Python≥3.11 自动要求 TensorFlow<2.15.1，本批明确不安装该后端，用上游支持的 ONNX 路径。不能把此环境写成上游全依赖检查通过；实际 CPU 加载已经验证。
- `manifests/mir-stage-status.json`：全部 `available=false`，状态为 `cpu-load-verified-awaiting-inference-and-routing`；没有注册为现有服务可执行任务。

检查子进程以 `CUDA_VISIBLE_DEVICES=""` 启动，Torch 报告 `cuda_initialized=false`。没有前向推理、GPU 占用测试、真实音频输入、分离质量或用时结论；1.68 秒左右的数字仅是 CPU 导入/权重加载时间。没有安装新生成模型，没有启动/重启现有网关。

## 占盘与 E 盘保存

09:40:24 UTC 既有容量记录：可用 208,089,600,000 字节；10:02:22 UTC 实测可用 **199,730,733,056 字节（199.73 GB）**。期间文件系统占用净增加 **8,358,866,944 字节（8.36 GB）**，含环境、缓存和暂存包；这是两次文件系统读数的差，不是模型权重大小。

`du -sb` 目录逻辑字节：Torch 环境 7,504,797,457；ONNX 环境 309,034,494；MIR 模型目录含辅助文件 220,218,752。uv 可以共享缓存/硬链接，这些目录读数不能与缓存简单相加作为物理占用。Torch 的直接 URL 缓存键不同，初次安装重新取得了同一锁定 874 MiB 制品；NVIDIA wheel 复用了已有缓存。

本地持久资料：`E:/MusicAgent&DAW/cloud-inference/environments/mir/`。其中 `mir-stage/` 含四个权重、源码与清单；`evidence/` 含精确锁、freeze、CPU 检查和最终状态；脚本副本在 `cloud-inference/tools/`，原始日志副本在 `cloud-inference/logs/mir-stage/`。已有本地 MIR 原目录不变。本批未执行完整云盘备份；此前 ACE 完整备份不包含本次新文件。

## 失败、修复和证据

第一次安装的包解析/安装和 Torch 依赖检查成功，随后 CPU 检查失败：Windows `Path` 序列化把远程路径写成反斜杠。已修为 `.as_posix()`，只更新阶段清单与新脚本，保留原始失败记录；第二次按已生成锁文件安装/检查通过，没有重新下载权重。

云端 `cache/mir-stage-assets.tar` 与配套 transfer receipt 仍是首次上传的失败阶段包，不能作为最终恢复包复用；运行目录内最终清单和 E 盘重新生成的阶段包已经修正。新用户指令要求后续新增模型仅落云端，本批到此冻结，不再传模型或执行备份。

- 准备/上传/完整性：[准备](../../builds/20261106T095754.792357Z-c560b4cf73.json)、[上传](../../builds/20261106T095820.481531Z-f32b4c4394.json)、[云端校验](../../builds/20261106T095856.486196Z-e28b313d24.json)。
- 首次失败：[记录](../../builds/20261106T095914.949541Z-521b2865d4.json)；路径修复后：[通过记录](../../builds/20261106T100110.135982Z-3dd8deb5f9.json)。
- ACE 未变及占盘：[记录](../../builds/20261106T100221.804936Z-e8cb5c0255.json)；证据回传：[清单](../../builds/20261106T100223.274181Z-215f241098.json)、[输入](../../builds/20261106T100226.826200Z-3e01439180.json)；新脚本语法：[通过](../../builds/20261106T100228.576316Z-f3bac3a359.json)。
- `ace-runtime.json` SHA 前后 `5d829934…5465`、ACE `pyvenv.cfg` 前后 `c7af3569…a2ee`、完整 ACE 包 freeze SHA 前后 `495d4756…e563` 一致；前后 `/health` 均 `ok`。这只证明上述清单/包列表未变及服务健康，不代替再次生成验证。
- 完整哈希、版本与 CPU 检查见本目录 `VERIFICATION.json`、`locks/`；本轮无 DAW 编译或用户工程写入。

## 后续仍未做

保持当前部署冻结。未来需要明确推进时，再做共用 GPU 调度、CPU/GPU 推理测试、取消与资源释放、音频上传/结果下载和 DAW/Agent 本地云端选择。不能以“已安装”推断能在应用中切换，也不能把同一模型换到云端当作准确率升级。

参考官方资料：[Demucs 4.1.0](https://github.com/adefossez/demucs/releases/tag/v4.1.0)、[固定 BeatThis 源码说明](https://github.com/CPJKU/beat_this/blob/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c/README.md)、[BasicPitch 0.4.0 运行后端说明](https://github.com/spotify/basic-pitch/blob/v0.4.0/README.md)。
