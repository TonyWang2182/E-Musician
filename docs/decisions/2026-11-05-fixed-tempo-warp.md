# 0.10.0：固定速度分析与离线 Warp

2026-11-05。已实现、自动验证通过、人工待验；验收结果另见本轮 review，本决策不替代测试证据。

## 选择与边界

本轮使用 [Beat This!](https://github.com/CPJKU/beat_this) 的 final0 模型产生拍点/小节拍候选，再由宿主计算中位 BPM、半倍/双倍候选和有限的 3/4、4/4 判断。未知拍号不伪装成已识别；界面允许修正 BPM、拍号和首拍。节奏波动只作为候选信息，本轮不生成逐段 Tempo Map 或局部 Warp anchors。

采用 [Signalsmith Stretch](https://github.com/Signalsmith-Audio/signalsmith-stretch) 作固定比例、保持音高的离线处理。stretch 1.3.2 与 linear 0.6.6 的精确 commit、头文件及 MIT 许可证哈希由 cmake/signalsmith.json 固定，配置时核对。不把“保持音高”称为任意比例完全无损。音色、瞬态和极端比例质量需要听感评估。

参考 [Ableton 的 Tempo/Warp 流程](https://www.ableton.com/en/manual/audio-clips-tempo-and-warping/) 将两个意图区分为“音频对齐工程”和“工程采用音频速度”。前者保持工程 BPM，后者改变全局 BPM/拍号且需 Agent 工程范围。默认对齐到能够完整保留片段前奏的下一个小节，不暗中裁掉首拍前音频。用户仍可指定目标时间。

## 状态与线程

Tracktion Edit 继续拥有唯一工程状态。Worker 只读原件与已准备 PCM，发布不可变候选；采用候选后才修改工程。Warp 以原件哈希、速度比和渲染器版本为缓存键，每次由原始 PCM 渲染，不对上次结果重复加工。原件与结果都保存到工程资产包，schema 6 显式记录引用及 hash，旧软件拒绝未知 schema。

原源时间、播放缓存时间和工程时间经同一固定比例映射转换。存档中的 source offset 是原源秒；引擎播放 offset 是原源 offset / speed ratio。裁剪、切分、Source 波形、分析输入和导出遵守同一约定。已接受且关联到该片段的和弦区间按仿射映射迁移；独立导入的 MIDI/分离轨保持独立编辑语义。

耗时解码、哈希、渲染在文件线程，模型在独立进程；实时回调不调用它们。候选渲染完成后重查项目 ID、revision、文件与取消状态，再在控制线程一次提交。跟随工程速度的片段也先准备再提交，不先改 BPM 留下未完成音频。可以一次 Undo/Redo；失败、取消或过期不提交部分结果。

Agent 使用受限工具读取 Warp、提出 Warp/节拍应用方案、确认后等待原生异步作业并回读数值。模型不接触任意文件路径或进程，不做音频 DSP，也不以描述代替实际回读。界面偏好（跟随视图、语言）不写音乐工程、不占用 Undo。
