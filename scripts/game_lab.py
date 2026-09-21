"""Borderless animated chat fixture and live capture/translation integration verification."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPixmap, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from screenlingo.core import Region
from screenlingo.ui import MainWindow
from screenlingo.win32 import focus_window, foreground_window, window_rect, user32


PAGES = [
    [("Arial", "Enemy spotted at the entrance."),
     ("Yu Gothic", "次のラウンドまで待ってください。"),
     ("Malgun Gothic", "같이 게임해 주셔서 감사합니다.")],
    [("Arial", "I need help. Cover me!"),
     ("Yu Gothic", "一緒に遊んでくれてありがとう。"),
     ("Malgun Gothic", "다음 라운드까지 기다려 주세요.")],
]


class GameLab(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScreenLingo Borderless Game Lab")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(860, 460)
        self.page = 0
        self.tick = 0
        self.clicks = 0
        self.chat = QRect(35, 200, 750, 175)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)

    def animate(self):
        self.tick += 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#182638"))
        # Real window animation, including a changing dark background beneath chat text.
        painter.fillRect(QRect((self.tick * 8) % self.width(), 95, 50, 80), QColor("#438f9c"))
        painter.setPen(QColor("#8cdcca"))
        painter.setFont(QFont("Arial", 17))
        painter.drawText(35, 48, "BORDERLESS GAME LAB / local synthetic chat")
        painter.setFont(QFont("Arial", 11))
        painter.drawText(35, 80, "Ctrl+T: select chat | Space: new messages | Esc: exit translation")
        shade = 18 + (self.tick % 20)
        painter.fillRect(self.chat, QColor(shade, shade + 6, shade + 15))
        for i, (family, text) in enumerate(PAGES[self.page]):
            font = QFont(family)
            font.setPixelSize(23)
            painter.setFont(font)
            painter.setPen(QColor("#f1f4fa"))
            painter.drawText(self.chat.x() + 14, self.chat.y() + 40 + i * 50, text)
        painter.setFont(QFont("Arial", 11))
        painter.setPen(QColor("#8cdcca"))
        painter.drawText(35, 420, f"Page: {self.page + 1} | Click-through events: {self.clicks} | F10: close lab")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.page = 1 - self.page
            self.update()
        if event.key() == Qt.Key.Key_F10:
            self.close()

    def mousePressEvent(self, event):
        self.clicks += 1


class ExternalFixture:
    """The test target runs in another process, as real games do."""
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="screenlingo-lab-")
        self.directory = Path(self.temp.name)
        self.process = subprocess.Popen([sys.executable, __file__, "--ipc", str(self.directory)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while not (self.directory / "ready.json").exists():
            if time.monotonic() > deadline or self.process.poll() is not None:
                raise RuntimeError("External fixture did not start")
            time.sleep(0.05)
        self.info = json.loads((self.directory / "ready.json").read_text())
        self.chat = QRect(*self.info["chat"])
        self.page = 0
        self.sequence = 0

    def command(self, **kwargs):
        self.sequence += 1
        path = self.directory / "command.tmp"
        path.write_text(json.dumps(dict(seq=self.sequence, **kwargs)))
        path.replace(self.directory / "command.json")

    def winId(self):
        return self.info["hwnd"]

    def width(self):
        return self.info["width"]

    def height(self):
        return self.info["height"]

    def mapToGlobal(self, point):
        return QPoint(*self.info["logical_origin"]) + point

    def show(self):
        pass

    def raise_(self):
        focus_window(self.winId())

    def activateWindow(self):
        focus_window(self.winId())

    def isVisible(self):
        return True

    def isEnabled(self):
        return True

    def x(self):
        return self.info["logical_origin"][0]

    def y(self):
        return self.info["logical_origin"][1]

    def move(self, x, y):
        self.command(move=[x, y])

    def update(self):
        self.command(page=self.page)

    def grab(self):
        pixmap = QPixmap(str(self.directory / "fixture.png"))
        pixmap.setDevicePixelRatio(pixmap.width() / self.width())
        return pixmap

    def close(self):
        self.command(close=True)

    def cleanup(self):
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)
        self.temp.cleanup()


def setup_ipc(fixture, directory):
    state = {"seq": 0}

    def ready():
        origin = fixture.mapToGlobal(QPoint(0, 0))
        data = {"hwnd": int(fixture.winId()), "width": fixture.width(), "height": fixture.height(),
                "chat": [fixture.chat.x(), fixture.chat.y(), fixture.chat.width(), fixture.chat.height()],
                "logical_origin": [origin.x(), origin.y()]}
        fixture.grab().save(str(directory / "fixture.png"))
        temp = directory / "ready.tmp"
        temp.write_text(json.dumps(data))
        temp.replace(directory / "ready.json")

    def poll():
        try:
            command = json.loads((directory / "command.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if command["seq"] == state["seq"]:
            return
        state["seq"] = command["seq"]
        if command.get("close"):
            fixture.close()
            return
        if "move" in command:
            fixture.move(*command["move"])
        if "page" in command:
            fixture.page = command["page"]
            fixture.update()
            QTimer.singleShot(50, lambda: fixture.grab().save(str(directory / "fixture.png")))

    fixture.ipc_timer = QTimer(fixture)
    fixture.ipc_timer.timeout.connect(poll)
    fixture.ipc_timer.start(30)
    QTimer.singleShot(400, ready)


class Verification:
    def __init__(self, app, fixture, settings):
        self.app, self.fixture, self.settings = app, fixture, settings
        self.rows = []
        self.started = None
        self.phase = 0
        self.finished = False
        self.error = None
        self.watchdog = QTimer()
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(lambda: self.fail("Timed out waiting for the real translation pipeline"))
        self.watchdog.start(60000)
        QTimer.singleShot(800, self.start)

    def start(self):
        try:
            self.settings.hide()
            self.fixture.show()
            self.fixture.raise_()
            user32.SetWindowPos(int(self.fixture.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            focus_window(int(self.fixture.winId()))
            self.old_cursor = QCursor.pos()
            QCursor.setPos(self.fixture.mapToGlobal(self.fixture.chat.center()))
            self.settings.interval.setValue(250)
            self.settings.realtime.setChecked(True)
            self.settings.on_hotkey(1)
            QTimer.singleShot(250, self.drag_selection)
        except Exception:
            self.fail(traceback.format_exc())

    def drag_selection(self):
        try:
            selector = self.settings.selector
            assert selector is not None and selector.isVisible()
            top_left = self.fixture.mapToGlobal(self.fixture.chat.topLeft()) - selector.geometry().topLeft()
            bottom_right = top_left + QPoint(self.fixture.chat.width() - 1, self.fixture.chat.height() - 1)
            self.started = time.perf_counter()
            QTest.mousePress(selector, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, top_left)
            QTest.mouseMove(selector, bottom_right)
            QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, bottom_right)
            QCursor.setPos(self.old_cursor)
            assert self.settings.worker is not None, self.settings.status.text()
            assert self.settings.target_hwnd == int(self.fixture.winId()), "Selected wrong window"
            self.settings.worker.result.connect(self.on_result)
            self.settings.worker.fault.connect(lambda token, message: self.fail(message))
            self.settings.worker.metrics.connect(self.on_metrics)
        except Exception:
            self.fail(traceback.format_exc())

    def on_metrics(self, token, metrics):
        if self.rows:
            self.rows[-1]["metrics"] = metrics

    def on_result(self, token, blocks):
        if self.finished or not blocks or not all(b.translated for b in blocks):
            return
        try:
            sources = [b.source for b in blocks]
            translations = [b.translated for b in blocks]
            assert len(blocks) == 3, f"Expected 3 chat lines, got {sources}"
            assert any("Enemy" in s or "Cover" in s for s in sources), sources
            assert any(any("\u3040" <= c <= "\u30ff" for c in s) for s in sources), sources
            assert any(any("\uac00" <= c <= "\ud7af" for c in s) for s in sources), sources
            assert all(any("\u4e00" <= c <= "\u9fff" for c in text) for text in translations), translations
            self.rows.append({"phase": self.phase, "latency_ms": round((time.perf_counter() - self.started) * 1000, 1),
                              "source": sources, "translation": translations})
            print("LIVE PASS phase", self.phase, "latency_ms", self.rows[-1]["latency_ms"], flush=True)
            if self.phase == 0:
                self.phase = 1
                QTimer.singleShot(600, self.change_page)
            elif self.phase == 1:
                self.phase = 2
                QTimer.singleShot(500, self.verify_layers)
        except Exception:
            self.fail(traceback.format_exc())

    def change_page(self):
        self.fixture.page = 1
        self.started = time.perf_counter()
        self.fixture.update()

    def verify_layers(self):
        try:
            overlay = self.settings.overlay
            assert overlay.isVisible(), "Overlay is hidden over target window"
            assert foreground_window() != int(overlay.winId()), "Overlay stole keyboard focus"
            # Native hit testing verifies the overlay does not receive clicks.
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            bounds = window_rect(int(overlay.winId()))
            target_bounds = window_rect(int(self.fixture.winId()))
            scale = target_bounds[2] / self.fixture.width()
            assert abs(bounds[0] - target_bounds[0] - self.fixture.chat.x() * scale) <= 2
            assert abs(bounds[1] - target_bounds[1] - self.fixture.chat.y() * scale) <= 2
            assert abs(bounds[2] - self.fixture.chat.width() * scale) <= 2
            packed = ((bounds[1] + 20) << 16) | ((bounds[0] + 20) & 0xFFFF)
            hit = user32.SendMessageW(int(overlay.winId()), 0x84, 0, packed)
            assert hit == -1, f"Expected HTTRANSPARENT, got {hit}"
            # Validate the screen-capture backend's exclusion using only the lab's chat rectangle.
            from screenlingo.capture import ScreenCapture
            from screenlingo.ocr import MultilingualOCR
            screen_capture = ScreenCapture(Region(*bounds))
            try:
                captured = screen_capture.grab()
            finally:
                screen_capture.close()
            detected = MultilingualOCR()(captured)
            assert any("Cover" in line[1] for line in detected), "Screen capture re-captured the overlay"
            # Composite only our controlled fixture and overlay, never the user's desktop.
            pixmap = self.fixture.grab()
            painter = QPainter(pixmap)
            painter.drawPixmap(self.fixture.chat.topLeft(), overlay.grab())
            painter.end()
            Path("artifacts").mkdir(exist_ok=True)
            assert pixmap.save("artifacts/game-lab-overlay.png")
            old = window_rect(int(overlay.winId()))
            self.fixture.move(self.fixture.x() + 20, self.fixture.y() + 10)
            self.old_overlay = old
            QTimer.singleShot(500, self.verify_move)
        except Exception:
            self.fail(traceback.format_exc())

    def verify_move(self):
        try:
            new = window_rect(int(self.settings.overlay.winId()))
            assert new[:2] != self.old_overlay[:2], "Overlay did not follow moved window"
            assert new[2:] == self.old_overlay[2:], "Overlay size changed unexpectedly"
            self.settings.restore()
            self.settings.move(self.fixture.mapToGlobal(self.fixture.chat.topLeft()))
            user32.SetWindowPos(int(self.settings.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            QTimer.singleShot(400, self.verify_alt_tab)
        except Exception:
            self.fail(traceback.format_exc())

    def verify_alt_tab(self):
        try:
            assert not self.settings.overlay.isVisible(), "Overlay covers unrelated foreground window"
            assert not self.settings.hotkeys.active, "Exit key remained grabbed outside game"
            self.settings.hide_to_tray()
            QTimer.singleShot(150, self.return_to_game)
        except Exception:
            self.fail(traceback.format_exc())

    def verify_escape(self):
        try:
            assert self.settings.overlay.isVisible(), f"Overlay did not return: fg={foreground_window()} target={int(self.fixture.winId())} overlay={int(self.settings.overlay.winId())} settings={int(self.settings.winId())} active={self.settings.translation_active} status={self.settings.status.text()}"
            assert self.settings.hotkeys.active
            # Exercise the native WM_HOTKEY handler deterministically without injecting game input.
            msg = wintypes.MSG()
            msg.message, msg.wParam = 0x0312, 3
            handled, _ = self.settings.hotkeys.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
            assert handled
            assert not self.settings.overlay.isVisible()
            assert not self.settings.hotkeys.active
            assert foreground_window() != int(self.settings.overlay.winId())
            self.finish()
        except Exception:
            self.fail(traceback.format_exc())

    def return_to_game(self):
        self.fixture.raise_()
        self.fixture.activateWindow()
        focus_window(int(self.fixture.winId()))
        QTimer.singleShot(400, self.verify_escape)

    def fail(self, message):
        if not self.finished:
            self.error = message
            print("LIVE FAIL:", ascii(message), flush=True)
            self.finish()

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.watchdog.stop()
        Path("artifacts").mkdir(exist_ok=True)
        Path("artifacts/game-lab-results.json").write_text(json.dumps({
            "passed": self.error is None, "error": self.error, "rows": self.rows,
            "checks": ["WGC HWND capture", "animated chat background", "English/Japanese/Korean to Chinese",
                       "hotkey starts selector", "mouse drag and physical DPI mapping",
                       "screen capture excludes translated overlay",
                       "new messages", "overlay input transparency", "overlay does not take focus", "window movement",
                       "occlusion hide/restore", "exit hotkey releases registration"],
            "scope": "Synthetic Qt borderless window in a separate process. CS2 and DJMAX not tested."}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.fixture.close()
        self.settings.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Runs the real Google translation pipeline on declared fixture text")
    parser.add_argument("--ipc", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(not args.verify)
    app.setOrganizationName("ScreenLingoTest")
    app.setApplicationName("GameLab")
    fixture = ExternalFixture() if args.verify else GameLab()
    fixture.show()
    verification = None
    if args.verify:
        settings = MainWindow()
        for editor, key in [(settings.region_key, "Ctrl+Alt+F20"), (settings.full_key, "Ctrl+Alt+F21"),
                            (settings.stop_key, "Ctrl+Alt+F22")]:
            editor.setKeySequence(QKeySequence(key))
        from screenlingo.warmup import Preparation
        Preparation(settings.options()).run()
        verification = Verification(app, fixture, settings)
    elif args.ipc:
        setup_ipc(fixture, args.ipc)
    app.exec()
    if args.verify:
        fixture.cleanup()
    if verification and verification.error:
        sys.exit(1)


if __name__ == "__main__":
    main()
