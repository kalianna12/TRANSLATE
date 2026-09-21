"""Controlled fixtures only: never send desktop contents to a translation provider."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication
from screenlingo.ocr import MultilingualOCR

from screenlingo.core import Translator
from screenlingo.ui import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "artifacts"
    output.mkdir(exist_ok=True)
    fixture = Image.new("RGB", (720, 180), "white")
    draw = ImageDraw.Draw(fixture)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
    draw.text((30, 30), "Hello world", font=font, fill="black")
    draw.text((30, 95), "Screen translation is ready", font=font, fill="black")
    ocr = MultilingualOCR()
    result = ocr(np.asarray(fixture)[:, :, ::-1].copy())
    texts = [line[1] for line in result or []]
    assert any("Hello" in text for text in texts), texts
    print("OCR PASS:", texts, "timing:", ocr.last_metrics)
    if args.network:
        translator = Translator()
        try:
            translated = translator.translate(texts)
            assert len(translated) == len(texts)
            assert any(any("\u4e00" <= char <= "\u9fff" for char in text) for text in translated)
            print("GOOGLE PASS:", ascii(translated))
        finally:
            translator.close()
    app = QApplication([])
    app.setOrganizationName("ScreenLingoTest")
    app.setApplicationName("SmokeTest")
    window = MainWindow()
    window.tray_only = True
    for editor, key in [(window.region_key, "Ctrl+Alt+F20"), (window.full_key, "Ctrl+Alt+F21"),
                        (window.stop_key, "Ctrl+Alt+F22")]:
        editor.setKeySequence(QKeySequence(key))
    window.show()

    def verify():
        try:
            assert window.isVisible()
            assert window.grab().save(str(output / "settings.png"))
            assert window.tray.isVisible()
            window.close()
            assert not window.isVisible() and not window.closing
            window.tray_menu.aboutToShow.emit()
            assert window.source_actions[0][0].isChecked()
            print("QT PASS: settings rendered to artifacts/settings.png")
        finally:
            window.quit_app()

    QTimer.singleShot(1000, verify)
    app.exec()


if __name__ == "__main__":
    main()
