# 0.5.1 Keyscape 修复候选与人工验收

状态：2026-10-27，0.5.1 Release候选已构建，相关自动检查通过，已交用户人工复测；Keyscape无声及Arm/Monitor退出尚未确认修复。

## 已知证据

- 用户新建MIDI轨加载Keyscape，选择MIDI输入后切Arm/Monitor会卡顿退出。
- Windows今日4次WER记录均为0.5.0 Release、Keyscape.vst3 1.5.0.0、c0000005、模块偏移0x782693；最新转储的ASIO音频线程在Keyscape内向0x20地址写入。不是下载/构建未完成的证据。
- 原始转储位于本机CrashDumps，只读分析，未复制进版本管理；.cache/v051保存调试输出。Release旧版本没有PDB，所以不宣称全部宿主帧已符号化。
- 从最新转储恢复ProcessData：256 samples、0 audio inputs、9 output buses；堆上的完整输出数组未包含在minidump中，无法凭该转储证明具体哪个bus被误用。一次读取缺失内存的诊断命令失败已保留记录，不是应用新崩溃。
- 固定JUCE的HostBufferMapper为inactive bus保留channel数量而传null样本指针；PluginHost只启用主输出。VST3规格允许inactive的实际样本地址为空，因此这是兼容性候选，不是已证明的宿主违规。

## 用户人工对照

1. 不加载插件，新建MIDI片段、打开钢琴卷帘、双击写音符：用户确认通过。
2. 有音符的片段加载Keyscape，不选MIDI输入、不切Arm/Monitor，播放：用户报告不退出但无声。
3. Keyscape界面自己的琴键：用户报告有反应但无声。
4. 同工程导入已知有声WAV/MP3：用户确认有声，并已关闭DAW。

## 本次候选

- JUCE VST3输入/输出mapper在prepare时为inactive通道分配独立float/double存储，process只清零/复用。附加输出仍inactive，不启用、不混入主输出，不在音频回调分配内存。
- 超过setupProcessing块上限的缓冲显式拒绝，禁止scratch溢出；默认mapper调用保持既有行为，实际宿主传入明确最大块长。
- 新增实际mapper回归：active/inactive/active顺序、独立通道、float/double、模拟插件向inactive写入、隔离/清零/指针复用、变长块和超长拒绝。
- 版本0.5.1；优化Release开启PDB且显式保留OPT:REF/ICF。旧0.5程序留在.cache/v051/baseline-0.5.0.exe。
- 仅Release相关检查与用户复测；本次不重跑30分钟长跑/四插件全矩阵，不使用computer-use。

主因仍需新旧行为对照。此前只读审查还发现MIDI启用的异步更新边界；本次先不混入这一不同修复，以便判断缓冲候选是否解决用户现象。

规格依据：[Steinberg AudioBusBuffers](https://steinbergmedia.github.io/vst3_doc/vstinterfaces/structSteinberg_1_1Vst_1_1AudioBusBuffers.html)。补丁以精确源/补丁/结果哈希纳入原manifest，不直接提交_deps。

## 构建与相关自动检查

- [Release构建](../../builds/20261027T083742.671390Z-8ab8e6f706.json)成功。首次编译因新增测试缺少内部FlagCache头文件失败，补齐依赖后构建成功；原失败记录保留。
- [首次CTest](../../builds/20261027T083801.599393Z-21ba7d3201.json)4/5通过：日志、核心契约、引擎集成、控制输出隔离通过；补丁契约仍为旧两文件白名单。仅将其同步为正式清单中的四个确切文件后，[定向重跑](../../builds/20261027T084201.342150Z-3dee0ba2c4.json)1/1通过。不是单次完整5/5，也未声称本候选Debug已验证。
- 应用集成包含生产125项，新增实际JUCE mapper回归；其余工程/片段/存储/工作台/DAW报告均passed。完整性与精简报告见[candidate-summary.json](candidate-summary.json)。未在本候选重跑真实第三方插件矩阵或长跑，不沿用旧版本结果作为新测量。
- 应用构建源码指纹084b4e91；当前指纹a67e1d7f，唯一差异为Python补丁契约测试。EXE SHA-256为f7e44157b69432a02f097823a158e6e300215401c7c4cbf96289056b7754899e；匹配PDB在本地build/bin/Release，未上传。
- 一次只读复核确认四文件精确白名单、哈希和未知修改拒绝仍保留。无音频回调分配来自代码审查，不是运行时分配计数测量。

## 人工复测交接

已通知用户启动原路径build/bin/Release/E-musician.exe（0.5.1），新建测试工程，加载Keyscape钢琴音色，先点插件琴键，再选择MIDI输入、切换一次Arm/Monitor并弹键盘；分别报告声音和稳定性。不操作用户GUI，不再次启动自动音频测试。若退出，保留匹配Release/PDB分析新转储；若只无声，再区分插件主输出、监听与MIDI路由。收到结果前，不将候选标为已修复或合并为已验收交付。
