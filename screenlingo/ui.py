import os

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame,
                              QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QMainWindow,
                              QMenu, QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon,
                              QVBoxLayout, QWidget)

from .core import LANGUAGES
from .overlay import RegionSelector, TranslationOverlay
from .win32 import (Hotkeys, exclude_from_capture, focus_window, foreground_window,
                    position_overlay, target_region_visible, window_at, window_minimized, window_rect)
from .worker import TranslationWorker





def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#eeeeee"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 5, 5)
    painter.setPen(QColor("#222222"))
    font = painter.font()
    font.setPixelSize(34)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        QApplication.instance().setStyle("windows")
        self.setFont(QFont("Microsoft YaHei UI", 9))
        self.settings = QSettings()
        self.worker = None
        self.selector = None
        self.pending = None
        self.generation = 0
        self.closing = False
        self.tray_only = False
        self.initialization_error = False
        self.credential_drafts = {}
        self.credential_provider = None
        self.target_hwnd = 0
        self.target_bounds = None
        self.target_crop = None
        self.translation_active = False
        self.overlay = TranslationOverlay()
        self.setWindowTitle("ScreenLingo · 屏幕翻译")
        self.setWindowIcon(app_icon())
        self._build()
        from .input_translation import InputTranslation
        self.input_translation = InputTranslation(self)
        self.input_translation.message.connect(self.input_message)
        self.input_translation.idle.connect(lambda: QTimer.singleShot(0, self.close) if self.closing else None)
        self.hotkeys = Hotkeys(QApplication.instance(), self.on_hotkey)
        self._tray()
        self.load_settings()
        self.tracking = QTimer(self)
        self.tracking.setInterval(100)
        self.tracking.timeout.connect(self.track_target)
        self.tracking.start()
        QTimer.singleShot(0, self.initialize)

    def _build(self):
        from .preferences import build_preferences
        build_preferences(self)

    def _tray(self):
        from .preferences import install_tray
        install_tray(self)

    def initialize(self):
        exclude_from_capture(self.winId())
        try:
            self.hotkeys.configure(self.bindings())
        except ValueError as exc:
            self.initialization_error = True
            self.status.setText(str(exc))
            self.restore()

    def bindings(self):
        return {1: self.region_key.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
                2: self.full_key.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
                3: self.stop_key.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
                4: self.input_key.keySequence().toString(QKeySequence.SequenceFormat.PortableText)}

    def load_settings(self):
        if self.settings.value("input_mode", "replace") == "game":
            self.settings.setValue("input_mode", "replace")
        for widget, key in [(self.language, "target"), (self.provider, "provider"), (self.source, "source"),
                            (self.ocr_backend, "ocr_backend"), (self.display_style, "display_style"),
                            (self.reasoning_effort, "reasoning_effort"), (self.reading_layout, "reading_layout"),
                            (self.input_source, "input_source"), (self.input_target, "input_target"), (self.input_mode, "input_mode")]:
            index = widget.findData(self.settings.value(key, widget.itemData(0)))
            widget.setCurrentIndex(max(0, index))
        self.api_key.setEnabled(self.provider.currentData() != "free")
        self.app_id.setText(self.settings.value("app_id", ""))
        from .windows_settings import startup_enabled
        self.autostart.setChecked(startup_enabled())
        self.load_credentials()
        self.credential_provider = self.provider.currentData()
        self.provider.currentIndexChanged.connect(self.switch_credentials)
        self.proxy.setText(self.settings.value("proxy", ""))
        try:
            self.interval.setValue(int(self.settings.value("interval", 200)))
        except (ValueError, TypeError):
            self.interval.setValue(200)
        self.realtime.setChecked(self.settings.value("realtime", True, type=bool))
        self.opacity.setValue(self.settings.value("shade_opacity", 88, type=int))
        self.fixed_background.setChecked(self.settings.value("fixed_background", False, type=bool))
        for key, edit in [(1, self.region_key), (2, self.full_key), (3, self.stop_key), (4, self.input_key)]:
            edit.setKeySequence(QKeySequence(self.settings.value(f"hotkey{key}", edit.keySequence().toString())))

    def load_credentials(self):
        from .windows_settings import unprotect
        provider = self.provider.currentData()
        encrypted = self.settings.value(f"credentials/{provider}/secret", "")
        self.api_key.clear()
        self.remember_key.setChecked(bool(encrypted))
        legacy_id = self.settings.value("app_id", "") if provider == self.settings.value("provider", "youdao") else ""
        self.app_id.setText(self.settings.value(f"credentials/{provider}/app_id", legacy_id))
        if encrypted:
            try:
                self.api_key.setText(unprotect(encrypted))
            except (OSError, ValueError):
                self.status.setText("保存的密钥无法解密，请重新填写并应用。")

    def switch_credentials(self):
        if self.credential_provider:
            self.credential_drafts[self.credential_provider] = (self.app_id.text(), self.api_key.text(), self.remember_key.isChecked())
        self.credential_provider = self.provider.currentData()
        draft = self.credential_drafts.get(self.credential_provider)
        if draft is None:
            self.load_credentials()
        else:
            self.app_id.setText(draft[0])
            self.api_key.setText(draft[1])
            self.remember_key.setChecked(draft[2])

    def save_settings(self):
        try:
            from .windows_settings import protect, set_startup, startup_enabled
            encrypted = protect(self.api_key.text().strip()) if self.remember_key.isChecked() and self.api_key.text().strip() else ""
            self.hotkeys.configure(self.bindings())
            if self.autostart.isChecked() != startup_enabled():
                set_startup(self.autostart.isChecked())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "设置未完整应用", str(exc))
            return
        provider = self.provider.currentData()
        self.settings.setValue(f"credentials/{provider}/secret", encrypted)
        self.settings.setValue(f"credentials/{provider}/app_id", self.app_id.text().strip())
        for key, value in self.options().items():
            if key != "api_key":
                self.settings.setValue(key, value)
        for key, value in self.bindings().items():
            self.settings.setValue(f"hotkey{key}", value)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            QMessageBox.warning(self, "保存失败", "无法写入当前用户设置，请检查权限后重试。")
            return
        self.initialization_error = False
        self.status.setText("设置已保存，热键已应用。翻译偏好将在下次启动翻译时生效。")

    def options(self):
        return {"target": self.language.currentData(), "provider": self.provider.currentData(),
                "api_key": self.api_key.text().strip(), "proxy": self.proxy.text().strip(),
                "interval": self.interval.value(), "realtime": self.realtime.isChecked(),
                "shade_opacity": self.opacity.value(), "source": self.source.currentData(),
                "app_id": self.app_id.text().strip(), "ocr_backend": self.ocr_backend.currentData(),
                "display_style": self.display_style.currentData(), "reasoning_effort": self.reasoning_effort.currentData(),
                "reading_layout": self.reading_layout.currentData(), "fixed_background": self.fixed_background.isChecked(), "input_source": self.input_source.currentData(),
                "input_target": self.input_target.currentData(), "input_mode": self.input_mode.currentData()}

    def input_message(self, message):
        self.status.setText(message)
        self.tray.setToolTip("ScreenLingo · " + message)
        if not self.isVisible() and not self.closing and not message.endswith("…"):
            self.tray.showMessage("输入翻译", message, QSystemTrayIcon.MessageIcon.Information, 3500)

    def on_hotkey(self, key):
        if key == 4:
            if not self.closing:
                self.input_translation.start(self.options())
        elif key == 3:
            target = self.target_hwnd
            self.stop()
            focus_window(target)
        else:
            self.request_start("region" if key == 1 else "full")

    def request_start(self, mode):
        if self.closing:
            return
        options = self.options()
        if options["provider"] == "deepseek" and not (options["api_key"] or os.getenv("DEEPSEEK_API_KEY")):
            self.restore()
            QMessageBox.warning(self, "需要 API Key", "请填写 DeepSeek API Key。")
            return
        if options["provider"] == "cloud" and not (options["api_key"] or os.getenv("GOOGLE_TRANSLATE_API_KEY")):
            self.restore()
            QMessageBox.warning(self, "需要 API Key", "请填写 Google Cloud Translation API Key，或选择免密钥试用。")
            return
        if options["provider"] in ("baidu", "youdao"):
            prefix = options["provider"].upper()
            if not ((options["api_key"] or os.getenv(prefix + "_API_KEY")) and
                    (options["app_id"] or os.getenv(prefix + "_APP_ID"))):
                self.restore()
                QMessageBox.warning(self, "需要服务凭据", "请填写应用 ID 和密钥，或选择 Google 免密钥服务。")
                return
        if options["proxy"] and not options["proxy"].startswith(("http://", "https://")):
            self.restore()
            QMessageBox.warning(self, "代理地址不正确", "请填写 http:// 或 https:// 开头的代理地址。")
            return
        self.stop()
        options["previous_hwnd"] = foreground_window()
        options["capture_mode"] = mode
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.pending = (mode, screen, options)
        if self.worker is not None:
            self.status.setText("正在结束上一轮请求，随后启动新的翻译…")
        else:
            self.begin_selection()

    def begin_selection(self):
        if not self.pending or self.closing:
            return
        mode, screen, options = self.pending
        self.pending = None
        self.hide()
        self.selector = RegionSelector(screen)
        self.selector.selected.connect(lambda region, logical: self.start_worker(region, logical, options))
        self.selector.cancelled.connect(lambda: self.cancel_selection(options.get("previous_hwnd", 0)))
        self.selector.open()
        if mode == "full":
            selector = self.selector
            QTimer.singleShot(120, lambda: selector.finish(selector.rect()) if self.selector is selector else None)

    def start_worker(self, region, logical, options):
        selected_hwnd = self.selector.target_hwnd if self.selector else 0
        if self.selector:
            self.selector.deleteLater()
            self.selector = None
        if options.get("capture_mode") == "region":
            hwnd = selected_hwnd or window_at(region.left + region.width // 2, region.top + region.height // 2)
            bounds = window_rect(hwnd)
            if not bounds or hwnd == int(self.winId()):
                self.receive_fault(self.generation, "未选中可捕获的窗口，请在游戏窗口内重新框选。")
                return
            self.target_hwnd = hwnd
            self.target_bounds = bounds
            self.target_crop = (region.left - bounds[0], region.top - bounds[1], region.width, region.height)
            options["window_hwnd"] = hwnd
            focus_window(hwnd)
            # The selector is still inside mouseReleaseEvent; its close can restore the old
            # foreground window. Activate the target after that native event has completed.
            QTimer.singleShot(0, lambda: focus_window(hwnd) if self.target_hwnd == hwnd else None)
        else:
            options["window_hwnd"] = 0
            focus_window(options.get("previous_hwnd", 0))
        try:
            self.hotkeys.set_active(True)
        except ValueError as exc:
            self.receive_fault(self.generation, str(exc))
            return
        if not self.overlay.prepare(region, logical, bool(options["window_hwnd"]), options.get("shade_opacity", 88)):
            self.hotkeys.set_active(False)
            self.restore()
            self.status.setText("无法从截图中排除覆盖层。请使用 Windows 10 2004+ / Windows 11 的普通桌面会话。")
            return
        self.translation_active = True
        self.overlay.display_style = options.get("display_style", "blend")
        self.overlay.fixed_background = options.get("fixed_background", False)
        self.overlay.reading_layout = options.get("reading_layout", "standard")
        options["fast_first_frame"] = exclude_from_capture(self.overlay.winId())
        token = self.generation
        self.worker = TranslationWorker(token, region, options, self)
        self.worker.result.connect(self.receive_result)
        self.worker.status.connect(self.receive_status)
        self.worker.fault.connect(self.receive_fault)
        self.worker.fatal.connect(self.receive_fatal)
        self.worker.metrics.connect(self.receive_metrics)
        self.worker.finished.connect(self.worker_finished)
        # Both selector and overlay are excluded from capture; no fixed startup delay.
        self.worker.start()
        self.status.setText("正在启动翻译…")

    def receive_result(self, token, blocks):
        if token == self.generation:
            self.overlay.set_blocks(blocks)

    def cancel_selection(self, previous_hwnd):
        self.stop()
        focus_window(previous_hwnd)

    def track_target(self):
        if not self.translation_active or not self.target_hwnd:
            return
        bounds = window_rect(self.target_hwnd)
        if bounds is None:
            self.stop()
            self.status.setText("目标窗口已关闭，翻译已停止。")
            return
        if bounds[2:] != self.target_bounds[2:] and not window_minimized(self.target_hwnd):
            self.stop()
            self.status.setText("目标窗口尺寸已变化，请重新框选。")
            return
        x, y, width, height = self.target_crop
        absolute = (bounds[0] + x, bounds[1] + y, width, height)
        visible = (not window_minimized(self.target_hwnd) and
                   target_region_visible(self.target_hwnd, absolute, self.overlay.winId()))
        if not visible:
            self.overlay.hide()
            self.hotkeys.set_active(False)
            return
        # Returning to the game also tucks away the settings-only window.
        if self.isVisible() and foreground_window() == self.target_hwnd:
            self.hide()
            focus_window(self.target_hwnd)
        try:
            self.hotkeys.set_active(True)
        except ValueError as exc:
            self.stop()
            self.status.setText(str(exc))
            return
        if not self.overlay.isVisible():
            self.overlay.show()
        position_overlay(self.overlay.winId(), absolute)

    def receive_metrics(self, token, metrics):
        if token == self.generation:
            first = metrics.get("first_result_ms")
            prefix = f"首段 {first:.0f} ms · " if first is not None else ""
            self.timing.setText(prefix + f"OCR {metrics['ocr_ms']:.0f} ms · 翻译 {metrics['translate_ms']:.0f} ms · "
                                f"处理合计 {metrics['total_ms']:.0f} ms · "
                                f"译文缓存命中 {metrics['translation_cache_hits']} 行")

    def receive_status(self, token, message):
        if token == self.generation:
            self.status.setText(message)
            self.tray.setToolTip(f"ScreenLingo · {message}")
            if "无文字" in message:
                self.overlay.set_message("没有识别到文字：请放大图片后重新框选。Esc 退出")
            elif message.startswith(("正在", "首次使用", "聊天内容")):
                self.overlay.set_message(message)

    def receive_fault(self, token, message):
        if token == self.generation:
            self.status.setText(message)
            self.overlay.set_message(message + " Esc 退出")
            if self.status.toolTip() != message:
                self.tray.showMessage("翻译暂时不可用", message, QSystemTrayIcon.MessageIcon.Warning, 5000)
                self.status.setToolTip(message)

    def receive_fatal(self, token, message):
        if token == self.generation:
            self.stop()
            self.receive_fault(self.generation, message)
            # Startup failures must remain visible even if notifications are disabled.
            self.restore()

    def worker_finished(self):
        finished = self.sender()
        if self.worker is finished:
            self.worker = None
        finished.deleteLater()
        if self.closing:
            QTimer.singleShot(0, self.close)
        elif self.pending:
            self.begin_selection()

    def stop(self):
        self.generation += 1
        self.pending = None
        self.translation_active = False
        self.target_hwnd = 0
        self.target_bounds = None
        self.target_crop = None
        self.hotkeys.set_active(False)
        if self.selector:
            self.selector.close()
            self.selector.deleteLater()
            self.selector = None
        if self.worker:
            self.worker.stop()
        self.overlay.set_blocks([])
        self.overlay.hide()
        self.status.setText("已停止，覆盖译文已清除。")
        self.tray.setToolTip("ScreenLingo · 已停止")

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.showMinimized()

    def closeEvent(self, event):
        if self.tray_only and not self.closing:
            self.hide()
            event.ignore()
            return
        self.closing = True
        self.stop()
        self.hotkeys.clear()
        if self.input_translation.busy:
            self.input_translation.cancel()
            if self.input_translation.busy:
                event.ignore()
                return
        preparation = getattr(self, "preparation", None)
        if preparation and preparation.isRunning():
            preparation.requestInterruption()
            event.ignore()
            return
        if self.worker is not None:
            self.status.setText("正在等待后台请求结束并安全退出…")
            event.ignore()
            return
        self.tray.hide()
        from .runtime import close_runtime
        close_runtime()
        self.overlay.close()
        event.accept()
        QApplication.instance().quit()

    def quit_app(self):
        self.closing = True
        self.close()
