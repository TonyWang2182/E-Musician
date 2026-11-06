# MuScriptor 权重访问

2026-11-06 核对官方模型页与 README。当前云端已有独立源码/环境，但尚无授权权重；不能把环境准备当作模型可用。

1. 在浏览器登录自己的 Hugging Face 账号，打开 [MuScriptor medium 模型页](https://huggingface.co/MuScriptor/muscriptor-medium)，阅读并自行接受页面条款。官方 [登录说明](https://github.com/muscriptor/muscriptor#huggingface-login-required) 明确写明接受后自动授权。该授权属于登录的个人账号。
2. 到 [Access Tokens](https://huggingface.co/settings/tokens) 创建 `read` 令牌，或只允许读取该模型的 fine-grained 令牌。下载不需要 write 权限。不要把令牌发在聊天或写进 Git。
3. 在已连接这台云服务器的 VS Code Remote SSH / Jupyter 终端运行下面命令，按交互提示登录。CLI 已在现有环境内，已只读验证帮助，无需重新安装。

```bash
HF_HOME=/root/autodl-tmp/emusician/workspace/models/muscriptor/hf \
  /root/autodl-tmp/emusician/envs/muscriptor/bin/hf auth login --no-add-to-git-credential
```

4. 完成后才开始云端权重下载、哈希校验和真实加载验证。本次未代替用户接受条款、登录、搜寻令牌或重试受限权重下载。

准备下载的精确文件为 `MuScriptor/muscriptor-medium@f32236969308476e01fd3aae67357de5feb05a2d/model.safetensors`，1,228,144,472 字节，SHA256 `ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec`。云端保留目录为 `models/muscriptor/`。已有源码固定 `8a1ef88672cc23c26619adaff37ec48d82c0b906`；官方 README 当前功能可能比该部署版本更新，不据此宣称已安装新功能。

模型权重采用 CC BY-NC 4.0 并附模型页条款，代码为 MIT；正式产品商业部署需要另行处理许可。MuScriptor 是多乐器转录模型，但不输出真实力度，密集混音和音色分辨仍可能出错。无需等待它授权才运行已经部署的 SheetSage2。

参考：[官方 gated 模型说明](https://huggingface.co/docs/hub/models-gated)、[访问令牌权限](https://huggingface.co/docs/hub/security-tokens)、[CLI](https://huggingface.co/docs/huggingface_hub/guides/cli)。
