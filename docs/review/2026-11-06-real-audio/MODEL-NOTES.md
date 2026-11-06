# 长度预算与 MuScriptor 访问

## 长度预算

长度由调用参数、上游实现/上下文约束，以及模型能否稳定完成音乐结构共同决定。上次评测的120秒不是已证明的模型最大能力。

- ACE：本项目 `scripts/cloud/gateway.py` 把请求限制为10–120秒，`ace_worker.py` 将请求时长传给上游 `GenerationParams(duration=...)`；上次测试主动选120秒。这是当前项目网关的边界。
- YuE2：上次测试主动覆盖 semantic 为2700–3000 tokens，约25 tokens/秒，因此上限约120秒；达到3000而未自然结束，结果明确标为截断。
- 固定上游 `YuE@1116bea76032bee5668e5f097294d082fa0b84f0` 的默认 semantic 为200–9000、ABC为32–4096，context为24576。提示词和ABC也占上下文；`sampling.py` 在最小预算前屏蔽 MUSIC_END，之后可自然结束，至最大预算停止。9000约对应360秒预算，不等于本项目已验证六分钟的稳定性/质量。
- 扩大时长应同步客户端、网关、worker、超时与资源准入，再测完整结尾、结构、显存和耗时；不能只修改一个UI数字。

本轮只读源码核查记录：`20261106T124453.788431Z-5e18241738`。未重新生成音乐。

## MuScriptor

官方入口：[medium模型](https://huggingface.co/MuScriptor/muscriptor-medium)、[官方登录说明](https://github.com/muscriptor/muscriptor#huggingface-login-required)。

由用户登录 Hugging Face，在模型页接受 CC BY-NC 4.0 权重条款；官方说明授权自动通过。随后在云端交互式 `hf auth login`，使用同账号具备该模型读取权限的 read 或 fine-grained token，不需要 write 权限。不要把 token 写入仓库、日志、命令参数或聊天。此前匿名401仅证明当时未授权，不能推断模型不可用。

当前公共源码/环境已就绪，权重仍未授权、未下载、未执行推理。本轮不代用户接受条款。商业用途需另行获得合适授权，不能把非商业权重默认作为产品商业许可。
