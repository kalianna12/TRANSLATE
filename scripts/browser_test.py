"""Real isolated Chromium window -> actual selector -> capture -> OCR -> Google -> overlay."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screenlingo.core import Region
from screenlingo.capture import WindowCapture
from screenlingo.ui import MainWindow
from screenlingo.win32 import user32, window_rect, foreground_window, focus_window, physical_monitor
from vertical_fixture import vertical_fixture


class BrowserTest:
    def __init__(self, app, args):
        self.app = app
        self.args = args
        self.output = Path(__file__).resolve().parents[1] / "artifacts"
        self.output.mkdir(exist_ok=True)
        if args.fixture == "manga":
            fixture_image = vertical_fixture()
            self.expected_lines = 1
        else:
            from document_benchmark import fixture, SAMPLES
            fixture_image = fixture(args.fixture)
            self.expected_lines = len(SAMPLES[args.fixture])
        fixture_image.save(self.output / "browser-fixture.png")
        self.title = "ScreenLingo-Vertical-Test-" + uuid.uuid4().hex[:8]
        self.html = self.output / "vertical-browser.html"
        image_style = "" if args.fixture == "manga" else f"width:{fixture_image.width / app.primaryScreen().devicePixelRatio()}px;"
        self.html.write_text(f'<meta charset="utf-8"><title>{self.title}</title>'
                             '<body style="background:#263449;margin:30px;color:white;font-family:sans-serif">'
                             '<h2>ScreenLingo vertical Japanese test</h2>'
                             '<p>Synthetic sample / no private page content</p>'
                             f'<img src="browser-fixture.png" style="{image_style}border:8px solid #ff00ff">', encoding="utf-8")
        profile = self.output / "browser-test-profile-current"
        self.browser = subprocess.Popen([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "--user-data-dir=" + str(profile), "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
            "--window-size=1100,850", "--window-position=60,20",
            "--app=" + self.html.as_uri()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.window = MainWindow()
        self.window.source.setCurrentIndex(self.window.source.findData(args.source))
        original_options = self.window.options
        self.window.options = lambda: {**original_options(), "progressive": not args.baseline}
        self.window.overlay.translated_painted.connect(self.on_painted)
        self.paint_latency = None
        self.full_paint_latency = None
        self.metrics = []
        if args.warm:
            from screenlingo.warmup import Preparation
            preparation = Preparation(self.window.options())
            preparation.run()
        if args.baseline:
            from screenlingo.ocr import get_ocr
            get_ocr().document_fast_path = False
        for edit, key in [(self.window.region_key, "Ctrl+Alt+F20"), (self.window.full_key, "Ctrl+Alt+F21"),
                          (self.window.stop_key, "Ctrl+Alt+F22")]:
            edit.setKeySequence(QKeySequence(key))
        self.hwnd = 0
        self.phase = "starting"
        self.messages = []
        self.result = None
        self.failed = None
        self.deadline = time.monotonic() + 50
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.start(500)

    def find_window(self):
        handles = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        @callback_type
        def enum(hwnd, extra):
            name = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, name, 512)
            if self.title in name.value and user32.IsWindowVisible(hwnd):
                handles.append(int(hwnd))
            return True
        user32.EnumWindows(enum, 0)
        return handles[0] if handles else 0

    def poll(self):
        try:
            if time.monotonic() > self.deadline:
                raise RuntimeError("Timed out: " + self.window.status.text())
            if self.phase == "starting":
                self.hwnd = self.find_window()
                if self.hwnd:
                    self.phase = "loading"
                    QTimer.singleShot(1500, self.select_image)
        except Exception as exc:
            self.finish(str(exc))

    def select_image(self):
        try:
            focus_window(self.hwnd)
            self.bounds = window_rect(self.hwnd)
            # A synthetic QTest drag cannot bypass Windows' foreground-stealing policy.
            # Keep only our isolated fixture above unrelated applications for this test.
            user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            capture = WindowCapture(self.hwnd, Region(*self.bounds))
            try:
                ready_deadline = time.monotonic() + 3
                while True:
                    image = capture.grab()
                    marker = (image[:, :, 0] > 220) & (image[:, :, 2] > 220) & (image[:, :, 1] < 40)
                    ys, xs = np.where(marker)
                    if len(xs) or time.monotonic() >= ready_deadline:
                        break
                    time.sleep(.05)
            finally:
                capture.close()
            if not len(xs):
                import cv2
                cv2.imwrite(str(self.output / "browser-load-failure.png"), image)
                raise RuntimeError("Browser fixture has not rendered the image marker")
            # Select just inside the magenta border; retain ample whitespace around the text.
            self.region = Region(self.bounds[0] + int(xs.min()) + 15, self.bounds[1] + int(ys.min()) + 15,
                                 int(xs.max() - xs.min()) - 29, int(ys.max() - ys.min()) - 29)
            import cv2
            cv2.imwrite(str(self.output / f"browser-source-{self.args.fixture}.png"), image[int(ys.min()) + 15:int(ys.max()) - 14,
                                                                        int(xs.min()) + 15:int(xs.max()) - 14])
            self.old_cursor = QCursor.pos()
            screen = QApplication.primaryScreen()
            QCursor.setPos(screen.geometry().center())
            self.window.on_hotkey(1)
            self.phase = "selecting"
            QTimer.singleShot(200, self.drag)
        except Exception as exc:
            self.finish(str(exc))

    def drag(self):
        try:
            selector = self.window.selector
            assert selector is not None
            x, y, width, height = physical_monitor(selector.winId())
            sx, sy = selector.width() / width, selector.height() / height
            region = self.region
            p1 = QPoint(round((region.left - x) * sx), round((region.top - y) * sy))
            p2 = p1 + QPoint(round(region.width * sx) - 1, round(region.height * sy) - 1)
            QTest.mousePress(selector, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
            QTest.mouseMove(selector, p2)
            self.started = time.perf_counter()
            QTest.mouseRelease(selector, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p2)
            QCursor.setPos(self.old_cursor)
            assert self.window.worker is not None, self.window.status.text()
            assert self.window.target_hwnd == self.hwnd, "Selection bound to a different window"
            print("TARGET", self.window.target_hwnd == self.hwnd, "DWM", self.bounds, "REGION", vars(region), flush=True)
            self.window.worker.status.connect(self.status)
            self.window.worker.result.connect(self.on_result)
            self.window.worker.metrics.connect(self.on_metrics)
            self.window.worker.fatal.connect(lambda token, message: self.finish(message))
            self.window.worker.fault.connect(lambda token, message: self.finish(message))
            self.phase = "running"
        except Exception as exc:
            self.finish(str(exc))

    def status(self, token, message):
        self.messages.append(message)
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW(foreground_window(), class_name, 256)
        print("STATUS", ascii(message), "FOCUS", foreground_window(), "TARGET", self.hwnd,
              "SETTINGS", int(self.window.winId()), "OVERLAY", int(self.window.overlay.winId()), "CLASS", class_name.value, flush=True)

    def on_result(self, token, blocks):
        if blocks and all(b.translated for b in blocks):
            self.result = [{"source": b.source, "translated": b.translated,
                            "box": [b.x, b.y, b.width, b.height]} for b in blocks]
            self.latency = (time.perf_counter() - self.started) * 1000

    def on_metrics(self, token, data):
        self.metrics.append(data)
        if self.result and self.phase == "running":
            self.phase = "verifying"
            QTimer.singleShot(500, self.verify)

    def on_painted(self):
        if self.paint_latency is None and hasattr(self, "started"):
            self.paint_latency = (time.perf_counter() - self.started) * 1000
        if self.full_paint_latency is None and self.result and len(self.result) >= self.expected_lines:
            self.full_paint_latency = (time.perf_counter() - self.started) * 1000

    def verify(self):
        try:
            assert self.window.overlay.isVisible(), f"Overlay hidden: foreground={foreground_window()} target={self.hwnd}"
            # Invisible tray windows may take foreground; a still-visible browser must retain its overlay.
            assert self.window.overlay.grab().save(str(self.output / f"browser-{self.args.fixture}-overlay.png"))
            if self.args.fixture == "manga":
                assert any("三者面談" in b["source"] and "東大" in b["source"] for b in self.result), self.result
            else:
                from document_benchmark import SAMPLES
                from benchmark import normalized, edit_distance
                actual = normalized("".join(b["source"] for b in self.result))
                reference = normalized("".join(SAMPLES[self.args.fixture]))
                self.char_errors = edit_distance(actual, reference)
                self.char_count = len(reference)
                assert len(self.result) == self.expected_lines, "Page lines missing"
                assert self.char_errors / self.char_count < .02, "Document OCR character error exceeds 2%"
            self.finish()
        except Exception as exc:
            self.finish(str(exc))

    def finish(self, error=None):
        if self.phase == "finished":
            return
        self.phase = "finished"
        self.failed = error
        self.timer.stop()
        data = {"passed": error is None, "error": error, "messages": self.messages,
                "latency_ms": getattr(self, "latency", None), "blocks": self.result,
                "paint_latency_ms": self.paint_latency, "metrics": self.metrics,
                "full_paint_latency_ms": self.full_paint_latency, "progressive": not self.args.baseline,
                "char_errors": getattr(self, "char_errors", None), "char_count": getattr(self, "char_count", None),
                "source_mode": self.args.source, "prewarmed": self.args.warm,
                "fixture": f"Synthetic {self.args.fixture} in isolated Edge app window, not the user's original image."}
        (self.output / self.args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT", ascii(data), flush=True)
        if self.hwnd:
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW(self.hwnd, 0x10, 0, 0)
        self.window.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--source", choices=["auto", "ja", "en", "ko"], default="auto")
    parser.add_argument("--fixture", choices=["manga", "ja", "en", "ko"], default="manga")
    parser.add_argument("--baseline", action="store_true", help="Disable projection and progressive OCR for comparison")
    parser.add_argument("--output", default="browser-test-results.json")
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("ScreenLingoTest")
    app.setApplicationName("BrowserTest")
    test = BrowserTest(app, args)
    app.exec()
    sys.exit(1 if test.failed else 0)
