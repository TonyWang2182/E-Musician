# 拍摄音频：原 DAW 实际导出

状态：三项音频已由保留的 0.13.6 实际音频/插件管线导出并进行数值核验。没有重新推理，没有替代成原录音，没有复用旧的 `test drive.wav`。实体声卡与人工听感不在本次验收范围。

## 交付

根目录：`E:/MusicAgent&DAW/demo-video/showcase-v1/audio`。

| 文件 | 来源与结果 | 数值核验 |
|---|---|---|
| `demo4-current-mix.wav` | 当前 `E:/E-musician/test-projects/demo 0&4/test drive.emproj`，9 轨，160 BPM，原插件/预设/自动化，0–60 秒 | 48 kHz、24 bit、双声道、2,880,000 帧；峰值 0.281397，RMS 0.044065，0 削波样本 |
| `d3-keyscape-midi-only-realtime.wav` | Tea for Two 的 132 音符转录，原工程已保存 Keyscape VST3 音色；原音频轨明确 Mute，只导出 MIDI 乐器 | 48 kHz、24 bit、双声道、768,000 帧/16 秒；峰值 0.201905，RMS 0.021428，0 削波样本；全部 16 个一秒块都有非零音频 |
| `d2-new-light-warp.wav` | 原生六场景联测实际 Apply Warp 后的 `captures/projects/D2-02-Warp.emproj`；保留 beat-analysis 来源与随 Warp 映射的和弦轨 | 48 kHz、24 bit、双声道、1,212,000 帧/25.25 秒；峰值 0.895430，RMS 0.159203，0 削波样本 |

哈希：

- Demo4：`f1ec132984dd193b89e3e39470103fb85ce1f09cb8ab5c498897388e4cc4bb9a`。
- D3：`6e0731d7db92ecbf04a4c64111f9755af83f6f2bd31edf21ca5f022e53bf56a7`。
- D2：`26c7c04fd03b42f4402ef2fd66322072d0aa38497a3879084fa41c1b2e6c73cd`。

**不要用于剪辑：** `audio/d3-keyscape-midi-only.wav` 是第一次最快速离线导出的诊断产物，开头六秒为零，保留供审查。最终采用上表带 `-realtime` 的文件。这里的 realtime 是渲染子进程按块等待，并未打开声卡或开始播放/录音。

## 真实来源和操作

实现入口 `scripts/showcase_audio.py`，只允许保留的 `E:/emusician-analysis-build/bin-0.13.6/Release/E-musician.exe`；EXE SHA-256 为 `81020b783de6540746de5a81215ea8a62cc133f4d8202a30d40add3b98940699`。

脚本只复制 `.emproj` 实际引用的音频和插件状态文件，保留相对路径。原工程、所引用文件和 EXE 在执行前后均进行 SHA-256 比较，最终均未改变。所有修改均对副本，通过原命令入口执行。

使用 `Client(..., show=False, offline_test=True)`，启动 `--control-stdio --control-output-probe`。不执行 play、rec、声卡设置、SSH、API 或模型推理。导出经真实 `export_wav`，由原生隔离渲染子进程恢复原插件状态并处理实际工程；不是脚本混合 WAV，也不是往波形界面填数据。导出不归一化，尾音预算为 0，音频块为 512。

Demo4 保存九轨：MAIN DRUM、EP、DRUM 2、SAMPLE-RISE、Antidote FX 1 X Strange Jungle、Jungle_174 - Fx_Laser_1、RACK、BASS、sax_player。BM-VOID、BM-HUSTLE、两个 Keyscape 实例与原生采样/效果器均保持；原项目已有 sax 录音属于此次混音素材，不是新表演。波形非零不能单独证明每个乐器的主观听感符合预期。

D3 来源：`E:/MusicAgent&DAW/demo-video/2026-11-14/rehearsal/D3-Piano-570d980002b6/D3-TeaForTwo-MIDI.emproj`。来源音频 SHA 与保存的分析 metadata 一致；原结果 JSON SHA 与 `workspace/results/transcribe/result.json` 一致。排序后核对 132 个音符的音高、通道及起止时间，时间容差 1µs。原工程有一处后续力度编辑：58 号音符、11.715625 秒的力度从原 TransKun 结果的 62 改为 60。脚本仅在导出副本通过 `write_notes` 恢复 62，保持其余音符与原 CC/踏板事件，记录差异。

严格负对照：原音频轨仍静音、Keyscape 仍加载，删除整个 MIDI clip 后再次真实导出，得到 **16 秒全部为 0 的 PCM**；Undo 后 132 个音符恢复。它证明最终声音依赖该 MIDI 轨输入，没有用原钢琴录音顶替。

可供实际界面拍摄的 D3 工程副本：`audio/evidence/0fd220ba9275/D3-Keyscape-MIDI-only.emproj`（配套 assets 同目录）。该文件在负对照前保存，含 132 音符、Keyscape 状态和已静音的原音频轨。

## 实际尝试与记录

| Recorder 记录 | 命令 | 结果 |
|---|---|---|
| `20261121T163757.792831Z-1f78322f00` | `python scripts/showcase_audio.py --mode all` | 失败留档：Demo4 原生采样尚在 loading 时过早导出；D3 检出单音力度与原结果差异 |
| `20261121T163931.927370Z-b487bfe6a2` | 同上 | Demo4 通过；D3 快速导出前六秒为零，且仅删除 notes 的对照还保留踏板 CC，出现真实机械/踏板声音，整轮 exit 1 |
| `20261121T164234.208316Z-df7921c457` | `python scripts/showcase_audio.py --mode d3 --realtime` | D3 通过：从第一秒起有音频；删除整个 MIDI clip 的负对照全零；Undo 132 音符恢复 |
| `20261121T170815.469731Z-7aef65928b` | `python scripts/showcase_audio.py --mode d2` | D2 通过：副本中实际 Warp/follow-tempo 为开启、已有 beat-analysis 来源；原生 export_wav 输出非零且无削波；原工程及 EXE 哈希不变 |

命令均由 `python scripts/dev_showcase.py showcase command ...` 包装执行；Recorder 的 JSON 位于 `docs/builds/`，原始输出位于 `build-logs/`，对应摘要已由 Recorder 追加到 DEVLOG。Demo4 的独立通过收据为 `audio/evidence/960d48c37d61/demo4.json`；D3 的最终通过收据为 `audio/evidence/0fd220ba9275/d3.json`。脚本现默认对 D3 使用 paced render，禁止覆盖已有音频。

这两次诊断说明宿主已创建插件不等于采样准备完成，移除音符也不等于没有 MIDI 控制事件；没有用放宽静音阈值掩盖这些区别。Keyscape 首轮静音与异步加载/快速渲染相关，但未取得插件内部诊断，因此不声称已经证明厂商内部根因。

## Keyscape 目录身份

来自本地宿主实际 `get_plugin_catalog` 回读，不是外部 API：

| 格式 | catalog id | 安装位置 |
|---|---|---|
| VST3 | `8d922c369a6f430a1b0fdeb1cfce8c36d099a9509db7f54c4ac0219208c96bf0` | `C:/Program Files/Common Files/VST3/Keyscape.vst3` |
| VST | `ab03e2fb0d7601e7caca08829931ab01dceef93087e37ce01bbfdf63e0e39321` | `C:/Program Files/Steinberg/VstPlugins/Keyscape.dll` |

D2 Warp 导出收据为 `audio/evidence/89f4b0bd8dc5/d2.json`。来源阶段工程已通过实际 Apply/Undo/Redo、和弦时间映射与保存重开检查，再由保留的 0.13.6 打开副本并导出；不是预估时间变换或外部音频处理。该轮六场景联测随后在 D3 的测试浮点舍入比较上失败，D2 的独立导出已通过；完整联测状态另记于 REPLAY.md。
