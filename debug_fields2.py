"""debug_fields2.py — получить полный маппинг field_id → name."""

import os
import time
import json
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
_bearer = {"v": ""}


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        page = browser.new_context(
            user_agent="Mozilla/5.0",
            viewport={"width": 1920, "height": 1080},
        ).new_page()

        def _on_req(req):
            if "sad1.brizo.ru/api" in req.url:
                a = req.headers.get("authorization", "")
                if a.startswith("Bearer "):
                    _bearer["v"] = a
        page.on("request", _on_req)

        def _block(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block)

        page.goto(f"{BRIZO_URL}/cabinet/login", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('input[type="email"]', timeout=30_000)
        page.locator('input[type="email"]').fill(os.getenv("BRIZO_EMAIL", ""))
        page.locator('input[type="password"]').fill(os.getenv("BRIZO_PASSWORD", ""))
        page.locator('button[type="submit"]').click()
        page.wait_for_url(lambda u: "/cabinet/" in u and "login" not in u, timeout=60_000)
        time.sleep(3)
        browser.close()

    sess = requests.Session()
    sess.headers.update({
        "Authorization": _bearer["v"],
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BRIZO_URL}/cabinet/deals",
    })

    r = sess.get(f"{BRIZO_URL}/api/fields?model_id=1", timeout=10)
    fields = r.json().get("data", [])
    print(f"Всего полей: {len(fields)}\n")

    # Полный маппинг
    print("=== ВСЕ ПОЛЯ (id → name) ===")
    field_map = {}
    for f in fields:
        fid = f["id"]
        name = f["name"]
        type_id = f["type_id"]
        field_map[fid] = name
        print(f"  id={fid}  type={type_id}  name={name}")

    # Теперь проверим сделку 1742291 с именами полей
    print("\n=== СДЕЛКА 1742291 С ИМЕНАМИ ПОЛЕЙ ===")
    r2 = sess.get(f"{BRIZO_URL}/api/deals/1742291", timeout=10)
    deal = r2.json()
    for f in deal.get("fields", []):
        fid = f["id"]
        fname = field_map.get(fid, f"UNKNOWN_FIELD_{fid}")
        print(f"  [{fid}] {fname}: {repr(f['value'])}")


if __name__ == "__main__":
    main()
