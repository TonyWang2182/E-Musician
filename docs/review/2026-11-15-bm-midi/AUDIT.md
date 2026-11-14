# BM / MIDI 独立审查

日期：2026-11-15。范围：只读源码审查；本文件不代表实际插件窗口、声卡或听感已通过。主线构建与实测由本轮结果档案记录。

## 修复前发现

1. `cmake/patches/tracktion/per-track-monitor.patch` 明确使 `auto` 在轨道 armed 时允许实时输入。用户本轮要求只有 `on` 可监听，因此这是需要更新的既有语义；`tests/EngineSessionProductionSmoke.inc` 原有 Auto 断言也必须同步改变，不能只修改 UI 文案。
2. `EngineSessionRecording.inc` 的旧 `set_input_monitor(input_device_id)` 路径会把所有引用该设备的轨道一起改为给定模式。GUI 已传 `track_id`，但旧 API 仍可能影响多轨。新契约应消除含糊的设备级写入，并同步 Agent/API 文档。
3. 实际音频图在 Tracktion `tracktion_EditNodeBuilder.cpp::createLiveInputsNode` 构建时调用逐轨 `isLivePlayEnabled`。只测该返回值不足以证明已分发的输入、持续音或声音输出隔离，需要实际 MIDI 注入和音频处理矩阵。
4. 固定 Tracktion 源码 `tracktion_MidiInputDevice.cpp::valueTreeChildRemoved` 在移除某个输入目标时调用 `injectNoteOffsToTrack()`；后者遍历**全部剩余目标轨道**，向其发送输入设备正在持有的 Note Off。切换或清除 A 轨输入会存在切断 B 轨持续音的路径。修复应定位被移除的目标，不能把清理广播给其他轨道。此项是代码路径证据，实际回归仍须记录。
5. `ExternalPlugin::midiPanic()` 仅置本插件的原子标志，音频处理时向本实例发送 Note Off/CC64；原生 Instrument 也有本实例的待处理 panic。它们优于设备级广播，但会影响同一插件的片段音符，须明确测试“Monitor Off 后正常片段回放”与停止实时持续音的边界。
6. 原插件探针的“创建 editor / 隐藏 peer”不等于真实厂商窗口附着通过。本轮 BM 重现应包含真实 native editor attach、关闭、重开及多实例；扫描成功、离线渲染成功分别记录。`NativePluginUI` 的异步 recreate 与 Tracktion 实例重建生命周期是审查点，尚不认定为本次崩溃根因。
7. 监听命令原路径调用 `TransportControl::restartAllTransports(engine, false)`。固定 Tracktion 的该函数会对所有活动 transport 调用 `stopIfRecording()`，并非仅刷新目标 Edit。**现有公开命令和 RecordingController 均在录音/收尾时拒绝相关变更，因此这不是已证实的同工程录音中断问题**；其风险是超出目标 Edit 的副作用及未来内部绕过保护的调用。实现改为目标 Edit 刷新更明确；验收应确认被拒绝的操作不会影响现有录音。
8. GUI 路径复查：`WorkspaceBrowser::activate` 已复制条目与回调，`PluginPanel::beginAdd/run` 已使用 SafePointer 并在原生调用后再次检查，因此不能再次把这些旧问题认定为本次崩溃根因。剩余待验证的风险是厂商初始化/窗口调用若泵送消息，`MainWorkspace::activateLibrary` 同步添加和 EngineSession 公开编辑入口缺少统一的重入排斥；重入的 new/undo/remove 等可能改变外层调用正在使用的 Edit。需要可控重入用例或实际崩溃栈后才能升级为确认根因。

## 必须覆盖的验证矩阵

| A 轨状态 | 实时键盘 | 全局录音后 A 新录音 | B 轨要求 |
| --- | --- | --- | --- |
| Monitor Off / Rec Off | 无实时声 | 无 | B 状态和输入不变 |
| Monitor On / Rec Off | 有实时声 | 无 | B Off 仍无实时声 |
| Monitor Off / Rec On | 无实时声 | 有 | B 未 armed 不得出现新录音 |
| Monitor On / Rec On | 有实时声 | 有 | B 依自己的 Monitor/Rec 工作 |

附加检查：

- 两轨绑定同一 MIDI 输入；分别切换 Monitor/Rec，按反向顺序再测一次。
- 两轨均 On 时允许二者同时响；只关 A 后 B 的持续音保持，A 的实时持续音和踏板不悬挂。
- A 清除或更换输入时 B 的持续音、CC64 状态和 Rec 标志保持。
- MIDI 输入固定通道映射和 MPE 开启时重复持续音关闭检查。实时输入传递原始 `sourceID`，消费者可能重映射通道；清理消息必须匹配真实到达装置的来源和通道，而不能仅通过通道 1 的非 MPE 用例推断。
- B 正在录音时切换 A 的 Monitor、Rec 或输入，B 应持续录音；若某种操作暂不允许，应给出明确提示，不得悄悄停止全局录音。
- Monitor Off 下既有 MIDI 片段仍可正常播放；On/Off 不应删除音符、修改音高或改变路由。
- 多条 Rec 开启时各自录入；Rec 关闭的轨道不应因为选中、输入相同或另一轨 Rec 开启而收到新片段。
- 关闭并重开工程仍按既有约定全部取消 armed / Monitor Off；保存的音符、装置和输入选择保持。
- 录音切换、停止、删除轨道和插件重开不能导致音频线程执行网络、JSON 或磁盘 I/O。
- BM 各型号分别列扫描、实例化、真实 editor、状态保存重开、音频、退出结果；不将某一型号通过推广为全部插件兼容。

## 审查状态

已将上述具体路径通知实现代理及主代理。最终差异审查、构建与真实音频证据待补记；不控制用户 GUI，不调用付费 API，不修改安装插件或用户偏好。

## 编译前差异复查

- 逐轨监听命令已取消设备级广播；多个目标共用设备时，缺少 `track_id` 的旧请求返回明确错误。旧 `auto` 请求规范为 Off，Rec 不会隐式启用监听。
- 新 MIDI 清理只向指定 AudioTrack 注入源 ID、实际通道匹配的 Note Off 和已踩下的踏板释放；不清空设备级按键状态，不调用全局 panic。审查期间发现“目标已移除后调用 `isLivePlayEnabled` 会跳过清理”的问题，已改为不依赖目标列表的轨道 Monitor 检查。
- `tests/EngineSessionMidiIsolationSmoke.inc` 的设计覆盖 16 种两轨 Monitor/Rec 组合，以实际 hosted graph 左/右 PCM 为判据，并检查双向录音归属、持续音/踏板、清除输入与片段声部继续播放。它使用诊断乐器和虚拟音频设备，不代替用户 MIDI 键盘、驱动或厂商插件听感验收。
- 工程操作重入保护覆盖 GUI/Agent 命令、同步工程接口、transport、后台任务提交和原生采样完成回调；完成回调在外层操作结束后处理。独立下栏定时器保留上一份显示，不在原生调用的嵌套消息循环中重读装置。普通 `executeRequest -> execute/newProject` 未发现自阻塞路径。
- 插件面板延迟添加改为先结束 JUCE one-shot Timer，再通过消息回调进入厂商代码，避免在厂商嵌套消息循环内重入尚未销毁的定时器；包含对应可控嵌套分发用例。
- `git diff --check` 已通过（只有换行规范提示，无 diff 错误）。本次静态复查未发现剩余阻塞项；运行结果以构建/测试档案为准。

仍需准确描述的边界：同一 MIDI 1.0 插件内，片段与键盘使用相同通道、相同音高的重叠声部通常无法按来源独立关闭；当前录音中不允许修改输入/Monitor/Rec，拒绝操作必须保持原录音继续。未取得用户原崩溃栈时，不将加固后的普通加载通过宣称为已证明所有崩溃根因或所有插件长期兼容。
