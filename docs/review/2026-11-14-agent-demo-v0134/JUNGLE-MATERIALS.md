# Jungle 演示素材交付与来源核查

日期：2026-11-14。归属：jungle_asset_pack。范围：准备用户后续 Demo 的素材；未编排完整歌曲，未改动 DAW 工程或引擎，未调用生成模型/API。

**状态：素材下载、格式检查、来源记录与打包已验证；人工听感、DAW 鼠标导入与实际发声待用户/主流程验收。**

## 交付位置

统一目录：`E:/MusicAgent&DAW/demo-video/2026-11-14/jungle-materials/`。

| 产物 | 状态与用途 |
| --- | --- |
| `jungle-materials-cc0.zip` | 可供本地 Demo 使用的便携素材包；5,987,499 bytes（约 5.71 MiB）；36 个条目；ZIP CRC 通过 |
| `portable-cc0/README.md` | 中英素材说明、导入顺序、Sampler 根音与原 MIDI 空白修正说明 |
| `portable-cc0/PAD-MAP.csv` | 鼓垫分配表；首要 36 kick、38 snare、42 closed hat、46 open hat |
| `portable-cc0/SOURCE-MANIFEST.json` | 31 个源/派生资产条目，含来源、许可、精确 commit、源校验值、变换方式、SHA256 |
| `portable-cc0/VALIDATION.json` | 所有 WAV/MIDI 的实际数据检查结果；明确未验证听感和 DAW UI |
| `personal-reference/Antidote Audio - Jungle in Ableton Project.zip` | 真实网上 Jungle 工程原始 ZIP，152,567,753 bytes（约 145.50 MiB），个人学习参考，未混入 CC0 包 |
| `START-HERE.md` | 两类交付的区别和许可入口 |
| `sources/` | 固定来源版本的原始 FLAC/文档；便于复核 |
| `evidence/` | 下载、源索引、原项目结构、ZIP 校验记录 |

ZIP SHA256：

```text
jungle-materials-cc0.zip
e621c73a5854e513ca2a095ba1ab674528df2169c72754e6efef04697a4bc7e4

Antidote Audio - Jungle in Ableton Project.zip
b3238f5b27729c9afaff38135499fc6b1be72b69ee5576bcd580b3da46d75315
```

所有媒体放在 E 盘交付目录，不加入 Git。仓库仅保留准备脚本、这份来源说明和标准执行记录。

## 便携包内容

**17 个 WAV + 7 个 MIDI**，均为实际文件，不是占位链接。

| 内容 | 数量 | 来源/说明 |
| --- | --- | --- |
| Drum Rack 鼓单击 | 8 WAV | kick、snare、closed/open hat、rim、clap、crash、cowbell；LMMS 新 CC0 样本库 |
| Sampler / FX | 4 WAV | FreePats synth bass C2（根音 36）、choir pad C4（根音 60）；LMMS flute A4（根音 69）、vinyl rewind |
| 人声 | 4 WAV | Producer Space 的 Let's Go / Break It Down / Yeah / Listen Up，真实下载的短句；不冒充用户录音 |
| 短 break | 1 WAV | **本地编写/渲染**的 170 BPM、4 小节 drum building block；仅使用包内 CC0 鼓，非经典 Amen 录音 |
| 下载原始 MIDI | 3 MID | Producer Space House Piano Riffs 012，bass/piano/strings，F minor，原 124 BPM |
| 可直接导入的派生 MIDI | 3 MID | 上述原件去除 352 拍前置空白，170 BPM，8 小节；保留全部音符相对时序/音高/力度/通道/长度 |
| 鼓测试 MIDI | 1 MID | **本地编写**的 4 小节 63 音符，36/38/42/46 映射；不是下载的现成乐曲 |

文件前缀 `DOWNLOADED_` / `ADAPTED_` / `LOCAL_` 和 manifest 的 `origin` 明确区分网上下载、派生处理和本地编写，避免将自制测试素材描述为现成开源工程。

来源原 MIDI 数据实际从零基拍位置 **352** 开始，若直接导入常被误认为无声。派生副本在第一拍发声、结束位置严格为 32 拍；3 个副本分别保留 32、72、3 个音符。预处理不生成新的旋律，未做整曲编排。源 program/controller 事件不复制，说明已写入清单。

## 来源与许可

1. [LMMS 新资产库](https://github.com/LMMS/assets) 明确采用 CC0，并只接收 CC0 内容。固定 commit `bc09e0745c69c73bd6c3112122031e4963ce3876`；下载实际 Git blob 并校验其 SHA1，再由 libsndfile 解码 FLAC 为 PCM-24 WAV，不改采样率、响度或时长。未采用许可不明的旧 LMMS 样本库。
2. [FreePats Synth Bass & Lead](https://freepats.zenvoid.org/Synthesizer/synth-lead.html) 版本 2020-05-22，来源 commit `426f32da700c42a4071b5061ee3bb2fc92de0680`；[Synth Pad Choir](https://freepats.zenvoid.org/Synthesizer/synth-pad.html) 版本 2020-05-16，来源 commit `b801f7fc3eee44f575cd480750aea4f6a16a07a9`。两者均为 CC0，作者 Elf of Happy and Love、FreePats 编辑；只取一个根音样本。原 SFZ 的 root/loop 参数随包记录，不宣称原生 Sampler 已支持 SFZ 导入。
3. [Producer Space 官方许可](https://producerspace.com/license) 将整个样本与 MIDI 库置于 CC0；文件来自其官网链接的 [Internet Archive 原库](https://archive.org/details/producer-space-cc0-sample-library)。下载内容与 Archive MD5 一致，同时保存 SHA256。只下载选中的 7 个小文件，未下载完整 1.6 GB 库。
4. [Antidote 2023 Jungle in Ableton 官方项目](https://www.antidoteaudio.com/jungle-inside-of-ableton) 为真实公开参考工程，原 ZIP 已下载且 CRC 通过；有 74 个条目，展开总量 164,524,851 bytes。静态解析 `.als` 确认包含 19 个轨道/返回轨名称、MIDI/音频轨、MultiSampler、Simpler、插件，以及 bass、break、vocal、pad、FX 等素材。**未发现 DrumGroupDevice，不能声称这个原项目已经用了 Drum Rack**；原生 Drum Rack 演示由独立 CC0 one-shot 套件满足。

Antidote 原工程需 Ableton 10/11 Suite，官方列出可选 Trash 2、Little Alter Boy；E-musician 0.13.x **不能直接打开 `.als`**。作者允许学习、改编和使用工程样本，但不能把整首原曲冒称自己的作品发布；[通用许可](https://www.antidoteaudio.com/licensing-and-terms) 另限制单独重新分发素材。原项目独立保留作个人参考，不收入 CC0 ZIP，不随开源仓库公开分发。官网正文经网页检索核查；本机存档 HTML 请求因 TLS 失败，没有伪称已保存完整页面。

## 验证与执行记录

脚本：`scripts/demo_jungle_prepare.py`（有界下载/源索引/原 ZIP）与 `scripts/demo_jungle_assets.py`（CC0 文件下载、处理、数据核验、ZIP）。

- WAV：全部完整解码，检查 finite / nonzero、帧数、声道、采样率、peak 与 RMS；输出均可被 libsndfile 读取。Sampler bass/pad 源接近 0 dBFS，后续加载后先把轨道/装置输出留出余量再试听。
- MIDI：独立 Standard MIDI parser 检查头、track 长度、事件边界、note on/off 配对、正时值；鼓文件 63 音符；派生 3 个 MIDI 与源音符逐条比较通过。建议先使用 `ADAPTED_`。
- Hash：Git blob SHA1 / Archive MD5 与源相符；每个交付资产 SHA256；两份 ZIP 都做完整 CRC 检查。
- 验证的是文件与容器，不等于实际 UI 加载、键盘演奏、录音或最终听感验收。

标准记录均有完整开始/结束时间、命令、退出码及原始日志路径：

| 记录 | 结果 |
| --- | --- |
| `docs/builds/20261114T112541.721304Z-6899202a3f.json` | 首次源索引已下载 LMMS / Archive / CC0 许可，随后官网 HTML 请求失败；失败记录保留 |
| `docs/builds/20261114T112805.665546Z-198ddd7538.json` | 原 ZIP 首次下载失败，TLS EOF；保留失败日志 |
| `docs/builds/20261114T113149.158685Z-dadc3c1fbc.json` | 重试官方下载主机成功；原 ZIP 下载与 CRC 通过 |
| `docs/builds/20261114T113410.482005Z-a3ab1c6309.json` | CC0 文件首次下载与本地短鼓素材处理通过 |
| `docs/builds/20261114T113452.358084Z-ca78ce60eb.json` | 补存官网 HTML 失败，TLS EOF；不影响已校验媒体；网页许可核查独立保留来源 |
| `docs/builds/20261114T113717.449427Z-17dd8a3904.json` | 发现源 MIDI 前置 352 拍后，重新处理与逐音符等价检查通过 |
| `docs/builds/20261114T113841.266234Z-bdc3babd64.json` | 最终全量媒体校验、manifest hash 与便携 ZIP CRC 通过 |
| `docs/builds/20261114T114024.668341Z-0d1167f36e.json` | 两个准备脚本 Python 语法检查通过 |
| `docs/builds/20261114T114122.407808Z-7e881c3f49.json` | CC0 源索引独立重跑通过；固定 3 个 GitHub 来源版本，官网 HTML 存档拆为可选 reference-pages |

最终命令：

```powershell
C:/Python314/python.exe -X utf8 scripts/dev_agent_demo.py command 'E:/MusicAgent&DAW/analysis/runtimes/chords-py310/Scripts/python.exe' scripts/demo_jungle_assets.py validate
```

## 下一步人工核验

1. 用临时工程，170 BPM、4/4；为 Drum Rack 放入 36/38/42/46 四个鼓样，逐垫试听，再播放 `LOCAL_Jungle_Drums_170BPM_4bars.mid`。
2. 单独 MIDI 轨加载 Sampler bass 根音 36，导入 `ADAPTED_HPR_Bass_012_Fminor_170BPM.mid`；确认第一拍发声、8 小节后结束。
3. 另一 Sampler 轨加载 choir pad 根音 60，再放一个人声 WAV 到音频轨，核查可读波形与播放。不要把该样本人声镜头替代演示脚本要求的真实麦克风录制。
4. 保存、关闭重开，检查音符、采样路径和声音。再决定最终段落与配色/混音指令。此次不提前把素材自动编成成品。

详细文件路径与最少操作见交付包 `README.md`。

## 追加核查：真实 0.13.4 宿主导入、装置加载和保存重开

2026-11-14 11:53 UTC 完成补验。**此前“文件格式已验，DAW 导入待验”的状态已推进为：真实离线宿主的导入/装置加载/保存重开已验证；GUI 鼠标操作、物理播放与听感仍未验证。** 无 LLM、GPU、模型调用、声卡打开、播放或音频渲染。

发现并修正了素材映射问题：原生 Rack 当前固定 16 垫，对应 MIDI **36–51**（`NativeInstrument.cpp`）；此前可选 Cowbell 使用通用 GM 56，超出该 Rack 范围。已将文件名和 `PAD-MAP.csv` 改为 **51_Cowbell.wav / MIDI 51 / pad 15**。36/38/42/46 核心映射保持，音频字节未改；WAV/MIDI 文件数仍为 **17 / 7**。以后不能把通用 GM 全套键位直接当作此固定 16 垫 Rack 的支持范围。

因此便携 ZIP 更新如下；上文旧 ZIP 数据仅保留作追溯，**当前应使用新版**：

| 项目 | 更新前 | 更新后 |
| --- | --- | --- |
| ZIP bytes | 5,987,499 | **5,987,589** |
| ZIP SHA256 | `e621c73a5854e513ca2a095ba1ab674528df2169c72754e6efef04697a4bc7e4` | **`224b81c3e34d5ce6345f9fdef7460ac71e9b6106096900cf06f4db040cf24fbc`** |
| 容器条目 / 媒体数量 | 36 / 17 WAV + 7 MIDI | 保持相同 |

新增 `tests/DemoJungleImportCheck.py`，复制实际 0.13.4 EXE 启动独占离线控制进程，使用交付包的真实文件完成：

- 全部 **7 个 MIDI** 导入，共 **277 音符**；核查音符数、音高集合、正时值与首音位置。原 3 个源文件的 352 拍偏移保持；派生副本从 0 拍开始。空工程先导入 170 BPM 鼓 MIDI，其余显式 `notes_only` 以保留工程速度；不声称已导入源控制器或复杂速度图。
- 全部 **17 个 WAV** 导入，逐项核对音频片段时长；总计 **24 轨**。
- 原生 **Drum Rack** 实际加载 8 个 one-shot 到合法垫位，逐个读回 MIDI note 和样本 SHA256。
- 原生 **Sampler** 实际加载 bass / choir pad，读回根音 **36 / 60** 和样本 SHA256。
- 实际保存 `.emproj` 与配套 assets，再重开：24 轨、277 音符、全部 Rack/Sampler 参数及样本身份相同，17 个音频哈希都出现在归档 assets 中，重开为 clean 状态。
- 全部交付源文件哈希保持；受保护的用户偏好/配置/工程文件无变化。

实际检查耗时 **9.407 秒**，不作为 GUI 操作延迟或播放性能结论。检查工程将素材集中载入用来核对数据，并非完成编曲；不拿它当演示成曲。

证据：

```text
docs/builds/20261114T115207.695105Z-c0a7854fee.json    # pad 51 映射重制
docs/builds/20261114T115327.474575Z-fe357cec36.json    # 新 ZIP / 数据校验通过
docs/builds/20261114T115330.061025Z-4d74c13678.json    # 真实 0.13.4 宿主检查通过
build/demo-jungle-import/69ae8db914844e2c9e17b5cad0c8f10a/report.json
build/demo-jungle-import/69ae8db914844e2c9e17b5cad0c8f10a/CC0-import-verification.emproj
```

检查命令：

```powershell
C:/Python314/python.exe -X utf8 scripts/dev_agent_demo.py command C:/Python314/python.exe tests/DemoJungleImportCheck.py --exe E:/emusician-analysis-build/bin-0.13.4/Release/E-musician.exe
```
