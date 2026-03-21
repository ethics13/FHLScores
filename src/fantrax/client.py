from __future__ import annotations

import os
import pickle
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import sys

import requests

FANTRAX_BASE = "https://www.fantrax.com"
API_URL = f"{FANTRAX_BASE}/fxpa/req"

if getattr(sys, "frozen", False):
    COOKIE_FILE = Path(sys.executable).parent / "fantrax_cookies.pkl"
else:
    COOKIE_FILE = Path(__file__).parent.parent.parent / "fantrax_cookies.pkl"

# Fantrax shortName → our internal field name (for stat parsing).
# All keys are uppercase — lookup normalises shortName with .upper().
_SCIP_SHORT_TO_FIELD: dict[str, str] = {
    "G":    "goals",
    "A":    "assists",
    "PTS":  "points",
    "BLK":    "blk",
    "BLOCK":  "blk",
    "BLOCKS": "blk",
    "HITS": "hits",
    "HIT":  "hits",
    "H":    "hits",
    "SOG":  "sog",
    "PPG":  "ppg",
    "PPP":  "ppp",
    "GWG":  "gwg",
    "W":    "wins",
    "OTL":  "ot_losses",
    "OL":   "ot_losses",
    "GAA":  "gaa",
    "SV%":  "save_pct",
    "SO":   "shutout",
    "SOGA": "shots_against",
    "SV":   "saves",
}

# Icon typeIds from Fantrax
_ICON_MINORS = "4"
_ICON_IR = "2"
_ICON_OUT = "30"
_ICON_DTD = "1"
_ICON_SUSP = "6"

# Slot short names that should be excluded (IR/IL/NA slots in Fantrax)
EXCLUDED_SLOTS = {"IR", "IR+", "IL", "IL+", "NA", "MIN"}

# NHL injury statuses to exclude
EXCLUDED_STATUSES = {"IR", "IL", "MINORS", "NA", "MINOR", "IR-LTI", "IR+", "O"}


@dataclass
class FantraxPlayer:
    fantrax_id: str
    name: str
    position: str       # player's actual position (e.g. "RW")
    team_abbrev: str
    status: str         # injury status (e.g. "IR", "DTD", "")
    roster_slot: str    # slot on fantasy roster (e.g. "C", "BN", "IR")


class FantraxAuthError(Exception):
    pass


class FantraxClient:
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        })
        self._logged_in = False
        self._positions: dict[str, str] = {}   # posId → shortName
        self._team_names: dict[str, str] = {}  # team_id → display name
        self._day_stats_cache: dict[str, dict] = {}  # date_str → allTeamsStats dict
        self._scip_to_field: dict[str, str] = {}    # built once from API response
        self._ownership_cache: dict[str, float] = {}  # normalized_name → ros_pct
        self._ownership_ts: float = 0.0
        self._ownership_thread_running: bool = False

    def reset_league_cache(self) -> None:
        """Clear all per-league cached data when switching leagues."""
        self._day_stats_cache.clear()
        self._scip_to_field.clear()
        self._positions.clear()
        self._team_names.clear()
        self._ownership_cache.clear()
        self._ownership_ts = 0.0

    def login(self) -> None:
        """Authenticate via Selenium (headless Chrome) and cache cookies."""
        # Try cached cookies first
        if COOKIE_FILE.exists():
            try:
                self._load_cookies(COOKIE_FILE)
                if self._check_auth():
                    self._logged_in = True
                    return
            except Exception:
                pass

        # Need fresh login via Selenium
        self._selenium_login()
        self._logged_in = True

    def _selenium_login(self) -> None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from webdriver_manager.chrome import ChromeDriverManager

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        with webdriver.Chrome(service=service, options=options) as driver:
            driver.get(f"{FANTRAX_BASE}/login")

            wait = WebDriverWait(driver, 20)
            email_field = wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[@formcontrolname='email']"))
            )
            email_field.clear()
            email_field.send_keys(self._username)

            password_field = wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[@formcontrolname='password']"))
            )
            password_field.clear()
            password_field.send_keys(self._password)
            password_field.submit()

            # Wait for redirect away from /login
            try:
                WebDriverWait(driver, 20).until(EC.url_changes(f"{FANTRAX_BASE}/login"))
            except Exception:
                pass
            time.sleep(3)  # let Angular finish setting cookies

            cookies = driver.get_cookies()
            if not cookies:
                raise FantraxAuthError("Selenium login returned no cookies — check credentials")

            with open(COOKIE_FILE, "wb") as f:
                pickle.dump(cookies, f)

            # Inject into requests session
            self._session.cookies.clear()
            for c in cookies:
                self._session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    def _load_cookies(self, path: Path) -> None:
        with open(path, "rb") as f:
            cookies = pickle.load(f)
        self._session.cookies.clear()
        for c in cookies:
            self._session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    def _check_auth(self) -> bool:
        """Make a lightweight API call to test if cookies are valid."""
        try:
            resp = self._session.post(
                API_URL,
                params={"leagueId": ""},
                json={"msgs": [{"method": "getFantasyLeagueInfo", "data": {"leagueId": ""}}]},
                timeout=10,
            )
            data = resp.json()
            page_err = data.get("pageError", {}).get("code", "")
            return page_err != "WARNING_NOT_LOGGED_IN"
        except Exception:
            return False

    def _api(self, league_id: str, methods: list[dict], retry: bool = True) -> list[dict]:
        """
        POST to /fxpa/req with the msgs array format.
        Returns list of response data dicts (one per method).
        """
        if not self._logged_in:
            self.login()

        msgs = []
        for m in methods:
            data = {"leagueId": league_id}
            data.update(m.get("data", {}))
            msgs.append({"method": m["method"], "data": data})

        resp = self._session.post(
            API_URL,
            params={"leagueId": league_id},
            json={"msgs": msgs},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()

        page_err = body.get("pageError", {}).get("code", "")
        if page_err == "WARNING_NOT_LOGGED_IN":
            if retry:
                self._logged_in = False
                # Force fresh Selenium login (ignore cached cookies)
                if COOKIE_FILE.exists():
                    COOKIE_FILE.unlink()
                self.login()
                return self._api(league_id, methods, retry=False)
            raise FantraxAuthError("Authentication failed after re-login attempt")

        responses = body.get("responses", [])
        return [r.get("data", {}) for r in responses]

    def _api1(self, league_id: str, method: str, data: dict = None) -> dict:
        """Convenience wrapper for a single-method call."""
        results = self._api(league_id, [{"method": method, "data": data or {}}])
        return results[0] if results else {}

    def initialize_league(self, league_id: str) -> None:
        """Fetch league info to populate positions and team names. Called once after login."""
        data = self._api1(league_id, "getFantasyLeagueInfo")
        self._positions = {
            k: v.get("shortName", k)
            for k, v in data.get("positionMap", {}).items()
        }

        # getFantasyLeagueInfo has no team list — use getTeamRosterInfo instead
        roster_data = self._api1(league_id, "getTeamRosterInfo", {"view": "STATS"})
        teams = roster_data.get("fantasyTeams", [])
        if isinstance(teams, dict):
            teams = list(teams.values())

        self._team_names = {}
        for t in teams:
            tid = (t.get("id") or t.get("teamId") or
                   t.get("fantasyTeamId") or t.get("teamid", ""))
            if tid:
                name = (t.get("shortName") or t.get("name") or
                        t.get("teamName") or str(tid))
                self._team_names[str(tid)] = name

    def get_team_name(self, team_id: str) -> str:
        return self._team_names.get(str(team_id), "")

    def get_my_team_id(self, league_id: str) -> str:
        """
        Call getTeamRosterInfo without a teamId — Fantrax returns the
        logged-in user's team. Parse teamId from displayedSelections.
        """
        data = self._api1(league_id, "getTeamRosterInfo", {"view": "STATS"})
        sel = data.get("displayedSelections", {})

        # Primary: displayedFantasyTeamId
        team_id = sel.get("displayedFantasyTeamId", "") or sel.get("teamId", "")
        if team_id:
            return team_id

        # Fallback: look for myTeam flag in fantasyTeams list
        teams = data.get("fantasyTeams", [])
        if isinstance(teams, dict):
            teams = list(teams.values())
        for t in teams:
            if t.get("myTeam", False):
                return t.get("id", "")

        team_ids = [t.get("id", "") for t in teams] if isinstance(teams, list) else []
        raise ValueError(
            "Could not auto-detect your team ID from Fantrax. "
            "Please set my_team_id manually in config.ini. "
            f"Available team IDs: {team_ids}"
        )

    def get_matchup_info(self, my_team_id: str, league_id: str):
        """
        Returns (opp_team_id, period_start, period_end, active_stats).

        active_stats: {team_id: {"2010": {scorer_id: {field: value}},
                                  "2020": {scorer_id: {field: value}}}}
          "2010" = skaters, "2020" = goalies.

        Stats are accumulated day-by-day across the scoring period because
        getLiveScoringStats only returns players with games on that specific date.
        Past days are cached; only today is always re-fetched.
        """
        import re as _re
        from datetime import date as date_cls, datetime as _dt, timedelta

        today = date_cls.today()
        today_str = today.isoformat()

        # Fetch today's data — gives us opponent, period dates, scip_to_field
        today_data = self._api1(
            league_id, "getLiveScoringStats",
            {"newView": True, "date": today_str, "playerViewType": "1", "sppId": "-1", "viewType": "1"},
        )

        # Opponent
        opp_team_id = ""
        for matchup_str in today_data.get("matchups", []):
            parts = matchup_str.split("_")
            if len(parts) == 2:
                away_id, home_id = parts
                if away_id == my_team_id:
                    opp_team_id = home_id
                    break
                if home_id == my_team_id:
                    opp_team_id = away_id
                    break
        if not opp_team_id:
            raise ValueError(f"Could not find opponent for team {my_team_id} in league {league_id}")

        # Period dates from displayPeriod field
        period_start = period_end = None
        display = today_data.get("displayPeriod", "").strip()
        m = _re.match(r'\((\w+ \d+, \d+)\s*-\s*(\w+ \d+, \d+)\)', display)
        if m:
            try:
                period_start = _dt.strptime(m.group(1), "%b %d, %Y").date()
                period_end   = _dt.strptime(m.group(2), "%b %d, %Y").date()
            except ValueError:
                pass
        if not period_start:
            period_start = today - timedelta(days=6)
        if not period_end:
            period_end = today

        # Build scipId → field name map (cached after first call)
        if not self._scip_to_field:
            for categories in today_data.get("scoringCategoriesPerGroup", {}).values():
                for cat in categories:
                    fld = _SCIP_SHORT_TO_FIELD.get(cat.get("shortName", "").upper())
                    if fld:
                        self._scip_to_field[cat["id"]] = fld
        scip_to_field = self._scip_to_field

        # Accumulate per-scorer stats across every day in the period.
        # GAA is a rate — we track a weighted sum (_wgaa) and divide by shots_against at the end.
        _RATE_FIELDS = {"gaa", "save_pct"}
        accumulated: dict[str, dict[str, dict]] = {
            my_team_id: {},
            opp_team_id: {},
        }

        d = period_start
        while d <= min(period_end, today):
            d_str = d.isoformat()

            # Use cached data for past days; always re-fetch today
            if d < today and d_str in self._day_stats_cache:
                day_data = self._day_stats_cache[d_str]
            elif d_str == today_str:
                day_data = today_data
            else:
                try:
                    day_data = self._api1(
                        league_id, "getLiveScoringStats",
                        {"newView": True, "date": d_str, "playerViewType": "1", "sppId": "-1", "viewType": "1"},
                    )
                    self._day_stats_cache[d_str] = day_data
                except Exception:
                    d += timedelta(days=1)
                    continue

            all_teams = day_data.get("statsPerTeam", {}).get("allTeamsStats", {})
            for team_id in (my_team_id, opp_team_id):
                # Merge stats from ALL roster slots (ACTIVE, BN, etc.) so bench
                # players and today's scratches still accumulate period totals.
                team_stats_map: dict = {}
                for slot_data in all_teams.get(team_id, {}).values():
                    if isinstance(slot_data, dict):
                        team_stats_map.update(slot_data.get("statsMap", {}))
                for scorer_id, raw in team_stats_map.items():
                    if scorer_id.startswith("_"):
                        continue  # skip aggregate rows (_2010, _2020)
                    day_stats: dict[str, float] = {}
                    for stat in raw.get("object2", []):
                        fld = scip_to_field.get(stat.get("scipId", ""))
                        if fld:
                            day_stats[fld] = float(stat.get("av", 0))
                    if not day_stats:
                        continue
                    acc = accumulated[team_id].setdefault(scorer_id, {})
                    # Infer shots_against and goals_against from saves ÷ save_pct per day.
                    # These are rarely direct scoring stats but can be computed this way.
                    day_sv  = day_stats.get("saves", 0.0)
                    day_pct = day_stats.get("save_pct", 0.0)
                    if day_pct > 0:
                        day_sa_inf = day_sv / day_pct
                        acc["_inf_sa"] = acc.get("_inf_sa", 0.0) + day_sa_inf
                        acc["_inf_ga"] = acc.get("_inf_ga", 0.0) + max(0.0, day_sa_inf - day_sv)
                    elif day_sv > 0:
                        # Shutout: save_pct=1.0 sometimes stored as 0 — assume no GA
                        acc["_inf_sa"] = acc.get("_inf_sa", 0.0) + day_sv
                    # Sum all counting stats
                    for fld, val in day_stats.items():
                        if fld not in _RATE_FIELDS:
                            acc[fld] = acc.get(fld, 0.0) + val

            d += timedelta(days=1)

        # Finalize: compute gaa (goals against count) and save_pct, split skater/goalie
        _GOALIE_MARKERS = {"wins", "saves", "shots_against", "gaa"}
        active_stats: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
        for team_id, scorers in accumulated.items():
            active_stats[team_id] = {"2010": {}, "2020": {}}
            for scorer_id, stats in scorers.items():
                inf_sa = stats.pop("_inf_sa", 0.0)
                inf_ga = stats.pop("_inf_ga", 0.0)
                sa     = stats.get("shots_against", 0.0)
                sv     = stats.get("saves", 0.0)
                if sa > 0:
                    stats["gaa"]      = sa - sv          # exact goals against count
                    stats["save_pct"] = sv / sa
                elif inf_sa > 0:
                    stats["gaa"]      = round(inf_ga)    # inferred goals against count
                    stats["save_pct"] = sv / inf_sa
                group = "2020" if _GOALIE_MARKERS & set(stats.keys()) else "2010"
                active_stats[team_id][group][scorer_id] = stats

        return opp_team_id, period_start, period_end, active_stats

    def get_all_rostered_names(self, league_id: str) -> set[str]:
        """Return raw names of all players on any fantasy roster in the league."""
        team_ids = list(self._team_names.keys())
        if not team_ids:
            return set()
        methods = [
            {"method": "getTeamRosterInfo", "data": {"teamId": tid, "view": "STATS"}}
            for tid in team_ids
        ]
        try:
            results = self._api(league_id, methods)
        except Exception:
            return set()
        names: set[str] = set()
        for data in results:
            for table in data.get("tables", []):
                for row in table.get("rows", []):
                    scorer = row.get("scorer")
                    if scorer:
                        name = scorer.get("name", "")
                        if name:
                            names.add(name)
        return names


    def get_player_ownership(self, league_id: str, names: list[str]) -> dict[str, float]:
        """Return {normalized_name: ros_pct} for the given player names.

        Searches getPlayerStats by last name for each player.  Results are
        cached for 10 minutes.  Launches a background thread so the first
        call returns immediately (shows '--'); subsequent polls get real data.
        """
        import threading
        import unicodedata

        def _norm(n: str) -> str:
            n = unicodedata.normalize("NFD", n)
            n = "".join(c for c in n if unicodedata.category(c) != "Mn")
            parts = n.lower().split()
            if not parts:
                return ""
            first = parts[0].rstrip(".")
            last = " ".join(parts[1:]) if len(parts) > 1 else first
            return f"{first[0]}.{last.replace(' ', '')}" if first else last

        now = time.monotonic()
        # Return cache if fresh AND all requested names are already cached
        missing = [n for n in names if _norm(n) not in self._ownership_cache]
        if not missing and now - self._ownership_ts < 600:
            return self._ownership_cache

        if self._ownership_thread_running:
            return self._ownership_cache

        names_to_fetch = list(names)

        def _run() -> None:
            self._ownership_thread_running = True
            try:
                result: dict[str, float] = dict(self._ownership_cache)
                for raw_name in names_to_fetch:
                    norm = _norm(raw_name)
                    if norm in result:
                        continue
                    # Use last name as search token (most discriminating)
                    parts = raw_name.strip().split()
                    search_token = parts[-1] if parts else raw_name
                    ros = self._search_player_ros(league_id, raw_name, search_token)
                    result[norm] = ros  # store 0 too so we don't retry 0%-owned players
                self._ownership_cache = result
                self._ownership_ts = time.monotonic()
            finally:
                self._ownership_thread_running = False

        self._ownership_thread_running = True
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return self._ownership_cache

    def _search_player_ros(self, league_id: str, full_name: str, search_token: str) -> float:
        """Return Ros% for a player by searching getPlayerStats with their last name.

        NHL names are abbreviated ('S. Steel'); Fantrax names are full ('Sam Steel').
        Compare via normalized 'first-initial.lastname' form to handle both.
        """
        import unicodedata as _ud

        def _n(s: str) -> str:
            s = _ud.normalize("NFD", s)
            s = "".join(c for c in s if _ud.category(c) != "Mn")
            parts = s.lower().split()
            if not parts:
                return ""
            first = parts[0].rstrip(".")
            last = " ".join(parts[1:]) if len(parts) > 1 else first
            return f"{first[0]}.{last.replace(' ', '')}" if first else last

        target = _n(full_name)
        try:
            # statusOrTeamFilter "ALL" returns both available and rostered players.
            data = self._api1(league_id, "getPlayerStats",
                              {"searchName": search_token, "statusOrTeamFilter": "ALL"})
            for row in (data.get("statsTable") or []):
                scorer = row.get("scorer") or {}
                if _n(scorer.get("name", "")) != target:
                    continue
                for cell in row.get("cells", []):
                    content = str(cell.get("content", ""))
                    if content.endswith("%") and "gainColor" not in cell:
                        try:
                            return float(content.rstrip("%"))
                        except ValueError:
                            pass
        except Exception:
            pass
        return 0.0

    def get_opponent_team_id(self, my_team_id: str, league_id: str) -> str:
        opp, _, _, _ = self.get_matchup_info(my_team_id, league_id)
        return opp

    def get_roster(self, team_id: str, league_id: str) -> list[FantraxPlayer]:
        """Fetch roster for team_id, filtering out IR/injured players."""
        results = self._api(
            league_id,
            [
                {"method": "getTeamRosterInfo", "data": {"teamId": team_id, "view": "STATS"}},
                {"method": "getTeamRosterInfo", "data": {"teamId": team_id, "view": "SCHEDULE_FULL"}},
            ],
        )
        stats_data = results[0] if results else {}

        players: list[FantraxPlayer] = []
        for table in stats_data.get("tables", []):
            for row in table.get("rows", []):
                if "posId" not in row:
                    continue
                scorer = row.get("scorer")
                if not scorer:
                    continue

                pos_id = row.get("posId", "")
                slot_name = self._positions.get(pos_id, pos_id)

                # Skip IR/IL/NA roster slots
                if slot_name.upper() in EXCLUDED_SLOTS:
                    continue

                status = _extract_status(scorer, row)

                # Skip excluded statuses
                if _is_excluded(status):
                    continue

                player = FantraxPlayer(
                    fantrax_id=str(scorer.get("scorerId", "")),
                    name=scorer.get("name", ""),
                    position=_strip_html(scorer.get("posShortNames", "")),
                    team_abbrev=scorer.get("teamShortName", ""),
                    status=status,
                    roster_slot=slot_name,
                )
                players.append(player)

        return players


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_status(scorer: dict, row: dict) -> str:
    """Map Fantrax icon typeIds to a status string."""
    # statusId '9' = in minors (belt-and-suspenders alongside icon check)
    if str(row.get("statusId", "")) == "9":
        return "MINORS"
    icons = scorer.get("icons", [])
    for icon in icons:
        type_id = str(icon.get("typeId", ""))
        if type_id == _ICON_MINORS:
            return "MINORS"
        if type_id == _ICON_IR:
            return "IR"
        if type_id == _ICON_OUT:
            return "O"
    return ""


def _is_excluded(status: str) -> bool:
    if not status:
        return False
    return status.upper() in EXCLUDED_STATUSES
