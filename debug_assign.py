"""debug_assign.py — inspect the deal popup to understand Ответственный field structure."""

import json
import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
LOGIN_URL  = f"{BRIZO_URL}/cabinet/login"

# Use a lead we know exists; pick any from the Bass column
DEAL_ID = "1742298"   # ООО "ДЫМОВ. ЮГ" — one we saw in run15/16


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        def _block(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block)

        # Capture Bearer token
        _bearer = {"v": ""}
        def _on_req(req):
            if "sad1.brizo.ru/api" in req.url:
                a = req.headers.get("authorization", "")
                if a.startswith("Bearer "):
                    _bearer["v"] = a
        page.on("request", _on_req)

        # Login
        print("Logging in...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('input[type="email"]', timeout=30_000)
        page.locator('input[type="email"]').fill(os.getenv("BRIZO_EMAIL", ""))
        page.locator('input[type="password"]').fill(os.getenv("BRIZO_PASSWORD", ""))
        page.locator('button[type="submit"]').click()
        page.wait_for_url(lambda u: "/cabinet/" in u and "login" not in u, timeout=60_000)
        print(f"Logged in at {page.url}")
        time.sleep(3)

        # Open the deal
        page.goto(f"{BRIZO_URL}/cabinet/deals#deal/{DEAL_ID}/main", timeout=60_000)
        time.sleep(4)

        # --- Screenshot 1: initial state ---
        page.screenshot(path="/private/tmp/debug_01_initial.png")
        print("Screenshot 1: initial state saved")

        # Dump ALL base-input fields
        fields = page.evaluate("""() => {
            const result = [];
            for (const c of document.querySelectorAll('.base-input')) {
                const lbl = c.querySelector('.base-input__label-text');
                const inp = c.querySelector('input, textarea');
                const toggle = c.querySelector('.base-select__toggle-btn, .base-input__right-btn');
                const r = c.getBoundingClientRect();
                result.push({
                    label: lbl ? lbl.innerText.trim() : '?',
                    value: inp ? inp.value : '',
                    placeholder: inp ? inp.placeholder : '',
                    readonly: inp ? inp.readOnly : null,
                    disabled: inp ? inp.disabled : null,
                    hasToggle: !!toggle,
                    toggleCls: toggle ? toggle.className : '',
                    x: Math.round(r.left), y: Math.round(r.top),
                    w: Math.round(r.width), h: Math.round(r.height),
                    visible: r.width > 0 && r.height > 0
                });
            }
            return result;
        }""")
        print("\n=== ALL BASE-INPUT FIELDS ===")
        for f in fields:
            if f['visible']:
                print(json.dumps(f, ensure_ascii=False))

        # Dump popup-members section
        members_info = page.evaluate("""() => {
            const pm = document.querySelector('.popup-members');
            if (!pm) return {err: 'no .popup-members'};
            const r = pm.getBoundingClientRect();
            const imgs = Array.from(pm.querySelectorAll('img.avatar-image')).map(img => {
                const ir = img.getBoundingClientRect();
                return {alt: img.alt, src: img.src.slice(-30), x: Math.round(ir.left), y: Math.round(ir.top)};
            });
            const addBtn = pm.querySelector('button.popup-members__add-btn');
            let addCoords = null;
            if (addBtn) {
                const br = addBtn.getBoundingClientRect();
                addCoords = {x: Math.round(br.left + br.width/2), y: Math.round(br.top + br.height/2)};
            }
            return {
                x: Math.round(r.left), y: Math.round(r.top),
                w: Math.round(r.width), h: Math.round(r.height),
                avatars: imgs,
                addBtnCoords: addCoords,
                innerHTML: pm.innerHTML.slice(0, 500)
            };
        }""")
        print("\n=== POPUP-MEMBERS SECTION ===")
        print(json.dumps(members_info, ensure_ascii=False, indent=2))

        # Try clicking "+" and see what happens
        add_btn = members_info.get("addBtnCoords")
        if add_btn:
            print(f"\nClicking '+' at {add_btn}...")
            page.mouse.click(add_btn["x"], add_btn["y"])
            time.sleep(2)
            page.screenshot(path="/private/tmp/debug_02_after_plus.png")
            print("Screenshot 2: after '+' click saved")

            # What new inputs appeared?
            new_inputs = page.evaluate("""() => {
                const result = [];
                for (const inp of document.querySelectorAll('input, textarea')) {
                    if (!inp.offsetParent) continue;
                    const r = inp.getBoundingClientRect();
                    if (r.width < 5 || r.height < 5) continue;
                    result.push({
                        tag: inp.tagName,
                        type: inp.type || '',
                        cls: inp.className.slice(0, 80),
                        placeholder: inp.placeholder,
                        value: inp.value,
                        x: Math.round(r.left), y: Math.round(r.top)
                    });
                }
                return result;
            }""")
            print("\n=== ALL VISIBLE INPUTS AFTER '+' CLICK ===")
            for i in new_inputs:
                print(json.dumps(i, ensure_ascii=False))

            # Find any search input that appeared (not the main fields)
            search_input = next(
                (i for i in new_inputs if i["x"] > 400 and i["y"] > 50 and i["y"] < 600),
                None,
            )
            if search_input:
                print(f"\nFound candidate search input: {search_input}")
                # Click it and type
                page.mouse.click(search_input["x"], search_input["y"])
                time.sleep(0.5)
                page.keyboard.type("Ника")
                time.sleep(2)
                page.screenshot(path="/private/tmp/debug_03_after_typing.png")
                print("Screenshot 3: after typing 'Ника' saved")

                # What dropdown items appeared?
                dropdown_items = page.evaluate("""() => {
                    const result = [];
                    for (const el of document.querySelectorAll(
                        '.base-dropdown__list-item-text, li, [class*=list-item]'
                    )) {
                        if (!el.offsetParent) continue;
                        const t = el.innerText.trim();
                        if (!t) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width < 5 || r.height < 5) continue;
                        result.push({tag: el.tagName, cls: el.className.slice(0, 60), text: t, x: Math.round(r.left), y: Math.round(r.top)});
                    }
                    return result;
                }""")
                print("\n=== DROPDOWN ITEMS AFTER TYPING 'Ника' ===")
                for item in dropdown_items:
                    print(json.dumps(item, ensure_ascii=False))
            else:
                print("No candidate search input found after '+' click")

        # Try the API approach — get users
        if _bearer["v"]:
            print(f"\n=== API: Bearer captured ({_bearer['v'][:40]}...) ===")
            import requests as _req
            sess = _req.Session()
            sess.headers.update({
                "Authorization": _bearer["v"],
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{BRIZO_URL}/cabinet/deals",
            })
            # Get full members list
            r = sess.get(f"{BRIZO_URL}/api/members", timeout=10)
            members = r.json().get("data", [])
            print("\n=== ALL MEMBERS ===")
            for m in members:
                print(f"  id={m['id']}  name={m['name']}  email={m['email']}")

            nika = next(
                (m for m in members if "Ника" in m.get("name","") or "Серафимова" in m.get("name","")),
                None,
            )
            print(f"\nНика: {nika}")

            if nika:
                nid = nika["id"]
                print(f"\n=== API tests: set responsible={nid} on deal {DEAL_ID} ===")
                for method, endpoint, body in [
                    ("PATCH", f"/api/deals/{DEAL_ID}", {"responsible_id": nid}),
                    ("PUT",   f"/api/deals/{DEAL_ID}/responsible", {"user_id": nid}),
                    ("POST",  f"/api/deals/{DEAL_ID}/members", {"user_id": nid, "is_responsible": True}),
                    ("PUT",   f"/api/deals/{DEAL_ID}/members/{nid}", {"is_responsible": True}),
                ]:
                    fn = getattr(sess, method.lower())
                    rr = fn(f"{BRIZO_URL}{endpoint}", json=body, timeout=10)
                    print(f"{method} {endpoint} → {rr.status_code}: {rr.text[:150]}")

                # Read back the deal to see what changed
                rd = sess.get(f"{BRIZO_URL}/api/deals/{DEAL_ID}", timeout=10)
                d = rd.json()
                print(f"\nDeal after tests: responsible_id={d.get('responsible_id')}")
                for m in d.get("members", []):
                    print(f"  {m['name']} is_responsible={m.get('is_responsible')} id={m['id']}")
        else:
            print("\nNo Bearer token captured — API tests skipped")

        browser.close()
        print("\nDone. Check screenshots at /private/tmp/debug_*.png")


if __name__ == "__main__":
    main()
