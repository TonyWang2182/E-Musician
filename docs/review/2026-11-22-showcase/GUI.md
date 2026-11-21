# 实际界面验证与拍摄记录

日期：2026-11-22（Asia/Shanghai）。所有操作限定在自行启动的 Showcase 进程、该进程的 UI Automation 控件以及显式启用的 loopback WebView 调试端口。没有 computer-use、Jianying、SSH 或模型 API。截图为实际窗口像素，不重画应用内容。捕获录像本身无声，首剪声音分别来自同一历史候选或已验证的原生音频导出；不把后期配音当实时录音。

主回执：[D1](../../builds/20261121T171331.727299Z-d387978a89.json)、[D2/D3](../../builds/20261121T173006.695521Z-56d6c0b0d2.json)。逐次请求/结果、截图/录像和带哈希的 capture-receipt 保存在交付目录 `captures/workflow-final`、`captures/workflow-d2`。正常退出仅说明捕获程序完成，个别动作失败仍保留在逐项回执中，不写成全动作通过。

## 已观察到的结果

- 实际窗口标题为 `E-musician - Audio Workspace`，Agent 页面英文，独立本地连接。界面只保留指令、阶段、试听、结果、Apply changes 与 Undo 等主要操作；真实 YuE 截断提示保留。
- YuE Preview 返回 `Previewing`，之后实际加入一条音频轨；ACE Preview/Stop 和 Apply 调用成功，新增第二条。人工听感没有替用户验收。
- 经共享工程命令删除 YuE，保留 ACE 原名；SCNet 应用后原曲加四条 stems。原曲静音，按 drums → bass → other → vocals 累计 Solo 截图与状态核对。
- New Light 中先由 Agent 产生 ChordMini 候选，再通过 Analysis / Recent analyses / Chords 1 / Add chord track 的真实控件应用。15 个和弦区间显示在时间线上。
- Beat/Warp 的 Apply 完成后实际回读：Warp enabled，source BPM 约125，target BPM120，源起点0.25秒、长度25秒；原和弦标签随相同映射移动。Source 控件与真实播放录像已捕获。
- Tea for Two 的 TransKun 候选 Apply 后新增 MIDI / Transcription，132 notes；实际 Edit MIDI notes 控件打开卷帘。Keyscape 实际窗口与 MIDI-only 导出来自独立已记录的 D3 素材，详见 AUDIO.md。

此次 GUI 的音频设备回读为44.1kHz /441样本，物理输出可用；GUI内存/DSP/xrun显示只是现场读数，不是性能基准，也不是麦克风输入或听感证据。

## 排除与保护

- Windows偶尔拒绝激活捕获窗口，工具明确失败并停止该次动作，不向其他程序发送输入。失败录像及存在错误/加载状态的画面不纳入最终镜头清单；成功帧不能证明被拒绝的动作成功。
- D1长会话中，临时New Light副本出现不在捕获请求清单内的FX音频导入；其新增内容先保存到 `captures/projects/New-Light-extra-edit-preserved.emproj`，随后用干净副本/新会话继续。未删除未知编辑，也未改用户原工程。
- 旧和弦结果在重开/另存后的来源检查中被拒绝；新请求实际新建任务且ready。选择旧“Chords 2”并非重试管线失效。拍摄时应在任务就绪后关闭/重开 Recent analyses，选择**最新**结果；干净D2会话只有 Chords 1。
- Demo4和部分D3镜头为真实静态UI的后期推近/并排，不冒充连续操作录屏。Sax位置使用抽象可替换画面，不声称已经拍到真人表演或麦克风波形。

## 网页与构建入口回归

普通Agent中英任务流程检查通过：[原始记录](../../builds/20261121T172444.155223Z-3cfe9c1fda.json)；包括等待、就绪、应用、完成、错误、旧方案和候选选择。JavaScript语法与捕获/组装Python语法检查均有独立回执。新增4项构建守卫测试通过：[记录](../../builds/20261121T173455.301983Z-c798fac5d3.json)，错误输出目录/模式不执行编译，旧0.13.6配置显式关闭Showcase。守卫测试使用模拟Recorder，没有重编或覆盖原版。
