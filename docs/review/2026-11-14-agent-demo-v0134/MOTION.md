# 演示片头 / 片尾动效

2026-11-14，独立视频资产；不修改 DAW 的启动动画、界面或既有 Logo。

## 设计与计划

- 复用 `assets/brand/yi-yue-shi-logo.png` 用户批准的透明大胡子树乐师，原字节不重绘。依据 `DESIGN.md`、`UiDesign.h` 和品牌 README，使用纸白 `#FEFEFD`、墨色 `#171817`、青绿 `#527D7A`，Segoe UI 无衬线。
- 此次是已固定品牌中的窄范围视频制作，沿用主任务给定开场/片尾与英文文案，不另发新风格选择。应用 Impeccable 的 animate/craft-floor；context 命令已读取现有 PRODUCT/DESIGN。当前显示字体沿用产品规范，未因默认网页规则更换品牌字体。
- 焦点：Logo 固定淡入，沿文字基线的一次横向揭示带出名称；随后介绍与代码网址就位。没有虚构波形、测量、任务进度或功能演示。
- 连续性：片头与片尾共用位置、Logo 和字级，片尾把说明换成邀请语；名称与网址最后保持静止，便于阅读和后期衔接。
- 导出目标：1920×1080，30 fps；开场 8 秒，同时提供 6 秒版对应原 I01；片尾 6 秒对应 O02。静音，不虚构或擅自添加 BGM。透明 VP9 WebM 作为可选叠加版本。
- 原稿开场共 24 秒，本素材只替代 Logo 镜头；其余功能预告仍用真实界面录屏。片尾 6 秒放 03:54–04:00；前 6 秒 O01 留给作品收束。8 秒开场若直接使用，须由剪辑在前 24 秒内部调整两秒，不能额外延长成片。

## 证据状态

已导出并完成文件解码、尺寸、帧率、帧数、时长和透明通道检查；已查看最终 MP4 解码帧及揭示过程的帧图。未操作 DAW、未调用模型/API、未控制用户界面；没有把片头当作真实功能测试。

## 可交付文件

根目录：`E:/MusicAgent&DAW/demo-video/2026-11-14/motion/`。

| 文件 | 实际编码 / 时长 / 帧数 | 用法 |
|---|---|---|
| `opener-1080p30.mp4` | H.264 / 8.000 秒 / 240 帧 | 8 秒开场版本；在原前 24 秒内部调整镜头分配 |
| `opener-6s-1080p30.mp4` | H.264 / 6.000 秒 / 180 帧 | 不改原分镜时，直接放 I01 00:00–00:06 |
| `closer-1080p30.mp4` | H.264 / 6.000 秒 / 180 帧 | O02 03:54–04:00；网址完整静止约 5.18 秒 |
| `opener-1080p30.webm` | VP9 alpha / 8.000 秒 / 240 帧 | 透明叠加版，不含纸白底 |
| `closer-1080p30.webm` | VP9 alpha / 6.000 秒 / 180 帧 | 透明片尾叠加版 |

全部 1920×1080、30/1 fps、无音轨。MP4 为 `yuv420p`，可作为普通视频导入剪辑软件；透明版需剪辑软件支持 VP9 alpha，若不识别就使用纸白 MP4，不当作导出失败。两个透明 WebM 均已通过 `libvpx-vp9` 解码验证：alpha 最小 0、最大 255、角落 RGBA=(0,0,0,0)。

可编辑资料：`motion-config.json`（文字/位置/时序），`source/demo_motion_render.py`（确定性逐帧渲染），`source/opener-poster.svg`、`source/closer-poster.svg`（含原始 Logo 的可编辑排版），`preview.html`（本地预览/播放，提供减少动态选项）。Python 渲染是最终视频的权威来源；浏览器与 SVG 的字体度量可能略有不同。`source/yi-yue-shi-logo.png` 为批准原件的逐字节副本。

## 渲染环境和命令

- Windows 11 build 26200；CPython 3.14.0、Pillow 12.1.1、fontTools 4.62.1。
- 编码器：本机既有 `E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`，FFmpeg 7.1 essentials、libx264 / libvpx-vp9；未安装或分发其二进制。
- 元数据核验：本机既有 `E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe`，2021-08-04 构建。完整视频另用上述 FFmpeg 7.1 全量解码通过。
- 先执行 `--stills-only` 一次，检查海报；完整渲染开始 `2026-11-14T11:29:48.705239Z`，结束 `11:30:23.754714Z`。仅视频生成，不是 DAW 产品构建。

```powershell
python scripts/demo_motion_render.py --out 'E:/MusicAgent&DAW/demo-video/2026-11-14/motion' --ffmpeg 'E:/SUMIN/ABC_Ocean/_tools/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe' --ffprobe 'E:/Users/28712/AppData/Local/Programs/Audio Jam/lib/win32/ffprobe.exe'
```

`RENDER-REPORT.json` 保留每条 FFmpeg/FFprobe 的参数数组、开始/结束时间、退出码、输出哈希及日志路径；`logs/` 保留原始输出。`DURATION-CHECK.json` 逐文件记录期望检查结果。`stills/` 含中间帧、最终编码抽帧、透明解码帧与 `contact-sheet.png`。

## 字体与品牌来源

- Logo SHA-256：`6b94245a35170ebbcab97a1cec0a5d5bde08233f1c8bbe8f671f314fd34005a2`，与 `assets/brand/README.md` 的批准记录一致，输出副本相同；没有改原件。
- Segoe UI / Segoe UI Bold 来自本机 `C:/Windows/Fonts/segoeui.ttf`、`segoeuib.ttf`。嵌入元数据标明 Microsoft supplied font / © Microsoft；**不是开源字体，未复制或分发字体文件**。视频只包含渲染像素，SVG/HTML 使用字体名称引用；在其他机器重渲染需相应已获许可字体，避免把字体文件随项目打包。
- 精确字体路径、SHA、版权和原有许可元数据在 `source/FONT-SOURCES.json`，其中关于 Hebrew layout 的 MIT 段落仅适用于该布局逻辑，不能据此将整款 Segoe UI 声明为 MIT。
- GitHub 文字和链接精确使用 `https://github.com/TonyWang2182/E-Musician`。

## 复核与迭代记录

- 已看两张 1920×1080 海报、最终 H.264 的 3 秒解码帧、0.5/1 秒文字揭示和最终画面接触表。原 Logo、名称、介绍与网址在安全区域内，没有假波形或性能/准确率承诺。
- 5 个文件均完整解码退出 0，1920×1080/30 fps；8 秒=240 帧，6 秒=180 帧；两个 VP9 的 `alpha_mode=1` 且真实 alpha 解码验证通过。音轨不存在。
- 首次附加时长断言误按文件排序写错预期列表，断言失败；改成按文件名映射核验后 5/5 通过，媒体未重渲染、没有视频损坏。保留此说明，不将脚本错误藏成测试从未失败。
- Impeccable 检测器第一次因 Windows CMD 包装器拆分含 `&` 的绝对路径而未读文件；切至输出目录用相对 `preview.html` 重跑，返回 `[]`。没有为其重命名项目或更改用户路径。
- 当前未检查具体剪辑软件的透明导入/色彩管理；用户可直接使用普通 MP4。未制作 BGM、旁白或完整 4 分钟视频，避免把品牌素材误称整片完成。
- 交付压缩包 `E-musician-motion-1080p30.zip`，4,319,040 字节，49 项文件，包含视频、可编辑源、Logo 原件副本、说明和证据，不含字体二进制。ZIP CRC 检查通过。
- 最终通过项目记录器 `python scripts/dev_agent_demo.py command python -c ...` 复核 5 个视频的尺寸/帧率/时长/帧数/SHA、批准 Logo 相同字节、两个透明解码范围、ZIP CRC、渲染器 Python 语法及产物源文件与仓库脚本一致；记录 `docs/builds/20261114T113342.563732Z-331e42938c.json`。没有重跑模型或控制 GUI。
