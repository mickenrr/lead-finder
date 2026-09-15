"""debug_reject_intercept.py — перехватываем сетевые запросы при reject_lead."""
import os, sys, time, json
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
EMAIL    = os.getenv("BRIZO_EMAIL", "")
PASSWORD = os.getenv("BRIZO_PASSWORD", "")
LEAD_ID  = "1742281"   # ООО "ОМЕГА" — нет сайта

api_calls = []

def _log_req(route):
    req = route.request
    if any(d in req.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
        route.abort()
        return
    if req.method in ("POST", "PUT", "PATCH", "DELETE") and "brizo.ru" in req.url:
        body = ""
        try:
            body = req.post_data or ""
        except Exception:
            pass
        entry = {"method": req.method, "url": req.url, "body": body[:600]}
        api_calls.append(entry)
        print(f"\n>>> {req.method} {req.url}")
        if body:
            print(f"    body: {body[:400]}")
    route.continue_()

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu", "--no-sandbox", "--disable-setuid-sandbox"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    page.route("**", _log_req)

    # ---------- Login ----------
    print("Логин...")
    page.goto(f"{BRIZO_URL}/cabinet/auth/sign-in", timeout=60_000)
    page.wait_for_selector('input[type="email"]', timeout=60_000)
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BRIZO_URL}/cabinet/**", timeout=30_000)
    print(f"Залогинились. URL: {page.url}")
    time.sleep(2)

    # ---------- Open deal ----------
    print(f"\nОткрываем лид {LEAD_ID}...")
    page.goto(f"{BRIZO_URL}/cabinet/deals#deal/{LEAD_ID}/main", timeout=30_000)
    time.sleep(4)

    # Dismiss overlay if present (but NOT if rejection modal already open)
    try:
        modal_el = page.query_selector(".required-fields-modal, .modal.required-fields-modal")
        if not (modal_el and modal_el.is_visible()):
            overlay = page.query_selector(".bg-overlay, .brizo-popup-overlay")
            if overlay and overlay.is_visible():
                print("Overlay найден — нажимаем Escape")
                page.keyboard.press("Escape")
                time.sleep(0.5)
    except Exception:
        pass

    page.screenshot(path="/private/tmp/reject_before_radio.png")
    print("Скрин до клика radio: /private/tmp/reject_before_radio.png")

    # ---------- Click Проиграно radio (real Playwright click) ----------
    print("\nКликаем Проиграно через Playwright locator...")
    proig_clicked = False
    try:
        # Try clicking the visible label/text
        pick = page.locator(".status-picker__pick", has_text="Проиграно").first
        if pick.is_visible(timeout=3_000):
            pick.click()
            proig_clicked = True
            print("Кликнули .status-picker__pick (Playwright)")
    except Exception as e:
        print(f"  Playwright pick click failed: {e}")

    if not proig_clicked:
        # Fallback: JS click on the radio
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
        print(f"  JS fallback result: {result}")
        proig_clicked = bool(result)

    if not proig_clicked:
        print("ОШИБКА: Проиграно не найден")
        browser.close()
        sys.exit(1)

    print("Клик выполнен. Ждём модал...")

    # ---------- Wait for modal ----------
    try:
        page.wait_for_selector(
            ".required-fields-modal, .modal.required-fields-modal",
            state="visible", timeout=8_000
        )
        print("Модал появился!")
    except Exception as e:
        print(f"Модал НЕ появился: {e}")
        page.screenshot(path="/private/tmp/reject_no_modal.png")
        browser.close()
        sys.exit(1)

    page.screenshot(path="/private/tmp/reject_modal_open.png")
    print("Скрин модала: /private/tmp/reject_modal_open.png")

    # ---------- Open dropdown and select option ----------
    modal_sel = ".required-fields-modal, .modal.required-fields-modal"
    modal_loc = page.locator(modal_sel).first

    # Click dropdown toggle
    toggle = modal_loc.locator(".base-select__toggle-btn, .base-input__right-btn").first
    toggle.click()
    time.sleep(2)
    page.screenshot(path="/private/tmp/reject_dropdown_open.png")
    print("Дропдаун открыт")

    # Collect options
    options = page.evaluate("""() => {
        for (const list of document.querySelectorAll('.base-dropdown__list')) {
            if (!list.offsetParent) continue;
            const items = list.querySelectorAll('.base-dropdown__list-item-text');
            if (items.length > 0) {
                return Array.from(items).map(el => {
                    const r = el.getBoundingClientRect();
                    return {text: el.innerText.trim(), x: r.left + r.width/2, y: r.top + r.height/2};
                });
            }
        }
        return [];
    }""")
    print(f"Варианты причины: {[o['text'] for o in options[:5]]}")

    target = next((o for o in options if 'нет кд' in o['text'].lower()), options[0] if options else None)
    if target:
        print(f"Кликаем '{target['text']}' по координатам ({target['x']:.0f}, {target['y']:.0f})")
        page.mouse.click(target["x"], target["y"])
        time.sleep(1)
        page.screenshot(path="/private/tmp/reject_option_selected.png")
        print("Скрин после выбора: /private/tmp/reject_option_selected.png")

        # Read the input value after selection
        val = page.evaluate("""() => {
            const modal = document.querySelector('.required-fields-modal, .modal.required-fields-modal');
            const inp = modal?.querySelector('input.base-input__field');
            return inp ? inp.value : 'NOT FOUND';
        }""")
        print(f"Значение поля 'Причина отказа' после выбора: '{val}'")
    else:
        print("ОШИБКА: нет вариантов в дропдауне!")
        browser.close()
        sys.exit(1)

    # ---------- Click Применить ----------
    print(f"\nСейчас нажмём Применить. API-запросы до этого: {len(api_calls)}")
    time.sleep(0.5)

    apply_btn = modal_loc.locator(
        "button.base-button_primary, button.base-button_blue, "
        "button[class*=primary], button[class*=blue]"
    ).first
    apply_btn.wait_for(state="visible", timeout=5_000)
    apply_btn.click(timeout=5_000)
    print("Применить нажат. Ждём закрытия модала...")

    time.sleep(3)
    page.screenshot(path="/private/tmp/reject_after_apply.png")
    print(f"Скрин после Применить: /private/tmp/reject_after_apply.png")
    print(f"API-запросы после Применить: {len(api_calls)}")

    # Wait for modal to close
    try:
        page.wait_for_selector(modal_sel, state="hidden", timeout=12_000)
        print("Модал закрылся!")
    except Exception:
        print("Модал НЕ закрылся за 12 секунд")

    time.sleep(2)
    browser.close()

print("\n========== Все API-запросы ==========")
for i, c in enumerate(api_calls):
    print(f"\n[{i+1}] {c['method']} {c['url']}")
    if c['body']:
        try:
            parsed = json.loads(c['body'])
            print(f"  body: {json.dumps(parsed, ensure_ascii=False)}")
        except Exception:
            print(f"  body: {c['body']}")
print("\nГотово.")
