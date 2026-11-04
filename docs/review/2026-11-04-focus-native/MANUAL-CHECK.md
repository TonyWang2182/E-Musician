# 0.7.0 Focus + Mix 人工短测

本页用于新界面真实窗口、键盘焦点和设备体验验收。自动组件渲染与离线音频测试不替代这些项目。先用已有工程的副本，避免把试改覆盖到日常工程。

1. 打开 `build/bin/Release/E-musician.exe`，标题应为 `0.7.0 - Focus + Mix`。打开已有混合工程，确认轨道、音符、插件和音色都在。播放一小段。
2. 在 Arrangement 中看 Clip 是否填满轨道高度。拖动、裁剪一个 Clip，然后 Ctrl+Z。切换 bars / seconds / both；放大，选择 1/16384，再 Ctrl+4，确认实线/虚线切换。音符和片段长度不应被切页改变。
3. 双击 MIDI Clip：下方保留编曲与钢琴卷帘；点 Piano roll：编辑区放大。画一个音符，拖动/修改力度，Ctrl+Z。切回 Arrangement，再切 Mixer，确认没有误删或更改片段。
4. Mixer 中拖动某轨音量和声像，确认右侧选中轨及底部 Master 与同一工程同步，Undo 可恢复。切页后右侧混音区仍在；小窗口出现内部滚动时可滚到通道底部 Details。
5. Devices 或右侧 Details → I/O + sends：确认 MIDI 键盘输入、Arm、Monitor、输出与 Send 都可找到；Automation 与 Master 切换仍可用。试录数秒后停止、回放。
6. Save As 到新名字，关闭后重新打开，确认录音、音符、路由和插件状态；导出 MIDI 或 WAV。最后将窗口缩到最小，看控件是否仍可操作。

有问题时记录“版本、页面、点击顺序、界面错误”；截图由用户提供，不要求重复全部旧版验收。

旧版完整保留在 `releases/0.6.1/E-musician.exe`；其源码分支为 `archive/v0.6.1-before-focus`，源码压缩包在同目录。退出当前版本后可直接运行旧版，无需重装。两个版本使用相同工程格式与用户配置位置；避免同时打开并写入同一个工程。
