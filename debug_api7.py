"""debug_api7.py — capture ALL API calls during contact creation."""
import os, json, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()
BASE = "https://sad1.brizo.ru"
DEAL_ID = "1743030"

all_requests = []
all_responses = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    def on_request(req):
        url = req.url
        if "sad1.brizo.ru/api" in url or "brizo.ru/api" in url:
            all_requests.append(f"{req.method} {url}")

    def on_response(resp):
        url = resp.url
        if "sad1.brizo.ru/api" in url or "brizo.ru/api" in url:
            try:
                body = resp.json()
                all_responses.append({
                    "method": resp.request.method,
                    "url": url,
                    "status": resp.status,
                    "body_keys": list(body.keys()) if isinstance(body, dict) else f"list[{len(body)}]",
                })
            except:
                all_responses.append({"method": resp.request.method, "url": url, "status": resp.status, "body_keys": "?"})

    page.on("request", on_request)
    page.on("response", on_response)

    login(page)
    _open_deal(page, DEAL_ID)
    time.sleep(2)

    # Clear logs - only track what happens during contact creation
    all_requests.clear()
    all_responses.clear()

    # Open contact form
    page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
            lbl.scrollIntoView({behavior: 'instant', block: 'center'});
            const inp = lbl.closest('.base-input')?.querySelector('input');
            if (inp) { inp.click(); inp.focus(); }
            return;
        }
    }""")
    time.sleep(1.5)

    create_btn = page.evaluate("""() => {
        for (const el of document.querySelectorAll('*')) {
            const txt = (el.innerText || '').trim();
            if (txt !== 'Создать контакт') continue;
            const r = el.getBoundingClientRect();
            if (r.width > 5 && r.height > 5)
                return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)};
        }
        return null;
    }""")
    print(f"Create btn: {create_btn}")
    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)

    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)

    print("\n--- Filling name (watch for API calls) ---")
    all_requests.clear(); all_responses.clear()
    name_loc.fill("АпиТест2 Контакт")
    time.sleep(0.5)
    page.keyboard.press("Tab")
    time.sleep(1.5)
    print(f"API requests after fill+Tab: {all_requests}")
    print("API responses after fill+Tab: " + str([r['url'].split('/api/')[-1] + '(' + str(r['status']) + ')' for r in all_responses]))

    print("\n--- Clicking comments area (save) ---")
    all_requests.clear(); all_responses.clear()
    page.mouse.click(1050, 450)
    time.sleep(2.5)
    print(f"API requests after click-save: {all_requests}")
    for r in all_responses:
        print(f"  {r['method']} /api/{r['url'].split('/api/')[-1]} → {r['status']} keys={r['body_keys']}")

    # Now try to capture full response body for POST/PUT requests
    print("\n\n=== Full details of write requests ===")
    for r in all_responses:
        if r["method"] in ("POST", "PUT", "PATCH"):
            print(f"  {r['method']} {r['url']}")
            print(f"    keys: {r['body_keys']}")

    browser.close()
