"""debug_metki2.py — inspect dropdown when typing INN into Метки field."""
import sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1743030"
INN = "590410780500"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())
    login(page)

    _open_deal(page, DEAL_ID)
    time.sleep(2)

    # Open Контакты dropdown
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

    # Click + Создать контакт
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
    if not create_btn:
        print("ERROR: create button not found"); browser.close(); sys.exit(1)
    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)

    # Fill name
    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("Дебаг Тестович")
    time.sleep(0.3)

    # Get Метки input coordinates (real coords for mouse click)
    metki_coords = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return null;
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                if (!container) break;
                container.scrollIntoView({behavior: 'instant', block: 'center'});
                const cr = container.getBoundingClientRect();
                return {
                    x: Math.round(cr.left + cr.width / 2),
                    y: Math.round(cr.top + cr.height / 2),
                };
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"Метки coords: {metki_coords}")

    if not metki_coords:
        print("ERROR: Метки not found"); browser.close(); sys.exit(1)

    # Real mouse click on Метки field center
    page.mouse.click(metki_coords["x"], metki_coords["y"])
    time.sleep(0.8)

    page.screenshot(path="/tmp/debug_m2_1_metki_clicked.png")
    print("Screenshot 1 (metki clicked): /tmp/debug_m2_1_metki_clicked.png")

    # Type the INN
    page.keyboard.type(INN)
    time.sleep(0.8)

    page.screenshot(path="/tmp/debug_m2_2_inn_typed.png")
    print("Screenshot 2 (inn typed): /tmp/debug_m2_2_inn_typed.png")

    # Inspect dropdown
    dropdown_info = page.evaluate("""() => {
        const results = [];
        // Look for any visible dropdown list items
        for (const sel of [
            '.base-dropdown__list-item-text',
            '.base-dropdown__create-btn',
            '[class*="create-btn"]',
            '.base-dropdown__list li',
            '.base-dropdown__list > *',
        ]) {
            for (const el of document.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                results.push({
                    sel: sel,
                    text: (el.innerText || '').trim().slice(0, 80),
                    cls: (el.className || '').toString().slice(0, 60),
                    x: Math.round(r.left + r.width/2),
                    y: Math.round(r.top + r.height/2),
                });
            }
        }
        return results;
    }""")
    print(f"\nDropdown items after typing INN: {dropdown_info}")

    # Also look for ANY element containing the INN text
    inn_elements = page.evaluate("""(inn) => {
        const results = [];
        for (const el of document.querySelectorAll('*')) {
            if (!el.offsetParent) continue;
            const txt = (el.innerText || '').trim();
            if (!txt.includes(inn) || el.children.length > 3) continue;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            results.push({
                tag: el.tagName,
                cls: (el.className || '').toString().slice(0, 60),
                text: txt.slice(0, 80),
                x: Math.round(r.left + r.width/2),
                y: Math.round(r.top + r.height/2),
            });
            if (results.length >= 10) break;
        }
        return results;
    }""", INN)
    print(f"\nElements containing INN '{INN}': {inn_elements}")

    # Try Enter first
    page.keyboard.press("Enter")
    time.sleep(0.5)
    page.screenshot(path="/tmp/debug_m2_3_after_enter.png")
    print("Screenshot 3 (after enter): /tmp/debug_m2_3_after_enter.png")

    # Check if chip appeared in Метки field
    chips_after = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return null;
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                return container ? container.innerText.trim() : null;
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"\nМетки field content after Enter: {chips_after!r}")

    browser.close()
    print("\nDone.")
