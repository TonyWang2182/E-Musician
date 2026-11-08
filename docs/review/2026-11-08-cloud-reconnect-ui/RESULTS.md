# 0.13.1：克隆云端重连、弹出界面与英文Agent

2026-11-08。实现、两次Release构建、自动检查与七模型短段整链通过；真实鼠标/DPI、ASIO与音乐质量待人工验收。分支`fix/cloud-reconnect-ui-v0131`，基线`12aa587`。代码同步状态见[PUBLISH](PUBLISH.md)。

新版已打开：`E:/emusician-analysis-build/bin-0.13.1/Release/E-musician.exe`，标题0.13.1，窗口响应，语言en，DAW内嵌Agent辅助进程已完成认证连接。此为启动/连接证据，不代替音频听感。[启动收据](OPENED.json)。以后双击`E:/MusicAgent&DAW/Start E-musician 0.13.1.cmd`；本地VS Code入口`E:/MusicAgent&DAW/E-musician-0.13.1.code-workspace`，任务使用`scripts/dev_reconnect.py`并写开发记录。旧0.13.0/0.12.1/0.12.0 EXE哈希未改变，旧入口与用户工程保留。

## 实际改动

- SSH别名`emusician-autodl`现在指向`root@connect.bjb2.seetacloud.com:44800`。使用原密钥登录；密码未写入源码或日志。旧配置保留于E盘connection/history/20261108T045751Z-44800。VS Code窗口未自动切换，连接方法见[SSH-WORKSPACE](SSH-WORKSPACE.md)。
- 复用云端`/root/autodl-tmp/emusician`、九套环境和固定release `ed7d6a920487a651c988`。克隆机缺少系统FFmpeg，已补装FFmpeg/libsndfile/libgomp后启动原计算服务。协议仍为2、远端loopback18082；没有从E盘恢复或上传模型。最终两个数据库完整性通过、活动任务为0、七项能力可用。[环境与服务](CLOUD-FINAL.json) / [本地同款隧道](LOCAL-CONNECTION.json)。
- 应用默认主题统一File/右键菜单、子菜单、下拉、设备控件、分析Options以及关闭保存/覆盖确认。浅纸面、细线、青绿焦点、命令与快捷键分列；Save/Discard/Cancel结果ID、Esc与异步保存逻辑保持。Windows原生文件选择器和第三方插件自身窗口不重绘。
- Agent网页向后端传UI语言；新任务系统指令约束模型回答语言，运行器的进度、计划与错误投影为当前语言。用户轨名、歌词、输入、模型已有内容和命令参数保留，不按字符过滤删中文。原有授权范围、一次接受、Undo与工程权威状态未改变。[架构决策](../../decisions/2026-11-08-shared-popup-agent-locale.md)。

## 构建、测试与真实证据

| 检查 | 结果与范围 | 记录 |
|---|---|---|
| 独立Release配置/初次构建 | 成功；bin-0.13.1，未覆盖旧EXE | eae6053e0c / bddeadc966 |
| 原生CTest | 11/11通过，包括工程、DSP、控制输出隔离、工作区 | 204f8502af |
| Agent Python | 360项通过；最终文案补齐后9项本地化针对复测通过 | d5afa69325 / f7af3f2a14 |
| 英文Agent真实API | GPT-5-mini两次；英文/中文问题都按English界面答复正确120 BPM与4/4；只读合成工程、没有编辑或音乐推理 | 0cd43a65a0 / [ENGLISH-LIVE](ENGLISH-LIVE.json) |
| Agent网页 | 初次4项通过；夹具改为经过真实locale投影后最终4项通过并逐图查看；含用户中文名称保留 | 6a359f9bda / a8c3d6b6f2 |
| 原生弹出组件 | 40项通过，中英文保存、菜单、Options截图检查；原按钮语义保留 | [组件报告](popup-style-report.json) |
| 测试夹具文字修正后构建 | 成功；只将测试菜单的UTF8省略号改ASCII，消除夹具乱码；最终workspace针对复测通过 | bb66b52f16 / daa95056f5 |
| 七模型真实整链 | 全部通过，见下表；实际原生公开命令/云模型/Agent授权与方案编译器 | 72ec595616 / [完整报告](CLOUD-END-TO-END.json) |
| 最终源码/产物审查 | 126个其他原生输入不变；唯一原生差异精确为上述测试字符串；旧三个EXE保持；最终SHA已记录 | 3a05f5a694 / [VERIFICATION](VERIFICATION.json) |

记录文件位于`docs/builds/`，每项含实际命令、配置、起止时间和原始日志路径。最终EXE SHA-256：`77d4bcbde825d63f04cd0debc1700deeca0039ff45f4803d799a078fbab20091`。七模型测试使用初次构建的冻结副本；之后只改了测试夹具显示字符串，最终构建复测工作区，没有重复付费模型推理。`verify_reconnect_release.py`核对这一精确差异；不冒称七模型跑在与最终EXE字节完全相同的文件上。

## 新主机七模型结果

实际机器RTX5090 32607MiB、驱动580.105.08；单重任务串行。MIR取New Light/Keyboard的8秒片段，生成请求12秒；原生宿主用离线测试设备，导出48kHz/16-bit，不使用物理ASIO，实际硬件缓冲区不适用。下表为公开命令启动到候选就绪的外层时间，包含上传、加载/文件检查、推理、回传及轮询；不是纯模型速度或实时音频性能。

| 模型 | 候选就绪外层时间 | 本次真实输出 |
|---|---:|---|
| SCNet | 19.27s | vocals/drums/bass/other四轨 |
| TransKun | 11.83s | 62音符、14控制事件、1程序事件 |
| ChordMini | 11.80s | 6段和弦标签 |
| MuScriptor | 11.57s | 此钢琴片段为1轨、61音符；不据此证明多乐器准确率 |
| SheetSage2 | 18.10s | 16音符、5和弦、17拍点、2注释 |
| ACE-Step 1.5 XL Turbo | 70.22s | 12.000s音频 |
| YuE2 | 75.68s | 11.9987s音频；保留预算/截断信息，不当自然结尾 |

每个模型均检查：候选未修改工程→经Agent生产方案编译器接受一次→重复接受不重复入轨→单次Undo/Redo→保存→禁用云端后重开→音乐状态一致→本地音频资产离线渲染非静音。转录项目保留原音频，因此离线渲染不等于新MIDI已挂乐器或其声音已验。此轮Agent请求为确定性夹具，真实LLM语言探针另列；不把固定请求当自然语言理解率。

七项总流程约306.85s。可复查项目和结果位于`E:/MusicAgent&DAW/cloud-inference/experiments/hybrid-clone-v0131-20261108/`，模型权重仍在云端。云端服务保持在线；没有关闭/释放任何实例，也没有验证夸克归档的完整可恢复性。

## 失败、修正与剩余验收

保留了首次服务未启动导致curl失败（baa1a5db63）、克隆检查发现缺FFmpeg（cac8ec69ec）、一次未正确引用含`&`路径的PowerShell前检失败（e55075043e；未发出API请求）。补装依赖与安全引用后通过。两次MSBuild均退出0，但工具链仍输出找不到可选`pwsh.exe`的警告；EXE存在、后续测试和启动通过，本轮没有更改全机工具链。

首次截图发现的是测试夹具省略号ASCII构造误解，已修正并重新构建/查看；生产菜单已有UTF8文字路径。未发现需要扩大到音频/工程逻辑的改动。

下一步按[模型与界面人工清单](MODEL-TESTS.md)试听与操作，先8–20秒再整曲。尤其确认ASIO共存、长任务、关闭时Save/Discard/Cancel、物理DPI、英文模型方案。英文产品视频按[7分50秒脚本](DEMO-SCRIPT.md)拍摄，等待可剪辑但须标注；不能用本轮短测宣称全曲准确、无损拉伸、零延迟或任意插件兼容。
