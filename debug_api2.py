"""debug_api2.py — explore Brizo tags API."""
import sys, time, json, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login
import checko as checko_module

load_dotenv()

BASE = "https://sad1.brizo.ru"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())
    login(page)

    # Extract cookies from Playwright context
    cookies = ctx.cookies()
    session_cookies = {c["name"]: c["value"] for c in cookies}
    print(f"Cookies: {list(session_cookies.keys())}")

    # Try to get auth token from localStorage/sessionStorage
    token_info = page.evaluate("""() => {
        const ls = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && (k.includes('token') || k.includes('auth') || k.includes('user'))) {
                ls[k] = localStorage.getItem(k);
            }
        }
        return ls;
    }""")
    print(f"Auth tokens in localStorage: {token_info}")

    # Get Authorization header from intercepted request
    _state = {"auth_header": None}

    def on_request(req):
        if "sad1.brizo.ru/api" in req.url:
            h = req.headers
            if h.get("authorization"):
                _state["auth_header"] = h.get("authorization")

    page.on("request", on_request)

    # Make a navigation that will trigger API calls
    page.goto(f"{BASE}/cabinet/deals", timeout=30000)
    time.sleep(3)

    auth_header = _state["auth_header"]
    print(f"Captured auth header: {auth_header}")
    browser.close()

# Now use requests with session
sess = requests.Session()
sess.cookies.update(session_cookies)
if auth_header:
    sess.headers["Authorization"] = auth_header
sess.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# GET all contact tags
print("\n=== GET /api/tags?model_id=3 (contact tags) ===")
r = sess.get(f"{BASE}/api/tags?model_id=3")
print(f"Status: {r.status_code}")
try:
    data = r.json()
    print(f"Response: {json.dumps(data, ensure_ascii=False)[:1000]}")
except:
    print(f"Raw: {r.text[:500]}")

# GET deal tags (for comparison)
print("\n=== GET /api/tags?model_id=1 (deal tags) ===")
r2 = sess.get(f"{BASE}/api/tags?model_id=1")
print(f"Status: {r2.status_code}")
try:
    data2 = r2.json()
    print(f"Response: {json.dumps(data2, ensure_ascii=False)[:1000]}")
except:
    print(f"Raw: {r2.text[:500]}")

# Try POST to create a test tag
print("\n=== POST /api/tags (create test tag) ===")
r3 = sess.post(f"{BASE}/api/tags", json={"name": "TEST_INN_123456789012", "model_id": 3})
print(f"Status: {r3.status_code}")
try:
    data3 = r3.json()
    print(f"Response: {json.dumps(data3, ensure_ascii=False)[:500]}")
except:
    print(f"Raw: {r3.text[:500]}")

print("\nDone.")
