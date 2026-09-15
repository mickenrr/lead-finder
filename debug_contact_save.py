"""
debug_contact_save.py — find the save mechanism for the contact creation form.

Opens deal 1742781, fills the contact name, then dumps all buttons visible
in the contact form panel (x > 550) before and after pressing Tab.
"""
import sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1742781"
TEST_NAME = "Тестовый Контакт"

def dump_buttons(page, label: str):
    btns = page.evaluate("""() => {
        const out = [];
        for (const btn of document.querySelectorAll('button, [role="button"]')) {
            if (btn.disabled) continue;
            const r = btn.getBoundingClientRect();
            if (r.width < 5 || r.height < 5) continue;
            const txt = (btn.innerText || btn.textContent || '').trim().slice(0, 60);
            const cls = (btn.className || '').toString().slice(0, 80);
            out.push({txt, cls,
                      x: Math.round(r.left + r.width/2),
                      y: Math.round(r.top  + r.height/2),
                      w: Math.round(r.width), h: Math.round(r.height)});
        }
        return out;
    }""")
    print(f"\n=== Buttons [{label}] ===")
    for b in btns:
        marker = " <-- CONTACT PANEL" if b["x"] > 550 else ""
        print(f"  txt={b['txt']!r:<30} x={b['x']:4d} y={b['y']:4d}  cls={b['cls'][:50]}{marker}")

def dump_visible_elements(page, label: str, x_min=550):
    els = page.evaluate(f"""() => {{
        const out = [];
        for (const el of document.querySelectorAll('*')) {{
            const r = el.getBoundingClientRect();
            if (r.width < 5 || r.height < 5) continue;
            if (r.left < {x_min}) continue;
            if (r.top < 0 || r.bottom > 1100) continue;
            const txt = (el.innerText || '').trim().slice(0, 60);
            if (!txt || txt.length > 50) continue;
            if (el.children.length > 3) continue;
            const cls = (el.className || '').toString().slice(0, 60);
            const tag = el.tagName;
            out.push({{tag, txt, cls,
                       x: Math.round(r.left + r.width/2),
                       y: Math.round(r.top  + r.height/2)}});
        }}
        return out;
    }}""")
    print(f"\n=== Visible elements x>{x_min} [{label}] ===")
    for el in els:
        print(f"  {el['tag']:<10} x={el['x']:4d} y={el['y']:4d}  txt={el['txt']!r:<35}  cls={el['cls'][:40]}")

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

    # Scroll to Contacts field and get coords — use container, not input
    # First dump ALL labels to see what's in the DOM
    all_labels = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('.base-input__label-text'))
            .map(lbl => {
                const r = lbl.getBoundingClientRect();
                return {txt: lbl.innerText.trim(), x: Math.round(r.left), y: Math.round(r.top),
                        w: Math.round(r.width), h: Math.round(r.height)};
            });
    }""")
    print(f"All field labels ({len(all_labels)}):")
    for lbl in all_labels:
        print(f"  {lbl['txt']!r:<35} x={lbl['x']:4d} y={lbl['y']:4d} w={lbl['w']:3d} h={lbl['h']:3d}")

    # Retry with extra time — case-insensitive: label renders as 'КОНТАКТЫ'
    field_coords = None
    for attempt in range(5):
        field_coords = page.evaluate("""() => {
            for (const lbl of document.querySelectorAll('.base-input__label-text')) {
                if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
                lbl.scrollIntoView({behavior: 'instant', block: 'center'});
                const container = lbl.closest('.base-input');
                if (!container) return {err: 'no container'};
                const r = container.getBoundingClientRect();
                return {x: Math.round(r.left + r.width / 2),
                        y: Math.round(r.top  + r.height / 2),
                        w: Math.round(r.width), h: Math.round(r.height)};
            }
            return null;
        }""")
        print(f"Attempt {attempt}: Контакты coords = {field_coords}")
        if field_coords and field_coords.get("x", 0) > 10 and field_coords.get("h", 0) > 2:
            break
        time.sleep(1.0)
    time.sleep(0.5)

    # Also check the input element position within the КОНТАКТЫ container
    inp_info = page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
            const container = lbl.closest('.base-input');
            const inp = container?.querySelector('input');
            if (!inp) return {err: 'no input'};
            const r = inp.getBoundingClientRect();
            const cR = container.getBoundingClientRect();
            return {inp_x: Math.round(r.left), inp_y: Math.round(r.top),
                    inp_w: Math.round(r.width), inp_h: Math.round(r.height),
                    cont_right: Math.round(cR.right), cont_bottom: Math.round(cR.bottom),
                    cont_top: Math.round(cR.top)};
        }
        return null;
    }""")
    print(f"Input element inside КОНТАКТЫ: {inp_info}")

    # Click the INPUT element directly (via JS focus+click to avoid opening chip detail)
    clicked = page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
            const container = lbl.closest('.base-input');
            const inp = container?.querySelector('input');
            if (inp) { inp.click(); inp.focus(); return {clicked: true, tag: 'input'}; }
            // Fallback: click right edge of container (past any chips)
            const cR = container.getBoundingClientRect();
            return {clicked: false, fallback: true, x: Math.round(cR.right - 30), y: Math.round(cR.bottom - 15)};
        }
        return null;
    }""")
    print(f"Click result: {clicked}")
    time.sleep(1.0)
    page.screenshot(path=f"/private/tmp/dbg_{DEAL_ID}_step1_contacts_clicked.png")
    print("Screenshot: step1_contacts_clicked")

    # Find + Создать контакт
    create_btn = page.evaluate("""() => {
        for (const el of document.querySelectorAll('.base-select__create-btn, [class*="create-btn"]')) {
            const r = el.getBoundingClientRect();
            if (r.width > 5 && r.height > 5)
                return {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2),
                        cls: (el.className||'').slice(0,60)};
        }
        return null;
    }""")
    print(f"+ Создать контакт button: {create_btn}")
    if not create_btn:
        print("ERROR: create button not found!")
        browser.close()
        sys.exit(1)

    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(1.5)
    page.screenshot(path=f"/private/tmp/dbg_{DEAL_ID}_step2_form_opened.png")
    print("Screenshot: step2_form_opened")

    # Check focused element
    focused = page.evaluate("""() => {
        const el = document.activeElement;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {tag: el.tagName, cls: (el.className||'').slice(0,80),
                x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)};
    }""")
    print(f"Focused after form open: {focused}")

    # Dump buttons before typing
    dump_buttons(page, "before typing")
    dump_visible_elements(page, "contact panel elements", x_min=550)

    # Type the name
    page.keyboard.type(TEST_NAME)
    time.sleep(0.5)
    page.screenshot(path=f"/private/tmp/dbg_{DEAL_ID}_step3_name_typed.png")
    print(f"\nTyped name: {TEST_NAME!r}")

    # Dump buttons after typing
    dump_buttons(page, "after typing name")
    dump_visible_elements(page, "contact panel after typing", x_min=550)

    # Try pressing Tab to move to next field
    page.keyboard.press("Tab")
    time.sleep(0.5)
    page.screenshot(path=f"/private/tmp/dbg_{DEAL_ID}_step4_after_tab.png")

    # Dump buttons after Tab
    dump_buttons(page, "after Tab")
    dump_visible_elements(page, "contact panel after Tab", x_min=550)

    # Check focused element after Tab
    focused2 = page.evaluate("""() => {
        const el = document.activeElement;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {tag: el.tagName, cls: (el.className||'').slice(0,80),
                x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)};
    }""")
    print(f"\nFocused after Tab: {focused2}")

    # Scroll the right panel down to find any save buttons below viewport
    page.evaluate("""() => {
        // Find the contact form scroll container (x > 550)
        function findScrollable(el) {
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            if (r.left < 550) return null;
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 10) return el;
            for (const ch of el.children) {
                const f = findScrollable(ch);
                if (f) return f;
            }
            return null;
        }
        const sc = findScrollable(document.body);
        if (sc) sc.scrollTop += 500;
        return sc ? 'scrolled' : 'no scrollable found';
    }""")
    time.sleep(0.5)
    page.screenshot(path=f"/private/tmp/dbg_{DEAL_ID}_step5_scrolled.png")
    dump_buttons(page, "after scrolling contact panel")
    dump_visible_elements(page, "contact panel scrolled down", x_min=550)

    print("\n\nAll screenshots saved to /private/tmp/dbg_*.png")
    print("Check step2_form_opened and step3_name_typed most carefully.")

    # Don't save — just close
    page.keyboard.press("Escape")
    time.sleep(1)
    browser.close()
