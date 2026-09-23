"""Ordinary Win32 copy/paste shortcuts; no game hooks, injection or drivers."""
import ctypes
from ctypes import wintypes as W
from .win32 import user32, foreground_window


class KeyboardInput(ctypes.Structure):
    _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("extra", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("data", W.DWORD),
                ("flags", W.DWORD), ("time", W.DWORD), ("extra", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("value", InputUnion)]


class GUIInfo(ctypes.Structure):
    _fields_ = [("size", W.DWORD), ("flags", W.DWORD), ("active", W.HWND),
                ("focus", W.HWND), ("capture", W.HWND), ("menu", W.HWND),
                ("move", W.HWND), ("caret", W.HWND), ("rect", W.RECT)]


user32.SendInput.argtypes = [W.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = W.UINT
user32.GetGUIThreadInfo.argtypes = [W.DWORD, ctypes.POINTER(GUIInfo)]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetClipboardSequenceNumber.restype = W.DWORD
user32.GetClipboardOwner.restype = W.HWND


def window_pid(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def focus_identity():
    hwnd = foreground_window()
    pid = W.DWORD()
    thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    info = GUIInfo()
    info.size = ctypes.sizeof(info)
    if not hwnd or not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return None
    return hwnd, pid.value, int(info.focus or hwnd)


def keys_released():
    # Never send shortcuts while a physical key/button is held.
    return not any(user32.GetAsyncKeyState(key) & 0x8000 for key in range(1, 255))


def sequence():
    return int(user32.GetClipboardSequenceNumber())


def clipboard_pid():
    return window_pid(user32.GetClipboardOwner())


def shortcut(letter, expected):
    if focus_identity() != expected or not keys_released():
        raise RuntimeError("输入焦点已变化或按键未松开，已取消替换。")
    events = (Input * 4)()
    for event, (key, up) in zip(events, [(0x11, False), (ord(letter), False),
                                       (ord(letter), True), (0x11, True)]):
        event.type = 1
        event.value.keyboard = KeyboardInput(key, 0, 2 if up else 0, 0, 0)
    sent = user32.SendInput(4, events, ctypes.sizeof(Input))
    if sent != 4:
        # Release only the keys this operation attempted to press.
        user32.SendInput(2, ctypes.cast(ctypes.byref(events, 2 * ctypes.sizeof(Input)), ctypes.POINTER(Input)), ctypes.sizeof(Input))
        raise RuntimeError("系统未接受复制/粘贴快捷键。请使用手动复制粘贴模式。")
