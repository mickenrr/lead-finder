"""debug_fields.py — найти маппинг field_id → field_name через API."""

import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")

_bearer = {"v": ""}


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

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

    endpoints = [
        "/api/deal/fields",
        "/api/deals/fields",
        "/api/fields?model=deal",
        "/api/fields?model_id=1",
        "/api/fields",
        "/api/custom-fields",
        "/api/pipeline/fields",
    ]
    for ep in endpoints:
        r = sess.get(f"{BRIZO_URL}{ep}", timeout=10)
        print(f"GET {ep} → {r.status_code}: {r.text[:400]}")
        print()


if __name__ == "__main__":
    main()
