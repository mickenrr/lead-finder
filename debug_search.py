"""debug_search.py — check what GET /api/contragents returns."""
import json, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _get_api_session

load_dotenv()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    login(page)
    time.sleep(1)
    browser.close()

sess = _get_api_session()
if not sess:
    print("No session!")
    exit(1)

# Test 1: search by known name
print("=== GET /api/contragents?search=Мороз ===")
r = sess.get(f"{BRIZO_URL}/api/contragents", params={"search": "Мороз", "limit": 10}, timeout=15)
print(f"Status: {r.status_code}")
try:
    d = r.json()
    print(json.dumps(d, ensure_ascii=False, indent=2)[:2000])
except:
    print(r.text[:500])

# Test 2: get specific contact we created (id=837279)
print("\n=== GET /api/contragents/837279 ===")
r2 = sess.get(f"{BRIZO_URL}/api/contragents/837279", timeout=10)
print(f"Status: {r2.status_code}")
try:
    print(json.dumps(r2.json(), ensure_ascii=False, indent=2)[:1000])
except:
    print(r2.text[:300])

# Test 3: list all contragents (no filter)
print("\n=== GET /api/contragents?limit=5 ===")
r3 = sess.get(f"{BRIZO_URL}/api/contragents", params={"limit": 5}, timeout=15)
print(f"Status: {r3.status_code}")
try:
    d3 = r3.json()
    print(json.dumps(d3, ensure_ascii=False, indent=2)[:2000])
except:
    print(r3.text[:500])
