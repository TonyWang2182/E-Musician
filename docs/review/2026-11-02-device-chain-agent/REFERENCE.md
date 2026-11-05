# 装置链与原生装置参考（2026-11-02）

## 官方依据与设计启发

- [Ableton Live 12：Working with Instruments and Effects](https://www.ableton.com/en/live-manual/12/working-with-instruments-and-effects/)：选中轨道的 Device View 在窗口底部；设备按信号链从左到右排列，支持折叠、启停、排序，浏览器双击或拖放添加。MIDI 乐器之前为 MIDI 信号、之后为音频信号。界面顺序和实际处理顺序必须一致，不能只调整视觉列表。
- [Ableton Live 12：Instrument, Drum and Effect Racks](https://www.ableton.com/en/live-manual/12/instrument-drum-and-effect-racks/)：鼓垫表示 MIDI 音符，16 垫为可翻页视口，共 128 音符；链支持预览、静音/独奏、增益、choke 等。现有实现为固定 36–51 的 16 个采样槽，并非完整多链 Rack。
- [Ableton Live 12：Live Instrument Reference](https://www.ableton.com/en/live-manual/12/live-instrument-reference/)：Simpler 注重波形定位、区域、音高、播放模式与包络；完整 Sampler 还含多采样分区、调制等。现有装置仅单 WAV、根音、起止与简化的释放，功能更接近基础单采样器。
- [Ableton Live 12：Live Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/)：EQ Eight 每段有多种滤波类型及可选频谱、L/R 或 M/S；Compressor 提供阈值、比例、动态反馈、干湿混合及侧链。现有 EQ 的首末频段固定架、中间固定峰；压缩器此前仅提供基本参数和静态曲线，并非 Ableton 相同算法。

## 可实施优先级

1. 底部可见设备链与内置装置选择：选轨后显示真实有序 slot、选中状态、左右切换、旁路/移除/重排；明确主轨、空链及第三方装置编辑器。文件载入状态统一使用同一装置身份和权威状态。
2. Sampler/Rack 先补真实加载、显示与试听的可靠性，再考虑波形缩放、包络、one-shot/gate、逐垫音量、翻页与 choke。渐进加入须覆盖真实渲染、录音、保存重开、撤销与旧工程兼容。
3. EQ 先提供实用高低切/架/峰/陷波选择和可靠曲线，压缩器先有真实 dry/wet 与真实压缩量反馈；进阶频谱、M/S、侧链和预设另行实现，不能用假数据显示。
4. 新装置和参数应有统一版本化描述、范围、单位、快照、读写命令及 Agent 能力发现、作用域校验、实际回读；实时音频线程不进行网络、文件操作、JSON 解析和阻塞。

本页为参考和优先级，不表示所有 Ableton 功能已经实现，也不承诺与其 DSP 或专有算法一致；性能结论必须以指定负载和设备的测量为准。
