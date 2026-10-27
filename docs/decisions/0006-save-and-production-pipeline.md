# ADR 0006：可观察保存事务与制作管线

日期：2026-10-27（Asia/Shanghai）。决定已实施；下列证据只覆盖对应场景，持续验收状态见 [CONTEXT](../CONTEXT.md)。本记录扩展 [ADR 0005](0005-daw-baseline-and-control.md)，更新其 schema3、MIDI 控制器及录音/路由/自动化待实施边界。

## 问题与依据

用户反馈两条音频加一条 Serum MIDI 轨保存无反馈。旧版副本基线四次 API 保存成功，但每次增加约 31.57 MB；该结果没有复现 GUI 故障。后续真实通知测试发现自动化回报会改写参数手动基值；GUI 回归又复现快速失败后线程尚未回收，下一次 Save 被误判为忙。不同问题分别处理，不增加插件品牌白名单。详细证据见 [保存审计](../review/2026-10-27-v05/SAVE-AUDIT.md)与 [制作架构复盘](../review/2026-10-27-v05/AUDIO-ARCHITECTURE.md)。

## 决定

### 1. 保存是一项带版本的事务

冻结工程 DTO 并受理 job，随后在消息线程逐个捕获原生插件；worker 负责媒体、内容摘要、序列化和文件事务，消息线程最后确认保存版本。job 暴露阶段、错误、捕获耗时和写入/复用字节。只有对应工程版本与插件代次仍匹配，才能清除已保存的变更；保存期间的新编辑继续保持 dirty。GUI 合并重复快捷键意图，按 job 显示结果，关闭/切换工程前再检查晚到编辑。

原生 VST3 `getState` 保留在消息线程。Steinberg 明确允许实时处理期间从 UI 线程读状态，而 JUCE 暂停处理会返回空缓冲，因此只读 VST3 捕获不主动暂停；VST2 读取和所有加载/恢复写状态路径仍保守暂停。逐插件调度不能中断一个卡住的原生函数，同进程插件不具备强制超时隔离。[Steinberg Processing FAQ](https://steinbergmedia.github.io/vst3_dev_portal/pages/FAQ/Processing.html#q-can-icomponentgetstatesetstate-be-called-during-processing)、[JUCE AudioProcessor](https://docs.juce.com/master/classjuce_1_1AudioProcessor.html)

实现：[EngineSessionJobs.inc](../../apps/desktop/EngineSessionJobs.inc)、[PluginHost.cpp](../../apps/desktop/PluginHost.cpp)。

### 2. 复用已归档媒体，保留原有事务保护

同一 bundle 内确认未变的媒体继续引用原 generation；需要比较内容时由 worker 完成，新增或变化媒体写入新 generation。Save As 向新 bundle 归档。提交前重新检查目标清单及复用文件，取消只清本事务新文件；不自动删除历史 generation。保存成功后更新活动素材引用，保持播放 Edit 和插件实例。

这减少重复媒体写入，不等于所有数据零复制：插件状态块仍重新写入，外部源比较仍有读取成本。旧清单被外部改写、素材丢失和取消不能靠覆盖旧文件来“恢复成功”。实现与失败保护见 [ProjectStorage.cpp](../../apps/desktop/ProjectStorage.cpp)、[StorageV3Tests.inc](../../tests/StorageV3Tests.inc)。

### 3. 参数手动基值与自动化播放值分开

曲线播放值不代表用户编辑。Watcher 通过预建的稳定参数映射过滤已应用值的回报，同时保留真实参数、程序及非参数修改；参数布局变化先失效映射，主线程核验后恢复。pending 变化立即参与 dirty 查询，读取快照不消费通知或额外推进 revision。

固定 Tracktion 的异步参数回报也需要同值检查，避免播放值覆盖 explicit 基值。补丁只约束该入口，初始化和程序刷新语义保留；依赖文件与补丁的哈希由 [补丁清单](../../cmake/patches/tracktion/manifest.json)校验。保存受管插件曲线时，opaque 状态块保持原样，参数回放数据保存 explicit 基值；其他参数仍取 raw 当前值，避免丢掉尚未异步同步的插件编辑。

### 4. 终态可见不等于线程已回收

请求入口可以回收 `done.load(acquire)` 已确认结束、状态为终态且没有待提交结果的 worker，让失败保存立即重试。它不调用完整 timer，不消费插件通知，也不提交前一项导入/打开/保存；这些结果仍由原完成路径处理身份、版本与取消检查。运行中的 worker 继续拒绝重入。

`join` 发生在任务函数返回之后，线程可能仍在销毁其捕获对象，因此不把它描述成严格零等待操作。确定性回归刻意不泵 timer，覆盖失败立即重试、新编辑保留、活动 worker 拒绝及旧版导入冲突：[EngineSessionJobRetryCases.inc](../../tests/EngineSessionJobRetryCases.inc)。

### 5. 录音提交接入同一工程和存储模型

录音复用固定引擎的输入、writer 和 Transport 生命周期；停止后的 finalizing 完成前，拒绝保存、切工程、改设备和音乐编辑，避免归档仍增长的文件。完整 take 才登记稳定 clip/note/controller/asset ID、准备音源并形成一次可撤销音乐事务。Undo 保留源文件，Redo 重新引用。

本轮是线性新 take；监听是输入设备级 off/auto/on，工程重开默认 disarm、monitor off。设备只在显式请求时扫描，配置返回实际驱动/采样率/块大小，失败尝试恢复旧设置。ASIO SDK 固定来源和哈希；启用编译支持、驱动枚举与真实硬件录音分别验收。实现：[EngineSessionRecording.inc](../../apps/desktop/EngineSessionRecording.inc)。

### 6. schema4 保存图语义，Agent 与 GUI 共用命令

活动 Tracktion Edit 仍是唯一可写音乐状态。schema4 增加输入选择、稳定 ID 的输出与发送、轨/主输出/插件自动化以及 MIDI 控制器；轨类型为 audio/instrument/bus，MIDI 片段类型为 midi。schema1–3 只读迁移，覆盖前备份原清单。所有输出和发送共同校验有向无环图，包括停用的边；删除轨/插件清理相应引用。

自动化点使用秒、归一化值与曲率，已解析曲线由原生 AutomationCurve 持有；缺失插件的曲线保留但不误绑其他参数。MIDI 裁切/分割保留控制器，并在边界补必要持续状态，不重放 all-notes-off 等瞬时命令。明确上限控制最坏输入规模，不将上限当性能承诺。[ProjectStorage.h](../../apps/desktop/ProjectStorage.h)、[EngineSessionAutomationRouting.inc](../../apps/desktop/EngineSessionAutomationRouting.inc)

GUI、快捷键和本地 Agent 复用 `EngineSession::execute`、工程身份/预期版本和现有幂等请求机制。新增 `start_recording/stop_recording`、`set_track_output`、`add_send/update_send/remove_send`、`set_automation_lane/remove_automation_lane` 等真实命令；快照与分页读取不建立第二份可写工程。录音状态与设备状态不按音频块递增音乐版本。[EngineSessionPublic.inc](../../apps/desktop/EngineSessionPublic.inc)

### 7. 离线引擎的设置与用户会话隔离

禁用设备自动初始化仍不足以隔离设置：离线渲染或合成输入测试中的 Engine 在销毁时也可能刷新设备配置。因此 `EngineSession(false)` 使用无磁盘文件、禁止保存的内存 `PropertyStorage`，每个实例另有独立临时缓存目录；交互会话继续使用正常持久设置。这样测试设备和 hosted 输入不会成为用户下次启动的设备配置。实现见 [EngineSession.cpp](../../apps/desktop/EngineSession.cpp)，回归验证显式 flush、实例隔离及 Engine 销毁前后用户设置文件的存在性和精确字节：[EngineSessionProductionSmoke.inc](../../tests/EngineSessionProductionSmoke.inc)。

### 8. 插件逻辑身份不随播放初始化改变

首次真实播放保存测试发现：保存完成、xrun 为 0、工程 revision 始终为 11，却仍 dirty。原始[失败报告](../../build/playback-save-smoke/909a6881-f2fd-41c6-a337-3fc5d2361966/report.json)与清单显示，停止时扫描身份是 `Serum.vst3` 包路径，播放后保存成 `Serum.vst3/Contents/x86_64-win/Serum.vst3`。固定 TE 的 `prepareToPlay` 更新运行时描述；原捕获代码直接采用该描述，令最后一次编辑缓存的 `currentKey` 与保存时生成的 `savedKey` 不同。路径还会使重开时精确目录匹配失败。这是身份表示变化，不能通过强制清 dirty 或忽略插件通知修复。

决定以通过扫描与工厂验证的逻辑路径持久化。Windows x64 VST3 仅接受同一包的 `Contents/x86_64-win/<包名>.vst3` 这一准确运行时别名，继续核验格式、class UID、旧 UID、角色与适用的参数状态版本；VST2 保留精确路径比较。已经保存的该种内部路径只能通过对应已扫描条目恢复，随后捕获规范身份；任意嵌套路径、另一模块、错误 UID 或版本继续拒绝并保留状态。原工厂精确匹配不放宽，不增加 Serum 特例。实现见 [PluginHost.cpp](../../apps/desktop/PluginHost.cpp)。

`get_save_diagnostics` 显式读取缓存键、保存键、现场内容键和插件 dirty/pending 标记，用于区分身份变化、旧缓存与真实编辑。现场摘要只在该诊断请求中计算，不加入 timer/常规快照，也不改变缓存键、保存基准或 dirty。播放回归保存失败前的快照和诊断，避免 Stop 改变现场后才取证。[EngineSessionPublic.inc](../../apps/desktop/EngineSessionPublic.inc)、[PlaybackSaveSmoke.py](../../tests/PlaybackSaveSmoke.py)

### 9. 异步验收检查合法完成顺序

打开工程与随后发送的编辑请求存在两种合法顺序：编辑先完成，则旧快照的 open 必须冲突且保留编辑；open 先提交，则旧版本编辑必须被版本/工程身份保护拒绝，已打开的工程保持完整、clean 且没有新增 Undo。测试同时检查响应、任务终态、精确版本和音乐快照，不以“任意失败都可接受”处理竞态，也不靠延迟生产代码制造测试窗口。[AgentJobsSmoke.py](../../tests/AgentJobsSmoke.py)

[第一次脚本失败](../builds/20261026T200021.049195Z-5518d8b367.json)假定编辑总能抢在 open 提交前。实际保存版本为 8，后续编辑为 9，open 正确提交为 10，旧编辑被拒绝；应用行为符合契约。[第二次脚本失败](../builds/20261026T200512.835375Z-ae20213bff.json)来自新增断言误用 C++ 字段 `canUndo/canRedo`，JSON API 的真实字段是 `can_undo/can_redo`。两次仅修正测试脚本，生产代码未变；[最终单项验证](../builds/20261026T200629.975491Z-ba35d36763.json)通过，[报告](../../build/agent-jobs-smoke/071a5a82-97a8-432e-8fa2-e7e5cc2f1158/report.json)保留实际顺序、响应和状态。

## 验证与保留边界

- 修复播放身份后的构建源码指纹 `6414b6c822ea3fddaf205eebba37d050c6ec13a1d299e6ad788325c4f14259f2`：[Release 完整回归](../builds/20261026T195504.062081Z-eb7ee0ca8d.json)与 [Debug 完整回归](../builds/20261026T195640.420355Z-4224db8938.json)均 5/5 通过。
- 后续测试脚本修正使整体源码清单指纹变为 `0f5a27e6d86108284295ea176334eee827e1ebbbd5f45b11cda9de5fe7a7a082`；比较两份记录，唯一变化是 `tests/AgentJobsSmoke.py`。应用源码仍为上述 `6414b6c8` 构建版本，复用的 Release EXE SHA-256 为 `a9e47c8fddd9e2ef315ee5da3ae69ceb3a9a08f9d7dd1573d02071d0963c093c`，不能将脚本指纹变化描述成应用重新构建。
- 同一版本的[播放保存报告](../verification/2026-10-27-v05/6414b6c8-playback-save.json)：两条长 MP3 与 Serum 默认音色，在 M-Audio M-Track Solo and Duo ASIO、48 kHz/256 帧下完成 8 次保存及重开；保存受理约 7.6–11 ms、完成约 98–176 ms，观察窗口 xrun 增量为 0。未变媒体复用、规范插件身份、后续编辑保留及三个内容键一致检查通过。该短测没有测量声学中断，也不覆盖所有音色。
- 同一版本的[通知与身份报告](../verification/2026-10-27-v05/6414b6c8-plugin-notification.json)32 项通过，包含实际运行时描述的规范捕获、准确旧路径恢复、错误模块/UID/格式/角色/版本拒绝，以及同值通知、自动化基值与重开检查；测试未播放或操作原生编辑器。
- 前一版本 `a5da803cc0f51f574872dd10ea519da1e5f1ddf1b75eb08e614f7293de8d3717` 的 [Release 回归](../builds/20261026T193644.413385Z-86ae6583f3.json)与 [Debug 回归](../builds/20261026T193851.440268Z-58797550cf.json)均 5/5 通过；[立即重试报告](../../build/smoke/Release/e7a5867118ce/job-retry-report.json)含 30 项检查，[GUI 回归报告](../../build/smoke/Release/e7a5867118ce/arrangement-report.json)含普通 Save、失败 Save As、重复快捷键合并和晚到编辑检查。保留该结果，不将它当成后来播放身份故障已被当时回归覆盖。
- [真实 Serum 通知报告](../../build/plugin-notification/e5f77859-3bfd-40d8-8507-2963e7b2b44f/report.json)：2397 参数两轮同值通知、真实修改反向检查、强制自动化回报和 explicit 基值保存重开通过；该测试未播放、未操作插件原生编辑器。
- 制作管线 [Release 报告](../../build/smoke/Release/e7a5867118ce/production-smoke.json)与 [Debug 报告](../../build/smoke/Debug/d8c40f8c8004/production-smoke.json)各 124 项检查通过，包含上述内存设置隔离。输入是 48 kHz/256 帧的合成 hosted buffers，不能替代物理音频/MIDI 或 ASIO 验收。

### 最终候选补充：34eb7d59

最终候选完整源码指纹为 `34eb7d59f81aac2e98ca90500e8dcce3bb3ce0c23a5c0f6b6fce59d2188c4676`，Release EXE SHA-256 为 `1a72c25210e296898167db1e33f57f4cbee0b21fa8c358e636917ee8f23024dd`，PE 文件/产品版本为 0.5.0。相对 `6414b6c8`，只有 `tests/AgentJobsSmoke.py` 与 `tests/EngineSessionDawSmoke.inc` 变化，后者编入应用，故最终 EXE 已重新构建；生产功能源文件未变。此前 `0f5a27e6` 仅改 Python 脚本、复用旧 EXE 的记录仍作为当时事实保留。

- 最终候选的 [Release 回归](../builds/20261027T014338.621504Z-71806cf8f6.json)与 [Debug 回归](../builds/20261027T014517.945704Z-e8baa314a1.json)均 5/5 通过，执行前后源码指纹一致；见[双配置摘要](../verification/2026-10-27-v05/34eb7d59-dual-config-summary.json)。`6414b6c8` 的[四款插件矩阵](../verification/2026-10-27-v05/6414b6c8-plugin-matrix.json)、通知及硬件专项保留原版本和原运行来源，不改称全部在最终 EXE 上重跑。
- [原生 GUI 摘要](../verification/2026-10-27-v05/native-ui-summary.json)来自 `6414b6c8`，实际覆盖另存为、Serum MasterVol 拖动后 dirty、鼠标 Save、播放中修改声像并保存、MIDI 拖动及精确 Undo、紧凑三轨可见和 ASIO Apply 回读。瞬时 Ctrl+S 注入没有触发保存，原因尚未实证；wrapper 因 20 分钟无新命令主动结束，整次执行仍记失败。已观察操作作为部分原生验收保留，不扩大为全部快捷键、录音/路由/自动化原生流程通过。
- 最终候选的[原生保存新进程回读](../verification/2026-10-27-v05/34eb7d59-native-reopen.json)恢复上述鼠标保存工程：两条 394.37 秒音频、16 音符 Serum MIDI、MasterVol=0.58157891、轨道 pan=0.19，三个内容摘要一致且 dirty=false，打开前后清单 SHA 一致；见[执行记录](../builds/20261027T014644.979910Z-11672c5c45.json)。
- 最终 EXE 的[播放保存报告](../verification/2026-10-27-v05/34eb7d59-playback-save.json)在两轨音频加 Serum 默认音色、M-Audio ASIO 实际 48 kHz/256 帧下完成 8 次保存，耗时 93.36–170.83 ms，观察窗口 xrun 增量为 0。未变媒体复用、保存期间修改保留、后续保存及重开一致均通过；见[执行记录](../builds/20261027T014649.523033Z-3deefd0d0b.json)。该短测仍不代表声学连续性或所有插件音色保证。
- [探针启动检查](../verification/2026-10-27-v05/34eb7d59-probe-startup.json)在初始化 2.191 秒后单次启动，完成 120.041 秒预热及 2.021 秒短测，持续 playing 且 xrun 增量为 0。它只验证启动与报告路径，正式长跑结果单列如下。
- [最终 30 分钟测量报告](../verification/2026-10-27-v05/34eb7d59-performance-30min.json)通过：[执行记录](../builds/20261027T014700.122339Z-5599e4a30c.json)退出码为 0，源码首尾一致。Windows 11、i7-13700H、Release、M-Audio ASIO 实际 48 kHz/256 帧，16 条独立合成立体声 WAV 循环播放，未加载第三方插件；独立后台实例保留 GUI 组件及定时器，窗口隐藏。完整预热 120.0899 秒，正式测量 1800.0124 秒，全程保持 playing，xrun 增量为 0。337,504 次音频回调耗时均值 0.4930 ms、最大 1.7551 ms；357 次控制线程声像编辑 P95 为 1.9308 ms、最大 6.1123 ms。消息定时器延迟 P95 为 2.7411 ms、最大 155.9507 ms；这些统计不等于物理鼠标到绘制延迟。
- [最终完整性报告](../verification/2026-10-27-v05/34eb7d59-final-integrity.json)确认长跑源码仍为 `34eb7d59`、Release EXE 仍为上述 `1a72c252`，并记录归档长跑报告的字节数与 SHA-256。受保护的 33 个用户文件共 410,250,775 字节，逐文件 SHA-256 全部未变；精确用户文件清单只保存在本机忽略目录，不发布。

完整插件/播放组合、真实输入、持续负载与声学连续性以各自报告为准。长跑通过限于上述合成音频、无第三方插件的隐藏窗口负载，不代表 Serum 持续 30 分钟或可见窗口交互已经验收；部分原生操作和组件回归也不替代实体 MIDI 演奏或人工听感。报告保持 `b01_acceptance_complete=false`，因为回调 P99.9 和物理 GUI 输入到绘制延迟尚未采集，不能将本次通过写成 B01 全部指标完成。侧链、多输出乐器、反馈路由、循环 comping、Touch/Latch/Write、TempoMap、SysEx/MPE 和运行期插件沙箱不属于本轮已验收范围。
