# 本地 Agent 控制接口 v1

## 0.10.0 节拍与 Warp 增量（自动验证通过，人工待验）

`start_analysis(kind="beats", preset="beat_this", parameters={"meter":"auto"|"3/4"|"4/4"})` 沿用片段内 start_seconds/duration_seconds（最多 600 秒）。候选 beat_events 采用分析区间相对秒，tempo 含 bpm、first_beat_seconds、first_downbeat_seconds、meter_numerator/denominator、meter_supported、tempo_candidates、variable_tempo；未知值为 null 或 numerator=0，不能当成已识别。波形峰值只给 UI，不放入语言模型上下文。

| 命令 | 语义 |
|---|---|
| get_audio_warp | clip_ids 查询真实音频映射，返回 enabled、source_bpm、target_bpm、follow_tempo、warp_speed_ratio、原源及播放偏移、位置/长度 |
| set_audio_warp | clip_ids、enabled；开启时 source_bpm 为原始录音速度、target_bpm 默认工程速度、follow_tempo；mode=preserve_pitch。可同时指定 first_beat_seconds（操作前当前片段相对秒）及 align_start_seconds（工程秒），返回后台 job_id |
| apply_beat_analysis | result_id、mode=audio_to_project/project_to_audio；可修正 bpm、first_beat_seconds（分析范围相对秒）、target_start_seconds（工程首拍目标）、follow_tempo。project_to_audio 采用全局 BPM 和明确 3/4、4/4 拍号，并保留所选音频当前速度 |

默认首拍取 first_downbeat_seconds，缺失必须明确指定。默认目标是能容纳片段前奏的下一小节；负起点拒绝。audio_to_project 的 BPM 修正指当前可听音频速度，宿主除以已有 Warp 比率换算为永久原源 BPM。project_to_audio 冻结所选音频的现有速度，并异步更新其他随工程变速的片段。两个动作不创建虚假音频轨或节拍轨。

新模型工具 read_audio_warp / propose_audio_warp / propose_beat_application 采用读取、范围检查、方案、确认、异步等待、回读、一次撤销。改变全局速度/拍号要求 project scope；Warp 需要包含整个片段的授权范围。现有 set_tempo 方案会等待跟随音频准备完成，不把 accepted 当作已完成。过期候选、文件改变和 revision 冲突拒绝提交。已接受的候选一次使用；撤销后通过 Redo 恢复。

Snapshot source_offset 保持**原始音频秒**；新增 playback_source_offset、warp_speed_ratio 等字段提供实际播放缓存映射。分析 source.clip_source_offset 是实际播放 PCM 偏移，Agent 对照 playback_source_offset 校验，并核对 warp_speed_ratio，不能直接拿它与原始偏移比较。

## 0.9.1 分析参数增量

`start_analysis` 与模型工具 `start_audio_analysis` 共用下列 parameters，kind 不变：

- separate：`stems=4|6`、`quality=fast|quality`、`segment_seconds=3..4`。能力 `separation_six_stems` 独立报告安装状态。六轨结果必须为 vocals/drums/bass/piano/guitar/other，按实际轨数检查导入预算。
- transcribe：`instrument=auto|piano|bass|guitar|vocals`，保留 onset/frame/minimum_note_ms/min_pitch/max_pitch。这是同一 Basic Pitch 的音域选项；other 仅显式选择音高乐器才允许尝试，drums 一直拒绝。
- chords：`vocabulary=extended|triads`。标签 N 或根音 C/C#/D/D#/E/F/F#/G/G#/A/A#/B 加冒号及 maj/min/7/maj7/min7/dim/aug/sus2/sus4/hdim7/dim7。显示 Cm7/G7，协议仍是 C:min7/G:7；未新增转位/9/11/13。

`get_analysis_job`、结果和保存 provenance 保留参数，完成后使用 Worker 规范化值。Agent 开始、取消、预览、接受均保留配置。`get_chord_regions` 增加可选 `analysis_id` 和 `latest_only` 供和弦轨分页，默认原行为不变。GUI 和弦选择未扩展 Agent 的音符/片段 selection_context；Agent 按授权来源读取真实 region ID 后编辑。

结果 `waveform_peaks` 是 128 点真实幅度概览，仅供原生绘制；Agent safe_result 将其剔除。本地语言设置不改命令、ID、参数、音乐数据或模型回答。

## 0.9 分析与候选导入（自动验证通过；人工验收见本轮记录）

音源分离、有音高分轨转 MIDI、和弦识别通过同一宿主管线由 GUI 或 Agent 发起。手动入口不依赖 API 密钥；推理在独立本机 Python 进程执行，语言模型仅收到有界摘要，不接收音频、模型文件路径或运行库路径。

| 宿主命令 | 参数与返回 |
|---|---|
| `get_analysis_capabilities` | `providers` 中每项为 `kind / available / model_id / version / experimental / detail`；最长单次 600 秒，单个重任务 |
| `start_analysis` | `clip_id`、`kind=separate/transcribe/chords`，可选片段内 `start_seconds / duration_seconds`；返回 `accepted` 与 `job_id / result_id`，不修改工程 |
| `get_analysis_job` | `job_id`；读取实际 `status / progress / phase / error / result_id`。`ready` 是候选完成，`applied` 是导入曾完成 |
| `get_analysis_result` | `result_id / offset / limit`（1–100）；返回 `items / total / source / model / result_hash / applied / present_in_project / stale`。`applied` 表示曾导入，`present_in_project` 表示当前工程保留该结果；分离路径不会暴露在该结果页 |
| `cancel_analysis_job` | `job_id`；取消本机计算，不删除原轨道 |
| `accept_analysis_result` | `result_id`，顶层带工程 ID、预期 revision 和可选选择 revision；后台核对来源及候选文件后原子导入，回执含新增轨道/片段/和弦 ID |
| `get_chord_regions` | 可选来源 `clip_id` 与 `offset / limit`（1–100）；返回已保存到工程的标签区间，不依赖候选缓存 |
| `edit_chord_region` | 真实 `id` 和可选 `label / start_seconds / end_seconds`；秒为工程绝对时间；单次命令、Undo 与工程版本保护 |

来源快照含 `project_id / clip_id / asset_id / track_id / clip_timeline_start / clip_source_offset / clip_duration / bpm / range_start_seconds / duration_seconds / timeline_start / source_sha256`。原片段不被覆盖。接受后分离新增四条音频轨，转录新增一条 MIDI 轨，和弦新增标签区间；MIDI 不自带原音色或弯音/踏板表达。`drums / other` 来源角色不可送入音高转录，改轨名不会移除该限制。和弦词表为 24 种大/小三和弦与 `N`，分数未经校准。

Agent 工具为 `start_audio_analysis / read_audio_analysis / cancel_audio_analysis / propose_analysis_import / read_chord_regions / propose_chord_edit`。开始工具在助手后台本地轮询宿主，不为进度额外调用付费模型；停止会取消该助手启动的任务。显式取消工具也可取消手动界面发起的分析，但须按宿主真实来源校验当前工程、片段和冻结时间选区；导入任务、已生成候选与其他终态不冒充可取消推理。取消请求后本地等候终态，未确认终态时明确返回 `cancel_completed=false`。默认分析范围取当前片段和时间选区交集，不能由模型扩大。导入与和弦修改均产生普通审核卡，点击应用后才写入工程。导入只提交 `result_id`，不会把大量候选音符展开成旧编辑动作；原有 16 动作/2000 次音符处理预算保持不变。

一次结果导入支持一次 Undo；相同候选幂等回执不创建重复对象，Undo 后使用 Redo，不重新接受旧候选。已完成不代表当前仍在工程中；查询当前和弦应使用 `get_chord_regions`。来源、速度、工程版本或选择变化会使旧审核卡失效。运行库/模型不可用、推理失败、来源过期和结果为空均不能显示为已完成的工程变更。

侧栏七类能力为工程/选区、MIDI 编辑、片段编辑、原生装置、音源分离、分轨转 MIDI、和弦识别。宿主命令、Agent 适配、装置目录、本机模型 readiness 和所选音频共同决定可用性；未就绪能力的示例按钮禁用。UI 示例、模拟 Provider 测试与真实模型测试分别记录，不能互相替代。新增实现与证据在 [Agent 分析记录](review/2026-11-05-audio-analysis/AGENT-NOTES.md)。

## 0.8.1 原生装置参数补充（2026-11-05）

EQ 每段 `shape` 为 `bell / low_shelf / high_shelf / high_pass / low_pass / notch`，高低通为 12 dB/oct，cut/notch 不使用 `gain_db`。宿主 `set_native_effect` 接收完整 state；Agent `set_native_effect_parameter` 可只给 `shape` 和 1-based `band`，本地编译器保留其余值。缺失 shape 的旧状态按首低架、尾高架、中间 bell 解读。新形状保存为装置状态 version 2，其余效果器版本不变。

`set_native_pad` 宿主参数仍为 `track_id / pad / gain_db / muted`，新增可选 `attack_ms`（0.1–2000）、`release_ms`（1–5000）、`one_shot`（bool）。缺失字段保持原值，旧状态默认 3ms/30ms、sampler 为 false、rack 为 true。Agent 动作允许只指定至少一个需要改的 pad 参数；编译器用已经读取的完整 pad 状态补齐，提交和回读保持原异步路径。MIDI 36 对应 0-based pad 0，Rack 固定 0–15。使用不同于旧默认的包络/模式保存为装置 version 2，旧程序拒绝而不会静默忽略。

`get_native_instrument` 返回已解析的包络/模式；模型侧移除本地 path，仅保留样本身份及允许读写的参数。仍要求 project 范围、已加载采样、单异步动作；模型不选择文件路径。`native_effect_catalog` 和 `native_instrument_catalog` 同步范围及类型，不匹配时停止装置操作。协议目录版本仍为 1，与装置存档版本分开。图形、旋钮、Agent 共用命令；它们不等于已接宿主自动化。验证与使用见[本轮人工检查](review/2026-11-05-device-controls/MANUAL-CHECK.md)。

装置 UI 的整机旁路使用通用 `set_plugin_enabled` 宿主命令；该命令暂未加入模型动作 allowlist，不能把“所有新声音参数可控制”解读为 Agent 可调用全部面板按钮。EQ 单频段的 `enabled` 仍可通过效果参数方案修改。

## 历史：原生采样器 / 鼓组底层命令（2026-11-02）

工作区视觉迭代：`get_native_instrument` 在已发布状态 ready 且该轨无待提交候选时，可能为已加载 pad 附带 `sample_sha256`，指向当前播放 bank 的源文件内容，用于非实时波形一致性检查；缺失不等于空音频。

只读 `get_native_instrument` 接收 `track_id`，返回类型、pads（采样器一个、鼓组 16 个）、asset_id/path、gain_db/muted、root_note/start/end 和 `load_status`/error。写操作 `add_native_instrument`（type 为 sampler/drum_rack）、`set_native_sample`（track_id/pad/path，空路径清除）、`set_native_pad`（pad/gain_db/muted）、`set_native_sampler`（root_note/start/end）受 project_id/revision 保护。写入提交为异步 accepted/job_id；必须观察 `get_job` 终态，不能把已受理当成已提交或可播放。当前 native job 无法取消；模型 Agent 可调用动作列表尚不含这些命令。限制与验证见[本轮记录](review/2026-11-02-sampler-drum-rack/RESULTS.md)。

实现入口为 EngineSession::executeRequest，本文主要描述原生 JSONL 协议，协议仍为v1。0.8.0第二批新增类型化批次结果引用，已通过本批原生与模型闭环验证；0.7.0的选择上下文和选择版本保护继续有效。唯一Edit/Undo边界不变。当前证据见[第二批记录](verification/2026-10-29-agent-batch2/RESULTS.md)。此前Release检查见[第一批记录](verification/2026-10-29-agent-sidebar/RESULTS.md)，不能当作本批验收；助手产品入口见[快速上手](AGENT_QUICKSTART.md)。

## 0.7.0内嵌传输与选择契约

常规DAW由工具栏Agent或Ctrl+Shift+A打开侧栏；DAW创建本机会话并拥有Python worker。AgentSidebar中的loopback JSONL桥先验证每会话能力令牌，再将EngineSession命令发到主消息线程；断开只结束助手连接，不能退出DAW。1MiB消息上限、有限等待及失联拒绝均属于传输约束；不是公开网络服务或模型API。原ControlServer的stdio模式保留下面的独立进程语义。

get_selection_context返回选择对象；get_snapshot的selection_context包含同一投影：
project_id、project_revision、selection_revision、active_track_id、active_clip_id、track_ids、clip_ids、note_clip_id、note_ids、note_count、notes_truncated、time_range（active/start_seconds/end_seconds）、focus与available。focus为arrangement/piano_roll/track/none；对象ID稳定，选择变化不增加音乐revision、不改变dirty或Undo。GUI保留最后音乐焦点，纯轨头选择不能冒充首个片段选择。控制stdio模式没有真实GUI选择时不能假造用户选区。

写请求可在顶层携带非负整数expected_selection_revision；不匹配返回selection_conflict，且不执行写入。它补充project_id/expected_revision，不替代工程版本校验。选择有界，available=false或truncated时Agent必须停止当前选择操作，不能自动扩大范围。模型产品的单方案16动作、每片段完整音符读取最多2000等更窄限制见快速上手。

页面/api/plan接受prompt与scope（selection默认、project显式）；/api/settings选择provider/model/base_url及可选api_key。嵌入页面不能通过/api/shutdown关闭DAW。Provider可以继续扩展，但只有Kimi/OpenAI实现了实际协议；API凭证和模型私有轮次状态不出现在页面状态。


## 启动和最小示例

```powershell
python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --demo build/agent-demo
```

该演示只在专用进程创建 8 小节测试音符、导出 MIDI、验证一步撤销，不播放声音，也不是产品乐句模板。应用直接入口为 `E-musician.exe --control-stdio`；加 `--show` 可同时显示该进程的界面。通过 stdin/stdout 发送 UTF-8 JSONL，stderr 留给诊断。关闭 stdin 后排空已接收请求再退出；此进程有自己的工程，不控制另一已打开的 DAW 窗口。

自动测试可使用Python客户端的 `offline_test=True`，映射到0.6.1既有 `--control-output-probe` 离线内存设备模式；普通 `--offline` 单独搭配control-stdio在该二进制中不生效。此诊断模式会向stderr写入探针标记，JSONL仍保持独立。

Python中可用`Client(executable, show=True)`同时显示受控工程，Agent和用户编辑同一活动Edit。调用者需保持Client/进程存活；关闭Client也会结束该控制实例。

读请求不要求身份：

```json
{"command":"get_snapshot"}
```

每个写请求携带最新工程身份及版本，`request_id` 对重试保持不变：

```json
{"request_id":"operation-1","project_id":"从快照取得","expected_revision":0,"command":"set_tempo","args":{"bpm":120}}
```

`scripts/agent_client.py` 的 `Client.request()` 可补齐缺失的身份和版本，明确传入的值不会被替换。`Client.raw()` 用于原样请求。控制端必须在收到 `conflict` 或 `wrong_project` 后重新读取状态、重新决定操作；不能盲目改变版本重放旧计划。

## 响应与任务生命周期

响应包含 `request_id/status/project_id/revision/result/error`。同步成功为 `completed`；后台任务为 `accepted`，`result.job_id` 用来查询 `get_job`，直到 `completed/failed/cancelled/conflict`。受理不代表文件已写出。保存的完成状态在主消息线程提交路径和 dirty 后才发布。

同一进程内，重复 request_id 和相同请求返回原始响应，不重复执行；不同内容重用 ID 会拒绝。当前比较序列化 JSON 内容，重试应保留同一字段顺序和数值表示。最多保存 10,000 个请求结果，达到后返回 busy，不淘汰幂等记录；重启后不保证跨进程幂等。任务历史保留最近 64 项。一个重文件任务执行/待提交时，新的重任务返回 busy 文本错误；取消后等到终态再提交下一项。

后台导入/打开只在原工程身份和版本仍匹配时提交。保存/导出使用启动时的固定快照；期间可继续编辑，晚到的保存不会清除后续编辑的 dirty。WAV 在独立子进程渲染，取消/失败不替换旧目标。最终替换前再次核对原目标指纹。

## 读命令

| command | args | result |
|---|---|---|
| get_selection_context | 无 | 当前只读选择对象及独立selection_revision |
| get_capabilities | 无 | 命令列表、格式、范围和分页上限；支持本批依赖引用时含batch_result_refs=true、batch_result_refs_version=1 |
| get_snapshot / get_project_state | 无 | 工程身份、版本、速度、播放位置、轨道、片段预览、插件槽及任务 |
| get_save_diagnostics | 无 | current_key/saved_key/fresh_content_key、plugin_dirty、pending_plugin_changes和revision；仅排错时显式调用，重新计算内容摘要，不用于播放头高频轮询 |
| get_track_clips | track_id, offset=0, limit=64（最大256） | total, offset, clips |
| get_clip_notes | clip_id, offset=0, limit=256（最大1000） | total, offset, notes |
| get_plugin_catalog | offset=0, limit=64（最大256） | total, offset, plugins |
| get_plugin_parameters | plugin_id, offset=0, limit=128（最大256） | total, offset, parameters，value 为0–1归一化值 |
| get_recording_inputs | 无 | inputs: id/name/type/midi/enabled/monitor；仅列现有引擎输入 |
| get_recording_state | 无 | recording/finalizing/error/tracks/recording_directory/monitor_scope，以及counting_in/count_in_beats_remaining/recording_start_seconds |
| get_recording_preferences | 无 | metronome_enabled/metronome_gain_db/metronome_record_only/count_in_enabled/count_in_bars；scope为application |
| get_clipboard_state | 无 | clipboard_id/project_id/clip_count；应用内的完整片段剪贴板，不是钢琴卷帘音符剪贴板 |
| get_audio_devices | scan=false；true仅用于显式刷新 | drivers（含inputs/outputs/separate_inputs_and_outputs）、当前driver/device及独立input_device_name/output_device_name、实际sample_rate/buffer_size、可选rates/sizes、输入输出通道和设备报告的延迟 |
| get_automation_targets | track_id；master表示主输出 | targets: target/plugin_id/parameter_id/name/current_normalized_value/text |
| get_automation_points | track_id, lane_id, offset=0, limit=256（最大1000） | points、total、offset、has_more |
| get_clip_controllers | clip_id, offset=0, limit=256（最大1000） | events、total、offset、has_more |
| get_jobs / get_job | 无 / job_id | 有界任务历史 / 单个任务 |
| get_events | after_sequence=0（非负整数） | events, sequence, resync_required |

快照每轨最多64个片段、全工程最多256个，包含 `clip_count/clips_truncated`；完整内容通过分页取得。快照只含 note_count；音符走专用分页。插件目录预览最多256项并带 total/truncated。事件保留最近1024条；resync_required 为 true 时先重读状态，再从新 sequence 继续。播放位置是轮询状态，不按每个采样产生事件。

0.6.0 快照补充以下运行状态，它们不是新的音乐版本，轮询更新不增加 revision：

| 位置/字段 | 含义 |
|---|---|
| 顶层 recording_preferences | 与get_recording_preferences相同的应用偏好对象 |
| 顶层 counting_in、count_in_beats_remaining | 是否在录音预备阶段、剩余拍号单位拍；例如6/8每小节6拍 |
| 顶层 memory_working_set_bytes、memory_private_bytes | Windows进程工作集和私有提交量，字节；包含进程内插件，不能归因到单个插件 |
| 顶层 cpu_usage、xruns、sample_rate、buffer_size | 既有音频回调负载（比例，乘100为DSP百分比）、欠载计数、实际采样率和实际缓冲区；cpu_usage不是整机CPU |
| 顶层 master_peak_left_db、master_peak_right_db、master_overloaded | 主输出左右电平及保留的过载指示 |
| tracks中的peak_left_db、peak_right_db、input_peak_db、overloaded | 轨道输出电平、所选音频输入电平及轨道过载指示；MIDI输入不提供音频输入电平 |

内存最多每秒采样一次，电平最多每50ms采样一次，查询在控制线程执行；高频请求不会提高这些采样频率。未取得内存数据时字节数为0，静音/无可用电平以-100 dB底值表示。输出电平随时间衰减，overloaded保持到reset_meters或对应运行对象被重建；不是持久化测量报告。reset_meters不清除xruns，也不修改工程。不要为单个电平持续拉取大型完整快照，更不能把读接口或JSON序列化搬入音频回调。

## 编辑命令

| command | args |
|---|---|
| new_project | 无；120 BPM，4/4 |
| create_track | kind: audio、instrument 或 bus，name；MIDI轨的持久类型仍是instrument；新ID由引擎生成，不接受id/track_id覆盖 |
| rename_track / reorder_track / remove_track | track_id；分别追加 name / index（0起）/ 无 |
| set_track_gain / set_track_pan | track_id，gain_db（-60到6）/ pan（-1到1） |
| set_track_muted / set_track_solo | track_id，muted / solo（布尔） |
| set_master_gain / set_loop | gain_db / enabled |
| set_tempo / set_time_signature | bpm（20–300）/ numerator（1–32）, denominator（1/2/4/8/16/32） |
| set_loop_range | start_seconds, end_seconds；0/0为自动全工程范围 |
| move_clip | clip_id, start_seconds |
| move_clips | clip_ids, delta_seconds, target_track_id（可选，须同类型） |
| trim_clip | clip_id, start_seconds, end_seconds；音频可选 source_offset |
| split_clip | clip_id, at_seconds；两侧均至少1µs（0.6.1起；仍拒绝非正/非有限范围） |
| duplicate_clips / delete_clips | clip_ids |
| copy_clips / cut_clips | clip_ids；非空、不重复且全部存在的完整片段ID数组；成功result含clipboard_id、clip_count |
| paste_clips | start_seconds（0–172800）、clipboard_id（JSONL必填）；target_track_id可选字符串；详见剪贴板规则 |
| set_clip_fades | clip_id, fade_in_seconds, fade_out_seconds；两者之和不超过片段长度 |
| create_midi_clip | track_id, start_beats, length_beats；新ID由引擎生成，不接受id/clip_id覆盖 |
| write_notes | clip_id, notes（替换整个片段音符；最多100,000个，但stdio仍受1MiB帧上限） |
| edit_notes | clip_id, upsert, delete_ids（各最多10,000个）；通过稳定ID局部编辑大MIDI片段 |
| batch | commands: [{command,args,as?},…]；1–100项纯编辑，不嵌套、不包含文件任务或插件参数写入；as仅供下述受支持创建结果使用 |
| undo / redo | 无 |

音符字段为 `id/pitch/start_beats/length_beats/velocity/channel`。新音符可省略 id；既有音符必须保留 id。音高0–127，力度1–127，通道1–16；同一 MIDI 片段的音符使用相同通道；鼓编辑在空片段默认使用10，已有音符时保留原通道。拍位置相对片段；片段起点是工程绝对拍。音频秒区间保持原速，不实现拉伸；MIDI跟随工程固定 BPM。

这里的beats统一为四分音符拍；不能与界面的`bar:beat:tick`直接互换。界面拍数按拍号分母计，1小节对应`numerator * 4 / denominator`个API拍，界面每个拍号单位拍有960 tick。bars/seconds/both、网格、snap、follow和画笔属于编辑器状态，没有改变API单位或自动量化Agent提交数据。需要对齐的调用者应根据快照中的BPM/拍号明确计算合法时间。

batch 先验证全部候选状态，再一次提交、一次撤销。普通音频/MIDI编辑及对应撤销保留活动 Edit 和无关插件实例；新增/删除/重排插件、工程切换可以明确停止播放。

## 原生 batch 结果引用（0.8.0，已自动验证）

发送带依赖的批次前，先检查 `get_capabilities` 的 `batch_result_refs=true` 和 `batch_result_refs_version=1`。缺少能力时停止该方案，不通过自行指定新轨/片段ID兼容旧程序。

每个子项只能包含 `command`、`args` 和可选的 `as`。`as` 必须匹配 `[A-Za-z][A-Za-z0-9_-]{0,39}`，同批唯一。只有 `create_track`、`create_midi_clip`、恰好复制一个源片段的 `duplicate_clips` 可声明别名。轨道/片段 UUID 由原生候选创建；调用者提供的别名不是持久ID。

| 引用位置 | 允许的结果类型 |
|---|---|
| args.track_id、args.target_track_id | 此前create_track产生的轨引用 |
| args.clip_id、args.clip_ids中的每一项 | 此前create_midi_clip或单源duplicate_clips产生的片段引用 |

只把上述位置中整个字符串为 `@alias` 的值当作引用；名称、音符ID、插件ID及任意嵌套字符串不递归替换，例如轨名 `@literal-name` 仍是文字。未知/前向/跨批次引用、类型不匹配、非字符串ID、重复或非法别名均拒绝。声明结果的对象若在本批结束前被删除，也拒绝整批，避免成功回执携带失效对象。

以下为原生请求示例，身份和版本须替换成最新快照值：

```json
{
  "request_id": "create-phrase-example-1",
  "project_id": "CURRENT_PROJECT_ID",
  "expected_revision": 12,
  "command": "batch",
  "args": {
    "commands": [
      {"command":"create_track","args":{"kind":"instrument","name":"Phrase"},"as":"piano"},
      {"command":"create_midi_clip","args":{"track_id":"@piano","start_beats":0,"length_beats":4},"as":"phrase"},
      {"command":"write_notes","args":{"clip_id":"@phrase","notes":[{"pitch":60,"start_beats":0,"length_beats":1,"velocity":80,"channel":1}]}}
    ]
  }
}
```

成功响应的 `result` 为 `{"refs":{"piano":"引擎生成的轨ID","phrase":"引擎生成的片段ID"},"executed_commands":3}`，外层仍含 status/project_id/revision。无别名的成功 batch 返回空 `refs` 和执行命令数。相同request_id/内容的重试返回原回执，不再次分配对象；该回执不保证对象在后来的Undo或其他编辑后仍存在，应以当前快照为准。

原生沿用一个私有候选，逐命令维持原有校验，整批最终验证后才一次应用到 Edit。后续子项失败不会留下前面子项的轨、片段或音符，不增加音乐revision、dirty或Undo，不返回任何临时 refs。有效提交才结束此前GUI手势，整批成为独立一次Undo；失败批次不拆分正在进行的手势。实际无内容变化的批次沿用原无操作语义，不强制增加revision。

`duplicate_clips` 继续给复制出的音符和控制器分配新ID；返回值只映射轨/片段别名，不提供音符映射。`write_notes` 和 `edit_notes` 修改音符时保留片段控制器。控制器原生trim/split规则仍见下文，不因模型助手暂缓带控制器的MIDI裁剪而收窄原生命令。

## Python 助手层的范围与任务控制

本节不是新增原生命令。模型只获得 `read_clip_notes` 与 `propose_plan`；Python动作经候选模拟、选择约束及编译后才变成上表中的原生 batch。例如模型 `duplicate_clip/delete_clip` 对应原生 `duplicate_clips/delete_clips`；`add_notes/delete_notes/move_notes/set_note_length` 等通过 `write_notes/edit_notes` 表达。不能把模型动作名直接发作原生 command。

单方案最多16项动作、2000次音符处理，每个待编辑MIDI片段完整读取最多2000音符。依赖链也受同一累计预算，不能靠多个子项绕过。选择范围及版本在生成和应用前校验：当前音符选择不授权整个片段或无关新增音符，跨轨目标需在授权范围内，派生对象的后续操作仍继承范围限制。含控制器的MIDI trim在此Python层明确拒绝；复制保留控制器，必要的音符UUID重写仍处于同一个原生batch。

本机HTTP的 `/api/pause`、`/api/resume`、`/api/cancel` 接受空对象。暂停只接受规划中任务；在途模型调用等待返回后才到达暂停边界，仍可能计费。恢复重新核对工程/选区；取消阻止后续派发和方案发布。提交/撤销阶段不能暂停或中途取消；原子批次完成后用受版本保护的Undo还原。`/api/state` 提供任务阶段/进度；旧GET结果受generation保护，不能覆盖新任务、取消或模型切换后的状态。

若原生提交未收到明确回执，结果未知，桥停止后续写入且不自动重试。若已收到completed但回读/核对失败，界面明确标记“已提交”，保留已确认版本供安全撤销，不声称未执行；Undo确认提交后立即消费原撤销资格，回读失败也不再次Undo。Kimi/OpenAI适配仍沿用第一批，本批没有新增模型厂商。架构及取舍见[ADR0011](decisions/0011-agent-atomic-dependent-plans.md)。

## 完整片段剪贴板（0.6.0）

`copy_clips`冻结选定完整片段的内容及其音频资产引用，后续编辑或删除源片段不改变剪贴板。它不复制媒体文件、轨道、路由或插件实例。复制不增加revision、dirty或Undo；`cut_clips`在成功复制后删除源片段，一次Undo恢复整个剪切；粘贴是一次工程编辑、一次Undo。复制/剪切仍属于写请求，必须携带request_id/project_id/expected_revision。

每次成功复制/剪切生成新`clipboard_id`。JSONL粘贴必须带上对应token，包括batch中的paste_clips；缺失或与当前剪贴板不一致时拒绝。copy_clips/cut_clips须单独调用，不放进batch。`get_clipboard_state`可读当前身份，但遇到token失效应重新确认要复制的内容，不能无条件换成最新token继续旧计划。同一request_id重试copy返回原响应，不会重新覆盖后来变化的剪贴板，这也是token不能省略的原因。

示例中的身份、版本、片段ID和token均需替换为当前返回值，省略的request_id/project_id/expected_revision仍应按前述写请求规则提供：

```json
{"command":"copy_clips","args":{"clip_ids":["clip-a","clip-b"]}}
{"command":"get_clipboard_state"}
{"command":"paste_clips","args":{"clipboard_id":"copy返回的clipboard_id","start_seconds":8,"target_track_id":"目标轨ID"}}
```

`start_seconds`对应最早片段的粘贴位置。省略target_track_id或传空字符串时，按复制时的原轨ID放回；原轨已删除则失败。指定目标轨时，将最上方复制轨对齐目标轨，再按原行间距映射其他片段；所有目标轨都必须存在且类型匹配，不自动新建轨道。类型不符、ID失效、越界或数量超限均整体失败，不留下部分片段。新片段、音符和controller都有新ID，音频资产ID复用当前工程的规范路径；Save As后不恢复旧素材路径。

纯MIDI片段组保留复制时的拍间距，因此复制后改BPM再粘贴仍保留音乐间隔。含音频的混合组保留复制时的秒间距，MIDI片段内部音符长度仍按拍。剪贴板仅限当前工程的当前进程，新建/打开工程或退出后清空，不进入`.emproj`，不使用Windows系统剪贴板。剪切后资产引用保留供粘贴和Undo使用，调用者不应删除这些素材文件。

GUI时间选区只圈定时间并选中相交的**完整片段**，不会改变copy/cut/delete的范围语义；复制内部一段必须先split。钢琴卷帘的音符剪贴板是独立编辑器状态，没有专用JSONL命令；Agent使用get_clip_notes及edit_notes/write_notes实现音符编辑。生成新音符可省略ID或分配新ID，保留已有音符的稳定ID，按片段边界和单通道约束一次提交；不能依赖GUI焦点、画笔或插入标记决定Agent操作。

## 插件和 Transport

| command | args |
|---|---|
| scan_plugins | paths（可选绝对目录数组）；include_default_paths=false可关闭默认目录；modules可指定最多64个绝对.dll/.vst3文件或包 |
| add_plugin | track_id（master表示主总线）, catalog_id |
| remove_plugin / open_plugin | plugin_id；remove另带所属track_id |
| move_plugin / set_plugin_enabled | track_id, plugin_id, index / enabled |
| set_plugin_parameter | plugin_id, parameter_id, value（有限0–1）；支持一步撤销 |
| play / pause / stop | 无 |
| seek | seconds（有限且非负）；允许空工程/最后片段之后定位，超过172800秒时限制在该上限 |

VST2/VST3只支持Windows x64。MIDI轨需要安装并加载可用乐器才发声；没有自带音源。参数ID以宿主当前返回为准，不假定跨插件版本兼容。参数写入通过主线程和标量Undo，保存/导出才获取完整插件状态。缺失插件保留槽位和状态；启用的缺失插件阻止相应音轨的WAV导出。扫描在独立子进程；正常播放中的插件仍在DAW进程内。

当前`EMUPLUG1`原始参数快照按索引存储。包含参数快照且保存版本非空时，版本必须与扫描到的插件版本一致；版本不匹配会保留missing槽和原状态块，不能静默将旧索引写入新版本。跨版本参数迁移尚未实现。

## 录音、设备、路由和自动化

下列接口已接入源码；构建、合成输入、真实声卡及插件兼容的通过状态分别以[CONTEXT](CONTEXT.md)与验证报告为准。录音不需要Agent拥有音频线程；GUI与Agent使用同一条命令路径。

| command | args及行为 |
|---|---|
| configure_audio_device | driver_type；device_name可同时指定输入/输出（ASIO）；或input_device_name/output_device_name；sample_rate、buffer_size、input_channels（可选0起索引数组） |
| set_track_input | track_id, input_device_id；空字符串清除选择，选择保存在工程中 |
| set_track_armed | track_id, armed（布尔）；仅音频/乐器轨；运行时状态，不写入工程 |
| set_input_monitor | `track_id`、`mode: off/auto/on`：逐轨运行时监听；旧版 `input_device_id` 仍支持，并同时修改该设备当前所选的全部轨道 |
| start_recording / stop_recording | 无；线性新take，开始前须关闭loop并选择/arm输入 |
| set_recording_preferences | 部分更新metronome_enabled、metronome_record_only、count_in_enabled（布尔）、metronome_gain_db（-36到0）、count_in_bars（1/2/4） |
| reset_meters | 无；重置轨道、音频输入及Master电平/过载保持，不重置xruns |
| set_track_output | track_id, target_track_id；master或既有bus ID |
| add_send | track_id, target_track_id；可选send_id、gain_db=-12、pre_fader=false、enabled=true |
| update_send / remove_send | track_id, send_id；update可追加target_track_id/gain_db/pre_fader/enabled |
| set_automation_lane | track_id、lane_id（新建可省）；新建必填target；可选plugin_id/parameter_id/enabled/points |
| remove_automation_lane | track_id, lane_id |

设备名与输入ID必须先从读接口取得，不能靠数组位置持久引用。配置设备要求先停止播放；失败会尝试恢复原driver与AudioDeviceSetup，并报告恢复失败。读出的sample_rate/buffer_size是实际协商值，延迟字段来自驱动，不等同于回环实测。显式`scan:true`可能耗时，禁止把它放进高频UI轮询。ASIO编译后还需本机厂商驱动；当前ASIO接入方式见[DEPENDENCIES](DEPENDENCIES.md)。

`sample_rates/buffer_sizes`只描述当前打开的设备。切换driver或设备时可先省略采样率和buffer，成功后重新读取可选值。`separate_inputs_and_outputs=true`的driver应分别传入`input_device_name/output_device_name`；`device_name`可能是组合显示名，不能当作独立输入或输出名。MIDI输入在轨道选择后首次arm时由引擎自动启用，无需另开JUCE MIDI开关。

示例只展示args；写请求仍需前述request_id/project_id/expected_revision。设备名称以本机`get_audio_devices`返回为准：

```json
{"command":"configure_audio_device","args":{"driver_type":"ASIO","device_name":"M-Audio M-Track Solo and Duo ASIO","sample_rate":44100,"buffer_size":256,"input_channels":[0,1]}}
{"command":"set_track_input","args":{"track_id":"audio-track-id","input_device_id":"从get_recording_inputs取得"}}
{"command":"set_track_armed","args":{"track_id":"audio-track-id","armed":true}}
{"command":"set_input_monitor","args":{"input_device_id":"从get_recording_inputs取得","mode":"auto"}}
{"command":"start_recording","args":{}}
{"command":"stop_recording","args":{}}
```

`monitor_scope`为 `track_and_input_device`。推荐使用 `track_id`：即使多轨选择同一个输入，每轨的 off/auto/on 也独立；auto 在该轨 arm 时监听，on 不依赖 arm，off 关闭该轨软件监听而不取消录音准备。新轨和重新打开的工程默认 off。旧调用 `input_device_id` 会对当前选择这个输入的所有轨统一设置，不应当用它实现逐轨控制。选择新输入时，on 轨会在控制线程重新绑定；若绑定失败会报告错误，同一次失败的选择不会无限重试，可重新设置监听或 arm 重试。监听是运行状态，离线回归覆盖共享输入、录音准备和切换输入，实体设备与听感仍需验收；按住键时关闭监听的尾音尚待专项处理。音频采用24-bit WAV新take，MIDI录入notes及CC、程序切换、pitchbend、poly-aftertouch/channel pressure。当前每MIDI片段沿用单通道模型，尚不声明MPE/SysEx、循环叠录与comping。

Stop受理后继续读recording/finalizing；finalizing结束并收到recording_completed后，片段才进入工程绑定并生成一次revision。所有同时录入轨道组成一次撤销事务，Undo保留录音源供Redo。录音/结束认领期间禁止音乐编辑、换设备、工程切换与保存；先Stop并等待finalizing=false再提交。设备、arm、monitor及播放位置不按音频块推进revision；完成take才改变音乐版本。工程重开不会自动arm输入。

节拍器/预备拍偏好保存在本机应用配置，`scope`为`application`，不属于工程schema、Undo或音乐revision。默认metronome_enabled=false、metronome_record_only=false、metronome_gain_db=-12、count_in_enabled=false、count_in_bars=1；关闭预备拍保留已选小节数。set_recording_preferences只更新提供的键，拒绝未知键和错误类型；预备/录音/收尾期间不能修改。JSONL设置偏好和reset_meters仍遵守写请求身份/幂等校验。

从**停止状态**start_recording时才使用预备拍；普通play没有预备拍，已经playing时start_recording直接录制。倒数由引擎音频时钟推进；`recording`在预备阶段可能已为true，必须结合`counting_in`区分真正写入阶段。get_recording_state的recording_start_seconds是预定录音起点，count_in_beats_remaining按拍号单位拍计数。预备阶段stop_recording取消本次录制并回到起点，不生成空take。节拍器强调小节首拍，只用于监听，不写入内部录音或离线WAV；这些新行为的设备听感和首音边界仍需独立验收。

```json
{"command":"set_recording_preferences","args":{"metronome_enabled":true,"metronome_record_only":false,"metronome_gain_db":-12,"count_in_enabled":true,"count_in_bars":1}}
{"command":"get_recording_preferences"}
{"command":"get_recording_state"}
{"command":"reset_meters","args":{}}
```

以上写命令示例同样省略了必需的请求身份字段。偏好不会随工程文件传给另一台电脑；Agent开录前应读当前应用设置，不假定打开工程会恢复某套预备拍配置。

输出与发送只能进入master/bus组成的有向无环图；send只允许bus，输出和所有send（包括disabled）一起校验cycle。同一轨到同一bus只允许一条send。发送增益-60..6dB，pre_fader决定位于源轨fader前或后。bus可承载自身的外部效果链。本版不声明任意侧链、外部硬件insert或多输出乐器矩阵。

轨道曲线target为`track_gain`、`track_pan`或`plugin_parameter`；master仅支持`master_gain`和`plugin_parameter`。非插件target的plugin_id/parameter_id必须留空；插件参数ID以当前`get_automation_targets`为准。每个参数只允许一条lane。points字段为`id/time_seconds/value/curve`：time_seconds是工程绝对秒，value归一化到0..1，curve范围-1..1（0为直线）。点按时间严格升序且不能同一时刻重复；改BPM不移动绝对秒曲线。

```json
{"command":"set_automation_lane","args":{"track_id":"audio-track-id","lane_id":"gain-curve","target":"track_gain","enabled":true,"points":[{"id":"point-a","time_seconds":0,"value":0.5,"curve":0},{"id":"point-b","time_seconds":8,"value":0.8,"curve":0}]}}
```

value不是dB；以目标返回的当前归一化值/显示文本理解参数，并由引擎转换原生范围。set_automation_lane传points会整体替换该lane，省略points则保留；传enabled=false会旁路。曲线进入真实引擎播放和离线导出，静态fader保存显式手动值，不保存播放中瞬时读值。这里提供Read/旁路与曲线编辑，不提供Touch/Latch/Write录制自动化。缺失插件保留原lane身份和点，等待同槽插件恢复；不能把旧参数ID应用到另一个插件。

controller读接口event字段为`id/beats/type/value/metadata`。beats相对clip；CC type为0..127，程序切换0x1001、poly-aftertouch0x1004、pitchwheel0x1005、channel pressure0x1007；普通7-bit值按`value >> 7`读取，pitchwheel保留0..16383，poly-aftertouch的metadata为音符号。split/trim在新边界补前序控制器状态，但不重放CC120..127通道模式动作；复制为controllers分配新ID。

## 文件命令

| command | args |
|---|---|
| import_audio | paths: 绝对WAV/MP3文件数组；每文件新建音轨 |
| import_midi | path: .mid/.midi；notes_only=false |
| save_project / open_project | path: .emproj |
| export_midi | path，clip_ids可选；选择导出从最早所选片段归零，整工程保留绝对拍 |
| export_wav | path, start_seconds=0, end_seconds=工程末端, sample_rate=48000, bit_depth=24, tail_seconds=2, realtime=false |
| cancel_job | job_id；扫描任务ID为plugin-scan |

所有路径必须绝对。WAV输出44.1/48/88.2/96kHz、16/24/32bit立体声，尾音0–60秒；不导出MP3。工程保存为schema4，包含输入选择、bus/send、自动化、MIDI controllers及既有资产/插件；schema1–3加载迁移，覆盖旧清单前保留原字节备份。

MIDI导入支持SMF0/1、PPQN；导出960PPQN并包含已录入的上述controller类型。当前SMF导入仍默认拒绝不能完整保留的CC、程序切换、表达、速度/拍号图和SMPTE，`notes_only`必须明确选择；不要把录音/导出支持误读为SMF导入已支持全部事件。空工程接受文件的固定速度/拍号，非空工程要求匹配；notes_only按现有速度导入拍点。

## 资源边界

JSONL单帧最大1MiB、嵌套最多32层、输入/输出队列各32项，主线程每轮最多处理8项。慢读端由独立写线程承担等待；不能把网络、JSON、文件I/O或Agent推理放进音频回调。64轨、4096片段和100,000音符是输入限制，不能解释为任意插件负载下的性能承诺。实测机器、设备和负载见验证报告。

schema4另限每轨32/全工程512条send、每owner256/全工程4096条lane、全工程100,000个automation点与100,000个controller事件。单次请求仍受1MiB上限限制。原生录音委托固定Tracktion writer与输入管线；尚未证明其在所有负载下无锁/零分配，也未从合成输入通过推断M-Audio或任意ASIO设备的实时性能。

## 0.6.1精度边界

固定网格最细1/16384全音符，即1/4096四分音符拍。网格、吸附与标尺是界面状态；Agent命令仍直接传完整双精度秒/拍，不受屏幕绘线密度限制。`split_clip`两侧至少1µs。原生工程保留完整位置；SMF导出4096PPQN，二进制细网格准确表示，任意自由位置/三连音舍入到最近tick，正时长至少1tick。长工程使用64位绝对tick及合法SMF间隔填充，不依赖32位绝对tick。Inspector的bar:beat:tick显示仍为每分母拍960刻度，不用于截断未编辑底层值。
