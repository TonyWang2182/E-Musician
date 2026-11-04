# ADR 0012：Focus + Mix 使用原生呈现层迁移

日期：2026-11-04（Asia/Shanghai）。状态：接受；验证进度见 CONTEXT。

用户已批准把 2026-11-02 的 Focus + Mix 设计接入实际应用，要求保留当前版本及全部功能。HTML 设计稿仅作为布局、配色与交互参考，不能替代已有生产能力。

保持 JUCE/Tracktion 原生实现。MainComponent 增加三个工作区和常驻混音栏；ArrangementView/PianoRoll 继续采用原有可视索引与有界绘制。FocusTheme 集中调色和字体。MixerView 是 EngineSession 快照的只读投影，通过既有 execute 和 gesture API 修改工程；没有新的音乐模型或单独 Undo 栈。真实电平来自原 telemetry，低频结构变化刷新控件，高频电平变化只重绘电平矩形。

原 SelectedTrackPanel 的设备、I/O、发送、自动化以及 Master 入口保留。片段精确起点/属性改到工作区下方；Source 和 MIDI Dock 继续可达。完整 MIDI 页并不采用原型的音域/音符限制。细网格、三连音、鼓步进、保存保护、任务取消及本地 Agent 协议均保留。

不修改音频回调、存储 schema、插件状态序列化或 Agent 命令。旧版 0.6.1 保留源码分支、EXE/PDB 和源码 ZIP；新版本为 0.7.0，独立功能分支，原工程/设置做哈希对照。

代价：原 UI 文档部分历史描述需由本次迁移文档明确覆盖；新增混音视图需要生命周期、共享手势和最小窗口回归。真实设备、第三方插件窗口、Windows DPI 与物理键盘焦点仍需人工短测，离线通过不能推断这些场景全部通过。
