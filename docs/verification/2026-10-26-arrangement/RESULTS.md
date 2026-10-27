# 0.2.1 编曲总览验证

日期：2026-10-26（Asia/Shanghai）。结论：**本轮多轨可见与导航修复通过，Debug/Release 全部自动测试通过。独立界面复核的两项交互缺陷均已修复，disposition 为 ship。** 此结论不表示完整 DAW/M2 或长期性能全部完成。

## 用户问题与交付

用户确认上一轮手工验证“补齐了”，随后指出编曲视窗看不到所有轨道。0.2.0 的中央波形只对应选中轨且 Compose 禁用；0.2.1 默认进入 Compose，在同一秒标尺上显示各轨真实波形和时长。选择同步列表与 Inspector，超出视口的轨道可滚动或通过选择滚入；1–32x 缩放、fit、横向滚动及定位共用同一 Transport。Separate 保留单轨细看，Transcribe 仍未实现。

用户的 `test-projects/CL.emproj` 为已有 schema 1 工程，本轮无需迁移，不重新保存。

## 最终构建与源码

| 配置 | 编译 | 自动测试 |
|---|---|---|
| Debug | [成功](../../builds/20261026T121615.152502Z-81c2ee5471.json) | [3/3 CTest 组通过](../../builds/20261026T121626.313758Z-3c453fe7be.json) |
| Release | [成功](../../builds/20261026T121719.630723Z-a6a433ab65.json) | [3/3 CTest 组通过](../../builds/20261026T121729.517740Z-0eb216527d.json) |

源码 SHA-256：`a8d3e9ad055f58e17c790406d24ec64a4965a4dd1542efc323c2101a2251ed94`。最终命令开始/结束指纹及收尾再次计算均一致。Windows 11、MSVC、固定 Tracktion/JUCE 组合；环境及原始输出路径见各 JSON。可选 pwsh.exe 不在 PATH 提示仍存在，构建返回 0，程序运行测试通过；没有为此修改系统工具。

首次编译因 JUCE Rectangle 无 getSize() 失败，[记录保留](../../builds/20261026T120354.872958Z-c1a4674f7e.json)。改用显式宽高后成功；同时修复最高缩放下短音频的时间标签精度。后续独立审查提出的焦点与拖入反馈在最后一批修复后重新跑了两配置。

## 自动验证内容

- `development.logging`：3 项日志回归。
- `core.contracts`：84 条核心断言。
- `engine.integration_smoke`：原引擎渲染/短时设备时钟、202 个 MP3/工程检查点和新增编曲组件检查。202 包含原有 196 项及每轨 WAV/MP3 准备源契约；这些计数处于不同层级，不相加冒称测试用例总数。
- 编曲检查通过真实组件回调/事件验证：默认页、切页、缩放按钮、三条真实轨道及峰值完成、共同时间比例、选轨、点击/拖动定位、首尾边界、32x 相邻时间标签可区分、水平范围、纵向末行可达、选中轨自动滚入、Home/End、导航不改变 revision/dirty、拖入/离开反馈及 Inspector 状态。
- 本轮几何样本实际时长为 2.000 / 2.040 / 2.037551 s，共同坐标下宽度约 548.04 / 559.00 / 558.33 px。短轨没有拉伸到最长轨长度；未将这组近似时长样本称为极端长短差视觉测试。
- 保存重开后的离线渲染逐样本最大差值仍为 0；导入/保存/打开失败保护、Undo/Redo、原素材归档与工程搬移回归继续通过。

报告：[arrangement](arrangement-report.json)、[project](project-report.json)、[engine](engine-report.json)、[transport](transport-report.json)。Realtek 48 kHz / 480 samples、-60 dB 短时设备时钟测试通过；不代表物理听感、loopback 或低延迟性能测试。

## 用户真实 CL 工程

[最终 Release 只读运行记录](../../builds/20261026T121924.309761Z-6a18fd8285.json) 与 [预览报告](preview-report.json)：2 条 MP3 音轨，工程时长 394.370612 s（约 6:34.4），两份峰值均完成。加载后 dirty=false、playing=false；没有执行保存或播放。两轨在 1280×800 与 1000×650 都同时可见，增益分别显示 -32 dB 和 0 dB。

本机 `project-preservation.json` 文件保护记录：目录内全部 7 个既有文件（清单及不同素材代次）在最初与最终预览后 SHA-256 一致，未覆盖用户工程。逐文件素材清单保留本机，不发布到公开仓库。

预览还验证了已有输出目录保护：[有意触发的拒绝记录](../../builds/20261026T120844.441567Z-6bf3bd0b3f.json) 返回预期 exit 1，原有 failure.txt sentinel 和目录内容不变，[保护报告](preview-guard-report.json) 为 passed。预览错误只写 stderr，不能在未拥有的目录落诊断文件。

## 原生界面与独立审查

| 状态 | 证据 |
|---|---|
| 用户 CL 两轨 | 本机 `ui-project-1280x800.png`、`ui-project-1000x650.png`，含用户波形，不发布到公开源码仓库 |
| 自有三轨及小窗口滚动入口 | [1280×800](ui-1280x800.png)、[1000×650](ui-1000x650.png) |
| 空态 | [1280×800](ui-empty-1280x800.png) |
| Separate 细看 | [截图](ui-separate-1280x800.png) |
| 32x 高倍刻度 | [截图](ui-zoom-1280x800.png) |
| 拖入目标状态 | [生产 drag enter/exit 回调截图](ui-drag-1280x800.png) |
| 真实原生焦点出现/离开 | [聚焦](ui-focus-native.jpg)、[离开画布后](ui-unfocused-native.jpg) |

独立首审确认多轨修复主体通过，提出两个 P2：Compose 没有可见键盘焦点、默认 Compose 下拖入只更新隐藏的旧波形。最终修复让 Canvas 依据 `hasKeyboardFocus(true)` 绘制当前 viewport 角线，focus 回调触发重绘；生产 drag enter/exit/drop 同步 ArrangementView 状态，拖入时角线加粗并显示 `drop WAV / MP3`。

实际 Computer Use 在可见 Debug 空工程点击画布后角线出现，点击 Compose 标签后角线消失，随后正常关闭测试窗口，最终窗口清单为空。[启动记录](../../builds/20261026T121726.545099Z-e40e83a2f9.json)。原始捕获为 JPEG，按原字节归档；UIA 仅报告顶层窗口焦点，因此内部焦点结论依实际可见反馈与组件代码，不假称 UIA 已验证内部焦点。没有使用伪造的 focus flag。

独立 verdict pass 对两项均评分“已修复”，disposition **ship**，仅关闭这两项，首审未验证范围继续保留。设计文档独立核对也确认：沿用既有灰阶、等宽、细线和角线体系，PRODUCT/DESIGN 与本轮实现一致，无需新增视觉系统或资产。

## 明确保留的范围

尚未完成 OS 鼠标全流程、64 轨压力、长中文极端标签截图、加载/失败截图、高 DPI、长期播放或低延迟基线；不能从组件事件报告推断这些全部通过。用户的手工确认不代替独立性能测量。

仍无片段移动/裁剪/分割、音乐网格、MIDI、模型分离/转录、Agent 或用户导出。峰值固定 512 samples/point，32x 短音频显示包络而非逐样本细节。后台化的是波形峰值；MP3 初次 PCM 准备、工程导入/打开与素材复制保存仍同步，缓存与旧素材代次尚无自动清理。schema 1 保持不变。

下一步推进片段编辑及撤销/持久化迁移，同时建立 B01 多轨长期基线和后台文件任务。
