"""debug_api4.py — login via CSRF + session, explore tags API."""
import os, json, re, requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("BRIZO_EMAIL")
PASSWORD = os.getenv("BRIZO_PASSWORD")
BASE = "https://sad1.brizo.ru"
LOGIN_URL = "https://brizo.ru/cabinet/login"

sess = requests.Session()
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
})

# Step 1: GET login page to get CSRF token
print("=== GET login page ===")
r = sess.get(LOGIN_URL, timeout=20)
print(f"Status: {r.status_code}, cookies: {list(sess.cookies.keys())}")

# Find CSRF token in HTML
csrf = None
soup = BeautifulSoup(r.text, "html.parser")
# Look for meta csrf
meta = soup.find("meta", {"name": "csrf-token"})
if meta:
    csrf = meta.get("content")
# Look for hidden input
if not csrf:
    inp = soup.find("input", {"name": "_token"})
    if inp:
        csrf = inp.get("value")
print(f"CSRF token: {csrf}")

# Step 2: POST login
print("\n=== POST login ===")
sess.headers.update({"X-CSRF-TOKEN": csrf or "", "Referer": LOGIN_URL})
login_data = {"email": EMAIL, "password": PASSWORD}
if csrf:
    login_data["_token"] = csrf

r2 = sess.post(LOGIN_URL, data=login_data, timeout=20, allow_redirects=True)
print(f"Login status: {r2.status_code}, url: {r2.url}")
print(f"Cookies after login: {list(sess.cookies.keys())}")

# Step 3: Try API with session
sess.headers.update({
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/cabinet/deals",
})

# GET contact tags
print("\n=== GET /api/tags?model_id=3 ===")
r3 = sess.get(f"{BASE}/api/tags?model_id=3", timeout=20)
print(f"Status: {r3.status_code}")
try:
    data = r3.json()
    print(f"Response: {json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")
except:
    print(f"Raw: {r3.text[:500]}")

# GET tags with different model_id
for mid in [1, 2, 3, 4]:
    r_m = sess.get(f"{BASE}/api/tags?model_id={mid}", timeout=10)
    try:
        d = r_m.json()
        print(f"\nmodel_id={mid}: status={r_m.status_code} items={len(d) if isinstance(d, list) else d}")
    except:
        print(f"model_id={mid}: status={r_m.status_code}, {r_m.text[:100]}")

# Try creating a tag
print("\n=== POST /api/tags ===")
r4 = sess.post(f"{BASE}/api/tags", json={"name": "TEST_INN_API", "model_id": 3}, timeout=10)
print(f"Status: {r4.status_code}, {r4.text[:300]}")

# Try with CSRF header
if csrf:
    sess.headers["X-CSRF-TOKEN"] = csrf
    r5 = sess.post(f"{BASE}/api/tags", json={"name": "TEST_INN_API2", "model_id": 3}, timeout=10)
    print(f"With CSRF — Status: {r5.status_code}, {r5.text[:300]}")
