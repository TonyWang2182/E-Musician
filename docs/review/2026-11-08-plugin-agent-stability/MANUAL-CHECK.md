# 0.13.2 人工短测

请使用 `E:/MusicAgent&DAW/Start E-musician 0.13.2.cmd`，检查标题版本。旧0.13.1入口保留；先用测试工程。本轮自动检查与兼容扫描的真实范围以RESULTS及plugin报告为准，未验证项不当作已通过。

## 1. 添加BM-COZY

1. Settings里确认你日常的M-Audio驱动、采样率及缓冲区；先保持停止。
2. 新建空工程，从Library搜索BM-COZY并添加。应新建/选择MIDI轨、出现装置链，列表刷新后仍可操作。
3. 另做一次Add plugin面板添加。等待状态应结束；不要连续反复点击。
4. 打开插件、选已加载的音色、播放一小段鼓MIDI，再保存重开。此步同时补足可见编辑器、真实ASIO、音色和播放的人工证据。
5. 若仍退出，记录准确时间、入口、音频驱动和当时是否播放，保留工程副本。全清单扫描通过只覆盖报告中的默认状态，不覆盖所有音色/窗口操作。

## 2. M/S/R按钮

轨头应直显M、S、R，不能是省略号。检查默认窗口大小和系统缩放下均清晰；依次切换Mute、Solo、Rec后标签不消失，选中状态可辨。停止后再关闭Rec，避免误录。

## 3. Agent基础混音

1. 打开有三条轨道的工程，把Agent的Scope设为 **Whole project**。
2. 点 **What the assistant can do → Basic mix** 的示例，或发送：

   `Give this project a conservative starting mix. Keep the arrangement and routing intact. Prepare the changes for review; I will audition them.`

3. 应看见当前模型轮次和等待秒数。检查方案里每条轨的修改前后值、理由；未Apply前工程不变。
4. 点Apply后播放试听；点Undo应一次还原本批。当前能力是初始音量/声像/开放原生效果器建议，不是已经听过整首或完成专业母带。
5. 若想验证简单指令，选中一轨，用 **Current selection** 发送：`Lower the selected track by 2 dB. Keep everything else unchanged.`

若报错，记录显示的code：timeout、output_limit、tool_round_limit、authentication或rate_limit分别代表不同原因。扩大等待时间不会增加模型输出预算；遇到预算/轮次限制可先缩小本次轨道范围。更详细步骤及真实API证据见[Agent说明](agent/README.md)。

本轮不需要重跑七个云端模型；模型分工见[清单](MODEL-MAP.md)，云端部署没有变化。
