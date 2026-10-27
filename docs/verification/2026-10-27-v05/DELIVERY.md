# E-musician 0.5.0 交付摘要

2026-10-27，Windows x64 Release。基础编曲、保存管线和本轮新增录音/路由/自动化已实现，并通过下列指定测试。用户的33个原工程及素材文件全部保持原SHA256。应用位于本机 `E:\E-musician\build\bin\Release\E-musician.exe`，操作见[快速上手](../../QUICKSTART.md)，源码在[GitHub](https://github.com/TonyWang2182/E-Musician)。

## 当前可用功能

- 单主编曲视窗、多轨音频与MIDI片段、底部钢琴卷帘、轨道混音和插件链；新工程120 BPM、4/4，无和弦模板和内置音源。
- WAV/MP3导入、MIDI导入编辑、Windows x64 VST2/VST3宿主、WAV/MIDI导出、工程保存重开及Undo/Redo。
- 音频/MIDI线性录音、输入选择/Arm/监听、M-Audio ASIO设置；总线、前/后推子发送、输出目标和反馈回路拒绝；手动编辑并播放轨道/Master/插件参数自动化曲线。
- GUI与预留Agent共用命令、版本检查、任务进度和取消；当前提供本地JSONL接口，不包含模型Agent。

保存先反馈状态，分阶段获取插件状态，后台复用已有媒体并原子提交清单。修复Serum播放后插件路径变化造成保存后仍dirty、重复参数回报误标修改，以及失败任务阻挡立即重试；保存期间的新编辑仍保留未保存状态。

## 本机验证结果

| 验证 | 结果与范围 |
|---|---|
| 最终双配置 | [Release/Debug各5/5](34eb7d59-dual-config-summary.json)，首尾源码一致；含工程、存储、片段、生产图及UI组件检查 |
| 两轨音频＋Serum | [播放中8次保存](34eb7d59-playback-save.json)，93.36–170.83ms；48kHz/256 ASIO，xrun0；重复保存复用31551826字节媒体，仅新写约22.5KB；后续编辑保护及重开一致 |
| 原生操作 | [另存为、Serum旋钮、按钮Save、播放中Save、MIDI拖动/Undo、三轨可见、ASIO Apply](native-ui-summary.json)；最终EXE[新进程回读](34eb7d59-native-reopen.json)恢复一致。原生全流程并未全部覆盖 |
| 实际插件 | [4款逐款10项](6414b6c8-plugin-matrix.json)：Serum VST3、Ample Bass P VST2、Auto-Key 2 VST3、BM-DOPE VST3；含扫描、状态、Undo、保存重开及非零渲染，不是四插件同时设备播放或全插件兼容保证 |
| 实际录音 | [M-Audio ASIO48k/256物理输入短录音](6414b6c8-hardware.json)，约2秒mono 24bit、收尾71.5ms、xrun0、保存重开；合成MIDI录音和控制器/Undo在生产检查中，未演奏实体键盘或人工试听 |
| 100000音符 | [停止播放、无插件JSONL测量](6414b6c8-midi-performance.json)，单音符编辑P95=26.42ms，原50ms门槛保持；不是鼠标到绘制延迟 |
| Agent任务 | [导入、取消、打开冲突、保存代次与SMF策略通过](0f5a27e6-agent-jobs.json)，无测试专属生产hook |

## 30分钟持续负载

[原始报告](34eb7d59-performance-30min.json)，[执行记录](../../builds/20261027T014700.122339Z-5599e4a30c.json)。机器为Windows 11、i7-13700H、20逻辑CPU、30445 MiB RAM，Release x64；M-Audio M-Track Solo and Duo ASIO，实际48000 Hz/256 samples。16条独立8秒合成立体声WAV循环、无第三方插件、窗口隐藏；预热120.09秒后正式测量1800.012秒，期间每约5秒提交声像编辑。

| 指标 | 实测 |
|---|---:|
| 音频中断计数增量 | 0；播放持续，未自动重启 |
| 回调次数 | 337504 |
| 音频处理均值 / 最大 | 0.493 / 1.755 ms；块预算5.333 ms |
| 357次控制命令P95 / 最大 | 1.931 / 6.112 ms |
| 消息定时器迟到P95 / 最大 | 2.741 / 155.951 ms |
| 设备音频负载采样均值 / 最大 | 9.30% / 17.55%（不是全机CPU百分比） |
| 进程CPU占用 | 单个逻辑核基准92.48%，可跨线程累加 |
| 私有内存起点 / 终点 | 226430976 / 227106816 bytes，增长675840 bytes（约0.64 MiB） |

指定探针门槛通过。没有逐回调P99.9分布、物理输入到绘制或端到端音频延迟测量，`b01_acceptance_complete=false`保留。隐藏窗口测试不证明可见UI绘制性能；定时器最大迟到保留原值，不用均值掩盖尾部延迟。这一30分钟样本也不能证明无限运行没有泄漏或所有插件负载稳定。

## 可追溯与边界

最终源码指纹 `34eb7d59f81aac2e98ca90500e8dcce3bb3ce0c23a5c0f6b6fce59d2188c4676`；Release EXE SHA256 `1a72c25210e296898167db1e33f57f4cbee0b21fa8c358e636917ee8f23024dd`。源码与档案已发布为[提交1ddef4e](https://github.com/TonyWang2182/E-Musician/commit/1ddef4eedfbe83a1c32b06668a0cef3711c17d2f)，后续为文档收口。[完整性摘要](34eb7d59-final-integrity.json)保留报告哈希、内存首尾及33个用户文件共410250775字节未变的结果；精确用户素材清单和音乐不发布。较早6414应用源与最终候选的区别是测试脚本和性能探针，旧证据保留原指纹。

原生瞬时Ctrl+S自动注入未触发，Space正常；鼠标Save/Save As闭环已验，不能据此宣布物理键盘快捷键已通过或确定存在应用缺陷。原生检查wrapper曾因20分钟无命令主动结束，失败记录保留；不把局部GUI操作包装为完整GUI套件通过。归档校验脚本一次成功状态名称写错也已记录并更正，详见[完整迭代记录](RESULTS.md)与[DEVLOG](../../DEVLOG.md)。

尚不包含插件运行期沙箱、32位桥接、侧链/任意插件多输出、comping、TempoMap、warp、自动化Touch/Latch/Write、MP3导出、真实分离/转录或模型Agent。全部插件兼容、实体MIDI演奏、人工听感以及可见GUI长时交互仍需对应验证；不影响按已实现入口继续进行基础编曲和后续迭代。
