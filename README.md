# E-musician

Windows 原生 DAW，使用 C++20、JUCE 和 Tracktion Engine。音频编辑、MIDI 编曲、插件宿主、工程保存和导出共用一套工程与控制接口；可选的编曲 Agent 通过同一接口提出并执行经确认的编辑。

**当前维护候选0.13.3已打开：新克隆云主机/VS Code已连接，工程Logo图标及双击旧版入口已修复，M/S/R固定标签不再省略。** 两次Release成功，首次完整CTest10/11、修正异步测试等待后workspace1/1通过，72项渲染和12项文件关联检查通过。窗口与Agent本地认证已验证；本次无模型推理或设备听感验收。入口`E:/MusicAgent&DAW/Start E-musician 0.13.3.cmd`，本地开发工作区`E:/MusicAgent&DAW/E-musician-0.13.3.code-workspace`；旧程序保留。

[本轮结果](docs/review/2026-11-14-reconnect-icons/RESULTS.md) · [人工测试](docs/review/2026-11-14-reconnect-icons/MANUAL-CHECK.md) · [Agent和云端/本地模型清单](docs/review/2026-11-14-reconnect-icons/CAPABILITIES.md) · [4分钟中英分镜与素材清单](docs/demo/2026-11-12-four-minute-demo.md)。以下为历史版本记录，云端当前连接以0.13.3为准。

**当前维护候选0.13.2已打开：插件入口生命周期、M/S/R文字与Agent基础混音修复。** 最终Release、CTest11/11、Agent371和两项真实GPT方案通过；53个已发现模块累计45完整宿主路径通过、8项仍有问题，逐项限制见[本轮结果](docs/review/2026-11-08-plugin-agent-stability/RESULTS.md)。真实ASIO、原COZY事故和听感待人工验收，没有完整整曲自动混音能力。入口`E:/MusicAgent&DAW/Start E-musician 0.13.2.cmd`，本地VS Code打开`E:/MusicAgent&DAW/E-musician-0.13.2.code-workspace`。0.13.1原生程序、入口和工程保留。

[本轮计划](docs/review/2026-11-08-plugin-agent-stability/PLAN.md) · [人工短测](docs/review/2026-11-08-plugin-agent-stability/MANUAL-CHECK.md) · [实际模型分工](docs/review/2026-11-08-plugin-agent-stability/MODEL-MAP.md) · [Agent评测与混音步骤](docs/review/2026-11-08-plugin-agent-stability/agent/README.md)。云端模型部署本轮未改，上一版本的重连与七模型验证如下。

[本轮结果](docs/review/2026-11-08-cloud-reconnect-ui/RESULTS.md) · [七模型测试](docs/review/2026-11-08-cloud-reconnect-ui/MODEL-TESTS.md) · [英文演示脚本](docs/review/2026-11-08-cloud-reconnect-ui/DEMO-SCRIPT.md) · [远程SSH工作区](docs/review/2026-11-08-cloud-reconnect-ui/SSH-WORKSPACE.md)。以下版本与备份条目为历史记录；克隆接通不代表夸克归档已做全量恢复验证。

云端备份进度：双击 `E:/查看备份进度.cmd` 查看自动更新的百分比、余量和校验状态；关闭窗口不停止下载。[使用与验证](docs/review/2026-11-07-backup-monitor/RESULTS.md)。

**保留候选 0.13.0：统一云端计算与七模型接入，自动验证通过、人工待验。** 分析支持 Auto/Local/Cloud 与模型选择；SCNet、TransKun、ChordMini、MuScriptor、SheetSage2 的结果可预览、确认入轨、撤销、保存与离线重开，保留踏板、乐器通道、原和弦标签、拍点和段落。生成可选 ACE／YuE2，明确提示长度预算截断。Agent 使用相同命令和候选。Release、CTest11/11、Agent349及七模型真实短段整链通过，物理声卡与听感仍需人工验收。[结果](docs/review/2026-11-07-hybrid-pipeline/RESULTS.md) / [最终人工清单](docs/review/2026-11-07-hybrid-pipeline/MANUAL-CHECK.md)。

双击 `E:/MusicAgent&DAW/Start E-musician 0.13.0 Hybrid.cmd`，确认标题0.13.0。新缓存和临时文件在E盘，模型权重仍在云端；旧版本和工程保留。下方条目均为历史版本状态。

**0.12.1 候选：生成默认值和分析故障保护（自动验证通过）**。Agent 自动沿用工程速度/拍号/播放头；本地分离增加提交内存准入、进程树隔离、可见错误，禁止 CUDA OOM 后同进程盲目切 CPU。Release、CTest11组、Agent334、Worker回归及一次真实GPT决策通过；真实短分离因资源不足未启动，原75秒六轨及ASIO仍待验。启动 `E:/MusicAgent&DAW/Start E-musician 0.12.1 Stability.cmd`；[结果](docs/review/2026-11-06-generation-stability/RESULTS.md) / [人工短测](docs/review/2026-11-06-generation-stability/MANUAL-CHECK.md)。云端MIR正在独立准备，当前尚不能自由切换本地/云端。

**0.12.0 候选：云端音乐生成（真实整链及E盘完整备份校验通过）**。ACE文字/歌词生成、手动下栏和Agent共用候选接口；试听后明确加入新轨，保存时携带本地音频。真实5090推理、原生及GPT-5-mini/ACE闭环、保存重开/离线渲染已验，Agent325项回归通过。人工听感/ASIO仍待验。状态见 [当前上下文](docs/CONTEXT.md)，操作见 [人工短测](docs/review/2026-11-06-cloud-generation/MANUAL-CHECK.md)；旧0.11程序保留，YuE2和MIR升级属后续批次。

**0.11.0：易乐师品牌与工作区（自动验证通过，人工待验）**。树乐师 Logo 用于启动、Windows 图标和左上角；新的浅色工作区、搜索库、顶部播放控制、可调整装置下栏与连续调参。轨道右键 → Track colour 染色，颜色支持保存/Undo及 Agent。启动 `E:/MusicAgent&DAW/Start E-musician 0.11.0 Workspace.cmd`，旧0.10.0保留。Release、CTest11/11、Agent300、离线闭环与组件截图已验；真实设备/鼠标/听感按 [人工短测](docs/review/2026-11-06-workspace-brand/MANUAL-CHECK.md) 确认。[结果](docs/review/2026-11-06-workspace-brand/RESULTS.md) / [设计规范](DESIGN.md)。

**0.10.0 节拍与 Warp（2026-11-05，自动验证通过，人工待验）**：可选播放头视图跟随；真实节拍分析、BPM/拍号/首拍修正；Source 固定比例保音高拉伸；Agent 等价方案与确认回读；新的 Save/Settings 和情境右键。保留原件及 0.9.1 程序，局部 Warp 点和变速 Tempo Map 尚未实现。入口 `E:/MusicAgent&DAW/Start E-musician 0.10.0 Tempo.cmd`。[结果](docs/review/2026-11-05-tempo-warp/RESULTS.md) / [人工短测](docs/review/2026-11-05-tempo-warp/MANUAL-CHECK.md)。

**0.9.1 分析工作区（2026-11-05）**：和弦结果在编曲区显示为和弦轨，分离和转录结果添加到普通音频/MIDI 轨。下栏显示波形、音符和和弦预览；Settings → Language 切换 English / 简体中文。轨道标题旁 rename、双击名称、F2、右键均可改名。分析新增可选四／六轨和品质档、乐器音域、七和弦等常用类型；具体算法和识别局限见 [Worker 记录](docs/review/2026-11-05-analysis-workspace/WORKER-NOTES.md)。

新入口：`E:/MusicAgent&DAW/Start E-musician 0.9.1 Analysis.cmd`，确认窗口标题 0.9.1；[人工短测](docs/review/2026-11-05-analysis-workspace/MANUAL-CHECK.md)。本轮工作树同下，新分支 `feature/analysis-workspace-v091`；构建/测试证据见 [结果](docs/review/2026-11-05-analysis-workspace/RESULTS.md)。旧 0.8.1 程序与 0.9.0 发布归档保留，未自动合并 main。以下 0.9.0 为历史基线。

**历史基线 0.9.0：本地音频分析（2026-11-05）**。顶部 `analyze` 打开下栏：HTDemucs 四轨分离、Basic Pitch 有音高音频转 MIDI、Chroma/HMM 大小三和弦识别。真实模型在独立本地进程运行，先生成候选，明确导入后才修改工程；手动与 Agent 共用接口。支持取消、来源检查、一次 Undo/Redo、保存重开，Agent 固定能力清单同步更新。**识别质量、实际 ASIO 与鼠标听感仍需人工验收。** [本轮结果](docs/review/2026-11-05-audio-analysis/RESULTS.md) / [人工短测](docs/review/2026-11-05-audio-analysis/MANUAL-CHECK.md) / [模型来源与本机测量](docs/review/2026-11-05-audio-analysis/WORKER-RESULTS.md)。

原 `Start E-musician 0.9.0 Analysis.cmd` 与新入口指向同一个分析构建目录，现在会运行 0.9.1；0.9.0 的独立 EXE/源码保留在发布归档。模型、隔离运行库和候选缓存位于 `E:/MusicAgent&DAW/analysis/`，不进入 Git。旧版 0.8.1 程序及入口保留。

**保留版本 0.8.1（2026-11-05）**：MIDI 音符与 clip 改为全行矩形；现有七种原生装置增加统一旋钮/图示，Sampler/Rack 增加 AR 和播放模式，EQ 每段可选六种形状，新声音参数支持 Agent。启动 `build/device-chain/bin/Release/E-musician.exe`，本机亦可双击 `E:/MusicAgent&DAW/Start E-musician 0.8.1.cmd`，检查标题版本。Release、CTest 10/10、Agent Python 245 和离线联测通过，实际桌面与设备听感待人工；[结果/截图](docs/review/2026-11-05-device-controls/RESULTS.md) / [人工短测](docs/review/2026-11-05-device-controls/MANUAL-CHECK.md)。新非默认装置状态使用版本 2，旧版会拒绝；旧程序备份保留。

**历史候选（2026-11-02）**：下方有序设备链、原生面板轮询修复、增强的压缩器、原创 Delay/Reverb/Auto Filter 和 Agent 装置参数接口。[结果与限制](docs/review/2026-11-02-device-chain-agent/RESULTS.md) / [Agent 测试手册](docs/review/2026-11-02-agent-diagnostics/README.md)。此前提及的完整合成器和商业级装置尚未完成；当前 `build/device-chain` 入口已更新为上方 0.8.1。

**历史候选（2026-11-02，试听/效果器）**：增加采样试听、波形优化、原生八段 EQ 与压缩器及相应 Agent 操作。使用独立的 `build/audition-effects/bin/Release/E-musician.exe`，双击后可用 Agent 按钮打开助手；不要用旧版覆盖包含新装置的工程。自动测试与真实设备限制见[本轮结果](docs/review/2026-11-02-audition-eq-compressor/RESULTS.md)，人工操作见[检查步骤](docs/review/2026-11-02-audition-eq-compressor/MANUAL-CHECK.md)。以下旧批次说明保留作为历史及其他构建入口。

**历史：DAW 0.8.0 / Agent 0.3 第二批，实现和本批自动验收完成，待人工桌面短测。** 本批加入一份方案内的新轨→新片段→明确音符、片段复制/跨轨移动/裁剪/删除、音符增删和时长调整，以及规划暂停、顺序方案和执行阶段显示。本批结果以[验证记录](docs/verification/2026-10-29-agent-batch2/RESULTS.md)为准，真实界面、中文输入法和 ASIO 听感由用户按[人工检查](docs/review/2026-10-29-agent-batch2/MANUAL-CHECK.md)确认。

0.7.0 / Agent 0.2 的原生侧栏、选择上下文和双模型验证保留在[第一批历史证据](docs/verification/2026-10-29-agent-sidebar/RESULTS.md)，不作为0.8.0新增能力的通过证明。

保留0.6.1的1/16384网格、Ctrl+4吸附虚实线、三级小节标尺与深缩放，以及0.6.0剪贴板、循环跟随、节拍器、预备拍和资源/电平显示。旧录音、混合工程、性能与插件证据保持原版本范围，见[0.5交付档案](docs/verification/2026-10-27-v05/DELIVERY.md)。

新工程默认 **120 BPM、4/4**。提供音频和弦识别及标签编辑，不提供自动和弦伴奏或乐句模板；MIDI 可通过用户安装的 Windows x64 VST2/VST3 乐器，或加载 WAV 的原生 Sampler／Drum Rack 发声。独立运行和本地分析不需要 Ableton 或 API 密钥。

既有Keyscape兼容、录音音符时间边界和保存修复继续保留。新功能沿用同一个工程、命令接口及Undo；模型请求在独立非实时进程中执行。不提供自动保存和恢复。

## 打开与开发

本轮工作树为 `E:/MusicAgent&DAW/worktrees/audio-analysis`，分支 `fix/plugin-agent-stability-v0132`。本机 VS Code 打开 `E:/MusicAgent&DAW/E-musician-0.13.2.code-workspace`：Ctrl+Shift+B 配置/构建 Release，运行 CTest 任务，F5 调试0.13.2。命令行先执行 `python scripts/dev_stability.py configure`，再分别执行 `build`、`test`；其他检查通过 `command` 子命令记录。`tests/HybridComputeEndToEnd.py` 会调用租用GPU，本轮没有重跑。所有实际步骤保留命令、时间、退出码、源码指纹和日志。

本机使用目录联接 `E:/emusician-analysis-source` 作为 CMake 源目录，构建目录 `E:/emusician-analysis-build`，避免上游 MSBuild 对路径中 `&` 的处理问题。固定 JUCE 8.0.6 / Tracktion Engine 3.2.0，具体 commit 和配置以本轮构建记录为准。其他机器需按 [BUILDING](docs/BUILDING.md) 准备依赖并调整工作区路径；现有 `dev_agent.py` 的历史默认构建目录不是这次 0.9.0 的入口。

新候选独立输出到 `E:/emusician-analysis-build/bin-0.13.0/Release/E-musician.exe`，旧0.12.x和发布归档保留。每次运行前保存并关闭旧窗口，核对新标题 **0.13.0**，避免单实例逻辑返回旧窗口。云端通过SSH连接；本地MIR与既有DAW功能独立保留。新schema8工程请用0.13.0打开。项目约定见 [AGENTS.md](AGENTS.md)，真实验证状态以 [CONTEXT](docs/CONTEXT.md) 为准。

## 基础操作

- **音频**：`add...` 导入 WAV/MP3。主编曲显示多轨片段；移动、跨同类轨拖放、多选、边缘裁剪，通过 `edit` 分割、复制、删除，片段属性设置源偏移和淡入淡出。原音频不会被这些编辑改写。
- **MIDI**：在 `add...` 菜单创建 MIDI/instrument 轨及 MIDI 片段，或导入 `.mid`。双击 MIDI 片段打开底部钢琴卷帘，编辑音高、起点、长度、力度、量化和 16 步鼓点。
- **插件**：选轨后进入 `devices → add plug-in...` 扫描已安装插件，向轨道或 master 加载乐器/效果器，调整顺序、旁通并打开原生窗口。没有加载可用乐器的 MIDI 轨不会发声。
- **混音与时间**：轨道增益、声像、mute/solo；底部播放、暂停、停止和循环；BPM 按钮设置固定速度、拍号及循环区间。音频保持原速，MIDI 按拍跟随速度。
- **录音**：音频设置选择实际设备；选轨的 I/O 面板选择音频或 MIDI 输入，轨头 R 预备，底部 Record 开始、Stop 收尾。监听按输入设备共享，可设 off/auto/on；新工程和重开默认关闭。一次 Undo 撤销本次录制，Redo 恢复。
- **路由与自动化**：添加 Bus，选轨设置输出及 pre/post-fader 发送；Automation 编辑轨道、主输出或插件参数曲线。播放和导出使用同一原生引擎曲线，反馈回路会被拒绝。
- **工程与输出**：`save/open` 保存重开 `.emproj`；`export` 导出全工程或范围 WAV、工程或选中 MIDI。文件任务显示进度并可取消，普通编辑继续使用同一个活动工程。

0.6.0工具栏把`bars / seconds / both`、`snap`、网格和`follow`分开。拖空白处框选片段，Ctrl+C/X/V复制/剪切/粘贴；Shift拖标尺选时间，Ctrl+L设循环。钢琴卷帘用`draw`或B开启单击画笔。Transport第二行提供click、音量/仅录音选项、独立count-in开关和1/2/4小节；从停止状态开始录音才预备倒数，Stop可取消。RAM显示进程工作集，DSP/xrun反映音频引擎，OUT/CLIP可清峰值。详细边界和按键见[快速上手](docs/QUICKSTART.md)。

Source 在底部查看选中音频源；本地分析使用顶部 analyze。32 位插件桥接、侧链、插件任意多输出、comping、自动化 Touch/Latch/Write、TempoMap 和时间拉伸尚未实现。MP3 支持导入和播放，不支持导出。

## 原生编曲助手 0.3

点击工具栏 **Agent** 或 **Ctrl+Shift+A** 开关侧栏：读取当前工程/选择 → 提出具体方案 → 明确应用 → 回读检查。收起保留输入和任务；DAW 拥有独立模型 worker，助手断开不能关闭工程。默认“当前选择”，全局速度/新建轨等操作需明确切为“整个工程”；选区或工程变化会拒绝旧方案。

规划器当前有19种编辑动作，支持在一次确认中连续建轨、建片段并写入明确音符，也可复制/移动/裁剪/删除片段、添加/删除/移动音符、调整时长/音高/力度及量化。方案显示执行顺序和具体修改，作为一份原子批次提交，成功后可一步撤销。规划中可请求暂停，须等待在途模型请求返回；待确认方案可放弃，应用期间不能暂停或取消。“检查→提交→核对→完成”表示后端阶段，不表示逐条修改已经分别提交。

Kimi 与 OpenAI 适配器已实现，凭证按服务通过 Windows DPAPI 本机加密保存；Anthropic、Gemini、本地兼容服务仍预留。本机两套凭证已配置，无需重复提供。OpenAI 可沿用已有 loopback 代理，不改系统网络。界面的“已配置”只说明本地凭证存在；0.8.0的实际调用状态另见[本批验证记录](docs/verification/2026-10-29-agent-batch2/RESULTS.md)。启动、支持范围、数据和费用边界见[Agent 快速上手](docs/AGENT_QUICKSTART.md)；[0.1历史证据](docs/verification/2026-10-29-kimi-agent/RESULTS.md)仅覆盖旧伴随模式。

单方案最多16项动作、2000次音符处理，每个待编辑片段的完整读取上限为2000音符；同一音符被多次处理会累计计入。摘要之外的明确片段目标通过分页补齐，超限拒绝。裁剪只保留原片段内部区间；含CC等控制器事件的MIDI片段暂不允许由Agent裁剪。本地分析已通过专用工具开放；仍无音频生成或长期自主任务，装置控制范围以能力目录为准。Agent也不能代替用户保存工程或删除磁盘文件。旧 `run_agent.py --exe PATH` 仍供独立浏览器伴随模式兼容使用。

## 工程与 Agent

普通工程为 schema 4；包含已接受分析/和弦的工程为 schema 5，0.8.1 明确拒绝 schema 5，首次升级保存前留存原清单备份。工程由 `.emproj` 和同名 `.assets` 目录组成，保存音频归档、MIDI 音符及控制器、片段、混音、插件状态、路由和曲线。移动工程时两者一起移动并保留名称关系。schema 1/2/3 可只读迁移，首次覆盖前保留旧清单备份。普通保存复用未变素材，后台完成文件事务；界面显示状态和结果，保存期间的新编辑仍保持未保存。保存成功后更新归档引用，播放继续复用已准备素材；删除原素材前仍应重开工程核对；旧素材代次与 MP3 PCM 缓存目前不自动清理。Undo 是进程内历史，不随工程重开恢复。

Agent 使用显式开启的本地 JSONL 通道，包含版本冲突保护、幂等请求、任务状态和分页读取：

```powershell
python scripts/agent_client.py --exe E:/emusician-analysis-build/bin/Release/E-musician.exe --demo build/agent-demo
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
