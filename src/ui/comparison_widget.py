from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel
)

from scoring.engine import SkaterTotals, GoalieTotals

# (header_label, attr_on_totals_obj, is_goalie_stat, lower_is_better)
_STATS: list[tuple[str, str, bool, bool]] = [
    ("G",    "goals",         False, False),
    ("A",    "assists",       False, False),
    ("BLK",  "blk",           False, False),
    ("Hits", "hits",          False, False),
    ("SOG",  "sog",           False, False),
    ("PPP",  "ppp",           False, False),
    ("GWG",  "gwg",           False, False),
    ("W",    "wins",          True,  False),
    ("GA",   "gaa",           True,  True),
    ("SV%",  "save_pct",      True,  False),
    ("SV",   "saves",         True,  False),
]

_GREEN      = QColor(0, 160, 0)
_RED        = QColor(200, 0, 0)
_GRAY       = QColor(120, 120, 120)
_ROW_FLASH  = QColor(255, 165, 0, 220)    # vivid amber/orange for score-change highlight

_HIGHLIGHT_MS = 10_000

_HEADER_STYLE = (
    "QHeaderView::section {"
    "  background-color: #1a252f;"
    "  color: white;"
    "  font-weight: bold;"
    "  padding: 2px;"
    "  border: none;"
    "}"
)


def _fmt(val, is_goalie: bool, attr: str) -> str:
    if attr == "gaa":
        return str(int(round(val)))
    if attr == "save_pct":
        return f"{val:.3f}"
    return str(val)


class ComparisonWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        # Score banner
        score_row = QWidget()
        score_layout = QHBoxLayout(score_row)
        score_layout.setContentsMargins(4, 0, 4, 0)

        score_font = QFont(); score_font.setBold(True); score_font.setPointSize(28)

        self._my_score_lbl = QLabel("0")
        self._my_score_lbl.setFont(score_font)
        self._my_score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        dash = QLabel("-")
        dash_font = QFont(); dash_font.setBold(True); dash_font.setPointSize(20)
        dash.setFont(dash_font)
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dash.setMaximumWidth(20)

        self._opp_score_lbl = QLabel("0")
        self._opp_score_lbl.setFont(score_font)
        self._opp_score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        score_layout.addWidget(self._my_score_lbl)
        score_layout.addWidget(dash)
        score_layout.addWidget(self._opp_score_lbl)
        score_row.setMaximumHeight(50)
        layout.addWidget(score_row)

        lbl = QLabel("PERIOD TOTALS")
        f = QFont(); f.setBold(True); f.setPointSize(8)
        lbl.setFont(f)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMaximumHeight(16)
        layout.addWidget(lbl)

        col_headers = ["Team"] + [s[0] for s in _STATS]
        self._table = QTableWidget(2, len(col_headers))
        self._table.setHorizontalHeaderLabels(col_headers)
        self._table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, len(col_headers)):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)

        small_font = QFont(); small_font.setPointSize(8); small_font.setBold(True)
        self._table.setFont(small_font)

        layout.addWidget(self._table)

        self._my_label  = "My Team"
        self._opp_label = "Opponent"

        # Score-change highlight state: row → time highlight started
        self._highlight_until: dict[int, datetime] = {}
        self._prev_my_score  = -1
        self._prev_opp_score = -1

        # Timer to expire highlights between polls
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setInterval(200)
        self._highlight_timer.timeout.connect(self._tick_highlights)
        self._highlight_timer.start()

    def set_labels(self, my_label: str, opp_label: str) -> None:
        self._my_label  = my_label
        self._opp_label = opp_label

    def _apply_row_bg(self, row: int, color: QColor) -> None:
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                item.setBackground(color)

    def _tick_highlights(self) -> None:
        now = datetime.now()
        expired = [
            row for row, t in self._highlight_until.items()
            if (now - t).total_seconds() * 1000 >= _HIGHLIGHT_MS
        ]
        for row in expired:
            del self._highlight_until[row]
            self._apply_row_bg(row, QColor(Qt.GlobalColor.transparent))

    def update_data(
        self,
        my_sk: SkaterTotals,
        my_gl: GoalieTotals,
        opp_sk: SkaterTotals,
        opp_gl: GoalieTotals,
    ) -> None:
        bold_font = QFont(); bold_font.setBold(True); bold_font.setPointSize(8)

        my_src  = (my_sk,  my_gl)
        opp_src = (opp_sk, opp_gl)

        # Count winning categories
        my_score = opp_score = 0
        for _, attr, is_goalie, lower_better in _STATS:
            src_idx = 1 if is_goalie else 0
            my_val  = getattr(my_src[src_idx],  attr, 0)
            opp_val = getattr(opp_src[src_idx], attr, 0)
            if my_val == opp_val:
                continue
            if (my_val > opp_val) ^ lower_better:
                my_score += 1
            else:
                opp_score += 1

        # Detect score changes (skip first poll)
        if self._prev_my_score != -1:
            now = datetime.now()
            if my_score != self._prev_my_score:
                self._highlight_until[0] = now
            if opp_score != self._prev_opp_score:
                self._highlight_until[1] = now
        self._prev_my_score  = my_score
        self._prev_opp_score = opp_score

        # Score labels
        self._my_score_lbl.setText(str(my_score))
        self._opp_score_lbl.setText(str(opp_score))
        if my_score > opp_score:
            self._my_score_lbl.setStyleSheet(f"color: {_GREEN.name()};")
            self._opp_score_lbl.setStyleSheet(f"color: {_RED.name()};")
        elif opp_score > my_score:
            self._my_score_lbl.setStyleSheet(f"color: {_RED.name()};")
            self._opp_score_lbl.setStyleSheet(f"color: {_GREEN.name()};")
        else:
            self._my_score_lbl.setStyleSheet(f"color: {_GRAY.name()};")
            self._opp_score_lbl.setStyleSheet(f"color: {_GRAY.name()};")

        # Row labels
        for row, label in enumerate([self._my_label, self._opp_label]):
            item = QTableWidgetItem(label)
            item.setFont(bold_font)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, item)

        # Stat cells
        for col_idx, (hdr, attr, is_goalie, lower_better) in enumerate(_STATS, start=1):
            src_idx = 1 if is_goalie else 0
            my_val  = getattr(my_src[src_idx],  attr, 0)
            opp_val = getattr(opp_src[src_idx], attr, 0)

            for row, val in enumerate([my_val, opp_val]):
                other = opp_val if row == 0 else my_val
                item = QTableWidgetItem(_fmt(val, is_goalie, attr))
                item.setFont(bold_font)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if val == other:
                    item.setForeground(_GRAY)
                elif (val > other) ^ lower_better:
                    item.setForeground(_GREEN)
                else:
                    item.setForeground(_RED)

                self._table.setItem(row, col_idx, item)

        # Re-apply active row highlights (items were just recreated)
        for row in self._highlight_until:
            self._apply_row_bg(row, _ROW_FLASH)

        # Fix height
        header_h = self._table.horizontalHeader().height()
        self._table.setFixedHeight(header_h + 2 * 22 + 2)
