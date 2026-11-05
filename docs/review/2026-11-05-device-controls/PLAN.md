# 矩形片段与原生装置控制迭代

日期：2026-11-05（Asia/Shanghai）。状态：实现及 Release 自动验证完成，真实桌面/设备验收待用户执行；证据见 [RESULTS](RESULTS.md)。

用户确认当前工程使用无明显问题。本轮聚焦现有七种原生装置的实际可操作性和 MIDI/clip 的矩形显示；不把原生装置外观等同于 Ableton 全部功能或算法。

## 实施与文件分工

1. PianoRoll / ArrangementView：音符占满音高行、片段占满片段轨道行，绘制与命中区域统一。保留音乐起止/实际时值、滚动裁剪和已有缩放，不通过拉长音符来填格。
2. NativeEffectsPanel / DeviceControlStyle：共享黑白旋钮、可编辑数值、重置与精调；EQ 频响、Compressor 传递曲线和实测压缩量；Delay 回声示意、Reverb 衰减示意、Auto Filter 频响及调制示意。静态图明确标识，不伪装实时分析仪。
3. NativeDevicePanel / NativeInstrument：Sampler/Rack 真实波形和每垫音量、Attack/Release、Gate/One-shot，增加包络图示及旋钮；沿用统一命令、异步发布和撤销。
4. 核心与接口：EQ 每段可选 bell / low shelf / high shelf / high pass / low pass / notch；旧状态按原有默认值解释。审查发现旧程序忽略新字段会静默变声，故非旧默认形状/包络保存为装置状态版本 2，旧默认保留版本 1。新参数同时接宿主校验、存储、Agent catalog/schema/编译/回读，拒绝无效输入。
5. 集成：检查窄窗、设备切换、参数文本、图示拖动、取消、Undo、保存重开；所有构建通过 Recorder，保留失败记录。源码冻结后重建并验证。

多人文件归属：矩形任务仅改 PianoRoll/ArrangementView；效果 UI 任务仅改 NativeEffectsPanel 和共享控件；采样任务改 NativeDevicePanel/NativeInstrument/core sampler 与对应测试；主代理负责 EQ DSP/宿主、ProjectStorage、Agent、MainComponent 集成和总文档。保留工作树已有未提交内容，不重置、不批量提交历史修改。

## 验收边界

- 自动：DSP 频响与音频测试、接口参数范围/兼容/回读、真实隔离 DAW 保存重开与撤销、UI 合成交互与实际代码渲染图片；完整相关回归。
- 人工：用户检查新矩形与缩放、七种装置的旋钮/图示、音频听感和键鼠输入；不使用 computer-use。
- 性能：不在绘制/音频回调读盘、网络或解码；图示有界，交互本地预览、释放后一次带版本的提交。离线测量不外推 ASIO 或复杂工程表现。
- 不增加付费模型请求；以真实 DAW 命令和模拟 Provider 检查 Agent 接口，不宣称自然语言任务成功率已验。

## 参考（官方来源，2026-11-05 查询）

- [Ableton 音频效果器手册](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/)：EQ、压缩、延迟、混响与滤波的参数分组及图示。
- [Ableton 乐器手册 / Simpler](https://www.ableton.com/en/manual/live-instrument-reference/)：波形和 Controls 分工、包络图与参数联动。
- [FabFilter Pro-Q 4：旋钮](https://prod.fabfilter.com/help/pro-q/using/knobs) 与 [显示和工作流](https://prod.fabfilter.com/help/pro-q/using/eqdisplay)：直接图形编辑、精确输入和细调。
- [W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)：二阶高通、低通、陷波与现有峰/架滤波器的系数参考；曲线和声音使用同一响应计算。

借鉴工作流和信息组织，继续使用 E-musician 黑白等宽风格；不复制品牌皮肤，不以新增旋钮冒充未实现的声音处理。
