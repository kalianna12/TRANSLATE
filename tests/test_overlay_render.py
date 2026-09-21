from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from screenlingo.core import Region, TextBlock
from screenlingo.overlay import TranslationOverlay


def render(style):
    app = QApplication.instance() or QApplication([])
    overlay = TranslationOverlay()
    overlay.region = Region(0, 0, 200, 80)
    overlay.resize(200, 80)
    overlay.display_style = style
    overlay.blocks = [TextBlock(10, 10, 100, 30, "a", " ", background=(240, 245, 250)),
                      TextBlock(60, 10, 100, 30, "b", " ", background=(240, 245, 250))]
    image = QImage(200, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    overlay.render(image)
    overlay.close()
    return image


def test_overlapping_shadows_do_not_accumulate_opacity():
    image = render("shade")
    assert image.pixelColor(20, 15).alpha() == image.pixelColor(80, 15).alpha()
    assert image.pixelColor(20, 15).alpha() == 224
    assert image.pixelColor(0, 0).alpha() == 0


def test_blend_uses_opaque_background_without_region_dimming():
    image = render("blend")
    assert image.pixelColor(80, 15).getRgb() == (240, 245, 250, 255)
    assert image.pixelColor(0, 0).alpha() == 0
