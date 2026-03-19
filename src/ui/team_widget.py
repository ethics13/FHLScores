from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QLabel

from ui.skater_table import SkaterTable
from ui.goalie_table import GoalieTable
from scoring.engine import ScoringSnapshot


class TeamWidget(QWidget):
    def __init__(self, team_label: str, flash_duration_ms: int = 5000, parent=None):
        super().__init__(parent)
        self._flash_duration_ms = flash_duration_ms
        self._show_period = False
        self._last_snapshot: ScoringSnapshot | None = None
        self._is_my_team = True
        self._last_changed: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Team label
        self._label = QLabel(team_label)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self._label.setFont(font)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMaximumHeight(20)
        layout.addWidget(self._label)

        # Draggable splitter between skaters and goalies
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._skater_table = SkaterTable(flash_duration_ms)
        self._goalie_table = GoalieTable(flash_duration_ms)
        self._splitter.addWidget(self._skater_table)
        self._splitter.addWidget(self._goalie_table)
        self._splitter.setSizes([500, 120])
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        # Animation timer — drives flash fade at 100ms intervals
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(100)
        self._anim_timer.timeout.connect(self._tick_animation)
        self._anim_timer.start()

    def _tick_animation(self) -> None:
        self._skater_table.viewport().update()
        self._goalie_table.viewport().update()

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_view_mode(self, show_period: bool) -> None:
        self._show_period = show_period
        self._skater_table.set_view_mode(show_period)
        self._goalie_table.set_view_mode(show_period)
        if self._last_snapshot:
            self._render()

    def update_data(
        self,
        snapshot: ScoringSnapshot,
        is_my_team: bool,
        changed: set[tuple[str, str]],
    ) -> None:
        self._last_snapshot = snapshot
        self._is_my_team = is_my_team
        self._last_changed = changed
        self._render()

    def _render(self) -> None:
        snapshot = self._last_snapshot
        if snapshot is None:
            return
        if self._is_my_team:
            if self._show_period:
                skaters       = snapshot.my_period_skaters
                goalies       = snapshot.my_period_goalies
                skater_totals = snapshot.my_skater_period_totals
                goalie_totals = snapshot.my_goalie_period_totals
            else:
                skaters       = snapshot.my_skaters
                goalies       = snapshot.my_goalies
                skater_totals = snapshot.my_skater_totals
                goalie_totals = snapshot.my_goalie_totals
        else:
            if self._show_period:
                skaters       = snapshot.opp_period_skaters
                goalies       = snapshot.opp_period_goalies
                skater_totals = snapshot.opp_skater_period_totals
                goalie_totals = snapshot.opp_goalie_period_totals
            else:
                skaters       = snapshot.opp_skaters
                goalies       = snapshot.opp_goalies
                skater_totals = snapshot.opp_skater_totals
                goalie_totals = snapshot.opp_goalie_totals

        self._skater_table.update_data(skaters, skater_totals, self._last_changed)
        self._goalie_table.update_data(goalies, goalie_totals, self._last_changed)
