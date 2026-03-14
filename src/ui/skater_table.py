from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

from ui.flash_delegate import FlashDelegate
from scoring.engine import SkaterRow, SkaterTotals

SKATER_COLUMNS = ["Name", "Team", "Opp", "Pos", "G", "A", "PTS", "+/-", "Hits", "SOG", "PPP", "GWG"]

STAT_TO_COL: dict[str, int] = {
    "goals": 4,
    "assists": 5,
    "points": 6,
    "plus_minus": 7,
    "hits": 8,
    "sog": 9,
    "ppp": 10,
    "gwg": 11,
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


class SkaterTable(QWidget):
    def __init__(self, flash_duration_ms: int = 5000, parent=None):
        super().__init__(parent)
        self._players: list[SkaterRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(SKATER_COLUMNS))
        self._table.setHorizontalHeaderLabels(SKATER_COLUMNS)
        self._table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        self._table.horizontalHeader().setDefaultSectionSize(45)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(3, len(SKATER_COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)

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
        players: list[SkaterRow],
        totals: SkaterTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
        if len(players) != len(self._players):
            self._delegate.clear_all()

        self._players = players
        row_count = len(players) + 1
        self._table.setRowCount(row_count)

        has_changes = any(
            (p.fantrax_id, stat) in changed_ids
            for p in players for stat in STAT_TO_COL
        )
        if has_changes:
            self._delegate.begin_batch()

        for row_idx, p in enumerate(players):
            self._set_cell(row_idx, 0, p.name, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._set_cell(row_idx, 1, p.team_abbrev)
            self._set_cell(row_idx, 2, p.nhl_opponent)
            self._set_cell(row_idx, 3, p.position)
            self._set_cell(row_idx, 4, str(p.goals))
            self._set_cell(row_idx, 5, str(p.assists))
            self._set_cell(row_idx, 6, str(p.points))
            self._set_cell(row_idx, 7, str(p.plus_minus))
            self._set_cell(row_idx, 8, str(p.hits))
            self._set_cell(row_idx, 9, str(p.sog))
            self._set_cell(row_idx, 10, str(p.ppp))
            self._set_cell(row_idx, 11, str(p.gwg))

            for stat, col in STAT_TO_COL.items():
                if (p.fantrax_id, stat) in changed_ids:
                    self._delegate.mark_changed(row_idx, col)

        # Totals row
        totals_row = len(players)
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(8)
        totals_data = [
            "TOTALS", "", "", "",
            str(totals.goals), str(totals.assists), str(totals.points),
            str(totals.plus_minus), str(totals.hits), str(totals.sog),
            str(totals.ppp), str(totals.gwg),
        ]
        for col, val in enumerate(totals_data):
            item = QTableWidgetItem(val)
            item.setFont(bold_font)
            item.setForeground(Qt.GlobalColor.darkGray)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(totals_row, col, item)

    def _set_cell(self, row: int, col: int, text: str,
                  align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter) -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)
        item.setTextAlignment(align)
