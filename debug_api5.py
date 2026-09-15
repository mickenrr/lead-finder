"""debug_api5.py — extract auth from Playwright then use requests for tags API."""
import os, json, time, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login
import checko as checko_module

load_dotenv()
BASE = "https://sad1.brizo.ru"

captured = {"auth": None, "cookies": {}}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    def on_request(req):
        if "sad1.brizo.ru/api" in req.url:
            h = dict(req.headers)
            for k in ("authorization", "Authorization"):
                if k in h:
                    captured["auth"] = h[k]

    page.on("request", on_request)
    login(page)

    # Wait for API calls to be made
    page.goto(f"{BASE}/cabinet/deals", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # Extract all cookies
    cookies = ctx.cookies()
    captured["cookies"] = {c["name"]: c["value"] for c in cookies}

    print(f"Auth header: {captured['auth']}")
    print(f"Cookie names: {list(captured['cookies'].keys())}")
    browser.close()

# Use requests with captured session
sess = requests.Session()
sess.cookies.update(captured["cookies"])
if captured["auth"]:
    sess.headers["Authorization"] = captured["auth"]
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": f"{BASE}/cabinet/deals",
    "X-Requested-With": "XMLHttpRequest",
})

# GET all contact tags
print("\n=== GET /api/tags?model_id=3 ===")
r = sess.get(f"{BASE}/api/tags?model_id=3", timeout=15)
print(f"Status: {r.status_code}")
try:
    data = r.json()
    print(f"Tags: {json.dumps(data, ensure_ascii=False, indent=2)[:3000]}")
except:
    print(f"Raw: {r.text[:500]}")

# Create a tag
print("\n=== POST /api/tags (create) ===")
r2 = sess.post(f"{BASE}/api/tags", json={"name": "590410780500_test", "model_id": 3}, timeout=15)
print(f"Status: {r2.status_code}")
try:
    print(f"Created tag: {json.dumps(r2.json(), ensure_ascii=False)}")
except:
    print(f"Raw: {r2.text[:500]}")
