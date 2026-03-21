"""
Diagnostic: capture the exact getPlayerStats request body the Fantrax
Angular app sends during page load, then also call it directly with
various params to find how to get ownership % for all players.

Outputs:
  fantrax_gps_angular_call.json  — exact body Angular sends
  fantrax_gps_raw_response.json  — raw getPlayerStats response
  fantrax_gps_response_keys.json — top-level keys and sample data
"""
import json
import pickle
import time
import requests
from pathlib import Path

COOKIE_FILE = Path("fantrax_cookies.pkl")
LEAGUE_ID   = "j3yl79c7man4av42"
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


def api1(session: requests.Session, method: str, data: dict) -> dict:
    body = {"msgs": [{"method": method, "data": {"leagueId": LEAGUE_ID, **data}}]}
    resp = session.post(API_URL, params={"leagueId": LEAGUE_ID}, json=body, timeout=20)
    resp.raise_for_status()
    responses = resp.json().get("responses", [])
    return responses[0].get("data", {}) if responses else {}


def capture_angular_call():
    """Use Selenium to intercept the exact getPlayerStats call Angular makes."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    with webdriver.Chrome(service=service, options=options) as driver:
        driver.get("https://www.fantrax.com/")
        time.sleep(1)
        driver.delete_all_cookies()
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
        for c in cookies:
            try:
                driver.add_cookie({
                    "name": c["name"], "value": c["value"],
                    "domain": ".fantrax.com", "path": "/", "secure": True,
                })
            except Exception:
                pass

        url = f"https://www.fantrax.com/fantasy/league/{LEAGUE_ID}/players"
        driver.get(url)
        print("Navigated to players page, waiting 25s for Angular...")
        time.sleep(25)

        # Grab all performance logs
        angular_calls = []
        for log in driver.get_log("performance"):
            try:
                msg = json.loads(log["message"])["message"]
                if msg.get("method") != "Network.requestWillBeSent":
                    continue
                req = msg.get("params", {}).get("request", {})
                url_str = req.get("url", "")
                if "/fxpa/req" not in url_str:
                    continue
                post = req.get("postData", "")
                if not post:
                    continue
                try:
                    body = json.loads(post)
                except Exception:
                    continue
                for m in body.get("msgs", []):
                    if m.get("method") == "getPlayerStats":
                        angular_calls.append({
                            "url": url_str,
                            "full_body": body,
                            "getPlayerStats_data": m.get("data", {}),
                        })
            except Exception:
                pass

        return angular_calls


def main():
    print("=== Step 1: Capture Angular getPlayerStats call ===")
    angular_calls = capture_angular_call()
    print(f"Found {len(angular_calls)} getPlayerStats call(s) from Angular")

    if angular_calls:
        Path("fantrax_gps_angular_call.json").write_text(
            json.dumps(angular_calls, indent=2), encoding="utf-8"
        )
        print("Saved to fantrax_gps_angular_call.json")
        gps_params = angular_calls[0]["getPlayerStats_data"]
        print(f"Angular params: {json.dumps(gps_params, indent=2)}")
    else:
        print("No Angular call captured — using empty params")
        gps_params = {}

    print("\n=== Step 2: Call getPlayerStats directly ===")
    session = load_session()

    # Call with exact Angular params
    print(f"\nCalling with Angular params: {gps_params}")
    data = api1(session, "getPlayerStats", gps_params)

    Path("fantrax_gps_raw_response.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    print("Saved full response to fantrax_gps_raw_response.json")

    # Show top-level structure
    print(f"\nTop-level keys: {list(data.keys())}")
    stats_table = data.get("statsTable") or []
    print(f"statsTable length: {len(stats_table)}")

    # Check first row for all fields
    if stats_table:
        row0 = stats_table[0]
        scorer = row0.get("scorer", {})
        print(f"\nFirst player: {scorer.get('name', '?')}")
        print(f"Scorer keys: {list(scorer.keys())}")
        print(f"Row keys: {list(row0.keys())}")
        # Show all cell content to find Ros%
        for i, cell in enumerate(row0.get("cells", [])):
            print(f"  cell[{i}]: {cell}")

    # Look for ownership data outside statsTable
    keys_summary = {}
    for k, v in data.items():
        if k != "statsTable":
            if isinstance(v, dict):
                keys_summary[k] = f"dict with {len(v)} keys: {list(v.keys())[:5]}"
            elif isinstance(v, list):
                keys_summary[k] = f"list[{len(v)}]"
            else:
                keys_summary[k] = str(v)[:100]
    print(f"\nOther fields in response: {json.dumps(keys_summary, indent=2)}")

    Path("fantrax_gps_response_keys.json").write_text(
        json.dumps({
            "top_level_keys": list(data.keys()),
            "stats_table_count": len(stats_table),
            "other_fields": keys_summary,
            "first_row_sample": stats_table[0] if stats_table else {},
        }, indent=2, default=str), encoding="utf-8"
    )
    print("\nSaved summary to fantrax_gps_response_keys.json")

    print("\n=== Step 3: Try getPlayerStats with numRecords=200 ===")
    big_params = {**gps_params, "numRecords": 200, "pageNumber": 0}
    data2 = api1(session, "getPlayerStats", big_params)
    stats2 = data2.get("statsTable") or []
    print(f"With numRecords=200: statsTable length = {len(stats2)}")

    print("\n=== Step 4: Try getPlayerStats sorted by %Rostered ===")
    for sort_id in ["ROS_PCT", "PCT_ROSTERED", "OWNED", "ROSTER_PCT", "rostered"]:
        try:
            d = api1(session, "getPlayerStats", {**gps_params, "sortId": sort_id})
            n = len(d.get("statsTable") or [])
            print(f"  sortId={sort_id!r}: {n} rows")
            if n:
                row = (d.get("statsTable") or [])[0]
                print(f"    first player: {row.get('scorer', {}).get('name', '?')}")
        except Exception as e:
            print(f"  sortId={sort_id!r}: error {e}")


if __name__ == "__main__":
    main()
