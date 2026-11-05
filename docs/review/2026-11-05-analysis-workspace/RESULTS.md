# 0.9.1 分析工作区交付记录

2026-11-05。状态：已实现，Release、自动回归、真实本地模型导入与 Agent 六轨整链已通过。实际鼠标/DPI、ASIO 共存和音乐质量待人工验收。

## 使用

入口：`E:/MusicAgent&DAW/Start E-musician 0.9.1 Analysis.cmd`，窗口标题应为 **0.9.1**。实际程序在 `E:/emusician-analysis-build/bin/Release/E-musician.exe`，VS Code 打开仓库的 `E-musician-Analysis.code-workspace`。本轮不自动打开或控制用户桌面。

- **和弦**：分析并点 Add chord track 后，编曲区标尺下有独立和弦轨；关闭分析下栏仍可见，双击区域可修正。多次分析可选择来源。
- **分离/MIDI**：下栏显示波形或矩形音符；确认添加后使用普通音频/MIDI 轨。新 MIDI 轨仍需选择乐器才能发声。
- **改名**：选中轨道标题有 rename；也可双击名称、F2 或右键 Rename。所有入口共用工程命令与 Undo。
- **语言**：Settings → Language → English / 简体中文，立即切换并记忆。工程名、轨名、素材名、插件界面和模型原话不被改写。
- **分析配置**：四/六轨、Fast/Quality；转录可选乐器音域；和弦增加常用七和弦等词表。时间范围与阈值在 Options，日常界面不展示内部评分和长报告。

短步骤见 [MANUAL-CHECK](MANUAL-CHECK.md)。0.8.1 独立程序和入口保留；0.9.0 保留在发布归档。旧 0.9.0 Analysis 启动脚本与新脚本指向同一个分析构建目录，因此会打开当前候选，不能当作独立旧版程序。

## 实现与质量边界

音乐权威状态仍由原工程控制层持有；和弦轨是只读快照投影，修改通过命令提交。后台 Worker 计算固定 128 点波形，原生绘制不解码音频；音符/和弦预览分页，和弦轨按可见时间范围裁剪。语言切换不修改工程、不重建音频图、不重启 Agent。模型推理、文件和 JSON 工作不进入音频回调。

真实六轨采用固定官方 HTDemucs-6s，可分 vocals、drums、bass、piano、guitar、other；钢琴串音和伪影仍是模型已知限制。Quality 增加重叠和两次移位平均，只表示更高计算量配置，没有证明每首歌更好。转录仍为同一 Basic Pitch ONNX，乐器选项调整音域。和弦是自有 Chroma/Viterbi 确定性模板，从 24 扩到 132 类 + N；没有新增训练式爵士模型、转位或 9/11/13 识别。模型来源、SHA、运行环境与真实短音乐探针见 [WORKER-NOTES](WORKER-NOTES.md)。

Agent 的手动/自动入口复用候选、参数、权限、一次导入及回读；不会把波形或大量音符发给聊天模型。当前和弦块的界面选择尚未加入 Agent 通用 selection_context，Agent 仍按源片段读取和修正。鼓转录、主/和声人声、主/节奏吉他和五线谱不在本次范围。

## 原生最终证据

EXE SHA-256：`a91c63949e1cc41cd7a6496f31db67477c3efd663fefee76a0947614135e04dc`。固定 JUCE 8.0.6 `19edd538429c93d277bf95b55aaa7e3eb545f951` / Tracktion Engine 3.2.0 `b0c7dd090a56b27fe01bb394617891906eb34daf`，Windows x64 Release。安全源目录联接用于避开 MSBuild 的 `&` 路径限制；不修改上游版本。

| 检查 | 结果 | 记录 |
|---|---|---|
| 最终 native build | 成功，175.74 秒 | [104159](../../builds/20261105T104159.651514Z-f59e181ba3.json) |
| CTest | 10/10，119.90 秒；包括原生 UI、语言不改工程/播放/设备、和弦快照/编辑及既有 DSP/工程回归 | [104645](../../builds/20261105T104645.093782Z-ae1748427c.json) |
| 真实 DAW + 本地模型 | 9/9 组；六轨真实分离、MIDI、扩展和弦、导入幂等、Undo/Redo、来源过期、保存重开/并发、MP3、取消；受保护工程/设置未变 | [104917](../../builds/20261105T104917.549319Z-17a2eace8e.json) / [报告](NATIVE-E2E.json) |
| Worker | 28 单测、12 真实进程边界、三种真实 Worker 和公开音乐探针 | [Worker 证据](WORKER-NOTES.md) |
| Agent 网页 | 四种最终 headless Edge 夹具、语言往返、草稿/用户文本保留、七类能力状态、零 JS 错误 | [104055](../../builds/20261105T104055.187269Z-86a76688f0.json) / [语言记录](I18N-NOTES.md) |
| Agent 全回归 | 275/275，104.49 秒；含 30 项分析与四/六轨实际数量回读 | [105454](../../builds/20261105T105454.915941Z-3087c73fd3.json) |
| Agent 真实宿主整链 | 12/12 组，51.99 秒；真实本地和弦、六轨分离与最终 DAW，模拟语言模型；确认后回读、一次 Undo/Redo、保存重开及角色保留 | [105445](../../builds/20261105T105445.111267Z-f2416f8e6f.json) / [报告](AGENT-E2E.json) |

实际原生组件渲染已检查英文/中文 1000×650 工作区、和弦与 MIDI 图形候选及 540×210 小面板；图形候选/和弦示例明确为 synthetic 夹具，不能当作真实识别结果截图。真实模型另由上表整链验证。截图与源码一致性详见 [UI-VERIFICATION](UI-VERIFICATION.json)；原生 WebView、物理屏幕 DPI 和人工鼠标操作仍待验收。[英文工作区](screenshots/ui-analysis-workspace-en-1000x650-synthetic-chords.png) / [中文工作区](screenshots/ui-analysis-workspace-zh-1000x650-synthetic-chords.png)。

原生构建、CTest 和真实模型 E2E 使用同一原生输入与二进制，整仓指纹当时为 `85a83842379a3c622b84598f96efe2e53bedb08a1c703171bb2a9e5dd24ef9e7`；随后只修正 Agent Python 六轨回读并补两个测试文件。最终 190 个源码输入为 `f58b075d0a5bef535899599382ad368ac41cf2058d02a1c07f5e75e6e2ec7b5d`，最终 Agent 两项记录期间冻结。原生、Worker 和网页文件未再改变，无需为 Python 修改重复编译原生。分阶段逐文件核对见 [VERIFICATION](VERIFICATION.json)。原始命令、配置、时间、失败、日志路径全部保留在 docs/builds 与 append-only DEVLOG。

## 发现和修复

- 初次构建发现 JUCE F2 常量及 StringArray 访问不匹配，修复后重新构建；失败记录 `102623-2598f6977d` 保留。
- 初次界面测试虽通过，但看实际截图发现部分中文乱码：源字面量经 JUCE ASCII 构造器误解码。补显式 UTF-8 重载、语义断言和即时面板刷新；重新构建后的截图中文正常。也修正 ComboBox 更新标签时丢当前选项的问题，切换语言不触发输入/监听命令。
- 第一次真实六轨导入失败：存储校验只允许四种 analysisRole。补 piano/guitar 后整链通过，失败记录 `103839-b55aae2cb1` 保留；没有丢弃拒绝校验来绕过问题。
- Agent 计划编译最初只接受四轨，显式乐器参数还会在重新授权时丢失；已统一四/六轨、预算、标签和配置。最后独立审查又发现完成回读硬编码四轨，补充 runtime 和真实六轨 Agent 测试。
- 构建输出仍有上游可选 `pwsh.exe` 不存在提示，MSBuild 退出码为 0，EXE 与后续 CTest/真实模型链成功；未据此宣称安装打包步骤通过，原输出不隐藏。

## 性能与剩余验收

本机 i7-13700H / 约 32GB / RTX 3050 Laptop 4GB / 驱动 555.99，离线 Worker 两条 CPU 线程，7 秒 44.1kHz 双声道合成输入，六轨 Quality 墙钟 28.58 秒，采样峰值 RSS 1.28GB、CUDA allocated 650MB / reserved 912MB。方法、版本和限制在 Worker 记录中。没有实际声卡缓冲和同时 ASIO 播放负载，不能推导实时稳定性或识别准确率。

下一步按人工短测确认轨道可见、改名、语言、短音乐听感和真实设备播放共存。本轮没有付费 LLM 请求，没有操作用户电脑界面；聊天模型的实际意图理解尚未验证。旧工程、凭证和模型权重不进入 Git；新模型权重的再分发许可未确认，仅本机评测部署。
