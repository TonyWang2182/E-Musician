# 音频输入设置界面（0.13.6）

状态：已实现，Release 0.13.6 原生交互测试及七张组件截图检查通过；本轮完整 CTest 11/11 通过（[记录 `023018ac4f`](../../builds/20261116T140925.017863Z-023018ac4f.json)）。本文不代表物理录音或厂商控制面板人工验收通过。

## 行为

- Settings → Audio / MIDI → Configure audio devices 增加独立的物理输入勾选。每项保留 `In 1`、`In 2` 等通道序号及驱动原始名称；勾选只修改本地草稿，Apply 后重新读取实际设备及已启用通道。
- ASIO 等共用设备的驱动仍只选择一个音频设备。输入设备栏明确显示“使用上方同一设备”，正文解释输入、输出共享设备，物理通道在下方选择。分离设备型驱动仍可分别选择输入与输出设备。
- 相邻物理输入可显式配成立体声。配对关闭时可分别选择两个单声道输入；配对要求两路同时启用，关闭其中一路立即清除无效配对草稿。所有输入均可关闭并提交空掩码。
- 切换驱动或设备时清空旧设备的通道、采样率和缓冲区能力，先 Apply，再显示新设备的真实能力。读取失败会禁用 Apply、通道和驱动面板入口，刷新恢复后才允许继续。
- “驱动控制面板...”仅在当前已打开设备明确支持、无未应用草稿时可用。执行统一 `show_audio_driver_panel` 命令，返回后刷新设备和实际设置；厂商界面使用厂商自己的外观。
- Apply 和驱动面板调用先经消息队列异步执行，持有独立回调副本并在返回后检查组件 SafePointer。忙碌期间禁止重复提交；嵌套厂商消息循环关闭设置窗口时不再读取已销毁组件。

## 外观与边界

保持已批准的纸白、墨色、细线、青绿焦点主题。普通标签改为既有 sans token，精确设备名称不翻译。标准内容区域为 660 × 590；540 × 560 合成小窗包含完整底栏操作，多输入列表滚动。中英文均提供空输入、草稿、失败、已应用和控制面板状态。

独立输入选择不代表轨道已经开始录音。轨道仍须在 Devices / I/O 选择输入，开启 Rec 预备，再使用全局录音；Monitor 独立。实际 M-Audio In 1 / In 2 信号、电平、左右路由、声卡控制面板和听感需用户验收。

## 自动检查范围

`AudioSettingsPanel::runInteractionSmokeTest` 扩展现有 `runArrangementSmokeTest`，由 `engine.integration_smoke` 在生产引擎验证后执行；不是独立的 `workspace.brand_colour` 测试。截图位于 `build/smoke/Release/<本次目录>/ui-audio-input*.png`。界面使用明确标识的合成设备回调，不操作用户 GUI 或声卡：

- 草稿不提前提交、初次设备 Apply 不带旧能力、拒绝后回读真实配置。
- In 2 独立掩码、两个单声道、显式立体声配对、关闭全部输入。
- 控制面板能力判断、未应用草稿保护、返回后真实值刷新。
- 同驱动换设备、读取失败后不保留可操作的旧能力。
- Apply／驱动面板回调期间销毁设置组件的生命周期检查。
- 英文普通／错误／新设备截图，中英窄窗 16 路长名称与空输入截图。

本轮实际目录为 `build/smoke/Release/67923928dea9`，六项音频设置检查均为 true，见[机器收据](UI-VERIFICATION.json)。七张原生组件截图已逐张查看：

- [In 2 单独启用](screenshots/ui-audio-input-in2-en-660x590-synthetic.png)、[驱动拒绝后恢复实际值](screenshots/ui-audio-input-rejected-en-660x590-synthetic.png)、[新设备未应用](screenshots/ui-audio-input-new-device-en-660x590-synthetic.png)。
- 16 路长名称小窗：[英文](screenshots/ui-audio-input-many-en-540x560-synthetic.png)、[中文](screenshots/ui-audio-input-many-zh-CN-540x560-synthetic.png)。底栏操作无重叠，长名称前两行完整；列表第三行在滚动视口边缘部分可见，滚动条明确显示。
- 空输入小窗：[英文](screenshots/ui-audio-input-empty-en-540x560-synthetic.png)、[中文](screenshots/ui-audio-input-empty-zh-CN-540x560-synthetic.png)。无输入说明、不可用驱动面板、实际状态和操作按钮均可辨认。

本轮没有发现阻断交互的排版或文字裁切问题；组件图片不包含 Windows 标题栏、厂商窗口或物理 DPI 行为。实际设备、鼠标／键盘、100%／150%／200% 缩放和听感仍按[人工清单](MANUAL-CHECK.md)验收。
