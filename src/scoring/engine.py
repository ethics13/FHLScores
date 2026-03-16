from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from fantrax.client import FantraxClient, FantraxPlayer
from nhl.client import NHLClient, NHLSkaterStats, NHLGoalieStats, NHLGame


# ---------------------------------------------------------------------------
# Snapshot types
# ---------------------------------------------------------------------------

@dataclass
class SkaterRow:
    fantrax_id: str
    name: str
    team_abbrev: str
    nhl_opponent: str
    position: str
    game_state: str = ""   # "LIVE", "FUT", "OFF", ""
    wperf: float = 0.0     # scoring-period performance score
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
class GoalieRow:
    fantrax_id: str
    name: str
    team_abbrev: str
    nhl_opponent: str
    game_state: str = ""   # "LIVE", "FUT", "OFF", ""
    wperf: float = 0.0     # scoring-period performance score
    wins: int = 0
    ot_losses: int = 0
    gaa: float = 0.0
    save_pct: float = 0.0
    shutout: int = 0
    shots_against: int = 0
    saves: int = 0
    goals_against: int = 0
    toi_seconds: int = 0
    has_played: bool = False


@dataclass
class SkaterTotals:
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
class GoalieTotals:
    wins: int = 0
    ot_losses: int = 0
    gaa: float = 0.0       # period: goals-against count; daily: rate
    save_pct: float = 0.0  # weighted average
    shutout: int = 0
    shots_against: int = 0
    saves: int = 0
    goals_against: int = 0


@dataclass
class ScoringSnapshot:
    timestamp: datetime
    my_skaters: list[SkaterRow]
    my_goalies: list[GoalieRow]
    opp_skaters: list[SkaterRow]
    opp_goalies: list[GoalieRow]
    # Today-only totals (shown in team table totals rows)
    my_skater_totals: SkaterTotals
    my_goalie_totals: GoalieTotals
    opp_skater_totals: SkaterTotals
    opp_goalie_totals: GoalieTotals
    # Full scoring-period totals (shown in comparison widget)
    my_skater_period_totals: SkaterTotals
    my_goalie_period_totals: GoalieTotals
    opp_skater_period_totals: SkaterTotals
    opp_goalie_period_totals: GoalieTotals
    live_game_count: int = 0
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    my_team_name: str = ""
    opp_team_name: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """'Brock Boeser' or 'B. Boeser' → 'b.boeser'."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower().strip()
    parts = name.split()
    if not parts:
        return ""
    first = parts[0].rstrip(".")
    last = " ".join(parts[1:]) if len(parts) > 1 else first
    return f"{first[0]}.{last.replace(' ', '')}" if first else last


def _fantrax_skater_totals(group: dict[str, dict[str, float]]) -> SkaterTotals:
    """Build SkaterTotals from Fantrax active-stats group dict."""
    t = SkaterTotals()
    for ps in group.values():
        t.goals   += int(ps.get("goals", 0))
        t.assists += int(ps.get("assists", 0))
        t.blk     += int(ps.get("blk", 0))
        t.hits    += int(ps.get("hits", 0))
        t.sog     += int(ps.get("sog", 0))
        t.ppg     += int(ps.get("ppg", 0))
        t.ppp     += int(ps.get("ppp", 0))
        t.gwg     += int(ps.get("gwg", 0))
    t.points = t.goals + t.assists
    return t


def _fantrax_goalie_totals(group: dict[str, dict[str, float]]) -> GoalieTotals:
    """Build GoalieTotals from Fantrax active-stats group dict.
    gaa here is goals-against COUNT (not a rate), so it sums across goalies."""
    t = GoalieTotals()
    total_sv  = 0.0
    total_sa  = 0.0
    for ps in group.values():
        t.wins          += int(ps.get("wins", 0))
        t.ot_losses     += int(ps.get("ot_losses", 0))
        t.shutout       += int(ps.get("shutout", 0))
        t.shots_against += int(ps.get("shots_against", 0))
        sv = int(ps.get("saves", 0))
        t.saves         += sv
        t.gaa           += float(ps.get("gaa", 0.0))   # sum goals-against counts
        total_sv        += sv
        total_sa        += float(ps.get("shots_against", 0) or (sv + ps.get("gaa", 0.0)))
    if total_sa > 0:
        t.save_pct = total_sv / total_sa
    return t


def _sum_skaters(rows: list[SkaterRow]) -> SkaterTotals:
    t = SkaterTotals()
    for r in rows:
        t.goals += r.goals
        t.assists += r.assists
        t.points += r.points
        t.blk += r.blk
        t.hits += r.hits
        t.sog += r.sog
        t.ppg += r.ppg
        t.ppp += r.ppp
        t.gwg += r.gwg
    return t


def _sum_goalies(rows: list[GoalieRow]) -> GoalieTotals:
    t = GoalieTotals()
    total_toi = 0
    total_ga = 0

    for r in (r for r in rows if r.has_played):
        t.wins += r.wins
        t.ot_losses += r.ot_losses
        t.shutout += r.shutout
        t.shots_against += r.shots_against
        t.saves += r.saves
        total_ga += r.goals_against
        total_toi += r.toi_seconds

    t.goals_against = total_ga
    if t.shots_against > 0:
        t.save_pct = t.saves / t.shots_against
    if total_toi > 0:
        t.gaa = (total_ga / total_toi) * 3600
    return t


# ---------------------------------------------------------------------------
# WPerf helpers
# ---------------------------------------------------------------------------

def _compute_skater_wperf(ps: dict) -> float:
    """Score a skater's scoring-period stats. Higher = better performance."""
    return (
        ps.get("goals",   0) * 4.0 +
        ps.get("assists", 0) * 3.0 +
        ps.get("ppp",     0) * 2.0 +
        ps.get("gwg",     0) * 5.0 +
        ps.get("sog",     0) * 0.3 +
        ps.get("hits",    0) * 0.5 +
        ps.get("blk",     0) * 0.5
    )


def _compute_goalie_wperf(ps: dict) -> float:
    """Score a goalie's scoring-period stats. Higher = better performance."""
    wins     = ps.get("wins",     0)
    saves    = ps.get("saves",    0)
    save_pct = float(ps.get("save_pct", 0.0))
    if wins == 0 and saves == 0:
        return 0.0
    score = wins * 5.0 + saves * 0.12
    if save_pct > 0:
        score += max(0.0, save_pct - 0.850) * 40.0
    return score


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ScoringEngine:
    def __init__(
        self,
        fantrax: FantraxClient,
        nhl: NHLClient,
        league_id: str,
        my_team_id: str,
    ):
        self._fantrax = fantrax
        self._nhl = nhl
        self._league_id = league_id
        self._my_team_id = my_team_id
        self._last_snapshot: Optional[ScoringSnapshot] = None
        # Cache completed boxscores so past days aren't re-fetched every poll
        self._completed_boxscores: dict[int, NHLBoxscore] = {}

    def refresh(self) -> ScoringSnapshot:
        _LIVE_STATES = {"LIVE", "CRIT"}
        _DONE_STATES = {"OFF", "FINAL", "OVER"}

        today = date.today()

        # Get opponent, period dates, and exact Fantrax active-player stats in one call
        opp_team_id, period_start, period_end, active_stats = self._fantrax.get_matchup_info(
            self._my_team_id, self._league_id
        )
        # Only need today's NHL games — period totals come from Fantrax directly
        today_games = self._nhl.get_games_for_date(today.isoformat())
        live_games = [g for g in today_games if g.state in _LIVE_STATES]

        # Today's teams for table filter + opponent column + game state
        playing_teams: set[str] = set()
        team_to_opponent: dict[str, str] = {}
        team_to_state: dict[str, str] = {}
        for g in today_games:
            at = g.away_team.upper()
            ht = g.home_team.upper()
            playing_teams.add(at)
            playing_teams.add(ht)
            team_to_opponent[at] = f"@{ht}"
            team_to_opponent[ht] = f"vs {at}"
            state = "LIVE" if g.state in _LIVE_STATES else ("OFF" if g.state in _DONE_STATES else "FUT")
            team_to_state[at] = state
            team_to_state[ht] = state

        # Fetch today's boxscores for active/completed games
        skater_by_id: dict[int, NHLSkaterStats] = {}
        goalie_by_id: dict[int, NHLGoalieStats] = {}

        today_active = [g for g in today_games if g.state in _LIVE_STATES | _DONE_STATES]
        for game in today_active:
            try:
                if game.game_id in self._completed_boxscores:
                    boxscore = self._completed_boxscores[game.game_id]
                else:
                    boxscore = self._nhl.get_boxscore(game.game_id)
                    if game.state in _DONE_STATES:
                        self._completed_boxscores[game.game_id] = boxscore

                for sk in boxscore.skaters:
                    skater_by_id[sk.player_id] = sk

                for gl in boxscore.goalies:
                    goalie_by_id[gl.player_id] = gl

                # Apply GWG for completed games
                if game.state in _DONE_STATES:
                    gwg = self._nhl.resolve_gwg(game.game_id)
                    for player_id, count in gwg.items():
                        if player_id in skater_by_id:
                            skater_by_id[player_id].gwg += count

            except Exception:
                continue

        # Build normalized name maps from accumulated stats
        nhl_skater_map: dict[str, list[NHLSkaterStats]] = {}
        nhl_goalie_map: dict[str, list[NHLGoalieStats]] = {}
        for sk in skater_by_id.values():
            key = _normalize_name(sk.name_default)
            nhl_skater_map.setdefault(key, []).append(sk)
        for gl in goalie_by_id.values():
            key = _normalize_name(gl.name_default)
            nhl_goalie_map.setdefault(key, []).append(gl)

        # 2. Get rosters (opp_team_id already resolved above via get_matchup_info)
        my_roster = self._fantrax.get_roster(self._my_team_id, self._league_id)
        opp_roster = self._fantrax.get_roster(opp_team_id, self._league_id)

        # Today's players for the tables (filtered to teams playing today)
        my_skaters, my_goalies = self._build_rows(my_roster, nhl_skater_map, nhl_goalie_map, playing_teams, team_to_opponent, team_to_state)
        opp_skaters, opp_goalies = self._build_rows(opp_roster, nhl_skater_map, nhl_goalie_map, playing_teams, team_to_opponent, team_to_state)

        # Period totals from Fantrax — exact match to their live scoring page
        my_ast  = active_stats.get(self._my_team_id, {})
        opp_ast = active_stats.get(opp_team_id, {})

        # Compute per-player scoring-period performance scores
        for row in my_skaters:
            row.wperf = _compute_skater_wperf(my_ast.get("2010", {}).get(row.fantrax_id, {}))
        for row in my_goalies:
            row.wperf = _compute_goalie_wperf(my_ast.get("2020", {}).get(row.fantrax_id, {}))
        for row in opp_skaters:
            row.wperf = _compute_skater_wperf(opp_ast.get("2010", {}).get(row.fantrax_id, {}))
        for row in opp_goalies:
            row.wperf = _compute_goalie_wperf(opp_ast.get("2020", {}).get(row.fantrax_id, {}))

        snapshot = ScoringSnapshot(
            timestamp=datetime.now(),
            my_skaters=my_skaters,
            my_goalies=my_goalies,
            opp_skaters=opp_skaters,
            opp_goalies=opp_goalies,
            # Today-only totals (sum of visible table rows)
            my_skater_totals=_sum_skaters(my_skaters),
            my_goalie_totals=_sum_goalies(my_goalies),
            opp_skater_totals=_sum_skaters(opp_skaters),
            opp_goalie_totals=_sum_goalies(opp_goalies),
            # Scoring-period totals (from Fantrax, for comparison widget)
            my_skater_period_totals=_fantrax_skater_totals(my_ast.get("2010", {})),
            my_goalie_period_totals=_fantrax_goalie_totals(my_ast.get("2020", {})),
            opp_skater_period_totals=_fantrax_skater_totals(opp_ast.get("2010", {})),
            opp_goalie_period_totals=_fantrax_goalie_totals(opp_ast.get("2020", {})),
            live_game_count=len(live_games),
            period_start=period_start,
            period_end=period_end,
            my_team_name=self._fantrax.get_team_name(self._my_team_id),
            opp_team_name=self._fantrax.get_team_name(opp_team_id),
        )
        self._last_snapshot = snapshot
        return snapshot

    def _build_rows(
        self,
        roster: list[FantraxPlayer],
        nhl_skater_map: dict[str, list[NHLSkaterStats]],
        nhl_goalie_map: dict[str, list[NHLGoalieStats]],
        playing_teams: set[str] = None,
        team_to_opponent: dict[str, str] = None,
        team_to_state: dict[str, str] = None,
    ) -> tuple[list[SkaterRow], list[GoalieRow]]:
        skaters: list[SkaterRow] = []
        goalies: list[GoalieRow] = []

        for fp in roster:
            team_up = fp.team_abbrev.upper()
            # Skip players whose NHL team has no game today
            if playing_teams is not None and team_up not in playing_teams:
                continue
            opp_str = (team_to_opponent or {}).get(team_up, "")
            game_state = (team_to_state or {}).get(team_up, "")
            norm = _normalize_name(fp.name)
            if fp.position.upper() in ("G", "GOALIE"):
                goalie_stats = _match_goalie(norm, fp.team_abbrev, nhl_goalie_map)
                row = GoalieRow(
                    fantrax_id=fp.fantrax_id,
                    name=fp.name,
                    team_abbrev=fp.team_abbrev,
                    nhl_opponent=opp_str,
                    game_state=game_state,
                )
                if goalie_stats:
                    row.wins = goalie_stats.wins
                    row.ot_losses = goalie_stats.ot_losses
                    row.gaa = goalie_stats.gaa
                    row.save_pct = goalie_stats.save_pct
                    row.shutout = 1 if goalie_stats.shutout else 0
                    row.shots_against = goalie_stats.shots_against
                    row.saves = goalie_stats.saves
                    row.goals_against = goalie_stats.goals_against
                    row.toi_seconds = goalie_stats.toi_seconds
                    row.has_played = goalie_stats.has_played
                goalies.append(row)
            else:
                skater_stats = _match_skater(norm, fp.team_abbrev, nhl_skater_map)
                row = SkaterRow(
                    fantrax_id=fp.fantrax_id,
                    name=fp.name,
                    team_abbrev=fp.team_abbrev,
                    nhl_opponent=opp_str,
                    position=fp.position,
                    game_state=game_state,
                )
                if skater_stats:
                    row.goals = skater_stats.goals
                    row.assists = skater_stats.assists
                    row.points = skater_stats.points
                    row.blk = skater_stats.blk
                    row.hits = skater_stats.hits
                    row.sog = skater_stats.sog
                    row.ppg = skater_stats.ppg
                    row.ppp = skater_stats.ppp
                    row.gwg = skater_stats.gwg
                skaters.append(row)

        skaters.sort(key=_skater_sort_key)
        return skaters, goalies

    @property
    def last_snapshot(self) -> Optional[ScoringSnapshot]:
        return self._last_snapshot


_POS_ORDER = {"C": 0, "LW": 1, "RW": 2, "W": 3, "D": 4}


def _skater_sort_key(row: "SkaterRow") -> int:
    # Use the first token of the position string (e.g. "C,LW" → "C")
    primary = row.position.split(",")[0].strip().upper()
    return _POS_ORDER.get(primary, 5)


def _match_skater(
    norm_name: str,
    team_abbrev: str,
    nhl_map: dict[str, list[NHLSkaterStats]],
) -> Optional[NHLSkaterStats]:
    candidates = nhl_map.get(norm_name, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Disambiguate by team
    for c in candidates:
        if c.team_abbrev.upper() == team_abbrev.upper():
            return c
    return candidates[0]  # fallback


def _match_goalie(
    norm_name: str,
    team_abbrev: str,
    nhl_map: dict[str, list[NHLGoalieStats]],
) -> Optional[NHLGoalieStats]:
    candidates = nhl_map.get(norm_name, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for c in candidates:
        if c.team_abbrev.upper() == team_abbrev.upper():
            return c
    return candidates[0]


def detect_changes(
    old: ScoringSnapshot, new: ScoringSnapshot
) -> set[tuple[str, str]]:
    """Return set of (fantrax_id, stat_name) for changed values."""
    changed: set[tuple[str, str]] = set()

    def diff_skaters(old_list: list[SkaterRow], new_list: list[SkaterRow]) -> None:
        old_map = {r.fantrax_id: r for r in old_list}
        for nr in new_list:
            or_ = old_map.get(nr.fantrax_id)
            if not or_:
                continue
            for stat in ("goals", "assists", "points", "blk", "hits", "sog", "ppg", "ppp", "gwg"):
                if getattr(or_, stat) != getattr(nr, stat):
                    changed.add((nr.fantrax_id, stat))

    def diff_goalies(old_list: list[GoalieRow], new_list: list[GoalieRow]) -> None:
        old_map = {r.fantrax_id: r for r in old_list}
        for nr in new_list:
            or_ = old_map.get(nr.fantrax_id)
            if not or_:
                continue
            for stat in ("wins", "ot_losses", "goals_against", "save_pct", "shutout", "shots_against", "saves"):
                if getattr(or_, stat) != getattr(nr, stat):
                    changed.add((nr.fantrax_id, stat))

    diff_skaters(old.my_skaters, new.my_skaters)
    diff_skaters(old.opp_skaters, new.opp_skaters)
    diff_goalies(old.my_goalies, new.my_goalies)
    diff_goalies(old.opp_goalies, new.opp_goalies)

    return changed
