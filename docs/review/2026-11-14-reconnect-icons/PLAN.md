# 0.13.3：克隆主机重连、工程图标与轨头按钮

2026-11-14。基线912e68f，维护分支fix/reconnect-file-icons-v0133。用户授权更新新SSH端点、连接当前VS Code与DAW，并自行验收模型/音频功能；不重新上传模型，不运行付费生成任务。

## 归属与步骤

1. root：保留旧程序及现有文档/日志，更新SSH别名到用户指定主机，核对克隆部署与协议2服务，检查本地同款隧道；通过Remote-SSH入口打开远程目录并读取连接日志。密码不进入文件、日志或Git。
2. track_button_fix：核对实际轨头主题与DPI字形，修复固定M/S/R标签的省略号，添加有意义的原生渲染检查与截图。
3. project_icon：核对.emproj Windows文件关联、Logo资源和启动参数；实现可回退的当前用户关联注册及安全工程打开路径。不得更改Windows UserChoice保护项，不覆盖用户工程。
4. capability_inventory：根据实际工具与登记清单整理Agent、云端和本地能力表，区分已实现与预留、语言模型与音乐模型。
5. root：独立0.13.3构建/相关回归/截图检查，应用文件关联，打开新版；更新上下文、开发日志与人工短测，不自动合并main。

## 初始发现

- .emproj的当前用户打开命令仍指向E:/E-musician/build/bin/Release/E-musician.exe，且没有DefaultIcon。双击工程启动旧版是持续看到旧按钮样式的具体可能路径；不把它当成所有DPI问题的证明。
- 当前Main.cpp对普通项目文件参数及已运行实例传入的文件未处理，需与图标关联一起补齐，不能只换图标而留下打不开工程的问题。
- 已用原SSH密钥连接用户指定的新克隆主机，目录存在；新端点只在首次加入known_hosts，常规连接仍使用严格主机密钥校验。未使用或保存用户提供的密码。
- Windows内置ssh-keyscan因KEX兼容失败，改由OpenSSH首次受限accept-new取得新端点公钥，旧主机记录不覆盖。后续验证使用StrictHostKeyChecking=yes。

## 验收与边界

每次构建/测试经scripts/dev_reconnect_icons.py记录，原始输出在build-logs，摘要在docs/builds与append-only DEVLOG。SSH认证、部署文件、服务健康、VS Code远端实际加载、DAW连接和模型推理分别记录。本轮不以连通代替推理/听感；不使用computer-use。用户人工检查S/M/R与文件图标/双击、模型效果、声卡与录音。保留0.13.2程序、原先文档变更与未跟踪构建记录。
