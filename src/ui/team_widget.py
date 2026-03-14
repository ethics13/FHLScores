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

    def update_data(
        self,
        snapshot: ScoringSnapshot,
        is_my_team: bool,
        changed: set[tuple[str, str]],
    ) -> None:
        if is_my_team:
            skaters = snapshot.my_skaters
            goalies = snapshot.my_goalies
            skater_totals = snapshot.my_skater_totals
            goalie_totals = snapshot.my_goalie_totals
        else:
            skaters = snapshot.opp_skaters
            goalies = snapshot.opp_goalies
            skater_totals = snapshot.opp_skater_totals
            goalie_totals = snapshot.opp_goalie_totals

        self._skater_table.update_data(skaters, skater_totals, changed)
        self._goalie_table.update_data(goalies, goalie_totals, changed)
