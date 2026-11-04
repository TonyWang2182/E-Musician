# Focus + Mix 原生界面独立完成审查

审查完成时间：2026-11-05 00:00（Asia/Shanghai）。审查对象：`E:\E-musician` 中的 0.7.0 C++/JUCE 原生实现。以用户选定的深色 Focus + Mix 方向、工具性优先和保留 0.6.1 功能为约束；独立阅读源码、测试记录并查看组件截图。本审查没有构建、启动或操作应用，没有使用 computer-use，也没有修改产品源码。

## Disposition · 交付判定

**SHIP：可以交付本机短测候选。** 在下述实际检查范围内，没有发现必须先修复的功能入口或视觉布局问题；没有剩余的补拍或重建要求。

这是原生迁移候选的完成审查结论。实际声卡、第三方插件、物理输入和 Windows DPI 的体验确认仍按 [MANUAL-CHECK.md](MANUAL-CHECK.md) 执行，不能据此称为这些场景已经通过验收。

## Evidence · 证据

设计依据为 `E:\MusicAgent&DAW\designs\2026-11-02-focus-mix-v2\DESIGN.md` 及 `previews/arrangement-1440.png`、`midi-1440.png`、`mixer-1440.png`，三张参考图均已查看。审查同时读取 [FEATURE-PARITY.md](FEATURE-PARITY.md)、[CODE-REVIEW.md](CODE-REVIEW.md) 和 `E:\Codex\skills\impeccable\reference\craft-floor.md`。参考图提供方向，不要求用删减原生能力的方式逐像素模仿。

最终证据目录为 [`build/smoke/Release/a3c9360dc861`](../../../build/smoke/Release/a3c9360dc861)。本次直接查看的最终截图包括：

| 范围 | 截图与尺寸 |
|---|---|
| 三个工作区及常驻混音 | `ui-focus-page{0,1,2}-1000x650.png`、`ui-focus-page{0,1,2}-1920x1080.png`；另查 `ui-focus-page{1,2}-1440x900.png` |
| 普通编曲、Source | `ui-1280x800.png`、`ui-separate-1280x800.png` |
| MIDI 原有工具与表单 | `ui-piano-fixture-820x440.png`、`ui-parameters-470x226.png` |
| 所选轨设备、I/O + sends、自动化 | `ui-track-panel-{0,1,2}-752x256.png`、`ui-track-panel-{0,1,2}-1168x272.png`；自动化包含通过真实测试命令写入的两个点 |
| Master 设备 | `ui-master-devices-1168x272.png` |

在此前同一轮审查中，还查看了 `6ad787d7b386` 批次的全部九张工作区尺寸图、最小 MIDI Dock、空工程、插件浏览器、精确片段起点、拖入状态、深缩放与远距离 MIDI 标尺截图。随后补齐详情面板的变更仅增加捕获/检查代码；最终批次的核心视图再次抽查，未发现外观变化或证据冲突。

最终 [CTest 记录](../../builds/20261104T155535.526844Z-66a086799d.json) 和 [日志](../../../build-logs/20261104T155535.526844Z-66a086799d.log) 显示 Release **5/5 通过，101.85 秒**，`source_changed_during_command=false`。[组件报告](../../../build/smoke/Release/a3c9360dc861/arrangement-report.json) 的状态为 `passed`；满轨高、三页保持选择与 revision、共享混音/Undo、同 revision 标量回读、隐藏编辑区快捷键保护、从 Mixer 打开 MIDI、最小停靠尺寸及详情面板控件边界检查均为 true。报告同时保留原有编曲、MIDI、保存、细网格及其他回归结果。

以下当前源码 SHA-256 已实际计算，并与最终测试记录的结束指纹逐项匹配；完整值可在上述记录查询：

| 文件 | SHA-256 前缀 |
|---|---|
| `MainComponent.cpp` | `12e649147b57c80d` |
| `ArrangementView.cpp` | `d2e8efd719a7554b` |
| `PianoRoll.cpp` | `be49f4e058f06f31` |
| `MixerView.cpp` | `81cd2263e8dbb4a3` |
| `SelectedTrackPanel.cpp` | `490fb2970af307ad` |
| `FocusTheme.h` | `bf2dce729a466189` |

字体、颜色、控件绘制和布局源码与截图对应。以不透明颜色 token 计算，正文／面板约 12.53:1、辅助文字／面板约 6.84:1、dim／面板约 5.00:1；这支持基础文字对比判断，不是整个应用的无障碍认证。

## Material findings · 实质问题

**未发现仍需处理的交付阻断项。** 初次证据缺少 SelectedTrackPanel 渲染图，不能用自动化命令通过代替视觉确认；最终批次已补齐设备、I/O、发送、带点曲线和 Master 截图，并增加最小 Dock 可见控件边界断言。这个证据缺口已关闭。

最小详情面板中的标签、输入、发送操作、lane 启停/删除和曲线不相互覆盖，底部提示仍在边界内。参数表单的初始值可读；普通与最小窗口的主导航、工程操作、传输和精确片段起点仍可辨认。缩短后的推子刻度已抽稀，未出现相邻刻度叠字。

[代码审查中的 R1–R3](CODE-REVIEW.md) 已有相应源码保护和最终通过的回归结果：Mixer 不再通过编辑快捷键更改隐藏片段，MIDI 打开入口能离开 Mixer，混音标量在同 revision 的后续刷新中可以回读。这里的结论针对这些已定位根因，不扩大为所有实际输入竞争都已验证。

## Fidelity and function scope · 设计符合度与功能范围

- 深灰连续画布、有限琥珀激活态、平面分隔、方形传输图标、三工作区和固定所选轨／Master 符合选定方向。常驻区在三个工作区的位置和宽度一致；读数来自原生快照，未把原型的虚构设备、CPU/RAM 或电平写进生产界面。
- Clip 填满所属轨道内容高度，名称带和波形／MIDI 预览在同一矩形中。源码的 `clipArea` 同时用于绘制与命中；片段、网格和标尺继续使用音乐时间。标尺按密度减少标签，不靠持续缩小字体容纳全部细分。
- MIDI 保留完整 0–127 音高、纵向滚动、编辑工具、力度、细网格和 16 步鼓控制；原型的 C3–C5 示例范围没有成为原生限制。完整 Piano roll 页补充停靠编辑器，而原有停靠入口仍在。
- 轨道和 Master 增益、声像、M/S/R、实际电平及 Undo 复用同一个 EngineSession。设备链、输入/监听、输出/发送和自动化通过原生详情面板保留；不要求把所有原生参数强塞进原型的简化通道条。
- 本轮未发现为了匹配原型而删除的关键原生能力。功能保留判断由源码映射、历史功能清单及本轮回归共同支持；截图本身不能证明每一种工程、插件和硬件组合都没有回归。

## Limitations · 结论边界

- 截图是离屏原生组件捕获，不含实际桌面窗口、系统对话框和第三方插件编辑器。没有实测显示缩放、跨屏 DPI、真实键盘焦点/鼠标拖动、屏幕阅读器、声卡、录音或听感；最终测试记录也明确保留 `runtime_verified=false`。
- 1000×650 下 MIDI Dock 的音高可视范围很浅，持续音符编辑更适合上方完整 Piano roll 页；混音条底部操作在最小窗内需要内部纵向滚动。截图和源码显示对应完整页／滚动路径保留，这不构成功能删除，也不应描述为最小窗能同时展示所有控件。
- 设备链和 I/O 截图使用隔离测试状态，插件链为空且没有真实录音输入；它们验证空态、禁用态和布局，不验证已加载插件窗口或真实设备路由。R3 的新增回归验证松手后的同 revision 回读终态，没有模拟物理鼠标按住期间的外部控制竞争。
- 这是原生 Windows JUCE 界面，没有可供网页检测器检查的 DOM；未运行 web detector，也不把它的缺席或空结果解释为质量通过。仅按原生源码、组件渲染及已有测试证据作出上述判断。

Questions skipped: 本次任务是限定范围的独立完成审查；设计方向和功能约束已确定，没有需要用户重新选择的事项。
