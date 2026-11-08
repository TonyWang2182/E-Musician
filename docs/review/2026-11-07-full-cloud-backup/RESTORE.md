# 备份与恢复说明

本轮包为Linux原路径快照，不是Windows可运行环境，也不是完整操作系统镜像。用户报告保存的AutoDL系统镜像与此数据备份互补。2026-11-08补充：使用修正stat mode兼容性的校验器，要求本次verify退出码0及新写入verification.json；单看旧报告或phase不够。夸克副本交接、文件数/容量和全部后续步骤见[清单](../2026-11-08-quark-recovery/CHECKLIST.md)。下载中不能删除原实例。

## 文件组织

- part-000000.tarpart起的编号文件：按编号拼接为一个未压缩POSIX tar，不能单独解压某一块。
- receipt.json及各part-*.json：块大小/SHA；manifest.jsonl：每个归档成员类型、权限、链接和文件SHA。
- inventory.json：实际纳入范围/排除策略；system.json：系统包、Python、glibc等系统重建依据；links.json：链接目标与存在性。
- verification.json：本地完整性核对结果。progress.json只表示下载/校验进度，不能替代完整性结论。

保留数据根/root/autodl-tmp/emusician的模型、envs、workspace、sources、deployments、tools、assets、jobs、results、experiments、manifests、logs，以及state内两个SQLite一致快照与迁移标记。补充/root/miniconda3，因为8个环境Python链接指向它；SheetSage2的Python3.11位于workspace内。cache仅保留wheel。

HF令牌目录、SSH/API凭据、旧备份、VS Code服务器、Git对象、pycache、可重建uv/HF下载缓存、运行锁/PID/WAL/SHM不纳入。权重本身保留；未来重新下载受限权重时仍需自行提供授权凭据。

## 重新核验及续传

本机仓库脚本scripts/cloud/pull_full_backup.py提供pull和verify命令。pull使用相同host、remote-root、destination可重用已经SHA核对的完整块；未完成块重传，不能更换同目录的备份身份。verify不需要云端，核对每个块、tar文件内容、路径/链接/权限和结束标记，不把Linux链接解压到Windows。

## 在新实例恢复

1. 首选用户已保存的AutoDL系统镜像，在兼容Linux x86_64/NVIDIA驱动实例启动；先不要运行模型服务。系统镜像包含的内容以AutoDL保存结果为准，本轮未通过平台API核验镜像。
2. 上传本目录全部完整tarpart、receipt、manifest及校验脚本；先重新verify，确认phase=verified。备份目录本身与恢复目标分开，不能边下载边恢复。
3. 在新建且无用户工作负载的实例恢复原路径；常规GNU tar可按顺序拼接文件并解包。例如先在空的暂存目录做解包检查：`cat part-*.tarpart | tar -xpf - -C /mnt/restore-check`。该目录必须已经存在并有足够空间；绝对符号链接仍指向原绝对路径，暂存解包不是可运行环境。
4. 系统镜像已恢复匹配的miniconda时，只需恢复数据目录。成员实际带`root/autodl-tmp/emusician/...`或`root/miniconda3/...`前缀；先确认解包根与成员前缀映射，不可直接把整个归档解到/root/autodl-tmp/emusician而造成重复目录。归档未记录数据根目录本身，需预建该根并设为0700。如另行恢复runtime，应先核对系统依赖/驱动，不能覆盖正在使用的Python。保留Linux权限与所有软/硬链接；环境不能直接随意换绝对路径。
5. 先核对两个数据库PRAGMA integrity_check、模型锁与权重SHA、Python版本和关键import，再启动统一compute服务、检查protocol2和能力目录。最后才执行短样本CPU/GPU验证。
6. 新实例SSH主机/端口/密钥可能改变，更新本机SSH alias和compute注册连接；不要把旧PID/锁作为正在运行的服务状态。DAW使用本地资产的工程仍可离线打开。

本次目标是保住文件并验证完整性；未做整机/异机恢复、GPU推理或跨驱动兼容演练。后续可增加可复用恢复脚本与自动健康检查。

## 本次长传输

scripts/Resume-FullCloudBackup.ps1会检测同一备份的现有下载进程，无运行者时在隐藏窗口启动带记录的四路传输；不会自动开关云实例。保持本机运行/联网、云实例无卡开机，睡眠或断网可能中断。重新启动会续用.partial前缀，但完整块仍须SHA通过才发布；损坏前缀会重传该块。每条连接180秒无进展重试，最多3次，单次任务总上限48小时。

recovery-essentials.zip是优先下载的小型恢复资料，141个文件，包括部署/模型锁/环境描述/源码包/两个数据库快照；它不包含全部权重或已安装环境，不能替代85.42GB全量备份。两种验证收据分开记录。
