# E-musician

Windows 原生 DAW，使用 C++20、JUCE 和 Tracktion Engine。音频编辑、MIDI 编曲、插件宿主、工程保存和导出共用一套工程与控制接口；可选的编曲 Agent 通过同一接口提出并执行经确认的编辑。

**本分支：DAW 0.8.0 / Agent 0.3 第二批，实现和本批自动验收完成，待人工桌面短测。** 本批加入一份方案内的新轨→新片段→明确音符、片段复制/跨轨移动/裁剪/删除、音符增删和时长调整，以及规划暂停、顺序方案和执行阶段显示。本批结果以[验证记录](docs/verification/2026-10-29-agent-batch2/RESULTS.md)为准，真实界面、中文输入法和 ASIO 听感由用户按[人工检查](docs/review/2026-10-29-agent-batch2/MANUAL-CHECK.md)确认。

0.7.0 / Agent 0.2 的原生侧栏、选择上下文和双模型验证保留在[第一批历史证据](docs/verification/2026-10-29-agent-sidebar/RESULTS.md)，不作为0.8.0新增能力的通过证明。

保留0.6.1的1/16384网格、Ctrl+4吸附虚实线、三级小节标尺与深缩放，以及0.6.0剪贴板、循环跟随、节拍器、预备拍和资源/电平显示。旧录音、混合工程、性能与插件证据保持原版本范围，见[0.5交付档案](docs/verification/2026-10-27-v05/DELIVERY.md)。

新工程默认 **120 BPM、4/4**。不提供和弦工具、乐句模板或自带音源；MIDI 通过用户安装的 Windows x64 VST2/VST3 乐器发声。独立运行不需要 Ableton、模型服务或 API 密钥。

既有Keyscape兼容、录音音符时间边界和保存修复继续保留。新功能沿用同一个工程、命令接口及Undo；模型请求在独立非实时进程中执行。不提供自动保存和恢复。

## 打开与开发

在 VS Code 中打开当前功能分支工作树。原 `E:\E-musician` 和 `build/bin` 保留既有 DAW 入口；本批使用独立 `build/agent-batch2`：

```powershell
python scripts/dev_agent.py build
python scripts/dev_agent.py test
python scripts/dev_agent.py run
```

默认 Release，产物为 `build/agent-batch2/bin/Release/E-musician.exe`。本机入口为 `E:\MusicAgent&DAW\Start E-musician Agent.cmd`，工作树内为 `Start-Agent.cmd`。**等本批构建完成、准备人工验证时，由用户保存并关闭仍运行的0.7.0或其他旧版，再启动并确认标题栏为0.8.0。** 开发与离线测试不自动关闭旧窗口；旧窗口未关时，单实例机制可能把启动请求交给旧版。0.7.0的历史产物仍位于 `build/sidebar`。普通构建、F5 调试及固定依赖入口继续保留：

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

0.6.0工具栏把`bars / seconds / both`、`snap`、网格和`follow`分开。拖空白处框选片段，Ctrl+C/X/V复制/剪切/粘贴；Shift拖标尺选时间，Ctrl+L设循环。钢琴卷帘用`draw`或B开启单击画笔。Transport第二行提供click、音量/仅录音选项、独立count-in开关和1/2/4小节；从停止状态开始录音才预备倒数，Stop可取消。RAM显示进程工作集，DSP/xrun反映音频引擎，OUT/CLIP可清峰值。详细边界和按键见[快速上手](docs/QUICKSTART.md)。

Source 在底部查看选中音频源。真实分轨/转录、32 位插件桥接、侧链、插件任意多输出、comping、自动化 Touch/Latch/Write、TempoMap 和时间拉伸尚未实现。MP3 支持导入和播放，不支持导出。

## 原生编曲助手 0.3

点击工具栏 **Agent** 或 **Ctrl+Shift+A** 开关侧栏：读取当前工程/选择 → 提出具体方案 → 明确应用 → 回读检查。收起保留输入和任务；DAW 拥有独立模型 worker，助手断开不能关闭工程。默认“当前选择”，全局速度/新建轨等操作需明确切为“整个工程”；选区或工程变化会拒绝旧方案。

规划器当前有19种编辑动作，支持在一次确认中连续建轨、建片段并写入明确音符，也可复制/移动/裁剪/删除片段、添加/删除/移动音符、调整时长/音高/力度及量化。方案显示执行顺序和具体修改，作为一份原子批次提交，成功后可一步撤销。规划中可请求暂停，须等待在途模型请求返回；待确认方案可放弃，应用期间不能暂停或取消。“检查→提交→核对→完成”表示后端阶段，不表示逐条修改已经分别提交。

Kimi 与 OpenAI 适配器已实现，凭证按服务通过 Windows DPAPI 本机加密保存；Anthropic、Gemini、本地兼容服务仍预留。本机两套凭证已配置，无需重复提供。OpenAI 可沿用已有 loopback 代理，不改系统网络。界面的“已配置”只说明本地凭证存在；0.8.0的实际调用状态另见[本批验证记录](docs/verification/2026-10-29-agent-batch2/RESULTS.md)。启动、支持范围、数据和费用边界见[Agent 快速上手](docs/AGENT_QUICKSTART.md)；[0.1历史证据](docs/verification/2026-10-29-kimi-agent/RESULTS.md)仅覆盖旧伴随模式。

单方案最多16项动作、2000次音符处理，每个待编辑片段的完整读取上限为2000音符；同一音符被多次处理会累计计入。摘要之外的明确片段目标通过分页补齐，超限拒绝。裁剪只保留原片段内部区间；含CC等控制器事件的MIDI片段暂不允许由Agent裁剪。当前没有音频理解/生成、任意插件自动控制或长期自主任务，Agent也不能代替用户保存工程或删除磁盘文件。旧 `run_agent.py --exe PATH` 仍供独立浏览器伴随模式兼容使用。

## 工程与 Agent

schema 4 工程由 `.emproj` 和同名 `.assets` 目录组成，保存音频归档、MIDI 音符及控制器、片段、混音、插件状态、路由和曲线。移动工程时两者一起移动并保留名称关系。schema 1/2/3 可只读迁移，首次覆盖前保留旧清单备份。普通保存复用未变素材，后台完成文件事务；界面显示状态和结果，保存期间的新编辑仍保持未保存。保存后重开工程才切到归档素材绑定，删除原素材前先重开；旧素材代次与 MP3 PCM 缓存目前不自动清理。Undo 是进程内历史，不随工程重开恢复。

Agent 使用显式开启的本地 JSONL 通道，包含版本冲突保护、幂等请求、任务状态和分页读取：

```powershell
python scripts/agent_client.py --exe build/agent-batch2/bin/Release/E-musician.exe --demo build/agent-demo
```

此示例创建测试 MIDI、导出并验证撤销，不播放声音，也不属于产品乐句模板。协议和命令参数见 [AGENT_API](docs/AGENT_API.md)。

64 轨、4096 片段和 100,000 音符是输入限制，不能解释为任何插件负载下的性能承诺。性能结论以实际机器、设备缓冲、负载和测量报告为准。

插件扫描使用独立进程、超时和失败隔离；播放中的插件仍在宿主进程。统一扫描机制不能保证所有厂商、版本和音色均兼容，真实插件矩阵与失败证据单独记录。

## 项目文档

- [当前交付清单](docs/DAW_BASELINE.md) · [开发计划](docs/DEVELOPMENT.md)
- [实际架构](docs/ARCHITECTURE.md) · [固定依赖](docs/DEPENDENCIES.md)
- [当前状态与证据](docs/CONTEXT.md) · [追加式开发日志](docs/DEVLOG.md)
- [UI 规格](docs/UI_REFERENCE.md) · [用户参考原件](docs/design/references/README.md)

更新日期：2026-10-29。参考图中的 unit~ 是参考品牌，项目名保持 E-musician。
