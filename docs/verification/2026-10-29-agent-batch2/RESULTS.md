# Agent 第二批验收：DAW 0.8.0 / Agent 0.3

状态：实现和本批自动验收完成；实际桌面、中文输入法与设备听感待人工短测。工作树music-agent-kimi，分支feature/kimi-music-agent，基线55f06b7；不自动合并main。

## 冻结产物

- 122个源码输入，SHA256：347a75c089fe0cd9b17f2e32866ed977004b8aa4b35e5d86a2603cf765cfa64a。
- Release EXE：build/agent-batch2/bin/Release/E-musician.exe。
- EXE SHA256：4fdb7ad2b6d6c6f7ee196e4d8519d452894e22439dcacbd411dee60467b2d190。
- 最终原生构建：[fd1297f0b5](../../builds/20261029T151710.063932Z-fd1297f0b5.json)。Windows/MSVC19.50、C++20、Release、并行2；固定Tracktion/JUCE依赖与WebView2 SDK来源沿用构建记录。
- 最终下列检查均使用同一源码指纹；构建/测试期间源码未变化。完整文件表见[source manifest](source-manifest.json)，Git暂存字节与测试输入的逐文件比对见[index manifest](git-index-source-manifest.json)（仅允许文本换行转换），机器摘要与全部本轮记录索引见[verification summary](verification-summary.json)。

## 实际通过项

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| DAW CTest | 5/5 | [b8dc6e3b44](../../builds/20261029T152204.645151Z-b8dc6e3b44.json) |
| Python编译/选区/协议/状态机/路径边界 | 219项 | [6e56f3dabb](../../builds/20261029T152331.492888Z-6e56f3dabb.json) |
| 既有Agent离线集成 | 通过 | [4e7e157403](../../builds/20261029T152403.888954Z-4e7e157403.json) |
| 第二批真实离线DAW + 合成Provider | 13项 | [报告](synthetic-native.json)、[fcf0f385dd](../../builds/20261029T152408.961071Z-fcf0f385dd.json) |
| 原生侧栏与选择/生命周期 | 24项，内含批次子回归126项 | [原生报告](native-sidebar.json)、[包装报告](native-wrapper.json)、[947cadb13e](../../builds/20261029T152422.361076Z-947cadb13e.json) |
| Windows逻辑AppData真实helper启动/退出 | ready、退出0、自有文件清理、保护文件不变 | [f55990a480](../../builds/20261029T152416.095422Z-f55990a480.json) |
| 合成浏览器UI | 260/340/560侧栏及1280独立页；暂停/阶段/转义/焦点边界；2000新增音符每页50、轮询保留展开与页码 | [326328ea9c](../../builds/20261029T152204.686177Z-326328ea9c.json) |

三步创建、一次Undo清空、Redo恢复原IDs、复制后原片段保护、跨轨移动、裁剪及音符编辑、后一步错误不留下部分结果、保存重开均经原生回读。原生回归在Undo之后实际派发消息，确认Redo仍有效、没有额外Undo动作；只同步调用不能证明这一点。

## 真实模型与模拟边界

| 模型 | 真实请求 | 输入/输出token | 返回模型 | 证据 |
| --- | --- | --- | --- | --- |
| GPT-5-mini | 1 | 2903 / 382 | gpt-5-mini-2025-08-07 | [报告](live-openai.json)、[3e4a286282](../../builds/20261029T152204.662693Z-3e4a286282.json) |
| Kimi K2.6 | 1 | 3090 / 234 | kimi-k2.6 | [报告](live-kimi.json)、[0227b8769f](../../builds/20261029T152220.641959Z-0227b8769f.json) |

每家仅首个“新轨→新片段→四个明确音符”方案由真实模型产生，应用、回读、Undo/Redo在真实离线DAW执行；后续三个编辑方案/拒绝检查由合成Provider驱动。合计仅2次真实模型请求、5993输入/616输出token；未把后续合成调用算作真实模型能力或用量。没有上传用户音乐，未加载插件或连接物理设备。各集成检查其77或78个受保护文件基线不变。

## 失败与修复保留

首次MSVC编译的Identifier重载歧义、嵌套构建目录使legacy复制夹具超过Win32路径限制、非法Content-Length夹具的TCP关闭竞态均已处理，未删减原有断言。新闭环还发现两处产品问题：批次的延后更新切碎Undo；非规范的EM_PROJECT/首次懒建SCENES基线导致Undo后的自动排序清掉Redo。现在提前规范初始/装载基线，并维持批次事务至下一个显式边界；没有修改共享依赖、生产消息泵或按时间禁用撤销。

侧栏另受Windows包文件虚拟化影响，已改逻辑同目录同名校验并拒绝符号链接。安全启动日志只记录阶段/异常类型/栈位置/路径形状，不记录异常内容或能力令牌。发现、审查与修复见[REVIEW](../../review/2026-10-29-agent-batch2/REVIEW.md)，所有失败和中间产物记录都在摘要索引中；原始日志保留在忽略目录build-logs。

## 验收边界

这些是离线工程、合成UI与小规模真实文本模型检查。原生窗口使用离屏测试，焦点事件是合成事件；截图不包含WebView HWND像素。没有新增ASIO长期负载、真实键盘/IME、听感或任意长路径支持结论。新增19种编辑动作不包含音频理解/生成、自动加载插件、模型保存/录音或长期自主任务；带CC的MIDI裁剪暂拒。

人工入口和步骤见[MANUAL-CHECK](../../review/2026-10-29-agent-batch2/MANUAL-CHECK.md)，产品范围见[AGENT_QUICKSTART](../../AGENT_QUICKSTART.md)。
