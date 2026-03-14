from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

_GREEN = QColor(0, 200, 0)
_BLUE  = QColor(30, 120, 255, 70)   # persistent "last changed" tint


class FlashDelegate(QStyledItemDelegate):
    """
    Paints a fading green flash on cells that recently changed,
    then a persistent blue tint on the last batch of changed cells
    until the next change batch arrives.
    """

    def __init__(self, flash_duration_ms: int = 10000, parent=None):
        super().__init__(parent)
        self._flash_duration_ms = flash_duration_ms
        self._flash_times: dict[tuple[int, int], datetime] = {}
        self._blue_cells:  set[tuple[int, int]] = set()

    def begin_batch(self) -> None:
        """Call once before mark_changed calls for a new round of changes."""
        self._blue_cells.clear()

    def mark_changed(self, row: int, col: int) -> None:
        key = (row, col)
        self._flash_times[key] = datetime.now()
        self._blue_cells.add(key)

    def clear_all(self) -> None:
        self._flash_times.clear()
        self._blue_cells.clear()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        key = (index.row(), index.column())

        if key in self._flash_times:
            elapsed_ms = (datetime.now() - self._flash_times[key]).total_seconds() * 1000
            if elapsed_ms >= self._flash_duration_ms:
                del self._flash_times[key]
                # Green done — fall through to blue tint below
            else:
                alpha = int(180 * (1.0 - elapsed_ms / self._flash_duration_ms))
                painter.save()
                painter.fillRect(option.rect, QColor(0, 200, 0, alpha))
                painter.restore()
                super().paint(painter, option, index)
                return

        if key in self._blue_cells:
            painter.save()
            painter.fillRect(option.rect, _BLUE)
            painter.restore()

        super().paint(painter, option, index)
