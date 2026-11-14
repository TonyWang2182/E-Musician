# 0.13.3：克隆重连与工程入口修复

2026-11-14。维护分支 `fix/reconnect-file-icons-v0133`，基线 `912e68f`。原 0.13.2 和旧 E:/E-musician EXE 保留；用户工程未迁移、覆盖或用于自动编辑。新模型推理、真实声卡和听感由用户验收。

## 云端与编辑器

- SSH 别名 `emusician-autodl` 指向本次用户指定的 bjb1 主机、22095 端口；原密钥认证通过，没有使用或存储本次密码。连接配置备份位置见 [CONNECTION](CONNECTION.json)。
- 复用克隆目录 `/root/autodl-tmp/emusician`，固定 release `ed7d6a920487a651c988` 文件、九环境解释器、FFmpeg、两个 SQLite 完整性检查通过；RTX 5090 32 GB，启动 protocol 2 / loopback 18082 服务，七个云端能力返回 available。[云端证据](CLOUD.json)。没有重新上传或下载模型。
- 通过 DAW 使用的 SSH 隧道工具更新本地 compute registry，[隧道证据](LOCAL-TUNNEL.json)。最终 EXE 只读控制接口返回七个云端 Provider、四个本地 Provider 和六分轨选项；[原生投影](DESKTOP-CAPABILITIES.json)，记录 `9773306b76`。登记可用不等于本次推理成功。
- VS Code 新远程窗口已实际连接，标题含 `emusician [SSH: emusician-autodl]`；本地开发窗口及未保存编辑保持。远程目录、日志摘录见 [VSCODE](VSCODE.json)。没有把原来的本地窗口转换成远程工作区。

## 工程入口与轨头

实际 `.emproj` 打开路径仍是旧 E:/E-musician/build/bin，而非新维护版本。Windows 11 的 `UserChoiceLatest` 还引用 `Applications\E-musician.exe`，因此仅修改扩展名默认 ProgID 无法改变最终解析。本轮按用户注册新 ProgID，并维护属于 E-musician 的应用注册；受保护的 UserChoice / UserChoiceLatest 值不改动，关联变更先备份、冲突时拒绝恢复覆盖。Windows 最终解析验收见 [ASSOCIATION](ASSOCIATION.json)；注册过程、失败和恢复边界见 [图标记录](icon/RESULTS.md)。

工程文件图标引用 EXE 中既有树乐师 Logo；CLI 与单实例转交补齐文件路径分派，复用未保存／录音保护及异步 `open_project` 命令。普通参数和含空格／& 的路径有回归检查，实际保存测试工程后异步打开成功。没有改动音频实时回调或直接写入第二套工程状态。

M/S/R 三个固定字母使用禁用省略号的紧凑绘制，保留按钮背景、焦点、开关和命令语义。真实组件的 72 个缩放／状态／主题组合通过，图像已查看；[UI 复核](ui/RESULTS.md)。这些是离屏渲染检查，不声称物理显示缩放与鼠标已经验收。

## 构建与检查记录

| 检查 | 结果与原始记录 |
|---|---|
| 首次 Release | 成功，`e3a71b29ba` |
| 首轮完整 CTest | 10/11，通过 engine.integration_smoke；workspace 新工程打开测试失败，`bbc82c6f3e` |
| workspace 原因与修复 | 测试把已排队的异步打开误当完成；仅增加有界任务等待及状态诊断，未改生产路径 |
| 第二次 Release | 成功，`7b242e79f9`；128 项原生输入与首次相比仅 `tests/MainWorkspaceSmoke.inc` 有变化 |
| workspace 针对性复测 | 1/1 通过，`277453f89c`；真实 open job completed，错误为空 |
| 注册脚本首轮 | 9 项通过；增加真实隔离 HKCU 往返后发现空 REG_NONE 表示差异，修正后 10 项通过，`7af994fa19`。失败与精确夹具清理记录保留 |
| Windows 11 关联补查 | 首次写入后实际解析仍指旧EXE，补齐自有应用注册；最终12项回归通过，`8afb78256b`，实际关联更新成功，`b074de8ef0`，受保护用户选择未变 |
| 最终原生能力读取 | 通过，`9773306b76`；没有调用模型或音频设备 |
| 正式启动 | 标题 0.13.3、窗口响应、DAW 所属 Agent helper 认证连接与 ready 消费通过，`17e8b5ca71`，[STARTUP](STARTUP.json) |

完整 CTest 没有在第二次构建后再跑一遍；这是首轮 10 项通过，加修正测试后的第 11 项通过。原生输入清单和独立复核明确记录了这个边界。最终整合核对见 [VERIFICATION](VERIFICATION.json)，原始命令及时间在 `docs/builds`，原始日志在忽略目录 `build-logs`。

执行关联补丁时曾有一条命令因E盘路径含未引用的`&`被PowerShell解析拒绝；未启动Python或写注册表。引用完整路径后执行成功。最终核对 `9969290e6b` 通过128项源码、旧EXE、启动入口、原生能力和Windows有效关联。

## 交付与下一步

新版入口 `E:/MusicAgent&DAW/Start E-musician 0.13.3.cmd`；EXE `E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe`；本地 VS Code 工作区 `E:/MusicAgent&DAW/E-musician-0.13.3.code-workspace`。应用已打开；不根据启动状态推断设备能发声。

用户按[人工清单](MANUAL-CHECK.md)验收工程文件图标／双击版本、S/M/R、普通 Agent Apply/Undo，以及各模型短段效果。完整[Agent 与模型清单](CAPABILITIES.md)区分已经开放和仍需手动的操作。当前不做新一轮付费 API／GPU 任务，不宣称之前未通过的第三方插件在本轮得到修复。

Git 工作分支保留，不自动合并 main；发布状态以本轮 PUBLISH 记录为准。
