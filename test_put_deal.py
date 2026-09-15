"""test_put_deal.py — PUT /api/deals/{id} с текущими полями + новый status_id."""
import os, json, requests, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
TEST_LEAD = "1742282"  # ООО "КУБАНЬ-ДИАЛОГ", нет сайта

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-gpu","--no-sandbox"])
    page = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    ).new_page()
    page.route("**", lambda r: r.abort() if any(d in r.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]) else r.continue_())
    brizo.login(page)
    bearer = brizo._api_state.get("bearer", "")
    browser.close()

sess = requests.Session()
sess.headers.update({"Authorization": bearer, "Accept": "application/json", "User-Agent": "Mozilla/5.0"})

# 1. Get current deal state
r = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
deal = r.json()
print(f"Статус до: status_id={deal.get('status_id')}")
print(f"Поля: {[(f['id'], f.get('value')) for f in deal.get('fields', [])]}")

# 2. Also check what fields are listed in /api/fields for model_id=1
rf = sess.get(f"{BRIZO_URL}/api/fields?model_id=1", timeout=10)
print("\n=== ВСЕ ПОЛЯ (model_id=1) ===")
field_defs = {}
for f in rf.json().get("data", []):
    field_defs[f["id"]] = f
    print(f"  id={f['id']} name={f['name']!r} type_id={f.get('type_id')} required={f.get('is_required')}")
    if "options" in f and f["options"]:
        for opt in f["options"][:10]:
            print(f"    option: {opt}")

# 3. Try PUT with current fields + status_id = 157665
print(f"\n=== PUT /api/deals/{TEST_LEAD} с полями ===")
fields_to_send = deal.get("fields", [])
payload = {
    "name": deal["name"],
    "status_id": 157665,
    "budget": deal.get("budget", 0),
    "fields": fields_to_send,
}
print(f"Payload: {json.dumps(payload, ensure_ascii=False)[:300]}")
r_put = sess.put(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", json=payload, timeout=10)
print(f"PUT → {r_put.status_code}")
try:
    resp = r_put.json()
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:500])
except Exception:
    print(r_put.text[:400])

# 4. Check status after
time.sleep(1)
rv = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
actual = rv.json().get("status_id")
print(f"\nСтатус после: {actual}")
if actual == 157665:
    print("✓ PUT СРАБОТАЛ! Статус изменён на Проиграно")
else:
    print("✗ Статус не изменился")

# 5. Try PATCH /status with {"status_id": 157665} and see full error
print(f"\n=== PATCH /api/deals/{TEST_LEAD}/status {{status_id: 157665}} ===")
r_patch = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json={"status_id": 157665}, timeout=10)
print(f"PATCH → {r_patch.status_code}")
try:
    print(json.dumps(r_patch.json(), ensure_ascii=False, indent=2))
except Exception:
    print(r_patch.text)
