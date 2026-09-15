"""intercept_stage_change.py — перехватываем все API-вызовы при смене стадии.
Включает response body для диагностики.
"""
import os, sys, time, json
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
EMAIL     = os.getenv("BRIZO_EMAIL", "")
PASSWORD  = os.getenv("BRIZO_PASSWORD", "")
LEAD_ID   = "1742291"   # другой лид — МИР ЭНЕРГО, нет сайта

api_log = []

def _block_track(route):
    if any(d in route.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]):
        route.abort()
        return
    route.continue_()

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu","--no-sandbox","--disable-setuid-sandbox"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    page.route("**", _block_track)

    # Capture ALL XHR/API responses
    def on_response(resp):
        url = resp.url
        method = resp.request.method
        if "brizo.ru/api" not in url:
            return
        if method in ("POST","PUT","PATCH","DELETE"):
            try:
                body = resp.request.post_data or ""
            except Exception:
                body = ""
            try:
                resp_body = resp.text()
            except Exception:
                resp_body = "?"
            entry = {
                "method": method,
                "url": url,
                "request_body": body[:400],
                "status": resp.status,
                "response": resp_body[:400],
            }
            api_log.append(entry)
            print(f"\n>>> {method} {url}")
            print(f"    req: {body[:200]}")
            print(f"    res [{resp.status}]: {resp_body[:200]}")

    page.on("response", on_response)

    # === LOGIN ===
    print("Логин...")
    page.goto(f"{BRIZO_URL}/cabinet/auth/sign-in", timeout=60_000)
    page.wait_for_selector('input[type="email"]', timeout=60_000)
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BRIZO_URL}/cabinet/**", timeout=30_000)
    print(f"URL после логина: {page.url}")
    # Wait for kanban to load
    for _ in range(20):
        if page.query_selector("a.kanban-card-deal"):
            break
        time.sleep(2)
    print("Канбан загружен")

    # === NAVIGATE TO DEAL ===
    print(f"\nОткрываем лид {LEAD_ID}...")
    page.goto(f"{BRIZO_URL}/cabinet/deals#deal/{LEAD_ID}/main", timeout=30_000)
    time.sleep(5)
    page.screenshot(path="/private/tmp/intercept_before.png")
    print(f"URL: {page.url}")

    # Check what's on the page
    picks = page.evaluate("() => Array.from(document.querySelectorAll('.status-picker__pick')).map(p => p.innerText.trim())")
    print(f"Status picker options: {picks}")

    # === CLICK ПРОИГРАНО via Playwright (real click) ===
    print("\nИщем Проиграно через Playwright...")
    proig_clicked = False
    try:
        pick_el = page.locator(".status-picker__pick").filter(has_text="Проиграно").first
        if pick_el.count() > 0 and pick_el.is_visible(timeout=3000):
            pick_el.click()
            proig_clicked = True
            print("Кликнули .status-picker__pick (Playwright)")
    except Exception as e:
        print(f"Playwright click failed: {e}")

    if not proig_clicked:
        # Try the parent item
        try:
            item_el = page.locator(".status-picker__item").filter(has_text="Проиграно").first
            if item_el.count() > 0:
                item_el.click(force=True)
                proig_clicked = True
                print("Кликнули .status-picker__item (force=True)")
        except Exception as e:
            print(f"item click failed: {e}")

    if not proig_clicked:
        print("Пробуем JS click...")
        result = page.evaluate("""() => {
            const picks = document.querySelectorAll('.status-picker__pick');
            for (const pick of picks) {
                if (pick.innerText.trim() === 'Проиграно') {
                    let el = pick.parentElement;
                    while (el && el !== document.body) {
                        const radio = el.querySelector('input[type="radio"].status-picker__radio');
                        if (radio) {
                            radio.click();
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'radio.click';
                        }
                        el = el.parentElement;
                    }
                    pick.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    return 'pick.dispatch';
                }
            }
            return false;
        }""")
        print(f"JS result: {result}")
        proig_clicked = bool(result)

    time.sleep(2)
    page.screenshot(path="/private/tmp/intercept_after_click.png")

    # Check if modal appeared
    modal = page.query_selector(".required-fields-modal, .modal.required-fields-modal")
    modal_visible = modal and modal.is_visible() if modal else False
    print(f"Модал виден: {modal_visible}")

    if modal_visible:
        # Select reason and click Применить
        modal_loc = page.locator(".required-fields-modal, .modal.required-fields-modal").first
        try:
            toggle = modal_loc.locator(".base-select__toggle-btn, .base-input__right-btn").first
            toggle.click()
            time.sleep(2)
            options = page.evaluate("""() => {
                for (const list of document.querySelectorAll('.base-dropdown__list')) {
                    if (!list.offsetParent) continue;
                    const items = list.querySelectorAll('.base-dropdown__list-item-text');
                    if (items.length > 0) {
                        return Array.from(items).map(el => {
                            const r = el.getBoundingClientRect();
                            return {text: el.innerText.trim(), x: r.left+r.width/2, y: r.top+r.height/2};
                        });
                    }
                }
                return [];
            }""")
            print(f"Варианты: {[o['text'] for o in options[:5]]}")
            if options:
                target = next((o for o in options if 'нет кд' in o['text'].lower()), options[0])
                print(f"Кликаем '{target['text']}'")
                page.mouse.click(target['x'], target['y'])
                time.sleep(1)
        except Exception as e:
            print(f"Dropdown error: {e}")

        print(f"\nAPI-запросы до Применить: {len(api_log)}")
        try:
            apply_btn = modal_loc.locator("button.base-button_primary, button.base-button_blue").first
            apply_btn.click(timeout=5000)
            print("Применить нажат")
            time.sleep(3)
            page.screenshot(path="/private/tmp/intercept_after_apply.png")
        except Exception as e:
            print(f"Apply error: {e}")

        print(f"API-запросы после Применить: {len(api_log)}")

    else:
        print("Модал НЕ появился — проверяем API-запросы от клика Проиграно")

    time.sleep(2)
    browser.close()

print("\n========== ВСЕ API ЗАПРОСЫ ==========")
for entry in api_log:
    print(f"\n{entry['method']} {entry['url']}")
    print(f"  req:  {entry['request_body'][:200]}")
    print(f"  res [{entry['status']}]: {entry['response'][:300]}")
print("\nГотово.")
