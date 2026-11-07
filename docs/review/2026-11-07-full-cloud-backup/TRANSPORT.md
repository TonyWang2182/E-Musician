# 完整云备份传输诊断与续传

日期：2026-11-07。远端备份 `full-20261107T080330Z`；本地目标为 `E:/MusicAgent&DAW/cloud-inference/backups/full-20261107T080330Z`。本文件记录传输机制和局部实测，不代表完整备份已经下载或恢复通过。

## 有界传输探针

条件：Windows 本机，经既有 `emusician-autodl` SSH 别名读取同一已完成分片；远端为用户已开启的 AutoDL 无 GPU 模式。主任务观察到约 0.5 CPU 配额。没有模型加载、推理、网络设置变更或公开上传。每项最多运行 30 秒，超时只结束探针自己启动的 SSH 子进程。MB/s 使用十进制字节；这些短样本不构成长期带宽保证。

| 方法 | 请求量 | 实收字节 | 秒 | MB/s | 结果 |
|---|---:|---:|---:|---:|---|
| Windows SSH，stdout 直接写文件 | 16 MiB | 7,700,480 | 30.032 | 0.256 | 超时，保留部分文件 |
| Windows SSH，PIPE 经 Python 256 KiB 读取写盘 | 16 MiB | 3,178,496 | 30.023 | 0.106 | 超时，保留部分文件 |
| 暂停备份 producer 后，Windows SSH 直接写文件 | 16 MiB | 2,916,352 | 30.017 | 0.097 | 超时，producer 已恢复 |
| 四路 Windows SSH 直接写文件 | 每路 8 MiB，共 32 MiB | 22,937,600 | 30.179 | 0.760 | 一路完成，其余三路超时 |
| Git SSH，显式既有 SSH 配置 | 16 MiB | 3,833,856 | 30.052 | 0.128 | 超时 |
| Windows SSH，`aes128-gcm@openssh.com` | 16 MiB | 2,850,816 | 30.039 | 0.095 | 超时 |

暂停试验只在核对 `/proc/1363/cmdline` 为本次 producer 与准确备份目标后发送 SIGSTOP；另设独立 35 秒 SIGCONT 看门狗，并在本地 `finally` 中再次恢复。没有暂停其他进程。该结果不支持“producer CPU 竞争是主要瓶颈”的判断。更换 SSH 实现或密码套件未表现出实质收益。

原始探针产物保留于忽略目录：

- `build/backup-transport-probe-uw3a20bg/`：最初 direct/PIPE 部分文件，数值见本表与工具执行记录。
- `build/backup-throughput-diagnosis-kfujbzjq/results.json`：暂停与四路试验；同目录保留各部分文件。
- `build/backup-ssh-client-probe-wxkm_b2q/results.json`：Git SSH 与 AES128-GCM；同目录保留 stderr 和部分文件。

主任务随后观察到生产四路约 33.4 MB/60 秒，约 0.55 MB/s。85.42 GB 按该短时速率估算约 43 小时，但不承诺最终耗时，也不把短探针的 0.760 MB/s 当作全程速率。

## 下载与断点续传

`scripts/cloud/pull_full_backup.py pull --direct-file --workers 4` 最多并行四个分片。SSH 将数据直接写入各自 `.partial`，完成后用 256 KiB 缓冲重新读取并核对整个分片 SHA-256；只有大小和 SHA 全部一致才原子改名为正式分片。

同一目标目录的 `source.json` 固定 SSH 别名和远端备份根。重新运行时，已经通过整片 SHA 的正式文件复用；未完成的普通 `.partial` 按本地长度续传。远端使用 `dd iflag=skip_bytes skip=<已验证非负字节数>` 从不可变的同一分片偏移处继续，现有前缀不会重新发送。前缀尚未单独证明正确，最终整片 SHA 仍是必要条件。

完整分片的 SHA 不符时，仅截断该任务拥有的 `.partial` 并从零重试；不改动已验证正式文件。过长的部分文件同样不能作为合法前缀。断线或 180 秒没有新增字节时，保留已经收到的前缀并重试，每个分片最多三次尝试。主循环有默认 48 小时总时限；失败或时限到达后可在同一目录再次运行。重启前必须先结束旧下载进程及其所属 SSH 子进程，避免同时写同一部分文件。

传输后还会验证 manifest、inventory、system、links sidecar，以及拼接 raw tar 的全部成员、类型、权限、链接元数据、文件 SHA、分片 SHA 和结尾填充。验证不解包，不等于异机恢复通过。

## 合成检查

命令：`python -m unittest discover -s tests -p test_full_backup_transport.py -v`。

最新版 27 项通过，包括断线前缀续传、已有前缀不重发、损坏前缀整片 SHA 失败后从零重试、180 秒停滞终止所属子进程、四路上限及乱序完成后的有序 tar 验证、sidecar 损坏、逃逸链接、缺失 hardlink 目标、重复成员和隐藏尾部。均为本地合成测试，不访问生产云服务。
