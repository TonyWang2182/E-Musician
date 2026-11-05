# 0.10.0 交付结果

2026-11-05。状态：**已实现，自动验证通过，真实设备/鼠标/听感待人工**。基线 be47b65771e32359c3c225092709330820952b0d，分支 feature/tempo-warp-workspace-v0100；未合并 main。完整精确记录见 [VERIFICATION.json](VERIFICATION.json)，每次失败、安装、配置、构建与测试的原始日志均保留在 build-logs，摘要在 docs/builds，DEVLOG 只追加。

## 可以使用的内容

- 跟随播放头开关、手动浏览暂停、偏好记忆，以及标尺右键恢复跟随。
- 真实本地 Beat This! 拍点/首拍/BPM/有限拍号候选，半倍/双倍与手动首拍修正；Align audio 保持工程速度，Use this tempo 采用素材速度与明确拍号。
- Source 固定比例保音高 Warp，原件保留、后台渲染、跟随工程 BPM、正确的裁剪/切分/源偏移、一次 Undo/Redo 和 schema 6 保存重开。
- Agent 读取、提出方案、范围检查、确认、等待后台完成、数值回读与撤销；侧栏九类能力由宿主实际就绪状态生成。
- 重做 Save/Save As、Settings 分类与中英文；轨道头、片段、空白、标尺右键使用已有命令。右键不移动播放头、不误触录音准备，也保留已有多选。

默认对齐到能保留首拍前音频的下一小节；不会暗中删除前奏。固定比例不会矫正歌曲中每一拍的自由速度变化。原件与渲染资产一起保存；新 schema 6 工程不要用旧版覆盖。

## 最终自动证据

最终 Release EXE：`474fc0824600c4aeb99ff4b617b890220d9b9a20e9dafde0f9ed6abe0bbfb5d6`。207 个源码输入：`47f058946b48a3020181aecee86b1e4ea7193247b5505751a67c147ed71df08e`。最终原生构建、CTest、三组整链期间源码完全冻结，逐文件相同。较早 Agent/Worker/网页测试的相关输入逐文件与最终版本一致。

| 检查 | 实际结果 | 记录 ID 后缀 |
|---|---|---|
| Release 构建 | 成功，独立 bin-0.10.0 | 17681fb951 |
| CTest | 10/10，通过原生和 UI 集成 | a0dca19eac |
| Warp 原生断言 | 188，通过含真实隔离 WAV 导出与两种 MP3 | 同上 |
| Worker 合同/数值 | 34/34，无跳过 | e875178300 |
| Agent Python | 291/291 | 6a0ef91df1 |
| 网页夹具 | 5/5 | 40bd183c86 |
| 原有真实模型原生整链 | 9/9，和弦/转录/六轨分离 | 086c4cd1a9 |
| Agent 原有真实模型整链 | 12/12，语言 Provider 为测试夹具 | 31d7ed47a9 |
| 新节拍/Warp 整链 | 9/9，两次真实 Beat This，语言 Provider 为测试夹具 | 2876c627cc |
| 最终证据/旧版哈希核对 | 通过 | ef5416c2c0 |

原生测试使用 44.1 kHz 双声道 440/660 Hz 合成信号，在 0.8/1.25/2 倍速度下检查精确输出帧数与音高；观测频率为约 440.008–440.020 / 660.012–660.030 Hz。12 个宽带瞬态能量重心检查的最大位置误差约 0.430 ms；这是该夹具的测量，不是所有音乐的瞬态保真承诺。裁剪 WAV、48 kHz 双声道 CBR MP3、44.1 kHz 单声道 VBR MP3 的实际导出与对应 Warp PCM 比较，拟合既有混音增益后的相对 RMS 残差均低于 0.000003。完整数字在 [WARP-REPORT.JSON](WARP-REPORT.JSON)。

测量环境：本机 Windows 11 10.0.26200、i7-13700H、约 29.7 GiB 可见物理内存，MSVC Release，固定 JUCE 8.0.6 / Tracktion 3.2.0。上述为离线渲染，没有活动音频设备或真实 ASIO 缓冲。模型单进程/2 计算线程、CUDA 探针用 22.05 kHz 短素材，公开 8 秒音乐整进程约 10.90 秒、追踪阶段约 0.50 秒，RSS 约 1.08 GiB、CUDA allocated 约 157 MiB；方法与精确环境见 [Worker 记录](WORKER-AGENT-NOTES.md) / [BEAT-PROBE.json](BEAT-PROBE.json)。不据此宣称实时播放或长曲性能已通过。

界面为真实组件离屏渲染，中英文/紧凑窗口已查看。初次截图发现 Follow 提示重叠和中文说明过小，已修正并复核最终截图；设备标签、和弦/拍点夹具有明确标识，不当作硬件/识别证据。[UI 验证](UI-VERIFICATION.json)记录了来源与范围。

## 失败与修复保留

首次权重下载 shell 引号失败后修正；第一次系统 Python Worker 测试缺 NumPy 的跳过不计通过，最终独立环境 34 项完整通过。Agent 旧 HTTP 拒绝路径遇到 Windows 连接重置；改为只丢弃明确有界的拒绝正文，过程中 413 不当等待的失败也保留，最后定向/全量通过。

原生首轮 `0236ee2ec9` 因新 UI 字体构造和缺失头文件失败，修正后 `5de2d58db6` 构建、`d718d888d5` CTest 通过；视觉 QA 后再构建为最终版本。构建日志存在上游 pwsh 不可用的非致命提示，MSBuild 返回 0 且最终产物/运行检查通过，未安装或更改系统 shell。

首次新整链 `02c38c1328` 九项功能均通过，最后保护断言把正常新增 Warp 缓存误认为设置变更，整体仍记为失败。只修正该测试的新增缓存白名单；旧文件修改/删除、偏好变化和其他新增仍失败。最后整链保护通过、原素材不变；没有修改或回滚用户配置来掩盖失败。

## 运行、保留与下一步

先保存关闭旧窗口，再打开 `E:/MusicAgent&DAW/Start E-musician 0.10.0 Tempo.cmd`，标题应为 0.10.0。实际 EXE 位于 `E:/emusician-analysis-build/bin-0.10.0/Release/`；VS Code 入口为 `E:/MusicAgent&DAW/E-musician-Tempo.code-workspace`。旧 0.9.1 EXE 仍在 bin/Release，hash 与旧归档相同，没有关闭用户旧程序。0.8.1、0.9.0、0.9.1 归档内容均按各自 manifest 再核对通过。

已准备 `E:/MusicAgent&DAW/test-projects/tempo-warp-0.10.0/synthetic-120bpm-4-4.wav`，先按 [人工短测](MANUAL-CHECK.md) 验证新增功能。实际 ASIO 共存、Windows DPI/鼠标、长素材/极端比例听感和真实语言模型意图仍待人工；本轮无付费 LLM 请求、无 computer-use。未实现局部 Warp 点、完整变速 Tempo Map、任意拍号自动识别、完全无损承诺或自动改写独立的 MIDI 派生轨。
