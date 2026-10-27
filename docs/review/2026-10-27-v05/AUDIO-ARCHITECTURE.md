# 录音、ASIO、自动化与路由：只读复盘和实施契约

日期：2026-10-27，Asia/Shanghai。本文是实施前复盘与建议，不是功能完成声明。未构建、未启动DAW、未打开音频/MIDI端口、未安装驱动、未录制用户输入；只读取工程、固定依赖源码、官方资料、设备注册信息及WinMM设备名称。唯一写入为本文。

## 结论

可以继续使用现有单个Tracktion Edit，复用其输入分配、录音、参数曲线和音频图，不需要再造一个音频引擎。但当前应用层schema3和绑定缓存没有这些状态；仅开启几个引擎开关会产生“听得到却保存不住”“录完不显示”“自动化播放把工程弄脏”等问题。应先解决当前保存缺陷，再扩展持久化契约和命令，然后接UI。

固定版本是Tracktion `b0c7dd090a56b27fe01bb394617891906eb34daf`（3.2.0）和其JUCE子模块 `19edd538429c93d277bf95b55aaa7e3eb545f951`（8.0.6）。官网最新API只用于寻找概念，编译签名以这些本地源码为准：官网AutomationCurve已采用EditPosition/显式UndoManager，本地仍是TimePosition及隐式owner UndoManager；官网TrackOutput新增的`setOutputToNone`不在此固定版中，不能直接照抄。

## 现有边界和必须处理的风险

| 证据 | 对新功能的影响 |
|---|---|
| `apps/desktop/EngineSession.cpp:234`，rebuild跳过无应用稳定ID的Clip | 引擎录音生成的Clip必须被应用认领，否则不显示、不进入save DTO |
| `ProjectStorage.h:StoredTrack/StoredProject`只含片段、混音、插件 | 输入、路由、自动化和非音符MIDI事件目前无法保存，需要schema4明确迁移 |
| `EngineSession.cpp:201/204`，capture读取当前volume/pan值 | 自动化播放后不能把当前曲线值存成新的基础参数；须用explicit值并独立保存曲线 |
| `tracktion_InputDevice.cpp:224`，监听取owner MonitorMode | 固定引擎监听模式属于输入设备；同一输入送多轨时不能伪装为每轨独立Off/Auto/In |
| `tracktion_TrackOutput.cpp:242`，输出内部以轨号字符串设置 | 应用保存稳定track ID；全部轨道创建/重排后解析，不能把显示顺序当持久身份 |
| `tracktion_WaveInputDevice.cpp:1665`，录音队列预建32个2×512块，空闲耗尽会new，load可能setSize，队列用CriticalSection | 原版不提供“录音回调绝对零分配/无锁”的保证，需实测目标并发负载；若要求严格有界，要维护显式补丁或自有预分配writer |
| 同文件`:691/702/1831`，结束writer会等待落盘；所谓异步stop最终仍在消息线程applyRecording | 不能把异步接口名称当无卡顿证明；必须单独测停止录音与落盘finalize耗时 |

## 本机设备事实

只读Win32_SoundDevice返回 `M-Audio M-Track Solo and Duo`、`USB Audio Device`、Realtek及Intel/NVIDIA相关设备，状态为OK。用户已向根代理确认使用M-Audio M-Track Solo/Duo及MIDI键盘。

WinMM `midiInGetNumDevs`/`midiInGetDevCapsW`只查询名称，返回两项，结果码均0：`SL GRAND`、`MIDIIN2 (SL GRAND)`。尚未打开端口，无法据此证明MIDI消息抵达或具体通道映射正确。

64位 `HKLM/SOFTWARE/ASIO`有10个注册项：Ableton Move、Ableton Push、ASIO4ALL v2、Focusrite Thunderbolt ASIO、Focusrite USB ASIO、Generic Low Latency ASIO Driver、M-Audio M-Track Solo and Duo ASIO、NUX Audio、UMC ASIO Driver、Yamaha Steinberg USB ASIO。注册项仅证明驱动登记，不能证明所有硬件已连接；优先在用户确认的M-Audio上验收。旧版Realtek 48kHz/480samples测量不属于ASIO验证。

## ASIO接入与固定来源

固定JUCE `juce_audio_devices.h:90`要求外部SDK，`juce_audio_devices.cpp:158`直接包含`iasiodrv.h`。实施方式为启用`JUCE_ASIO=1`，把核验后的SDK `common`目录加入include路径，同时保留WASAPI回退。不要升级JUCE或用当前master文档的“内附SDK”选项代替本地约束。

官方[ASIO下载入口](https://www.steinberg.net/asiosdk)此次重定向到[ASIO SDK 2.3.4固定ZIP](https://download.steinberg.net/sdk_downloads/ASIO-SDK_2.3.4_2025-10-15.zip)。已在内存中读取并核验，未写入依赖目录：

| 对象 | 字节数 | SHA-256 |
|---|---:|---|
| 完整ZIP | 8910208 | `d5ebf0c20dd2c5f43771fd0c1418f4b361bf52434ee670097cfa6b3a335e2eca` |
| ASIOSDK/common/iasiodrv.h | 2379 | `86ad4788452c74823653cf57d4bd557c48bb6542d7e6eb7fff80102c705a066d` |
| ASIOSDK/common/asio.h | 44265 | `93d2f80d49b4ac9c963514e7c1307ab5111d8104246192233745beb058534ea1` |
| ASIOSDK/common/asiosys.h | 2165 | `f44a1ed0fd7c056ff047aeebc4c05a8c185f0585a24d8debc55c70107777dbef` |
| ASIOSDK/LICENSE.txt及common/LICENSE.txt | 2640 | `61e56814f24b32216884b2db0b4dcc317111a5ab354d54d19dd9fc13d71b1c7a` |

包内许可提供专有条款或GPLv3选项；按文件保留声明，不能说“开启ASIO即已完成发行许可”。官方[2026-10-21许可FAQ](https://forums.steinberg.net/t/asio-sdk-proprietary-licensing-faq/1044024)区分内部开发测试与向外发行；本轮是本地开发，不代用户签署、提交协议或安装驱动。SDK/bootstrap应固定URL与整包/文件哈希，使用忽略的`_deps/asio_sdk`并验证路径，不把8.9MB原包混进源码。

设备命令须返回实际驱动类型、设备名、输入/输出通道、采样率、块大小和输入/输出延迟。切换驱动仅停止本应用Transport，在录音期间拒绝切换；失败保持或恢复先前配置，不能静默回退后仍显示ASIO。不要在默认启动时抢占用户其他DAW使用的ASIO设备。

## 录音路径

固定引擎现成入口：`InputDeviceInstance::setTarget`、`setRecordingEnabled`（InputDevice.h:129/153），`TransportControl::record(false)`（TransportControl.h:91），`stop/stopRecording`（:98/108），以及`TransportControl::Listener::recordingFinished`（:363）。[官方输入实例文档](https://tracktion.github.io/tracktion_engine/classengine_1_1InputDeviceInstance.html)描述了输入实例、目标和停止回调；实际使用固定源码签名。

推荐状态机：`idle → preparing → recording → finalizing → idle/failed`。开始前检查至少一条arm轨、输入可用、可写录音目录、格式和磁盘空间。Record与Stop命令必须幂等，重复点击不生成多份take。UI显示准备、录制、写入完成，不以按了Stop就宣称可安全关闭。

音频由引擎设备回调送已有recording writer线程，24-bit WAV作为初始录音格式；GUI只读取计量和有界峰值/录音状态。应用不得在音频回调中序列化工程、复制文件、扫描插件或抓取状态块。

未保存工程用专用`%LOCALAPPDATA%/E-musician/recordings/<project-id>/`会话目录，已保存工程也先录到独立take staging，文件名含稳定take UUID。明确设置`editFileRetriever`与录音filename mask，避免引擎落到进程cwd。录音文件在已完成take引用、撤销历史和恢复记录仍持有时不能删除；不能复制DemoRunner析构里清理整个临时目录的做法。

在recordingFinished中收集新Clip；音频登记asset ID、源路径、格式/长度信息，MIDI登记clip/note稳定ID。所有armed轨的一次take应作为一次可撤销事务；Undo移除片段但保留录音文件，Redo重新引用同一文件，不重新录制。主线程只提交已准备元数据和绑定；文件哈希与归档进入worker。要覆盖结束时没有音符、录音不足一块、磁盘错误、输入断开、最后note-off缺失和停止过程中关闭窗口。

录音期间保存请求应合并并排到finalizing完成后，再保存完整一致版本；不能复制仍增长的WAV，或先显示saved再补录音片段。Save/close提示须区分录制中和后台落盘中。监控实际writer积压和停止耗时，遇到未能落盘的take保持恢复位置并显示失败。

MIDI使用硬件时间戳与引擎时钟，不按GUI timer采集。空轨默认输入通道策略必须可见；当前schema限制每clip单通道，录入多通道应拆片段/轨或在schema中明确扩展，不能丢通道。除notes，还应保留键盘常用CC64、其他CC、pitchbend与压力事件；否则SL GRAND踏板录完无法重现。建议typed channel-event DTO，禁止无提示抛弃。SysEx/TempoMap可先明确不支持，不能冒充完整MIDI录音。

每轨监听需要明确实现选择：固定引擎模式是输入全局，可暂呈现为输入设置；若UI采用每轨Off/Auto/In，必须增加真实per-destination策略（可核验的小补丁或应用路由节点），不靠改变同一个owner模式伪装独立。输入监听默认off，避免应用启动或打开旧工程时主动打开麦克风反馈路径；用户arm并选择监听后才生效。

## 自动化

先实现真正可绘制、播放、Undo及保存的音量、声像、send gain和已加载插件参数曲线；不以静态折线UI代替实际音频处理。一个lane用稳定`lane_id + owner_track_id/plugin_slot_id + parameter_id`定位，插件附版本/身份；缺失或参数不匹配保留lane并标记unresolved，不能绑定到同序号的其他参数。

状态仍放引擎`AutomatableParameter::getCurve()`；命令先校验有序有限点、时间范围、值范围和点数上限，手势结束一次提交一次Undo。固定`AutomationCurve.h:80/89/93`提供add/move/setCurveValue，曲率范围-1至1。初期时间单位统一秒；UI可映射当前固定BPM显示拍位，改BPM时不偷偷改变绝对时间曲线。API返回明确单位及normalized值，适配器通过`valueRange.convertFrom0to1`转换内部值，避免把音量fader值当dB。

保存静态参数使用`getCurrentExplicitValue()`；当前播放值只作为显示值，曲线读出不触发工程revision或完整插件state快照。已有PluginHost监听必须区分用户写入与引擎automation回放，特别是插件会把宿主写入回报为parameterChanged的情况。可复用AutomationRecordManager的read/write模式，但本阶段至少read/bypass和可编辑曲线要实际工作；Touch/Latch/Write录自动化应单列实现和验证，不从曲线编辑推断已具备。

验收必须实际render：音量渐变的分段RMS趋势、声像左右声道能量、发送曲线只影响湿声、已测试插件参数自动化前后不同；保存重开后同设置render等价，播放/seek/loop的曲线位置一致。曲线回放期间不产生额外Undo/dirty/保存循环。官方[AutomationCurve文档](https://tracktion.github.io/tracktion_engine/classengine_1_1AutomationCurve.html)只用于概念参考，其当前签名与固定版本不同。

## 路由

可用的第一阶段应包括普通轨 → 组总线 → master、独立return轨、每轨多send、pre/post-fader、明确硬件输入/输出选择。输出和send都保存目标稳定ID，而不是名称或位置；bus/return的插件链与普通音轨复用。任意插件多输出、侧链、外部硬件insert和反馈路由须明确另验，不能因有一个bus就声称所有复杂路由完成。

复用`TrackOutput::setOutputToTrack`及`AuxSendPlugin`/`AuxReturnPlugin`；发送在pluginList中位于fader前/后决定pre/post语义。应用为send和return分配稳定ID、明确bus-number映射，存储目标track ID，加载后重新解析内部bus号。内置路由节点与外部VST槽分离，不把aux节点序列化成需要厂商扫描的外部插件。

编辑前将所有直接output、send及未来sidechain边作为有向图做DFS/Kahn校验：拒绝自环、两轨互送、bus经return间接回流。引擎TrackOutput只检查直出递归，不能替代应用对send边的整图检查。修改先校验完整候选图再一次事务提交；删除目标要明确拒绝或一次事务把所有引用改为master/删除send，Undo恢复图及参数。录音期间拒绝破坏录音目标的路由/轨道删除。

主输出导出与离线worker必须恢复相同路由和曲线；不能只在可见UI进程接线。测量直出+send没有重复放大错误、pre-send不随源fader变化、post-send随fader变化、mute/solo及bus solo的行为、latency compensation、Undo与重开。官方[TrackOutput](https://tracktion.github.io/tracktion_engine/classengine_1_1TrackOutput.html)与[AuxSend](https://tracktion.github.io/tracktion_engine/classengine_1_1AuxSendPlugin.html)提供概念，固定版方法以源码为准。

## schema4及Agent契约建议

新增持久字段：`track.kind=audio|instrument|bus|return`、`input {device_id,display_name,channel_indices,midi_channel}`、`output {kind:master|track|device,target_id,channels}`、`sends [{id,target_track_id,gain_db,pre_fader,enabled}]`、`automation [{id,owner/parameter identity,bypass,points:[{id,time_seconds,value_normalized,curve}]}]`、必要的`clip.midi_events`。arm/monitor是易产生声音的会话状态；打开工程保留输入选择但默认disarm/monitor off。具体结构由存储和引擎负责人先对齐，不能两人各加一份模型。

schema1–3只读迁移，新增字段缺省直出master、无send/curve、未arm；覆盖前继续旧清单精确备份。schema4校验外键、类型、cycle、参数身份、总点数与MIDI事件上限。不可识别新语义明确拒绝，不能旧代码保存后悄悄擦掉路由。

建议公共命令：`get_audio_devices/get_midi_inputs/get_recording_state`；`configure_audio_device`；`set_track_input/set_track_armed/set_track_monitor`；`start_recording/stop_recording`；`set_track_output/create_send/update_send/remove_send`；`list_automation_targets/get_automation_points/write_automation_points/set_automation_enabled`。现有工程身份、预期revision、request_id和分页继续沿用；设备变化、录音进度和meter属于运行状态，不能每个音频块推进revision。最终take提交和曲线/路由编辑才产生音乐事务。

## 实施拆分与验收顺序

1. 保存负责人先完成当前两audio+插件MIDI复现、主线程耗时分段和保存一致性；当前保存卡住时不要同时加入录音finalize等新阻塞点。
2. 固定ASIO依赖与设备枚举/选择、schema4 DTO及迁移契约；不默认切用户设备。确认M-Audio实际协商参数后单列硬件验证。
3. 录音输入/arm/monitor/状态机与完成take认领；独立synthetic fixture测试无需录用户麦克风。固定引擎`testing/EnginePlayer`和`WaveInputDevice.test.cpp`已用HostedAudioDeviceInterface模拟音频输入、块大小和延迟，可作为真实路径测试基础；不是假调用“插入一个音频clip”充当录音测试。
4. 自动化、bus/send图及离线恢复，补实际render、Undo和schema往返测试；UI负责人使用统一命令和快照，不另持音乐状态。
5. 用户确认M-Audio/SL GRAND后实际设备录音，覆盖停止、保存、重开和回放；将硬件测试与合成设备测试分别记录。之后做带录音/保存/插件负载的持续播放性能，而非只测空轨API。

建议文件归属：引擎新增 `EngineSessionRecording.inc`、`EngineSessionAutomationRouting.inc`及对应录音/路由smoke；ASIO用独立bootstrap脚本。根代理统一接入EngineSession.cpp成员/listener/include、Commands/Public分发、EngineSession.h快照和CMake，避免和保存hot-path负责人冲突。ProjectStorage.h/.cpp仅由存储负责人按先对齐的schema4契约改写；UI/Arrangement/PianoRoll由界面负责人独占。所有源码冻结后再统一构建/测试，保留前后指纹。

验收不能仅看编译或播放按钮：最少包括正确音频样本/长度、MIDI音符与踏板事件、录音结束后一次Undo、并发保存队列、设备拔插、路由cycle拒绝、曲线实际音频变化、复开工程完整性、真实ASIO采样率/块大小和欠载。输入上限不作为性能承诺。当前文档中的全部新增能力仍处于设计阶段。

## 2026-10-27 实施接线附记（源码已写，尚未编译或验收）

本轮实际新增 `EngineSessionProduction.h`、`EngineSessionAutomationRouting.inc`、`EngineSessionRecording.inc`、`tests/EngineSessionProductionSmoke.inc`、`scripts/bootstrap_asio.py`。原有章节中的提案以本节最终契约为准。根代理负责现有 EngineSession、命令、快照、内容摘要、CMake 接线；保存代理负责 schema4 DTO/持久化与 SMF 导出；界面代理负责 UI。新增代码状态仍是“待集成验证”，不能将本节当成已通过测试的报告。

最终 schema4：track kind 为 audio/midi/bus；inputDeviceId、outputTargetId（master 或 bus ID）、sends{id,targetTrackId,gainDb,preFader,enabled}、automation{id,target,pluginId,parameterId,enabled,points{id,timeSeconds,value,curve}}。masterAutomation 的 target 只允许 master_gain/plugin_parameter；轨道只允许 track_gain/track_pan/plugin_parameter。value 为 0..1，适配器转换为参数原生范围；timeSeconds 严格递增，curve 为 -1..1。clip.controllers 保存 Tracktion CC/program/pitchwheel/pressure 类型、14 bit 值、beats、metadata。SysEx 与 MPE 不在本轮能力声明中。每轨32 sends、项目512 sends，每owner256 lanes、项目4096 lanes、项目100000 points与100000 controllers。

新命令：set_track_input、set_track_armed、set_input_monitor、start_recording、stop_recording、configure_audio_device、set_track_output、add_send/update_send/remove_send、set_automation_lane/remove_automation_lane。读接口：get_recording_inputs、get_recording_state、get_audio_devices、get_automation_targets。monitor 明确是输入设备级 off/auto/on，共享同一输入的轨道共享其模式，不伪装成独立的每轨monitor。录音为线性新take，loop打开时拒绝录音；audio为overlay，MIDI不合并或覆盖已有片段。关闭工程与设备切换前必须先完成录音。

录音调用原生 InputDeviceInstance 和 TransportControl。recordingAboutToStop 第一次回调开始“Record take”撤销事务，recordingFinished为原生片段、音符、controllers分配稳定ID、为WAV认领asset/source。poll待所有输入停止后只返回一次完成信号；根代理随后inspect/登记录音音频、重建bindings、刷新长度、一次recordEdit、再开启新事务。录制及finalizing期间拒绝音乐/路由编辑；保留Stop。Undo移除take片段而不删除其源文件，Redo继续引用同一个文件。仍须用测试确认多输入一次撤销、设备断开及native writer停止耗时。

路由使用实际 AuxReturn/AuxSend 原生插件；直接输出和全部发送（含disabled）共同校验DAG，自环、间接cycle、重复target拒绝。internal辅助插件不带emId，不混入外部插件槽/保存通知。pre/post根据fader前后位置实现。曲线元数据仅记录身份，已解析参数的points以原生AutomationCurve为权威；缺失插件才保留未绑定points，避免误绑其它插件。保存轨/主fader使用getCurrentExplicitValue。固定引擎curve.bypass不使用UndoManager，故代码明确经state.setProperty写入；send gain原生setGainDb也不自带撤销，故另用SendGainChange。

设备配置停止播放后执行，失败恢复旧driver type与AudioDeviceSetup，并报告回滚失败。get_audio_devices只有显式scan=true时扫描驱动；30Hz快照不扫描硬件。ASIO bootstrap固定官方SDK包与各头文件SHA256，不安装驱动，不修改注册表；执行权由根代理通过Recorder统一掌握。本附记写入时未执行该脚本。

新增ProductionSmoke包含：cycle与无效curve拒绝、native curve及Undo/Redo、actual render对比直接输出/parallel send能量、curve改变导出音频、HostedAudioDeviceInterface生成的音频+MIDI+CC64同步录音、片段认领与一次Undo/Redo。合成输入不触碰麦克风或物理MIDI。真实M-Audio/SL GRAND、ASIO实际协商buffer/rate、插件自动化、持续负载与保存回归由根代理单独执行记录。仍不宣称零分配无锁录音、全矩阵sidechain/多输出、循环comping、Touch/Latch/Write或全部硬件通过。

更正：本项目MIDI轨道沿用既有持久类型 `instrument`，因此最终track.kind为audio/instrument/bus；`midi`仅用于clip.kind。录音输入匹配与测试已遵循该既有模型。
