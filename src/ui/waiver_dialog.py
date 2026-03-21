from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
)

from scoring.engine import WaiverRow

_STATE_COLOR: dict[str, QColor] = {
    "LIVE": QColor(235, 248, 255),
    "FUT":  QColor(219, 213, 205),
    "OFF":  QColor(140, 140, 140),
}

_HEADER_STYLE = (
    "QHeaderView::section {"
    "  background-color: #1a3a2a;"
    "  color: white;"
    "  font-weight: bold;"
    "  padding: 2px;"
    "  border: none;"
    "}"
)

# Stats shown are period totals. PROJ = period_wperf + projected_remaining.
_SK_COLS = ["Name", "Team", "Pos", "Opp", "REM", "G", "A", "SOG", "PPP", "Hits", "BLK", "PROJ", "Ros%"]
_GL_COLS = ["Name", "Team", "Opp", "REM", "W", "SV%", "SV", "GA", "PROJ", "Ros%"]


class WaiverDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Top Available Players — Scoring Period")
        self.resize(860, 540)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        hdr_font = QFont(); hdr_font.setBold(True); hdr_font.setPointSize(9)

        sk_lbl = QLabel("SKATERS  (period stats · sorted by PROJ = period rate × remaining games)")
        sk_lbl.setFont(hdr_font)
        layout.addWidget(sk_lbl)

        self._sk_table = self._make_table(_SK_COLS)
        layout.addWidget(self._sk_table)

        gl_lbl = QLabel("GOALIES")
        gl_lbl.setFont(hdr_font)
        layout.addWidget(gl_lbl)

        self._gl_table = self._make_table(_GL_COLS)
        layout.addWidget(self._gl_table)

        self._status_lbl = QLabel("No data yet.")
        small = QFont(); small.setPointSize(8); small.setItalic(True)
        self._status_lbl.setFont(small)
        layout.addWidget(self._status_lbl)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        tbl = QTableWidget(0, len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(headers)):
            tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setVisible(False)
        tbl.verticalHeader().setDefaultSectionSize(22)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        small_font = QFont(); small_font.setPointSize(8)
        tbl.setFont(small_font)
        return tbl

    def update_data(
        self,
        skaters: list[WaiverRow],
        goalies: list[WaiverRow],
        timestamp: str = "",
    ) -> None:
        self._fill_skaters(skaters)
        self._fill_goalies(goalies)
        count = len(skaters) + len(goalies)
        ts_str = f" — {timestamp}" if timestamp else ""
        self._status_lbl.setText(
            f"{count} available player(s) active today{ts_str}. "
            "Period stats build incrementally each poll."
        )

    def _fill_skaters(self, players: list[WaiverRow]) -> None:
        self._sk_table.setRowCount(len(players))
        for row_idx, p in enumerate(players):
            tip = (f"Period: G:{p.p_goals} A:{p.p_assists} SOG:{p.p_sog} "
                   f"PPP:{p.p_ppp} Hits:{p.p_hits} BLK:{p.p_blk} | "
                   f"PROJ: {p.projected:.1f}")
            self._set(row_idx, 0, p.name, self._sk_table, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tooltip=tip)
            self._set(row_idx, 1, p.team_abbrev, self._sk_table)
            self._set(row_idx, 2, p.position, self._sk_table)
            self._set(row_idx, 3, p.nhl_opponent, self._sk_table)
            self._set(row_idx, 4, str(p.games_remaining) if p.games_remaining > 0 else "-", self._sk_table)
            self._set(row_idx, 5, str(p.p_goals), self._sk_table)
            self._set(row_idx, 6, str(p.p_assists), self._sk_table)
            self._set(row_idx, 7, str(p.p_sog), self._sk_table)
            self._set(row_idx, 8, str(p.p_ppp), self._sk_table)
            self._set(row_idx, 9, str(p.p_hits), self._sk_table)
            self._set(row_idx, 10, str(p.p_blk), self._sk_table)
            self._set(row_idx, 11, f"{p.projected:.1f}", self._sk_table)
            ros_str = f"{p.ros_pct:.0f}%" if p.ros_pct > 0 else "--"
            self._set(row_idx, 12, ros_str, self._sk_table)
            if p.game_state in _STATE_COLOR:
                self._set_row_bg(row_idx, _STATE_COLOR[p.game_state], self._sk_table)

    def _fill_goalies(self, players: list[WaiverRow]) -> None:
        self._gl_table.setRowCount(len(players))
        for row_idx, p in enumerate(players):
            tip = (f"Period: W:{p.p_wins} GA:{p.p_goals_against} "
                   f"SV:{p.p_saves} SV%:{p.p_save_pct:.3f} | "
                   f"PROJ: {p.projected:.1f}")
            self._set(row_idx, 0, p.name, self._gl_table, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tooltip=tip)
            self._set(row_idx, 1, p.team_abbrev, self._gl_table)
            self._set(row_idx, 2, p.nhl_opponent, self._gl_table)
            self._set(row_idx, 3, str(p.games_remaining) if p.games_remaining > 0 else "-", self._gl_table)
            self._set(row_idx, 4, str(p.p_wins), self._gl_table)
            self._set(row_idx, 5, f"{p.p_save_pct:.3f}", self._gl_table)
            self._set(row_idx, 6, str(p.p_saves), self._gl_table)
            self._set(row_idx, 7, str(p.p_goals_against), self._gl_table)
            self._set(row_idx, 8, f"{p.projected:.1f}", self._gl_table)
            ros_str = f"{p.ros_pct:.0f}%" if p.ros_pct > 0 else "--"
            self._set(row_idx, 9, ros_str, self._gl_table)
            if p.game_state in _STATE_COLOR:
                self._set_row_bg(row_idx, _STATE_COLOR[p.game_state], self._gl_table)

    def _set(
        self, row: int, col: int, text: str,
        table: QTableWidget,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        tooltip: str = "",
    ) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        if tooltip:
            item.setToolTip(tooltip)
        table.setItem(row, col, item)

    def _set_row_bg(self, row: int, color: QColor, table: QTableWidget) -> None:
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item:
                item.setBackground(color)
