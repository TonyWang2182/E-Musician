# Focus + Mix 原生迁移：独立代码回归审查

审查时间：2026-11-04 23:43（Asia/Shanghai）。分支 `feature/focus-native-v070`；基线 `7f7eb6528bc1b7c8bb41c181a6448a5d330d239b`。本次检查基线到工作树的差异，包括未跟踪的新 `MixerView.*`、`FocusTheme.h`；不能只用 `7f7eb65..HEAD`，因为实现尚在工作树。

方式：只读源码审查，不构建、不运行应用、不使用 computer-use，不修改源码。统一构建与截图由主代理负责。以下是修复前发现，状态不能替代后续构建或实际 GUI 结果。

## 发现

### R1 · P1 · Mixer 页面仍能通过快捷键编辑隐藏片段

位置：`MainComponent.cpp:1180–1189`（`showWorkspace`），`2275–2317`（`keyPressed`）。

复现路径：在 Arrangement 选中片段，切换 Mixer，然后按 Delete/Backspace、Ctrl+X 或 Ctrl+D。`showWorkspace(2)` 隐藏 Arrangement 并把焦点交给 MainComponent，但 `keyPressed` 没有页面条件，仍然调用 `delete_clips`、`cut_clips` 或 `duplicate_clips`，目标是隐藏 Arrangement 的选择。`S`、Ctrl+L 和 Ctrl+4 同样作用于不可见编辑区。用户正在查看混音参数，音乐内容却会改变。

相关问题：完整 Piano roll 页面点击顶部控件后，焦点不再位于 `PianoRoll` 子树，现有 Ctrl+C/X/V/D 和 Delete 分支可能再次落到片段操作；单纯切换页面时转移焦点不能覆盖之后的控件交互。

建议：先保护文本编辑；再按当前工作区分派编辑区快捷键。Mixer 不执行隐藏片段的快捷编辑；完整 MIDI 页将其支持的音符快捷键交给可见且启用的 PianoRoll。保留 Save/Undo/Redo/Transport 等工程级快捷键，避免将其重新回送 `onProjectKey` 造成递归。

需要的回归：保存片段/音符数与 revision，选中片段后进入 Mixer，逐一发送上述按键，确认音乐内容不变；完整 MIDI 页把焦点转移到顶部控件后执行音符剪切与 Undo，确认 MIDI clip 本体未被删除。

### R2 · P2 · 从 Mixer 的 Edit 菜单无法实际打开 MIDI 编辑器

位置：`MainComponent.cpp:1800`（Edit 菜单 id 5），`1845–1895`（`showPianoRoll`），`1106`（可见性条件）。

复现路径：选中 MIDI 片段，切换 Mixer，使用 Edit > Edit MIDI notes。菜单仍可用且调用 `showPianoRoll()`，但该方法只把 `dock` 设为 MIDI，没有改变 `page==2`。`resized()` 因而继续隐藏 PianoRoll，界面看起来没有响应；原 0.6.1 的打开编辑器入口被新的页面条件遮住。

建议：由 `showPianoRoll` 统一保证编辑器可见。已在完整 MIDI 页时保持完整页；从 Mixer 打开时进入 Arrangement + MIDI Dock（或明确进入完整 MIDI 页），然后设置可见编辑器的焦点。

需要的回归：从三个工作区调用同一打开动作，确认对应 MIDI 片段确实可见、项目 revision 和选中 clip ID 不变。

### R3 · P2 · Mixer 拖动期间拒绝或外部修改后，推子可能不再回读权威值

位置：`MixerView.cpp:103–112`（手势与提交），`137–138`（拖动期间跳过 setValue），`237–255`（revision 缓存和仅电平刷新）。

复现路径：Mixer 缓存 revision N；外部命令先改动工程到 N+1，下一次定时刷新之前用户开始拖动推子。提交因 expected revision N 被拒绝；`run()` 随即读入 N+1，但 `Strip::update()` 因鼠标仍按下而跳过推子的值。此后 N+1 已缓存，30 Hz 刷新只更新电平；`endGesture()` 也不恢复数值。松手后 UI 可以长期显示未提交的 gain/pan。拖动期间外部修改同一参数也有相同路径。旧 MainComponent 的滑块每个 tick 在松手后都会回读，这里新增的优化丢失了该保障。

建议：为被跳过的标量回读保留待更新状态，松手后同步；或在轻量遥测分支中继续同步非拖动的 gain/pan。无需重建所有控件或复制全部音乐快照。错误回读不能依赖未来恰好发生另一次 revision 变化。

需要的回归：分别覆盖轨道 gain、pan、Master gain 的过期提交/外部变更；结束手势后验证轨道 rail、完整 Mixer、Transport Master（适用时）与 EngineSession 一致，并确认 rejected value 不改变工程或新增 Undo。

## 已核对的边界

- Mixer 通过原 `execute`、`beginEditGesture`、`endEditGesture` 入口提交；没有第二份可写音乐模型或独立 Undo 栈。轨道控件捕获稳定 ID，普通连续 gain 拖动的合并逻辑正确。
- `Strip::run` 在可能重建并销毁 strip 前复制结果回调，之后不再读取 strip 成员；`showDetails` 也复制回调与 ID，并用父 Mixer 的 SafePointer 检查回调后的存活。未确认普通路径存在 use-after-free。异步工程切换/真实插件窗口仍不在本次静态结论范围内。
- Source、设备、I/O、send、自动化、Master 设备、原插件浏览器、删除/重排轨道与导出仍有源码入口。旧直接插件按钮被隐藏后，原生插件编辑器可从 Devices 的 open 按钮到达。
- Arrangement 的 full-height `clipArea` 同时供绘制、命中、框选与跨轨 ghost 使用；未发现视觉与命中使用两种纵向几何。矩形选择现在需要从真正空白处开始，原水平时间计算和细网格逻辑未变。
- PianoRoll 修改主要是颜色/文字绘制；音符索引、时间坐标、精细吸附、写入和快捷键实现未被删掉。
- 完整 Mixer 的遥测更新有每个 strip 扫描轨道的 O(N²) 查找；当前工程上限 64 轨，所以这是有界开销，不能仅凭静态源码称为性能故障。未做本轮测量，不借用旧版性能数字给新 UI 背书。

## 验证缺口与修复前指纹

现有新增 smoke 覆盖普通 gain 手势、pan/mute/solo/Master、Undo、三页可见性、选轨/revision 保持和截图；它没有覆盖 R1 的页面快捷键、R2 的全局菜单入口、R3 的拖动中冲突/最终回读。源码中已有检查不能代替检查实际执行通过。

| 文件 | SHA-256（修复前） |
|---|---|
| MainComponent.cpp | `8965bc2cd5c7fd6a893fea87bb1f633ef44b7675acb2ee7fedae572431b16b30` |
| MixerView.cpp | `6a4c887283d4140f9bc3a169e749bf6551ed4841add7700b84c4f81137de6c5d` |
| ArrangementView.cpp | `d2e8efd719a7554bfe9df560937b122bf0c430cf6405c612ce3ac8290ad8337f` |
| PianoRoll.cpp | `be49f4e058f06f31c8b3e28a8165009f7b5ac0f4ae6ae1a7fa109ee4954f4573` |

建议在交付前修复 R1–R3，再由统一冻结构建执行对应组件回归。实际设备、第三方插件、DPI 与物理键盘焦点仍按人工短测记录。

## 第二轮冻结源码复查（2026-11-04 23:46，Asia/Shanghai）

结论：R1、R2、R3 的根因均已在当前源码中处理；本次复查未发现这三处修复新增的阻断问题。状态为**源码修复复核通过，统一构建/测试结果待主代理记录**。保留上方修复前发现作为历史，不把静态复查写成运行验证。

| 发现 | 修复复核 | 对应新增检查 |
|---|---|---|
| R1 | `MainComponent.cpp:2313–2328` 将完整 MIDI 页的音符快捷键子集路由到可见且启用的 PianoRoll；非 Arrangement 页阻止片段快捷键进入旧分支。文本输入保护在分派之前，Save/Undo/Redo 等工程按键不回送 PianoRoll，因此未引入 `onProjectKey` 递归。 | `1719–1733` 检查 Mixer 下 Delete/Ctrl+X/Ctrl+D/S 不改变 revision；完整 MIDI 页 Ctrl+A/Delete 删除音符而保留片段，然后调用 Undo。该检查直接从 MainComponent 分派，覆盖失去 PianoRoll 子树焦点后的路由入口。 |
| R2 | `MainComponent.cpp:1870` 在 Mixer 调用 `showPianoRoll()` 时切回 Arrangement，随后原 `dock=midi` + `resized()` 使编辑器可见；完整 MIDI 页保留 page 1。 | `1724–1725` 从 Mixer 调用该入口并断言页面离开 Mixer、PianoRoll 可见。 |
| R3 | `MixerView.cpp:123–133` 的 `syncScalars()` 在非拖动状态下以 `dontSendNotification` 回读 gain/pan；`264` 在相同 revision 的轻量刷新路径中也执行。已缓存的 revision 不再阻止松手后的标量修复，也不会通过同步过程重复提交命令。 | `323–347` 检查同一引擎的第二个 Mixer 回读轨道 gain；人为保留错误 gain/pan/Master 显示后，使用相同 revision 快照恢复三者，并断言工程 revision 不变；附加 pan 文字回读检查。 |

新增 R3 检查验证的是“拖动已结束、revision 已消费”的故障终态，没有模拟真实鼠标按住时的外部控制竞争；它能够直接防止本次丢失同 revision 回读路径的回归。完整鼠标/物理键盘、第三方插件及设备场景仍属于既定人工短测范围。本次没有运行这些新增检查，没有改动任何源码。

第二轮复查文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| MainComponent.cpp | `539c84c74a1e3c7b33197bab4707638f4dbafe9a3a105fdeb4c84f49cb7dc19c` |
| MixerView.cpp | `684a7c8587d961d3802a6d46e5da5193b4ef2c1741882fb493f056d5d433716b` |
