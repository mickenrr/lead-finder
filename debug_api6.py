"""debug_api6.py — find contact creation API + tag assignment endpoint."""
import os, json, time, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()
BASE = "https://sad1.brizo.ru"
DEAL_ID = "1743030"

captured = {"auth": None, "contact_responses": []}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    def on_request(req):
        if "sad1.brizo.ru/api" in req.url:
            h = dict(req.headers)
            for k in ("authorization", "Authorization"):
                if k in h:
                    captured["auth"] = h[k]

    def on_response(resp):
        url = resp.url
        if "sad1.brizo.ru/api/contacts" in url:
            try:
                body = resp.json()
                captured["contact_responses"].append({
                    "url": url,
                    "status": resp.status,
                    "method": resp.request.method,
                    "body": body,
                })
            except:
                pass

    page.on("request", on_request)
    page.on("response", on_response)
    login(page)

    _open_deal(page, DEAL_ID)
    time.sleep(2)

    # Create one contact
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
    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)

    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("АпиТест Контакт")
    time.sleep(0.3)
    page.keyboard.press("Tab")
    time.sleep(0.3)
    page.keyboard.type("Генеральный директор")
    time.sleep(0.5)

    # Click elsewhere to save
    page.mouse.click(1050, 450)
    time.sleep(2.0)

    print("=== Contact API responses captured ===")
    for r in captured["contact_responses"]:
        print(f"\n  {r['method']} {r['url']} → {r['status']}")
        print(f"  Body: {json.dumps(r['body'], ensure_ascii=False)[:500]}")

    # Get contact chips to find IDs
    contact_chips = page.evaluate("""() => {
        const chips = document.querySelectorAll('[class*="chip"], [class*="contact-chip"], [class*="tag-chip"]');
        return Array.from(chips).map(c => ({
            text: c.innerText.trim().slice(0, 50),
            cls: c.className.toString().slice(0, 60),
            html: c.innerHTML.slice(0, 200),
        }));
    }""")
    print(f"\nContact chips in DOM: {contact_chips[:5]}")

    auth = captured["auth"]
    browser.close()

# API calls with auth
if not auth:
    print("No auth header captured")
else:
    sess = requests.Session()
    sess.headers.update({
        "Authorization": auth,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": f"{BASE}/cabinet/deals",
    })

    # Search for the test contact
    print("\n=== GET /api/contacts?search=АпиТест ===")
    r = sess.get(f"{BASE}/api/contacts", params={"search": "АпиТест"}, timeout=15)
    print(f"Status: {r.status_code}")
    try:
        data = r.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    except:
        print(r.text[:500])

    # Try contacts list
    print("\n=== GET /api/contacts?limit=5 ===")
    r2 = sess.get(f"{BASE}/api/contacts", params={"limit": 5}, timeout=15)
    print(f"Status: {r2.status_code}")
    try:
        data2 = r2.json()
        print(json.dumps(data2, ensure_ascii=False, indent=2)[:2000])
    except:
        print(r2.text[:500])
