"""quick_check.py — быстрая проверка статусов через bearer от brizo."""
import os, requests, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-gpu","--no-sandbox","--disable-setuid-sandbox"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    page.route("**", lambda r: r.abort() if any(d in r.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]) else r.continue_())
    brizo.login(page)
    sess = requests.Session()
    sess.headers.update({"Authorization": brizo._api_state["bearer"], "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    browser.close()

for lead_id in ["1742309", "1742310", "1742311"]:
    r = sess.get(f"{os.getenv('BRIZO_URL','https://sad1.brizo.ru')}/api/deals/{lead_id}", timeout=10)
    d = r.json()
    print(f"Лид {lead_id}: status_id={d.get('status_id')}  responsible={d.get('responsible_id')}")
