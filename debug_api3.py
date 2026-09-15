"""debug_api3.py — use requests to explore Brizo tags API."""
import os, json, requests
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("BRIZO_EMAIL")
PASSWORD = os.getenv("BRIZO_PASSWORD")
BASE = "https://sad1.brizo.ru"

sess = requests.Session()
sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Origin": BASE,
    "Referer": f"{BASE}/cabinet/deals",
})

# Step 1: Login via POST to brizo.ru API
print("=== Logging in ===")
r = sess.post("https://brizo.ru/api/login", json={"email": EMAIL, "password": PASSWORD})
print(f"Login status: {r.status_code}")
try:
    print(f"Login response: {r.json()}")
except:
    print(f"Login raw: {r.text[:500]}")

# Try alternative login endpoint
if r.status_code != 200:
    r2 = sess.post(f"{BASE}/api/login", json={"email": EMAIL, "password": PASSWORD})
    print(f"Alt login status: {r2.status_code}, {r2.text[:200]}")

print(f"Session cookies: {dict(sess.cookies)}")

# Step 2: GET contact tags
print("\n=== GET /api/tags?model_id=3 ===")
r3 = sess.get(f"{BASE}/api/tags?model_id=3")
print(f"Status: {r3.status_code}")
try:
    data = r3.json()
    print(f"Response: {json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")
except:
    print(f"Raw: {r3.text[:500]}")

# Step 3: try POST to create tag
print("\n=== POST /api/tags (create tag) ===")
r4 = sess.post(f"{BASE}/api/tags", json={"name": "TEST_123", "model_id": 3})
print(f"Status: {r4.status_code}")
try:
    print(f"Response: {json.dumps(r4.json(), ensure_ascii=False)}")
except:
    print(f"Raw: {r4.text[:300]}")
