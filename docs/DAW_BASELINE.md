# 0.5 DAW 基础功能与验收清单

2026-10-29补充：本文保留0.5基础版本验收范围。0.5.2的Keyscape/MIDI保存及后续音频录音/混合工程已获用户确认；0.6新增日常操作的当前任务与证据请看[DEVELOPMENT](DEVELOPMENT.md)、[CONTEXT](CONTEXT.md)及[快速上手](QUICKSTART.md)，不要用下表历史通过项替代新版验证。

日期：2026-10-27。状态：**0.5基础编曲版本已交付并同步GitHub main；Debug / Release各5/5、三轨原生保存、指定插件/硬件矩阵与16轨无插件30分钟长跑通过。** B01仍缺回调P99.9和物理输入到绘制时延。原生按钮操作、组合键注入、实体演奏与听感分别记录，不能从组件检查推断全部通过。最新执行状态见[CONTEXT](CONTEXT.md)，旧内容保留在[0.4历史清单](history/DAW_BASELINE-v04.md)。

## 已锁定需求

- 默认120 BPM、4/4。固定节奏20–300 BPM（固定引擎上限），默认1/16网格，可关闭吸附。
- 不做和弦工具、确定性乐句模板，也不开发自有音色。MIDI通过用户已有插件发声。
- Windows x64 VST2/VST3、音频与MIDI录音、ASIO、自动化点/曲线、bus/return/send/轨输出属于本轮范围；32位桥接与真实模型另行排期。
- 音频和MIDI编辑/相应撤销保持同一Edit与无关插件实例，播放不中途主动停止；插件实例变化、工程/设备切换可以明确停止。
- Agent需要真实统一控制接口与可运行本地示例，不增加空聊天面板。

## 实施与验收状态

| 项目 | 状态 | 验收 |
|---|---|---|
| schema4 与统一音乐状态 | 已实现，Debug/Release 通过 | schema1/2/3 迁移与备份、插件状态、录制控制器事件、路由/曲线持久化；旧素材不自动清理 |
| 统一命令、增量事务 Undo、120 BPM | 已实现，Debug/Release 通过 | 手势一步撤销、批次原子、版本冲突/幂等、Edit及无关实例保留；GUI和Agent共用入口 |
| 音频编辑、混音与输出 | 已实现，Debug/Release 实际渲染通过 | WAV、48 kHz CBR MP3、44.1 kHz VBR MP3；移动、裁剪、分割、复制删除、淡化、撤销、保存重开及源字节保护；WAV/MIDI导出 |
| 主编曲窗与底部 MIDI 编辑器 | 已实现，Debug/Release 组件及部分原生操作通过 | 单轨头、最后轨道滚动可达；双击 MIDI 打开底部编辑器，首次适配音高，最小窗口保留至少两轨；原生三轨紧凑视图、音符拖动与Undo恢复已验；OS组合键和DPI另列边界 |
| 轨道设备链与录音入口 | 已实现，Debug/Release 组件/引擎通过 | 选轨后就近打开插件、设置 I/O、Arm、共享输入 Monitor、Record/Stop；录音收尾期间禁工程编辑和切设备 |
| ASIO 与受控设备设置 | 已实现，组件与指定硬件通过 | Driver/Input/Output/Rate/Buffer 经统一命令 Apply；实际值回读、拒绝回滚、新输入默认监听关闭；M-Audio ASIO48000Hz/256原生表单及短输入录音已有独立记录 |
| 音频与 MIDI 录音 | 已实现，Debug/Release 合成输入通过 | 124 项生产模块检查包含真实引擎录音、音频样本/MIDI音符与踏板、稳定 ID、整次录制 Undo/Redo及保存重开；不等于实体键盘已演奏验证 |
| 自动化与路由 | 已实现，Debug/Release 实际渲染通过 | 增益/声像/主输出/插件参数目标、点和曲线编辑；bus/return、pre/post send、轨输出、整图拒绝环路；Undo及schema4往返 |
| 保存反馈与增量归档 | 已实现，组件/存储及原生按钮流程通过 | 普通 Save/Save As反馈、Serum原生编辑后dirty清除及新进程回读；12次Ctrl+S合并仅为组件注入验证；快速失败重试、迟到编辑、有界后续保存、媒体复用与旧目标保护 |
| VST2/VST3 宿主 | 已实现，四款指定插件通过 | Serum VST3、Ample Bass P VST2、Auto-Key 2 VST3、BM-DOPE VST3的扫描/参数/Undo/恢复/保存重开/非零渲染通过；Serum通知32项及原生MasterVol编辑已验；不推断所有插件、音色或版本兼容 |
| stdio JSONL Agent 控制 | 已实现，Debug/Release 协议/输出隔离通过 | 显式启用、有界队列、分页、任务状态和统一录音/设备/路由/曲线命令；不含模型或聊天面板 |
| 性能与最终交付 | V509指定范围交付完成 | 双配置各5/5、三轨保存、指定插件/硬件矩阵、10万音符短测及16轨无插件30分钟长跑通过；长跑xrun0，内存变化已记录，用户33文件哈希未变；GitHub已同步，B01完整验收和输入/听感限制保留 |

### 本次通过证据与适用范围

- [最终候选 Release 检查](builds/20261027T014338.621504Z-71806cf8f6.json) 与 [Debug 检查](builds/20261027T014517.945704Z-e8baa314a1.json) 对应同一源码指纹 `34eb7d59f81aac2e98ca90500e8dcce3bb3ce0c23a5c0f6b6fce59d2188c4676`，两次执行首尾均未变化。各5/5是日志、引擎补丁契约、核心契约、引擎集成和控制通道输出隔离五组检查，不是五款插件。
- [当前双配置摘要归档](verification/2026-10-27-v05/34eb7d59-dual-config-summary.json) 固定当次两个 latest.json；原产物目录分别为 `build/smoke/Release/15fb2ff96804` 和 `build/smoke/Debug/e1382d1549d2`。两配置均通过工程202、片段317、存储103、生产模块124项检查；DAW断言数分别为Release801、Debug766。当前指纹相对6414b6c8只改变`tests/AgentJobsSmoke.py`和`tests/EngineSessionDawSmoke.inc`，应用源码未变。摘要保留 scope、原始路径、精选产物哈希及这项差异；[6414b6c8双配置摘要](verification/2026-10-27-v05/6414b6c8-dual-config-summary.json)、[a5da803c双配置摘要](verification/2026-10-27-v05/final-dual-config-summary.json)和[此前Release摘要](verification/2026-10-27-v05/release-check-192926-summary.json)全部保留。
- 同份摘要中的保存组件证据为 `dirty=false`、任务数2→3、按钮重新可用、状态 `Saved`、错误为空；快速失败 SaveAs 不执行关闭回调，迟到编辑保留工程打开，连续请求不会无限重试。轨道滚动、MIDI dock、自动化面板和受控设备设置的组件检查同时通过，原生鼠标/键盘和实际设备配置不由这些注入组件夹具证明。
- 精选合成工程截图为 [1000×650](verification/2026-10-27-v05/34eb7d59-release-ui-1000x650.png) 与 [1280×800](verification/2026-10-27-v05/34eb7d59-release-ui-1280x800.png)；独立 [立即重试报告](verification/2026-10-27-v05/34eb7d59-release-job-retry-report.json)、[工作台报告](verification/2026-10-27-v05/34eb7d59-release-arrangement-report.json) 和 [生产模块报告](verification/2026-10-27-v05/34eb7d59-release-production-smoke.json)已归档，Debug对应文件及哈希在双配置摘要中。截图只含合成测试音频，无用户音乐或工程文件；所有旧前缀与`final-*`文件保留原来源，不覆盖。
- 最终候选的[三轨播放中8次保存](builds/20261027T014649.523033Z-3deefd0d0b.json)通过，详见[报告](verification/2026-10-27-v05/34eb7d59-playback-save.json)。两轨音频＋Serum默认音色，M-Audio ASIO实际48000 Hz/256，保存总耗时93.36–170.83 ms，驱动xrun增量为0；覆盖未变素材复用、受理后编辑仍dirty及重开一致。此短时API测量不等于听感连续性或复杂插件负载保证。
- [原生界面记录](verification/2026-10-27-v05/native-ui-summary.json)覆盖两条394.37秒音频＋Serum：Save As/Save、Serum原生MasterVol改变→dirty→Save清除、播放中保存、音符拖动与Undo、紧凑三轨可见及ASIO表单Apply。该流程来自6414b6c8应用；最终34eb7d59候选另做[新进程回读](builds/20261027T014644.979910Z-11672c5c45.json)，[恢复报告](verification/2026-10-27-v05/34eb7d59-native-reopen.json)确认原生保存的参数、三轨与clean状态，源清单未改写。
- 同一应用实现的[四插件矩阵](verification/2026-10-27-v05/6414b6c8-plugin-matrix.json)、[Serum通知32项](verification/2026-10-27-v05/6414b6c8-plugin-notification.json)和[M-Audio短输入录音](verification/2026-10-27-v05/6414b6c8-hardware.json)已通过，按6414b6c8原指纹保留。该次物理输入实际48000 Hz/256，约2.009秒mono 24-bit，收尾约71.50 ms，xrun增量0；不代替实体MIDI键盘演奏或人工试听。
- [较早三轨 Serum API 保存](builds/20261026T185857.155747Z-b5d66c012e.json)、[Serum20项通知/保存重开](builds/20261026T185830.754109Z-ce021a9d95.json)及 [M-Audio ASIO短录音](builds/20261026T190521.115296Z-b56bacfa9d.json)保留为历史记录。该次录音实际44100 Hz/256，48 kHz请求被拒绝并回滚；不覆盖当前已成功打开的48000 Hz配置，也不代替物理MIDI键盘验收。后续矩阵与原生操作汇总见 [本轮验证记录](verification/2026-10-27-v05/RESULTS.md)。

原生Space可用；Sky瞬时Ctrl+S注入未产生保存任务，修饰键状态读取时序仅是候选原因，尚未实证。不能把组件构造的Ctrl+S合并测试当作全部OS快捷键通过；鼠标Save/Save As已有实测闭环。实际键盘、听感和未覆盖的录音UI流程保留限制。

## 架构决策

活动音乐状态仍归Tracktion Edit。瞬时DTO用于命令预校验、保存及候选打开；不建立另一个可任意修改的音乐模型。普通操作通过引擎ValueTree事务增量更新，撤销不再重建全Edit。应用稳定ID、源素材引用与插件槽元数据纳入相同事务。

工程revision变化时更新结构快照，播放头按30Hz单独读取；音符快照及内容摘要按片段缓存，仅音符/序列变化才失效，混音修改复用共享不可变向量。小批音符修改采用共享音符视图及写时复制，MIDI缩略图缓存可见概览，edit_notes不为单音符操作展开全片段JSON。原生插件状态在保存/导出及结构删除前的恢复缓存等明确边界采集，不能每帧获取；插件持久身份使用规范扫描标识，不因播放准备后描述符变化误判工程已修改。

音频采用sincMedium；固定Tracktion基线包含HQ源定位与外部参数自动化回传两个可核验补丁。前者修复44.1→48kHz的块相关调制和裁剪亚样本相位问题，后者避免自动化回传覆盖用户手动基础值。补丁、前后哈希及schema2清单进入版本管理，详见 [依赖说明](DEPENDENCIES.md)。

文件任务单个重任务执行。保存先显示状态并受理，原生插件状态按槽位在控制线程捕获，worker复用未变媒体并提交原子清单；成功时只清除所保存代次，失败任务及时回收，立即重试不会被已结束worker挡住。文件哈希/MP3准备/复制使用取消检查；音频线程不执行应用文件/JSON/网络工作。导出使用独立进程和固定快照。

录音由固定引擎的InputDeviceInstance、Transport及writer完成，结束后统一认领片段、控制器和素材，并组成一次撤销。音频设置面板只通过同一设备命令修改配置，不再直接操作AudioDeviceManager；录音及收尾时后端拒绝配置。自动化点/曲线与路由归属活动Edit，界面仅保留手势预览，不能形成第二份可写音乐模型。

控制协议仅显式启用本地stdio，GUI和Agent调用相同命令语义。写请求有request_id/project_id/expected_revision；读快照不带全部音符，get_clip_notes分页。accepted仅表示异步受理；完成状态由任务查询和事件给出。扫描worker禁止主进程回退；运行中插件仍在DAW进程内，不能宣称已实现插件实时沙箱。

## 性能门槛

沿用开发计划B01：本机接电、记录系统/设备/缓冲，16条立体声WAV，48kHz目标256samples，预热2分钟再测30分钟。设备不支持的配置写未测，不能用实际480samples替称256通过。音频处理P99.9目标小于单块预算80%，检测欠载目标0；常见交互P95目标小于50ms。插件负载、UI交互、磁盘任务及内存趋势分别记录，输入对象上限不是性能承诺。

同一应用实现的6414b6c8[100000音符Release测量](builds/20261026T195406.132690Z-21b502a8a0.json)覆盖**停止播放、无插件的JSONL往返**：声像P95约11.72 ms、快照约11.91 ms、单音符修改约26.42 ms，Undo/Redo通过。0.4的[历史记录](builds/20261026T170525.513639Z-4f33e20459.json)保留；当前集成报告中的10001音符单次耗时仍只是夹具诊断。这些数值均不是物理输入到绘制时延。

最终34eb7d59候选的[长跑执行记录](builds/20261027T014700.122339Z-5599e4a30c.json)及[完整报告](verification/2026-10-27-v05/34eb7d59-performance-30min.json)通过。范围为本机Release、隐藏窗口、16份独立合成立体声WAV、无第三方插件，M-Audio ASIO实际48000Hz/256。播放保持运行，控制线程每5秒修改声像；不是持续鼠标操作或重插件工程测试。

| 测量 | 本次结果 |
|---|---|
| 预热 / 正式测量 | 120.09秒 / 1800.012秒 |
| 音频回调 | 337504次；平均0.49296 ms，最大1.7551 ms；单块预算5.3333 ms |
| xrun增量 | 0；来源为驱动计数及宿主回调超时统计 |
| 357次控制线程声像编辑 | P95 1.9308 ms，最大6.1123 ms |
| 消息定时器延后 | P95 2.7411 ms，最大155.95 ms；不是输入到绘制延迟 |
| 进程私有内存 | 226430976 → 227106816字节，增加675840字节 |

报告明确`b01_acceptance_complete=false`：逐回调P99.9分布及物理GUI输入到绘制时延未测。回调均值/最大值不能替代缺失的分位数，隐藏窗口结果不能替代可见工作台持续交互；也不据一次内存曲线宣称没有泄漏。复杂插件负载、实体键盘与听感保留各自验证范围。

用户项目测试只用副本。[最终完整性记录](verification/2026-10-27-v05/34eb7d59-final-integrity.json)确认33文件、410250775字节全部SHA256不变，源码及Release EXE在长跑期间不变；逐文件清单留在本地忽略目录，不发布用户素材。构建/测试统一dev.py记录首尾指纹、失败与原日志；源码和精选档案已同步[GitHub](https://github.com/TonyWang2182/E-Musician)，发布记录见[CONTEXT](CONTEXT.md)。

任意插件多输出/侧链、硬件insert、反馈路由、复杂take/comping、TempoMap、音频拉伸、Touch/Latch/Write自动化录制、32位桥接、运行期插件沙箱、分轨/转录和模型Agent不属于本次已实现范围。MP3仅导入/播放，不导出。
