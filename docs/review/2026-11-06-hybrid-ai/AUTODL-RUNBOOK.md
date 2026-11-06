# AutoDL 保存、备份与复用手册

日期：2026-11-06。**这是待部署的操作方案，不代表目录、备份脚本、镜像或云服务已创建。** 对应 [完整模型/架构计划](PLAN.md)。

## 1. 跑完到底保存什么

不需要把显卡运行状态保存下来。我们用的是预训练模型推理，通常没有新的训练 checkpoint；要保存的是下次能重跑的材料和本次实际结果。

| 材料 | 最少内容 | 保存频率 |
|---|---|---|
| 部署代码 | 自有 commit、上游 commit、安装/启动/迁移脚本、配置模板 | 每次修改形成版本 |
| 运行环境 | Python、依赖锁/已安装清单、系统库/FFmpeg、Torch/CUDA、驱动、GPU、镜像 ID；必要 wheel/源码包及校验 | 每个通过验证的环境版本 |
| 完整模型 | 所有 checkpoint、config、tokenizer、codec/VAE、采样配置、准确 revision、SHA-256、来源与许可 | 每个正式评测版本一次 |
| 输入与任务 | 授权样本、输入 hash、裁剪区间、预处理、请求参数、seed、任务 ID、源码/模型版本 | 每次实验 |
| 原始输出 | 分轨 WAV/FLAC、MIDI、音符/和弦/节拍 JSON、生成 WAV；YuE2 ABC 与可用中间产物 | 每次实验与创作 |
| 评测证据 | 冷/热启动、各阶段耗时、显存/RAM、错误、听感/质量记录、人工修正成本 | 包括失败实验 |
| 本地工程 | 工程文件及它引用的本地 assets | 按用户正常保存操作 |

`pip freeze` 只是一份已安装清单，不能单独还原 Python、系统依赖、上游源码和 GPU 驱动。镜像也不能保证换主机后的驱动相同。所有成功模型至少保留准确可重建说明；重点环境可另存归档，并在另一实例验证恢复。

模型下载缓存可能只含指向 blobs 的符号链接。归档需保留完整链接目标，或导出成独立模型目录再核对实际文件 hash；不要只复制一个 HF snapshots 文件夹后以为权重已保留。

## 2. 保存在哪里

以下云端盘解释以普通容器为主。Pro 没有独立数据盘，`autodl-tmp` 为重置时保留的特殊目录，必须按实际实例类型检查。[普通环境/目录](https://www.autodl.com/docs/env/) / [Pro](https://www.autodl.com/docs/instance_pro_data/)

| 位置 | 用途 | 不能误解的地方 |
|---|---|---|
| 普通容器系统盘 | 基础依赖、代码、网关、较小环境 | 保存镜像包含此盘；通常容量较小 |
| `/root/autodl-tmp/emusician/` | 正在运行的环境、模型、输入输出 | 关机保留；普通容器的镜像不含此盘；释放实例会丢失 |
| `/root/autodl-fs/emusician/` | 已验证模型与结果档案，跨同地区实例复用 | 先确认实际已挂载；网络盘不宜直接做高频推理 IO |
| `E:\MusicAgent&DAW\cloud-inference\` | 本地长期主档、权重副本、实验结果 | 位于代码工作树之外；不要整目录上传 GitHub |
| 用户本地工程及 assets | 最终接受的音乐成果 | 工程不引用云端临时 URL 或易清理缓存 |
| Git 仓库 | 代码、精确版本、非秘密配置、文档和脱敏摘要 | 不放模型大文件、音频、token、SSH 私钥、完整云镜像 |

建议结构：

```text
本地 E:\MusicAgent&DAW\cloud-inference\
  manifests\models\<model-id>\<revision>\
  manifests\environments\<environment-id>\
  models\<model-id>\<revision>\
  datasets\<dataset-id>\
  experiments\<run-id>\
  results\<job-id>\
  backups\<backup-id>\

云端 /root/autodl-tmp/emusician/
  envs/<environment-id>/
  models/<model-id>/<revision>/
  jobs/<job-id>/
  state/                   持久任务数据库
  cache/                   可重建缓存；有容量限额
  exports/<backup-id>/      备份暂存；确认空间足够

云端 /root/autodl-fs/emusician/
  models/<model-id>/<revision>/
  environments/<environment-id>/
  archives/<backup-id>/
```

代码继续保存在当前真实工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`，以后部署脚本和锁文件再入库。运行库与用户产物不放进这个工作树。

文件存储不随普通实例释放而一起删除，但仍受平台账号/欠费清理规则约束，不能当唯一档案。当前文档列出 20GB 免费、额外容量计费；本文不据此保证全部模型可免费长期存放。[文件存储规则](https://api.autodl.com/docs/fs/)

## 3. 每次任务的结果包

```text
<job-id>/
  request.json             参数、seed、输入hash、选择范围、版本
  result.json              结果类型、时基、文件列表、能力与缺项
  metrics.json             机器/环境、逐阶段耗时、峰值内存
  inputs.json              输入列表、来源、许可和本地档案位置
  outputs/                 原始WAV/FLAC/MID/JSON，及可用ABC等
  logs/                    无密钥的stdout/stderr和错误
  checksums.sha256         完整文件清单
```

相同输入可按 hash 共用一份资产，避免每个任务重复存整首音乐。`inputs.json` 引用的资产必须一并备份或确认已在长期档案存在。结果包只记录凭据引用名，不记录凭据本体。

## 4. 第一次配置好后

1. 记录所租地区、实例类型、GPU、RAM、盘大小、实例到期/释放倒计时；检查实际文件存储挂载。不可只在未挂载的 `/root/autodl-fs` 路径下新建普通文件夹冒充备份盘。
2. 配置最小服务与一个模型，运行固定短样本。输出有效后锁代码、环境和权重 revision，不用浮动 latest 作为复用依据。
3. 把所需模型完整目录及 manifest 复制到文件存储，并下载一份到本地；较大的模型每个版本只保存一次，后续实验只保存引用。
4. 将代码提交和非秘密锁文件保存到 Git；本地和云端保存相同 manifest。具体 git 发布仍按项目既有流程。
5. 备份数据完成、任务停止、凭据未嵌入待分享环境后，**关机，再在控制台“更多→保存镜像”**。记录镜像名/ID和对应环境版本。镜像只是系统盘快捷恢复，数据盘环境仍需另存或重建。[官方镜像步骤](https://www.autodl.com/docs/image/)

不要把含 token/SSH 私钥的个人镜像公开分享。HF 下载凭据独立保存于受限秘密位置；只导出模型文件，不把整个含登录令牌的缓存目录当作公开模型包。

## 5. 每次收工的顺序

1. 停止接收新任务，等待当前任务终态；如果主动中止，记录 interrupted。不能打包仍在写入的 WAV 或直接复制活跃 SQLite 数据库。数据库用一致性备份，或正常停止服务后连同必要状态一起归档。
2. 生成带日期/版本的新结果包，含失败记录、参数、输出和校验清单。先检查运行盘与文件存储余量。
3. 上传到已挂载的文件存储；本地通过 SFTP 下载结果包和清单。用版本化目录，不使用会删目标文件的同步选项覆盖唯一备份。
4. 本地比较 SHA-256；解包后再检查内部文件；实际打开至少一个音频、MIDI 和 JSON。确认所引用输入/权重也可取得。
5. 若本次环境改变，数据备份后关机并保存新私有镜像；环境未变就不重复保存大镜像。
6. 查看控制台已关机。关闭网页、SSH 窗口或 DAW 都不等于实例关机。
7. 需要释放实例时，必须先完成异机恢复测试和本地副本验证；普通收工只关机，不依赖实例长期保管唯一结果。

普通容器官方当前为连续关机 15 天释放，Pro 为 60 天；潮汐等产品可能更短。释放和主机下架会清除实例数据，查看控制台倒计时。文件存储也有长期未登录/欠费清理条件。[普通实例](https://www.autodl.com/docs/instance_data/) / [Pro](https://www.autodl.com/docs/instance_pro_data/) / [文件存储](https://api.autodl.com/docs/fs/)

## 6. Windows 上具体怎么取回

最直观的方法是 SFTP：FileZilla 等客户端选择 SFTP，填写 AutoDL 控制台 SSH 提供的主机、端口、root 和登录凭据，右边进入已生成的云端归档目录，左边选本地 `cloud-inference\backups\<backup-id>`，下载归档及 SHA 文件。确认失败队列为空，再校验文件。[官方 SFTP 教程](https://www.autodl.com/docs/filezilla/)

下列是**未执行的命令模板**。需先创建对应归档和目录；`archive-host`、`12345`、`run-EXAMPLE` 均须替换为真实值。不会因为复制这些示例就自动获得备份。

在远端 Linux 终端，假定 `run-EXAMPLE` 已是停止写入的完整结果目录，只打包结果，不重复压缩全部权重：

```bash
set -euo pipefail
test ! -e /root/autodl-tmp/emusician/exports/run-EXAMPLE.tar.gz
test ! -e /root/autodl-tmp/emusician/exports/run-EXAMPLE.tar.gz.sha256
tar -czf /root/autodl-tmp/emusician/exports/run-EXAMPLE.tar.gz \
  -C /root/autodl-tmp/emusician/jobs run-EXAMPLE
cd /root/autodl-tmp/emusician/exports
sha256sum run-EXAMPLE.tar.gz > run-EXAMPLE.tar.gz.sha256
```

在**本地 Windows PowerShell**（不是服务器终端）：

```powershell
$backupDir = 'E:\MusicAgent&DAW\cloud-inference\backups\run-EXAMPLE'
if (Test-Path -LiteralPath $backupDir) { throw 'Choose a new backup directory' }
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
Set-Location -LiteralPath $backupDir
scp -P 12345 root@archive-host:/root/autodl-tmp/emusician/exports/run-EXAMPLE.tar.gz .
if ($LASTEXITCODE -ne 0) { throw 'Archive download failed' }
scp -P 12345 root@archive-host:/root/autodl-tmp/emusician/exports/run-EXAMPLE.tar.gz.sha256 .
if ($LASTEXITCODE -ne 0) { throw 'Checksum download failed' }
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath '.\run-EXAMPLE.tar.gz').Hash
$expectedHash = ((Get-Content -LiteralPath '.\run-EXAMPLE.tar.gz.sha256' -Raw).Trim() -split '\s+')[0]
if ($actualHash -ine $expectedHash) { throw 'Backup checksum mismatch' }
```

发生错误或中断就停止，不能把残留文件当成新备份成功；重试使用新的归档名和本地目录。下载后仍需解包和内部文件检查。第一次保存每个模型时也用 SFTP 复制完整模型目录、manifest 和校验清单。大文件传输优先使用可重试/续传客户端；上述 scp 示例没有实现断点续传。用户凭据不粘到文档或命令参数里。

## 7. 下次如何复用并连接 DAW

1. 原实例仍在：开机，核对模型与环境，启动后台服务。新实例：选择已保存私有镜像；挂载对应地区文件存储，把本次所需模型/环境恢复到运行盘。
2. 如果更换地区或文件存储不可访问，从本地档案或已验证外部存储恢复；镜像不自动迁移普通数据盘。数据盘环境若不能直接恢复，按固定依赖与系统包说明重建。
3. 记录新的驱动/GPU，核对模型文件哈希；固定 30 秒样本能运行才连接 DAW。验证方法不必要求跨 GPU 输出字节完全相同。
4. 启动云端后台任务服务并仅监听 `127.0.0.1:8000`。SSH 断开不应杀掉服务；用受管理进程或平台支持的 screen/tmux 启动，而非只在交互 shell 前台运行。[SSH 文档](https://www.autodl.com/docs/ssh/)
5. 本地 PowerShell 建立隧道（服务实现后才可用）：

```powershell
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:18080:127.0.0.1:8000 -p 12345 root@archive-host
```

6. 保持这个连接；拟新增 DAW 设置中的服务地址填 `http://127.0.0.1:18080`，凭据用独立本地安全配置；测试 health/capabilities 后运行真实任务。当前 0.11.0 尚没有此设置项。[官方隧道说明](https://api.autodl.com/docs/ssh_proxy/)
7. 断线重连后先按原 job_id 查任务，不直接重复提交。任务结果完整下载且用户接受后才修改工程。

## 8. 一次必须做的恢复演练

保留原实例，另起实例或干净环境 → 仅使用镜像/锁文件、模型档案、输入包恢复 → 完成一个真实 MIR 任务和一个生成任务 → 本地导入 → 保存并关云端 → 重开工程播放。列出实际步骤、时长、缺失依赖和 hash。通过后才可认为“这套部署能复用”。

无需备份可重建的 GPU kernel/编译缓存和每次失败的巨大中间张量；原始日志和失败参数仍保留。今后若进行 LoRA/微调，则额外保存训练数据版本、配置、adapter/checkpoint 和需要续训的 optimizer/scheduler/RNG 状态；本次预训练推理不需要这些训练材料。
