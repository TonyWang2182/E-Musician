# Sampler / Drum Rack 控件与参数（2026-11-05）

状态：实现、集成构建和自动验证已完成，证据见 [RESULTS](RESULTS.md)；真实桌面和听感待人工。以下保留分工实现与审查过程。

参考 [Ableton Live 12 Simpler 官方手册](https://www.ableton.com/en/live-manual/12/live-instrument-reference/#simpler)：采样区域和控制区域分工，旋钮与包络节点共同编辑同一参数，Gate 与 One-shot 有不同的音符释放语义。本轮沿用现有黑白等宽字体，没有复刻商标、商业音色或声称具备完整 Simpler 功能。

## 实现

- 六个采样器旋钮：根 MIDI 音高、起点、终点、增益、Attack、Release；鼓组在每个垫提供增益、Attack、Release。使用共享 `DeviceControlStyle.h`，数值可键入、双击复位、Shift 微调，滚轮不意外改值。
- 真实波形旁展示 A/R 包络。两个节点可拖动，Escape 放弃本次图形手势；横向手柄范围按对数映射，不是实时音频测量，也不是完整 ADSR。Gate 的 Release 接收 note-off，One-shot 忽略 note-off，此时 Release 控件禁用。
- 16 垫保持 36–51 从左到右、从下到上的映射。单击选择，已载入垫右下三角或双击可试听；原有顶部 play/stop 保留。
- 拖动只改 UI 预览，释放时走统一命令；工程、版本、pad 变化拒绝旧手势。数值键入也走同一命令。起止不合法会回到权威值并提示。`full sample` 恢复完整采样范围。
- `set_native_pad` 可选 `attack_ms`（0.1–2000，默认 3）、`release_ms`（1–5000，默认 30）、`one_shot`（布尔，默认 Sampler false、Rack true）。旧命令省略新字段时保留已有值；旧 version 1 工程采用上述默认。新增参数与历史默认等价时仍写 version 1；任意 pad 的 A/R/播放模式不等价时写 version 2，让旧程序明确拒绝而非静默丢失音色变化。所有字段由描述接口回读。根任务负责存储验证、能力目录和 Python Agent 映射。
- 参数编辑只在 message thread 复制小型 `PreparedBank` 所有权描述，worker 复用已载入不可变 PCM 和原 SHA-256，仍经原队列提交、版本校验和一次 Undo。换采样、工程加载和 reconcile 保持重新读取/校验源文件。共享所有权不进入音频回调；音频线程仍读取有界固定 bank。

## 加入的检查

- `NativeInstrumentTests.cpp`：字段/类型/范围、旧增益命令保留包络、已载入 PCM 复用（移除独立测试源后仍可准备参数 bank）、显式载入仍拒绝缺失文件、相同素材下 Gate 与 One-shot 的实际音频输出区别。
- `NativeDeviceEndToEnd.py`：真实离线 DAW 异步参数修改、Undo/Redo、旧参数修改保留新增字段、保存和重新打开后的字段回读；沿用原有实际 WAV 渲染检查。
- 面板合成 smoke：旋钮类型、Gate/One-shot 控件状态、Escape 和过时手势、600×212/600×250/700×440/1000×260 布局与截图。高度小于 250 时合并重复的轨道标题与文件操作行，保留文件名、波形/包络和数值旋钮，让主工作区还能看见一条完整轨道；紧凑鼓垫分别放置 MIDI 号和样本名，避免文字重叠。
- 集成首轮发现 Escape 检查对 `.1` 步进的 double 使用 `== 3`；还原值为等价浮点值，已改为 1e-6 容差并检查拖动标志归零。截图在完成失败路径断言后清理诊断文字，使用同一隔离目录中 Waveform smoke 真正生成并校验 SHA 的 WAV，仍明确标注合成面板，不能视为真实用户桌面验收。

## 边界

无 Decay/Sustain、循环、切片、Warp、采样滤波或调制矩阵；A/R 作用于有界采样播放核心，不冒充这些功能。包络图按参数画静态形状，不显示正在播放的包络。参数发布仍会在 bank generation 切换时停止旧 voice，未新增实时无缝参数自动化承诺。冷启动、换样本、Undo/Redo 的重新装载仍可能读取磁盘。人工需在真实工作台确认旋钮文字、拖动手感、鼓垫试听及音色听感。
