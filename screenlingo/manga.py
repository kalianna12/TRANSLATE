"""Explicit manga reading order and vertical Chinese glyph placement."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontMetrics

# Unicode vertical presentation forms keep punctuation upright in CJK columns.
VERTICAL = str.maketrans({"，": "︐", "、": "︑", "。": "︒", "：": "︓", "；": "︔",
                         "！": "︕", "？": "︖", "（": "︵", "）": "︶", "「": "﹁", "」": "﹂",
                         "『": "﹃", "』": "﹄", "“": "﹁", "”": "﹂", "…": "︙"})
CLOSING = set("︐︑︒︓︔︕︖︶﹂﹄︙,.;:!?)]}")
OPENING = set("︵﹁﹃([{")


def split_columns(glyphs, rows):
    columns, start = [], 0
    while start < len(glyphs):
        end = min(len(glyphs), start + rows)
        if rows > 1 and end < len(glyphs):
            # Move the preceding character with punctuation to the next column.
            if glyphs[end] in CLOSING or glyphs[end - 1] in OPENING:
                end -= 1
        columns.append(glyphs[start:end])
        start = end
    return columns


def reading_order(blocks):
    """Top-to-bottom bands, right-to-left within each band; not panel segmentation."""
    pending = sorted(blocks, key=lambda b: (b.y, -b.x))
    result = []
    while pending:
        anchor = pending.pop(0)
        band = [anchor]
        # Anchor tolerance avoids chaining a tall bubble through the entire page.
        tolerance = max(8, min(anchor.width, anchor.height) * .75)
        for block in pending[:]:
            if abs(block.y - anchor.y) <= tolerance:
                band.append(block)
                pending.remove(block)
        result.extend(sorted(band, key=lambda b: (-b.x, b.y)))
    return result


def vertical_cells(text, rect):
    """Return one font size and bounded glyph cells, columns running right to left."""
    glyphs = [c for c in text.translate(VERTICAL) if not c.isspace()]
    if not glyphs or rect.width() < 2 or rect.height() < 2:
        return 7, []
    fitted = rect.adjusted(1, 1, -1, -1)
    font = QFont("Microsoft YaHei UI")
    for size in range(32, 6, -1):
        font.setPixelSize(size)
        metrics = QFontMetrics(font)
        cell_w = max(size, max(metrics.horizontalAdvance(c) for c in set(glyphs))) + 2
        cell_h = metrics.height()
        rows = max(1, int(fitted.height() // cell_h))
        columns_text = split_columns(glyphs, rows)
        columns = len(columns_text)
        if cell_h <= fitted.height() and columns * cell_w <= fitted.width():
            break
    capacity_cols = max(0, int(fitted.width() // cell_w))
    capacity_rows = max(0, int(fitted.height() // cell_h))
    if not capacity_cols or not capacity_rows:
        return size, []
    rows = min(rows, capacity_rows)
    columns = min(columns, capacity_cols)
    right = fitted.center().x() + columns * cell_w / 2
    top = fitted.center().y() - min(rows, len(glyphs)) * cell_h / 2
    cells = []
    for column, text_column in enumerate(columns_text[:columns]):
        for row, char in enumerate(text_column[:rows]):
            cells.append((char, QRectF(right - (column + 1) * cell_w, top + row * cell_h, cell_w, cell_h)))
    return size, cells


def draw_vertical(painter, rect, text):
    size, cells = vertical_cells(text, rect)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    painter.setFont(font)
    for char, cell in cells:
        painter.drawText(cell, int(Qt.AlignmentFlag.AlignCenter), char)
