"""
One-time diagnostic: find which endpoint the player-detail popup uses.
Captures ALL new network requests triggered by clicking a player name.
Run with:  python find_ros_endpoint.py
Outputs:   fantrax_popup_requests.json
           fantrax_page_source.html   (full DOM after Angular renders)
           fantrax_links.json          (all <a> elements for selector debugging)
"""
import json
import pickle
import time
from pathlib import Path

COOKIE_FILE = Path("fantrax_cookies.pkl")
LEAGUE_ID = "j3yl79c7man4av42"
OUT = Path("fantrax_popup_requests.json")


def main():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    with webdriver.Chrome(service=service, options=options) as driver:
        # Load cookies
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

        # Navigate to Add Players page
        url = f"https://www.fantrax.com/fantasy/league/{LEAGUE_ID}/players"
        driver.get(url)
        print("Navigated, waiting 20s for Angular to load...")
        time.sleep(20)

        # --- Always save page source for inspection ---
        src = driver.page_source
        Path("fantrax_page_source.html").write_text(src, encoding="utf-8")
        print(f"Saved page source ({len(src)} chars) to fantrax_page_source.html")

        # --- Dump all <a> elements for selector debugging ---
        links_info = driver.execute_script("""
            var links = [];
            document.querySelectorAll('a').forEach(function(a) {
                links.push({
                    text: a.innerText.trim().substring(0, 80),
                    href: a.getAttribute('href') || '',
                    className: a.className || '',
                    id: a.id || '',
                    parentTag: a.parentElement ? a.parentElement.tagName : '',
                    parentClass: a.parentElement ? (a.parentElement.className || '') : ''
                });
            });
            return links;
        """)
        Path("fantrax_links.json").write_text(
            json.dumps(links_info, indent=2), encoding="utf-8"
        )
        print(f"Saved {len(links_info)} links to fantrax_links.json")

        # --- Also dump clickable elements that might be player names ---
        clickable_info = driver.execute_script("""
            var results = [];
            // Look for span/div/td with cursor:pointer that might be player names
            var all = document.querySelectorAll('[class*="player"], [class*="scorer"], [class*="name"]');
            all.forEach(function(el) {
                results.push({
                    tag: el.tagName,
                    text: el.innerText.trim().substring(0, 80),
                    className: el.className || '',
                    href: el.getAttribute('href') || '',
                });
            });
            return results.slice(0, 100);
        """)
        Path("fantrax_clickable.json").write_text(
            json.dumps(clickable_info, indent=2), encoding="utf-8"
        )
        print(f"Saved {len(clickable_info)} player-class elements to fantrax_clickable.json")

        def grab_all_requests(logs):
            """Capture ALL network requests from performance logs."""
            reqs = []
            for log in logs:
                try:
                    msg = json.loads(log["message"])["message"]
                    if msg.get("method") != "Network.requestWillBeSent":
                        continue
                    req = msg.get("params", {}).get("request", {})
                    url_str = req.get("url", "")
                    # Skip noise: images, fonts, CSS, JS bundles, analytics
                    if any(x in url_str for x in [
                        ".png", ".jpg", ".gif", ".ico", ".woff", ".css",
                        "google-analytics", "googletagmanager", "doubleclick",
                        "fantrax.com/static", "fantrax.com/assets",
                        "/sockjs/", "webpack",
                    ]):
                        continue
                    entry = {"url": url_str, "method": req.get("method", "GET")}
                    post = req.get("postData", "")
                    if post:
                        try:
                            entry["body"] = json.loads(post)
                        except Exception:
                            entry["body_raw"] = post[:500]
                    reqs.append(entry)
                except Exception:
                    pass
            return reqs

        # Drain logs from page load
        page_reqs = grab_all_requests(driver.get_log("performance"))
        page_urls = {r["url"] for r in page_reqs}
        print(f"Page load: {len(page_reqs)} requests captured")

        fxpa = [r for r in page_reqs if "/fxpa/req" in r["url"]]
        fxpa_methods = []
        for r in fxpa:
            for m in (r.get("body") or {}).get("msgs", []):
                fxpa_methods.append(m.get("method"))
        print(f"  /fxpa/req methods on page load: {fxpa_methods}")

        # --- Try to click a player name ---
        # Strategy: find <a> elements whose href looks like a player info link
        # (contains 'playerInfo' or similar), not a nav link.
        clicked = False
        clicked_text = ""

        # First try: JS-driven — find first <a> with href containing 'playerInfo'
        js_result = driver.execute_script("""
            var anchors = document.querySelectorAll('a');
            for (var i = 0; i < anchors.length; i++) {
                var a = anchors[i];
                var href = a.getAttribute('href') || '';
                var text = (a.innerText || '').trim();
                // Skip nav links (short text like "Players", "Roster", etc.)
                // Player links typically have a real name (2+ words or longer text)
                if (href.indexOf('playerInfo') !== -1) {
                    a.click();
                    return {clicked: true, text: text, href: href, method: 'playerInfo-href'};
                }
            }
            // Fallback: find first <a> in a table cell
            var td_a = document.querySelector('td a, .scorer a, .player a');
            if (td_a) {
                td_a.click();
                return {clicked: true, text: (td_a.innerText||'').trim(), href: td_a.getAttribute('href')||'', method: 'td-a'};
            }
            return {clicked: false, text: '', href: '', method: 'none'};
        """)
        print(f"JS click attempt: {js_result}")
        if js_result and js_result.get("clicked"):
            clicked = True
            clicked_text = js_result.get("text", "")

        # XPath fallbacks — avoid nav links by excluding short/known nav texts
        if not clicked:
            nav_texts = {"players", "roster", "transactions", "standings", "trade", "home", "scores"}
            xpath_selectors = [
                "//td[contains(@class,'player')]//a",
                "//td[contains(@class,'scorer')]//a",
                "//td[contains(@class,'name')]//a",
                "//span[contains(@class,'player')]//a",
                "//div[contains(@class,'player-name')]//a",
                "//a[contains(@href,'playerInfo')]",
                "//table//tbody//tr[1]//a",
            ]
            for selector in xpath_selectors:
                try:
                    els = driver.find_elements(By.XPATH, selector)
                    for el in els:
                        txt = (el.text or "").strip()
                        if txt.lower() not in nav_texts and len(txt) > 3:
                            print(f"Clicking via {selector}: {txt!r}")
                            el.click()
                            clicked_text = txt
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception as e:
                    print(f"  XPath {selector} failed: {e}")
                    continue

        if not clicked:
            print("WARNING: Could not find a clickable player link.")
            print("  Check fantrax_links.json and fantrax_page_source.html for DOM structure.")

        print(f"Clicked: {clicked!r}, text: {clicked_text!r}")
        print("Waiting 8s for popup API call...")
        time.sleep(8)

        # Capture ALL new requests after click
        popup_reqs = grab_all_requests(driver.get_log("performance"))
        new_reqs = [r for r in popup_reqs if r["url"] not in page_urls]

        print(f"\nNew requests after click ({len(new_reqs)} total):")
        for r in new_reqs:
            print(f"  [{r['method']}] {r['url']}")
            if "body" in r:
                for m in r["body"].get("msgs", []):
                    print(f"    fxpa method: {m.get('method')} data_keys={list(m.get('data',{}).keys())}")

        # Fantrax-only calls
        fantrax_new = [r for r in new_reqs if "fantrax.com" in r["url"]]
        print(f"\nFantrax-only new requests ({len(fantrax_new)}):")
        for r in fantrax_new:
            print(f"  [{r['method']}] {r['url']}")
            if "body" in r:
                print(f"    body: {json.dumps(r['body'])[:300]}")

        result = {
            "clicked": clicked,
            "clicked_text": clicked_text,
            "page_load_fxpa_methods": fxpa_methods,
            "new_requests_after_click": new_reqs,
            "fantrax_new_requests": fantrax_new,
        }
        OUT.write_text(json.dumps(result, indent=2))
        print(f"\nWritten to {OUT}")


if __name__ == "__main__":
    main()
