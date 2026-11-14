# 四轨染色与基础混音：0.13.4 实际宿主核查

状态：**生产命令编译、实际原生宿主事务及保存重开已验证；真实 LLM 理解这两条提示词尚未验证。** 本检查没有调用 API、云端模型、音频设备或用户正在使用的 DAW；确定性 Provider 直接返回预先定义的工具参数，不能作为模型理解能力、自动听音混音或听感质量的证明。

## 演示输入与预期

范围选择 **Whole project**。工程内必须各有且仅有一条 `Drums`、`Bass`、`Pad`、`Vocal`；这四个名称与提示词和测试保持一致。它是“明确参数的基础混音及染色”演示，不是自动母带或根据声音自主调音。

| 轨道 | 目标颜色 | 音量 | 声像 |
| --- | --- | --- | --- |
| Drums | `#D8BEBC` | −6 dB | 保持，测试基线为居中 |
| Bass | `#BFD2CF` | −8 dB | 保持，测试基线为居中 |
| Pad | `#91A7C3` | −12 dB | −0.20，左偏 20% |
| Vocal | `#DCCCA1` | −4 dB | +0.10，右偏 10% |

可直接复制的完整提示词：[English](D4-MIX-en.txt) / [中文](D4-MIX-zh.txt)。它们与 `tests/DemoColourMixCheck.py` 内原文逐字一致；TXT 末尾仅加一个换行。

人工拍摄步骤：

1. 在实际拍摄工程的副本中准备上述四轨，保留原有片段和装置；先保存一份修改前版本。不要把此处的测试正弦音当人声或音乐素材使用。
2. 打开 Agent，设置 **Whole project**，粘贴英文提示词并发送。使用中文演示时改贴中文稿。真实模型还需要可用的语言 API，本离线检查没有替代该前提。
3. 先拍“结果就绪/审阅”画面：应只有四项颜色、四项音量、两项声像，共 **10 个编辑操作**。没有点击 **Apply** 前，轨道必须保持原样。若模型增加片段、改 BPM、换音色或改其他轨道，取消方案，不为拍摄直接接受。
4. 点击 **Apply**，拍四轨颜色与混音数值变化。播放对比由用户人工确认；颜色本身不影响声音。
5. 用一次 Agent 撤销恢复全部 10 项，再用 DAW 的 Redo 恢复；保存为新的工程，关闭后重开，核对颜色、音量、声像及原片段/音符/装置仍在。

在原四分钟分镜中，它适合放在 Demo 4 的装置与混音镜头之间，剪出“指令→审阅→Apply→四轨变化”的短镜头；不替代实际 MIDI 和人声录制过程。未做 GUI 鼠标或设备录音验证。

## 实测内容与证据

测试源码：[DemoColourMixCheck.py](../../../tests/DemoColourMixCheck.py)。通过标准是实际宿主回读与文件重开，不以编译、启动或假快照代替。

- 独立复制的 **0.13.4 Release** EXE，通过 `--control-stdio --control-output-probe` 启动专属无界面宿主；不连接声卡。
- 基线为四轨：Drums 挂 Drum Rack，Bass 与 Pad 挂 Sampler，三轨合计 **11 个真实 MIDI 音符**；Vocal 导入明确命名为 `SYNTHETIC-not-a-vocal-recording.wav` 的 440 Hz 测试音。采样器和鼓组使用另一份 261.625565 Hz 测试音，均由测试脚本生成，无第三方素材。
- 英文和中文各从同一保存基线重新打开，通过当前 `AgentRuntime → propose_plan → 生产编译器 → DawBridge → 原生命令 batch`。
- 审阅阶段 revision 和工程内容不变；每种语言只调用一次确定性 Provider。点击应用路径只提交一次 **10 命令原子批次**，revision 只增加 1。
- 颜色和 gain/pan 逐项回读；一次 Agent Undo 恢复基线，一次原生 Redo 恢复目标；真实异步保存、重开后内容再次一致。
- 每个阶段保留片段、全部 MIDI 音符、速度、主轨参数、输出路由和 sends，以及 Rack/Sampler 的装置身份、采样 SHA、包络与播放参数。测试路由为四轨输出 Main/master、空 sends；不声称覆盖复杂路由组合。
- 原合成 WAV 的 SHA 不变；被保护的用户工程和设置清单未改变。没有实际播放、听感、延迟或性能结论。

通过运行：2026-11-14 **19:42:36–19:42:53 CST**，16.723 秒；这是检查耗时，不是音频性能基准。

- [成功构建/测试收据](../../builds/20261114T114236.982777Z-1aaa7d0a82.json)，退出码 0。
- 原始日志：`build-logs/20261114T114236.982777Z-1aaa7d0a82.log`。
- 完整报告与各阶段快照：`build/demo-colour-mix/167338d7a3dc4c67893ec2d458011eeb/report.json`。
- 基线工程：同目录 `SYNTHETIC-four-track-baseline.emproj`。
- 英文结果工程：同目录 `SYNTHETIC-four-track-en-US-mixed.emproj`。
- 中文结果工程：同目录 `SYNTHETIC-four-track-zh-CN-mixed.emproj`。
- 测试目录中的 `.emproj` 配套 assets 目录应一起保留。
- EXE SHA-256：`c99d9b0894687f1066bc09febe9c4d6ee5afbc4e38413fac5d6620a101245d5a`。

首轮记录也保留：[失败收据](../../builds/20261114T114149.979807Z-e3b5d8fdb5.json)，19:41:49–19:42:07 CST。原因是新测试把 runtime 附加只读快照的整个 user message 错当成原始提示词，确定性 Provider 的断言失败，尚未发出任何 Agent 应用批次。仅修正测试拆分“原文/只读上下文”的断言后重跑成功，未修改产品源码。

复跑命令（仓库根目录）：

```powershell
python scripts/dev_agent_demo.py command python tests/DemoColourMixCheck.py --exe E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe --version 0.13.4 --timeout 90
```

如人工运行提示 quota/429，先恢复语言 API 的余额或模型可用性；离线事务检查通过不会解决 API 配额。若审阅成功但应用提示工程已变化，重新读取当前工程并重新提出方案，不复用旧方案。若只有颜色变了，应核对待应用清单是否确实包含四项音量和两项声像，不把颜色变化当混音完成。
