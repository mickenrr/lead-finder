"""debug_metki4.py — click toggle-btn, then type INN, look for Create option."""
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

    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("Дебаг4 Тестович")
    time.sleep(0.3)

    # Find and click the TOGGLE BUTTON of the Метки field
    toggle_result = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return null;
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                const toggleBtn = container?.querySelector('.base-select__toggle-btn');
                if (toggleBtn) {
                    container.scrollIntoView({behavior: 'instant', block: 'center'});
                    const r = toggleBtn.getBoundingClientRect();
                    return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)};
                }
                // fallback: click the input
                const inp = container?.querySelector('.base-input__field');
                if (inp) {
                    const r = inp.getBoundingClientRect();
                    return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2), fallback: true};
                }
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"Toggle btn coords: {toggle_result}")

    if not toggle_result:
        print("ERROR: toggle btn not found"); browser.close(); sys.exit(1)

    # Click toggle to open dropdown
    page.mouse.click(toggle_result["x"], toggle_result["y"])
    time.sleep(0.8)

    page.screenshot(path="/tmp/debug_m4_1_toggle_clicked.png")
    print("Screenshot 1 (toggle clicked): /tmp/debug_m4_1_toggle_clicked.png")

    # Check what's in dropdown now
    dropdown_before = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return null;
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                const dropdown = container?.querySelector('.base-input__dropdown');
                return dropdown ? dropdown.innerHTML.slice(0, 500) : 'no dropdown';
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"Dropdown HTML before typing: {dropdown_before!r}")

    # Type INN
    page.keyboard.type(INN)
    time.sleep(1.0)

    page.screenshot(path="/tmp/debug_m4_2_inn_typed.png")
    print("Screenshot 2 (inn typed): /tmp/debug_m4_2_inn_typed.png")

    # Check dropdown after typing
    dropdown_after = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return null;
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const container = metki.closest('.base-input');
                const dropdown = container?.querySelector('.base-input__dropdown');
                return {
                    html: dropdown ? dropdown.innerHTML.slice(0, 1000) : 'no dropdown',
                    text: dropdown ? dropdown.innerText.trim() : '',
                };
            }
            el = el.parentElement;
        }
        return null;
    }""")
    print(f"Dropdown after typing INN: {dropdown_after}")

    # Also check all visible dropdowns on page
    all_dropdowns = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('.base-input__dropdown, .base-dropdown__list'))
            .filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 5 && r.height > 5;
            })
            .map(el => ({
                cls: el.className,
                text: el.innerText.trim().slice(0, 100),
                html: el.innerHTML.slice(0, 300),
            }));
    }""")
    print(f"All visible dropdowns: {all_dropdowns}")

    # Look for a create button or any clickable "create" option
    create_tag_btn = page.evaluate("""() => {
        // Search for create-btn in any visible dropdown
        for (const sel of [
            '.base-select__create-btn',
            '[class*="create-btn"]',
            '.base-dropdown__create',
        ]) {
            for (const el of document.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (r.width > 5 && r.height > 5)
                    return {sel, text: el.innerText.trim().slice(0,50), x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)};
            }
        }
        return null;
    }""")
    print(f"Create-tag button: {create_tag_btn}")

    if create_tag_btn:
        print(f"Clicking create-tag btn: {create_tag_btn}")
        page.mouse.click(create_tag_btn["x"], create_tag_btn["y"])
        time.sleep(0.5)
        page.screenshot(path="/tmp/debug_m4_3_after_create.png")
        print("Screenshot 3: /tmp/debug_m4_3_after_create.png")

        result = page.evaluate("""() => {
            const nameEl = document.querySelector('textarea.contact__name');
            if (!nameEl) return null;
            let el = nameEl.parentElement;
            while (el && el !== document.body) {
                const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                    .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
                if (metki) {
                    return metki.closest('.base-input')?.innerText?.trim();
                }
                el = el.parentElement;
            }
            return null;
        }""")
        print(f"Метки after create click: {result!r}")

    browser.close()
    print("\nDone.")
