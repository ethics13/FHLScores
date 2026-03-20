from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QComboBox, QPushButton,
)

from config import AppConfig
from fantrax.client import FantraxClient
from nhl.client import NHLClient
from scoring.engine import ScoringEngine, ScoringSnapshot, detect_changes
from ui.team_widget import TeamWidget
from ui.comparison_widget import ComparisonWidget
from ui.sound_player import SoundPlayer


class WorkerThread(QThread):
    data_ready = pyqtSignal(object)  # ScoringSnapshot
    error_occurred = pyqtSignal(str)

    def __init__(self, engine: ScoringEngine):
        super().__init__()
        self._engine = engine

    def run(self) -> None:
        try:
            snapshot = self._engine.refresh()
            self.data_ready.emit(snapshot)
        except Exception as e:
            self.error_occurred.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config
        self._last_snapshot: ScoringSnapshot | None = None
        self._worker: WorkerThread | None = None
        self._scratch_alert: str = ""
        self._scratch_alert_polls: int = 0

        self.setWindowTitle("FHL Live Scoring")
        self.resize(1400, 700)

        # Build clients (shared across league switches)
        self._fantrax = FantraxClient(config.username, config.password)
        self._nhl = NHLClient()
        self._engine: ScoringEngine | None = None
        self._sound = SoundPlayer()

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── League selector bar ──────────────────────────────────────────────
        selector_bar = QWidget()
        selector_bar.setMaximumHeight(30)
        selector_layout = QHBoxLayout(selector_bar)
        selector_layout.setContentsMargins(6, 2, 6, 2)

        lbl = QLabel("League:")
        f = QFont(); f.setBold(True); f.setPointSize(9)
        lbl.setFont(f)
        selector_layout.addWidget(lbl)

        self._league_combo = QComboBox()
        self._league_combo.setFont(f)
        for league_id, name in config.leagues:
            self._league_combo.addItem(name, userData=league_id)
        self._league_combo.currentIndexChanged.connect(self._on_league_changed)
        selector_layout.addWidget(self._league_combo)
        selector_layout.addStretch()

        self._view_btn = QPushButton("Today")
        self._view_btn.setFont(f)
        self._view_btn.setCheckable(True)
        self._view_btn.setChecked(False)
        self._view_btn.setFixedWidth(75)
        self._view_btn.clicked.connect(self._on_view_toggled)
        selector_layout.addWidget(self._view_btn)

        self._sound_btn = QPushButton("Sound: ON")
        self._sound_btn.setFont(f)
        self._sound_btn.setCheckable(True)
        self._sound_btn.setChecked(True)
        self._sound_btn.setFixedWidth(90)
        self._sound_btn.clicked.connect(self._on_sound_toggled)
        selector_layout.addWidget(self._sound_btn)

        main_layout.addWidget(selector_bar)

        # ── Team panels ──────────────────────────────────────────────────────
        self._outer_splitter = QSplitter(Qt.Orientation.Vertical)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._my_widget  = TeamWidget("MY TEAM",   config.flash_duration_ms)
        self._opp_widget = TeamWidget("OPPONENT",  config.flash_duration_ms)
        self._splitter.addWidget(self._my_widget)
        self._splitter.addWidget(self._opp_widget)
        self._splitter.setSizes([700, 700])

        self._comparison = ComparisonWidget()

        self._outer_splitter.addWidget(self._splitter)
        self._outer_splitter.addWidget(self._comparison)
        self._outer_splitter.setSizes([530, 120])
        self._outer_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self._outer_splitter)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Initializing...")

        # Poll timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._do_poll)

        # Start after event loop is running
        QTimer.singleShot(0, self._initial_load)

    # ── Active league helpers ────────────────────────────────────────────────

    @property
    def _active_league_id(self) -> str:
        return self._league_combo.currentData()

    # ── Startup / league init ────────────────────────────────────────────────

    def _initial_load(self) -> None:
        self._status.showMessage("Logging in to Fantrax (launching browser)...")
        try:
            self._fantrax.login()
        except Exception as e:
            self._status.showMessage(f"Login failed: {e}")
            return

        self._load_league(self._active_league_id)

    def _load_league(self, league_id: str) -> None:
        """Initialise (or re-initialise) for the given league and start polling."""
        self._poll_timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._engine = None
        self._last_snapshot = None
        self._fantrax.reset_league_cache()

        self._status.showMessage(f"Fetching league info for {self._league_combo.currentText()}...")
        try:
            self._fantrax.initialize_league(league_id)
        except Exception as e:
            self._status.showMessage(f"Could not load league info: {e}")
            return

        my_team_id = self._config.get_my_team_id(league_id)
        if not my_team_id:
            self._status.showMessage("Detecting your team...")
            try:
                my_team_id = self._fantrax.get_my_team_id(league_id)
                self._config.save_my_team_id(league_id, my_team_id)
                self._status.showMessage(f"Team detected: {my_team_id}")
            except Exception as e:
                self._status.showMessage(f"Could not detect team: {e}")
                return

        self._engine = ScoringEngine(
            self._fantrax,
            self._nhl,
            league_id,
            my_team_id,
        )

        self._do_poll()

    def _on_view_toggled(self, checked: bool) -> None:
        self._view_btn.setText("Period" if checked else "Today")
        self._my_widget.set_view_mode(checked)
        self._opp_widget.set_view_mode(checked)

    def _on_sound_toggled(self, checked: bool) -> None:
        self._sound.enabled = checked
        self._sound_btn.setText("Sound: ON" if checked else "Sound: OFF")

    def _on_league_changed(self, _index: int) -> None:
        # Ignore signals fired before initial load completes
        if not self._fantrax._logged_in:
            return
        self._load_league(self._active_league_id)

    # ── Polling ──────────────────────────────────────────────────────────────

    def _do_poll(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if self._engine is None:
            return

        self._worker = WorkerThread(self._engine)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _on_data_ready(self, snapshot: ScoringSnapshot) -> None:
        changed: set[tuple[str, str]] = set()
        if self._last_snapshot is not None:
            changed = detect_changes(self._last_snapshot, snapshot)

        self._last_snapshot = snapshot

        # Detect newly scratched players on my team
        if changed:
            scratch_ids = {fid for fid, stat in changed if stat == "scratched"}
            if scratch_ids:
                names = [sk.name for sk in snapshot.my_skaters if sk.fantrax_id in scratch_ids and sk.scratched]
                if names:
                    self._scratch_alert = f" | ⚠ SCRATCH: {', '.join(names)}"
                    self._scratch_alert_polls = 10

        self._sound.handle_changes(changed)

        self._my_widget.update_data(snapshot, is_my_team=True,  changed=changed)
        self._opp_widget.update_data(snapshot, is_my_team=False, changed=changed)
        if snapshot.my_team_name:
            self._my_widget.set_label(snapshot.my_team_name)
        if snapshot.opp_team_name:
            self._opp_widget.set_label(snapshot.opp_team_name)
        if snapshot.my_team_name and snapshot.opp_team_name:
            self._comparison.set_labels(snapshot.my_team_name, snapshot.opp_team_name)
        self._comparison.update_data(
            snapshot.my_skater_period_totals,  snapshot.my_goalie_period_totals,
            snapshot.opp_skater_period_totals, snapshot.opp_goalie_period_totals,
            my_sk_pgr=snapshot.my_sk_pgr,   opp_sk_pgr=snapshot.opp_sk_pgr,
            my_gl_pgr=snapshot.my_gl_pgr,   opp_gl_pgr=snapshot.opp_gl_pgr,
            my_sk_pgp=snapshot.my_sk_pgp,   opp_sk_pgp=snapshot.opp_sk_pgp,
            my_gl_pgp=snapshot.my_gl_pgp,   opp_gl_pgp=snapshot.opp_gl_pgp,
        )

        interval_s = (
            self._config.poll_interval_live if snapshot.live_game_count > 0
            else self._config.poll_interval_idle
        )
        self._poll_timer.stop()
        self._poll_timer.start(interval_s * 1000)

        ts = snapshot.timestamp.strftime("%H:%M:%S")
        period_str = ""
        if snapshot.period_start and snapshot.period_end:
            ps = snapshot.period_start.strftime("%b %d").lstrip("0").replace(" 0", " ")
            pe = snapshot.period_end.strftime("%b %d").lstrip("0").replace(" 0", " ")
            period_str = f" | Period: {ps}–{pe}"

        scratch_str = ""
        if self._scratch_alert_polls > 0:
            self._scratch_alert_polls -= 1
            scratch_str = self._scratch_alert
        else:
            self._scratch_alert = ""

        self._status.showMessage(
            f"Last updated: {ts}{period_str} | Live Games: {snapshot.live_game_count} | Poll: {interval_s}s{scratch_str}"
        )

    def _on_error(self, message: str) -> None:
        self._status.showMessage(f"Error: {message}")
        self._poll_timer.stop()
        self._poll_timer.start(self._config.poll_interval_idle * 1000)

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        if self._worker:
            self._worker.quit()
            self._worker.wait(3000)
        super().closeEvent(event)
