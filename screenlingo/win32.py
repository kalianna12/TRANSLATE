"""Small, typed Win32 boundary for capture affinity and native hotkeys."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter


IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def foreground_window():
    return int(user32.GetForegroundWindow() or 0)


def focus_window(hwnd):
    if hwnd and user32.IsWindow(hwnd):
        user32.SetForegroundWindow(hwnd)


def window_at(x, y, exclude_hwnd=0):
    if exclude_hwnd:
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @callback_type
        def visit(hwnd, extra):
            if int(hwnd) == int(exclude_hwnd) or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            if user32.GetWindowLongPtrW(hwnd, -20) & 0x20:
                return True
            bounds = window_rect(hwnd)
            if bounds and bounds[0] <= x < bounds[0] + bounds[2] and bounds[1] <= y < bounds[1] + bounds[3]:
                found.append(int(hwnd))
                return False
            return True
        user32.EnumWindows(visit, 0)
        return found[0] if found else 0
    handle = user32.WindowFromPoint(wintypes.POINT(x, y))
    return int(user32.GetAncestor(handle, 2) or handle or 0)


def window_rect(hwnd):
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    rect = wintypes.RECT()
    # WGC window frames omit the invisible resize border; use DWM visible bounds.
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def window_minimized(hwnd):
    return bool(user32.IsIconic(hwnd))


def target_region_visible(hwnd, rect, overlay_hwnd):
    """Check actual occlusion rather than focus; tray utilities can own foreground invisibly."""
    x, y, width, height = rect
    pad = min(4, width // 3, height // 3)
    points = [(x + width // 2, y + height // 2), (x + pad, y + pad),
              (x + width - pad - 1, y + pad), (x + pad, y + height - pad - 1),
              (x + width - pad - 1, y + height - pad - 1)]
    top = [None] * len(points)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(candidate, extra):
        if int(candidate) == int(overlay_hwnd) or not user32.IsWindowVisible(candidate) or user32.IsIconic(candidate):
            return True
        if user32.GetWindowLongPtrW(candidate, -20) & 0x20:  # transparent helper layers
            return True
        bounds = window_rect(candidate)
        if bounds:
            left, upper, w, h = bounds
            for i, (px, py) in enumerate(points):
                if top[i] is None and left <= px < left + w and upper <= py < upper + h:
                    top[i] = int(candidate)
        return any(value is None for value in top)

    user32.EnumWindows(visit, 0)
    return all(value == int(hwnd) for value in top)


def position_overlay(hwnd, rect):
    x, y, width, height = rect
    user32.SetWindowPos(int(hwnd), wintypes.HWND(-1), x, y, width, height, 0x0010 | 0x0040)


def make_overlay_nonactivating(hwnd):
    style = user32.GetWindowLongPtrW(int(hwnd), -20)
    user32.SetWindowLongPtrW(int(hwnd), -20, (style | 0x08000000 | 0x00000020 | 0x00080000 | 0x80) & ~0x40000)
    user32.SetWindowLongPtrW(int(hwnd), -8, 0)


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def physical_monitor(hwnd):
    if not IS_WINDOWS:
        raise RuntimeError("此版本需要 Windows 10 2004 或更新版本。")
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    monitor = user32.MonitorFromWindow(int(hwnd), 2)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    r = info.rcMonitor
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def exclude_from_capture(hwnd):
    if not IS_WINDOWS or sys.getwindowsversion().build < 19041:
        return False
    return bool(user32.SetWindowDisplayAffinity(int(hwnd), 0x11))


def parse_hotkey(sequence):
    parts = sequence.upper().replace(" ", "").split("+")
    modifiers = {"CTRL": 0x2, "ALT": 0x1, "SHIFT": 0x4, "META": 0x8, "WIN": 0x8}
    mask = 0x4000  # MOD_NOREPEAT
    for part in parts[:-1]:
        if part not in modifiers:
            raise ValueError("热键支持 Ctrl、Alt、Shift、Win 加字母、数字或 F1–F24。")
        mask |= modifiers[part]
    key = parts[-1]
    if key in ("ESC", "ESCAPE"):
        return mask, 0x1B
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("热键末尾请选择字母、数字或 F1–F24。")
    if mask == 0x4000:
        raise ValueError("热键至少需要一个修饰键，例如 Ctrl+T。")
    return mask, vk


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app, callback):
        super().__init__()
        self.app = app
        self.callback = callback
        self.bindings = {}
        self.configured = {}
        self.active = False
        app.installNativeEventFilter(self)

    def configure(self, bindings):
        parsed = {key: parse_hotkey(value) for key, value in bindings.items()}
        if len(set(parsed.values())) != len(parsed):
            raise ValueError("三个热键不能相同。")
        if not IS_WINDOWS:
            raise ValueError("全局热键仅支持 Windows。")
        old = self.bindings.copy()
        self.clear()
        try:
            for key, (mod, vk) in parsed.items():
                if key == 3 and not self.active:
                    continue
                if not user32.RegisterHotKey(None, key, mod, vk):
                    raise ValueError(f"{bindings[key]} 已被其他程序占用，请换一个热键。")
                self.bindings[key] = (mod, vk)
            self.configured = parsed
        except ValueError:
            self.clear()
            for key, (mod, vk) in old.items():
                if user32.RegisterHotKey(None, key, mod, vk):
                    self.bindings[key] = (mod, vk)
            raise

    def set_active(self, active):
        if active and not self.active:
            mod, vk = self.configured.get(3, (0x4000, 0x1B))
            if not user32.RegisterHotKey(None, 3, mod, vk):
                raise ValueError("退出热键被占用，请在设置中更换。")
            self.bindings[3] = (mod, vk)
        elif not active and self.active:
            user32.UnregisterHotKey(None, 3)
            self.bindings.pop(3, None)
        self.active = active

    def clear(self):
        if IS_WINDOWS:
            for key in self.bindings:
                user32.UnregisterHotKey(None, key)
        self.bindings.clear()

    def nativeEventFilter(self, event_type, message):
        if IS_WINDOWS:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and int(msg.wParam) in self.bindings:
                self.callback(int(msg.wParam))
                return True, 0
        return False, 0
