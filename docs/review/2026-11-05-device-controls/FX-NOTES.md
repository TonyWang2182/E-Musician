# 效果器控件实施记录 · 2026-11-05

状态：实现和集成自动验证已完成，最终证据以 [RESULTS](RESULTS.md) 为准；真实桌面和听感待人工。以下保留本分工的实现及审查记录。

## 参考与取舍

阅读 [Ableton Live 12 Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/) 及 [FabFilter Pro-Q Knobs](https://prod.fabfilter.com/help/pro-q/using/knobs)。借鉴图形直接操作、参数分组、垂直拖动与精细调整；保持项目现有黑白/等宽设计，不复制品牌皮肤或未实现功能。FabFilter 的键位并非全量照搬：本工程旋钮双击恢复默认，数值框单击编辑，Shift 拖动精调；滚轮禁用以免滚动设备区时误改声音。

## 实现

- `DeviceControlStyle.h`：共用 `emusician::deviceui::ControlLook` 和 `configureKnob`。明确的可编辑数值框及颜色，避免外层 LookAndFeel 导致值框不清晰；旋钮具有焦点、禁用及悬停状态。
- `NativeEffectsPanel.cpp`：五种效果器统一旋钮/直接数值输入；效果开关走既有 `set_plugin_enabled`；重置走一次 `set_native_effect`。EQ 重置仅作用于当前段，其他装置重置整个当前设备。
- EQ 使用主代理新增的六种 shape 参数，禁用 cut/notch 无意义的 gain 控件；图中编号、选中环与按钮一致。
- `NativeEffectsGraph.inc`：EQ 响应与节点拖动；压缩器真实 wet 静态曲线、T/R 两个拖点及读取原有原子 GR 的可见表；Delay 回声电平/时间指引及 T/F 拖点；Reverb 非实测 RT60 指引与衰减时间拖点/阻尼条；Auto Filter 与当前 RBJ DSP 同公式的中心 cutoff 湿信号响应、cutoff/Q 拖点、LFO 范围及一秒静态波形指引。
- 图形只读/修改消息线程的参数快照，不取实时音频；没有伪造的实时频谱或房间脉冲响应。EQ/滤波曲线固定 180 个采样点，仅参数/尺寸变化重算。动态 GR 的 UI 轮询仍为 4 Hz，隐藏父窗口低频恢复，显式隐藏停止。
- 所有连续拖动先修改局部预览，释放才通过带 revision、project/track 校验的统一命令提交；Esc 取消图形拖动，不把无变化点击写成命令。
- 600×212 的最小工作区、600×250 与 1000×250 的实际组件布局，压缩器/滤波器旋钮分两行；EQ 给 shape 行单独预留空间，窄窗不让旋钮盖住下方控件；不新增串行音频线程工作。

## 新增的集成冒烟验收点

原生 UI smoke 覆盖轨道及 master 的 EQ shape/unused gain/reset、开关真实 slot、旋钮和非空值框边界、五类装置 600/1000 尺寸截图、压缩器拖动预览与 Esc/释放、Delay 时间、Reverb 衰减及 Filter cutoff/Q 拖点命令回读，保留之前过时 revision 的拒绝测试。

集成首轮 600×250 EQ/Compressor/Delay/Reverb 与 1000×250 Filter 的离屏图已人工读图确认数值可见、层次清晰；主代理随后压缩宿主的重复标题行，为最小窗口保留编曲轨道空间，因此补充了 600×212 的全部控件边界检查及 EQ/Compressor/Filter 截图。完整窗口与新最小尺寸结果仍由主集成记录归档。

需人工确认：实际显示器和 DPI 下的值框文字、Shift 精调/数值键盘编辑、图形拖点和 Undo、声音变化。离屏/合成事件不等于真实 ASIO、实体鼠标或听感验证。尚无新增实时频谱、动态 EQ、侧链、节奏同步或完整 Ableton 装置等价能力。

## 集成前审查修正

独立审查指出压缩器 R 拖点原以 -1 dB 输入反算比率，在 threshold 接近 0 dB 时失效；改为 0 dB 输入，threshold=0 时不绘制/命中没有可辨识斜率的 R 点，旋钮仍可设 ratio，并增加 -0.5 dB threshold 下 4:1→8:1 回归。低采样率时，频率文本保留用户请求值，EQ 节点以 DSP 的 0.475×sampleRate 上限定位，Auto Filter 节点和 LFO 范围以 DSP 的 0.45×sampleRate 上限定位；新增 22.05 kHz / 20 kHz 请求 / Q=10 的显示数学检查。上述为新增源码检查项，运行结果由主集成记录给出。
