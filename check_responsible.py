"""Compare kanban card structure for Nika's vs Marina's deals."""
import os, time, json, re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
load_dotenv()

BRIZO_URL = os.getenv("BRIZO_URL")
token = {"bearer": ""}

def _cap(req):
    if "sad1.brizo.ru/api" in req.url:
        a = req.headers.get("authorization", "")
        if a.startswith("Bearer "):
            token["bearer"] = a

import requests
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.on("request", _cap)
    from brizo import login, _wait_for_kanban
    login(page)
    time.sleep(2)
    _wait_for_kanban(page)
    time.sleep(2)

    # Compare Nika's confirmed deal (1742781) vs Marina's deal (1743067)
    card_info = page.evaluate("""() => {
        const results = [];
        const targets = ['1742781','1742889','1743026','1743067','1743065','1743071'];
        for (const card of document.querySelectorAll('a.kanban-card-deal')) {
            const href = card.getAttribute('href') || '';
            const m = href.match(/deal\\/(\\d+)/);
            if (!m || !targets.includes(m[1])) continue;
            const avatarImg = card.querySelector('.kanban-card-deal__avatar img');
            results.push({
                id: m[1],
                title: (card.querySelector('.kanban-card-deal__title')?.innerText || '').trim(),
                avatar_alt: avatarImg?.getAttribute('alt') || '(no avatar)',
                avatar_src: avatarImg?.getAttribute('src') || '(no src)',
            });
        }
        return results;
    }""")
    browser.close()

for c in card_info:
    print(f"Deal {c['id']} «{c['title']}»: responsible={c['avatar_alt']}")

# Also check API responsible_id for these deals
sess = requests.Session()
sess.headers["Authorization"] = token["bearer"]
sess.headers["Accept"] = "application/json"

print("\n=== API responsible_id ===")
for deal_id in ['1742781','1742889','1743026','1743067','1743065','1743071']:
    r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=15)
    d = r.json()
    resp_id = d.get("responsible_id")
    user_id = d.get("user_id")
    # Find responsible in members
    members = d.get("members", [])
    resp_name = next((m["name"] for m in members if m["id"] == resp_id), f"id={resp_id}")
    print(f"Deal {deal_id}: responsible_id={resp_id} ({resp_name}), user_id={user_id}")
