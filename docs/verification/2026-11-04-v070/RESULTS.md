# 0.7.0 Focus + Mix 交付记录

日期：2026-11-04（Asia/Shanghai）。原生 JUCE 界面已接入，最终 Release 自动回归 **5/5 通过**。源码与构建/测试指纹一致；实际设备、听感、第三方插件窗口和 Windows DPI/物理快捷键的新版人工短测尚未执行。

## 版本与回退

- 当前入口：`build/bin/Release/E-musician.exe`，0.7.0；独立副本 `releases/0.7.0/E-musician.exe`。
- 原版：`releases/0.6.1/E-musician.exe`、PDB、`source-v061.zip`；源码分支 `archive/v0.6.1-before-focus`，基线 `7f7eb65`。
- 原 EXE SHA-256 `491ba101bfe1eefb48a82bacba2226c722c7e97bc87e4743ff5e45cd4e6a4cfe`；保留副本校验一致。
- 新 EXE SHA-256 `133f9139b9b56c6fc7f89613b18454bc613ba57996947fbefd868b8719773566`。
- 新源输入 SHA-256 `79e8eff06b55bcdc75b25270be0cceb9e74fe0fd0983bec75e71597ee254cf37`。
- 526 个原有用户工程/设置文件的逐文件 SHA-256 均未改变；精确清单仅在本地 `.cache/v070/`，不上传用户工程或设置。

## 实现范围与功能保留

编曲、完整钢琴卷帘、完整混音三个工作区共用原工程；右侧常驻所选轨+Master。Clip填满轨高，轨道色/标题与背景区分，原细网格/三级标尺/拖动裁剪保留。旧MIDI Dock、Source、Clip精确起点/属性、设备链、I/O/send、Automation及Master入口继续可达。新增推子使用原命令及Undo手势，电平是实际引擎快照。项目、录音、ASIO、插件、导出和Agent JSONL的引擎/存储实现未修改。

[54项源码功能清单](../../review/2026-11-04-focus-native/FEATURE-PARITY.md)记录每项入口及证据范围；源码保留与自动回归不是每一种第三方插件/设备已人工通过的承诺。无新增自动保存、恢复、和弦工具、模板或Agent业务。

## 构建与测试

所有尝试由 `scripts/dev.py` 记录，源码在每轮配置/构建/测试期间冻结。

| 轮次 | 检查记录 | 结果与目的 |
|---|---|---|
| 1 | [432e15cfda](../../builds/20261104T154035.555249Z-432e15cfda.json) | 5/5，85.99s；基础迁移、满高Clip、双混音和页面布局 |
| 2 | [2b80bd6373](../../builds/20261104T154520.307263Z-2b80bd6373.json) | 5/5，82.61s；修复隐藏片段快捷键、Mixer进入MIDI、延迟推子读回 |
| 3 | [d47870478c](../../builds/20261104T154820.152862Z-d47870478c.json) | 5/5，81.61s；小窗口推子刻度不重叠、Focus播放按钮 |
| 最终 | [66a086799d](../../builds/20261104T155535.526844Z-66a086799d.json) | 5/5，101.85s；补齐 Devices/I/O/Automation/Master 原生截图及最小 Dock 边界 |

最终[构建记录](../../builds/20261104T155508.416921Z-940a29deca.json)与测试均 `source_changed_during_command=false`，且首尾指纹与交付源码一致。MSBuild输出中出现`pwsh.exe`不可用信息，返回码为0、实际EXE生成、版本资源与全部后续测试成功；原始日志保留，不把该信息隐藏或改写成失败。Debug未重建。

五组：开发日志、固定引擎补丁、核心契约、引擎/工程/Clip/DAW/存储/生产录音路由及原生UI集成、控制输出隔离。生产录音/路由/自动化报告229项通过。新增验证包括：

- Clip整轨高，保留原拖动/裁边/淡化/选区/三连音/1/16384回归。
- 两处Mixer参数同步、单手势Undo、声像C/L/R、松手后同revision回读校正。
- Mixer的Delete/Cut/Duplicate/Split不会修改隐藏片段；完整MIDI页音符删除保持Clip，Undo恢复。
- Mixer中的Edit MIDI入口能显露编辑器。
- 三页1000×650、1440×900、1920×1080的常驻rail位置、选中轨、revision一致；保留最小窗口MIDI Dock的两行编曲。
- 原保存保护、失败/过时请求、收尾回调、MIDI导出/重开等现有检查继续执行。

离线组件CPU检查：100000音符局部横移+绘制P95约1.97ms，拖动+绘制约1.79ms，细网格迭代约0.0018ms；详细参数与样本在[arrangement报告](arrangement-report.json)。这些是Windows Release合成组件CPU耗时，不是音频延迟、屏幕输入延迟或任意工程性能保证。

## 视觉与审查

截图是当前EXE生成的原生组件渲染，内容来自隔离测试工程，无网页原型或用户工程截图混入：

- [编曲](arrangement-1280x800.png)
- [钢琴卷帘](piano-1440x900.png)
- [混音](mixer-1440x900.png)、[最小窗口混音](mixer-1000x650.png)

独立[代码审查](../../review/2026-11-04-focus-native/CODE-REVIEW.md)的R1–R3根因已修复、复查和运行断言通过。独立[视觉复核](../../review/2026-11-04-focus-native/FINISH-REVIEW.md)结论为 **SHIP：可交付本机短测候选**。摘要与截图哈希见[SUMMARY.json](SUMMARY.json)。[I/O 面板](io-minimum.png)、[带测试点的自动化](automation-minimum.png)、[Master 设备](master-devices.png)也已捕获。完整本地证据：`build/smoke/Release/a3c9360dc861`。

## 下一步人工短测

按[短测清单](../../review/2026-11-04-focus-native/MANUAL-CHECK.md)，用旧工程副本检查播放/录音、三页切换、细网格、Undo、设备/I/O、保存重开和导出。用户提供截图/现象，开发者继续构建与debug；没有使用computer-use操作用户窗口。
