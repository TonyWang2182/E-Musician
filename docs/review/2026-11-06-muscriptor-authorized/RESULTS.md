# MuScriptor medium 授权与云端部署结果

2026-11-06，分支 `feature/muscriptor-authorized-20261106`，基线3f8d89f。状态：官方权重读取权限、文件完整性、CPU加载和一次8秒GPU转录均已验证；尚未接入DAW/Agent，整曲质量未验。

## 权限和部署位置

用户提供的是Hugging Face下载令牌，不是托管推理API。官方固定权重HEAD返回授权后的302，commit、文件大小和LFS SHA与部署锁一致；没有代用户接受条款。凭据仅在云端MuScriptor私有HF_HOME下，目录0700、文件0600，没有写入本地项目、Git、命令参数或开发日志。推理使用另一个离线HF_HOME，不读取下载令牌。

- 权重：`/root/autodl-tmp/emusician/models/muscriptor/model.safetensors`，1,228,144,472字节，SHA256 `ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec`。
- 同目录 `config.json` 为官方126字节medium配置，dim1024 / heads16 / layers24 / card1395；不可省略，否则固定源码可能回退large默认架构。
- 模型：`MuScriptor/muscriptor-medium@f32236969308476e01fd3aae67357de5feb05a2d`；源码 `8a1ef88672cc23c26619adaff37ec48d82c0b906`。
- 环境：`/root/autodl-tmp/emusician/envs/muscriptor`，保持已安装依赖，无新增依赖或全局环境修改。large未下载。
- 直接复用时调用 `TranscriptionModel.load_model(weights_path=Path(权重绝对路径), device='cuda', dtype='float32')`，本地文件模式不会再次在线选取main分支模型。

## 实际验证

| 检查 | 实际结果 |
|---|---|
| CPU加载 | 306,503,680参数，全部位于CPU且为有限值；CUDA未初始化。加载1.353秒 |
| GPU输入 | Keyboard.mp3前8秒，明确短片段，不是整首279秒验收；两个原生5秒块，末块补2秒 |
| GPU输出 | 61个音符事件、61个MIDI note_on；模型输出乐器acoustic_piano；MIDI8秒，无片段末尾后的音符 |
| 时间 | 推理及导出1.297秒；含加载1.799秒；守护流程4.691秒。均不包含权重传输 |
| 资源 | RTX5090 32607MiB；Torch2.10.0+cu128；浮点权重float32、上游GPU autocast；batch1、beam1、无随机采样。CUDA allocated约2.457GB、reserved约2.475GB，实测空闲最低11808MiB |
| 服务共存 | ACE驻留但队列空，GPU串行锁/资源准入/180秒截止，只清理私有子进程组；完成后空闲14774MiB |
| 代码检查 | 8项守护CPU检查及7组二进制接收检查通过；真实运行脚本SHA核验 |

速度是这台机器的一次短探针，不是整曲性能保证。力度100是模型导出的默认值，MIDI120BPM是导出占位，不是测得的演奏力度或节拍；本次未运行额外节拍模型。多乐器转录准确率、复杂混音和整曲表现尚待评测，非商业权重许可仍需遵守。

短探针原始结果留在云端：`/root/autodl-tmp/emusician/results/muscriptor-authorized/gpu-20261106T134439Z-c8402e6a/`，包含8秒fixture、events.json与transcription.mid。CPU证据位于同级 `cpu-20261106T134345Z-a573f284/`。详细收据见[探针记录](probe/RESULTS.md)。

## 网络失败与处理

首次云端认证超时90秒；既有network_turbo恢复公网访问后，认证及模型API、固定文件元数据接口仍分别返回503，不能据此判令牌无效。改用本机连接HF官方源验证后，按1MiB内存块经SSH直接流入云盘，两个端点均验大小与SHA；整个成功中转278.84秒。权重没有在本地磁盘落盘，未向镜像站发送令牌，跨域重定向移除Authorization，签名下载URL不写日志。

中转receiver对不符SHA、超长/过短流、已有不同文件、软链和磁盘余量不足拒绝发布；临时文件哈希通过后原子发布。原失败脚本和记录保留，成功版本见[relay.json](relay.json)。一次等待密钥输入的本地启动在任何凭据输入/网络请求前被取消，以纳入BrokenPipe清理修正；之后仅一次真实中转，未重复模型推理。

中央模型清单已根据真实收据更新，旧MuScriptor清单另存 `deployment-before-authorized.json`。此前所有源码、依赖和其他模型档案SHA保持；没有启动新服务、修改已有ACE或桌面代码，也没有将模型/音频备份到E盘。当前状态见[deployment](deployment.json)和[catalog](catalog.json)。
