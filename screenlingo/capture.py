"""Capture the source HWND itself, independent of screen overlays and occluding windows."""
import threading
import time
import sys

import mss
import numpy as np

from .win32 import window_rect, window_minimized, target_region_visible


class CaptureUnavailable(RuntimeError):
    pass


class WindowCapture:
    def __init__(self, hwnd, region, interval=100):
        from windows_capture import WindowsCapture
        bounds = window_rect(hwnd)
        if bounds is None:
            raise CaptureUnavailable("所选窗口已关闭，请重新框选。")
        self.hwnd = hwnd
        self.initial_bounds = bounds
        self.crop = (region.left - bounds[0], region.top - bounds[1], region.width, region.height)
        x, y, width, height = self.crop
        if x < 0 or y < 0 or x + width > bounds[2] or y + height > bounds[3]:
            raise CaptureUnavailable("框选范围必须完全位于同一个目标窗口内，请重新框选聊天窗。")
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.frame = None
        self.closed = False
        self.error = ""
        self.last_arrival = 0.0
        build = sys.getwindowsversion().build
        self.capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False,
                                      draw_border=False if build >= 22000 else None,
                                      minimum_update_interval=interval if build >= 26100 else None)

        @self.capture.event
        def on_frame_arrived(frame, control):
            try:
                # Always retain the newest frame. A static browser may send only a black
                # startup frame and one real frame; Python-side throttling lost that real frame.
                data = frame.frame_buffer
                if data.shape[1] != bounds[2] or data.shape[0] != bounds[3]:
                    self.error = "目标窗口尺寸已改变，请重新框选。"
                    self.ready.set()
                    return
                cropped = data[y:y + height, x:x + width, :3].copy()
                with self.lock:
                    self.frame = cropped
                    self.last_arrival = time.monotonic()
                self.ready.set()
            except Exception:
                self.error = "窗口采集失败，请重新框选。"
                self.ready.set()

        @self.capture.event
        def on_closed():
            self.closed = True
            self.ready.set()

        self.control = self.capture.start_free_threaded()

    def grab(self, cancelled=lambda: False):
        deadline = time.monotonic() + 5
        while not self.ready.wait(0.05):
            if cancelled():
                raise InterruptedError()
            if time.monotonic() > deadline:
                raise CaptureUnavailable("未收到窗口画面，请确认游戏处于无边框/窗口模式且没有最小化。")
        if self.closed or window_rect(self.hwnd) is None:
            raise CaptureUnavailable("目标窗口已关闭。")
        if self.error:
            raise CaptureUnavailable(self.error)
        if window_minimized(self.hwnd):
            return None
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def close(self):
        self.control.stop()


class ScreenCapture:
    def __init__(self, region):
        self.region = region
        self.capture = mss.mss()

    def grab(self, cancelled=lambda: False):
        return np.array(self.capture.grab(self.region.as_dict()))[:, :, :3].copy()

    def close(self):
        self.capture.close()


class CoordinatedScreenCapture:
    """Ask the GUI to hide its overlay and capture; never touch Qt from the worker."""
    def __init__(self, request):
        self.request = request

    def grab(self, cancelled=lambda: False):
        reply = {"ready": threading.Event(), "cancelled": cancelled}
        self.request(reply)
        deadline = time.monotonic() + 5
        while not reply["ready"].wait(0.05):
            if cancelled():
                raise InterruptedError()
            if time.monotonic() > deadline:
                reply["expired"] = True
                raise CaptureUnavailable("等待桌面截图超时，请重新框选。")
        if "error" in reply:
            raise CaptureUnavailable(reply["error"])
        return reply.get("frame")

    def close(self):
        pass


class PreviewThenWindowCapture:
    """Fast selection snapshot first; bind live HWND capture after presenting that result."""
    def __init__(self, hwnd, region):
        self.hwnd, self.region = hwnd, region
        self.initial_bounds = window_rect(hwnd)
        if not self.initial_bounds:
            raise CaptureUnavailable("所选窗口已关闭，请重新框选。")
        x, y, width, height = self.initial_bounds
        if region.left < x or region.top < y or region.left + region.width > x + width or region.top + region.height > y + height:
            raise CaptureUnavailable("框选范围必须完全位于同一个目标窗口内，请重新框选聊天窗。")
        self.screen = ScreenCapture(region)
        self.window = None

    def grab(self, cancelled=lambda: False):
        if self.window:
            return self.window.grab(cancelled)
        if window_rect(self.hwnd) != self.initial_bounds:
            raise CaptureUnavailable("窗口位置已改变，请重新框选。")
        if not target_region_visible(self.hwnd, tuple(vars(self.region).values()), 0):
            self.activate_window()
            return self.window.grab(cancelled)
        return self.screen.grab(cancelled)

    def activate_window(self):
        if self.window is None:
            self.window = WindowCapture(self.hwnd, self.region)

    def close(self):
        if self.window:
            self.window.close()
        self.screen.close()
