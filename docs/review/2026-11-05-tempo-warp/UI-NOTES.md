# 0.10.0 原生工作流界面记录

2026-11-05。状态：界面实现已提交工作树，等待集中编译、离屏检查及人工验证。此记录不是测试通过声明；最终证据由本轮 RESULTS/构建记录补充。

## 文件与责任

- `MainComponent.cpp/.h`：保存/设置窗口、上下文操作分派、Source/Warp 组件与主窗口离屏检查。
- `WorkflowPanels.h`：无额外编译单元的 Settings 与 Save 组件；沿用原有黑白、等宽字体、细线与圆角按钮。保存主操作使用实心按钮。
- `ArrangementView.cpp/.h`：右键命中、保留选择、播放头跟随查询，以及拉伸后波形/裁剪预览坐标。
- `UiLanguage.h`：跟随偏好文件，保持语言偏好和工程状态相互独立。
- 引擎、持久化、DSP 和节拍模型由其他模块负责，本 UI 不直接写 Edit。

## 交互变化

**跟随播放头**：时间线上方直接显示 Follow: off/on/paused。Settings → Editing 和标尺右键共用此设置。手动滚动或编辑暂停本次跟随；重启播放或重新开关恢复，右键还可直接 Resume following。用户明确操作才写 `%APPDATA%/E-musician/follow-playhead.txt`，默认关闭；初始化及离屏测试不改用户偏好。

**设置**：独立窗口分 Audio/MIDI、Editing、Language 三页。设备页显示当前设备/实际采样率/缓冲区，并打开原有 AudioSettingsPanel；草稿、Apply、实际回读、失败保留的设备管线不变。仅打开通用设置不改变设备或播放状态。录音期间配置设备入口禁用，语言和视图偏好仍可查看。MIDI 输入继续在每轨 Devices/I/O 选择。

**保存**：首次保存或 Save As 打开名称/文件夹面板，Choose folder 选择目录，Save project 提交准确的 `.emproj` 路径，已存在文件明确确认替换。已有路径的 Save/Ctrl+S 直接进入原异步保存队列；保存状态仍由真实任务完成回读，保留重复按键合并和失败重试。不新增自动保存/恢复。面板取消不写文件；项目切换不会把旧面板保存到新工程。

**情境右键**：轨道头、片段、空白、标尺分开生成菜单；命中右键即返回，不进入 seek、拖动或框选。已选片段群保留，点击其他片段才切换目标；轨道头/标尺/空白菜单不清掉多选。剪切、复制、粘贴、重复、切分、删除、循环、轨道静音/独奏/录音准备等复用统一命令。修改携带菜单打开时的 revision，工程变化后由宿主拒绝过期操作。粘贴和切分仅在有适用目标/合法位置时出现。删除交给命令层 Undo。

已查固定 JUCE 的 Button 实现：默认任意鼠标按钮都可能触发普通点击。轨道头五个按钮因此使用专用 HeaderButton 消费右键手势，直接打开轨道菜单，避免误触静音/独奏/准备录音。离屏行为检查也点击实际 mute 按钮的右键入口。

**Source/Warp**：显示当前可听片段的映射波形和片段相对时间。Warp 开关、原始 BPM、目标 BPM、Follow tempo 和 Apply 形成一组明确草稿；Apply 前不修改工程。原始/目标 BPM 限 20–300；跟随工程时目标栏只读。Analyze beats 跳转分析页的 Beats 标签。调用 `set_audio_warp` 的请求包含 project_id、request_id、expected_revision；接受后跟踪 job_id，完成前不宣称应用成功。原音频与渲染缓存仍由引擎管理。

波形/拖动使用 `playbackSourceOffset`、`playbackSourceDuration`；Source 播放头为 `projectPosition - clipStart`，点选反算为 `clipStart + clickedClipTime`。统一命令里的 source_offset 仍是原始文件秒，UI 不改变其定义。首批只有固定比例保音高 Warp，没有局部标记或 Tempo Map。

## 自动验证入口（待集中运行）

主窗口现有 arrangement smoke 新增：

- 中英文 Settings 三页最小窗口：`ui-settings-{0,1,2}-{en,zh-CN}.png`。
- 中英文 Save 面板与准确路径回调：`ui-save-project-{en,zh-CN}.png`。
- 1000×650 Source/Warp 与合成和弦轨并存：`ui-source-warp-{en,zh}-1000x650.png`。
- Settings 录音状态禁止设备配置、独立跟随回调；不改用户语言/跟随偏好。
- Source 的跟随目标只读、非法 BPM 不进入引擎；此处是 UI 数据夹具，不是实际拉伸验收。
- Arrangement 四类右键保持位置、revision、多选，且不启动拖动。

真实拉伸、原文件不变、频率/长度、取消、保存重开、Undo/Redo 由集中引擎测试覆盖。实际 DPI、鼠标可达性、长期 ASIO 播放与听感仍需人工确认。

静态检查 `git diff --check` 已通过，记录 `docs/builds/20261105T120504.888251Z-7a14704c36.json`；该检查发生在最后 HeaderButton 补丁前，仅证明当时文本差异无空白错误，不代表编译或运行验收。

集中构建 `20261105T121151.406749Z-0236ee2ec9` 报出两项 UI 编译问题：新字体助手缺少明确的 `juce::Font::plain` 参数、Main 使用最小编辑跨度常量却漏含 `EditGrid.hpp`。两处已补齐并重新冻结，等待重编译。首次失败保留在构建记录中。

## 首轮真实离屏检查与修正

集中重编译后的 `build/smoke/Release/2a52c9c6ce55/arrangement-report.json` 为 passed，新增设置/保存/Source、终态冲突解锁、右键多选检查均通过。已逐张读取实际 `ui-settings-{0,1,2}-{en,zh-CN}.png`、`ui-save-project-{en,zh-CN}.png`、`ui-source-warp-{en,zh}-1000x650.png`，共 10 张，不使用 computer-use。

- Settings 三页 640×360：导航与正文有明确分隔；设备名称、48000 Hz/256、设备配置按钮、语言选择均完整，没有相互覆盖。
- Save 640×356：名称/目录区域、取消/实心保存按钮完整；测试目录可读，名称原文不被翻译。
- Source 1000×650：合成和弦轨与一条完整紧凑音轨仍可见；Source 名称、Warp、BPM、跟随工程速度、应用、分析节拍和波形刻度均在区域内。测试音频的密集峰值呈水平边界，不能据此推断真实音乐拉伸听感。
- **发现并修正**：Follow 从 76 px 扩宽至 194 px，但主窗口快捷说明仍硬编码 x=426，覆盖 x=336..530 的 Follow 按钮文字。改为从 `follow.getRight()+12` 起绘；空间小于 420 px 时隐藏次要说明，同时避开 Agent 侧栏。
- **发现并修正**：中文 Editing 说明被 JUCE 的长无空格文本压成一行，约 6 px 字形，虽未越界却不易阅读。三个中文设置说明改为明确分行，中文提示字体从 13 调到 15；英文维持原有字号/换行。

上述两项修正已重新冻结；仍需下一次构建与截图复核后才标为最终通过。设置偏好重启、真实鼠标与听感仍是人工待验。


## 最终截图复核

最终构建17681fb951 / CTest a0dca19eac通过。root查看f87397cf889d中的Source中英文、Settings三个中文页、Save中英文：Follow与右侧提示分离，中文说明按两/三行显示；原有英文布局及Beats组件源码未再变化，紧凑动作完整。最终归档14张截图及精确SHA见UI-VERIFICATION.json，人工DPI/鼠标仍待验。
