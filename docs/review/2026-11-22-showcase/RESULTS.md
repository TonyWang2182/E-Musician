# 独立拍摄版与录音波形：验收记录

日期：2026-11-22（Asia/Shanghai；Recorder 文件名使用 UTC）。工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`，分支 `feature/showcase-recording-v1`，基线 `0c41caaee976aa5cf4018e6c83697c7cf282ae4b`。

**结论：独立录音增强版和离线拍摄版已构建；六场景真实工程联测 25 项及真实 GUI 流程已完成。现有结果的回放、真实工程操作和模型新推理是不同证据，本轮没有进行新推理。录音实时波形已通过确定性 PCM 生产管线测试，实体麦克风 take、实际听感仍待用户验收。** 240 秒影片、最终镜头清单与剩余真人素材见 [DELIVERY.md](DELIVERY.md)。

## 产物和保留边界

| 产物 | 路径 | SHA-256 |
|---|---|---|
| 原 0.13.6，未覆盖 | `E:/emusician-analysis-build/bin-0.13.6/Release/E-musician.exe` | `81020b783de6540746de5a81215ea8a62cc133f4d8202a30d40add3b98940699` |
| 录音波形增强版 | `E:/emusician-analysis-build/bin-0.13.6-recording/Release/E-musician.exe` | `2eb6bd99dd37f8aed032c83ae07cdf82b9ebcb78a59f698df202d1ba7038adf1` |
| 离线拍摄版 | `E:/emusician-analysis-build/bin-showcase-v1/Release/E-musician.exe` | `a6ba0e3b1e15937f50d004e0d4f9448256323d4c0b061d7e9c3b7ee486c1eeee` |

拍摄包在 `E:/MusicAgent&DAW/demo-video/showcase-v1`。窗口标题为 `E-musician - Audio Workspace`。三个初始工程为 New ideas（90 BPM，空工程）、New Light（120 BPM，1 音频轨）和 Tea for Two（120 BPM，1 音频轨）。manifest、模板及实际工程 ID/BPM 均核对一致，联测前后初始工程与资产哈希不变；测试的 10 个阶段工程另存于 `captures/projects`。

`workspace/manifest.json` SHA-256：`4d23b724ef164707ff0f2fa03b277c857930eadb8a968764bc78c45ac51049b7`。原用户 `test drive.emproj` 与引用素材仅复制后使用；保护依据和实际音频导出见 [AUDIO.md](AUDIO.md)。

## 构建与自动检查

本轮使用 Windows 11、C++20、MSVC Release；Python 3.14。每次实际构建/命令都有 `docs/builds/<Recorder>.json` 和 `build-logs/<Recorder>.log`。下面保留失败及后续修订，不把不同配置的结果合并成一次全绿测试。

| 检查 | 实际结果 | Recorder / 证据 |
|---|---|---|
| 录音版配置、首次 Release 构建 | 成功，`EMUSICIAN_SHOWCASE=OFF` | `12156ed850` / `5b573405bd` |
| 首次录音版完整 CTest | **10/11**；新增录音波形绘图断言失败 | `edb5d9b574`，完整日志 `20261121T163740.245968Z-edb5d9b574.log` |
| 录音绘制修订后增量构建 | 成功 | `96b93ebf88` |
| 录音版 engine.integration_smoke 复测 | **1/1**，87.31 秒；产物生产检查 1180 项通过 | `e95679d452`；`build/smoke/Release/012e283e7907/production-smoke.json` |
| 既有 Agent 单测 | **390/390** | `a9c8e3dee8`，`test_music_agent*.py` |
| 新离线回放单测 | **20/20** | 最终 `b57aa4a51f`，`test_showcase_replay.py` |
| 拍摄版配置、首次 Release 构建 | 成功，`EMUSICIAN_SHOWCASE=ON` | `0695814c22` / `58b46b830f` |
| 拍摄版完整 CTest | **9/11**，两项普通模式假设与隔离模式冲突，仍记失败 | `9cf1432c97`，见下文 |
| 拍摄版选择上下文修订后增量构建 | 成功 | `cf0a17321e` |
| 六场景真实原生联测 | **25 项通过**，约 97.6 秒含固定等待 | `e144f68a98`；`tests/3e61ba0012654773831d7b8d2089c0ce/report.json`（交付目录） |
| 既有中英 Agent 网页流程 | **22 项通过** | `3cfe9c1fda`，实际浏览器测试；见 [GUI.md](GUI.md) |
| 构建目录/模式守卫 | **4 项通过** | `c798fac5d3`，不匹配时拒绝开始构建，普通配置显式 OFF |
| 交付只读核查 | 通过；原版、原工程、三起点、manifest 与联测 EXE 一致 | `1764eefd12`，交付包 `tests/DELIVERY-AUDIT.json` |

拍摄版 CTest 两项失败的原始错误为：`engine.integration_smoke` 的“relative audio-cache root is rejected without fallback”，以及 `workspace.brand_colour` 的“temporary locale zh-CN”。拍摄版设计为固定独立缓存、不读取生产环境缓存覆盖、锁定英文；上述测试针对普通模式。没有改产品绕过隔离，也没有把失败报告改成通过。录音版相应普通功能已有上一轮检查证据。拍摄版专用六场景与普通引擎回归不可互相替代。

最终拍摄版增量构建的 Recorder 标记 `source_changed_during_command=true`，差异仅为非 C++ 的 `scripts/showcase_firstcut.py`；录音版最终增量差异仅为 capture/audio Python。首轮构建与脚本开发曾交错，所有差异保留在源指纹中；最终候选以表内 EXE 哈希、各测试报告为准，不声称工作树全程未变。

## 六场景具体通过了什么

实际 `AgentRuntime`、`DawBridge` 和 native 子进程完成：YuE2/ACE 两个生成候选分别应用；删除未选 take 后 SCNet 四轨导入；ChordMini 候选经 Analysis 对应命令手动接受；Beat This 候选实际执行保音高 Warp；TransKun 结果导入可编辑 MIDI。源文件、结果及范围均校验；本地有限英文指令匹配不代表通用自然语言理解能力。

应用后单次 Undo、原生 Redo、拒绝重复 Apply、完整轨道/clip/notes/和弦状态回读、保存重开均通过。错用 YuE2 源执行 ACE 分离场景时，范围预检在创建任务前拒绝，无候选、无工程变更；worker 源哈希拒绝另由单测覆盖。Warp 后和弦标签不变，时间边界按真实同一变换映射。132 个音符的音高、力度、通道完全一致；秒→拍→秒最大误差 `1.7763568394002505e-15` 秒。

失败轮次也保留：首次联测暴露 headless 选择未发布统一 selection context，修复仅 showcase 编译的 helper 后重跑；第二轮到最后因测试独立舍入浮点边界失败，逐音核对后改为明确 1µs 误差比较，再全程通过。未改动音符数据来满足测试。[REPLAY.md](REPLAY.md) 有完整记录。

Headless output-probe 的两次 Preview 都返回 `unavailable`，只证明调用/停止及不改工程，不能作为试听通过。独立真实GUI已显示Previewing、两take分别实际应用；后续四轨、手动和弦、Warp及132音符转录也已完成，回执见[GUI.md](GUI.md)。人工听感仍需区分。

## 录音、媒体和来源

录音增强复用 Tracktion 后台写入的真实峰值，消息线程管理 take，编曲窗口按可见范围绘图。六种 callback/输入路径、单/双声道、静音/实际电平、增长、停止交接、预备拍取消、非零起点、Monitor Off、Undo/Redo 和过期 take 检查通过。输入为 hosted buffers，48 kHz/256 样本；不是实体麦克风。没有新增音频回调网络、解析、磁盘或 UI 工作。[RECORDING.md](RECORDING.md) 记录其范围。

三个可用音频均经保留的 0.13.6 真正导出：Demo4 当前九轨混音 60 秒、D3 Keyscape MIDI-only 16 秒、D2 Warp 25.25 秒，均 48 kHz/24-bit 双声道、无削波样本。D3 原音频静音且删掉整个 MIDI clip 的负对照全零；恢复的 132 音符真正驱动 Keyscape，未用原钢琴录音替代。最初快速离线 Keyscape 输出有开头静音，明确排除，最终使用按块等待的独立渲染。[AUDIO.md](AUDIO.md) 给出每次尝试、哈希和回执。

六段无字背景、片头/尾、抽象 sax 替换画面、英文 TTS 和字幕已生成；`VALIDATION.json` 记录解码/时长/字幕检查。该文件不是 DAW 全部功能或最终影片验收。真人 sax 素材与用户真实录音 take 仍待补入；抽象动画不作真人演奏或麦克风证据。实际原生截图、连续录屏和后期复合镜头按捕获清单分别保留来源。

## 限制与下一步

- 模型结果来自历史已保存产物；20/15/12/8/6/10 秒等待仅为拍摄节奏。无 SSH、外部模型 API、权重推理或在线速度/质量结论。
- Python replay 只允许 loopback，生产配置/密钥读取被隔离；不是操作系统级防火墙，不据此保证第三方插件不会自行联网。
- 待用户实体麦克风、声卡、长 take、听感及实际工程流畅度验收；无量化性能结论，也不宣称峰缓存完全无锁。
- GUI记录已完成；240秒首剪/无旁白版最终状态由交付清单补充。按最终镜头清单取素材，排除失败或错误提示截图，临时额外编辑已另存保留。
- 此包依赖本机编译进的 workspace、脚本/Python 路径与已安装 VST。不是可随意拷到任意电脑即运行的便携发行版。启动与发布状态见 [PUBLISH.md](PUBLISH.md)。

最终只读代码复核没有发现普通模式被切入回放或新在线 Provider 回退：CMake 默认 OFF、native 路由与选择辅助命令受编译开关限制、run_agent 在读取生产配置前进入显式 ReplayProvider。此检查不增加新的编译或实机证据。
