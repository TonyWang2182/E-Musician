# 0.10.0 节拍、保音高拉伸与日常操作

2026-11-05，状态：已实现，自动验证通过，人工待验。基线 be47b65771e32359c3c225092709330820952b0d；工作树 E:/MusicAgent&DAW/worktrees/audio-analysis，分支 feature/tempo-warp-workspace-v0100。开始前已有两条 1105 启动记录及 DEVLOG 追加，保留。0.9.1 EXE/PDB/源码文档归档保持不动。最终范围与证据见 [RESULTS](RESULTS.md)。

## 本轮范围

1. 用户已明确第 1 项是视图跟随播放头滚动：显著开关、持久化偏好、设置和时间轴右键入口，手动浏览的行为可预期。
2. 真实节拍/首拍分析、BPM 与 3/4、4/4 拍号候选；可半倍/双倍、改拍号、修正首拍。音频跟随工程与工程采用素材速度是明确不同动作。结果用拍线、短数字和两项应用入口表示，不堆内部报告。
3. Source 中提供固定比例保音高拉伸，原音频保留，后台准备播放缓存、统一源时间/播放时间映射；保存、撤销、裁剪、切分、分析和导出不能各用不一致的位置。已经接受的关联分析信息必须按映射处理或明确失效，不静默错位。
4. Agent 查询/计划/预览/权限/确认/回读/撤销配套升级。全局速度变更必须工程范围；工具不可自行提供文件/进程路径。手动与 Agent 使用同一宿主命令。
5. 重做保存与设置界面，沿用黑白风格；清楚呈现名称、路径、保存进度/结果，保留异步文件事务，不新增自动保存恢复。设置组织为音频/MIDI、编辑习惯、语言。
6. 按轨道头、片段、编曲空白、标尺提供情境右键；复用已有命令、上下文、Undo，右键不跳播放头、不无故清空多选。只显示真实已实现且适用的操作。

首批针对固定速度素材；局部 Warp 标记编辑、完整变速/变拍号 Tempo Map、任意比例完全无损不宣称完成。预留版本化接口而不做空按钮。模型优先 Beat This!；DSP 优先评估 Signalsmith Stretch。两者正式锁定来源、commit/权重 SHA、许可证和环境后才部署。

## 协作归属

- root：EngineSessionAnalysis.inc、AnalysisPanel、CMake、集成合同/端到端、整体构建与开发档案。
- analysis_arrangement：AudioWarp/TimeMap 新组件，ProjectStorage、EngineSession 模型/命令/任务/公开快照与 Warp 工程事务；不编辑 Main/Arrangement/AnalysisPanel。
- analysis_models_upgrade：audio_analysis Worker/安装器、music_agent Python 与网页能力、对应测试/真实探针。
- analysis_i18n：MainComponent、ArrangementView、UiLanguage、设置/保存/Source UI、新 UI 离屏测试与人工清单。

## 验收

每次实际构建/测试通过 Recorder 记录命令、配置、时间、失败和原始日志。固定版本 Release；源码冻结后完成有关 CTest、Python 合同、真实 Worker 和真实宿主整链，查看英文/中文/最小窗口渲染。

重点检查：已知点击轨的节拍时间和半倍歧义、空/短/坏素材；保音高频率与精确长度、立体声、接缝和取消；原文件不变、连续改速不重复加工、跟随工程速度、裁剪/切分/保存重开/导出；Agent scope、过期、确认后回读、一次 Undo/Redo；右键多选与播放头、保存取消与失败、语言/设备状态不被无关交互改变。真实 ASIO、鼠标/DPI、复杂歌曲识别和音乐听感由用户人工确认，不以自动测试代替。
