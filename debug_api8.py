"""debug_api8.py — capture full request/response for contact creation + explore tag assignment."""
import os, json, time, re, requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()
BASE = "https://sad1.brizo.ru"
DEAL_ID = "1743030"

state = {"auth": None, "contragent_id": None, "contragent_post_body": None}

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
            auth = req.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                state["auth"] = auth
            if "contragents" in req.url and req.method == "POST":
                state["contragent_post_body"] = req.post_data

    def on_response(resp):
        url = resp.url
        if "sad1.brizo.ru/api" not in url:
            return
        # Capture contragent creation response
        if "contragents" in url and resp.request.method == "POST" and not re.search(r"/contragents/\d+", url):
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get("id"):
                    state["contragent_id"] = str(body["id"])
                    print(f"*** CONTACT CREATED: id={body['id']} ***")
                    print(f"    Full response: {json.dumps(body, ensure_ascii=False)[:500]}")
            except:
                pass
        # Also from GET /api/contragents/{id}/comments
        m = re.search(r"/api/contragents/(\d+)/comments", url)
        if m and not state["contragent_id"]:
            state["contragent_id"] = m.group(1)
            print(f"*** CONTACT ID from comments URL: {m.group(1)} ***")

    page.on("request", on_request)
    page.on("response", on_response)

    login(page)
    _open_deal(page, DEAL_ID)
    time.sleep(2)

    # Create contact
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
    name_loc.fill("АпиТест8 Контакт")
    time.sleep(0.3)
    page.keyboard.press("Tab")
    time.sleep(2.0)  # wait for POST /api/contragents/ response

    page.mouse.click(1050, 450)
    time.sleep(2.0)

    print(f"\nAuth: {state['auth']}")
    print(f"Contragent ID: {state['contragent_id']}")
    print(f"POST body: {state['contragent_post_body']}")

    auth = state["auth"]
    contragent_id = state["contragent_id"]
    browser.close()

if not auth or not contragent_id:
    print("ERROR: missing auth or contragent_id")
else:
    sess = requests.Session()
    sess.headers.update({
        "Authorization": auth,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE}/cabinet/deals",
    })

    # GET the contragent to see its structure including tags field
    print(f"\n=== GET /api/contragents/{contragent_id} ===")
    r = sess.get(f"{BASE}/api/contragents/{contragent_id}", timeout=15)
    print(f"Status: {r.status_code}")
    try:
        data = r.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    except:
        print(r.text[:500])

    # Create a tag for INN
    print(f"\n=== POST /api/tags (create INN tag) ===")
    r2 = sess.post(f"{BASE}/api/tags", json={"name": "590410780500", "color_id": 1, "model_id": 3}, timeout=10)
    print(f"Status: {r2.status_code}")
    try:
        tag_data = r2.json()
        print(json.dumps(tag_data, ensure_ascii=False))
        tag_id = tag_data.get("id") or (tag_data.get("data") or {}).get("id")
        print(f"Tag ID: {tag_id}")
    except:
        print(r2.text[:300])
        tag_id = None

    if tag_id:
        # Try assigning tag to contragent
        print(f"\n=== Assign tag {tag_id} to contragent {contragent_id} ===")
        # Try POST /api/contragents/{id}/tags
        r3 = sess.post(f"{BASE}/api/contragents/{contragent_id}/tags", json={"tag_id": tag_id}, timeout=10)
        print(f"POST tags status: {r3.status_code}, {r3.text[:200]}")

        # Try PUT /api/contragents/{id} with tags
        r4 = sess.put(f"{BASE}/api/contragents/{contragent_id}", json={"tags": [tag_id]}, timeout=10)
        print(f"PUT with tags status: {r4.status_code}, {r4.text[:200]}")

        # Try PATCH
        r5 = sess.patch(f"{BASE}/api/contragents/{contragent_id}", json={"tags": [tag_id]}, timeout=10)
        print(f"PATCH with tags status: {r5.status_code}, {r5.text[:200]}")
