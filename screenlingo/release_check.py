"""Offline packaged smoke test with isolated preferences and no provider calls."""
import json
from pathlib import Path


def run(output):
    import cv2
    import numpy as np
    import windows_capture
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication
    from .ocr import MultilingualOCR
    from .ui import MainWindow
    from .windows_settings import protect, unprotect
    app = QApplication([])
    app.setOrganizationName("ScreenLingoReleaseTest")
    app.setApplicationName("OfflineCheck")
    frame = np.full((120, 600, 3), 255, np.uint8)
    cv2.putText(frame, "Hello world", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    readings = MultilingualOCR()(frame, source="en")
    assert any("Hello" in row[1] for row in readings)
    assert unprotect(protect("test-only")) == "test-only"
    window = MainWindow()
    window.tray_only = True
    for edit, key in [(window.region_key, "Ctrl+Alt+F20"), (window.full_key, "Ctrl+Alt+F21"), (window.stop_key, "Ctrl+Alt+F22")]:
        edit.setKeySequence(QKeySequence(key))
    window.show()
    def finish():
        try:
            assert window.provider.findData("baidu") >= 0
            assert window.autostart.text()
            assert window.grab().save(str(Path(output).with_suffix(".png")))
            for index in range(window.tabs.count()):
                window.tabs.setCurrentIndex(index)
                app.processEvents()
                assert window.grab().save(str(Path(output).with_name(Path(output).stem + f"-tab{index}.png")))
            Path(output).write_text(json.dumps({"ocr": [r[1] for r in readings], "preferences": True,
                                               "dpapi": True, "capture_import": True}), encoding="utf-8")
        finally:
            window.quit_app()
    QTimer.singleShot(1000, finish)
    app.exec()
