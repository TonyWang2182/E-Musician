# 0.3.0 音频片段移动验证

日期：2026-10-26。结果：**本轮片段模型、移动、Undo/Redo、schema 2 保存和旧工程迁移通过限定范围验收。** M1/M2 整体、物理键盘组合键、DPI 矩阵和长期性能不因此关闭。

## 构建与自动验证

最终源码 SHA-256：`8cf293b75671b65c7c698595629cbf22eca6e68421cb8d8af0e90ccf5b00bcc2`。以下四条记录首尾指纹一致，运行期间未改源码。

| 配置 | 构建 | 测试 |
|---|---|---|
| Debug | [通过](../../builds/20261026T134405.577079Z-f403edb0b0.json) | [3/3 CTest 组通过](../../builds/20261026T134414.295789Z-e3fe3d33af.json)，85.46 s |
| Release | [通过](../../builds/20261026T134922.497996Z-8002889c05.json) | [3/3 CTest 组通过](../../builds/20261026T134930.497330Z-bc6c1993bb.json)，83.37 s |

这些时长是整套开发检查用时，不是音频性能基准。两配置均报告原 202 项工程检查、新增 317 项片段检查、核心 84 断言及日志 3 项通过。原始命令日志由各记录指向 build-logs，包含现有 `pwsh.exe` 不在 PATH 的非致命构建后提示；实际构建退出码为 0。

最终补正 Windows 版本资源：固定 JUCE 的生成规则遗漏 Info.txt 依赖，曾使 Explorer 属性仍显示 0.1.0。项目 CMake 已补依赖，两份 EXE 的 FileVersion/ProductVersion 均核实为 0.3.0。此次仅 CMakeLists.txt 改动，应用、UI 与测试源码同原生交互/界面审查时完全一致。下方原生运行及归档截图属于先前指纹 `8337032508478607fe47f05ebe8c10154210227cf2f16501c1ca2475901553e7`；自动 JSON 报告已替换为最终构建的结果。详见 [最终来源对照](final-evidence.json)，不把早先 OS 运行冒记为最终 EXE 的再次操作。

实际 Tracktion 离线渲染覆盖：

- WAV 48 kHz stereo、MP3 CBR 48 kHz stereo、MP3 VBR 44.1 kHz mono。三者分别移到 8 秒，前 8 秒静音，所比较的后段与原音频对应，最大样本差值为 0。
- Undo/Redo 恢复实际声音，保存后独立 EngineSession 重开，比较的全部渲染样本差值为 0；clip/asset ID 和位置保留，Undo 栈不持久化。
- 两个同轨片段共享同一 asset，每代次只复制一次；非零 sourceOffset=0.173 s 的片段对应原始采样区间，移动其中一段不改另一段。
- schema 1 打开不写清单，确定生成 ID，显式保存的旧清单备份逐字节一致，备份加保留素材可恢复旧工程。
- 无效时间、零/坍缩长度、越源区间、悬空引用、重复 ID、过期版本、对象上限和失败保存保留活动工程；源素材字节不变。

证据：[clip-report.json](clip-report.json)、[Release 对照](release-clip-report.json)、[project-report.json](project-report.json)、[engine-report.json](engine-report.json)、[transport-report.json](transport-report.json)。短时 Transport 检查使用 -60 dB；不代替用户听感或长期实时稳定性。

## 界面与实际工程

[arrangement-report.json](arrangement-report.json) 验证真实组件事件：点击/微拖不 seek，不提前提交；释放鼠标只增一次 revision；一步 Undo；Escape 取消；过期手势拒绝；输入草稿不被 refresh/blur 提交；Enter 精确到 8 秒；测试后音乐内容与 dirty 恢复。

- [8 秒移动 1280×800](ui-clip-start8-1280x800.png)、[1000×650](ui-clip-start8-1000x650.png)
- [Separate](ui-separate-1280x800.png)、[空工程](ui-empty-1280x800.png)、[缩放](ui-zoom-1280x800.png)、[拖入反馈](ui-drag-1280x800.png)
- 图中测试正弦音的高密度峰值可呈实心包络，来自真实音频，不是示意波形。

独立界面审查给出 **ship**，范围为上述窗口尺寸、截图和相关交互代码，没有要求重建的 UI 问题；文档中的旧交互说法已由独立 documenter 更新。见 [复核记录](REVIEW.md)。未进行系统 DPI 100/150/200% 矩阵，原有 DESIGN 简要格式/sidecar 漂移未作为副作用修复。

原生 OS 验证只使用 `build/user-review/clips-318586745ea8/CL.emproj` 副本：[运行记录](../../builds/20261026T132042.202787Z-ee95a4cd81.json)。数字键加 Enter 将 Drum 从 0 移到 8；Undo 按钮一次回 0 且 clean，Redo 回 8；保存后清单为 schema 2，旧 schema 1 备份哈希等于原始清单；重新打开保留位置。随后真实鼠标拖至 43.990216 s，一次 Undo 回 8 且 clean。验证未播放用户音乐，窗口已正常关闭。

原生截图 `ui-cl-start8-native.jpg`、`ui-cl-undo-native.jpg`、`ui-cl-drag-native.jpg`、`ui-cl-reopened-native.jpg` 是未经编辑的窗口捕获。因包含用户工程波形，仅保留在本机此目录，不发布到公开源码仓库。

**键盘验收限制：** 自动化注入的 Ctrl+A/粘贴/Ctrl+Z 没有可靠触发；直接数字/Enter及按钮成功。此次不把 Ctrl 组合键写成原生验证通过，物理键盘确认保留待办。固定 JUCE Windows 后端使用 GetAsyncKeyState 读取修饰键，这可能与快速注入有关，但尚未证明原因，不据此认定程序快捷键缺陷。详见 [native-interaction-report.json](native-interaction-report.json)。

新进程还以只读方式打开保存后的 CL 副本：[运行记录](../../builds/20261026T133254.625195Z-3aae4328e0.json)，[报告](preview-report.json)。2 轨，402.370612244898 s，波形完成、dirty=false、playing=false；本机 `ui-project-1280x800.png`、`ui-project-1000x650.png` 均保留 Drum @ 8.000 s。含用户波形的两张预览不发布到公开仓库。

用户原工程在本轮开始前已更新为 schema 1 revision132，包含11文件。本轮使用新基线，验证前后11文件SHA-256一致，没有覆盖用户后来的保存。逐文件保护报告 `project-preservation.json` 含用户素材清单，仅保留本机。

## 失败记录与当前边界

1. [首轮测试失败](../../builds/20261026T130303.386011Z-405f1e4083.json)：夹具恢复使用 JUCE replaceWithText 默认 CRLF，而写器使用 LF。改用原字节恢复并严格核对，不放宽清单保护断言。
2. [第二轮测试失败](../../builds/20261026T130652.416342Z-a8744147e8.json)：像素换算后的 TimeRange 长度为 1.99999999999999978，严格等于 2 的断言失败。区间比较采用1e-9秒容差，严格一次 revision/Undo 保留，报告记录原始数值。

本轮未实现裁剪/分割/跨轨移动、用户 WAV 导出、节拍网格、MIDI、模型、Agent、录音或插件管理。导入/MP3准备/保存仍同步，旧归档与缓存无自动回收。保存后的活动源仍指原路径，重开才绑定归档。64轨/4096对象只是输入保护，不能解释为已经达到性能门槛。
