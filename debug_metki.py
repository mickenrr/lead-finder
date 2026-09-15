"""debug_metki.py — inspect Метки fields when contact creation form is open."""
import sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1743030"

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

    # Find + Создать контакт
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
    print(f"Создать контакт btn: {create_btn}")
    if not create_btn:
        print("ERROR: create button not found")
        browser.close()
        sys.exit(1)

    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)

    # Fill name so form is in "contact filling" state
    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("Дебаг Тестович")
    time.sleep(0.5)

    # Screenshot 1: contact form open, name filled
    page.screenshot(path="/tmp/debug_metki_1_form_open.png")
    print("Screenshot 1 (form open): /tmp/debug_metki_1_form_open.png")

    # List ALL Метки labels and their positions
    metki_info = page.evaluate("""() => {
        const results = [];
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'метки') continue;
            const r = lbl.getBoundingClientRect();
            const container = lbl.closest('.base-input');
            const cr = container ? container.getBoundingClientRect() : {};
            const inp = container?.querySelector('input');
            const ir = inp ? inp.getBoundingClientRect() : {};
            // Find parent chain classes (up to 4 levels)
            let parents = [];
            let el = lbl.parentElement;
            for (let i = 0; i < 6 && el && el !== document.body; i++) {
                if (el.className) parents.push(el.className.toString().slice(0, 50));
                el = el.parentElement;
            }
            results.push({
                label_y: Math.round(r.top),
                label_x: Math.round(r.left),
                label_w: Math.round(r.width),
                label_h: Math.round(r.height),
                container_y: Math.round(cr.top || 0),
                has_input: !!inp,
                input_visible_y: ir.top ? Math.round(ir.top) : null,
                input_w: ir.width ? Math.round(ir.width) : 0,
                parents: parents,
            });
        }
        return results;
    }""")
    print("\n=== All Метки labels when contact form is open ===")
    for i, m in enumerate(metki_info):
        print(f"  [{i}] label_y={m['label_y']} label_x={m['label_x']} "
              f"w={m['label_w']} h={m['label_h']} "
              f"has_input={m['has_input']} input_y={m['input_visible_y']} "
              f"input_w={m['input_w']}")
        print(f"       parents: {m['parents'][:3]}")

    # Also check what the contact__name's parent chain looks like
    name_parents = page.evaluate("""() => {
        const ta = document.querySelector('textarea.contact__name');
        if (!ta) return [];
        let el = ta.parentElement;
        const chain = [];
        for (let i = 0; i < 10 && el && el !== document.body; i++) {
            chain.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,60)});
            el = el.parentElement;
        }
        return chain;
    }""")
    print("\n=== contact__name parent chain ===")
    for p_ in name_parents:
        print(f"  {p_['tag']}: {p_['cls']}")

    # Try pressing Tab and typing role, then screenshot
    page.keyboard.press("Tab")
    time.sleep(0.3)
    page.keyboard.type("Генеральный директор")
    time.sleep(0.5)

    page.screenshot(path="/tmp/debug_metki_2_after_role.png")
    print("\nScreenshot 2 (after role): /tmp/debug_metki_2_after_role.png")

    # Now check Метки positions again
    metki_info2 = page.evaluate("""() => {
        const results = [];
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'метки') continue;
            const r = lbl.getBoundingClientRect();
            const inp = lbl.closest('.base-input')?.querySelector('input');
            const ir = inp ? inp.getBoundingClientRect() : {};
            results.push({
                label_y: Math.round(r.top),
                label_x: Math.round(r.left),
                has_input: !!inp,
                input_y: ir.top ? Math.round(ir.top) : null,
            });
        }
        return results;
    }""")
    print("\n=== All Метки labels AFTER typing role ===")
    for m in metki_info2:
        print(f"  label_y={m['label_y']} label_x={m['label_x']} "
              f"has_input={m['has_input']} input_y={m['input_y']}")

    # Try clicking Метки using contact__name ancestor search
    metki_result = page.evaluate("""() => {
        const nameEl = document.querySelector('textarea.contact__name');
        if (!nameEl) return {found: false, reason: 'no contact__name'};
        // Walk up to find a container that also has Метки
        let el = nameEl.parentElement;
        while (el && el !== document.body) {
            const metki = Array.from(el.querySelectorAll('.base-input__label-text'))
                .find(lbl => lbl.innerText.trim().toLowerCase() === 'метки');
            if (metki) {
                const r = metki.getBoundingClientRect();
                const inp = metki.closest('.base-input')?.querySelector('input');
                if (inp) {
                    const ir = inp.getBoundingClientRect();
                    inp.scrollIntoView({behavior: 'instant', block: 'center'});
                    inp.click();
                    inp.focus();
                    return {
                        found: true,
                        label_y: Math.round(r.top),
                        input_y: Math.round(ir.top),
                        container_cls: el.className.toString().slice(0, 80),
                    };
                }
            }
            el = el.parentElement;
        }
        return {found: false, reason: 'Метки not in contact form ancestors'};
    }""")
    print(f"\n=== Anchor search result (from contact__name up): {metki_result}")

    if metki_result.get("found"):
        time.sleep(0.3)
        page.keyboard.type("123456789012")
        page.keyboard.press("Enter")
        time.sleep(0.5)
        page.screenshot(path="/tmp/debug_metki_3_after_inn.png")
        print("Screenshot 3 (after typing INN): /tmp/debug_metki_3_after_inn.png")

    # Press Escape to close without saving
    page.keyboard.press("Escape")
    time.sleep(0.5)

    browser.close()
    print("\nDone.")
