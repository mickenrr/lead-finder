"""test_reject_api.py — проверяем смену стадии на Проиграно через REST API."""
import os, requests, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")

# Лид для теста (ООО "ОМЕГА", нет сайта, должен быть Проиграно)
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

# Текущий статус
r = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10)
before = r.json().get("status_id")
print(f"Статус до: status_id={before}")

# Попытка 1: PATCH /api/deals/{id}/status {"id": 157665}
print(f"\nПопытка PATCH /api/deals/{TEST_LEAD}/status {{\"id\": 157665}}")
r1 = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}/status", json={"id": 157665}, timeout=10)
print(f"  → {r1.status_code}: {r1.text[:200]}")

after1 = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10).json().get("status_id")
print(f"  Статус после: {after1}")

if after1 == 157665:
    print("  ✓ /status endpoint РАБОТАЕТ!")
else:
    # Попытка 2: PATCH /api/deals/{id} {"status_id": 157665}
    print(f"\nПопытка PATCH /api/deals/{TEST_LEAD} {{\"status_id\": 157665}}")
    r2 = sess.patch(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", json={"status_id": 157665}, timeout=10)
    print(f"  → {r2.status_code}: {r2.text[:200]}")

    after2 = sess.get(f"{BRIZO_URL}/api/deals/{TEST_LEAD}", timeout=10).json().get("status_id")
    print(f"  Статус после: {after2}")
    if after2 == 157665:
        print("  ✓ /deals PATCH РАБОТАЕТ!")
    else:
        print("  ✗ Оба метода не сработали. Нужно искать другой endpoint.")
