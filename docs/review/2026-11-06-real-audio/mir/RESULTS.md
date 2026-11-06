# 整曲 MIR：实际结果与限制

2026-11-06，用户上传的两份完整 MP3 在现有 RTX5090 云实例上完成三项顺序推理；各一次真实模型调用，没有裁切、重抽或更换模型。原始 WAV/MIDI/LAB/JSON 仅在云端。本地仅保存小型验证元数据；原部署wrapper、模型、环境、ACE服务和DAW未修改。以下是文件完整性和处理结果，不是准确率或人工听感验收。

## 输入身份

| 用户素材 | 云端名称 | 完整音频 | SHA256 |
| --- | --- | --- | --- |
| `New Light.mp3` | `inputs/newlight.mp3` | 218.3047845805秒；44.1kHz双声道；9,627,241帧 | `885891e2076ca629d3e60685a68df3be07e20da00f0ee45038b5da547519826b` |
| 用户明确的 `Keyboard.mp3` | `inputs/piano.mp3` | 279.0309750567秒；44.1kHz双声道；12,305,266帧 | `5b425c8fe09cf82f99a530ae529fe7607c0b792e93d0f91455cc338fd95b632f` |

`inputs/` 的完整前缀为 `/root/autodl-tmp/emusician/workspace/evaluations/real_audio_20261106/`。每次前检和实际worker均核对输入SHA；完整解码帧数与预检一致，SCNet和TransKun本次模型采样率均为44.1kHz，所以没有重采样。

## 原始结果

输出统一前缀：`/root/autodl-tmp/emusician/results/evaluations/real_audio_20261106/`。每个任务父目录的 `attempt.json` 和 `data/result.json` 均为 `status=passed`；`result.json` 记录各原始文件的绝对路径、字节数和SHA。原始结果供父代理打包，不包含失败任务。

| 任务目录 | 原始结果 | 实际检查 |
| --- | --- | --- |
| `scnet-20261106T125207Z-22e9bebf/data/` | `drums.wav`、`bass.wav`、`other.wav`、`vocals.wav` | 每个文件77,018,016字节，FLOAT WAV、44.1kHz双声道、完整9,627,241帧；逐块重读全部有限值 |
| `chordmini-20261106T125321Z-31c71300/data/` | `chords.lab`、`chords.json` | 147段连续区间；覆盖0–218.3047845805秒，尾差0；2351个feature帧全部预测，未延长标签 |
| `transkun-20261106T125401Z-ed271438/data/` | `piano.mid` | 14,986字节；重新解析得到2178个音符、172个CC事件，CC64/67保留；音符/控制合法，末事件276.955729秒，无越过源时长事件 |

SCNet输出未做额外归一化或削波，保留模型的浮点结果。drums peak=1.238231、other peak=1.039966，大于1的采样在FLOAT WAV中原样保留；这不是保存过程中被削波。后续浏览器试听若转成PCM，必须另做试听副本，不能覆盖这批原始结果。TransKun保持16秒segment、8秒hop、`discardSecondHalf=False`、`mergeIncompleteEvent=True`，未修剪或量化原始音符、未丢弃踏板事件。ChordMini保持batch1、hard vote、无额外平滑，词表仍是170类，不保证任意爵士扩展和弦或转位准确。

## 资源与耗时

单 RTX5090，总显存32607MiB；ACE常驻但无活动任务。三项开始/结束时均空闲14774MiB，按共享锁串行执行。Torch/Torchaudio为原独立环境2.10.0+cu128，CUDA12.8。实例cgroup内存限额96,636,764,160字节（90GiB）；准入和运行监测使用cgroup有效余量，不能将`/proc/meminfo`的整宿主机容量当成实例资源。

| 项目 | worker含加载/处理/输出 | 外围含前检/启动/监测 | CUDA allocated / reserved峰值 | 0.5秒采样RSS最大值 |
| --- | ---: | ---: | ---: | ---: |
| SCNet整曲 | 25.059秒 | 27.430秒 | 1.342 / 2.504GiB | 2.792GiB |
| ChordMini整曲 | 2.266秒 | 4.652秒 | 0.024 / 0.037GiB | 1.370GiB |
| TransKun整曲 | 7.167秒 | 9.518秒 | 0.917 / 1.113GiB | 1.780GiB |

CUDA统计来自该worker的PyTorch allocator，不是整卡总占用。RSS为采样值，不保证捕获瞬时峰值；时间不含本地上传、SSH建连或后续打包。本次只有各一个文件，不是重复性能基准或其他机器的速度承诺。三个worker结束后已释放GPU时段给后续SheetSage2，未再运行模型。

## 版本与记录

- SCNet源码 `a8a862231de29e6832a26c590e5c29f82f736f66`，发布v1.0.15；权重SHA `ac25975f0f5704f3d1a3c3c251505b7a0f417a22eafe82773440ee4f7e14b74f`。使用原11秒窗口、overlap4、AMP、batch1，未修改上游实现。
- ChordMini源码/权重版本 `aa6e3a8d7b017f082fd2aaff9329d5c26af49c03`；权重SHA `e0a12ca6d881f81e01dfb459b4836ec7dac8d8f87b0170a412b5807256b3a1fc`。
- TransKun源码/权重版本 `c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6`；权重SHA `50a80010effc2a59ffcd068a95cd2b29bd7f23a27a3515bc3ccd209c89a3d44c`。
- 三次实际推理使用同一整曲脚本SHA `8b3aa4c41b651754befd53a798661931ee29e3f52b7d8e21776d3c5dacf18480`；guard SHA `0879672f45a8fb32417b25dd0cae103ca3c97be8b63d294db8e890f7e2ffe011`。
- 实际推理Recorder：SCNet `20261106T125205.389283Z-e9f0cec391`；ChordMini `20261106T125311.502792Z-7147533edd`；TransKun `20261106T125358.860792Z-d262c74a62`。命令、起止、stdout和版本保存在对应 `docs/builds/` 与忽略目录 `build-logs/`。
- CPU guard故障测试5项通过：`20261106T125002.929397Z-9553ff950b`；有效资源读取修正后复测 `20261106T125149.559452Z-2884e256e4`，包括owned子进程忽略SIGTERM后SIGKILL、退出竞争、最终诊断/cleanup/写盘异常保留记录。没有使用额外GPU来做故障测试。

## 失败与修正完整保留

首次SCNet执行在CPU前检碰到 `stat().st_size()` 笔误，尚未导入Torch、加载模型或调用GPU；Recorder `20261106T125020.300752Z-72fa38eb9a`，失败目录 `scnet-20261106T125021Z-399a479b`。修正为属性读取，并把资源检查改为cgroup与宿主余量较小值，独立完整MP3前检成功 `20261106T125111.514749Z-5e613c6a01`。之后才进行第一次实际SCNet推理。

一次纯CPU guard复测SSH连接被重置，Recorder `20261106T125112.669058Z-1c58943951`；不能把连接退出255当作测试通过。一次有界重连后5项测试通过，后续实际任务加入ConnectTimeout和ServerAliveInterval。上述两项是基础设施/前检尝试，不能计为多次模型结果筛选。

小证据见 [SCNet](evidence/scnet/attempt.json)、[ChordMini](evidence/chordmini/attempt.json)、[TransKun](evidence/transkun/attempt.json)、[前检失败](evidence/scnet-preflight-failure/attempt.json)。分离串音、漏音、和弦识别正确性、钢琴音符/力度/踏板准确率尚待人工试听或标注核对；没有从输出数量或速度推断准确率。
