from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy

_STATE_COLOR: dict[str, QColor] = {
    "LIVE": QColor(235, 248, 255),   # very light blue
    "FUT":  QColor(219, 213, 205),   # light taupe
    "OFF":  QColor(140, 140, 140),   # dark gray
}

from ui.flash_delegate import FlashDelegate
from scoring.engine import GoalieRow, GoalieTotals

GOALIE_COLUMNS = ["Name", "Team", "Opp", "W", "GAA", "SV%", "SV"]

STAT_TO_COL: dict[str, int] = {
    "wins": 3,
    "gaa": 4,
    "save_pct": 5,
    "saves": 6,
}

_HEADER_STYLE = (
    "QHeaderView::section {"
    "  background-color: #2c3e50;"
    "  color: white;"
    "  font-weight: bold;"
    "  padding: 2px;"
    "  border: none;"
    "}"
)


class GoalieTable(QWidget):
    def __init__(self, flash_duration_ms: int = 5000, parent=None):
        super().__init__(parent)
        self._players: list[GoalieRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(GOALIE_COLUMNS))
        self._table.setHorizontalHeaderLabels(GOALIE_COLUMNS)
        self._table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        self._table.horizontalHeader().setDefaultSectionSize(45)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(3, len(GOALIE_COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        small_font = QFont()
        small_font.setPointSize(8)
        self._table.setFont(small_font)

        self._delegate = FlashDelegate(flash_duration_ms, self._table)
        self._table.setItemDelegate(self._delegate)

        layout.addWidget(self._table)

    def viewport(self):
        return self._table.viewport()

    def update_data(
        self,
        players: list[GoalieRow],
        totals: GoalieTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
        active = [p for p in players if p.has_played]

        if len(active) != len(self._players):
            self._delegate.clear_all()

        self._players = active
        row_count = len(active) + 1
        self._table.setRowCount(row_count)

        has_changes = any(
            (p.fantrax_id, stat) in changed_ids
            for p in active for stat in STAT_TO_COL
        )
        if has_changes:
            self._delegate.begin_batch()

        for row_idx, p in enumerate(active):
            self._set_cell(row_idx, 0, p.name, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._set_cell(row_idx, 1, p.team_abbrev)
            self._set_cell(row_idx, 2, p.nhl_opponent)
            self._set_cell(row_idx, 3, str(p.wins))
            self._set_cell(row_idx, 4, f"{p.gaa:.2f}")
            self._set_cell(row_idx, 5, f"{p.save_pct:.3f}")
            self._set_cell(row_idx, 6, str(p.saves))

            if p.game_state in _STATE_COLOR:
                self._set_row_bg(row_idx, _STATE_COLOR[p.game_state])

            for stat, col in STAT_TO_COL.items():
                if (p.fantrax_id, stat) in changed_ids:
                    self._delegate.mark_changed(row_idx, col)

        # Resize table height to exact content
        header_h = self._table.horizontalHeader().height()
        row_h = self._table.verticalHeader().defaultSectionSize()
        self._table.setFixedHeight(header_h + (row_count * row_h) + 2)

        # Totals row
        totals_row = len(active)
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(8)
        totals_data = [
            "TOTALS", "", "",
            str(totals.wins),
            f"{totals.gaa:.2f}", f"{totals.save_pct:.3f}",
            str(totals.saves),
        ]
        for col, val in enumerate(totals_data):
            item = QTableWidgetItem(val)
            item.setFont(bold_font)
            item.setForeground(Qt.GlobalColor.darkGray)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(totals_row, col, item)

    def _set_row_bg(self, row: int, color: QColor) -> None:
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                item.setBackground(color)

    def _set_cell(self, row: int, col: int, text: str,
                  align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter) -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)
        item.setTextAlignment(align)
