"""Explicit hotkey translation; clipboard access stays on the GUI thread."""
import os
import time
import json
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, QThread, QTimer, Signal, QMimeData
from PySide6.QtWidgets import QApplication
from .core import Translator, TranslationError
from . import input_native as native


class InputJob(QThread):
    result = Signal(str)
    failed = Signal(str)

    def __init__(self, text, options, parent=None):
        super().__init__(parent)
        self.text, self.options = text, options

    def run(self):
        client = None
        try:
            client = Translator(**self.options)
            values = client.translate([self.text], self.isInterruptionRequested)
            if not self.isInterruptionRequested() and values:
                self.result.emit(values[0])
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("输入翻译失败，请检查翻译设置。")
        finally:
            if client:
                client.close()


class InputTranslation(QObject):
    message = Signal(str)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = None
        self.phase = "idle"
        self.clipboard = QApplication.clipboard()
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.tick)
        self.backup = None
        self.owned_sequence = None
        self.trace_events = []

    def trace(self, event, **details):
        """Bounded diagnostic metadata only: never text, clipboard contents or credentials."""
        from PySide6.QtCore import QStandardPaths
        self.trace_events.append({"event": event, "phase": self.phase, **details})
        self.trace_events = self.trace_events[-40:]
        try:
            folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "input-diagnostic.json").write_text(json.dumps(self.trace_events, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    @property
    def busy(self):
        return self.phase != "idle" or self.job is not None

    def start(self, options):
        if self.busy:
            self.message.emit("输入翻译正在进行，请稍候；托盘菜单可取消。")
            return
        self.manual = options.get("input_mode") == "clipboard"
        self.target = native.focus_identity()
        self.trace_events = []
        self.trace("start", mode=options.get("input_mode", "replace"), target_pid=self.target[1] if self.target else 0)
        if not self.manual and (not self.target or self.target[1] == os.getpid()):
            self.message.emit("请先打开游戏聊天框并输入文字，再按输入翻译热键。")
            return
        self.options = {key: options.get(key, "") for key in ("provider", "api_key", "proxy", "app_id")}
        self.options.update(source=options.get("input_source", "zh-CN"),
                            target=options.get("input_target", "ko"),
                            reasoning_effort=options.get("reasoning_effort", "none"))
        self.backup = QMimeData()
        mime = self.clipboard.mimeData()
        if mime:
            for fmt in mime.formats():
                self.backup.setData(fmt, mime.data(fmt))
        self.owned_sequence = None
        self.observed_sequence = native.sequence()
        if self.manual:
            self.original = self.clipboard.text()
            self.launch()
        else:
            self.phase = "release"
            self.deadline = time.monotonic() + 2
            self.timer.start()

    def cancel(self, message="已取消输入翻译，未发送消息。"):
        stage = self.phase
        self.trace("cancel", reason=message)
        self.timer.stop()
        self.phase = "idle"
        if self.job:
            self.job.requestInterruption()
        if self.backup is not None and self.owned_sequence is not None and native.sequence() == self.owned_sequence:
            self.clipboard.setMimeData(self.backup)
        self.backup = None
        self.owned_sequence = None
        self.message.emit(f"[{stage}] {message}")
        if not self.job:
            self.idle.emit()

    def select_all(self, replacing=False):
        self.send_shortcut("A")
        self.replacing = replacing
        self.phase = "selected"
        self.deadline = time.monotonic() + .06

    def send_shortcut(self, letter):
        self.trace("shortcut", key=letter)
        native.shortcut(letter, self.target)

    def tick(self):
        try:
            if not self.manual and native.focus_identity() != self.target:
                self.cancel("窗口或输入焦点已切换，已取消替换。")
                return
            now = time.monotonic()
            if self.phase == "release":
                if native.keys_released():
                    self.select_all()
                elif now > self.deadline:
                    self.cancel("按键未松开，已取消输入翻译。")
            elif self.phase == "selected" and now >= self.deadline:
                if self.replacing:
                    self.paste()
                    return
                self.copy_marker = "ScreenLingo-copy-" + uuid.uuid4().hex
                self.clipboard.setText(self.copy_marker)
                self.owned_sequence = native.sequence()
                self.observed_sequence = native.sequence()
                self.send_shortcut("C")
                self.phase = "copy"
                self.deadline = time.monotonic() + 1
            elif self.phase == "copy":
                seq = native.sequence()
                if seq != self.observed_sequence:
                    self.trace("clipboard_changed", owner_pid=native.clipboard_pid(), replacing=self.replacing)
                    owner = native.clipboard_pid()
                    if owner != self.target[1] and owner != 0:
                        self.cancel("复制来源无法核实（剪贴板可能无所有者或由其他进程提供），已取消替换。请使用手动剪贴板模式。")
                        return
                    self.owned_sequence = self.observed_sequence = seq
                    text = self.clipboard.text()
                    if text == self.copy_marker:
                        if now > self.deadline:
                            self.cancel("游戏未复制聊天文字，已恢复剪贴板。请改用手动模式。")
                        return
                    self.original = text
                    self.launch()
                elif now > self.deadline:
                    self.cancel("未复制到聊天文字。请确认聊天框已打开，或改用手动复制粘贴模式。")
            elif self.phase == "translating" and self.manual and not self.clipboard_unchanged():
                self.cancel("剪贴板内容已变化，已取消自动替换。")
        except RuntimeError as exc:
            self.cancel(str(exc))

    def launch(self):
        self.trace("translation_start", chars=len(self.original))
        if not self.original.strip() or len(self.original) > 2000:
            self.cancel("请输入 1–2000 字符；空内容不会提交翻译。")
            return
        self.phase = "translating"
        self.clipboard_snapshot = self.snapshot()
        self.timer.start()
        self.message.emit("正在翻译输入文字…")
        self.job = InputJob(self.original, self.options, self)
        self.job.result.connect(self.translated)
        self.job.failed.connect(lambda message: self.cancel(message) if self.phase != "idle" else None)
        self.job.finished.connect(self.finished)
        self.job.start()

    def translated(self, text):
        self.trace("translation_returned", chars=len(text))
        if self.phase != "translating":
            return
        if self.manual and not self.clipboard_unchanged():
            self.cancel("剪贴板内容已变化，已取消替换。")
            return
        # A paste must not contain line breaks/control characters that some games submit.
        self.output = " ".join(text.split())
        if not self.output or len(self.output) > 4000 or any(ord(c) < 32 for c in self.output):
            self.cancel("译文为空或过长，未替换输入文字。")
            return
        try:
            if self.manual:
                self.clipboard.setText(self.output)
                self.complete("译文已复制，请手动 Ctrl+V 粘贴，确认后发送。")
            elif native.focus_identity() != self.target:
                self.cancel("窗口或输入焦点已切换，已取消替换。")
            else:
                self.select_all(replacing=True)
        except RuntimeError as exc:
            self.cancel(str(exc))

    def paste(self):
        if native.focus_identity() != self.target or not native.keys_released():
            self.cancel("输入焦点或按键状态已变化，已取消替换。")
            return
        self.clipboard.setText(self.output)
        self.owned_sequence = native.sequence()
        self.send_shortcut("V")
        self.complete("已请求粘贴译文，请在聊天框确认后自行发送。译文保留在剪贴板。")

    def snapshot(self):
        mime = self.clipboard.mimeData()
        return tuple(sorted((fmt, bytes(mime.data(fmt))) for fmt in mime.formats())) if mime else ()

    def clipboard_unchanged(self):
        sequence = native.sequence()
        if sequence == self.observed_sequence:
            return True
        # Reading delayed-rendered clipboard data can itself change its sequence.
        # Only permit an identical payload; real external changes still cancel.
        if self.snapshot() != self.clipboard_snapshot:
            return False
        self.observed_sequence = native.sequence()
        self.trace("clipboard_sequence_only")
        return True

    def complete(self, message):
        self.trace("complete")
        self.phase = "idle"
        self.timer.stop()
        self.backup = None
        self.owned_sequence = None
        self.message.emit(message)
        if not self.job:
            self.idle.emit()

    def finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        if self.phase == "idle":
            self.idle.emit()
