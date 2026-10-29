# 本地 Agent 控制接口 v1

实现入口：`EngineSession::executeRequest`、`ControlServer`。本文已对照0.6.0源码更新（2026-10-29），协议版本仍为v1。新增接口随最终Release5/5通过；人工操作与听感待验收，完整范围见[0.6.0记录](verification/2026-10-29-v060/RESULTS.md)。协议不包含模型、聊天界面或网络服务。

## 启动和最小示例

```powershell
python scripts/agent_client.py --exe build/bin/Release/E-musician.exe --demo build/agent-demo
```

该演示只在专用进程创建 8 小节测试音符、导出 MIDI、验证一步撤销，不播放声音，也不是产品乐句模板。应用直接入口为 `E-musician.exe --control-stdio`；加 `--show` 可同时显示该进程的界面。通过 stdin/stdout 发送 UTF-8 JSONL，stderr 留给诊断。关闭 stdin 后排空已接收请求再退出；此进程有自己的工程，不控制另一已打开的 DAW 窗口。

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
| get_capabilities | 无 | 命令列表、格式、范围和分页上限 |
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
| create_track | kind: audio、instrument 或 bus，name；MIDI轨的持久类型仍是instrument |
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
| create_midi_clip | track_id, start_beats, length_beats |
| write_notes | clip_id, notes（替换整个片段音符；最多100,000个，但stdio仍受1MiB帧上限） |
| edit_notes | clip_id, upsert, delete_ids（各最多10,000个）；通过稳定ID局部编辑大MIDI片段 |
| batch | commands: [{command,args},…]；1–100项纯编辑，不嵌套、不包含文件任务或插件参数写入 |
| undo / redo | 无 |

音符字段为 `id/pitch/start_beats/length_beats/velocity/channel`。新音符可省略 id；既有音符必须保留 id。音高0–127，力度1–127，通道1–16；同一 MIDI 片段的音符使用相同通道；鼓编辑在空片段默认使用10，已有音符时保留原通道。拍位置相对片段；片段起点是工程绝对拍。音频秒区间保持原速，不实现拉伸；MIDI跟随工程固定 BPM。

这里的beats统一为四分音符拍；不能与界面的`bar:beat:tick`直接互换。界面拍数按拍号分母计，1小节对应`numerator * 4 / denominator`个API拍，界面每个拍号单位拍有960 tick。bars/seconds/both、网格、snap、follow和画笔属于编辑器状态，没有改变API单位或自动量化Agent提交数据。需要对齐的调用者应根据快照中的BPM/拍号明确计算合法时间。

batch 先验证全部候选状态，再一次提交、一次撤销。普通音频/MIDI编辑及对应撤销保留活动 Edit 和无关插件实例；新增/删除/重排插件、工程切换可以明确停止播放。

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
| set_input_monitor | input_device_id, mode: off/auto/on；运行时设备级监听 |
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

`monitor_scope`固定为`input_device`：共享同一输入设备的轨道共享off/auto/on，不能视作独立的每轨监听。auto在轨道arm时监听；on持续监听已连接目标；off关闭软件监听。音频采用24-bit WAV新take，MIDI录入notes及CC、程序切换、pitchbend、poly-aftertouch/channel pressure。当前每MIDI片段沿用单通道模型，尚不声明MPE/SysEx、循环叠录与comping。

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
