from __future__ import annotations

import sys
from pathlib import Path

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    _MULTIMEDIA_AVAILABLE = True
except ImportError:
    _MULTIMEDIA_AVAILABLE = False


def _sounds_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "sounds"
    return Path(__file__).parent.parent.parent / "sounds"


class SoundPlayer:
    """Plays MP3 sound effects for stat changes. Silently no-ops if QtMultimedia unavailable."""

    # Stat names that trigger each sound (priority order: goal > ga > hit)
    GOAL_STATS = {"goals", "assists"}
    GA_STATS   = {"goals_against"}
    HIT_STATS  = {"hits", "blk"}

    def __init__(self):
        self._enabled = True
        self._players: dict[str, tuple] = {}  # name → (QMediaPlayer, QAudioOutput)

        if not _MULTIMEDIA_AVAILABLE:
            return

        sounds = _sounds_dir()
        for name, filename in [("goal", "goal.mp3"), ("ga", "GA.mp3"), ("hit", "hitt.mp3")]:
            path = sounds / filename
            if path.exists():
                player = QMediaPlayer()
                audio = QAudioOutput()
                player.setAudioOutput(audio)
                player.setSource(QUrl.fromLocalFile(str(path)))
                self._players[name] = (player, audio)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool) -> None:
        self._enabled = val

    def handle_changes(self, changed: set[tuple[str, str]]) -> None:
        """Call with the detect_changes result. Plays highest-priority matching sound."""
        if not self._enabled or not changed:
            return

        stats = {stat for _, stat in changed}

        if stats & self.GOAL_STATS:
            self._play("goal")
        elif stats & self.GA_STATS:
            self._play("ga")
        elif stats & self.HIT_STATS:
            self._play("hit")

    def _play(self, name: str) -> None:
        entry = self._players.get(name)
        if entry:
            player, _ = entry
            player.stop()
            player.play()
