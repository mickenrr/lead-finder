"""debug_metki3.py — try Tab/comma/click to commit tag in Метки."""
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
    if not create_btn:
        print("ERROR: create button not found"); browser.close(); sys.exit(1)
    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)

    # Fill name
    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("Дебаг2 Тестович")
    time.sleep(0.3)

    # Get Метки container coords
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
                return {x: Math.round(cr.left + cr.width / 2), y: Math.round(cr.top + cr.height / 2)};
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"Метки coords: {metki_coords}")

    # Click Метки with real mouse
    page.mouse.click(metki_coords["x"], metki_coords["y"])
    time.sleep(0.5)

    # Type INN char by char (to trigger keydown/input events per character)
    page.keyboard.type(INN)
    time.sleep(0.8)

    page.screenshot(path="/tmp/debug_m3_1_inn_typed.png")
    print("Screenshot 1 (inn typed): /tmp/debug_m3_1_inn_typed.png")

    # ----- Try Tab -----
    print("Trying Tab...")
    page.keyboard.press("Tab")
    time.sleep(0.5)
    page.screenshot(path="/tmp/debug_m3_2_after_tab.png")
    chip_after_tab = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return 'no contact__name';
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                // Look for chips
                const chips = container ? container.querySelectorAll('[class*="chip"], [class*="tag"], [class*="label"]') : [];
                return {
                    innerText: container ? container.innerText.trim() : null,
                    chipCount: chips.length,
                    chips: Array.from(chips).map(c => c.innerText.trim().slice(0, 30)),
                };
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"After Tab — Метки: {chip_after_tab}")
    print("Screenshot 2 (after Tab): /tmp/debug_m3_2_after_tab.png")

    # ----- If Tab didn't work, re-click and try Comma -----
    # First check if the field is empty still
    field_empty = (chip_after_tab or {}).get("innerText", "Метки") == "Метки"
    if field_empty:
        print("Tab didn't commit. Re-clicking Метки and trying Comma...")
        page.mouse.click(metki_coords["x"], metki_coords["y"])
        time.sleep(0.5)
        page.keyboard.type(INN)
        time.sleep(0.5)
        page.keyboard.press(",")
        time.sleep(0.5)
        chip_after_comma = page.evaluate("""() => {
            const nameEl = document.querySelector('textarea.contact__name');
            if (!nameEl) return 'no contact__name';
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
        page.screenshot(path="/tmp/debug_m3_3_after_comma.png")
        print(f"After Comma — Метки: {chip_after_comma!r}")
        print("Screenshot 3 (after Comma): /tmp/debug_m3_3_after_comma.png")

        # ----- Inspect DOM of Метки for any interactive elements -----
        metki_dom = page.evaluate("""() => {
            const nameEl = document.querySelector('textarea.contact__name');
            if (!nameEl) return null;
            let el = nameEl.parentElement;
            while (el && el !== document.body) {
                const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                    .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
                if (metki) {
                    const container = metki.closest('.base-input');
                    return container ? container.innerHTML.slice(0, 2000) : null;
                }
                el = el.parentElement;
            }
            return null;
        }""")
        print(f"\n=== Метки container innerHTML ===\n{metki_dom}")

    browser.close()
    print("\nDone.")
