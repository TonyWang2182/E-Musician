# 0.13.2 插件、轨头与Agent修复结果

2026-11-08。基线`1dd6621`，分支`fix/plugin-agent-stability-v0132`。已构建、自动验证并打开最终候选；保留0.13.1原生EXE。没有使用computer-use，没有改云端部署、用户音频素材或已有工程。

## 已实现与证据

| 问题 | 处理与验证 |
| --- | --- |
| 从Library添加插件可能退出 | 修复列表刷新后仍引用旧列表项，以及回调自身被销毁的生命周期错误。PluginPanel在第三方初始化和结果回调后重验SafePointer。四项真实组件生命周期回归通过；原用户COZY事故没有取得相同崩溃栈，不能断言所有诱因都已消除。 |
| M/S/R显示省略号 | 24px按钮原来左右共20px留白，文字区域仅4px；现按控件宽度分配。20/24/28px、开/关/禁用的原生图像以及真实轨头已查看。 |
| 插件扫描误拒 | 排除VST3包内支持DLL，接受且规范化精确Windows VST3标准二进制别名。Groove Agent SE、Padshop、Retrologue在最终版本完整复测通过。 |
| Agent混音不响应 | 增加一次批量读取混音设置/原生效果器的工具，补回已有路由与瞬时峰值摘要，显示轮次、等待秒数和具体错误码。保留GPT-5-mini/high/4096预算，推理调用默认等待120秒，不自动重发收费请求。 |
| 模型能力不清楚 | 发布[实际模型分工](MODEL-MAP.md)和[Agent测试/架构说明](agent/README.md)。没有独立自动混音模型或整曲回听能力；当前基础混音是待确认的参数建议。 |

## 插件检查结论

发现并逐项检查53个模块，覆盖默认目录和已有自定义目录。初轮42个完整通过；最终版本补测COZY及三个Steinberg全部通过，累计**45个通过完整宿主路径：38项非零PCM、7项默认静音**。完整路径是扫描、加载、参数读取、状态保存重开、2秒48kHz立体声PCM16导出、正常退出，不能等同于所有音色、授权、编辑器或实际播放都可用。

**仍有8项未通过，不能承诺“所有插件都能用”：**

- SWAM Double Bass 3、SWAM Viola 3：导出文件生成后控制宿主退出，原因未定位；按精确ID在本机目录暂时禁用，插件和工程状态未删除。显式重扫会解除此标记，但不会修复崩溃。
- Ample Bass A VST2：扫描超过30秒，后续阶段未测试；不能仅凭超时认定不兼容。
- Ample Guitar SJ VST2：保存后重开成为缺失占位，原始状态已保留，原因未定位。
- Keyscape、Omnisphere、MPC Beats64、Kontakt 7 Portable VST2：固定多输出布局与当前单声道/立体声宿主链路不兼容，加载被拒绝。Keyscape、Omnisphere、Kontakt的已安装VST3版本通过本次宿主检查。

最终目录有53项、50项元数据可用、3项标不可用；**元数据可用不是兼容通过**。逐项状态、版本、EXE哈希与限制见[兼容矩阵](plugin/COMPATIBILITY.md)和[插件报告](plugin/RESULTS.md)。

COZY停止状态真实设备加载使用DirectSound/AirPods Pro、44.1kHz、实际2560帧，10秒稳定并正常退出；配置已恢复原字节。M-Audio目前不在线，未强开缺席设备，ASIO验收仍留人工。没有正式性能或听感结论。

## 构建与测试

- 初轮Release `242037a9f0`；初轮CTest `ace113f741`：11/11。初轮组合截图因Graphics延迟提交而全黑，修正编码时机并新增图像内容断言；真实轨头当时已清楚。
- 最终configure `f557218608`，Release `bf75fc0851`，CTest `1ccfefae75`：11/11，113.50秒；115项主题检查和4项生命周期检查通过。Windows Release固定JUCE/Tracktion依赖未升级。
- Agent `b9c850ad3d`：371项通过；最终网页 `2e034e6a40`：2项通过并查看340px截图。
- 真实GPT API `af7989d67c`：三轨三原生效果器基础混音2轮、36.576秒；普通编辑1轮、16.113秒。两项均生成有效待确认方案，无工程修改；共3次API请求，输入22344/输出2636 tokens。是本机当次网络/API测量，不是保证时延。
- 全插件审计 `bd46d280f4`：53项完成，原失败记录保留；最终4项复测 `b52b363926`，隔离 `5fccf26dee`，隔离/监督器测试4/4 `7623e6d098`。
- 启动 `e3757621ad`；最终源码/启动核对 `bb43c47b10`：127项原生输入与最终构建前指纹一致，24项Agent/web输入分别匹配对应测试。旧EXE哈希保持；最终标题0.13.2、窗口响应、助手子进程和匹配本地控制连接正常，见[VERIFICATION.json](VERIFICATION.json)。

初轮插件审计EXE与最终EXE分开保留。最终原生源码相比初轮只变了MainComponent、PluginHost、WorkspaceBrowser及两个相关测试文件；因此全清单初轮与最终针对性复测不能冒称同一个二进制全量测试。全局记录中的source_changed可能包含并行Python/工具/文档工作，独立原生指纹用于核对构建输入。两次配置、两次构建、失败探针和后续修正均在docs/builds和build-logs，不删除失败历史。

## 打开与下一步

双击`E:/MusicAgent&DAW/Start E-musician 0.13.2.cmd`；实际程序在`E:/emusician-analysis-build/bin-0.13.2-final/Release/E-musician.exe`，VS Code入口为`E:/MusicAgent&DAW/E-musician-0.13.2.code-workspace`。当前已经打开，不必重复启动。

按[人工短测](MANUAL-CHECK.md)验证Library/Add plugin添加COZY、实际ASIO播放保存、M/S/R和Agent方案Apply/Undo。下一步优先补插件恢复错误诊断、定位两个SWAM控制宿主退出；固定多输出需要明确的总线映射/保存模型后再开发。完整自动混音另需整曲测量和回听评估，不能用瞬时峰值冒充。仅同步维护分支，不自动合并main。
