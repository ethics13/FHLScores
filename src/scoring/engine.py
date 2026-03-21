from __future__ import annotations

import time as _time
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
    games_remaining: int = 0
    games_played: int = 0
    scratched: bool = False   # team had LIVE/OFF game but player not in NHL boxscore
    ros_pct: float = 0.0      # % rostered globally (background-fetched; 0 until available)
    # Today's NHL stats
    goals: int = 0
    assists: int = 0
    points: int = 0
    blk: int = 0
    hits: int = 0
    sog: int = 0
    ppg: int = 0
    ppp: int = 0
    gwg: int = 0
    # Full scoring-period stats (from Fantrax)
    p_goals: int = 0
    p_assists: int = 0
    p_blk: int = 0
    p_hits: int = 0
    p_sog: int = 0
    p_ppp: int = 0
    p_gwg: int = 0


@dataclass
class GoalieRow:
    fantrax_id: str
    name: str
    team_abbrev: str
    nhl_opponent: str
    game_state: str = ""   # "LIVE", "FUT", "OFF", ""
    wperf: float = 0.0     # scoring-period performance score
    games_remaining: int = 0
    games_played: int = 0
    # Today's NHL stats
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
    ros_pct: float = 0.0      # % rostered globally (background-fetched; 0 until available)
    # Full scoring-period stats (from Fantrax)
    p_wins: int = 0
    p_goals_against: int = 0
    p_saves: int = 0
    p_save_pct: float = 0.0


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
class WaiverRow:
    """An unowned player available on the waiver wire who played today."""
    name: str
    team_abbrev: str
    position: str
    nhl_opponent: str
    game_state: str
    games_remaining: int = 0
    projected: float = 0.0    # sort key: period_wperf + projected_remaining
    ros_pct: float = 0.0      # % rostered globally (populated after first background fetch)
    # Period stats (accumulated across scoring period; today always included)
    p_goals: int = 0
    p_assists: int = 0
    p_blk: int = 0
    p_hits: int = 0
    p_sog: int = 0
    p_ppp: int = 0
    p_gwg: int = 0
    # Goalie period stats
    p_wins: int = 0
    p_saves: int = 0
    p_save_pct: float = 0.0
    p_goals_against: int = 0


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
    # All players active during the scoring period (for Period view)
    my_period_skaters: list[SkaterRow] = field(default_factory=list)
    my_period_goalies: list[GoalieRow] = field(default_factory=list)
    opp_period_skaters: list[SkaterRow] = field(default_factory=list)
    opp_period_goalies: list[GoalieRow] = field(default_factory=list)
    # Sum of games remaining/played across all period players (for clinch calculations)
    my_sk_pgr: int = 0
    opp_sk_pgr: int = 0
    my_gl_pgr: int = 0
    opp_gl_pgr: int = 0
    my_sk_pgp: int = 0
    opp_sk_pgp: int = 0
    my_gl_pgp: int = 0
    opp_gl_pgp: int = 0
    live_game_count: int = 0
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    my_team_name: str = ""
    opp_team_name: str = ""
    available_skaters: list[WaiverRow] = field(default_factory=list)
    available_goalies: list[WaiverRow] = field(default_factory=list)


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


def _populate_period_stats(
    skaters: list[SkaterRow],
    goalies: list[GoalieRow],
    sk_group: dict,
    gl_group: dict,
) -> None:
    for row in skaters:
        ps = sk_group.get(row.fantrax_id, {})
        row.wperf     = _compute_skater_wperf(ps)
        row.p_goals   = int(ps.get("goals",   0))
        row.p_assists = int(ps.get("assists", 0))
        row.p_blk     = int(ps.get("blk",     0))
        row.p_hits    = int(ps.get("hits",    0))
        row.p_sog     = int(ps.get("sog",     0))
        row.p_ppp     = int(ps.get("ppp",     0))
        row.p_gwg     = int(ps.get("gwg",     0))
    for row in goalies:
        ps = gl_group.get(row.fantrax_id, {})
        row.wperf           = _compute_goalie_wperf(ps)
        row.p_wins          = int(ps.get("wins",  0))
        row.p_saves         = int(ps.get("saves", 0))
        ga                  = int(round(float(ps.get("gaa", 0.0))))
        row.p_goals_against = ga
        inf_sa = row.p_saves + ga
        row.p_save_pct      = row.p_saves / inf_sa if inf_sa > 0 else 0.0


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
        # Cache of all rostered player names (refreshed every 2 minutes)
        self._rostered_names_cache: set[str] = set()
        self._rostered_names_ts: float = 0.0
        # Accumulated per-player NHL stats across the scoring period (for waiver ranking)
        # dict[player_id] → {"goals":n, "assists":n, ..., "games":n}
        self._period_player_stats: dict[int, dict] = {}
        self._period_stats_game_ids: set[int] = set()   # game_ids already processed
        self._period_cache_key: tuple = (None, None)    # (period_start, period_end)

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

        # Games remaining per team through end of scoring period
        team_gp: dict[str, int] = {}
        team_total: dict[str, int] = {}
        if period_end:
            try:
                team_gp = self._nhl.get_games_remaining_in_period(period_end)
            except Exception:
                pass
            if period_start:
                try:
                    team_total = self._nhl.get_total_games_in_period(period_start, period_end)
                except Exception:
                    pass
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
        # Track teams whose boxscores were successfully fetched (used for scratch detection)
        teams_with_boxscores: set[str] = set()

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
                    teams_with_boxscores.add(sk.team_abbrev.upper())

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

        # Teams whose boxscores were fetched = eligible for scratch detection
        active_teams = teams_with_boxscores

        # Today's players for the tables (filtered to teams playing today)
        my_skaters, my_goalies = self._build_rows(my_roster, nhl_skater_map, nhl_goalie_map, playing_teams, active_teams, team_to_opponent, team_to_state, team_gp, team_total)
        opp_skaters, opp_goalies = self._build_rows(opp_roster, nhl_skater_map, nhl_goalie_map, playing_teams, active_teams, team_to_opponent, team_to_state, team_gp, team_total)

        # Period totals from Fantrax — exact match to their live scoring page
        my_ast  = active_stats.get(self._my_team_id, {})
        opp_ast = active_stats.get(opp_team_id, {})

        # Period rows — all roster players regardless of today's game schedule (no scratch detection)
        my_period_sk, my_period_gl = self._build_rows(
            my_roster, nhl_skater_map, nhl_goalie_map, None, None, team_to_opponent, team_to_state, team_gp, team_total)
        opp_period_sk, opp_period_gl = self._build_rows(
            opp_roster, nhl_skater_map, nhl_goalie_map, None, None, team_to_opponent, team_to_state, team_gp, team_total)

        # Populate period stats on today rows AND period rows
        for team_sk, team_gl, ast in (
            (my_skaters,    my_goalies,    my_ast),
            (opp_skaters,   opp_goalies,   opp_ast),
            (my_period_sk,  my_period_gl,  my_ast),
            (opp_period_sk, opp_period_gl, opp_ast),
        ):
            _populate_period_stats(
                team_sk, team_gl,
                ast.get("2010", {}),
                ast.get("2020", {}),
            )

        # pgr/pgp computed from full roster BEFORE activity filter — includes
        # goalies/skaters who haven't played yet but still have games remaining
        my_sk_pgr  = sum(r.games_remaining for r in my_period_sk)
        opp_sk_pgr = sum(r.games_remaining for r in opp_period_sk)
        my_gl_pgr  = sum(r.games_remaining for r in my_period_gl)
        opp_gl_pgr = sum(r.games_remaining for r in opp_period_gl)
        my_sk_pgp  = sum(r.games_played for r in my_period_sk)
        opp_sk_pgp = sum(r.games_played for r in opp_period_sk)
        my_gl_pgp  = sum(r.games_played for r in my_period_gl)
        opp_gl_pgp = sum(r.games_played for r in opp_period_gl)

        # Players who appeared in Fantrax period stats at all (even with 0 counted stats,
        # e.g. a physical player whose league doesn't score hits/BLK)
        my_sk_active  = set(my_ast.get("2010", {}).keys())
        opp_sk_active = set(opp_ast.get("2010", {}).keys())
        my_gl_active  = set(my_ast.get("2020", {}).keys())
        opp_gl_active = set(opp_ast.get("2020", {}).keys())

        def _sk_played(r: SkaterRow, active_ids: set) -> bool:
            return (r.fantrax_id in active_ids or
                    r.games_played > 0 or
                    r.p_goals + r.p_assists + r.p_blk + r.p_hits + r.p_sog + r.p_ppp + r.p_gwg > 0)

        def _gl_played(r: GoalieRow, active_ids: set) -> bool:
            return r.fantrax_id in active_ids or r.p_saves > 0 or r.p_wins > 0

        # Filter period rows to players who played at least one game this period
        my_period_sk  = [r for r in my_period_sk  if _sk_played(r, my_sk_active)]
        opp_period_sk = [r for r in opp_period_sk if _sk_played(r, opp_sk_active)]
        my_period_gl  = [r for r in my_period_gl  if _gl_played(r, my_gl_active)]
        opp_period_gl = [r for r in opp_period_gl if _gl_played(r, opp_gl_active)]

        # Available players (waiver wire) + roster Ros% — single ownership fetch for all
        available_sk: list[WaiverRow] = []
        available_gl: list[WaiverRow] = []
        try:
            rostered = self._get_rostered_names()
            # Incrementally build period stats for unowned player ranking
            if period_start and period_end:
                self._refresh_period_player_stats(period_start, period_end)

            # Collect ALL names needing Ros%: roster + waiver candidates (one combined fetch)
            all_ownership_names: list[str] = [fp.name for fp in my_roster + opp_roster]
            for sk in skater_by_id.values():
                if _normalize_name(sk.name_default) not in rostered:
                    all_ownership_names.append(sk.name_default)
            for gl in goalie_by_id.values():
                if gl.has_played and _normalize_name(gl.name_default) not in rostered:
                    all_ownership_names.append(gl.name_default)
            for hist in self._period_player_stats.values():
                pname = hist.get("_name", "")
                if pname and _normalize_name(pname) not in rostered:
                    all_ownership_names.append(pname)
            all_ownership_names = list(dict.fromkeys(n for n in all_ownership_names if n))

            try:
                combined_ownership = self._fantrax.get_player_ownership(
                    self._league_id, all_ownership_names)
            except Exception:
                combined_ownership = {}

            # Backfill ros_pct on period rows now that ownership is available
            for row in my_period_sk + opp_period_sk:
                row.ros_pct = combined_ownership.get(_normalize_name(row.name), 0.0)
            for row in my_period_gl + opp_period_gl:
                row.ros_pct = combined_ownership.get(_normalize_name(row.name), 0.0)

            available_sk, available_gl = self._build_available(
                skater_by_id, goalie_by_id, rostered,
                playing_teams,
                team_to_opponent, team_to_state, team_gp, team_total,
                combined_ownership,
            )
        except Exception:
            pass

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
            my_period_skaters=my_period_sk,
            my_period_goalies=my_period_gl,
            opp_period_skaters=opp_period_sk,
            opp_period_goalies=opp_period_gl,
            my_sk_pgr=my_sk_pgr,   opp_sk_pgr=opp_sk_pgr,
            my_gl_pgr=my_gl_pgr,   opp_gl_pgr=opp_gl_pgr,
            my_sk_pgp=my_sk_pgp,   opp_sk_pgp=opp_sk_pgp,
            my_gl_pgp=my_gl_pgp,   opp_gl_pgp=opp_gl_pgp,
            live_game_count=len(live_games),
            period_start=period_start,
            period_end=period_end,
            my_team_name=self._fantrax.get_team_name(self._my_team_id),
            opp_team_name=self._fantrax.get_team_name(opp_team_id),
            available_skaters=available_sk,
            available_goalies=available_gl,
        )
        self._last_snapshot = snapshot
        return snapshot

    def _build_rows(
        self,
        roster: list[FantraxPlayer],
        nhl_skater_map: dict[str, list[NHLSkaterStats]],
        nhl_goalie_map: dict[str, list[NHLGoalieStats]],
        playing_teams: set[str] = None,
        active_teams: set[str] = None,
        team_to_opponent: dict[str, str] = None,
        team_to_state: dict[str, str] = None,
        team_gp: dict[str, int] = None,
        team_total: dict[str, int] = None,
        ownership: dict[str, float] = None,
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
            gp = (team_gp or {}).get(team_up, 0)
            total = (team_total or {}).get(team_up, 0)
            gp_played = max(0, total - gp)
            norm = _normalize_name(fp.name)
            if fp.position.upper() in ("G", "GOALIE"):
                goalie_stats = _match_goalie(norm, fp.team_abbrev, nhl_goalie_map)
                row = GoalieRow(
                    fantrax_id=fp.fantrax_id,
                    name=fp.name,
                    team_abbrev=fp.team_abbrev,
                    nhl_opponent=opp_str,
                    game_state=game_state,
                    games_remaining=gp,
                    games_played=gp_played,
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
                row.ros_pct = (ownership or {}).get(norm, 0.0)
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
                    games_remaining=gp,
                    games_played=gp_played,
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
                else:
                    # Mark scratched if team's boxscore was fetched but player is absent
                    row.scratched = active_teams is not None and team_up in active_teams
                row.ros_pct = (ownership or {}).get(norm, 0.0)
                skaters.append(row)

        skaters.sort(key=_skater_sort_key)
        return skaters, goalies

    def _refresh_period_player_stats(self, period_start, period_end) -> None:
        """Incrementally accumulate NHL stats for all players across past days of the period.
        Fetches up to 8 uncached boxscores per call to limit latency."""
        cache_key = (period_start, period_end)
        if cache_key != self._period_cache_key:
            # New scoring period — reset
            self._period_player_stats.clear()
            self._period_stats_game_ids.clear()
            self._period_cache_key = cache_key

        try:
            all_ids = self._nhl.get_completed_game_ids_in_period(period_start, period_end)
        except Exception:
            return

        fetched = 0
        for gid in all_ids:
            if gid in self._period_stats_game_ids:
                continue
            if fetched >= 8:
                break  # resume next refresh
            try:
                if gid in self._completed_boxscores:
                    boxscore = self._completed_boxscores[gid]
                else:
                    boxscore = self._nhl.get_boxscore(gid)
                    self._completed_boxscores[gid] = boxscore
                for sk in boxscore.skaters:
                    acc = self._period_player_stats.setdefault(sk.player_id, {
                        "goals": 0, "assists": 0, "blk": 0,
                        "hits": 0, "sog": 0, "ppp": 0, "games": 0,
                    })
                    acc["goals"]   += sk.goals
                    acc["assists"] += sk.assists
                    acc["blk"]     += sk.blk
                    acc["hits"]    += sk.hits
                    acc["sog"]     += sk.sog
                    acc["ppp"]     += sk.ppp
                    acc["games"]   += 1
                    # Store identity so FUT players can be shown pre-game
                    acc["_name"] = sk.name_default
                    acc["_team"] = sk.team_abbrev.upper()
                    acc["_pos"]  = sk.position
                for gl in boxscore.goalies:
                    if not gl.has_played:
                        continue
                    acc = self._period_player_stats.setdefault(gl.player_id, {
                        "wins": 0, "saves": 0, "goals_against": 0,
                        "shots_against": 0, "games": 0,
                    })
                    acc["wins"]          += gl.wins
                    acc["saves"]         += gl.saves
                    acc["goals_against"] += gl.goals_against
                    acc["shots_against"] += gl.shots_against
                    acc["games"]         += 1
                    acc["_name"]  = gl.name_default
                    acc["_team"]  = gl.team_abbrev.upper()
                    acc["_pos"]   = "G"
                    acc["_goalie"] = True
                self._period_stats_game_ids.add(gid)
                fetched += 1
            except Exception:
                continue

    def _get_rostered_names(self) -> set[str]:
        """Return normalized names of all rostered players, cached for 2 minutes."""
        now = _time.monotonic()
        if now - self._rostered_names_ts > 120:
            raw = self._fantrax.get_all_rostered_names(self._league_id)
            self._rostered_names_cache = {_normalize_name(n) for n in raw}
            self._rostered_names_ts = now
        return self._rostered_names_cache

    def _build_available(
        self,
        skater_by_id: dict,
        goalie_by_id: dict,
        rostered_names: set[str],
        playing_teams: set[str],
        team_to_opponent: dict,
        team_to_state: dict,
        team_gp: dict,
        team_total: dict,
        ownership: dict[str, float] = None,
    ) -> tuple[list[WaiverRow], list[WaiverRow]]:
        skaters: list[WaiverRow] = []
        goalies: list[WaiverRow] = []
        ownership = ownership or {}

        seen_ids: set[int] = set()

        # ── Players with LIVE/OFF game today (have boxscore stats) ──────────
        for sk in skater_by_id.values():
            if _normalize_name(sk.name_default) in rostered_names:
                continue
            seen_ids.add(sk.player_id)
            team_up = sk.team_abbrev.upper()
            rem = (team_gp or {}).get(team_up, 0)

            hist = self._period_player_stats.get(sk.player_id, {})
            p_goals   = hist.get("goals",   0) + sk.goals
            p_assists = hist.get("assists",  0) + sk.assists
            p_blk     = hist.get("blk",      0) + sk.blk
            p_hits    = hist.get("hits",     0) + sk.hits
            p_sog     = hist.get("sog",      0) + sk.sog
            p_ppp     = hist.get("ppp",      0) + sk.ppp
            games_played = hist.get("games", 0) + 1

            period_wperf = _compute_skater_wperf({
                "goals": p_goals, "assists": p_assists, "blk": p_blk,
                "hits": p_hits, "sog": p_sog, "ppp": p_ppp,
            })
            rate = period_wperf / max(1, games_played)
            projected = period_wperf + rate * rem

            skaters.append(WaiverRow(
                name=sk.name_default, team_abbrev=sk.team_abbrev,
                position=sk.position,
                nhl_opponent=(team_to_opponent or {}).get(team_up, ""),
                game_state=(team_to_state or {}).get(team_up, ""),
                games_remaining=rem,
                projected=projected,
                ros_pct=ownership.get(_normalize_name(sk.name_default), 0.0),
                p_goals=p_goals, p_assists=p_assists, p_blk=p_blk,
                p_hits=p_hits, p_sog=p_sog, p_ppp=p_ppp,
            ))

        for gl in goalie_by_id.values():
            if not gl.has_played:
                continue
            if _normalize_name(gl.name_default) in rostered_names:
                continue
            seen_ids.add(gl.player_id)
            team_up = gl.team_abbrev.upper()
            rem = (team_gp or {}).get(team_up, 0)

            hist = self._period_player_stats.get(gl.player_id, {})
            p_wins   = hist.get("wins",          0) + gl.wins
            p_saves  = hist.get("saves",         0) + gl.saves
            p_ga     = hist.get("goals_against", 0) + gl.goals_against
            p_sa     = hist.get("shots_against", 0) + gl.shots_against
            p_svp    = p_saves / p_sa if p_sa > 0 else 0.0
            games_played = hist.get("games", 0) + 1

            period_wperf = _compute_goalie_wperf({
                "wins": p_wins, "saves": p_saves, "save_pct": p_svp,
            })
            rate = period_wperf / max(1, games_played)
            projected = period_wperf + rate * rem

            goalies.append(WaiverRow(
                name=gl.name_default, team_abbrev=gl.team_abbrev,
                position="G",
                nhl_opponent=(team_to_opponent or {}).get(team_up, ""),
                game_state=(team_to_state or {}).get(team_up, ""),
                games_remaining=rem,
                projected=projected,
                ros_pct=ownership.get(_normalize_name(gl.name_default), 0.0),
                p_wins=p_wins, p_saves=p_saves,
                p_save_pct=p_svp, p_goals_against=p_ga,
            ))

        # ── Players with FUT game today (period stats only, game not started) ─
        # Uses identity stored in _period_player_stats from earlier boxscores.
        pt = playing_teams or set()
        for pid, hist in self._period_player_stats.items():
            if pid in seen_ids:
                continue
            team_up = hist.get("_team", "")
            if not team_up or team_up not in pt:
                continue
            pname = hist.get("_name", "")
            if not pname or _normalize_name(pname) in rostered_names:
                continue
            rem = (team_gp or {}).get(team_up, 0)
            games_played = hist.get("games", 0)

            if hist.get("_goalie"):
                p_wins  = hist.get("wins",          0)
                p_saves = hist.get("saves",         0)
                p_ga    = hist.get("goals_against", 0)
                p_sa    = hist.get("shots_against", 0)
                p_svp   = p_saves / p_sa if p_sa > 0 else 0.0
                period_wperf = _compute_goalie_wperf({
                    "wins": p_wins, "saves": p_saves, "save_pct": p_svp,
                })
                rate = period_wperf / max(1, games_played)
                goalies.append(WaiverRow(
                    name=pname, team_abbrev=hist.get("_team", ""),
                    position="G",
                    nhl_opponent=(team_to_opponent or {}).get(team_up, ""),
                    game_state=(team_to_state or {}).get(team_up, "FUT"),
                    games_remaining=rem,
                    projected=period_wperf + rate * rem,
                    ros_pct=ownership.get(_normalize_name(pname), 0.0),
                    p_wins=p_wins, p_saves=p_saves,
                    p_save_pct=p_svp, p_goals_against=p_ga,
                ))
            else:
                p_goals   = hist.get("goals",   0)
                p_assists = hist.get("assists",  0)
                p_blk     = hist.get("blk",      0)
                p_hits    = hist.get("hits",     0)
                p_sog     = hist.get("sog",      0)
                p_ppp     = hist.get("ppp",      0)
                period_wperf = _compute_skater_wperf({
                    "goals": p_goals, "assists": p_assists, "blk": p_blk,
                    "hits": p_hits, "sog": p_sog, "ppp": p_ppp,
                })
                rate = period_wperf / max(1, games_played)
                skaters.append(WaiverRow(
                    name=pname, team_abbrev=hist.get("_team", ""),
                    position=hist.get("_pos", ""),
                    nhl_opponent=(team_to_opponent or {}).get(team_up, ""),
                    game_state=(team_to_state or {}).get(team_up, "FUT"),
                    games_remaining=rem,
                    projected=period_wperf + rate * rem,
                    ros_pct=ownership.get(_normalize_name(pname), 0.0),
                    p_goals=p_goals, p_assists=p_assists, p_blk=p_blk,
                    p_hits=p_hits, p_sog=p_sog, p_ppp=p_ppp,
                ))

        skaters.sort(key=lambda r: r.projected, reverse=True)
        goalies.sort(key=lambda r: r.projected, reverse=True)
        return skaters[:20], goalies[:10]

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
            for stat in ("goals", "assists", "points", "blk", "hits", "sog", "ppg", "ppp", "gwg", "scratched"):
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
