# 0.9.1 分析工作区、语言与分析质量迭代

状态：已实现、自动验证通过、人工待验。开始：2026-11-05（Asia/Shanghai）。基线 `f0d95b3`，工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`，分支 `feature/analysis-workspace-v091`。保留 0.9.0 发布归档和旧 0.8.1 程序；开始前已有两条启动记录及 DEVLOG 追加保留。实际结果与未验内容见 [RESULTS](RESULTS.md)。

## 用户目标与交付顺序

1. 分析以音乐结果为中心：独立和弦轨道与共用时间轴，分离与转 MIDI 导入普通音频/MIDI 轨；下栏用图形结果和必要操作，技术诊断留日志，不展示大量分数或模型说明。
2. 轨道名称增加可发现的改名入口，双击名称、F2/右键复用现有 rename_track 命令；保存与 Undo 保持一致。
3. Settings 中切换 English / 简体中文，持久保存应用语言；用户轨名、音乐数据和 Agent 输入不翻译，不重启音频引擎或模型任务。
4. 按现成开源方案升级分析：可选真实六轨分离和质量档；有音高转录增加明确乐器范围；扩展和弦识别基线。手动/Agent 共用同一契约。新模型就绪、算法运行与识别质量分别记录，不将确定性和弦模板称作训练模型。
5. 运行相关原生/Worker/Agent 自动检查，查看实际组件渲染；提供人工短测。真实鼠标、ASIO 与听感由用户验证，不使用 computer-use。

## 文件归属

- root：AnalysisPanel、MainComponent、EngineSessionAnalysis、ProjectStorageAnalysis、Agent 分析契约、CMake、总体文档、集成构建和交付。
- analysis_arrangement：ArrangementView、EngineSession.h / EngineSessionPublic.inc 的只读和弦快照及缓存、轨道改名触发。
- analysis_models_upgrade：audio_analysis worker、setup_analysis、对应测试与 WORKER-NOTES。
- analysis_i18n：UiLanguage、AgentSidebar/网页与其语言支持、其他原生组件本地化、I18N-NOTES。

## 设计与边界

维持白底黑线、紧凑控件、矩形片段与同一时间轴。和弦轨是工程 EM_CHORDS 的只读投影，不新建会发声的假音轨。多个分析来源可切换，避免和弦互相覆盖。接受分析结果仍是明确的一次操作及一次 Undo，候选不会悄悄写工程；接受后轨道可见。空结果和失败各保留简短、可行动的提示。

推理、波形读取与文件校验留在后台。paint 不读盘或推理；本地化不触及音频状态。六轨采用单独登记的固定模型及 SHA，原四轨路径保留。品质档增加计算量必须可选择。扩大标签词表不等于复杂爵士识别准确，许可与测量范围写入开发档案。

## 验收

- 和弦轨对齐、缩放/滚动、选择与编辑跳转、关闭 dock 后可见；来源切换、Undo/Redo、保存重开。
- 双击/F2/右键与显式改名入口一致；中文/长名称不丢失，取消不修改工程。
- 两种语言及持久化、原生与 Agent 侧栏切换、用户文本不变；小尺寸布局截图。
- 真实六轨工作进程输出名称/长度/有限值/哈希；转录 profile 与扩展标签合同、错误/取消/旧数据兼容；未实测内容明确列出。
- 原生 Release + CTest，相关 Worker/Agent 单测与真实进程整链。每次尝试均经 Recorder 留原始日志和 docs/builds 记录，最终验证冻结源码。

后续高质量 learned chord、多乐器模型、五线谱与复杂爵士专项训练不在本次小型界面改版中冒充完成；需要另行实测集成。当前首先完成可见、可编辑、手动/Agent 一致的工作流程。
