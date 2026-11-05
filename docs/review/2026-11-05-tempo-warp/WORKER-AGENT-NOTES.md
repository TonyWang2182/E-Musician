# 0.10.0 Beat This Worker 与 Agent 管线

2026-11-05；工作树 `E:/MusicAgent&DAW/worktrees/audio-analysis`，分支 `feature/tempo-warp-workspace-v0100`。本文件记录本分工实现与证据，原生构建、真实宿主全链与人工验收由主任务单独汇总，不从 Python 通过推断它们通过。

## 实现边界

- 真实本地 `beats` Provider 使用官方预训练 Beat This!，独立 Python 进程、离线 checkpoint 路径、2 条计算线程。网络只用于显式安装，运行时不下载模型、不调用付费 LLM、不上传音频。重任务仍使用原生单任务/取消/不可变候选约束。
- `preset=beat_this`；参数 `meter=auto|3/4|4/4`。`beat_events` 为相对分析范围的 `time_seconds/is_downbeat`，最多 10000 项；`tempo` 返回 BPM、首拍、首强拍、3/4或4/4候选、半倍/双倍备选、节奏波动标志。拍号根据真实预测强拍间隔推断；证据不足时 numerator=0，不伪造概率。人工 meter 参数不会生成虚假强拍。
- 静音返回空拍点和 null BPM/首拍；少于0.25秒明确按“不足以建立节拍”返回空候选，不调用网络。公开音乐和已知节拍夹具真实执行了模型，另有独立安装 forward 探针。128点背景波形来自真实PCM绝对峰值，原音频未改；Agent上下文丢弃该数组。
- Agent 新增 `read_audio_warp`、`propose_audio_warp`、`propose_beat_application`。候选只引用 ID，方案检查范围、时间、源身份和 Warp 比率，明确预览后才单命令提交；后台任务完成后回读真实比例、起点、长度、开关和工程速度/拍号，再给出成功及一次Undo。
- `audio_to_project` 保持工程速度与拍号；`project_to_audio` 只能在明确 project 范围，采用音频速度/指定拍号但保留所选音频当前播放速度。未知拍号只阻止全局拍号采用，不阻止音频跟随已有工程；缺首强拍必须人工指定。首拍默认放到能容纳前奏的下一个小节，不把负起点悄悄截掉。半倍/双倍通过明确 `bpm` 修正，不伪造新分析结果。
- 既有 `set_tempo` DSL 接受原生异步 batch 回执，并按 oldBpm/newBpm 计算跟随音频起点、时长和淡变；后续裁剪使用更新后的 Warp 比率换算原源偏移。新增 postcondition 检查 Warp 字段；无需把跟随音频变速降为仅文字描述。
- 原生来源 `clip_source_offset` 是当前播放缓存偏移；Agent 在新候选包含 `warp_speed_ratio` 时与快照 `playback_source_offset` 比较，同时绑定比率。旧未Warp候选仍兼容，非零裁剪偏移不会被当作源文件错位。
- 侧栏增加“节拍/速度”和“音频Warp”，共九类能力。真实宿主与 Provider 决定可用状态；英文/中文短文案、BPM/拍号摘要、确认范围与数字变更均保留，不把技术报告搬进主操作流。

## 固定模型与部署

官方实现：[CPJKU/beat_this](https://github.com/CPJKU/beat_this)，代码 commit **`b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`**，package版本1.1.0。[官方 README](https://github.com/CPJKU/beat_this/blob/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c/README.md)说明代码和发布权重为MIT；训练录音本身的权利不随权重转移。推理使用官方 `Audio2Beats` 的 minimal 后处理，没有安装 madmom/DBN，也未自行训练。

- checkpoint：[官方 final0.ckpt](https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt)，81,058,141字节。
- SHA256：`8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`，首次官方下载后固定在源码中，之后安装和正常推理检查该hash。
- 模型目录：`E:/MusicAgent&DAW/analysis/models/beat-this/<commit>/`；独立运行库 `analysis/runtimes/beats-cuda-py310/`。
- Python3.10.19、PyTorch2.5.1+cu124、torchaudio2.5.1+cu124、NumPy1.26.4、einops0.8.0、rotary-embedding-torch0.6.4、soxr0.3.7；完整依赖在 `scripts/audio_analysis/requirements-beats.txt`，安装清单含所有包版本、源文件hash、许可证hash。
- 注册仅增加 `providers.beats`。与注册前的 `registry-history/1793879394421758600.json` 对比，transcribe/chords/separate/separate_6s 四项完全相同。原注册备份保留。
- 显式安装命令：`python scripts/setup_analysis.py --root "E:/MusicAgent&DAW/analysis" --kind beats --device cuda`。uv复用缓存中的torch wheel，只新增约3.9MiB torchaudio下载；没有改旧模型环境或全局Python。

## 实际检查与失败记录

所有执行均由 Recorder 留下 `docs/builds/<id>.json`、`build-logs/<id>.log`、开始/结束时间、命令与 DEVLOG 追加。

| 检查 | 结果 / 记录 |
|---|---|
| 首次下载 shell 引号错误 | 失败；`20261105T114725.032340Z-502cd55238`，未开始网络下载，改用stdin传脚本 |
| 官方权重下载及hash | 通过；`20261105T114738.958965Z-a1942e27d5` |
| 独立环境与固定torch/torchaudio | 通过；`20261105T114817.762814Z-6cff8a61c3`、`20261105T114822.982600Z-03f607d86d` |
| 固定代码/依赖安装、真实CUDA forward并注册 | 通过；`20261105T114838.829630Z-86ef5b620d`、`20261105T114855.153333Z-540235db40` |
| 初次Worker合同+数值 | 34项中25通过/9因系统Python缺NumPy跳过；`20261105T115532.451104Z-0903537b1a`，不是34全通过 |
| 隔离环境完整Worker合同+数值 | **34项全部通过**；`20261105T115907.496827Z-c6185301fc` |
| 最终真实Worker五类输入 | **5项通过**；`20261105T121023.579051Z-74933b593c`，`analysis/manifests/beat-probe-7459e19bc1b3.json` |
| 额外已知120BPM合成节奏真实模型检查 | 通过；`20261105T120856.374852Z-a77ede5b4b`，`beat-probe-a522677df996.json` |
| 初次完整Agent290项 | 1个旧HTTP拒绝测试Windows10053错误，其余通过；`20261105T120411.353536Z-16b3ab8568` |
| HTTP中间修复后291项 | 1个无正文超限长度测试超时；`20261105T120721.801123Z-fc038a1a15`，此中间版本读取了不应等待的413正文，已修正 |
| 最终HTTP定向回归及重复拒绝 | 通过；`20261105T120944.357489Z-853f2a79f8`。只对403/415且已声明不超过32768字节的正文有界丢弃，不解析、不授权、不dispatch；413立即拒绝 |
| Agent新增tempo合同/状态机 | **15项通过**；定向记录与最终全量回归见主任务证据 |
| 新整链脚本CLI导入 | 通过；`20261105T120950.921057Z-63b3d3d56d`，不等于原生整链已通过 |
| Agent九能力与Beat预览网页 | 五个合成状态夹具通过；`20261105T121131.417131Z-7a4e1436cc`，无真实模型调用；400px Beat预览图已看 |

最终Worker执行源码指纹：`d1678995f73d946e6c83d6038945e6965cc559a4516792c8a1648300bd4478c2`（六个Worker执行模块，不是整个仓库）。首轮真实音乐指纹早于短输入分支，保留旧记录；最终五类探针使用同一个上述版本。

## 性能与准确性边界

同一Windows本机，i7-13700H、约32GB RAM、RTX3050Laptop4GB、驱动555.99；离线Worker，22.05kHz单声道输入，两条计算线程，**无ASIO/声卡缓冲、无实时播放验收**。RSS每100ms采样，GPU值来自PyTorch分配器；并行开发工作仍存在。

最终公开8秒VibeAce整进程10.90秒，追踪阶段约0.50秒，主要开销在新进程导入PyTorch；峰值RSS1,164,214,272字节，CUDA allocated164,153,856 / reserved188,743,680字节，无CPU回退。检测11拍，65.217BPM及半倍/双倍备选；拍号未知、波动标志为true。该片段没有人工真值，不报告准确率。

16秒合成120BPM、4/4鼓/贝斯夹具产生32拍、120BPM、4/4；首强拍0.26秒，相对设定0.25秒误差约10ms，中位最近参考拍误差10ms。**只说明这一夹具**，不等于爵士、复杂节奏、6/8、自由速度或真实乐曲保证。静音/10ms短片段均没有伪造BPM；短输入明确未推理。CUDA OOM回退实现但未强制触发验证。

## 主任务接手的真实宿主检查

`python tests/MusicAgentTempoIntegration.py --exe <新Release.exe> --timeout 300`。默认只读取缓存公开8秒源，复制到独立build目录；冻结exe副本、不接触用户工程，并核对原素材及受保护配置hash。

覆盖两次真实BeatThis：音频→工程候选与Agent确认/回读、一次Undo/Redo、保存重开、关闭Warp/Undo、既有set_tempo异步跟随处理、非零偏移Warp裁剪、重新分析当前可听片段、人工90BPM/3/4首拍修正后工程采用音频速度。语言Provider明确为确定性fixture，不能当作真实LLM理解率。最终原生构建、整链结果、全量回归和人工鼠标/听感状态由主任务补入全局开发档案。

## 最终冻结与人工验证用语

2026-11-05 20:17 CST：Python Worker、Agent、网页及对应测试文件冻结，等待主任务使用新的 0.10.0 原生程序执行整链验证。最终完整 Agent **291/291 通过**：`20261105T121319.800459Z-6a0ef91df1`；最终网页 **5/5 通过**：`20261105T121405.452925Z-40bd183c86`。定向 tempo **15/15 通过**：`20261105T120947.009984Z-daa7e5b9c5`。最终 400px 节拍候选截图已查看，BPM、拍号、候选点和确认范围可见，无水平越界。

以下是人工验收指令，只有操作者实际完成后才能标为人工通过；本轮没有调用付费语言模型验证自然语言理解率。

1. 选择一段有清晰鼓点的音频片段，输入：`分析选中音频的节拍和速度，先展示结果，不要改工程。` 应先出现候选，音轨、BPM和素材位置不变。
2. 输入：`让这段音频跟随当前工程速度，保留音高，把第一个强拍对齐到小节线，先给我预览。` 预览须明确选中片段、速度比例、起点、时长和跟随开关；确认后试听首拍/节拍器，一次撤销恢复原始状态。
3. 若结果提示首强拍或拍号需要检查，明确给出：`源音频是120 BPM、4/4，分析区间内第一个强拍在0.25秒。` 这是人工修正，应保留该事实，不能声称模型已自动识别正确。
4. 将范围切到整个工程，再输入：`工程采用这段音频的速度和4/4拍号，保留这段素材现在的播放速度。` 未切换工程范围时应拒绝全局变速；预览须指出工程BPM/拍号变化。
5. 输入：`选中的片段关闭Warp，恢复原始速度，先预览。` 确认后长度变化与预览一致，可一次撤销；素材原文件不变。
6. 输入：`这段素材原始速度是90 BPM，让它跟随工程速度，保持音高。` 注意“原始速度”与已拉伸后听到的速度不同；Agent读取当前Warp比例，再进行换算，不应重复乘比例。
7. 给已经Warp的片段从前面裁掉一小段，再做节拍分析/应用；应基于现在能听到的片段，并保留前奏，不出现源偏移错误。整链脚本覆盖此路径，但真实鼠标操作/听感仍由人工确认。
8. 静音、极短片段、自由速度或6/8素材：允许无结果、未知拍号或人工修正，不应自动套出确定4/4及虚构高置信。

原生整链入口：`python tests/MusicAgentTempoIntegration.py --exe E:/emusician-analysis-build/bin-0.10.0/Release/E-musician.exe --timeout 300`。该脚本启动隔离副本，语言Provider为确定性测试夹具，模型分析真实执行。

### 原生整链保护断言修正（20:29 CST）

主任务的首次真实整链 `02c38c1328` 已通过9项功能流程，最后因旧 `protected()` 把正常新增的 Warp 缓存也当作设置更改而失败。仅修改 `tests/MusicAgentTempoIntegration.py` 的保护断言：原有哈希全部保留，既有文件改变/删除仍失败；仅允许新增于规范 `%APPDATA%/E-musician/cache/warp-v1/` 目录下、文件名恰为64位十六进制加 `.wav`/`.json` 的文件。另对两处受保护目录建立文件清单，其他扩展名/子目录的新增文件也失败。`ui-language.txt`、`follow-playhead.txt` 明确纳入哈希保护，原先不存在也记录空值，新增偏好仍失败。报告新增允许缓存及改变/删除/意外新增的脱敏相对路径；没有修改共享保护函数或产品代码。

隔离临时文件回归首次因模拟 protected() 复用字典导致快照共享而失败：`20261105T122909.316898Z-f9e1242a34`；快照显式复制原字典后，同组保护边界全部通过：`20261105T122921.727480Z-f853646556`。覆盖合法新缓存、两项缺失偏好新增、错误扩展名/目录/嵌套路径、既有缓存修改和删除、外部路径诊断。整链由主任务使用新保护断言重跑；之前失败记录保留。


## 最终原生整链结果

使用最终EXE474fc082…，2876c627cc的新节拍/Warp九组全部通过，保护集合/偏好/原素材均保持；31d7ed47a9的原有Agent分析12组与086c4cd1a9的原生真实模型9组通过。Worker34项在e875178300完整复核。验证期间源码冻结，语言Provider明确为模拟、Beat This和其他音乐模型为真实本地推理。归档报告见AGENT-TEMPO-E2E.json、AGENT-ANALYSIS-E2E.json、NATIVE-E2E.json；真实模型意图理解及听感仍待用户。
