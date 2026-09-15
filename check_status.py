"""check_status.py — проверить статус лидов через brizo.py login."""
import os, requests, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-gpu","--no-sandbox","--disable-setuid-sandbox"])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    def _block(route):
        if any(d in route.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]):
            route.abort()
        else:
            route.continue_()
    page.route("**", _block)

    brizo.login(page)

    sess = requests.Session()
    sess.headers.update({
        "Authorization": brizo._api_state["bearer"],
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    })

    # Статусы воронки
    r_statuses = sess.get(f"{BRIZO_URL}/api/statuses", timeout=10)
    print(f"\nСтатусы воронки ({r_statuses.status_code}):")
    status_map = {}
    if r_statuses.status_code == 200:
        for s in r_statuses.json().get("data", []):
            status_map[s["id"]] = s["name"]
            print(f"  id={s['id']}  name={s['name']}")

    # Состояние затронутых лидов
    print()
    for lead_id in ["1742291", "1742295", "1742299", "1742301", "1742304"]:
        r = sess.get(f"{BRIZO_URL}/api/deals/{lead_id}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            sid = d.get("status_id")
            sname = status_map.get(sid, f"id={sid}")
            print(f"Лид {lead_id} ({d.get('name',''):35}): статус={sname!r}  ответственный id={d.get('responsible_id')}")

    browser.close()
