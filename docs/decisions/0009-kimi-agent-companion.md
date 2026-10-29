# ADR 0009：Kimi Agent 先作为独立本机助手

- 日期：2026-10-29；状态：首版实施。
- 基线：DAW0.6.1，Agent0.1；独立分支feature/kimi-music-agent。

## 决定

以Python标准库构建单进程协调器和本机HTTP界面，通过现有JSONL启动一个可见DAW。实时引擎不改，继续只有一个权威Tracktion Edit。网页与模型不能直接写Edit；方案由本地编译器转换成有限的公共命令，确认后用一次batch提交。

模型Provider、动作编译器、控制桥、任务循环、UI分别替换。工具只有读取音符及提议方案；没有任意代码、网络和文件工具。初期不把真实音频发送给语言模型，也不宣称实现音频理解。

每个任务从新快照开始。只读音符分页检查前后版本，模型提出的ID和动作严格校验；方案保存原revision，用户确认前后均不刷新它来绕过冲突。应用只消费一次，不对不确定结果自动重试。执行后回读确定性检查。Undo仅针对仍为最近revision的Agent批次，不能选择性撤销后续人工编辑。

## 本机边界

HTTP只绑定127.0.0.1随机端口，Host/Origin检查、会话令牌、限制请求体和线程数、同源CSP。网页只保存临时会话令牌到sessionStorage以支持刷新，API密钥交给Windows DPAPI。模型/地址偏好与密钥分开。网络、文件、JSON和模型工作均不在音频回调中。

关闭页面不退出DAW。显式关闭助手时检查未保存状态；协议失败且DAW仍活着时阻止强制结束，让用户先保存并在原生窗口关闭。模型在途取消只保证停止后续步骤，不能保证取消账单。

## 可测试性与代价

默认测试使用模拟Provider，真实DAW测试通过0.6.1已有control-output-probe离线内存设备模式；不能把普通--offline当作control-stdio的有效隔离参数。真实Kimi使用合成工程单独验收，证据与模拟测试区分。

代价：目前是伴随窗口，不能附着任意已有DAW窗口；只支持受限编辑，不是完整自主创作系统。新对象引用需下一次任务，长任务编排、素材库、音频分析/生成、插件控制和原生侧栏留待后续。

## 官方资料

- [Kimi工具调用](https://platform.kimi.com/docs/guide/use-kimi-api-to-complete-tool-calls)：模型提出工具请求，由应用执行与回传。
- [参数参考](https://platform.kimi.com/docs/api/models-overview)：K2.6可关闭thinking；K2.7不接受关闭thinking；K3使用reasoning_effort。
- [快速开始](https://platform.kimi.com/docs/guide/start-using-kimi-api)：兼容Chat Completions，官方中国站api.moonshot.cn/v1。

本轮真实/models查询确认K2.6可用；不按旧模型列表猜测。程序不自动切换模型或供应商以掩盖调用失败。
