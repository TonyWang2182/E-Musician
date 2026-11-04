# Focus + Mix 原生界面功能保留核查

日期：2026-11-04（Asia/Shanghai）。审查基线：`7f7eb65`，应用 0.6.1，`feature/fine-grid-v061`。本页是实施前源码清单及验收约束，**不是新版已经通过的结果**。新界面为同一 C++/JUCE 应用，不能把 HTML 原型中的演示值或缩减功能替换生产实现。

用户要求：保留当前版本，应用已选定的深色 Focus + 常驻双通道混音区，新版保留原版所有功能。原型的静态音符、CPU/RAM 示例、仅 C3–C5 音域、模拟保存及录音不属于生产规范；生产端必须继续读取真实 EngineSession 状态。

## 证据入口

- `apps/desktop/MainComponent.cpp`：工程生命周期、工具栏、底部控制、Inspector、对话框和键盘分发；基线主要入口为 `Impl`（665）、`runArrangementSmokeTest`、`showAddMenu`（1657）、`showEditMenu`（1681）、`showExportMenu`（1720）、`showPianoRoll`（1746）、`keyPressed`（2175）。后续改动会移动行号，函数名为稳定定位依据。
- `apps/desktop/ArrangementView.cpp`：轨头、片段命中/预览/提交、标尺、缩放/滚动、波形缓存及 `runSmokeTest`。
- `apps/desktop/PianoRoll.cpp`：完整 MIDI 编辑器和 `runInteractionSmokeTest`。
- `apps/desktop/SelectedTrackPanel.cpp`：设备链、I/O + sends、自动化、Master 切换及面板交互检查。
- `docs/AGENT_API.md`、`EngineSession*.inc`、`ControlServer.cpp`：公共命令、revision、任务和协议边界。
- [0.6.1 证据](../../verification/2026-10-29-v061/RESULTS.md)、[现有功能规格](../../UI_REFERENCE.md)、[架构](../../ARCHITECTURE.md)。旧规格中个别缩放上限文字早于 0.6.1；以当前源码、0.6.1 记录为准。

## 功能映射与验收要求

表内“新版入口”是必须保留的目标入口，最终是否通过由本次构建及结果档案填写。可以改位置和外观，不得只保留无法到达的回调。

| ID | 原版真实能力 | 新版必须可到达的入口／语义 | 现有自动检查 |
|---|---|---|---|
| P01 | New、Open、Save、Save As；未保存工程标识 | 顶部工程操作；保留 Ctrl+N/O/S/Shift+S | MainComponent 保存生命周期，project/storage |
| P02 | New/Open/Close 的 Save/Discard/Cancel | 同一未保存保护；保存取消/失败禁止继续关闭 | MainComponent 保存 continuation/失败/过时状态 |
| P03 | 保存先受理、阶段反馈、重复请求合并、迟到编辑保持 dirty | 常驻可读保存状态和详细错误；不能只闪提示 | MainComponent + SavePipeline/PlaybackSave 专项 |
| P04 | 异步导入/保存/导出任务状态、取消任务 | 底部状态和 cancel task；失败信息可阅读 | engine.jobs、任务 smoke；文件保护 |
| P05 | 原工程 schema、资产和插件状态往返 | 同格式直接打开；不得为换皮迁移音乐数据 | project/storage/production |
| T01 | 新音频、MIDI/instrument、Bus/group 轨 | Add 菜单完整保留 | DAW command tests |
| T02 | 重命名、上下移动、删除轨；Undo 恢复 | Edit 菜单；不能只保留删除 | DAW/clip/production |
| T03 | 音频 WAV/MP3 多文件导入；MIDI 单文件导入；系统拖放 | Add + 原窗口文件拖入 | project/MP3 + MainComponent 文件入口 |
| T04 | 在播放头创建 4 小节 MIDI Clip | Add 菜单；合法 instrument 轨启用 | DAW/clip |
| A01 | 全轨共用时间坐标、真实音频波形、MIDI 概览、多片段 | 编曲页；Clip 填满轨高但保留标签/淡化/边缘命中 | Arrangement 几何/波形/公共时间尺度 |
| A02 | 片段点击只选中、不改变播放位置；多选/框选 | 编曲页原鼠标语义；选中反馈与播放头区别清楚 | Arrangement selection/rectangle |
| A03 | 主体移动、同类跨轨移动、组相对位置、边缘裁剪 | 整高 Clip；窄 Clip 也保留移动与裁边可达性 | Arrangement real drag + single Undo + stale revision |
| A04 | 音频淡入/淡出拖柄和精确数值 | Clip 顶角 + Clip properties | fade handle/clip tests |
| A05 | Split(S)、Duplicate(Ctrl+D)、Delete/Backspace | Edit 菜单 + 快捷键 | clip/DAW + MainComponent keyboard |
| A06 | Copy/Cut/Paste clips；新粘贴对象保持唯一 ID 和选择 | Ctrl+C/X/V + Edit 菜单 | clipboard stale identity/boundary/Undo |
| A07 | 精确片段起点，Enter/set 提交、Escape 恢复，blur 不提交 | Inspector/Details；不得因常驻 rail 删除精确输入 | MainComponent start field/atomic Undo |
| A08 | Clip properties：位置、长度、音频 source offset、fade | 清楚可到达的属性入口；秒或 bar:beat:tick 随标尺 | MainComponent/clip exact precision |
| A09 | bars/seconds/both 独立标尺模式；三级小节命名 | 主工具栏；不以显示模式改变音乐数据或 Snap | Arrangement ruler units/tiers |
| A10 | 固定、自适应、三连音至 1/16384 网格 | 原全部选项；新外观不得缩成原型的选项子集 | fine-grid Core/Arrangement/Piano |
| A11 | 独立 Snap、Ctrl+4、Alt 临时绕过；开实线/关虚线 | 当前编辑区控制和清晰状态；不同时切换两个编辑器 | Arrangement/Piano pixel + shortcuts |
| A12 | 指针锚定 Ctrl+wheel 深缩放、+/-、Fit、双向滚动 | 编曲页完整保留；不能采用原型受限 zoom | 48h/300BPM deep zoom、scroll/last row |
| A13 | 标尺定位、Shift 拖时间选区、空白定位、Home/End/左右 | 同一时间轴模型及原键盘语义 | Arrangement seek/time selection |
| A14 | 循环开关、循环范围、循环括号拖动、Ctrl+L 选区循环 | 底部 Transport + 时间轴 + Timing 表单 | loop selection atomic Undo |
| A15 | Follow；手动滚动/编辑暂停跟随直至重启播放 | 工具栏按钮，状态可读 | follow pause test |
| A16 | 源音频详情波形、源数据及定位 | Source 可收起区域仍可打开 | WaveformView/MainComponent |
| M01 | 双击 MIDI Clip 打开真实 PianoRoll | 编曲双击 + MIDI 页；必须绑定同一 clip ID | MainComponent + Piano smoke |
| M02 | 全 0–127 MIDI 音高与纵向滚动，首次 fit pitch | 完整 PianoRoll；不照搬原型 C3–C5 限制 | MIDI fit/pitch boundaries/scroll |
| M03 | 双击写音符、B 单击画笔、选择/Shift 多选/框选 | MIDI 页原工具及键盘入口 | draw toggle/single click/selection |
| M04 | 音符拖动、右边缘改长、量化、半音/八度升降 | MIDI 页工具 + 上下/Shift+上下 | MIDI drag/resize/quantize/boundary/Undo |
| M05 | 音符 Copy/Cut/Paste/duplicate/delete、Ctrl+A | MIDI 焦点下作用于 notes；不可落到隐藏编曲 clip | MIDI clipboard/group-atomic/project-forwarding |
| M06 | Velocity 1–127，单拖动单提交 | MIDI slider/文本框与力度视图 | MIDI velocity gesture |
| M07 | 独立网格/Snap/缩放/滚动/插入标记/播放头 | MIDI 页完整保留 | fine-grid+Ctrl4+zoom+insertion |
| M08 | 16 步鼓编辑；鼓音高选择和 4 拍 block 号 | Drum steps 按钮及所有原控制；不删除以迎合原型 | compact drum mode/step edit |
| M09 | 大集合可视索引、8192 绘制预算、完整命中/选择 | 沿用生产绘制，不复制或反复全量投影 | 100k notes timing/index/dense tests |
| X01 | 每轨 gain/pan/mute/solo/arm | 轨头 + 当前轨 rail +全混音页共享状态 | old track controls + 新 mixer 集成检查 |
| X02 | Master gain、真实输出电平、overload reset | Master 常驻 rail；真实快照而非原型示例值 | telemetry/production + reset path |
| X03 | gain/pan 拖动 Undo 归组及轨道身份绑定 | 多处推子更改同一 EngineSession；选轨中不能串轨 | 原 gesture checks + 新 mixer stale/gesture check |
| X04 | Bus 输出路由、pre/post send、发送启停/增删/gain | Details 的 I/O + sends 完整保留 | production route/cycle/render/save |
| X05 | 插件目录扫描、自定义路径、过滤、增删/排序/旁通/打开 | Devices 浏览器；track 与 Master 都可达 | plugin host/notification 历史专项，面板 smoke |
| X06 | 缺失插件状态和原状态块保留 | 显示 missing，禁开无效编辑器，允许管理 | plugin/storage |
| X07 | 轨/Master gain/pan/插件参数自动化，点增删/拖动/Alt 曲率 | Details > Automation；lane启停、删除、目标选择全部保留 | SelectedTrackPanel + production/render |
| R01 | 音频/MIDI 输入选择、Arm、Off/Auto/On Monitor | I/O 页；当前输入共享监听语义不改 | production inputs/recording + 旧人工验收 |
| R02 | 全局录音/停止、录音收尾及一次 Undo | Transport 常驻；录制/收尾期间原保护保留 | production recording boundaries |
| R03 | 节拍器启停、仅录音模式、音量 | Transport Click 与选项菜单 | count-in/metronome production |
| R04 | 独立预备拍开关 + 1/2/4 小节，Stop 取消 | 底部控制完整保留 | count-in cancel/clock tests |
| R05 | ASIO/WASAPI、输入/输出设备、采样率/缓冲，失败回滚 | Audio settings；录音时禁切设备 | controlled settings smoke + 旧硬件记录 |
| R06 | 真实 RAM/DSP/xrun、输入/输出/主电平 | 底部/rail 的读数来自 EngineSession telemetry | telemetry production，新增布局可见性 |
| E01 | 整工程 WAV、循环段 WAV、实时速率 WAV | Export 菜单完整保留 | render/DAW/storage |
| E02 | WAV sample rate/bit depth/额外 tail/起止范围 | 导出参数窗口；保持取消和旧目标保护 | render-worker/export checks |
| E03 | 全工程 MIDI、所选 MIDI Clip 导出 | Export 菜单完整保留 | SMF4096PPQN/短音/保存重开 |
| K01 | 全局 Undo/Redo、Ctrl+Z/Y/Shift+Z | 原历史共享；新按钮不另造历史 | MainComponent/core/DAW |
| K02 | 文本输入焦点保护、原 Space 行为、Esc取消当前手势 | 页面切换后焦点进入可见上下文；文本输入不误删/播放 | MIDI nested focus + MainComponent |
| I01 | `--control-stdio` JSONL、`--show`、稳定ID/revision/幂等写入 | CLI不变，新 GUI 复用同一 execute；不依赖浏览器 | output isolation/DAW/AgentJobs |
| I02 | 分页、batch/Undo、事件、异步任务查询/取消 | 协议及返回值不改；无 Agent 模型接入 | protocol/AgentJobs 历史专项 |

## 本次最容易丢失的能力

1. 新常驻混音区占据旧 Inspector 的位置。必须给精确 Clip 起点/属性保留明确入口，不能只保留音量和声像。
2. MIDI 独立页不能替换成 HTML 原型的限制版编辑器。保留完整音域、步进鼓、三连音、最细网格、粘贴标记及大音符索引。
3. Devices 必须仍能到 I/O、Send、Automation 和 Master；单个“打开插件”按钮不足以替代原面板。
4. 两处混音推子必须使用同一快照和命令。拖动途中切换轨道要锁定原轨；快照刷新不能重建正在操作的控件、抢焦点或中断滑块文本输入。
5. 隐藏页面保有焦点会误路由 Delete/Ctrl+D/Ctrl+4。切页要显式管理焦点，确认全局快捷键不绕过 PianoRoll 原分发规则。
6. 增大 Clip 到整轨高后，需要重新验证顶部淡化柄、裁边柄与主体命中顺序；同一几何同时服务绘制和事件。
7. 按钮状态必须依赖录音/收尾/任务/缺失对象，不因新壳统一启用。保存失败的详细文本和取消任务不能放到不可见区域。
8. 1000×650 最小窗口需实测：新 rail 吃掉水平空间，底部旧控制不能越界；Piano/Details 的最小高度仍需保留。

## 验收范围与未执行项

本次审查只读源码，未构建、未启动应用、未操作用户电脑。原 0.6.1 Release 5/5、Core118/clip407/DAW799/production229 是历史参照，不能计作 0.7.0 通过。

优先复用 `python scripts/dev.py check --config Release --note "..."`：development.logging、engine.patch_contracts、core.contracts、engine.integration_smoke、control.output_isolation。`RunEngineSmoke.py` 要求独立进程、新目录、engine/project/clip/DAW/storage/production/arrangement 报告及 1280×800、1000×650 原生组件 PNG。新增页面/rail 必须加入同一组件 smoke，核对共享状态和可达性；不得删除旧断言使新布局通过。

本轮视觉验收应同时读取：编曲、MIDI、Mixer、Source、Details 三页、空工程、保存状态、最小窗口；再做一组跨页面真实命令检查（选轨→推子→Undo→MIDI编辑→保存/重开）。设备声音、第三方插件窗口和原生窗口焦点由用户人工短测。旧 Keyscape、真实录音/混合多轨人工通过是历史证据，不能推断新布局已人工验收。

保留明确边界：本轮不新增自动保存/恢复、Warp/时间拉伸、TempoMap、侧链、多输出、和弦工具、模板或 Agent 业务；也不以“保留所有功能”声称所有 VST 兼容、所有设备性能均获验证。
