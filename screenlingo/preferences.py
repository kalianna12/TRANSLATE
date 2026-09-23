"""Plain native Windows preferences and a compact tray menu."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox, QLineEdit,
                              QCheckBox, QSpinBox, QKeySequenceEdit, QPushButton, QHBoxLayout,
                              QLabel, QSystemTrayIcon, QMenu, QTabWidget)
from .core import LANGUAGES

SOURCES = {"自动识别（日 / 英 / 韩）": "auto", "日语": "ja", "英语": "en", "韩语": "ko", "中文": "zh-CN"}
PROVIDERS = {"有道翻译（推荐）": "youdao", "DeepSeek-V4.1-Flash（AI 翻译）": "deepseek", "百度通用翻译": "baidu", "Google（免密钥）": "free", "Google Cloud（官方）": "cloud"}


def build_preferences(window):
    window.setWindowTitle("ScreenLingo 首选项")
    window.setMinimumWidth(490)
    window.resize(560, 540)
    root = QWidget()
    window.setCentralWidget(root)
    layout = QVBoxLayout(root)
    window.tabs = QTabWidget()
    layout.addWidget(window.tabs)
    translation = QGroupBox("翻译")
    form = QFormLayout(translation)
    window.provider = QComboBox()
    for label, value in PROVIDERS.items():
        window.provider.addItem(label, value)
    form.addRow("翻译工具", window.provider)
    window.reasoning_effort = QComboBox()
    for label, value in [("关闭思考（默认 · 最快）", "none"), ("低", "low"), ("高", "high"), ("最高（较慢）", "max")]:
        window.reasoning_effort.addItem(label, value)
    form.addRow("AI 推理强度", window.reasoning_effort)
    window.reasoning_effort.setToolTip("仅 DeepSeek 生效。使用当前区域的上下文；重新框选会清空历史上下文。")
    window.source = QComboBox()
    for label, value in SOURCES.items():
        window.source.addItem(label, value)
    form.addRow("原文语言", window.source)
    window.language = QComboBox()
    labels = {"en": "英语", "ja": "日语", "ko": "韩语", "zh-CN": "简体中文", "zh-TW": "繁体中文",
              "fr": "法语", "de": "德语", "es": "西班牙语", "pt": "葡萄牙语", "it": "意大利语",
              "ru": "俄语", "vi": "越南语", "th": "泰语", "ar": "阿拉伯语"}
    for label, value in LANGUAGES.items():
        window.language.addItem(labels.get(value, label), value)
    form.addRow("译文语言", window.language)
    window.app_id = QLineEdit()
    window.app_id.setPlaceholderText("百度 / 有道的应用 ID")
    form.addRow("应用 ID", window.app_id)
    window.api_key = QLineEdit()
    window.api_key.setEchoMode(QLineEdit.EchoMode.Password)
    window.api_key.setPlaceholderText("密钥仅在本次运行中使用")
    form.addRow("密钥", window.api_key)
    window.remember_key = QCheckBox("在此 Windows 账户加密保存密钥")
    form.addRow(window.remember_key)
    show_key = QCheckBox("显示密钥")
    show_key.toggled.connect(lambda checked: window.api_key.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
    form.addRow(show_key)
    window.provider_hint = QLabel()
    window.provider_hint.setWordWrap(True)
    form.addRow(window.provider_hint)
    window.proxy = QLineEdit()
    window.proxy.setPlaceholderText("可选：http://127.0.0.1:7890")
    form.addRow("代理", window.proxy)
    def provider_changed():
        window.reasoning_effort.setEnabled(window.provider.currentData() == "deepseek")
        window.app_id.setEnabled(window.provider.currentData() in ("baidu", "youdao"))
        window.api_key.setEnabled(window.provider.currentData() != "free")
        window.provider_hint.setText("DeepSeek：只需 API Key，无需应用 ID 或下载模型。RapidOCR 本地识别后上传文字，使用上下文保持译名一致。"
                                     if window.provider.currentData() == "deepseek" else
                                     "百度：填写开发者 APPID 和密钥（不是大模型 API Key）。本地识别后只上传文字。"
                                     if window.provider.currentData() == "baidu" else
                                     "有道：填写应用 ID 和应用密钥，不需要额外 apikey。识别在本地完成，只上传文字。"
                                     if window.provider.currentData() == "youdao" else "切换翻译工具后请填写对应凭据，点击应用保存。")
    window.provider.currentIndexChanged.connect(provider_changed)
    provider_changed()
    window.tabs.addTab(translation, "翻译")

    recognition = QGroupBox("识别与显示")
    form = QFormLayout(recognition)
    window.ocr_backend = QComboBox()
    window.ocr_backend.addItem("RapidOCR（推荐 · 已内置）", "rapid")
    form.addRow("识别引擎", window.ocr_backend)
    window.realtime = QCheckBox("持续监测框选区域")
    window.realtime.setChecked(True)
    form.addRow(window.realtime)
    window.interval = QSpinBox()
    window.interval.setRange(100, 10000)
    window.interval.setSingleStep(50)
    window.interval.setValue(200)
    window.interval.setSuffix(" ms")
    form.addRow("检测间隔", window.interval)
    window.interval.setToolTip("从每轮截图开始计时，包含识别与翻译；不是完成后再等待完整间隔。")
    window.display_style = QComboBox()
    window.display_style.addItem("背景融合（网页 / 文档 / 漫画）", "blend")
    window.display_style.addItem("深色遮罩（游戏 / 复杂背景）", "shade")
    form.addRow("覆盖效果", window.display_style)
    window.fixed_background = QCheckBox("固定背景（文字不变时保持覆盖层）")
    window.fixed_background.setToolTip("首次译文确定背景色；后续不随游戏背景重新取色。重新框选后重置。")
    form.addRow(window.fixed_background)
    window.reading_layout = QComboBox()
    window.reading_layout.addItem("常规横排", "standard")
    window.reading_layout.addItem("日文漫画竖排（上→下，右→左）", "manga")
    window.reading_layout.setToolTip("漫画模式按相邻原文列组织对白，译文竖排。建议框选单个分镜或气泡；不自动识别复杂分镜。")
    form.addRow("文字排版", window.reading_layout)
    window.opacity = QSpinBox()
    window.opacity.setRange(30, 100)
    window.opacity.setValue(88)
    window.opacity.setSuffix(" %")
    form.addRow("原文遮罩", window.opacity)
    window.display_style.currentIndexChanged.connect(lambda: window.opacity.setEnabled(window.display_style.currentData() == "shade"))
    window.opacity.setEnabled(False)
    hint = QLabel("固定原文语言可减少识别耗时。\n自动处理日文竖排，按从右到左的顺序翻译。")
    hint.setWordWrap(True)
    form.addRow(hint)
    window.tabs.addTab(recognition, "识别与显示")

    hotkeys = QGroupBox("快捷键")
    form = QFormLayout(hotkeys)
    window.region_key = QKeySequenceEdit(QKeySequence("Ctrl+T"))
    window.full_key = QKeySequenceEdit(QKeySequence("Ctrl+Shift+T"))
    window.stop_key = QKeySequenceEdit(QKeySequence("Esc"))
    window.input_key = QKeySequenceEdit(QKeySequence("Ctrl+Y"))
    for name, editor in [("框选翻译", window.region_key), ("全屏翻译", window.full_key), ("停止翻译", window.stop_key), ("输入翻译", window.input_key)]:
        editor.setMaximumSequenceLength(1)
        form.addRow(name, editor)
    window.autostart = QCheckBox("登录 Windows 后自动启动到托盘")
    form.addRow(window.autostart)
    form.addRow(QLabel("关闭首选项仍驻留托盘；完全退出请使用托盘菜单。"))
    window.tabs.addTab(hotkeys, "快捷键与启动")
    input_tab = QGroupBox("游戏聊天输入翻译")
    form = QFormLayout(input_tab)
    window.input_source = QComboBox()
    for label, value in [("中文", "zh-CN"), ("自动识别", "auto"), ("日语", "ja"), ("英语", "en"), ("韩语", "ko")]:
        window.input_source.addItem(label, value)
    window.input_target = QComboBox()
    for label, value in [("韩语", "ko"), ("日语", "ja"), ("英语", "en"), ("中文", "zh-CN")]:
        window.input_target.addItem(label, value)
    window.input_mode = QComboBox()
    window.input_mode.addItem("替换当前聊天输入框", "replace")
    window.input_mode.addItem("仅翻译剪贴板（手动复制 / 粘贴）", "clipboard")
    form.addRow("输入原文语言", window.input_source)
    form.addRow("输入译文语言", window.input_target)
    form.addRow("操作方式", window.input_mode)
    input_shortcut = QLabel(window.input_key.keySequence().toString())
    window.input_key.keySequenceChanged.connect(lambda sequence: input_shortcut.setText(sequence.toString()))
    form.addRow("输入翻译热键", input_shortcut)
    note = QLabel("先打开游戏聊天框并输入文字，再按输入翻译热键。翻译后请确认内容，自行按 Enter 发送。\n使用“翻译”页选定的服务、凭据和推理强度；此处语言设置独立于屏幕翻译。\n不支持复制粘贴的游戏请使用剪贴板模式。替换期间不要切换窗口或继续输入。译文会保留在剪贴板。")
    note.setWordWrap(True)
    form.addRow(note)
    window.tabs.addTab(input_tab, "输入翻译")
    window.status = QLabel("正在准备识别模型…")
    window.status.setWordWrap(True)
    window.timing = QLabel("")
    window.timing.setWordWrap(True)
    layout.addWidget(window.status)
    layout.addWidget(window.timing)
    buttons = QHBoxLayout()
    buttons.addStretch()
    save = QPushButton("应用")
    save.clicked.connect(window.save_settings)
    close = QPushButton("关闭")
    close.clicked.connect(window.hide_to_tray)
    buttons.addWidget(save)
    buttons.addWidget(close)
    layout.addLayout(buttons)


def install_tray(window):
    window.tray = QSystemTrayIcon(window.windowIcon(), window)
    window.tray.setToolTip("ScreenLingo · 右键设置")
    menu = QMenu()
    window.tray_menu = menu
    window.menu_actions = {}
    for key, label, callback in [(1, "框选翻译", lambda: window.request_start("region")),
                                  (2, "全屏翻译", lambda: window.request_start("full")),
                                  (3, "停止翻译", window.stop)]:
        action = menu.addAction(label)
        action.triggered.connect(callback)
        window.menu_actions[key] = (action, label)
    menu.addSeparator()
    input_menu = menu.addMenu("输入翻译到")
    input_group = QActionGroup(input_menu)
    window.input_target_actions = []
    for label, value in [("韩语", "ko"), ("日语", "ja"), ("英语", "en"), ("中文", "zh-CN")]:
        action = input_menu.addAction(label)
        action.setCheckable(True)
        input_group.addAction(action)
        def choose_input(checked=False, value=value):
            window.input_target.setCurrentIndex(window.input_target.findData(value))
            window.settings.setValue("input_target", value)
        action.triggered.connect(choose_input)
        window.input_target_actions.append((action, value))
    menu.addAction("取消输入翻译", lambda: window.input_translation.cancel())
    menu.addSeparator()
    language_menu = menu.addMenu("原文语言")
    group = QActionGroup(language_menu)
    window.source_actions = []
    for label, value in SOURCES.items():
        action = language_menu.addAction(label)
        action.setCheckable(True)
        group.addAction(action)
        def choose(checked=False, value=value):
            window.source.setCurrentIndex(window.source.findData(value))
            window.settings.setValue("source", value)
        action.triggered.connect(choose)
        window.source_actions.append((action, value))
    menu.addSeparator()
    menu.addAction("首选项…", window.restore)
    menu.addSeparator()
    menu.addAction("退出", window.quit_app)
    def refresh():
        for key, (action, label) in window.menu_actions.items():
            action.setText(label + "\t" + window.bindings()[key])
        for action, value in window.source_actions:
            action.setChecked(value == window.source.currentData())
        for action, value in window.input_target_actions:
            action.setChecked(value == window.input_target.currentData())
    menu.aboutToShow.connect(refresh)
    window.tray.setContextMenu(menu)
    window.tray.activated.connect(lambda reason: window.restore() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    window.tray.show()
