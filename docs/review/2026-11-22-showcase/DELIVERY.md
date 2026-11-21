# 录音波形、离线拍摄版与四分钟影片交付

日期：2026-11-22，Asia/Shanghai。源码分支 `feature/showcase-recording-v1`，本地目录 `E:/MusicAgent&DAW/worktrees/audio-analysis`。所有大媒体均在 `E:/MusicAgent&DAW/demo-video/showcase-v1`，不上传源码仓库。入口总览：[START-HERE.md](<E:/MusicAgent&DAW/demo-video/showcase-v1/START-HERE.md>)。

## 两个程序

| 用途 | 启动入口 | 实际程序 |
|---|---|---|
| 0.13.6 录音增强 | `E:/MusicAgent&DAW/Start E-musician Recording.cmd` | `E:/emusician-analysis-build/bin-0.13.6-recording/Release/E-musician.exe` |
| 三工程离线拍摄 | `E:/MusicAgent&DAW/Start E-musician Workspace.cmd` | `E:/emusician-analysis-build/bin-showcase-v1/Release/E-musician.exe` |

录音增强版显示实际输入产生的增长波形，停止后交接到可编辑 clip。原 0.13.6、工程文件关联及原创 `test drive.emproj` 均保持。录音增强版 SHA-256 为 `2eb6bd99dd37f8aed032c83ae07cdf82b9ebcb78a59f698df202d1ba7038adf1`；拍摄版为 `a6ba0e3b1e15937f50d004e0d4f9448256323d4c0b061d7e9c3b7ee486c1eeee`。

拍摄版固定英文，标题为 `E-musician - Audio Workspace`；File → Projects 仅有 New ideas、New Light、Tea for Two 三个起点。使用包内六条英文提示词，依次执行双模型候选、分离、和弦、Warp、钢琴 MIDI；实际 Preview / Apply / Undo / 保存走原生工程管线。无需 SSH 或模型 API。使用历史真实结果和有限提示词回放，不是本轮新推理；等待时长是拍摄节奏。其工作根、设置及缓存与正常 DAW 隔离，不能把此包视为通用模型能力或可随意搬机的安装包。

## 拍摄和剪辑资料

- [英文分镜、旁白、时间轴和操作](../../demo/2026-11-22-showcase-script-en.md)
- [中文对照稿](../../demo/2026-11-22-showcase-script-zh.md)
- [剪辑说明](../../demo/2026-11-22-showcase-editing.md)
- 提示词：`showcase-v1/scripts/agent-prompts.txt` 与 P1–P6.txt。
- 六段无字章节背景、原 Logo 片头/片尾、透明版本及可编辑生成脚本：`showcase-v1/motion`。
- 240 秒英文配音、逐条配音、英文/中文字幕：`showcase-v1/narration`。
- 原生录屏、真实截图、音频导出与素材来源分别保存在 `captures`、`audio`、`workspace/provenance.json`。

两版首剪均为 **240 秒、1920×1080、30 fps、7200 帧、48 kHz 双声道**，完整解码检查通过，试听段均非静音，无满幅削波样本。

| 版本 | 交付目录内路径 | SHA-256 |
|---|---|---|
| 英文旁白版 | `exports/E-musician-Showcase-240s-English.mp4` | `480c2723ac7ab061c54f8b4d69669a7993abb4befc0a6026a6ccfd8cd3353b0d` |
| 无旁白音乐版 | `exports/E-musician-Showcase-240s-Music-Only.mp4` | `62b22a9f0c49f17169d7aa0896f55bff560a39aecbd1586946774c3b2cf7aefc` |

技术证据：`exports/FINAL-TECHNICAL-QA.json`，镜头表：`scripts/shot-map-final-2026-11-22.json`，抽帧：`exports/qa/final-film-contact-sheet.png`。原生录屏和实际截图分别保留来源；剪辑只做裁切、运镜和按实测时间重定时，不伪造 UI 状态。New Light 两段按真实帧时间与宿主播放位置校准；这不是采样级同步或完整听感验收。Demo4 的 60 秒音频连续播放，镜头切换不重启声音。

**03:01–03:10 的 sax 分屏仍需用户替换**：当前使用可替换抽象画面和真实已有轨道，不充当本轮麦克风录入或真人演奏证据。其余资料已经整理，可直接自行重拍；完整听感、录屏音轨及物理录音按下方清单验收。

## 已有验证与未验范围

- 原有 Agent 390 项、新回放 20 项、真实原生六场景 25 项、中英网页流程 22 项、构建模式守卫 4 项通过。
- 录音版完整 CTest 首轮 10/11；修复新增波形断言后，相关 engine 测试 1/1 通过，生产检查 1180 项。输入为 48 kHz / 256 样本 hosted PCM，并非实体麦克风。
- 拍摄版普通 CTest 9/11，两项依赖普通缓存/可切中文的旧测试与隔离英文模式冲突，仍按失败记录；不将专用 25 项联测冒充完整 11/11。
- 真实 GUI 已观察到 Previewing、Apply、四轨导入、手动和弦轨、Warp 和 132 音符 MIDI。捕获中的失败、额外编辑保全与弃用片段见 [GUI.md](GUI.md)。
- 原版 EXE、原工程、三个起始工程、manifest 及联测 EXE 哈希经最终只读审计一致：`showcase-v1/tests/DELIVERY-AUDIT.json`，Recorder `1764eefd12`。
- 未声称实体声卡长录音、听感、麦克风来源、量化性能、整曲模型质量已验收；本轮没有调用新推理或付费 API。

## 用户最短验收

1. 关闭其他 DAW 进程，打开 Recording 入口与工程副本。关闭 Loop，Settings 选择声卡及有效输入，目标音轨选 In 1 / In 2 并开启 R。
2. 点击全局 Record，说话或演奏 10 秒：波形应持续增长，响声峰值更大；停止后保留真实 clip。Monitor 与是否录下是独立的，按监听方式选择。
3. 回放、Undo / Redo、保存重开；再录 3–5 分钟并缩放/滚动，检查掉音、波形交接与录屏软件的声音。记录实际采样率/缓冲区和负载。

完整清单：[MANUAL-CHECK.md](MANUAL-CHECK.md)。前三个拍摄起点已恢复，源素材和历史结果保留。展示期间只使用一个 DAW；需要重拍时先另存并关闭，再按 START-HERE 的显式重置命令恢复三工程。

## 代码与记录

两种构建输出独立；共享 CMake cache 的模式和目录已加守卫。每次构建、失败、修订和验证都有 `docs/builds` 收据及 `build-logs` 原始日志。DEVLOG 只追加，先前遗留修改与 36 个旧未跟踪收据保留，不归入本次提交。最终源码提交/推送以 [PUBLISH.md](PUBLISH.md) 及交付包 `RELEASE.json` 为准；不合并 main。
