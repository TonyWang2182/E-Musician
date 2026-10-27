# E-musician 0.5 快速上手

按当前 Windows 界面标签编写，日期：2026-10-27。先完成“导入或写音符 → 播放 → 保存 → 重开”，再尝试录音和路由。实际验证范围见 [验证记录](verification/2026-10-27-v05/RESULTS.md)。

## 启动与打开工程

已有编译产物时，在项目目录的 PowerShell 中运行：

```powershell
Set-Location -LiteralPath 'E:\E-musician'
python scripts/dev.py run --config Release --note "日常使用"
```

没有产物时按 [构建说明](BUILDING.md)先完成构建。点击顶部 `open`，或按 **Ctrl+O**，选择 `.emproj` 文件。测试工程在 `E:\E-musician\test-projects`。搬动工程时，把 `歌曲.emproj` 与同目录的 `歌曲.assets` 文件夹一起复制；打开的是 `.emproj`，不要选素材目录。插件程序和外部音色库需要另外安装。

`new` / **Ctrl+N** 创建默认 **120 BPM、4/4** 的空工程。点击底部的 `120 BPM` 可调整速度、拍号和循环范围；改变BPM不会自动拉伸音频。

## 导入音频与查看全部轨道

1. 点击 `add...` → `Import audio... (WAV / MP3)`，可一次选多个文件；也可把音频文件拖入主窗。等待底部导入任务完成。
2. 中央只有一个多轨编曲时间轴。滚轮上下看轨道，**Shift+滚轮**横移，**Ctrl+滚轮**缩放；`-` / `+` 调整缩放，`fit` 显示整个工程。
3. 点击片段选中；拖主体移动，拖边缘裁剪。`edit` 菜单提供分割、复制、删除和 `Clip properties...`。网格默认 `grid 1/16`，拖动时按 **Alt** 可暂时忽略吸附。
4. 点击标尺定位；底部 `play` / **Space** 播放或暂停，`stop` 停止并归零。轨头 `M` 是静音，`S` 是独奏；点击轨道本身不会独奏。

`details` 展开所选轨道/片段属性。`source` 打开下方的源音频波形；`close editor` 收起下方区域。这里的 `source` 是查看源文件，不是音源分离。

工作台示例只含合成测试素材：[1280×800](verification/2026-10-27-v05/34eb7d59-release-ui-1280x800.png)、[1000×650](verification/2026-10-27-v05/34eb7d59-release-ui-1000x650.png)。

## MIDI片段与已有乐器插件

1. `add...` → `New MIDI / instrument track`，选中这条轨道。
2. 点击该轨头的 `devices`，在底部 `devices` 页点击 `add plug-in...`。插件浏览窗中先用 `scan installed`，或 `scan folder...` 扫描安装目录。
3. 确认浏览窗顶部目标是这条MIDI轨，选一个标为 `instrument` 的乐器，点击 `add >`。回到底部设备链，选插件再点 `open` 打开它的原生窗口；`bypass` 旁路，`up` / `down` 调整链顺序。
4. 在标尺定位，`add...` → `New 4-bar MIDI clip at playhead`。已有MIDI文件可用 `Import MIDI...`。
5. 双击MIDI片段打开**底部钢琴卷帘**。空白网格双击写音符，拖动改音高/位置，拖边缘改长度；选中音符后用 `velocity`、`quantize`、`pitch -` / `pitch +` 调整。`drum steps` 展开16步鼓编辑，仍需合适的鼓乐器插件发声。

没有加载可用乐器的MIDI轨不会发声。当前插件入口为 Windows x64 VST2/VST3；具体插件、版本和音色是否正常，以实际加载和验证结果为准。

## 设置声卡并录音

1. 停止播放，点顶部 `audio settings`。在 `Driver` 选驱动，ASIO在 `Device` 选厂商声卡；分离输入/输出的驱动分别选 `Input` 和 `Output`。点 `apply`，以面板 `Active:` 显示的实际配置为准。
2. 更换设备后先应用默认配置，再选它实际支持的 `Sample rate` / `Buffer size` 并应用。失败时面板显示错误及回读值。**关闭设置窗后才能开始录音。** MIDI键盘输入在下一步选择，无需在此寻找MIDI总开关。
3. 音频录音先建 `New audio track`；MIDI录音建乐器轨，并按上节加载乐器。选轨 → 轨头 `devices` → 底部 `I/O + sends`，在 `recording input` 下拉框选麦克风/线路或MIDI端口，再点 `arm record`，按钮变为 `armed`。已选输入后也可用轨头 `R` 切换预备录制。
4. 新输入默认 `monitor off`，仍可录音，只关闭软件输入监听。需要听到输入时选择 `monitor auto`（随录制预备状态监听）或 `monitor on`（持续监听已连接轨道）。**监听属于共享输入设备：多轨用了同一个输入，修改模式会一起生效。** MIDI键盘要经插件实时发声也需要监听；已有片段播放不受这个输入开关控制。
5. 关闭底部 `loop`，定位录音起点，点 `rec` 开始线性录音；点 `stop` 结束。等待 `Finishing recording...` 消失，片段提交后再保存。录音及收尾时编辑、保存和设备切换暂不可用；一次录制可整体Undo。

当前没有循环叠录/comping流程。多个MIDI端口名称相似时，选择实际收到键盘数据的端口；端口能列出不等于已经验证实体演奏。

## Bus、发送与自动化

**分组/发送：** `add...` → `New bus / group track`。选原轨，打开 `devices` → `I/O + sends`：`track output` 可选 `Master output` 或已建Bus；`send to bus` 选目标后点 `add send`，下方选择该发送，调整dB、`post-fader` / `pre-fader`，或用 `bypass send`、`remove send`。效果器可加在Bus的设备链上。会产生反馈环的连接会被拒绝。

**自动化：** 选轨 → `devices` → `automation`，从下拉框选轨道音量/声像或当前插件提供的参数。曲线区双击加点，拖点移动，**Alt+上下拖点**调整该点后面的曲线，选点按 **Delete** 删除。`bypass lane` 暂停该曲线，`delete lane` 删除整条；右上 `master` 切换到主输出的设备/自动化。横轴为工程秒，纵轴为归一化百分比。当前支持画曲线和播放，不提供Touch/Latch/Write录制模式。

## 保存、撤销与导出

`save` / **Ctrl+S** 保存，首次会选择 `.emproj` 位置；`save as` / **Ctrl+Shift+S** 另存为。保存中按钮显示 `saving...`，顶部状态为 `Saving...`；等到 **`Saved`** 才表示当前状态已保存。`Unsaved changes` 表示仍有新编辑；`Save failed - retry` 时查看底部具体错误，再重试。连续按Ctrl+S会合并请求，不需要反复点击；保存期间的新编辑仍需保存。关闭前等待保存结束。

若快捷键没有响应，请点击已验证的`save` / `save as`按钮。本轮自动化工具的瞬时Ctrl+S注入未触发保存，尚不能据此判断实体键盘有问题。

`undo` / **Ctrl+Z** 撤销，`redo` / **Ctrl+Y** 恢复；重开工程后不保留撤销历史。当前没有完整自动保存/崩溃恢复，重要版本可以用 `save as` 留副本。

`export` 菜单可选 `Export project WAV...`、`Export loop range WAV...`、`Export project WAV at real-time speed...`，或导出完整/所选MIDI片段。WAV选好路径后，设置起止秒、采样率、位深和尾音，再点 `apply`；等待后台任务完成。实时速度选项是渲染方式，不是声卡内录；**MP3目前仅导入，不导出。**

## Agent接口入口

接口使用本地JSONL，与GUI共用工程命令。最小示例在项目目录运行：

```powershell
python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --demo build/agent-demo
```

示例会启动专用进程，创建测试音符并导出MIDI，不操作另一已打开的DAW窗口。需要同屏控制可用 `E-musician.exe --control-stdio --show` 配合客户端。请求、版本冲突和异步任务完成状态见 [Agent API](AGENT_API.md)；当前没有内置模型或聊天面板。
