"""test_reject_api4.py — пробуем разные payload с status_id."""
import os, json, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
TEST_LEAD = "1742281"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-gpu","--no-sandbox"])
    page = browser.new_context(user_agent="Mozilla/5.0", viewport={"width": 1920, "height": 1080}).new_page()
    page.route("**", lambda r: r.abort() if any(d in r.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]) else r.continue_())
    brizo.login(page)
    bearer = brizo._api_state.get("bearer", "")
    browser.close()

sess = requests.Session()
sess.headers.update({"Authorization": bearer, "Accept": "application/json", "User-Agent": "Mozilla/5.0"})

def try_patch(payload, description):
    r = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json=payload, timeout=10)
    print(f"\n{description}")
    print(f"  Payload: {payload}")
    print(f"  Status: {r.status_code}")
    try:
        data = r.json()
        print(f"  Response: {json.dumps(data, ensure_ascii=False)}")
    except Exception:
        print(f"  Response: {r.text[:300]}")
    # Check if stage changed
    rv = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
    actual = rv.json().get("status_id")
    print(f"  Actual status_id: {actual}")
    return r.status_code in (200, 201)

# What does the required_fields error look like for status_id?
try_patch({"status_id": 157665}, "PATCH /status {status_id: 157665}")

# Try with fields array
fields = [{"id": 483204, "value": "Нет КД"}]
try_patch({"status_id": 157665, "fields": fields}, "PATCH /status with fields")

# What field is 483204?
print("\n=== GET /api/fields?model_id=1 (все поля) ===")
rf = sess.get(f"{BRIZO_URL}/api/fields?model_id=1", timeout=10)
for f in rf.json().get("data", []):
    if f["id"] == 483204 or "причина" in f["name"].lower() or "отказ" in f["name"].lower():
        print(f"  id={f['id']} name={f['name']!r} type={f.get('type_id')}")
        if "options" in f:
            for opt in f["options"][:20]:
                print(f"    option: {opt}")

# Also print ALL field names to find rejection reason
print("\n=== Все поля модели 1 ===")
for f in rf.json().get("data", []):
    print(f"  id={f['id']} name={f['name']!r} type_id={f.get('type_id')}")
