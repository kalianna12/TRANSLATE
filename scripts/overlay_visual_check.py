"""Offline dense-text visual fixture: no screenshots or translation API calls."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QRectF, QPoint
from PySide6.QtGui import QImage, QPainter, QFont, QColor
from PySide6.QtWidgets import QApplication
from screenlingo.core import Region, TextBlock
from screenlingo.overlay import TranslationOverlay

app = QApplication([])
width, height = 900, 430
blocks = []
original = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
original.fill(QColor(241, 248, 255))
painter = QPainter(original)
font = QFont("Arial")
font.setPixelSize(23)
painter.setFont(font)
painter.setPen(QColor(20, 24, 30))
for index, (src, dst) in enumerate([
    ("Enemy spotted at the entrance. Please wait for the next round.", "入口处发现敌人。请等待下一轮。"),
    ("I need help. Cover me! Thanks for playing.", "我需要帮助，掩护我！感谢一起游玩。"),
    ("The girl looked at the light. She was waiting for an answer.", "女孩望着灯光。她正在等待一个答案。"),
    ("We can read a dense paragraph without stacked shadows.", "密集段落也能清楚阅读，不再叠加一层层阴影。"),
    ("The original background remains visible around the text.", "文字周围保留原来的背景。"),
]):
    y = 45 + index * 43
    rect = QRectF(20, y, 850, 44)
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter), src)
    blocks.append(TextBlock(20, y, 850, 44, src, dst, (241, 248, 255), (24, 28, 36)))
painter.end()
original.save("artifacts/overlay-original.png")
overlay = TranslationOverlay()
overlay.region = Region(0, 0, width, height)
overlay.resize(width, height)
overlay.blocks = blocks
for style in ("blend", "shade"):
    overlay.display_style = style
    canvas = original.copy()
    paint = QPainter(canvas)
    overlay.render(paint, QPoint())
    paint.end()
    assert canvas.save("artifacts/overlay-" + style + "-qa.png")
overlay.close()
