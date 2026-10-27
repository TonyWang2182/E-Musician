# E-musician

Windows 原生 DAW，使用 C++20、JUCE 和 Tracktion Engine。本轮先把音频编辑、MIDI 编曲、插件宿主、工程保存和导出做成可直接操作的基础，并给后续 Agent 提供同一套控制接口。

**0.5.0 基础编曲版本已通过本轮指定回归及30分钟持续播放检查，交付摘要见 [DELIVERY](docs/verification/2026-10-27-v05/DELIVERY.md)。** 下述是当前代码的功能入口，具体设备、插件和性能以实测范围为准；最新上下文见 [CONTEXT](docs/CONTEXT.md)。

新工程默认 **120 BPM、4/4**。不提供和弦工具、乐句模板或自带音源；MIDI 通过用户安装的 Windows x64 VST2/VST3 乐器发声。独立运行不需要 Ableton、模型服务或 API 密钥。

当前修复分支为 **0.5.1 Keyscape兼容候选**：Release构建及相关自动检查通过，用户已确认MIDI编写、播放与Keyscape使用正常；Arm/Monitor切换和实体键盘输入仍待分项确认，见[候选记录](docs/verification/2026-10-27-v051/RESULTS.md)。下方0.5证据保留原版本范围，不等同于候选已验收。

## 打开与开发

在 VS Code 中打开 `E:\E-musician`。首次准备依赖后，按 **F5** 构建并调试；**Ctrl+Shift+B** 只构建。

```powershell
python scripts/dev.py bootstrap --note "准备固定依赖"
python scripts/dev.py check --config Debug --note "验证本轮修改"
python scripts/dev.py run --config Debug --note "启动编辑器"
```

优化构建使用 `--config Release`，产物为 `build/bin/Release/E-musician.exe`。日常操作见 [快速上手](docs/QUICKSTART.md)，设备设置、构建和测试入口见 [BUILDING](docs/BUILDING.md)。所有构建与测试经过日志脚本，失败也保留；项目约定见 [AGENTS.md](AGENTS.md)。

## 基础操作

- **音频**：`add...` 导入 WAV/MP3。主编曲显示多轨片段；移动、跨同类轨拖放、多选、边缘裁剪，通过 `edit` 分割、复制、删除，片段属性设置源偏移和淡入淡出。原音频不会被这些编辑改写。
- **MIDI**：在 `add...` 菜单创建 MIDI/instrument 轨及 MIDI 片段，或导入 `.mid`。双击 MIDI 片段打开底部钢琴卷帘，编辑音高、起点、长度、力度、量化和 16 步鼓点。
- **插件**：选轨后进入 `devices → add plug-in...` 扫描已安装插件，向轨道或 master 加载乐器/效果器，调整顺序、旁通并打开原生窗口。没有加载可用乐器的 MIDI 轨不会发声。
- **混音与时间**：轨道增益、声像、mute/solo；底部播放、暂停、停止和循环；BPM 按钮设置固定速度、拍号及循环区间。音频保持原速，MIDI 按拍跟随速度。
- **录音**：音频设置选择实际设备；选轨的 I/O 面板选择音频或 MIDI 输入，轨头 R 预备，底部 Record 开始、Stop 收尾。监听按输入设备共享，可设 off/auto/on；新工程和重开默认关闭。一次 Undo 撤销本次录制，Redo 恢复。
- **路由与自动化**：添加 Bus，选轨设置输出及 pre/post-fader 发送；Automation 编辑轨道、主输出或插件参数曲线。播放和导出使用同一原生引擎曲线，反馈回路会被拒绝。
- **工程与输出**：`save/open` 保存重开 `.emproj`；`export` 导出全工程或范围 WAV、工程或选中 MIDI。文件任务显示进度并可取消，普通编辑继续使用同一个活动工程。

Source 在底部查看选中音频源。真实分轨/转录、32 位插件桥接、侧链、插件任意多输出、comping、自动化 Touch/Latch/Write、TempoMap 和时间拉伸尚未实现。MP3 支持导入和播放，不支持导出。

## 工程与 Agent

schema 4 工程由 `.emproj` 和同名 `.assets` 目录组成，保存音频归档、MIDI 音符及控制器、片段、混音、插件状态、路由和曲线。移动工程时两者一起移动并保留名称关系。schema 1/2/3 可只读迁移，首次覆盖前保留旧清单备份。普通保存复用未变素材，后台完成文件事务；界面显示状态和结果，保存期间的新编辑仍保持未保存。保存后重开工程才切到归档素材绑定，删除原素材前先重开；旧素材代次与 MP3 PCM 缓存目前不自动清理。Undo 是进程内历史，不随工程重开恢复。

Agent 使用显式开启的本地 JSONL 通道，包含版本冲突保护、幂等请求、任务状态和分页读取：

```powershell
python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --demo build/agent-demo
```

此示例创建测试 MIDI、导出并验证撤销，不播放声音，也不属于产品乐句模板。协议和命令参数见 [AGENT_API](docs/AGENT_API.md)。

64 轨、4096 片段和 100,000 音符是输入限制，不能解释为任何插件负载下的性能承诺。性能结论以实际机器、设备缓冲、负载和测量报告为准。

插件扫描使用独立进程、超时和失败隔离；播放中的插件仍在宿主进程。统一扫描机制不能保证所有厂商、版本和音色均兼容，真实插件矩阵与失败证据单独记录。

## 项目文档

- [当前交付清单](docs/DAW_BASELINE.md) · [开发计划](docs/DEVELOPMENT.md)
- [实际架构](docs/ARCHITECTURE.md) · [固定依赖](docs/DEPENDENCIES.md)
- [当前状态与证据](docs/CONTEXT.md) · [追加式开发日志](docs/DEVLOG.md)
- [UI 规格](docs/UI_REFERENCE.md) · [用户参考原件](docs/design/references/README.md)

更新日期：2026-10-27。参考图中的 unit~ 是参考品牌，项目名保持 E-musician。
