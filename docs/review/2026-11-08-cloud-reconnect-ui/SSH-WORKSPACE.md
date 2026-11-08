# VS Code 本地与云端工作区

本轮已验证命令行 SSH 能连接克隆后的新主机，端口为 `44800`，连接别名为 `emusician-autodl`。Remote-SSH 扩展已安装；这不代表当前 VS Code 窗口已经切换到了云端。

## 两个窗口分别做什么

| 窗口 | 打开的目录 | 用途 |
| --- | --- | --- |
| 本地 VS Code | `E:/MusicAgent&DAW/worktrees/audio-analysis` | DAW 源码、构建、Agent 接入和开发记录 |
| 远程 VS Code | `/root/autodl-tmp/emusician` | 云端模型、环境、任务服务及推理结果 |

两个窗口可以同时打开。远程目录仍在云端，打开它不会将整个目录下载到 E 盘；本地项目也不会因此自动同步过去。

## 打开云端窗口

最简单的方法：双击 `E:/MusicAgent&DAW/cloud-inference/Connect AutoDL Music.cmd`。此入口会以 `emusician-autodl` 新开远程窗口，并请求打开 `/root/autodl-tmp/emusician`。

也可以手动操作：

1. 在 VS Code 按 `Ctrl+Shift+P`，选择 **Remote-SSH: Connect to Host...**。
2. 选择 **emusician-autodl**，等待远程连接完成。
3. 选择 **File → Open Folder...**，输入 `/root/autodl-tmp/emusician`。
4. 查看左下角，应显示 **SSH: emusician-autodl**。普通本地窗口不会显示这个远程标识。

首次进入克隆实例时，VS Code 可能需要安装或准备远程服务；命令行 SSH 已通与远程编辑器准备完成是两项独立结果。

## 配置位置与 DAW 的关系

实际连接配置位于 `E:/MusicAgent&DAW/cloud-inference/connection/ssh_config`，由用户目录下的 `~/.ssh/config` 通过 `Include` 引用。以后主机地址或端口变化，更新实际配置文件中的对应项即可。本文不保存密码。

DAW 会自行建立访问云端模型服务的 SSH 隧道，不依赖 VS Code 的远程窗口。连接 VS Code 是为了查看和维护云端文件；关掉这个编辑器窗口不等于关掉云端实例，也不会替代 DAW 的云端服务配置。
