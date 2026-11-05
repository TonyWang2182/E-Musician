# 0.11.0 原生装置工作区

状态：实现待主任务构建与验证。2026-11-06；工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`。本分工不启动用户程序、不调用付费 API、不操作桌面。构建、CTest、真实原生交互截图由主任务统一用 Recorder 执行；这里不以源码实现代替通过记录。

## 设计与实际操作

- 阅读了 AGENTS、当前 CONTEXT、DEVELOPMENT、ARCHITECTURE、UI_REFERENCE，以及 impeccable context / craft floor。既有 PRODUCT/DESIGN 部分描述仍是早期版本，采用用户已批准的浅纸面方向与当前真实代码；全局文件由主任务管理。
- `DeviceControlStyle.h` 复用 `UiDesign.h` 的纸面、浅灰面板、墨色、次级文字、细线和克制的青灰选中态；普通标签用 sans，参数/单位保留等宽字体；按钮为3px角，不引入装饰卡片。
- `DeviceChainStrip` 保持真实信号顺序、左右切换、缺失/旁路提示，将六个并排添加按钮收为一个 Add device 菜单。Sampler/Rack仅在MIDI轨可选；插件浏览仍可从菜单进入。
- EQ 在至少720×260的面板中采用全宽图及底部频段/形状/参数；推荐常规下栏280–330px高。600×212仍保留紧凑图/旋钮布局，不删除形状、启停、数值输入、重置与键盘路径。
- 效果器标题显示当前轨道或Master及装置名称。Sampler/Rack共享控件外观和选中颜色；低高度时仍保留原来的采样名优先布局，避免标题与样本选择互相覆盖。

## 连续调参和事务

UI使用统一命令：`begin_native_effect_gesture` → 多次 `update_native_effect_gesture` → `end_native_effect_gesture`。EngineSession由协作代理实现校验和最终事务；`Effect::previewSettings`只发布临时原子DSP参数，不写工程ValueTree。`get_native_effect`在手势中仍返回已提交参数，UI保留本地草稿。结束时一次提交、一次Undo；Esc、失焦、隐藏、切轨或析构取消预览。外部音乐编辑/保存等边界由EngineSession先取消，避免存旧参数却持续听新参数。

更新请求使用手势起始revision，不为每个mousemove构造完整快照；冲突交给EngineSession拒绝并恢复已提交参数。新Knob将Escape与正在操作的具体控件绑定，避免旧控件失焦取消新图形手势。文本输入、双击默认值和离散选项继续用一次普通命令。

A/B为当前打开面板内的两份比较参数。切换会真实改变本装置并进入Undo；Copy只更新另一比较槽，不修改音乐。槽不跨关闭/工程保存持久化，提示中明确此范围。它不是绕过工程状态的“隐藏试听”。

## 音频路径

- EQ连续变化使用约10ms系数过渡，包含启停到单位系数；初始载入或reset立即采用当前参数，不引入额外启动渐入。对每段只保留固定系数、步长、滤波历史。
- Compressor的阈值、比例映射、makeup、attack/release系数使用10ms平滑；dry/wet仍为原5ms过渡，真实湿声GR照常回读。
- Delay的time/feedback使用20ms平滑、分数采样读指针，避免直接跳转到新整数tap；改变时间可能出现磁带式音高滑动，不宣称保音高Warp。原历史缓冲不重建。
- Reverb的feedback/damping使用20ms平滑；Auto Filter沿用原cutoff/Q/depth平滑并加入LFO频率平滑。没有声卡听感数据时不声称所有极端参数都绝无伪影。
- Sampler/Rack本次只统一外观，参数/换样仍沿用原发布bank流程；旧voices可能停止，**没有宣称连续采样器无缝调参**。

## 真实频谱与计量边界

EQ图叠加真实装置输出的mono平均信号频谱，与参数响应曲线分开。音频回调仅在UI读取租约有效时采集固定2048点；原子帧单次发布、读取单次版本检查，音频线程不FFT、不分配、不锁等待。租约48个音频块后失效，停止显示后自动停止采集。一个块最多发布一帧，大块余下样本可以丢弃，作为显示快照而不是录音。

Hann窗与FFT在UI线程20Hz执行，绘制128个对数分箱、0至-90dBFS，停止更新约0.5秒后标为inactive。20Hz是UI目标频率，不是实测性能。2048点分辨率随声卡采样率变化，低于第一个频率bin不能精确分辨；立体声反相信号在mono平均中可抵消。该图不是声学质量评分，也不是输入/输出自动补偿对比。原始采样不进入Agent接口。Compressor仍显示来自DSP的真实GR，示意曲线不冒充实测动态包络。

## 待执行的针对性验证

1. `tests/NativeEffectsTests.cpp`新增EQ运行中增益、Compressor运行中makeup、Delay时间改变的连续过渡断言，并保留allocation观察。原有响应/形状/边界/混合测试全部保留；Reverb与AutoFilter既有测试仍须通过。
2. `NativeEffectsPanel::runInteractionSmokeTest`新增旋钮预览不改committed状态/revision、Escape、一次revision/一次Undo、A/B回读与Copy独立性；保留外部编辑冲突、图形拖动、低采样率、形状、旁路及212px小窗口测试。
3. 新增1000×330真实EQ组件截图，检查全宽图与底控；既有600×212、600×250以及其他装置截图继续生成。截图必须由主任务实际查看，不能由边界断言推断视觉完成。
4. EngineSession协作代理负责专用手势事务、实时实例保留、保存/导出边界、cancel/no-op/Undo/Redo及其原生smoke；本分工不改EngineSession文件。
5. 用户人工：播放一段音乐，持续扫EQ增益/频率，确认拖动中变化、Esc恢复、松手一次Undo；比对A/B；切换装置和隐藏下栏不残留预览；真实频谱/GR随音乐与停止变化；Sampler/Rack加载、试听、键盘操作不回退。

性能与稳定性结论待Release构建、离线基准和实际ASIO/缓冲/负载证据。无对应证据不得把“有平滑/有界采集”写成复杂工程实时性能通过。

## 追加分工：Arrangement 投影

主任务将 `ArrangementView.cpp/.h` 交给本分工，未编辑Main。标准轨高从104改为88，紧凑64不变；轨头170/160px。M/S/R/Devices为底部单行，Rename在名称右侧；输入电平/过载提示与类型/增益共用一条副行，避免叠字。

轨道颜色只读 `TrackSnapshot.colour`：浅轨头背景、2px身份条、矩形clip浅填充和18px标题带。选中状态继续独立黑轮廓，波形/音符仍是墨色且保留实际时间几何；没有改写音乐数据来填满网格。普通名称改sans，时间、单位与刻度保留mono。原有可见范围、双精度时域、深缩放、峰值后台管线保持。

新增 `trackAtPosition(Point<int>) const` 接受Arrangement本地坐标，排除标尺/和弦轨/滚动条并计入垂直滚动；`revealPosition(double)` 只横向居中显示并暂停follow，不seek、不改selection；`visibleTimeRange()`供主任务外侧真实工程overview使用，保留原54px标尺与点击行为。

组件smoke追加颜色实际像素、88/64轨高、轨头控件边界、滚动后的drop命中、overview位置与选区/播放头不变检查；输出 `arrangement-track-colours-synthetic.png`，该图只用颜色投影夹具，音频/MIDI内容仍来自隔离测试工程。原clip编辑/Undo、精细网格与波形测试没有移除。所有新增结果仍等待统一构建与执行。

### 首轮截图后的目标标识修正
已查看 workspace-smoke/10824f53c42b/ui-workspace-brand-1280x800.png：效果器链缺少所属轨，选中轨被视口遮住时不能确定调节目标。DeviceChainStrip 左侧新增固定 120 px（窄于 600 px 时 100 px）的目标轨名称，完整名称 tooltip，空轨提示独立。600 px 链仍保留约 300 px 装置视口，左右导航与 Add 未移除。没有修改 Arrangement 行高或总文档；本修正待 root 最终构建与截图验证。


## 统一验收补记（root，2026-11-06）

本分工冻结后的相关原生/Python/网页/组件回归已由主任务执行并通过，精确命令、失败链、源码/产物指纹与限制见 [RESULTS](RESULTS.md) / [VERIFICATION](VERIFICATION.json)。前面的“待验”保留为当时状态；物理 ASIO、鼠标/DPI 与听感仍待人工。

根任务最终将宽EQ上下布局门槛改为720×240，默认下栏280px（body244），用户可拖高；600×212紧凑布局保持。1440×900合成六轨可完整显示，装置链左侧明确目标轨，实际截图已复核。
