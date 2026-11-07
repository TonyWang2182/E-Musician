# 云端备份阶段结果（2026-11-07）

状态：云端完整快照生成通过、小型恢复资料本地校验通过；全量E盘下载与逐成员验证仍进行中，不能释放原实例。此记录不宣称全量完成。

## 已有证据

- 用户报告已保存AutoDL系统镜像并启用无卡模式；实际SSH恢复，cgroup0.5CPU/2GiB，磁盘原文件仍在。没有启动模型推理，也没有修改DAW。
- 完整快照`/root/autodl-tmp/emusician/exports/full-20261107T080330Z`：85,416,949,760字节，160块，311031成员（168451普通文件、23729目录、2668符号链接、116183硬链接）。云端capture从08:03:24至08:15:37 UTC，记录fe22aad7c2；归档时持有调度锁、保存双SQLite一致性快照。
- 范围含全部7个已接入模型、MERT2依赖和早期MIR文件；9环境、源码、激活链接、部署、结果、系统Python与wheel。当前清单里7模型＋MERT2＋基础MIR普通文件合计约37.56GB；环境和源码另计。排除凭据、旧备份、缓存、运行PID/锁/WAL等。
- 2668符号链接全部目标存在且落入备份范围；唯一editable源码ACE已包含。目录root/autodl-tmp/emusician本身未作为tar成员保存，恢复需预建0700，见RESTORE。
- E盘recovery-essentials.zip：5,590,138字节，141文件，SHA256 `0982d6565543ea19fa7aa62b632042957b5dadbec0e15a108b872c3bf3318a9d`；ZIP CRC、整包与逐文件SHA通过（fe9fd80c58）。这是配置/部署/源码包/环境描述与队列快照，不含完整环境和全部权重。
- 已下载82,192,946字节完整manifest，SHA `79eb27448b472395fcec59d5f127c2c83f6f5f05b431194330819d5ad284d496`；所有metadata侧文件SHA、九环境和模型目录覆盖、凭据路径排除通过（ec8e08883d）。两数据库integrity_check=ok，队列均终态。此检查仍不是85GB载荷核验。
- 最终CPU合成检查31/31通过（8fdcef873d）：WAL一致快照、运行任务拒绝、凭据排除、断线/损坏/续传、四并发上限、归档路径/链接/元数据/结束标记。

## 下载现状和运行方式

本地`E:/MusicAgent&DAW/cloud-inference/backups/full-20261107T080330Z`。单PIPE约0.106MB/s，四路直写探针0.760MB/s；暂停归档、Git SSH及AES128-GCM未解决慢链路，不能称显卡性能问题。完整下载预计长时间运行，实测波动很大，不承诺结束时刻。详细条件见TRANSPORT。

后台任务由Resume-FullCloudBackup.ps1启动，记录d7f62143f8。保留部分文件、断点续传、整片SHA后才发布；全量后自动验证逐成员SHA/类型/权限/链接及全部块，成功才写verification.json。目录内Check Backup.cmd查看进度，Resume Backup.cmd在无同类进程时重启。电脑需保持运行/联网，云端需继续无卡开机；本轮未改电源/睡眠设置，也没有开关或释放实例。

## 失败与变更留痕

- 初次4项capture测试2错误是SQLite连接上下文不自动close导致Windows临时目录占用；改为closing后4/4通过（5486753fe9→49a553f41f）。
- 首次远程命令非交互PATH无python，未进入capture（0ef3edaa53）；改绝对Python路径后，ffmpeg不在PATH导致metadata步骤失败（ffd999c7f9）。改为记录可选工具缺失，重试新目录成功；旧失败目录保留。
- 单PIPE下载因速度太慢主动终止所属进程（e52938d55c/fadfd752eb）；四路初版为增加.partial续传再次主动停止所属进程（dd4b7259fd/9203daaae0），未停止其他用户进程。后台最终版复用了已下载前缀。
- 原DEVLOG及10份原有未跟踪记录保留。代码维护分支，不合并main。

## 未完成

E盘全量块下载、全部载荷逐成员校验仍待后台任务结束。没有异机恢复、恢复后的模型GPU推理、物理音频或听感验收。AutoDL系统镜像仅用户报告完成，未通过平台API核验镜像内容。旧ACE21.5GB已验证备份继续保留。
