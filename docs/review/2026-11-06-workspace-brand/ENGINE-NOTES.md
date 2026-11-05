# 0.11.0 引擎颜色与原生效果手势

日期：2026-11-06。状态：**已实现，等待 root 统一编译及离线回归**。本文件不代表声卡、连续播放或实际鼠标听感验收。

## 轨道颜色契约

- 共用原生命令 `set_track_colour`，参数仅为 `{ "track_id": "稳定轨道 ID", "colour": "#RRGGBB" }`。大小写输入均接受，回读统一大写；`""` 恢复默认配色。拒绝非字符串、短格式、alpha、空格、非法十六进制和多余字段。
- `EngineSession::TrackSnapshot.colour`、`StoredTrack.colour` 和 JSON `tracks[].colour` 同义。字段附加在结构体尾部，保持已有聚合初始化位置；没有修改插件快照字段。
- 权威值在现有 Edit 的轨道 `emColour` 属性中。内容指纹包含颜色，遵循 revision、dirty、Undo/Redo 和原生 batch 原子语义。
- 单独染色和仅含染色的 batch 使用元数据快速路径，验证完整候选后直接写属性，不调用 `applyTo`，不替换 Edit、轨道、clip、MIDI 序列或插件实例。混合结构编辑 batch 仍走原有通用应用流程。
- 保存清单增加可选 `colour` 字段，不升 schema；旧工程缺字段读为空，旧版软件读取新工程可能忽略这一视觉字段。存档写入规范大写值。

## 原生效果连续手势

四个命令均通过 `EngineSession::execute`：

| 命令 | 参数 / 结果 | 行为 |
| --- | --- | --- |
| `begin_native_effect_gesture` | `{track_id, device_id}` → `{gesture_id}` | 校验归属、保存项目和 revision；一次仅允许一个效果手势 |
| `update_native_effect_gesture` | `{gesture_id, state}` | 校验完整效果配置，向现有 DSP 发布预览；不写 Edit、不增 revision、不改变 dirty/Undo |
| `end_native_effect_gesture` | `{gesture_id}` | 只提交最后的合法值，一次 revision、一次 Undo；没有变化则不创建历史 |
| `cancel_native_effect_gesture` | `{gesture_id}` | 恢复当前已提交状态，不恢复过期的开始值；不改工程历史 |

预览只保留一个设备的小型配置草稿，不建立第二套可写工程。`set_native_effect` 独立命令也改用轻量提交：一个 UndoableAction 同步现有逻辑设备槽和 live plugin 的状态字节，复用原来的 DSP 实例。原生效果 DSP 读取原子参数发布；音频回调不执行 JSON、文件、网络、Undo 或命令分发。

GUI 可缓存 begin 时的 revision，正常拖动每步无需构造工程快照。其他编辑、保存、导出、Undo、新建/打开以及切轨取消预览；异步外部修改推进 revision 时同样取消。错误 token 不会取消别的手势。取消恢复的是当前权威参数，因此不覆盖其间合法编辑。纯读取及播放/暂停/停止/定位不取消。既有音量手势 API 保留，开始音量手势时先取消效果预览。

录音中或仍有后台任务时暂不开始效果手势，沿用当前编辑边界。效果面板的失焦、隐藏、Escape、切设备生命周期由 NativeEffectsPanel 负责。Python Agent 保持已审核的最终参数命令，不自动持有 GUI 试听草稿。

`nativeEffectSpectrum(projectId, trackId, deviceId, std::array<float,2048>&, sequence)` 是控制线程只读接口，核对项目、设备归属和启用状态。DSP 提供有限采集租约；FFT 和绘制在界面线程。未添加返回原始音频给 Agent 的工具。

## 检查与待验收

新增 `tests/EngineSessionWorkspaceSmoke.inc`，入口为 `runWorkspaceEngineSmokeTest(report, outputDirectory)`；root 的新工作区 smoke 负责调用。全部使用测试自身的离线 EngineSession 和输出目录，不读取用户工程或连接真实音频设备。

已编写的回归覆盖：

1. 颜色规范化、未知字段及类型拒绝、无变化不增 revision；Edit/轨道/clip/只读音符视图保持同一实例。
2. 染色 Undo/Redo、同轨连续染色 batch 的一次提交和一次 Undo、后一个命令失败不产生部分变更。
3. 颜色保存/重开、去掉颜色字段的旧清单兼容、非法清单拒绝。
4. 原生 compressor 无变化手势、非法数值、30 次 preview 后一次提交/Undo/Redo；预览不变更 committed state、dirty 或历史。
5. 合成离线 DSP 电平验证 preview、Undo 和 cancel 的实际参数作用；固定 48 kHz、128-frame block、每次观察 32 blocks、双声道常数 0.2。此项是功能回归，不是设备性能或听感测量。
6. 错 token、外部改名打断、同步兼容保存和实际异步 `save_project` 边界；存档只写已提交参数，颜色和效果重开保留。

本子任务未自行运行构建或测试。统一命令、开始/结束、产物及原始日志由 root 的 Recorder 记录；最终通过数量和证据应在本目录 RESULTS 与本文件追加。连续拖动手感、真实播放无爆音、录音设备、DPI 和硬件占用仍需单独人工验证。

## 追加：Agent 颜色真实宿主闭环（待执行）

`tests/MusicAgentColourIntegration.py --exe <新构建 EXE> --timeout 60` 使用复制到独立测试目录的原生程序、真实 stdio bridge 和确定性语言 Provider。编写了两轨颜色规范化、先 review 后一次 batch、精确回读、一次 Agent Undo / 原生 Redo、实际异步保存重开、音符和其他音乐内容保持不变、原生 stale-selection revision 拒绝。

该进程没有真实 GUI 选区，测试不伪造这一能力：原生 headless 当前选择请求应拒绝；另在真实 ID 的快照副本上明确标记一个合成单轨选区，只运行 Python 授权 guard 检查另一轨不得越界。报告 `gui_selection_tested=false`、`physical_audio=false`、`external_llm=false`，包含实际 EXE SHA 和保护文件检查。脚本已完成，仍由 root 统一 Recorder 执行并补充结果。


## 统一验收补记（root，2026-11-06）

本分工冻结后的相关原生/Python/网页/组件回归已由主任务执行并通过，精确命令、失败链、源码/产物指纹与限制见 [RESULTS](RESULTS.md) / [VERIFICATION](VERIFICATION.json)。前面的“待验”保留为当时状态；物理 ASIO、鼠标/DPI 与听感仍待人工。
