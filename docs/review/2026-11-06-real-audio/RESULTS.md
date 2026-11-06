# 原文件测试结果

四项模型真实推理各完成一次。New Light 为完整218.3048秒，Keyboard为完整279.0310秒；输入上传前后SHA一致，无裁切。文件有效性已检查，听感和识别准确率未人工验收。

| 输入 / 任务 | 模型 | 含加载与文件输出的云端外层时间 | 原始输出 |
|---|---|---:|---|
| New Light / 分离 | SCNet | 27.43秒 | vocals、drums、bass、other，4个完整44.1kHz双声道FLOAT WAV |
| New Light / 和弦 | ChordMini | 4.65秒 | chords.lab、chords.json；147段，时间轴0–218.3048秒 |
| Keyboard / 钢琴转录 | TransKun | 9.52秒 | piano.mid；2178音符、172条CC64/67踏板事件，最后事件276.956秒 |
| New Light / 综合分析 | SheetSage2 | 14.78秒 | ABC、MIDI、旋律/和弦/节拍/强拍/调性/段落LAB、事件/令牌JSON |

机器为单RTX5090（32607MiB），CUDA12.8，各自固定版本的独立环境；ACE服务驻留但队列空，四项串行。上述为守护进程墙钟时间，包含子进程启动、模型加载、推理、保存与检查，不含输入上传、人工准备与后续打包。SCNet/ChordMini/TransKun为Torch2.10.0+cu128，SheetSage2为2.8.0+cu128；实际参数、资源峰值和精确版本见[三项MIR证据](mir/RESULTS.md)及[综合分析证据](scores/RESULTS.md)。这里是离线文件分析，无ASIO缓冲区指标。

SheetSage2单个300秒模型窗口覆盖完整原曲，2809/5120输出tokens，未触顶，无模型warnings，ABC导出无错误。输出720事件，最后事件217.01秒；这是模型结果，不是人工乐谱真值。

## 原始文件

云端结果根目录：`/root/autodl-tmp/emusician/results/evaluations/real_audio_20261106/`。

- `scnet-20261106T125207Z-22e9bebf/data/`：四个原始分轨WAV。
- `chordmini-20261106T125321Z-31c71300/data/`：和弦LAB/JSON。
- `transkun-20261106T125401Z-ed271438/data/piano.mid`：Keyboard完整转录结果。
- `sheetsage2-20261106T125454Z-75be3531/transcription/`：综合分析原始导出。

统一原文件包为该目录的 `NewLight-Keyboard-raw-results.zip`，308,835,729字节（约309MB/294.53MiB）；38文件、逐成员CRC/SHA及整包SHA通过，见[打包凭据](delivery.json)，包内有逐文件SHA清单。用户可在云端JupyterLab文件浏览器定位此目录下载。不改写原始模型输出，不接入DAW，不把模型或新音频下载到E盘。

## 结果边界与记录

- SCNet仅四类分离，不等于八种乐器细分；鼓峰值1.238、other峰值1.040，原始32位浮点保留超出±1的值，没有为试听归一化或写PCM削波。
- ChordMini使用170标签词表，输出数量不代表复杂爵士和弦准确率；本轮未自动平滑标签。
- TransKun是钢琴模型；输入若含其他乐器或残余混音，音符仍可能误判。踏板数据保留，但尚未以人工真值核验。
- SheetSage2的ABC/联合MIDI不是所有乐器的逐轨精确总谱，未生成PDF或额外合成试听。
- 首次SCNet启动在CPU前检因`st_size()`笔误失败，尚未导入Torch/加载模型；修正后才进行唯一一次实际SCNet推理。另一次CPU守护检查SSH连接reset，复核并重跑CPU检查通过。原失败记录保留，没有推理重抽。
- 纯CPU检查覆盖MIR guard 5项、SheetSage2 guard 8项、打包7项；独立代码复核和最终输入/脚本/DAW基线一致性见[VERIFICATION](VERIFICATION.json)。
- 最终本地审查首次把ChordMini CQT收据当作SCNet/TransKun PCM字段读取，触发KeyError（`20261106T125812.368039Z-cca37335eb`）；按实际收据类型修正后通过（`20261106T125828.288522Z-bf61536931`）。只是审查脚本修正，没有重新运行模型。两份本地原文件与上传SHA一致，原257个DAW构建输入未变。

长度预算和MuScriptor申请步骤见[模型说明](MODEL-NOTES.md)，MuScriptor仍未获得访问授权，本轮没有执行该模型。
