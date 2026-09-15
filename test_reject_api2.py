"""test_reject_api2.py — ищем правильный формат для смены стадии."""
import os, json, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
TEST_LEAD = "1742281"

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

# Посмотрим на все поля объекта сделки
print("=== Полный объект сделки ===")
r = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
deal = r.json()
# Print top-level keys and their values (not 'fields' array)
for k, v in deal.items():
    if k != "fields":
        print(f"  {k}: {v}")

print(f"\nСтатус до: {deal.get('status_id')}")

# Try PUT /api/deals/{id}
print(f"\n=== PUT /api/deals/{TEST_LEAD} ===")
r_put = sess.put(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", json={"status_id": 157665}, timeout=10)
print(f"  → {r_put.status_code}: {r_put.text[:300]}")

# Check status after PUT
r_check = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
print(f"  Статус после: {r_check.json().get('status_id')}")

# Try PATCH /status with status_id (not id)
print(f"\n=== PATCH /api/deals/{TEST_LEAD}/status {{status_id: 157665}} ===")
r2 = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json={"status_id": 157665}, timeout=10)
print(f"  → {r2.status_code}: {r2.text[:300]}")

# Try to find rejection reasons
print(f"\n=== GET /api/deals/{TEST_LEAD}/reject_reasons ===")
r3 = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/reject_reasons", timeout=10)
print(f"  → {r3.status_code}: {r3.text[:200]}")

print(f"\n=== GET /api/reject_reasons ===")
r4 = sess.get(f"{BRIZO_URL}/api/reject_reasons", timeout=10)
print(f"  → {r4.status_code}: {r4.text[:400]}")

print(f"\n=== GET /api/loss_reasons ===")
r5 = sess.get(f"{BRIZO_URL}/api/loss_reasons", timeout=10)
print(f"  → {r5.status_code}: {r5.text[:400]}")

# Try /status with reason
print(f"\n=== PATCH /status with reason ===")
payloads = [
    {"id": 157665, "reason": "Нет КД"},
    {"id": 157665, "reject_reason": "Нет КД"},
    {"id": 157665, "reject_reason_id": 1},
    {"status_id": 157665, "reject_reason": "Нет КД"},
]
for payload in payloads:
    r_t = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json=payload, timeout=10)
    print(f"  payload={payload} → {r_t.status_code}: {r_t.text[:150]}")
    if r_t.status_code in (200, 201):
        print("  ✓ СРАБОТАЛО!")
        break
