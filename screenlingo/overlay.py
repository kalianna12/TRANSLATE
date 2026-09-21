from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .core import Region
from .win32 import exclude_from_capture, physical_monitor, make_overlay_nonactivating, window_at


class RegionSelector(QWidget):
    selected = Signal(object, object)
    cancelled = Signal()

    def __init__(self, screen):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = None
        self.end = None
        self.target_hwnd = 0

    def open(self):
        self.show()
        exclude_from_capture(self.winId())
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 16, 28, 115))
        painter.setFont(QFont("Microsoft YaHei UI", 13))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRect(24, 24, self.width() - 48, 60), Qt.AlignmentFlag.AlignCenter,
                         "拖动鼠标框选翻译区域 · Esc 取消 · 在当前屏幕内选择")
        if self.start is not None:
            rect = QRect(self.start, self.end).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#66e0c0"), 2))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
            self.end = self.start
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancel()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            point = event.position().toPoint()
            self.end = QPoint(max(0, min(self.width() - 1, point.x())),
                              max(0, min(self.height() - 1, point.y())))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        local = QRect(self.start, self.end).normalized().intersected(self.rect())
        if local.width() < 16 or local.height() < 16:
            self.start = self.end = None
            self.update()
            return
        self.finish(local)

    def finish(self, local):
        x, y, width, height = physical_monitor(self.winId())
        sx, sy = width / self.width(), height / self.height()
        left, top = round(local.x() * sx), round(local.y() * sy)
        right, bottom = round((local.x() + local.width()) * sx), round((local.y() + local.height()) * sy)
        region = Region(x + left, y + top, right - left, bottom - top)
        logical = QRect(self.mapToGlobal(local.topLeft()), local.size())
        # Closing a tool window can reorder other applications during focus restoration.
        # Bind the visible source while the selection is still on screen.
        self.target_hwnd = window_at(region.left + region.width // 2, region.top + region.height // 2, self.winId())
        self.hide()
        self.selected.emit(region, logical)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()

    def cancel(self):
        self.hide()
        self.cancelled.emit()
        self.close()


class TranslationOverlay(QWidget):
    translated_painted = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Window | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.blocks = []
        self.region = None
        self.shade_opacity = 88
        self.display_style = "blend"
        self.message = ""

    def prepare(self, region, logical, window_capture=False, shade_opacity=88):
        self.region = region
        self.shade_opacity = shade_opacity
        self.blocks = []
        self.message = "正在启动翻译…"
        self.setGeometry(logical)
        make_overlay_nonactivating(self.winId())
        self.show()
        # Abort if exclusion is unavailable; capturing our own translated overlay is unsafe.
        if not exclude_from_capture(self.winId()) and not window_capture:
            self.hide()
            return False
        return True

    def set_blocks(self, blocks):
        self.blocks = blocks
        if any(block.translated for block in blocks):
            self.message = ""
        self.update()

    def set_message(self, message):
        self.message = message
        self.update()

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0084:  # WM_NCHITTEST: explicitly hand input to the underlying game.
            return True, -1  # HTTRANSPARENT
        if msg.message == 0x0021:  # WM_MOUSEACTIVATE
            return True, 3  # MA_NOACTIVATE
        return super().nativeEvent(event_type, message)

    def paintEvent(self, event):
        if not self.region:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        sx, sy = self.width() / self.region.width, self.height() / self.region.height
        # Paint ALL erasure backgrounds before any translation. Adjacent boxes must
        # never cover an earlier line's translated text or stack translucent shadows.
        from PySide6.QtGui import QPainterPath
        mask = QPainterPath()
        mask.setFillRule(Qt.FillRule.WindingFill)
        visible_blocks = [block for block in self.blocks if block.translated]
        for block in visible_blocks:
            rect = QRectF(block.x * sx, block.y * sy, block.width * sx, block.height * sy)
            if self.display_style == "blend":
                painter.fillRect(rect, QColor(*block.background))
            else:
                mask.addRect(rect)
        if self.display_style != "blend":
            painter.fillPath(mask, QColor(6, 10, 18, round(self.shade_opacity * 2.55)))
        for block in visible_blocks:
            rect = QRectF(block.x * sx, block.y * sy, block.width * sx, block.height * sy)
            font = QFont("Microsoft YaHei UI")
            alignment = (Qt.AlignmentFlag.AlignCenter if block.height > block.width * 1.5 else
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            flags = alignment | Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere
            fitted = rect.adjusted(1, 0, -1, 0)
            for size in range(max(8, min(32, int(rect.height() * 0.82))), 6, -1):
                font.setPixelSize(size)
                bounds = QFontMetrics(font).boundingRect(fitted.toRect(), int(flags), block.translated)
                if bounds.height() <= fitted.height() and bounds.width() <= fitted.width():
                    break
            painter.setFont(font)
            painter.setPen(QColor(*block.foreground) if self.display_style == "blend" else QColor("#ffffff"))
            painter.save()
            painter.setClipRect(rect)
            painter.drawText(fitted, int(flags), block.translated)
            painter.restore()
        if self.message and not any(block.translated for block in self.blocks):
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(12)
            painter.setFont(font)
            flags = Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere | Qt.AlignmentFlag.AlignLeft
            available = QRect(6, 4, max(1, self.width() - 12), max(1, self.height() - 8))
            bounds = QFontMetrics(font).boundingRect(available, int(flags), self.message)
            panel = QRect(0, 0, self.width(), min(self.height(), bounds.height() + 12))
            painter.fillRect(panel, QColor(10, 18, 30, 235))
            painter.setPen(QColor("#a4efd9"))
            painter.drawText(panel.adjusted(6, 4, -6, -4), int(flags), self.message)
        painter.end()
        if any(block.translated for block in self.blocks):
            self.translated_painted.emit()
import ctypes
from ctypes import wintypes
