from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

_STATE_COLOR: dict[str, QColor] = {
    "LIVE": QColor(235, 248, 255),   # very light blue
    "FUT":  QColor(219, 213, 205),   # light taupe
    "OFF":  QColor(140, 140, 140),   # dark gray
}

from ui.flash_delegate import FlashDelegate
from scoring.engine import SkaterRow, SkaterTotals

SKATER_COLUMNS = ["Name", "WPerf", "Team", "Opp", "Pos", "G", "A", "BLK", "Hits", "SOG", "PPP", "GWG"]

STAT_TO_COL: dict[str, int] = {
    "goals": 5,
    "assists": 6,
    "blk": 7,
    "hits": 8,
    "sog": 9,
    "ppp": 10,
    "gwg": 11,
}

_WPERF_COL = 1

def _wperf_emoji(score: float) -> str:
    if score <= 0:  return ""
    if score < 2:   return "❄️"
    if score < 4:   return "🚀"
    if score < 7:   return "🔥"
    return                  "🔥🔥"

def _wperf_bg(score: float) -> QColor | None:
    if score <= 0:  return None
    if score < 2:   return QColor(173, 216, 230)   # light blue
    if score < 4:   return QColor(255, 240, 80)    # yellow
    if score < 7:   return QColor(255, 160, 40)    # orange
    return                  QColor(210, 40, 40)     # red

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
        self._last_totals  = None
        self._last_changed: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, len(SKATER_COLUMNS))
        self._table.setHorizontalHeaderLabels(SKATER_COLUMNS)
        self._table.horizontalHeader().setStyleSheet(_HEADER_STYLE)
        self._table.horizontalHeader().setDefaultSectionSize(45)
        self._table.horizontalHeader().setMinimumSectionSize(30)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 40)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(4, len(SKATER_COLUMNS)):
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
        self._show_period = False

        layout.addWidget(self._table)

    def viewport(self):
        return self._table.viewport()

    def set_view_mode(self, show_period: bool) -> None:
        self._show_period = show_period

    def update_data(
        self,
        players: list[SkaterRow],
        totals: SkaterTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
        if len(players) != len(self._players):
            self._delegate.clear_all()
        self._last_totals  = totals
        self._last_changed = changed_ids
        self._render(players, totals, changed_ids)

    def _render(
        self,
        players: list[SkaterRow],
        totals: SkaterTotals,
        changed_ids: set[tuple[str, str]],
    ) -> None:
        self._players = players
        row_count = len(players) + 1
        self._table.setRowCount(row_count)

        has_changes = (not self._show_period) and any(
            (p.fantrax_id, stat) in changed_ids
            for p in players for stat in STAT_TO_COL
        )
        if has_changes:
            self._delegate.begin_batch()

        for row_idx, p in enumerate(players):
            # Tooltip on name cell — always shows period stats
            tip = (f"Period: G:{p.p_goals} A:{p.p_assists} "
                   f"BLK:{p.p_blk} Hits:{p.p_hits} "
                   f"SOG:{p.p_sog} PPP:{p.p_ppp} GWG:{p.p_gwg}")

            g   = p.p_goals   if self._show_period else p.goals
            a   = p.p_assists if self._show_period else p.assists
            blk = p.p_blk     if self._show_period else p.blk
            hit = p.p_hits    if self._show_period else p.hits
            sog = p.p_sog     if self._show_period else p.sog
            ppp = p.p_ppp     if self._show_period else p.ppp
            gwg = p.p_gwg     if self._show_period else p.gwg

            self._set_cell(row_idx, 0, p.name, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tooltip=tip)
            self._set_cell(row_idx, 1, _wperf_emoji(p.wperf))
            if not self._show_period:
                bg = _wperf_bg(p.wperf)
                if bg:
                    item = self._table.item(row_idx, _WPERF_COL)
                    if item:
                        item.setBackground(bg)
            self._set_cell(row_idx, 2, p.team_abbrev)
            self._set_cell(row_idx, 3, p.nhl_opponent)
            self._set_cell(row_idx, 4, p.position)
            self._set_cell(row_idx, 5, str(g))
            self._set_cell(row_idx, 6, str(a))
            self._set_cell(row_idx, 7, str(blk))
            self._set_cell(row_idx, 8, str(hit))
            self._set_cell(row_idx, 9, str(sog))
            self._set_cell(row_idx, 10, str(ppp))
            self._set_cell(row_idx, 11, str(gwg))

            if p.game_state in _STATE_COLOR:
                self._set_row_bg(row_idx, _STATE_COLOR[p.game_state])

            if not self._show_period:
                for stat, col in STAT_TO_COL.items():
                    if (p.fantrax_id, stat) in changed_ids:
                        self._delegate.mark_changed(row_idx, col)

        # Totals row
        totals_row = len(players)
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(8)
        if self._show_period:
            tg  = sum(p.p_goals   for p in players)
            ta  = sum(p.p_assists for p in players)
            tbl = sum(p.p_blk     for p in players)
            thi = sum(p.p_hits    for p in players)
            tso = sum(p.p_sog     for p in players)
            tpp = sum(p.p_ppp     for p in players)
            tgw = sum(p.p_gwg     for p in players)
            totals_data = ["TOTALS", "", "", "", "", str(tg), str(ta), str(tbl), str(thi), str(tso), str(tpp), str(tgw)]
        else:
            totals_data = [
                "TOTALS", "", "", "", "",
                str(totals.goals), str(totals.assists),
                str(totals.blk), str(totals.hits), str(totals.sog),
                str(totals.ppp), str(totals.gwg),
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
