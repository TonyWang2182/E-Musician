# 钢琴卷帘、采样器与鼓组 Rack：第一版视觉提案

状态：**用户已确认方向，首版实现及离线验证状态见 [结果](../../review/2026-11-02-device-redesign/RESULTS.md)。** 三张 PNG 是生成的界面示意，波形、音符、轨道、读数和刻度均为示例，不是实际工程截图。

1. `01-piano-roll.png`：当前窗口中展开 MIDI 编辑区，保留返回编曲入口、小节标尺、琴键、网格与力度；支持精确选择和缩放，最终需保持既有 1/16384 网格与 Ctrl+4 吸附约定。
2. `02-sampler.png`：设备留在主窗口下方，以波形、起止范围和根音为中心。当前实际音源使用 0–1 比例保存起止，图中标成秒的数值只是视觉示意；实现前应根据真实样本时长正确换算，不得把比例误当秒。
3. `03-drum-rack.png`：4×4 鼓垫与选中垫详情同屏，底行 36–39、其上依次 40–43、44–47、48–51。当前点击 pad 只选择，已支持真实波形显示；鼓垫范围拖拽和试听仍未实现。

参考 [Ableton Live MIDI 编辑](https://www.ableton.com/en/live-manual/12/editing-midi/)、[乐器](https://www.ableton.com/en/live-manual/12/live-instrument-reference/)和 [Drum Rack](https://www.ableton.com/en/manual/instrument-drum-and-effect-racks/) 的操作结构；Live 的最大化 Clip View 不等同于独立窗口全屏。保留本项目黑白线框视觉，避免将图片中生成的音符、音高标签间距、时间单位或波形当作精确规格；实现须使用实际数据和真实坐标。
