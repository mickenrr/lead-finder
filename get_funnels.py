"""get_funnels.py — получить все статусы воронки через API."""
import os, json, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")

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

r = sess.get(f"{BRIZO_URL}/api/funnels", timeout=10)
data = r.json()
print(json.dumps(data, ensure_ascii=False, indent=2))
