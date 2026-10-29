# ADR0010：内嵌Agent、选择范围与模型适配

日期2026-10-29，状态已实施并通过本批自动验证，物理输入和播放短测待用户。证据见[RESULTS](../verification/2026-10-29-agent-sidebar/RESULTS.md)。

DAW拥有AgentService，按首次打开侧栏启动本机Python辅助进程，使用每次启动独立令牌认证的loopback JSONL连接。旧stdio入口保留兼容，嵌入模式不使用EOF退出DAW的机制。WebView2只载入本机受控页面；侧栏收起保留任务与文本，停止可见状态轮询。断开、重启、退出只清理自己拥有的助手。

EngineSession继续拥有唯一Edit。选择是带独立selection_revision的只读视图信息，不增加音乐revision或Undo。GUI在控制请求执行前同步当前选择；切换聊天保留最后音乐焦点。方案捕获project/revision/selection，确认时防止过期选择；范围由本地执行层限制，不能依赖模型遵守提示词。

模型工厂将厂商API转换为统一message/tool/usage协议；密钥按provider隔离。OpenAI使用Responses并保存工具轮次所需reasoning items；不上传实际用户音频。能力未实现/未配置与已经真实验证必须分开显示。无自动跨厂商回退，无自动充值或无限付费重试。

首次接入增加WebView2依赖与内存开销，需要独立验收。按需启动、隐藏停止轮询、绑定范围的IPC和现有视口绘制维持性能边界；物理设备听感由用户确认。
