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

GOALIE_COLUMNS = ["Name", "WPerf", "Team", "Opp", "REM", "W", "GA", "SV%", "SV", "Ros%"]
_ROS_COL = 9

STAT_TO_COL: dict[str, int] = {
    "wins": 5,
    "goals_against": 6,
    "save_pct": 7,
    "saves": 8,
}

_WPERF_COL = 1

def _wperf_emoji(wperf: float, games: int) -> str:
    if games == 0: return ""
    rate = wperf / games
    if rate < 2.0: return "❄️"
    if rate < 4.5: return "🚀"
    if rate < 7.0: return "🔥"
    return                "🔥🔥"

def _wperf_bg(wperf: float, games: int) -> QColor | None:
    if games == 0: return None
    rate = wperf / games
    if rate < 2.0: return QColor(173, 216, 230)   # light blue  (cold)
    if rate < 4.5: return QColor(255, 240, 80)    # yellow
    if rate < 7.0: return QColor(255, 160, 40)    # orange
    return                QColor(210, 40, 40)      # red

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
        self._last_totals  = None
        self._last_changed: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(GOALIE_COLUMNS))
        self._table.setHorizontalHeaderLabels(GOALIE_COLUMNS)
        self._table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        self._table.horizontalHeader().setDefaultSectionSize(45)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 40)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(5, len(GOALIE_COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnHidden(_ROS_COL, True)  # visible only in period mode
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
        self._show_period = False

        layout.addWidget(self._table)

    def viewport(self):
        return self._table.viewport()

    def set_view_mode(self, show_period: bool) -> None:
        self._show_period = show_period
        self._table.setColumnHidden(_ROS_COL, not show_period)

    def update_data(
        self,
        players: list[GoalieRow],
        totals: GoalieTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
        # In period mode the engine already filtered to active-period goalies
        active = players if self._show_period else [p for p in players if p.has_played]
        if len(active) != len(self._players):
            self._delegate.clear_all()
        self._last_totals  = totals
        self._last_changed = changed_ids
        self._render(active, totals, changed_ids)

    def _render(
        self,
        players: list[GoalieRow],
        totals: GoalieTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
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
            tip = (f"Period: W:{p.p_wins} GA:{p.p_goals_against} "
                   f"SV:{p.p_saves} SV%:{p.p_save_pct:.3f}")

            w   = p.p_wins          if self._show_period else p.wins
            ga  = p.p_goals_against if self._show_period else p.goals_against
            sv  = p.p_saves         if self._show_period else p.saves
            svp = p.p_save_pct      if self._show_period else p.save_pct

            self._set_cell(row_idx, 0, p.name, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tooltip=tip)
            self._set_cell(row_idx, 1, _wperf_emoji(p.wperf, p.games_played))
            if not self._show_period:
                bg = _wperf_bg(p.wperf, p.games_played)
                if bg:
                    item = self._table.item(row_idx, _WPERF_COL)
                    if item:
                        item.setBackground(bg)
            self._set_cell(row_idx, 2, p.team_abbrev)
            self._set_cell(row_idx, 3, p.nhl_opponent)
            self._set_cell(row_idx, 4, str(p.games_remaining) if p.games_remaining > 0 else "-")
            if self._show_period:
                self._set_cell(row_idx, 5, str(w))
                self._set_cell(row_idx, 6, str(ga))
                self._set_cell(row_idx, 7, f"{svp:.3f}")
                self._set_cell(row_idx, 8, str(sv))
                ros_str = f"{p.ros_pct:.0f}%" if p.ros_pct > 0 else "--"
                self._set_cell(row_idx, _ROS_COL, ros_str)
            else:
                self._set_cell(row_idx, 5, str(w),         tooltip=f"Period: {p.p_wins}")
                self._set_cell(row_idx, 6, str(ga),        tooltip=f"Period: {p.p_goals_against}")
                self._set_cell(row_idx, 7, f"{svp:.3f}",   tooltip=f"Period: {p.p_save_pct:.3f}")
                self._set_cell(row_idx, 8, str(sv),        tooltip=f"Period: {p.p_saves}")

            if p.game_state in _STATE_COLOR:
                self._set_row_bg(row_idx, _STATE_COLOR[p.game_state])

            if not self._show_period:
                for stat, col in STAT_TO_COL.items():
                    if (p.fantrax_id, stat) in changed_ids:
                        self._delegate.mark_changed(row_idx, col)

        # Resize table height to exact content
        header_h = self._table.horizontalHeader().height()
        row_h = self._table.verticalHeader().defaultSectionSize()
        self._table.setFixedHeight(header_h + (row_count * row_h) + 2)

        # Totals row
        totals_row = len(players)
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(8)
        if self._show_period:
            tga = sum(p.p_goals_against for p in players)
            tsv = sum(p.p_saves        for p in players)
            tw  = sum(p.p_wins         for p in players)
            tsa = tsv + tga
            tsvp = (tsv / tsa) if tsa > 0 else 0.0
            totals_data = ["TOTALS", "", "", "", "", str(tw), str(tga), f"{tsvp:.3f}", str(tsv), ""]
        else:
            totals_data = [
                "TOTALS", "", "", "", "",
                str(totals.wins),
                str(totals.goals_against), f"{totals.save_pct:.3f}",
                str(totals.saves),
            ]
        for col, val in enumerate(totals_data):
            item = QTableWidgetItem(val)
            item.setFont(bold_font)
            item.setForeground(Qt.GlobalColor.darkGray)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(totals_row, col, item)

        if not self._show_period:
            for stat, col in STAT_TO_COL.items():
                if any((p.fantrax_id, stat) in changed_ids for p in players):
                    self._delegate.mark_changed(totals_row, col)

    def _set_row_bg(self, row: int, color: QColor) -> None:
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                item.setBackground(color)

    def _set_cell(self, row: int, col: int, text: str,
                  align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
                  tooltip: str = "") -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)
            item.setData(Qt.ItemDataRole.FontRole, None)
        item.setTextAlignment(align)
        item.setForeground(Qt.GlobalColor.black)
        if tooltip:
            item.setToolTip(tooltip)
