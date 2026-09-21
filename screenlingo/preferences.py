"""Plain native Windows preferences and a compact tray menu."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QGroupBox, QComboBox, QLineEdit,
                              QCheckBox, QSpinBox, QKeySequenceEdit, QPushButton, QHBoxLayout,
                              QLabel, QSystemTrayIcon, QMenu, QTabWidget)
from .core import LANGUAGES

SOURCES = {"自动识别（日 / 英 / 韩）": "auto", "日语": "ja", "英语": "en", "韩语": "ko", "中文": "zh-CN"}
PROVIDERS = {"有道翻译（推荐）": "youdao", "百度通用翻译": "baidu", "Google（免密钥）": "free", "Google Cloud（官方）": "cloud"}


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
        window.app_id.setEnabled(window.provider.currentData() in ("baidu", "youdao"))
        window.api_key.setEnabled(window.provider.currentData() != "free")
        window.provider_hint.setText("百度：填写开发者 APPID 和密钥（不是大模型 API Key）。本地识别后只上传文字。"
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
    window.ocr_backend.addItem("GLM-OCR（实验性 · 本地 Ollama）", "glm")
    form.addRow("识别引擎", window.ocr_backend)
    window.glm_status = QLabel("GLM 默认不下载、不加载；需要时安装 Ollama，再下载模型。")
    window.glm_status.setWordWrap(True)
    form.addRow(window.glm_status)
    glm_buttons = QHBoxLayout()
    window.glm_check = QPushButton("检查模型")
    window.glm_download = QPushButton("下载 GLM-OCR")
    install = QPushButton("Ollama 官网")
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    install.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://ollama.com/download/windows")))
    window.glm_check.clicked.connect(lambda: window.manage_glm(False))
    window.glm_download.clicked.connect(lambda: window.manage_glm(True))
    for button in (window.glm_check, window.glm_download, install):
        glm_buttons.addWidget(button)
    form.addRow(glm_buttons)
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
    for name, editor in [("框选翻译", window.region_key), ("全屏翻译", window.full_key), ("停止翻译", window.stop_key)]:
        editor.setMaximumSequenceLength(1)
        form.addRow(name, editor)
    window.autostart = QCheckBox("登录 Windows 后自动启动到托盘")
    form.addRow(window.autostart)
    form.addRow(QLabel("关闭首选项仍驻留托盘；完全退出请使用托盘菜单。"))
    window.tabs.addTab(hotkeys, "快捷键与启动")
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
    menu.aboutToShow.connect(refresh)
    window.tray.setContextMenu(menu)
    window.tray.activated.connect(lambda reason: window.restore() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    window.tray.show()
