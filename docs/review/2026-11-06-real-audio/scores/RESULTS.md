# New Light 全曲综合分析记录

状态：脚本、纯 CPU 生命周期检查、真实全曲 GPU 推理和原始输出检查均通过；识别准确性与听感待人工确认。只执行了一次模型推理，无重抽或截短。

固定脚本 [SOURCE-LOCK.json](SOURCE-LOCK.json)，run SHA256 `db54d98bb211d24dbdeecb03e05e948f88e919b7588a41247aaacb0c294c2d8a`。云端不可变目录 `workspace/evaluations/real_audio_20261106/scripts/scores-e8bb19237de6/`。原生默认 full prompts / 单 300 秒窗口、原曲 218.3048 秒、未设置时长上限。无重采样后音频拷回 E、无 DAW 变更。

独立代理只读审查确认全文件与 owned-child guard；依审查补充 supervisor SIGTERM/SIGHUP 的异常清理路径。8 项纯 CPU 检查覆盖：准入拒绝、初始诊断错误、模拟成功、末态诊断错误、清理错误、无效 JSON、子进程退出竞争、终止信号经异常清理后保留收据。全部通过，未调用模型或初始化 CUDA。Recorder `20261106T125334.245695Z-10b6a4ef77`；上传记录 `fe17274dcb`、`0d3e2561cb`、`3949fc1cb1`。

MuScriptor 暂无授权权重，其单独访问步骤见 [ACCESS](ACCESS.md)。本轮未代为登录或同意条款。

## 全曲执行

实际输入 SHA 与上传原件一致。原件 218.3047845805 秒，模型默认 FFmpeg 解码重采样后 218.3047916667 秒，差值约 7 微秒；保留完整输入。单 300 秒窗口，全部任务 prompts 为 `timestamp / downbeat_meter / structure / key / chord_full / melody_full`。2809 / 5120 tokens，未达到上限；720 个事件，最晚事件 217.01 秒；没有 warnings，ABC 导出无错误。最后一个事件早于文件结束本身不等于截短。

机器 NVIDIA RTX 5090 32GB，独立 Python 3.11.14 / Torch 2.8.0+cu128 / CUDA 12.8，BF16，2 CPU 线程。含加载的工作进程测量 12.206 秒，外层守护 14.777 秒，窗口编码解码 7.654 秒。峰值已分配 3,534,086,144 字节、峰值保留 3,617,587,200 字节；ACE 保持驻留，最低空闲 10,710MiB，退出恢复 14,774MiB，ACE 队列前后为空。这是本文件和该机器的一次测量，不外推到所有音乐。

原始输出根目录：

```text
/root/autodl-tmp/emusician/results/evaluations/real_audio_20261106/sheetsage2-20261106T125454Z-75be3531/
```

`transcription/` 内保留 26 个文件，包括 `score.abc`、`transcription.mid`、`melody.mid`、`melody_vocal.mid`、`melody_instrumental.mid`、`chords.mid`，以及 beat/downbeat/key/chord/structure/melody LAB、events JSON/TSV、原始 tokens、playback JSON 和上游 result。所有 MIDI 可解析、音符数值与时间有界：旋律 544 个 note-on（人声388、器乐156）、和弦527个 note-on、联合1071个 note-on。和弦 MIDI 的 note-on 数是展开的和弦音数，不是和弦个数；这些数字也不是识别准确率。此模型提供主旋律/和弦的 lead sheet，不是所有乐器的完整复调分谱；没有生成 PDF 或人工渲染五线谱。

模型原始预测调性为 `G:major`；结构标签从开头 silence/intro，经过 verse/chorus/interlude 到 204.91 秒后的 outro。它们是模型预测，未经过试听或人工真值验证，不能当作确定的音乐学结论；完整边界保留在 `structure.lab`，没有人为改写。

## 证据

- 真实全曲命令/退出记录：`20261106T125452.523291Z-2026784c25`。
- [守护收据](evidence/guard-receipt.json)：执行源码 SHA、开始时间、外层时间、ACE/显存前后状态、退出码。
- [模型收据](evidence/result-receipt.json)：完整输入校验、窗口/事件/上限信息、全部输出文件大小与 SHA。
- 两份小证据复制：`20261106T125545.880547Z-2dee4f4bc9`、`20261106T125551.135667Z-5ca48b5ea7`；原始标签只读核查：`20261106T125555.979928Z-17327b3330`。
- 原始日志：`/root/autodl-tmp/emusician/logs/evaluations/real_audio_20261106/sheetsage2-20261106T125454Z-75be3531.log`。

GPU 已释放，无额外模型重跑。原始音频、谱文件和模型保持云端，本地只留脚本、文档和小型审计收据；未修改 DAW、ACE 服务或模型注册。
