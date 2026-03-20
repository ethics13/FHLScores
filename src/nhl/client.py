from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

NHL_API = "https://api-web.nhle.com"


@dataclass
class NHLGame:
    game_id: int
    state: str  # "LIVE", "OFF", "FUT", "PRE", etc.
    away_team: str
    home_team: str


@dataclass
class NHLSkaterStats:
    player_id: int
    name_default: str
    team_abbrev: str
    position: str
    goals: int = 0
    assists: int = 0
    points: int = 0
    blk: int = 0
    hits: int = 0
    sog: int = 0
    ppg: int = 0
    ppp: int = 0
    gwg: int = 0


@dataclass
class NHLGoalieStats:
    player_id: int
    name_default: str
    team_abbrev: str
    wins: int = 0
    ot_losses: int = 0
    shots_against: int = 0
    saves: int = 0
    goals_against: int = 0
    toi_seconds: int = 0
    has_played: bool = False

    @property
    def gaa(self) -> float:
        if self.toi_seconds <= 0:
            return 0.0
        return (self.goals_against / self.toi_seconds) * 3600

    @property
    def save_pct(self) -> float:
        if self.shots_against <= 0:
            return 0.0
        return self.saves / self.shots_against

    @property
    def shutout(self) -> bool:
        return self.goals_against == 0 and self.toi_seconds >= 3600


@dataclass
class NHLBoxscore:
    game_id: int
    skaters: list[NHLSkaterStats] = field(default_factory=list)
    goalies: list[NHLGoalieStats] = field(default_factory=list)


class NHLClient:
    def __init__(self):
        self._client = httpx.Client(
            base_url=NHL_API,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "FHLScoring/1.0"},
        )
        self._gwg_cache: dict[int, dict[int, int]] = {}

    def get_todays_games(self) -> list[NHLGame]:
        from datetime import date
        today = date.today().isoformat()
        return self.get_games_for_date(today)

    def get_games_for_date(self, date_str: str) -> list[NHLGame]:
        resp = self._client.get(f"/v1/schedule/{date_str}")
        resp.raise_for_status()
        data = resp.json()
        games: list[NHLGame] = []
        for day in data.get("gameWeek", []):
            if day.get("date") == date_str:
                for g in day.get("games", []):
                    games.append(NHLGame(
                        game_id=g["id"],
                        state=g.get("gameState", "FUT"),
                        away_team=g.get("awayTeam", {}).get("abbrev", ""),
                        home_team=g.get("homeTeam", {}).get("abbrev", ""),
                    ))
                break
        return games

    def _fetch_games_in_range(
        self, start, end, skip_completed_on: object = None
    ) -> dict[str, int]:
        """Fetch all games between start and end, optionally skipping completed games on skip_completed_on.
        Makes two fetches if the range spans more than one NHL gameWeek."""
        from datetime import date as _date, timedelta
        _DONE = {"OFF", "FINAL", "OVER"}
        team_games: dict[str, int] = {}
        fetch_dates = [start]
        # If range is > 7 days or end is in a later week, fetch the end week too
        if (end - start).days >= 7:
            fetch_dates.append(end)
        seen_game_ids: set = set()
        for fetch_date in fetch_dates:
            try:
                resp = self._client.get(f"/v1/schedule/{fetch_date.isoformat()}")
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            for day in data.get("gameWeek", []):
                try:
                    day_date = _date.fromisoformat(day["date"])
                except (KeyError, ValueError):
                    continue
                if day_date < start or day_date > end:
                    continue
                for g in day.get("games", []):
                    gid = g.get("id")
                    if gid in seen_game_ids:
                        continue
                    seen_game_ids.add(gid)
                    if skip_completed_on and day_date == skip_completed_on:
                        if g.get("gameState", "") in _DONE:
                            continue
                    at = g.get("awayTeam", {}).get("abbrev", "").upper()
                    ht = g.get("homeTeam", {}).get("abbrev", "").upper()
                    if at:
                        team_games[at] = team_games.get(at, 0) + 1
                    if ht:
                        team_games[ht] = team_games.get(ht, 0) + 1
        return team_games

    def get_total_games_in_period(self, period_start, period_end) -> dict[str, int]:
        """Return {team_abbrev: total_games} for every game between period_start and period_end."""
        return self._fetch_games_in_range(period_start, period_end)

    def get_games_remaining_in_period(self, period_end) -> dict[str, int]:
        """Return {team_abbrev: games_remaining} from today through period_end."""
        from datetime import date as _date
        today = _date.today()
        return self._fetch_games_in_range(today, period_end, skip_completed_on=today)

    def get_live_games(self) -> list[NHLGame]:
        return [g for g in self.get_todays_games() if g.state == "LIVE"]

    def get_boxscore(self, game_id: int) -> NHLBoxscore:
        resp = self._client.get(f"/v1/gamecenter/{game_id}/boxscore")
        resp.raise_for_status()
        data = resp.json()

        skaters: list[NHLSkaterStats] = []
        goalies: list[NHLGoalieStats] = []

        player_by_game = data.get("playerByGameStats", {})
        for side in ("awayTeam", "homeTeam"):
            team_data = player_by_game.get(side, {})
            team_abbrev = data.get(side, {}).get("abbrev", "")
            skaters.extend(_parse_skaters(team_data, team_abbrev))
            goalies.extend(_parse_goalies(team_data, team_abbrev))

        return NHLBoxscore(game_id=game_id, skaters=skaters, goalies=goalies)

    def resolve_gwg(self, game_id: int) -> dict[int, int]:
        """Return {player_id: gwg_count} from play-by-play. Cached per game."""
        if game_id in self._gwg_cache:
            return self._gwg_cache[game_id]

        resp = self._client.get(f"/v1/gamecenter/{game_id}/play-by-play")
        resp.raise_for_status()
        data = resp.json()

        # Determine final scores
        away_abbrev = data.get("awayTeam", {}).get("abbrev", "")
        home_abbrev = data.get("homeTeam", {}).get("abbrev", "")

        plays = data.get("plays", [])
        # Only care about goal events
        goal_events = [
            p for p in plays
            if p.get("typeDescKey") == "goal"
        ]

        # Track score as we process goals
        away_score = 0
        home_score = 0
        gwg_player_id: Optional[int] = None

        # We need final period score to determine winner/loser
        # Get final score from linescore if available
        linescore = data.get("linescore", {})
        final_away = _get_final_score(linescore, "away")
        final_home = _get_final_score(linescore, "home")

        if final_away is None or final_home is None:
            # Game not finished — can't determine GWG
            return {}

        # Determine which team won and loser's final score
        if final_away > final_home:
            winner_abbrev = away_abbrev
            loser_final = final_home
        else:
            winner_abbrev = home_abbrev
            loser_final = final_away

        gwg_threshold = loser_final + 1

        gwg_counts: dict[int, int] = {}
        for event in goal_events:
            scoring_team = event.get("details", {}).get("eventOwnerTeamId")
            event_away = event.get("details", {}).get("awayScore", 0)
            event_home = event.get("details", {}).get("homeScore", 0)

            # Figure out team that scored by comparing score deltas
            if event_away > away_score:
                scoring_abbrev = away_abbrev
                away_score = event_away
            elif event_home > home_score:
                scoring_abbrev = home_abbrev
                home_score = event_home
            else:
                # Fallback via eventOwnerTeamId matching
                scoring_abbrev = away_abbrev if scoring_team == data.get("awayTeam", {}).get("id") else home_abbrev

            if scoring_abbrev == winner_abbrev:
                winner_score_now = event_away if winner_abbrev == away_abbrev else event_home
                if winner_score_now == gwg_threshold and gwg_player_id is None:
                    scorer_id = event.get("details", {}).get("scoringPlayerId")
                    if scorer_id:
                        gwg_player_id = int(scorer_id)
                        gwg_counts[gwg_player_id] = gwg_counts.get(gwg_player_id, 0) + 1

        self._gwg_cache[game_id] = gwg_counts
        return gwg_counts


def _parse_skaters(team_data: dict, team_abbrev: str) -> list[NHLSkaterStats]:
    skaters = []
    for group_key in ("forwards", "defense"):
        for p in team_data.get(group_key, []):
            s = p.get("skaterStats", p)
            skater = NHLSkaterStats(
                player_id=p.get("playerId", 0),
                name_default=_format_name(p.get("name", {}).get("default", "")),
                team_abbrev=team_abbrev,
                position=p.get("position", ""),
                goals=s.get("goals", 0),
                assists=s.get("assists", 0),
                points=s.get("points", 0),
                blk=s.get("blockedShots", s.get("blocks", s.get("blk", 0))),
                hits=s.get("hits", 0),
                sog=s.get("shots", s.get("sog", 0)),
                ppg=s.get("powerPlayGoals", s.get("ppg", 0)),
                ppp=s.get("powerPlayPoints", s.get("ppp",
                    s.get("powerPlayGoals", 0) + s.get("powerPlayAssists", 0))),
                gwg=0,  # resolved separately
            )
            skaters.append(skater)
    return skaters


def _parse_goalies(team_data: dict, team_abbrev: str) -> list[NHLGoalieStats]:
    goalies = []
    for p in team_data.get("goalies", []):
        gs = p.get("goalieStats", p)
        shots_against = gs.get("shotsAgainst", 0)
        saves = gs.get("saves", 0)
        goals_against = gs.get("goalsAgainst", 0)
        toi_str = gs.get("toi", "0:00")
        toi_seconds = _toi_to_seconds(toi_str)
        decision = gs.get("decision", "")

        goalie = NHLGoalieStats(
            player_id=p.get("playerId", 0),
            name_default=_format_name(p.get("name", {}).get("default", "")),
            team_abbrev=team_abbrev,
            wins=1 if decision == "W" else 0,
            ot_losses=1 if decision == "O" else 0,
            shots_against=shots_against,
            saves=saves,
            goals_against=goals_against,
            toi_seconds=toi_seconds,
            has_played=shots_against > 0,
        )
        goalies.append(goalie)
    return goalies


def _format_name(full_name: str) -> str:
    """Convert 'Brock Boeser' → 'B. Boeser'."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0].upper()}. {' '.join(parts[1:])}"
    return full_name


def _toi_to_seconds(toi: str) -> int:
    """Convert 'MM:SS' string to total seconds."""
    try:
        parts = toi.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(toi)
    except (ValueError, AttributeError):
        return 0


def _get_final_score(linescore: dict, side: str) -> Optional[int]:
    """Extract final score from linescore for 'away' or 'home'."""
    totals = linescore.get("totals", {})
    val = totals.get(side)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    # Try alternate structure
    by_period = linescore.get("byPeriod", [])
    if by_period:
        score = sum(p.get(side, 0) for p in by_period)
        return score
    return None
