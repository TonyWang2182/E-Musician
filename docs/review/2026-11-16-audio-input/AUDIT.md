# 音频输入独立审计（2026-11-16）

状态：源码诊断已确认；修复补丁已准备；本审计未启动物理设备、应用窗口或厂商面板，未执行构建。修复后的运行证据由本轮 RESULTS / 构建档案补充，不能把本文当作硬件验收。

实际工作树为 `E:/MusicAgent&DAW/worktrees/audio-analysis`。读取了 CONTEXT、DEVELOPMENT、ARCHITECTURE、UI_REFERENCE、录音时钟 ADR、当前录音实现、既有测试和固定依赖。保留已有 DEVLOG 与其他代理修改。本审计拥有三个新引擎补丁及其 manifest 新增项、`tests/AudioInputLifecycle.py` 和本文。

## 已确认的两个缺陷

1. **引擎逻辑输入“启用”不代表物理输入已经打开。** 旧 `OutputOnlyBehaviour::shouldOpenAudioInputByDefault()` 返回 false，固定 Tracktion `Engine::initialise()` 因而以 0 个默认输入初始化 JUCE。旧 `configureDevice()` 在没有 `input_channels` 时强制 `useDefaultInputChannels=true`；JUCE 的 `updateSetupChannels()` 按内部 `numInputChansNeeded` 重写掩码，该值初始为 0，也会被后续显式掩码的位数改变。仅改变采样率/缓冲区因此可能关闭全部输入，或将稀疏 In2 掩码替换为 In1。
2. **稀疏 In2 的回调索引与物理索引不一致。** 固定 JUCE 的 Windows ASIO / WASAPI / DirectSound 都将已启用输入按顺序压紧到回调指针数组。只打开物理通道 1 时，实际 PCM 位于回调槽 0。固定 Tracktion 的 `WaveInputDeviceInstance::copyIncomingDataIntoBuffer()` 却按 `ChannelIndex::indexInDevice` 读取槽 1；在越界分支中只有断言，没有清空重用缓冲区。Release 因此可能录到静音或此前缓冲内容。旧 Hosted 测试使用密集 `[0,1]`，并给两路相同波形，无法发现错误通道或稀疏映射。

只读检查当前 `%APPDATA%/E-musician/Settings.xml` 得到：

| 字段 | 观察值 |
|---|---|
| Driver / device | ASIO / M-Audio M-Track Solo and Duo ASIO |
| Rate / buffer | 44100 Hz / 512 samples |
| JUCE `audioDeviceInChans` | `0`，无物理输入 |
| Tracktion `inEnabled` | 256 位全启用 |
| Tracktion `stereoChansIn` | `0`，单声道输入 |

没有读取或输出其他设置内容、凭据、网页存储或用户工程。该快照说明持久化配置具有缺陷条件；并不声称本审计已听到用户当时的输入或读到运行中驱动状态。

Tracktion `WaveInputDevice::setEnabled()` 仅更新 `DeviceManager::inEnabled` 和输入对象列表，没有打开 JUCE 物理通道。旧 `bind()` 只检查逻辑 `isEnabled()`，所以可以成功绑定一个物理关闭的输入。旧 `start_recording` 只检查存在 armed 目标和 transport 状态，缺少物理通道可用性核验。`numChannels==0` 时固定引擎明确清空输入缓冲，因而“transport 前进、生成可读 WAV”仍可能只是录到数字静音。

## 固定依赖与回调契约

权威基线：Tracktion `b0c7dd090a56b27fe01bb394617891906eb34daf`，其固定 JUCE `19edd538429c93d277bf95b55aaa7e3eb545f951`（8.0.6）。本机使用忽略目录 `.cache/monitor-engine`；本审计没有修改该 checkout。

下列行号针对未添加本轮补丁的固定文件：

| 源码 | 证据 |
|---|---|
| `tracktion_engine/utilities/tracktion_Engine.cpp:70` | false 行为分支传默认输入数 0 |
| `tracktion_engine/playback/tracktion_DeviceManager.cpp:909` | loadSettings 分别恢复 JUCE 物理配置和 TE `inEnabled` / stereo 配置 |
| `juce_audio_devices/audio_io/juce_AudioDeviceManager.cpp:711,792` | 默认掩码按可变输入位数重建；显式掩码会修改默认位数 |
| `juce_audio_devices/native/juce_ASIO_windows.cpp:507,884,1333` | 仅对启用位填入 `inBuffers[n++]`，回调数为 `numActiveInputChans` |
| `juce_audio_devices/native/juce_WASAPI_windows.cpp:474,1046,1510,1572` | `channelMaps` 收集启用物理索引，传递 active-bit 数量的紧凑输入缓冲 |
| `juce_audio_devices/native/juce_DirectSound_windows.cpp:1031,1129` | 输入 AudioBuffer 大小为启用位数，left/right 写入递增 `numIns` |
| `tracktion_engine/playback/tracktion_DeviceManager.cpp:1483,1544` | 旧实现不作输入映射，直接转发给物理 Wave 输入 |
| `tracktion_engine/playback/devices/tracktion_WaveInputDevice.cpp:1129` | 旧实现以物理索引读回调数组；越界不清空 |
| `tracktion_engine/playback/tracktion_HostedAudioDevice.cpp:75,82` | Hosted 输入始终是从 0 连续的掩码，回调也是密集顺序 |

JUCE `AudioIODeviceCallback` 头文件的总说明提到与 `getOutputChannelNames()` 相同索引、未启用槽为空；参数说明则说每个已启用通道一条数据。不能仅凭这段概述推翻实际 Windows 实现。本补丁同时接纳上述两种形状：回调指针数等于当前启用位数时视为紧凑数组，否则按物理槽数组读取；密集前缀掩码时两种索引相同。未启用位始终映射为空，即使调用者提供了非空指针。

## 已准备的固定引擎补丁

`DeviceManager::prepareToStart()` 在回调暂停阶段按实际设备名字数量和 active mask 预分配物理→回调索引及物理指针数组。音频回调只做有界索引/指针赋值，将紧凑输入展开为物理槽，再走原有 Tracktion 路径；不增加网络、文件读取、JSON、锁或回调内容器扩容。超过实际块大小的分块路径保留空指针，避免空指针加偏移。

WaveInput 每个目的声道在来源缺失、禁用、空指针或越界时明确清零，防止旧块残留。轨道内部音频输入仍使用原来的物理/内部索引，设备无关的录音时钟、writer、目标和工程状态不变。未新增输出通道选择功能；本轮仅给已有分块输出指针运算补充空指针保护。

| 补丁 | 上游文件 SHA-256（LF） | 补丁后文件 SHA-256（LF） |
|---|---|---|
| `physical-input-callback-map-h.patch` | `9ac86376ea2828516452bd14ba34d9fa446e41c91ba9af2f71fc74c1550a800d` | `6df5bacba9e3dcf986432772d440d1716276484c537823687bf20600976e6686` |
| `physical-input-callback-map-cpp.patch` | `75d76576fa7c4cee25985a69c07df6b66058ca6271506f5951e833adfa08a57e` | `3f1f367ae5bb8e728674e00acd8711bca9587f565165b82c71b4a54be44b1233` |
| `physical-input-buffer-clear.patch` | `6dd21a1e3fe4589c4d0f72c24ae6633d6d6fa69952d3b6246fcd9afdd7e95fe6` | `bf3424aec6f6aa189d5d6f5b18bc4eb426228141c5e495f5d344701af1ea9f53` |

生成时逐一核对当前源文件等于 `git show <固定提交>:<文件>`，用现有 `apply_exact_patch()` 纯内存应用，输出逐字节等于目标内容；该检查通过。新 manifest 总计 16 个文件，仍在既有工具 16 文件上限内；没有重算或改写其他 13 个补丁。真实应用、配置、编译与测试由主代理另行记录。

## 驱动设置面板边界

固定 `juce_AudioIODevice.h:328` 提供 `hasControlPanel()` / `showControlPanel()`，不需要按 M-Audio 厂商名硬编码。固定 ASIO 的 `showControlPanel()` 调用当前已打开 ASIO 对象的 `controlPanel()`。其返回值根据耗时是否超过 300 ms 判断是否需要首选缓冲重开，不能解释成“窗口是否显示成功”；内置 `AudioDeviceSelectorComponent` 也只在 true 时 close/restart 后端。调用可能进入厂商嵌套消息循环，应复用控制层防重入、录音/播放保护并在返回后重新查询实际参数。没有面板的后端应清楚显示不支持，而非任意启动系统程序。

“支持任意声卡”可实现为按已安装 JUCE 后端和设备能力枚举、实际输入声道、单/立体声与厂商面板处理，不能据此保证所有声卡/驱动版本或物理接线已验收。设备身份也不能仅依赖 TE `wavein_` 名称散列：固定 TE 对恰好两路的设备统一命名 Input 1 / Input 2，不同声卡可能产生相同旧 ID。项目切换设备时需有接口身份限定；无法证明来源的旧物理 ID 不应静默绑定到新卡。

## 测试缺口与新探针

既有 `EngineSessionProductionSmoke.inc` 使用 Hosted 的两个同波形输入，覆盖录音/Stop/PCM/Undo/持久化，但不覆盖物理打开掩码、稀疏 In2、左右通道区分、重配失败回滚与驱动身份变化。`HardwareRecordingSmoke.py` 直接传 `[0,1]`，只验证 WAV 格式/时长，不测 PCM 内容，也绕开了设置页省略掩码的路径。

后端代理负责新增原生假驱动测试：独立波形 In1/In2、紧凑 `[1]`、完整物理槽 `[null, signal]`、有效输入后下一块为空、较大回调块、mono/stereo、身份和失败回滚。原生测试未实际运行之前仅为计划/实现中。

`tests/AudioInputLifecycle.py` 已准备，静态 AST 解析和合成 24-bit 双声道 PCM 指标检查通过，没有启动 EXE。物理执行必须显式 `--allow-physical-capture`，由主代理通过 Recorder 运行：

- 拒绝运行中的 E-musician；不关闭、终止或操纵已有用户实例。
- 父进程保存 Settings.xml 原始字节，专用 Python 子进程先等待 gate，再在 Windows Job Object 归属建立后启动专用 DAW；超时只回收该进程树。
- master -60 dB、逐轨 Monitor Off、metronome/count-in Off；不打开厂商 GUI，不播放导入片段。
- 检查禁用输入拒绝 Arm、单路 In1、双 mono、单独 In2、stereo pair、同设备省略掩码保留、非法配置保持实际设备状态、录音期间重配拒绝。
- 每个 take 核验 WAV 声道/格式/长度，记录各声道 RMS、peak、非零采样数和数字静音标记，再核验一次 Undo/Redo、保存重开 disarmed。
- 进程退出后恢复 Settings.xml 字节并核对 SHA；如检测到新用户实例，不覆盖其可能在用的偏好，保留备份并明确报告恢复延期。

该探针允许物理来源静音，但会明确记录；静音文件、非零噪声或正常时钟都不是输入接线/演奏/听感验收。原始 take 保留在应用为专用测试工程生成的独立 recordings 子目录，路径写入报告；归档工程、PCM 副本和偏好备份须放仓库忽略目录或仓库外目录，脚本检查仓库内路径确已忽略，不能纳入 Git。

## 补充独立复查

复查新配置实现时发现：失败候选会改变 JUCE 默认通道计数，若回滚沿用旧 `useDefaultInputChannels=true`，即使传入旧掩码也可能恢复成别的通道。后端已改为回滚时显式提交保存的输入/输出掩码，并加入初始默认零输入状态的非法配置测试；运行结果仍待主代理记录。

新 UI 的同设备 Apply 传完整输入掩码与立体声配对，新设备 Apply 不复用上一设备的通道/采样能力；厂商面板只对实际已打开且支持面板、无未提交草稿的设备可用。异步 Apply/面板调用复制回调并在返回后检查 SafePointer，测试包含回调期间删除设置窗口。后端在控制操作及设备更换期间阻止嵌套编辑，返回后重新读取实际参数。独立源码复查未发现其他阻断项；不是鼠标、硬件面板或完整运行验收。

明确保留的边界：旧工程的非限定物理 `wavein_` 输入须重新选择；驱动类型、系统端点名和通道名完全相同时，JUCE 当前接口没有硬件序列号可证明更换了另一台同名设备。当前设置 UI 要求存在一个输出选项；普通独立输入 + 系统输出可用，但某后端若完全没有输出端点，不能由本轮 UI 选择为纯输入模式。
