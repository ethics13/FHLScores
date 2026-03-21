"""
Diagnostic: dump the full cell structure from getTeamRosterInfo(view=STATS)
to find where Ros% lives for rostered players.

Outputs:
  debug_roster_cells.json  — full row data for first 3 players on my team
"""
import json
import pickle
import requests
from pathlib import Path

COOKIE_FILE = Path("fantrax_cookies.pkl")
LEAGUE_ID   = "j3yl79c7man4av42"
MY_TEAM_ID  = "hkfcxketman4av4g"
API_URL     = "https://www.fantrax.com/fxpa/req"


def load_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )})
    with open(COOKIE_FILE, "rb") as f:
        cookies = pickle.load(f)
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
    return s


def api1(session, league_id, method, data=None):
    body = {"msgs": [{"method": method, "data": {"leagueId": league_id, **(data or {})}}]}
    resp = session.post(API_URL, params={"leagueId": league_id}, json=body, timeout=20)
    resp.raise_for_status()
    responses = resp.json().get("responses", [])
    return responses[0].get("data", {}) if responses else {}


def main():
    session = load_session()

    print("=== getTeamRosterInfo(view=STATS) for my team ===")
    data = api1(session, LEAGUE_ID, "getTeamRosterInfo",
                {"teamId": MY_TEAM_ID, "view": "STATS"})

    output = []
    for table in data.get("tables", []):
        for row in table.get("rows", []):
            scorer = row.get("scorer")
            if not scorer:
                continue
            name = scorer.get("name", "?")
            cells = row.get("cells", [])
            entry = {
                "name": name,
                "row_keys": list(row.keys()),
                "scorer_keys": list(scorer.keys()),
                "cells": cells,
            }
            output.append(entry)
            print(f"\nPlayer: {name}")
            print(f"  row keys: {list(row.keys())}")
            for i, cell in enumerate(cells):
                print(f"  cell[{i}]: {cell}")
            if len(output) >= 5:
                break
        if len(output) >= 5:
            break

    Path("debug_roster_cells.json").write_text(
        json.dumps(output, indent=2, default=str), encoding="utf-8")
    print("\nSaved to debug_roster_cells.json")

    # Also try with no teamId (logged-in user's team)
    print("\n=== Also trying getPlayerStats with scorerId of first player ===")
    if output:
        # Get scorerId from scorer data
        first_scorer = None
        for table in data.get("tables", []):
            for row in table.get("rows", []):
                s = row.get("scorer")
                if s and s.get("name"):
                    first_scorer = s
                    break
            if first_scorer:
                break
        if first_scorer:
            scorer_id = first_scorer.get("scorerId", "")
            name = first_scorer.get("name", "")
            print(f"Trying getPlayerStats for {name} (scorerId={scorer_id})")
            for params in [
                {"scorerId": scorer_id},
                {"scorerIds": [scorer_id]},
                {"searchName": name.split()[-1]},
                {"searchName": name.split()[-1], "statusOrTeamFilter": "ALL_TAKEN"},
                {"searchName": name.split()[-1], "statusOrTeamFilter": "ALL"},
            ]:
                try:
                    d = api1(session, LEAGUE_ID, "getPlayerStats", params)
                    rows = d.get("statsTable") or []
                    print(f"  params={params} → {len(rows)} rows")
                    if rows:
                        print(f"    first: {rows[0].get('scorer', {}).get('name', '?')}")
                        for i, cell in enumerate(rows[0].get("cells", [])):
                            if "%" in str(cell.get("content", "")):
                                print(f"    cell[{i}] with %: {cell}")
                except Exception as e:
                    print(f"  params={params} → error: {e}")

            # Also try without leagueId
            print(f"\nTrying getPlayerStats with empty leagueId for {name.split()[-1]}")
            try:
                body = {"msgs": [{"method": "getPlayerStats",
                                  "data": {"searchName": name.split()[-1]}}]}
                resp = session.post(API_URL, params={}, json=body, timeout=20)
                resp.raise_for_status()
                responses = resp.json().get("responses", [])
                d = responses[0].get("data", {}) if responses else {}
                rows = d.get("statsTable") or []
                print(f"  empty leagueId → {len(rows)} rows")
                if rows:
                    for r in rows:
                        print(f"    {r.get('scorer', {}).get('name', '?')}")
            except Exception as e:
                print(f"  empty leagueId → error: {e}")


if __name__ == "__main__":
    main()
