from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.ini"


class ConfigError(Exception):
    pass


@dataclass
class AppConfig:
    username: str
    password: str
    leagues: list[tuple[str, str]]        # [(league_id, display_name), ...]
    poll_interval_idle: int
    poll_interval_live: int
    flash_duration_ms: int
    _team_ids: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls) -> "AppConfig":
        if not CONFIG_PATH.exists():
            raise ConfigError(f"config.ini not found at {CONFIG_PATH}")

        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH, encoding="utf-8")

        try:
            username = parser["fantrax"]["username"].strip()
            password = parser["fantrax"]["password"].strip()
        except KeyError as e:
            raise ConfigError(f"Missing config key: {e}") from e

        if not username or username == "your_email@example.com":
            raise ConfigError("Please set your Fantrax username in config.ini")
        if not password or password == "yourpassword":
            raise ConfigError("Please set your Fantrax password in config.ini")

        # Load leagues list (ordered as written in config)
        leagues: list[tuple[str, str]] = []
        if parser.has_section("leagues"):
            for league_id, name in parser.items("leagues"):
                leagues.append((league_id.strip(), name.strip()))
        if not leagues:
            raise ConfigError("No leagues defined in [leagues] section of config.ini")

        # Load per-league team IDs
        team_ids: dict[str, str] = {}
        if parser.has_section("team_ids"):
            for league_id, team_id in parser.items("team_ids"):
                team_ids[league_id.strip()] = team_id.strip()

        try:
            poll_idle = int(parser["app"].get("poll_interval_idle", "30"))
            poll_live = int(parser["app"].get("poll_interval_live", "10"))
            flash_ms  = int(parser["app"].get("flash_duration_ms", "10000"))
        except (KeyError, ValueError) as e:
            raise ConfigError(f"Invalid app config value: {e}") from e

        return cls(
            username=username,
            password=password,
            leagues=leagues,
            poll_interval_idle=poll_idle,
            poll_interval_live=poll_live,
            flash_duration_ms=flash_ms,
            _team_ids=team_ids,
        )

    def get_my_team_id(self, league_id: str) -> str:
        return self._team_ids.get(league_id, "")

    def save_my_team_id(self, league_id: str, team_id: str) -> None:
        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH, encoding="utf-8")
        if not parser.has_section("team_ids"):
            parser.add_section("team_ids")
        parser["team_ids"][league_id] = team_id
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            parser.write(f)
        self._team_ids[league_id] = team_id

    # Convenience for code that still uses the old single-league API
    @property
    def league_id(self) -> str:
        return self.leagues[0][0] if self.leagues else ""

    @property
    def my_team_id(self) -> str:
        return self.get_my_team_id(self.league_id)
