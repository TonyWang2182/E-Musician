# 本地构建、使用与 VS Code 调试

## 当前 0.10.0 工作树（2026-11-05）

实际源码在 `E:/MusicAgent&DAW/worktrees/audio-analysis`，CMake 使用联接 `E:/emusician-analysis-source`，构建目录 `E:/emusician-analysis-build`。新 EXE 单独输出到 `bin-0.10.0/Release`，保留仍运行的 0.9.1 `bin/Release`。不要把历史脚本默认目录误当作当前产物。

```powershell
python scripts/dev_tempo.py configure
python scripts/dev_tempo.py build
python scripts/dev_tempo.py ctest
python scripts/dev_tempo.py agent
python scripts/dev_tempo.py tempo-e2e
```

命令通过 Recorder 记录开始/结束、退出码、原始日志及源码指纹；失败会返回非零。VS Code 打开 E-musician-Analysis.code-workspace，Ctrl+Shift+B 编译，F5 使用明确的 0.10.0 路径；最终构建证据以本轮 review 为准。首次依赖准备增加 `python scripts/bootstrap_stretch.py`，CMake 只验证固定 commit/文件 hash，不自行联网安装。其他机器通过脚本 --source-dir/--build-dir 调整路径，并准备原有引擎/WebView/ASIO 依赖。

真实本地节拍环境通过 `scripts/setup_analysis.py` 的 beats 步骤配置，精确来源和部署在本轮 WORKER-AGENT-NOTES。离线集成会使用本机模型，不调用付费语言模型；物理声卡和音乐听感仍需人工测试。下方为历史流程。

更新日期：2026-10-29。本页保留通用构建流程与历史0.5入口；当前0.7.0 Agent功能工作树使用下面的独立入口。日常助手操作见[快速上手](AGENT_QUICKSTART.md)，实际验证边界见[CONTEXT](CONTEXT.md)。

## 0.7.0 Agent工作树入口（2026-10-29）

本批在 music-agent-kimi 功能工作树开发，用VS Code打开该工作树。日常运行读[Agent快速上手](AGENT_QUICKSTART.md)，本批构建/模型/性能证据读[RESULTS](verification/2026-10-29-agent-sidebar/RESULTS.md)。下方旧版E盘入口与验证日期保留为历史说明。

执行 python scripts/dev_agent.py build、test、run，默认Release；也可用VS Code中Agent sidebar对应任务。构建使用VS18 2026和独立build/sidebar，固定WebView2 SDK经官方NuGet下载与哈希检查；编译并发限制2。本批不覆盖build/bin旧EXE，不改全局依赖或系统网络。源码改动后先关闭自己运行的新版再构建；冻结源码直到Recorder结束。WebView2 Runtime是运行时条件，与SDK不同，缺失时侧栏给出错误，不把失败写成就绪。

测试入口包含原有CTest、Python聚合及原生离线侧栏测试；真实模型测试是另外显式授权和计费的检查，不在常规build/test中自动调用。助手只依赖Python标准库；网页开发测试所用headless浏览器工具不属于运行时需求。最终本版仅Release通过，Debug未重建。


## 开发环境

| 组件 | 当前工程要求 | 本机已记录的版本 |
|---|---|---|
| 系统 | Windows x64；其他平台尚无构建预设 | Windows构建10.0.26200 |
| C++编译器 | Visual Studio 2026，安装“使用C++的桌面开发”和Windows SDK；C++20 | MSVC 19.50.35723.0，SDK 10.0.26100.0 |
| CMake / CTest | 当前预设需要CMake 4.2或更新版本 | CMake 4.2.3 |
| Python | 完整开发与测试流程使用Python 3.11或更新版本 | Python 3.14.0 |
| Git | 可访问依赖仓库的Git | Git 2.52.0.windows.1 |
| VS Code | C/C++、CMake Tools；Python扩展用于脚本编辑 | 推荐列表已写入项目 |

这些是本机此前的环境记录，不代表其他工具组合均已验收。`CMakeLists.txt`的通用最低版本为3.25，但当前`Visual Studio 18 2026`生成器需要CMake 4.2。基础开发脚本可使用Python 3.10，新增任务回归使用的`hashlib.file_digest`需要3.11，因而完整流程按3.11起步。

## 首次运行

用VS Code打开整个`E:\E-musician`文件夹，再在PowerShell终端执行：

```powershell
Set-Location -LiteralPath 'E:\E-musician'
python scripts/dev.py bootstrap --note "准备固定Tracktion、JUCE、VST2与ASIO接口"
python scripts/dev.py check --config Debug --note "首次配置、构建和测试"
python scripts/dev.py run --config Debug --note "启动原生编辑器"
```

`bootstrap`下载并核对固定Tracktion/JUCE提交、三个VST2接口头文件和官方ASIO SDK 2.3.4接口头，再严格应用仓库中的SRC源定位补丁，首次需要网络。Tracktion/JUCE已有非空目录版本错误、SRC补丁出现未知修改时会拒绝。ASIO归档和允许成员经固定SHA-256验证后安装到忽略的`_deps/asio_sdk`；不安装声卡驱动。CMake配置只复核补丁和ASIO文件，不自动下载。依赖来源和许可文本见 [DEPENDENCIES](DEPENDENCIES.md)。

`check`顺序执行配置、编译和CTest，失败即停；`run`启动已经编译好的程序，启动成功不代表音频或性能验收。Debug产物为`build\bin\Debug\E-musician.exe`，Release产物为`build\bin\Release\E-musician.exe`。

## 边开发边测试

1. 修改代码并保存。重新链接前关闭本轮启动的E-musician；调试中用 **Shift+F5** 停止，否则Windows可能锁住EXE并报`LNK1168`。
2. 按 **F5**，选择`E-musician: Debug`。预启动任务先配置、构建，再启动C++调试器。首次F5不会下载依赖，先完成`bootstrap`。
3. 只编译用 **Ctrl+Shift+B**；检查用命令面板 **Tasks: Run Task → E-musician: test Debug**，该任务也会先构建。
4. 完成一轮修改后运行相应配置的`check`，用`--note`记录目的，再补充人工开发日志与续接上下文。

```powershell
python scripts/dev.py check --config Debug --note "说明本轮修改与要验证的行为"
python scripts/dev.py check --config Release --note "验证优化构建"
```

F5与项目Tasks已接入`scripts/dev.py`日志入口。直接点CMake Tools自己的构建按钮不会经过这层记录；实际构建、测试、启动和性能运行使用项目入口。一个配置只运行一条构建流水线，开始后冻结源码，等记录结束再修改，以便首尾源码指纹能对应同一份产物。

Debug适合断点和功能检查。音频线程停在断点时不能继续保持实时输出；CPU、掉音和延迟测量使用Release，并记录实际设备、采样率、缓冲区与工程负载。

## 打开与保存用户工程

点击`open`或按Ctrl+O，在`E:\E-musician\test-projects`中选择`.emproj`文件，不是同名`.assets`目录。文件与素材目录应一起保留。开发回归使用整个工程包的独立副本，不覆盖原工程；当前受保护文件清单和哈希基线见 [CONTEXT](CONTEXT.md)。

`new`创建120 BPM、4/4的空工程。`save`保存当前位置；`save as`另存为新工程包。schema4保存音频资产、MIDI notes/controllers、插件状态、输入选择、bus/send及自动化；schema1–3在打开时迁移，覆盖旧版清单前保留带旧schema和随机后缀的原字节备份。录音arm与监听不会因为打开工程自动恢复为正在录制。旧版本程序不能安全覆盖schema4工程。

保存按钮受理后显示`saving...`，工程状态显示`Saving...`；当前状态完成提交后显示`Saved`。`Unsaved changes`表示还有未保存编辑，`Save failed - retry`时查看底部具体错误后重试。保存期间可继续普通编辑，后续编辑不会被较早任务清掉；重复Ctrl+S在命令入口合并为同一个任务，必要时最多一次后续保存。该合并行为已有组件回归，原生组合键注入的限制见下方快捷键说明。

保存后原工程会继续引用当前已打开的音频源；重新打开保存的工程后才绑定包内副本。关闭或切换工程前应等待保存任务及主线程提交完成。素材代际和MP3缓存不会自动清理；当前没有完整自动保存、崩溃恢复或缓存垃圾回收功能。迁移备份不等同于完整工程备份。

## 音频编曲入口

`add...`按钮打开新增菜单，可导入WAV/MP3、导入MIDI、新建音频轨、新建MIDI/乐器轨，或在选中的乐器轨播放头位置新建四小节空白MIDI片段。导入任务在后台执行，可观察进度和取消；同一时刻只接收一项重文件任务。

主窗口持续显示唯一的多轨编曲时间轴和轨头，通过纵向滚动、横向滚动和缩放查看全部轨道。`source`打开底部所选音频的源波形，`devices`打开底部轨道面板；双击MIDI片段打开底部钢琴卷帘，`close editor`收起。原Compose/Separate/Transcribe三页导航不再常驻；转录和真正的音源分离尚未实现。

| 操作 | 入口和行为 |
|---|---|
| 选择片段 | 点击；Ctrl/Shift配合点击多选；选择本身不自动移动播放头 |
| 移动与跨轨 | 拖片段主体；音频移到音频轨，MIDI移到MIDI/乐器轨；Escape取消当前拖动 |
| 裁剪 | 拖左右边缘；改变片段范围，不重写源文件 |
| 精确属性 | `details`展开右侧Inspector，或使用`edit` → `Clip properties...`，编辑起点、源偏移、长度、淡入淡出 |
| 分割、复制、删除 | `edit`菜单；分割位于播放头，快捷键S；复制Ctrl+D；删除Delete |
| 网格与吸附 | 默认1/16拍；可切换小节/秒与自由模式；Alt临时忽略吸附 |
| 显示范围 | `-`、`+`、`fit`；Ctrl+滚轮缩放，Shift+滚轮横移；普通滚轮纵向滚动 |
| 轨道管理 | 新建、重命名、重排、删除；使用轨道选择和编辑菜单 |
| 混音 | 轨头`M`/`S`为mute/solo，`details`提供所选轨gain/pan；底部为主输出音量；选轨不等于solo |
| Transport | Space播放/暂停，stop归零；标尺定位；循环开关与范围、BPM和拍号可在相关控件/菜单编辑 |

固定BPM控制MIDI拍位；音频保持原速，不自动跟随BPM拉伸。普通编辑和Undo保持同一个Edit及无关插件实例；插件拓扑、工程切换和设备设置等操作可能需要停止播放。

Undo/Redo用于当前内存会话，工程重开后历史为空。增益、声像、loop和插件参数有显式标量Undo，手势合并为一步。引擎配置中的64是Undo保留的最少事务数，不是固定64步上限，详见 [ARCHITECTURE](ARCHITECTURE.md)。

## MIDI、鼓步进与插件

双击MIDI片段打开主窗口底部钢琴卷帘Dock，首次按片段音高适配；上方仍保留编曲轨道，`close editor`收起。在网格空白处双击添加音符，拖动音符改起点/音高，拖边缘改长度；支持框选、多选、力度、量化、移调、复制和删除。`drum steps`展开的16步鼓编辑器与钢琴卷帘操作同一组MIDI数据：每页是四个四分音符拍的16步；空片段添加鼓点默认通道10，已有音符则保留片段通道。它不提供内置鼓音色，也不是乐句模板库。

MIDI导入支持SMF0/1的PPQN时基。当前工程只有固定速度，复杂tempo map、SMPTE、控制器及其他不支持的SMF导入事件不会静默当成完整还原；API可显式选择`notes_only`导入音符。新增MIDI录音与导出保留常用controller，不能据此推断SMF导入已支持全部事件；具体格式与反馈见 [AGENT_API](AGENT_API.md)。

选轨后点击轨头或工具栏的`devices`，底部`devices`页可操作已有插件链；`add plug-in...`打开独立插件浏览窗。用`scan installed`扫描已安装位置，或用`scan folder...`选择目录；目录扫描默认也包含默认路径。Agent API的`include_default_paths=false`可只扫描指定范围，`modules`可直接列出最多64个DLL/VST3模块。扫描位于独立进程，正常运行中的插件仍在DAW进程中。

浏览窗确认目标轨或主输出，选插件后点`add >`。底部链面板用`open`打开原生插件窗口，`bypass`旁路，`up`/`down`排序，`remove`移除；右上`master`切换主输出链。当前只接入Windows x64 VST2/VST3。MIDI轨需要安装并加载一个可用乐器插件才会发声；本项目没有自带音源、和弦工具或确定性乐句模板。插件程序与外部音色库不会随工程打包，接收工程的机器需要相应插件与资源。实际插件兼容结果见CONTEXT，不能按格式开关推断所有插件均兼容。

## 录音、ASIO和混音扩展

源码已接入以下工作流；运行前使用本轮编译产物，并查看CONTEXT中的实际通过记录。

1. 停止播放，打开`audio settings`，选择`Driver`和`Device`（分离I/O驱动显示`Input`/`Output`），点`apply`。更换设备先应用默认配置，再选择该设备支持的`Sample rate`/`Buffer size`，以`Active:`实际回读值为准。M-Audio使用列表实际返回的厂商ASIO驱动名；仅安装SDK不会安装驱动。设置窗关闭后才能开始录音。
2. 新建音频轨或MIDI/乐器轨，点击轨头`devices` → 底部`I/O + sends`，在`recording input`选择输入，再点`arm record`，或在已配置输入后用轨头`R`预备录音。MIDI监听发声还需要可用乐器插件。SL GRAND与MIDIIN2 (SL GRAND)是本机枚举到的两个端口，不能假定用途相同，须实测选择。
3. 新输入默认`monitor off`；可改为`monitor auto`/`monitor on`。监听模式是输入设备级，同一输入共享模式；auto随arm监听，on持续监听已连接轨道，off关闭软件监听但不禁止录音。关闭`loop`后点击`rec`开始线性录音，`stop`结束。
4. 等待`Finishing recording...`结束再保存。一次take的全部录音轨道作为一个Undo事务；Undo不删源WAV，Redo继续引用。录制及结束认领期间暂停工程编辑/设备切换/保存，不能把半写入文件归档成完成工程。

音频新take使用24-bit WAV，录音文件先落到独立会话目录（正常路径为`%APPDATA%/E-musician/recordings/<project-id>`），保存再归档到工程资产。MIDI录音保留音符、踏板等CC、pitchbend、程序切换与压力事件；仍采用单通道clip模型，不声明MPE/SysEx或循环comping。真实输入、掉线恢复及长时间录音仍应在各自验证报告中单列。

`add...` → `New bus / group track`新建可承载效果链的bus。普通轨在`devices` → `I/O + sends`的`track output`选择master或bus；`send to bus`选目标并点`add send`，再调发送增益及`post-fader`/`pre-fader`。直接输出和发送共同拒绝反馈环，含暂时disabled的send。删除被引用bus、插件的语义由统一编辑命令处理并可Undo；不使用界面直接改引擎树。当前范围不包括任意侧链、外部硬件insert和多输出乐器矩阵。

`devices` → `automation`提供真实轨道gain/pan、master gain或插件参数曲线；右上`master`切换主输出。双击加点、拖动移点、Alt+上下拖点改曲率、Delete删点；`bypass lane`旁路，`delete lane`删整条。参数列表来自当前实例；曲线时间为工程绝对秒，接口值0..1由引擎转换为参数原生范围，参与播放/导出。曲线编辑有Undo；没有Touch/Latch/Write录制模式。Agent命令与完整JSON示例见[AGENT_API](AGENT_API.md)。

## 导出与后台任务

导出菜单提供完整工程/范围WAV、实时WAV渲染，以及完整工程/所选MIDI的标准MIDI文件。WAV表单可选择44.1/48/88.2/96kHz、16/24/32位和0–60秒尾音；尾音为明确长度，不自动检测插件尾音。没有MP3导出功能。

WAV渲染在独立worker进程中运行，不占用交互实例的播放引擎，也不打开输出设备。导出使用提交时冻结的工程和插件状态。实时渲染选项仍是该worker中的渲染方式，不是直接录制声卡输出。缺失且启用的插件可能阻止对应音轨的WAV导出，避免把缺失处理误报成正确成品。

导入、保存、打开、导出区分“任务已受理”和“任务已完成”。取消、工程revision变化、目标文件被外部修改均有明确结果；不要仅根据任务ID或进度条到末端认定提交成功。保存完成后的后续打开/关闭由主线程确认，任务协议见 [AGENT_API](AGENT_API.md)。

## 常用快捷键

| 快捷键 | 行为 |
|---|---|
| Ctrl+N / Ctrl+O | 新建 / 打开 |
| Ctrl+S / Ctrl+Shift+S | 保存 / 另存为 |
| Ctrl+Z | Undo |
| Ctrl+Y / Ctrl+Shift+Z | Redo |
| Ctrl+D / Delete | 复制 / 删除选中内容 |
| S | 在播放头分割选中的可分割片段 |
| Space | 播放 / 暂停 |

此表列出当前实现的键位绑定，不表示所有OS输入路径已验。原生验证中Space正常；Sky瞬时Ctrl+S组合键注入未产生保存任务，而鼠标Save成功。JUCE读取修饰键的`GetAsyncKeyState`时序是候选原因，尚未实证，不据此宣称应用快捷键已修复或物理键盘必然失效。保存可使用`save`/`save as`按钮；完整现象与后续结论见[验证记录](verification/2026-10-27-v05/RESULTS.md)。

## Agent接口与回归入口

应用通过`--control-stdio`开启本地JSONL控制，无网络监听。协议含快照和分页、revision冲突、幂等请求、原子批量编辑、Undo、插件与文件任务查询。读写的是同一受控进程的活动工程；加`--show`后GUI也操作该工程。客户端启动的进程不会附着另一已打开的DAW窗口。

可运行客户端示例：

```powershell
python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --demo build/agent-demo
```

示例用于验证协议与可控编辑，不是乐句模板或自动作曲功能；没有乐器时不会自行发声。生产调用的帧限制、请求字段、任务轮询和`edit_notes`局部修改见 [AGENT_API](AGENT_API.md)。

完整`check`会运行CTest注册的日志脚本、核心和引擎组；新增基础回归包含schema/MIDI/编辑与任务断言。单独运行JSONL任务回归时同样经过Recorder，避免无日志的测试执行：

```powershell
python -c "import sys; sys.path.insert(0,'scripts'); from dev import Recorder; Recorder('verify-agent-jobs','Release','JSONL任务回归').execute([sys.executable,'tests/AgentJobsSmoke.py','--exe','build/bin/Release/E-musician.exe','--timeout','180'])"
```

这是一条可执行方法，不是已通过声明。结果以新记录的源码指纹和输出为准；新增代码之后不能沿用旧`latest.json`。没有设备时应明确记录受限项，不补写音频成功。MP3样本已在仓库中，只有重新生成样本才需要[测试素材说明](../tests/fixtures/README.md)中的隔离编码环境。

新增引擎smoke包含ProductionSmoke：人工生成音频与MIDI/CC64送入HostedAudioDeviceInterface，通过公开录音命令测试空工程、Stop认领、一次Undo/Redo、schema4重开、bus/send实际渲染与自动化；也检查MIDI split/trim的控制器边界延续。它不打开麦克风或物理MIDI，不替代M-Audio/SL GRAND设备验收。报告写入本次smoke目录下`production-smoke.json`，只有该次执行成功后才可标记通过。

以下专项脚本也应通过同样的 `Recorder(...).execute([...])` 入口执行，且运行期间不修改源码：

| 脚本 | 参数与范围 |
|---|---|
| `tests/SavePipelineSmoke.py` | `--exe`、可选精确 `--module`、两次 `--audio`；先复制素材，检查增量保存、另存为和保存期间编辑 |
| `tests/PlaybackSaveSmoke.py` | `--exe`、精确乐器 `--module`、两次 `--audio`；低音量循环播放并保存，记录实际设备、耗时和 xrun；可设 `--max-xrun-delta 0` |
| `tests/PluginNotificationSmoke.py` | `--exe`、精确且已扫描 `--module`；真实通知、自动化基值和保存重开，插件版本以报告为准 |
| `tests/PluginHostSmoke.py` | `--exe`、一次或多次精确 `--module`、可选 `--realtime`；扫描、参数、Undo、恢复和非零渲染 |
| `tests/HardwareRecordingSmoke.py` | `--exe`、精确 ASIO `--device`、可选 `--fallback-default`；录制实际输入两秒、关闭监听；48k请求失败与实际配置分别记录 |
| `tests/MidiControlPerformance.py` | `--exe`；100000音符、停止播放、无插件，测量JSONL往返而非物理输入到画面延迟 |

硬件录音不自动加入CTest；该专项会读取指定设备的真实音频输入。所有脚本在新的build子目录写产物，不能传入用户工程作为输出目标。

## 性能验证

Release长跑使用唯一输出目录，并通过Recorder记录。以下示例请求120秒预热后测量1800秒的既定多轨负载，具体参数行为以当前性能入口为准：

```powershell
python -c "import sys,uuid; from pathlib import Path; sys.path.insert(0,'scripts'); from dev import Recorder; output=Path('build/performance')/uuid.uuid4().hex; Recorder('performance','Release','16轨基础长跑').execute([str(Path('build/bin/Release/E-musician.exe').resolve()),'--performance-test',str(output.resolve()),'1800','--show'])"
```

运行前保存自己的工作，确认输出设备和音量；播放负载会产生实际声音。测量期间避免并行编译、模型推理等额外重负载。记录实际设备采样率/缓冲区、测量时长、CPU、xrun、命令响应、内存及可测的周期统计。请求48kHz/256不代表设备实际接受256；设备拒绝时记录实际值。未采集的回调P99、物理界面响应和真实回环延迟继续标为未测。

64轨、4096片段、100000音符等是输入与资源保护上限，不是所有负载组合能以低延迟稳定运行的承诺。长跑目标与回归负载见 [DEVELOPMENT](DEVELOPMENT.md)。

新增录音管线复用固定引擎的输入队列和writer线程，仍含锁、队列耗尽时分配及Stop等待writer的路径；当前没有零分配/无锁或全负载实时保证。保存优化的UI响应、插件state抓取耗时、写入/复用字节、录音停止耗时与ASIO实际xrun应分别测量，不能用空工程或旧配置测试代替两音轨+挂插件MIDI轨的真实场景。

## 日志与排错

| 位置 | 内容 |
|---|---|
| `docs/DEVLOG.md` | 追加式开发和执行记录 |
| `docs/CONTEXT.md` | 当前进度、验证结果和下一步 |
| `docs/builds/` | 构建/运行的结构化记录、源码指纹和命令结果 |
| `build-logs/` | 对应命令输出及原始字节日志；准确路径以结构化记录为准 |
| `build/Testing/Temporary/LastTest.log` | CTest日志；实际构建目录以记录为准 |
| `build/smoke/<config>/latest.json` | 该配置最近一次引擎smoke产物索引 |
| `build/agent-jobs-smoke/` | 独立JSONL任务回归产物，目录以脚本输出为准 |
| 性能命令指定目录 | 性能报告与采样数据 |

依赖未准备先运行`bootstrap`；生成器不识别先确认CMake4.2和VS2026的C++组件；缺少SDK先修复开发环境。`LNK1168`先关闭自己启动的对应配置程序，不批量结束用户进程。界面可开但无声时检查设备、mute/solo、主输出及MIDI乐器；不要把构建通过当成声卡或插件兼容证明。

GitHub保留源码、测试、结构化构建摘要及精选验证产物。`_deps/`、`build/`、`build-logs/`、缓存、个人工程和录音不上传；历史DEVLOG中的原始日志链接仅在原开发机器可打开，对应`docs/builds/`摘要仍可在线审查。
