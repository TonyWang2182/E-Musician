# MuScriptor 授权后部署

2026-11-06。基线3f8d89f；分支 `feature/muscriptor-authorized-20261106`。

用户提供专用HF read token，继续先前被访问权限阻断的云端部署。不代用户接受模型条款。

最终状态：四步全部完成。官方文件权限、medium权重/config校验、CPU加载、8秒真实GPU转录、catalog与代码证据审查均通过。云端下载503采用官方源RAM中转处理，详见[结果](RESULTS.md)和[验证](VERIFICATION.json)。

1. 隐藏终端输入，经SSH stdin到云端，仅向HF官方验证账号与固定medium权重访问；日志只留状态。授权成功后凭据只保存在MuScriptor私有HF_HOME、权限0600，不进本地文件/Git/日志。
2. 授权成功才下载固定revision medium权重，核对大小/SHA；保留公共源文件及依赖版本。禁止large模型、DAW接入或E盘模型/音频下载。
3. CPU加载通过后，在独占GPU锁及ACE空闲时做明确标为8秒短片段的加载/导出探针，不冒充整曲/准确率验收。
4. 分别更新文件/环境/加载/推理状态、中央catalog和开发文档。失败证据保留，只从实际结果宣布完成。

root拥有授权/下载/汇总；agent_generation拥有隔离加载与短探针；native_generation只读审查，不读取凭据。
