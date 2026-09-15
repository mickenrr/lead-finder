"""test_reject_api3.py — декодируем ошибку required_fields."""
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

# Полный ответ 422
r = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json={"id": 157665}, timeout=10)
print(f"Status: {r.status_code}")
try:
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))
except Exception:
    print(r.text)

# Также проверим, какие поля в fields для этой сделки
print("\n\n=== Поля сделки (fields array) ===")
rd = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
for f in rd.json().get("fields", []):
    print(f"  id={f['id']} type={f['type']} value={repr(f.get('value'))}")
