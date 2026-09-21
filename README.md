# ScreenLingo 屏幕翻译

当前源码：识别固定使用 RapidOCR；翻译可选有道、百度、Google 或 **DeepSeek-V4.1-Flash**。DeepSeek 默认关闭思考，支持上下文和严格 JSON 块映射，详见 [DeepSeek 设置](DEEPSEEK.md)。原来的 GLM-OCR 下载入口已移除。下述 1.2 ZIP 是旧版，不包含最新源码功能。

漫画可在首选项 → 识别与显示 → 文字排版，选择 **日文漫画竖排（上→下，右→左）**。应用后重新框选，建议选单个分镜或气泡。常规横排仍为默认设置。

Snipaste 式 Windows 翻译工具：设置窗口只负责配置；按热键框选游戏聊天窗后，在原文字位置先画阴影遮罩，再显示中文译文。游戏和翻译层共同存在，鼠标、键盘继续操作游戏。

## 快速开始

打包版：解压 `dist/ScreenLingo-1.2-Windows-x64.zip` 到固定目录，双击 `ScreenLingo.exe`，无需 Python，已含 OCR 模型。保留整个 `_internal` 目录。首次右键托盘 → 首选项，填写所选服务的 APPID 和密钥并应用。可勾选 Windows 账户加密保存密钥、登录 Windows 自动启动；自启动默认关闭。删除程序前先取消自启动，移动目录后重新应用自启动设置。本版默认 RapidOCR＋有道，新增背景融合及可选 GLM，详见 [RELEASE_1.2.md](RELEASE_1.2.md)。已有用户保留原翻译源。

双击 **`start.bat`**。本目录已经安装好开发环境及日韩识别模型。

在其他电脑需要 Windows 10 2004+ / Windows 11、Python 3.11+（64 位）及能访问 Google 的网络。启动脚本自动安装依赖；首次翻译会下载并校验两个识别模型。Windows 11 已实测，Windows 10 兼容路径尚未实机验证。

1. 启动后显示托盘图标，后台预热模型与 Google 连接。右键图标 → **首选项…**，打开简洁中文设置。
2. 选择翻译工具、原文语言（自动或固定日 / 英 / 韩）和译文语言，点击**应用**，关闭设置。固定语言通常更快；混合语种请选择自动识别。
3. 将游戏切换至无边框或窗口模式。按 **`Ctrl+T`**，拖动鼠标框选聊天内容。
4. 框选完成后自动恢复游戏焦点，原位置出现阴影遮罩及译文。新聊天到来时自动更新。
5. 按 **`Esc`** 清除覆盖层并结束翻译。之后 Esc 恢复游戏原本的作用。

| 默认热键 | 功能 |
| --- | --- |
| `Ctrl+T` | 框选窗口内的区域并实时翻译 |
| `Ctrl+Shift+T` | 翻译鼠标所在显示器的整个屏幕 |
| `Esc` | 退出当前翻译 / 取消框选 |

三个热键均可修改。退出键在目标区域可见且翻译开启时注册；区域被遮挡或窗口最小化时隐藏覆盖层并释放退出键。全屏模式的退出键在该次翻译结束前保持有效。

全局 Ctrl+T 会占用浏览器的同名快捷键，可改为 Ctrl+Alt+T。已被其他程序占用的热键会提示冲突。设置修改在下一次翻译时生效；热键保存后立即生效。

设置面板不展示翻译正文，保留最近处理耗时供调试。双击托盘图标返回设置；右键托盘可启动、停止翻译、切换原文语言或退出程序。关闭设置窗口会收起到托盘，右键 → **退出** 才结束程序。更新后需先退出旧版本，再双击 start.bat。

## 窗口采集与覆盖

- **框选模式**：关闭选择器前锁定原窗口。确认区域可见且覆盖层可排除时，首帧直接采集框选画面以缩短启动时间；实时阶段使用 Windows Graphics Capture 按目标 HWND 采集框选区域。被遮挡时首帧也改用窗口采集。选择器和译文层都排除在屏幕采集之外。
- **全屏模式**：采集当前显示器，通过 `WDA_EXCLUDEFROMCAPTURE` 排除覆盖层。该模式与绑定窗口模式不同。
- 覆盖层始终置顶、鼠标穿透、不获取键盘焦点。先对区域轻度变暗，再在原文行位置绘制可调深度的阴影，最后画白色译文。
- 目标窗口移动时跟随；目标区域被遮挡或窗口最小化时隐藏，重新可见时恢复；关闭或改变尺寸时停止，需重新框选。区域可见性不依赖前台焦点，避免托盘工具抢焦点导致译文消失。
- 框选应完整位于**同一个窗口、同一显示器**内。不支持跨多个显示器框选；改动分辨率、显示器缩放或窗口尺寸后需重新选择。
- 旧版 Windows 可能保留系统的捕获边框。程序不会注入游戏进程，也不修改游戏文件。

## 自动语言识别和速度

检测器只运行一次，中英日模型与韩文模型识别文字行，再按置信度和字符类别选择结果。同一聊天窗可以包含不同语言的消息。纯汉字短句可能无法仅凭字符区分中文和日文，会交给 Google 自动识别。单行内同时混合大量日韩字符、艺术字体和极小字号仍可能误识别。

新安装默认每 **200 ms** 检测一次变化，已有设置保留。这不是端到端延迟保证。真实耗时还包括 OCR、Google 网络请求和过期结果检查。早前已预热、固定日语的浏览器竖排小样本连续 5 次为 **431–459 ms**；混合三语、整页正文和网络慢请求尚不能保证 500 ms。

- 启动预热检测器、识别器和 Google 连接；跨次框选复用模型、HTTP Session 和译文缓存。
- 固定韩语只运行韩语识别器，固定日语 / 英语只运行中英日识别器，同时向翻译服务传递固定源语言。
- 按 CPU 逻辑核心数使用 1–4 个推理线程。当前是 CPU ONNX 推理，未启用 GPU。
- 日文竖排合并同列检测碎片，再按右到左合并相邻列作为段落翻译；细笔画、模糊字、跨气泡排版仍可能误识别。
- 宽幅纯色横排正文使用快速行定位，先显示完成翻译的部分，再补齐其余行；漫画与复杂背景保留神经网络检测。部分显示和整页完成是两种不同延迟。
- 长正文翻译分块并发，已成功部分保留缓存；画面变化检查改用等价整数求和，减少每轮 CPU 开销。
- 文字行形状缓存忽略单纯背景亮度变化；相同原文复用翻译缓存。
- 日韩英分别成批送给 Google 自动识别，最多同时进行 3 个请求，避免把混合消息误判成一种语言。
- 背景动画不会仅凭像素变化清除译文；内容或文字位置变化才更新。
- 网络返回后确认文字仍在原位置；已滚走或被替换的旧结果不覆盖到新聊天上。
- 网络失败后渐进退避重试；429 限流遵守服务端等待时间，缺省至少 60 秒，避免持续重复请求。退出立即清除覆盖层，后台请求在超时后安全结束。

最新长正文和漫画优化见 [PERFORMANCE_UPDATE.md](PERFORMANCE_UPDATE.md)，上一轮记录见 [TEST_REPORT.md](TEST_REPORT.md)。CS2 / DJMAX 留待手动实测，步骤见 [GAME_TESTING.md](GAME_TESTING.md)。不宣称已经验证这两款游戏。

## 翻译服务和隐私

- 新配置默认 **有道翻译＋RapidOCR**，需填写应用 ID 和应用密钥。仍可选择百度、Google 免密钥及 Google Cloud。已有用户保留之前的翻译源选择。
- 可切换 **Google Cloud Translation Basic 官方 API**，填写 API Key。官方服务可能计费，程序不会自动启用计费。
- 百度 / 有道官方接口需要应用 ID 和密钥。有道使用应用 ID＋应用密钥，不需要额外 apikey。DeepSeek 只需 API Key，也支持 `DEEPSEEK_API_KEY` 环境变量。
- 默认密钥仅保留当前会话；可勾选 Windows DPAPI 加密保存，按翻译工具分别存储，仅当前 Windows 账户可解密。取消勾选并应用会删除保存的密钥。也可使用环境变量 `GOOGLE_TRANSLATE_API_KEY`、`BAIDU_APP_ID` / `BAIDU_API_KEY`、`YOUDAO_APP_ID` / `YOUDAO_API_KEY`。打包文件不包含个人凭据。
- 可填写自己的 HTTP 代理，例如 `http://127.0.0.1:7890`。留空使用 Requests 支持的环境/系统代理配置。
- OCR 和截图在本地处理；只有识别文字发送给所选翻译服务。Google 免密钥启动预热还会发送固定公开单词 Ready。正常运行不保存截图或聊天记录，缓存仅存于内存。
- 偏好保存在当前用户的 Qt 设置中：`HKEY_CURRENT_USER\Software\ScreenLingo\ScreenLingo`。代理地址会保存，避免在其中填写密码。
- Git 仅跟踪项目源码、构建配置和使用文档；测试素材、测试脚本、测试结果、模型权重及本地凭据不上传。本地原文件保留。

## 已知限制

主要面向正常桌面和无边框游戏。独占全屏、受保护画面、HDR、游戏内特殊捕获限制可能导致黑屏、颜色偏差或覆盖不可见，尚未逐一验证。程序不会绕过游戏的捕获限制。

阴影是覆盖矩形，不是背景修复。复杂背景或过长译文可能影响阅读，译文会尝试缩小以适应原文字行；非常长的译文仍可能裁切。可增大游戏聊天字体、调整遮罩透明度。Google 对昵称、俚语、缩写和游戏术语可能翻译不自然。

聊天高速滚动或消失时间短于网络请求时，旧消息会丢弃。建议只框选需要阅读的聊天窗，降低整屏 OCR 开销。未测试实际游戏帧率损失，不保证每帧翻译。

## 开发与测试

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m screenlingo.models
.\.venv\Scripts\python.exe main.py
```




目录：`ui.py` 设置与会话；`overlay.py` 框选与覆盖；`capture.py` HWND 采集；`worker.py` 实时流水线；`ocr.py` 多语言 OCR；`core.py` 翻译与变化检测；`win32.py` 热键与窗口跟踪。

技术参考：[Windows Capture](https://github.com/NiiightmareXD/windows-capture/tree/main/windows-capture-python)、[Windows 覆盖层截图排除](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity)、[Google 官方 API](https://docs.cloud.google.com/translate/docs/basic/translating-text)、[RapidOCR 模型表](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)、[百度官方接口](https://api.fanyi.baidu.com/doc/23)、[有道官方接口](https://ai.youdao.com/DOCSIRMA/html/transapi/trans/api/wbfy/index.html)。
