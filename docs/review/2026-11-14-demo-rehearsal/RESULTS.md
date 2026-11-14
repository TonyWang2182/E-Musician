# 0.13.3 演示操作验证

2026-11-14。用户要可复制提示词、具体步骤并验证可用。本轮沿用0.13.3，不改产品代码、不重新构建、不操作用户正在打开的GUI或工程。

## 必须先区分的两个结果

**ACE原样英文指令已通过真实GPT完整链路；其余五条自然语言指令尚未完成实测。** YuE2首次GPT调用返回HTTP429，音乐任务启动数0。随后一次小请求（64输出token上限、无工具）得到允许列表内的`error.type=insufficient_quota`。停止继续调用GPT，未自动换账户或语言模型。原始失败与诊断收据保留；诊断只证明这次小请求的额度拒绝，不能还原之前已丢弃的错误正文。

其余音乐任务改为显式`--direct-pipeline`：结构化参数→生产授权/任务接口→真实模型→候选/方案→明确接受→Undo/Redo→保存重开。没有假Provider或模拟音乐数据。这能验证模型/工程管线，**不能算作英文提示词、鼠标交互或听感验收**。

## 本轮逐项结果

| 案例 | 实际输入与输出 | 自动检查结果 | 英文提示词状态 |
|---|---|---|---|
| D1-ACE | 90 BPM、4/4、含独立歌词字段；32秒/48kHz/立体声音频 | GPT直接start_generation，无BPM追问；2次语言调用、1次音乐生成；候选、Apply、Undo/Redo、保存重开通过 | 本次原样输入已通过一次 |
| D1-YuE2 | 与ACE实际音乐brief/lyrics相同，32秒预算；实际31.9987秒/48kHz/立体声 | 结构化模型管线通过；完成标记`token_budget`截断 | GPT入口被额度拒绝，待补验 |
| D1-SCNet | 接受并保存的ACE音频，32秒，四声部 | 四声部真实音频、保留来源/新增4轨、撤销/保存重开通过 | 未调用，待额度恢复补验 |
| D2-Chords | New Light第60–84秒；15个和弦区段 | 真实ChordMini、和弦轨/撤销/保存重开通过 | 未调用，待额度恢复补验 |
| D2-Warp | 上述已含和弦的工程；本地Beat This检测约125 BPM、4/4、首小节拍1.68秒 | 固定比例保音高Warp至120 BPM，ratio0.96，clip起点0.25秒/长度25秒；15区段映射、撤销/保存重开通过 | 未调用，待额度恢复补验 |
| D3-Piano | Tea for Two已分离钢琴第20–36秒；132音符、17控制事件、1 program-change | 真实TransKun、可编辑MIDI、控制事件及保存重开通过 | 未调用，待额度恢复补验 |
| D4 | 鼓组、Sampler、指定插件、真实MIDI/麦克风录制 | 本轮只核对操作入口；设备、声音和连续录屏由用户验收 | 原脚本设计为手动展示，无Agent代录声明 |

生成长度只证明实际音频时长。YuE2明确触达token预算，不能宣称自然结束或完整64小节；ACE结束原因unknown。人声是否符合要求、和弦准确率、音符漏检/误检、分离串音、Warp音质均未试听验收。实际控制事件为16个CC64、1个CC67，另有1个program-change；不统称为17次踏板动作。

六项均完成。已保存工程见[E盘入口](<E:/MusicAgent&DAW/demo-video/2026-11-14/OPEN-FIRST.md>)；后续新界面迭代须另记，不能覆盖本批0.13.3证据。

## 验证条件

- 原生EXE：`E:/emusician-analysis-build/bin-0.13.3/Release/E-musician.exe`；SHA256 `90c7a476618bccc01e581b47d46b3880422143b8382e000bb915e94108c9baa3`。
- 语言模型：现有OpenAI `gpt-5-mini` / high。ACE回执为`gpt-5-mini-2025-08-07`，总23,010输入/1,880输出token；不是价格或账单承诺。
- 音乐计算：已连接克隆实例上的ACE、YuE2、SCNet、ChordMini、TransKun；Beat This为本地已注册`beat-this-final0`。模型版本/候选hash见[收据摘要](RECEIPTS.json)与对应完整本地report。
- 每案例隔离EXE/工程，离线设备测试控制接口；不是物理ASIO缓冲/CPU延迟测试。界面选择未伪造，Agent案例使用Whole project、唯一英文来源轨名。每音乐任务最多一次，不重试推理；失败语言任务保留。
- 检查候选生成不改工程、接受后版本递增一次、轨道/和弦/音符及Warp回读、一次Undo/Redo、保存重开、已保存音频实际存在与hash。指定源文件和少量设置前后hash核对。
- New Light和Tea钢琴独立摘段，原件未改，见[SOURCES.json](SOURCES.json)。全量用户磁盘/工程没有做枚举式保护测试；用户GUI和输入设备未被控制。
- 云端完成推理后可与下一任务的下载阶段重叠；本地Beat This与云端TransKun并行。记录墙钟时间包含网络/排队/进程启动，不能拿来作模型性能排名。

## 交付与下一步

1. [操作稿：六条英文提示词、点击步骤、D4录音流程](../../demo/2026-11-14-demo-operations.md)。TXT位于`E:/MusicAgent&DAW/demo-video/2026-11-14/prompts/`，与cases逐字一致。
2. [手动模型入口](MANUAL-FALLBACK.md)：无需语言API，但仍需模型/算力可用；此文档的鼠标路径为源码核查，未做实际GUI点击验证。特别标注Cloud和弦切Beats前先改Local的路由遗留问题，本轮未修产品代码。
3. [原4分钟中英分镜](../../demo/2026-11-12-four-minute-demo.md)：继续用于镜头/旁白/剪辑，新操作稿覆盖旧选区与32秒预算步骤。
4. 恢复OpenAI API可用性后，用相同来源副本对YuE2、SCNet、ChordMini、Warp、TransKun五条原样提示词补验；不能以本轮direct-pipeline通过替代该步骤。
5. 用户按操作稿完成Preview试听、GUI/DPI、指定VST3、键盘/麦克风、ASIO录屏声音和实际连续take验收，再录成片。模型计算等待剪辑注明Processing time shortened；旧结果补拍标Previously generated/analyzed result。

本轮开发/检查记录在`docs/builds/20261114T1053*`之后的demo-rehearsal-check收据，原始日志在忽略目录build-logs；[计划](PLAN.md)、[流程审查](FLOW-AUDIT.md)、[验证设计](VALIDATION-DESIGN.md)与源码一并保留。不自动合并main。
