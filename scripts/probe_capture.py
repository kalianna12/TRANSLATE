"""Compare actual WGC frames and DWM bounds for a standard decorated test window."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel
from windows_capture import WindowsCapture
from screenlingo.win32 import window_rect

app = QApplication([])
window = QLabel("ScreenLingo capture geometry probe")
window.setWindowTitle("ScreenLingo capture geometry probe")
window.resize(500, 400)
window.show()
capture = None
control = None


def start():
    global capture, control
    print("DWM", window_rect(int(window.winId())), "client", window.width(), window.height(), flush=True)
    capture = WindowsCapture(window_hwnd=int(window.winId()), cursor_capture=False, draw_border=False)

    @capture.event
    def on_frame_arrived(frame, ctl):
        print("WGC", frame.width, frame.height, flush=True)
        ctl.stop()

    @capture.event
    def on_closed():
        pass

    control = capture.start_free_threaded()


QTimer.singleShot(400, start)
QTimer.singleShot(2500, app.quit)
app.exec()
if control:
    control.stop()
