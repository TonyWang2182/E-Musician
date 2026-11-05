# 0.8.1：矩形片段与原生装置控制

日期：2026-11-05，Asia/Shanghai。状态：**实现和 Release 自动验证完成；真实桌面/DPI/设备听感待用户检查。** 入口和步骤见 [人工短测](MANUAL-CHECK.md)，参考与任务分工见 [计划](PLAN.md)。

## 已实现的范围

- 钢琴卷帘音符为占满音高行的直角矩形；音频/MIDI clip 填满普通或紧凑轨道的片段行，保留细分隔线。绘制与命中区域一致，实际音符时长和未吸附位置保持不变。
- 七种现有装置统一黑白旋钮、数值输入、Shift 精调和双击复位。图形可拖动参数，本地预览、释放提交、Esc 取消；所有工程修改沿用统一命令、revision 和 Undo。
- Sampler/Rack：真实波形及 AR 图，每个 pad 的 Attack/Release/Gate/One-shot；鼓垫播放图形和双击试听。纯参数改动共享已有不可变 PCM，避免重新读取解码同一采样；显式换样本和工程重开仍核对源内容。
- EQ：八段各自可选 Bell、Low/High shelf、High/Low pass、Notch；图和声音共用频响计算。Compressor：六个旋钮、阈值/比率拖点、真实 GR。Delay/Reverb/Auto Filter：旋钮及回声/衰减/截止共振/LFO 图示，图示明确是参数展示。
- 下栏去掉重复标题，设备顺序条与关闭按钮同排。1000×650 最小窗口保留一条完整紧凑轨道，1280×800 保留至少两条；装置控件覆盖 600×212、600×250、1000×250 等尺寸。
- 新增声音参数接入宿主校验、保存、能力目录、Agent schema、局部修改、回读和撤销。Agent 只改一个包络值时，由本地读取并保留其他值；EQ 修改不覆盖其他频段。整台装置旁路仍属于宿主命令/UI，未加入模型动作列表。

新参数超出旧版默认行为时，装置状态保存为版本 2，旧程序明确拒绝；保留默认行为时仍使用版本 1。新程序可读取旧状态并填入旧默认值。详细边界见 [ADR](../../decisions/2026-11-05-visual-device-controls.md) 和 [接口](../../AGENT_API.md)。

## 最终验证与可追溯产物

最终源码 SHA-256 `846b6b2c43d7e35dc046f39f1f879b3af692066c0f9bfcd8b529018c23008a7f`，161 个源码输入；EXE SHA-256 `c0099db16a428b04e8bda55fef6444658711c8cafa9b784a7b5a127979ab9082`。最终五条构建/测试记录的开始及结束源码指纹一致。命令、UTC 时间、日志及产物位置见 [VERIFICATION.json](VERIFICATION.json)，相对上一验证候选的 28 个源码变动文件见 [SOURCE-CHANGESET.json](SOURCE-CHANGESET.json)。早期并行捕获已包含矩形视图和共享旋钮文件，清单同时保留这份捕获与上一验证版本，未误称干净基线。

| 检查 | 实际结果与记录 |
|---|---|
| Release x64 构建 | 成功，22.50 s；[构建](../../builds/20261104T174510.587395Z-4b892d27f9.json) |
| CTest 全套 | 10/10，86.00 s；DSP、存储、录音/路由及 UI/引擎 smoke、输出隔离等；[记录](../../builds/20261104T174533.245723Z-a02903701d.json) |
| Agent Python | 245 项通过；[记录](../../builds/20261104T172818.461252Z-a094aa0dd4.json)。此后全部 scripts/ 与 tests/test_music_agent* 输入 SHA 未变；另有端到端脚本见下行 |
| 原生效果真实离线音频 | 11 项通过，包括新 EQ 形状的实际衰减、无效值拒绝、Undo/Redo、主轨、保存重开；[记录](../../builds/20261104T174659.712267Z-feb39b69b2.json) |
| Sampler/Rack 真实离线联测 | 12 项通过，新增包络/播放模式、保存重开与撤销；[记录](../../builds/20261104T174745.104050Z-00fbfd9c95.json) |
| 模拟模型 → 真实 DAW | 11 项通过，包含单参数保留、EQ 形状和采样包络、能力目录、异步终态、回读与 Undo；最终保护集 added/removed/modified 均空；[记录](../../builds/20261104T174758.755341Z-3cbfcfa5d9.json) |

代码生成的真实组件截图来自 `build/smoke/Release/9e3d5fba7f82/`，测试素材为生成的 WAV，不是用户工程：[矩形音符](screenshots/piano-full-row-rectangles.png)、[编曲片段](screenshots/ui-clip-start8-1280x800.png)、[最小窗口及设备链](screenshots/ui-device-chain-1000x650.png)、[Sampler](screenshots/ui-native-sampler-dock-600x212.png)、[Rack](screenshots/ui-native-rack-dock-600x212.png)、[EQ](screenshots/ui-native-eq-minimum.png)、[Compressor](screenshots/ui-native-compressor-minimum.png)、[Auto Filter](screenshots/ui-native-filter-minimum.png)、[Delay](screenshots/ui-native-delay-dock.png)、[Reverb](screenshots/ui-native-reverb-dock.png)。已读图复查，不能代替实体鼠标和用户 DPI 验收。

## 性能测量边界

Lenovo 21HX，Intel i7-13700H，系统报告物理内存 31,923,757,056 字节，Windows 11 build 26200，Visual Studio 18 2026 / Release x64。JUCE 8.0.6 `19edd538429c93d277bf95b55aaa7e3eb545f951`，Tracktion Engine 3.2.0 `b0c7dd090a56b27fe01bb394617891906eb34daf`，固定依赖来源见 `cmake/dependencies.json`；沿用 `.cache/monitor-engine` 和既有受控补丁。

10 万音符合成局部视图，深缩放平移与拖动加离屏绘制的 CPU P95 分别 **1.161 ms / 1.406 ms**，最差 1.832 / 2.021 ms；索引在手势中复用，最大查询索引节点数 18。原始字段在该 smoke 的 `arrangement-report.json`。这是 UI 合成工作负载，没有声卡、屏幕帧呈现或模型参与；不外推为所有工程的 FPS/实时延迟保证。离线音频检查采用 48 kHz 立体声生成素材，未打开物理设备，实际设备缓冲区为 0/不适用；本轮没有新增 ASIO 性能基准。

## 过程中的失败与修复

所有尝试的开始/结束时间、命令、配置及原始日志路径在 `docs/builds/`；DEVLOG 保留追加记录。

1. [首次 UI smoke](../../builds/20261104T172841.644105Z-f2c10585e6.json) 在包络 Escape 的精确浮点相等断言失败，改为容差并检查取消后的拖动标志。离屏钢琴卷帘黑图则来自 Direct2D 尚未 flush，已让 Graphics 生命周期结束后读取像素并检查首尾行。
2. [第二次 smoke](../../builds/20261104T173320.932811Z-0d7f8c79bd.json) 暴露标准窗口轨道空间不足；随后实际截图又显示最小窗口只剩标尺。修复重复标题开销、紧凑控件布局，并补最小窗口完整轨道断言；没有通过删除原空间要求让测试变绿。
3. [首次 Agent 联测](../../builds/20261104T173121.837881Z-4195d8b24a.json) 的 11 个功能检查通过，但保护文件集合发生变化，整体判失败。当时同时运行另一套共享本机缓存的联测，未保留路径差异，无法断言具体原因。现增加 added/removed/modified 记录并串行运行；[首次串行重测](../../builds/20261104T173722.106363Z-085578a84e.json) 保护集无变化。此结果不能扩大为整轮所有本地文件完全未变。
4. [效果音频联测](../../builds/20261104T174140.635326Z-decbe84334.json) 在工程重开后立即导出，被“采样仍在加载”拒绝。测试原只等待当前 Sampler/Rack 个别场景，后续效果器场景遗漏了同工程内的异步采样。现在每次重开都等待本测试所有原生乐器明确 ready，错误或超时直接失败，不重复提交失败写命令，也未放宽宿主导出保护。
5. 审查还修复了接近 0 dB 阈值时的压缩比拖点反算、低采样率时节点与 DSP 截止上限不一致、最小面板的频率刻度与 Hz 标签重叠。相应交互/数值/截图检查保留在实际 smoke 中。

## 仍需人工验收和保留的限制

- 没有使用 computer-use，没有启动用户工程进行操作；用户负责真实鼠标、键盘、DPI、M-Audio ASIO 和听感。此次不重新宣称旧版录音/Keyscape 验收适用于所有新组合。
- 没有付费模型请求。Agent 联测使用确定性模拟 Provider 和真实隔离 DAW，验证工具链，不能证明自然语言理解成功率。
- Sampler 仍为单 WAV，Rack 为 16 垫；仅 AR 和 Gate/One-shot，没有完整 ADSR、循环、Warp、多层采样或合成器。新 bank 发布仍会停止当前声音，下一次按键使用新设置；暂不承诺连续无缝参数自动化。
- Delay/Reverb/LFO 等图示不是实时频谱、实测房间响应或音频分析。没有新增外部侧链、动态 EQ、Tempo 同步，也不宣称完整 Ableton 算法或商业装置等价。
- Release 离线结果不等于实际声卡低延迟/长期稳定性。原版 EXE 保存在 `.cache/pre-device-controls-20261105/`；当前功能工作树的既有未提交修改均保留，本轮没有合并或推送 main。
