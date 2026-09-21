"""Non-overlapping text rectangles and consistent sizes for adjacent prose lines."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QFontMetrics

FLAGS = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter |
            Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere)


def layout_blocks(blocks, sx, sy):
    original = [QRectF(b.x * sx, b.y * sy, b.width * sx, b.height * sy) for b in blocks]
    rects = [QRectF(r) for r in original]
    # Partition intersecting OCR boxes. Shrinking never creates a new intersection.
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            overlap = a.intersected(b)
            if overlap.isEmpty():
                continue
            dx, dy = abs(a.center().x() - b.center().x()), abs(a.center().y() - b.center().y())
            if dx / max(1, min(a.width(), b.width())) > dy / max(1, min(a.height(), b.height())):
                left, right = (a, b) if a.center().x() <= b.center().x() else (b, a)
                cut = (overlap.left() + overlap.right()) / 2
                left.setRight(cut)
                right.setLeft(cut)
            else:
                top, bottom = (a, b) if a.center().y() <= b.center().y() else (b, a)
                cut = (overlap.top() + overlap.bottom()) / 2
                top.setBottom(cut)
                bottom.setTop(cut)
    sizes = []
    for block, rect in zip(blocks, rects):
        font = QFont("Microsoft YaHei UI")
        fitted = rect.adjusted(1, 0, -1, 0)
        size = 7
        for candidate in range(max(7, min(32, int(rect.height() * .82))), 6, -1):
            font.setPixelSize(candidate)
            bounds = QFontMetrics(font).boundingRect(fitted.toRect(), FLAGS, block.translated)
            if bounds.height() <= fitted.height() and bounds.width() <= fitted.width():
                size = candidate
                break
        sizes.append(size)
    parents = list(range(len(blocks)))
    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i
    for i, a in enumerate(original):
        for j in range(i + 1, len(original)):
            b = original[j]
            # Only neighbouring horizontal prose; don't force unrelated bubbles/title to one size.
            if min(a.width() / max(1, a.height()), b.width() / max(1, b.height())) < 2:
                continue
            if max(a.height(), b.height()) > min(a.height(), b.height()) * 1.25:
                continue
            overlap_x = min(a.right(), b.right()) - max(a.left(), b.left())
            gap = max(a.top(), b.top()) - min(a.bottom(), b.bottom())
            if overlap_x >= min(a.width(), b.width()) * .5 and -min(a.height(), b.height()) * .25 <= gap <= max(a.height(), b.height()):
                parents[root(j)] = root(i)
    minimum = {}
    for i, size in enumerate(sizes):
        r = root(i)
        minimum[r] = min(size, minimum.get(r, size))
    return [(r, minimum[root(i)]) for i, r in enumerate(rects)]
