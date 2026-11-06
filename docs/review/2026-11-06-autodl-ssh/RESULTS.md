# VS Code Remote-SSH 与 E 盘档案（2026-11-06）

状态：**实际远程连接、文件备份下载与校验通过；模型推理及 DAW 云接口未部署**。

用户提供已运行的 AutoDL 实例连接信息，授权配置 VS Code SSH 并将最终本地数据放到 E 盘。本轮没有使用 computer-use，没有安装音乐模型、改动实时引擎、租新实例、关闭用户实例或调用付费语言模型。

## 已完成

- 本机已安装 Remote-SSH 0.128.0；实际 VS Code 1.144.1。
- 新建 `emusician-autodl` 别名；Windows 默认 `.ssh/config` 只前置 Include，原有三个主机条目保留。专用配置、固定主机公钥、私钥和配置回滚副本位于 `E:/MusicAgent&DAW/cloud-inference/`。
- 用户提供密码只用于首次连接和追加专用公钥；配置和脚本不保存该密码。使用独立 Ed25519 密钥，已验证 BatchMode 登录，开启严格主机公钥检查；私钥与连接配置 ACL 实际检查仅本机用户、SYSTEM、Administrators。
- VS Code 用户设置新增本主机 Linux 类型、远端 server 安装目录；固定 Windows OpenSSH 路径及90秒连接等待。其它原有设置逐项保持，未输出或存入公开档案。
- 已打开 VS Code 远程窗口。最新成功日志有 resolver resolved、forwarding server、tunneled port、exec server created/cached，无 Resolver error；不能仅凭 CLI 启动声称连通。
- 实际读取：RTX5090 / 32607MiB、驱动580.76.05、Python3.12.3、250GB数据盘。实际驱动以本次 nvidia-smi 为准，未沿用租用页面标注。
- 云端根 `/root/autodl-tmp/emusician`，含 workspace/models/jobs/results/experiments/manifests/cache/state/exports/tools/vscode-server 等目录。VS Code 编辑的是云端目录，**不会自动同步到 E 盘**。
- 本地根 `E:/MusicAgent&DAW/cloud-inference`；有远程/本地 code-workspace、`Connect AutoDL Music.cmd` 和 `Save Cloud Data.cmd`。
- 备份工具已实际运行：包含云端工作代码、模型、输入/任务/结果/评测/清单和工具，跳过缓存、环境、VS Code server、状态数据库及常见秘密目录/软链接；要求任务已停止写入，不提供活跃数据库一致性快照。
- 实际将3个基础验证文件打包、下载到 E 盘，归档大小/hash 与包内所有文件 SHA-256 检查通过；这是文件验证，不是 MIR/音频生成验收。[精确证据](VERIFICATION.json)
- 收口检查：部署工具与 scripts/cloud 源文件逐字一致，Python AST、PowerShell AST、两个 workspace/验证 JSON、git diff --check 通过；apps/core/src 无本轮变更。二次 BatchMode 检查确认远端 server 位于数据盘，验证清单存在。

## 使用入口

本地双击 `E:/MusicAgent&DAW/cloud-inference/Connect AutoDL Music.cmd` 进入远程开发；终端可用 `ssh emusician-autodl`。工作代码放远端 workspace，结果放 results，模型放 models。

任务完成后双击 `E:/MusicAgent&DAW/cloud-inference/Save Cloud Data.cmd`。备份写入 E 盘 backups 下新的时间目录，失败保留 `.partial`，验证成功才发布完整归档；云端原件保留，不自动关机/释放。完整模型若为外部符号链接需先导出独立文件；大模型归档需要额外云端磁盘空间。恢复演练与后续增量同步仍待做。

## 失败、修正与边界

1. E盘继承的未知 SID 权限被 OpenSSH 拒绝；对新建连接目录/秘密文件限定 ACL 后，解析配置和密钥登录通过。第一次 Set-Acl 对三个已有受限项出现 SeSecurityPrivilege 错误，其余项成功；最终读取关键私钥/配置 ACL，确认仅用户、SYSTEM、Administrators，未将该命令退出码误当作全部成功。
2. 非交互 SSH 中 `python3` 不在 PATH；实际解释器位于 `/root/miniconda3/bin/python`，已固定并真实重测。没有任意修改远端全局 PATH 或安装替代 Python。
3. 首次 VS Code 连接22秒等待超时，远端下载安装继续完成；固定客户端 OpenSSH、延长等待后，后续真实连接成功。原始 VS Code 日志留本机 APPDATA，不复制带潜在连接令牌的完整日志到公开 Git。
4. 初次远端 find 列举模板转义失败，未修改数据；最终通过受控 Python 与日志读取验证结果。

本轮无应用构建，因此不创建伪造的 docs/builds 成功记录。首次接入没有改 PyTorch/CUDA，现有2.5.1/cu124不作为5090推理就绪证据；后续需要兼容5090的独立模型环境、真实短样本和 GUI/Agent 候选闭环。没有把“SSH连通”写成模型/ASIO/DAW云功能完成。
