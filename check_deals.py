"""Quick API check for deal contacts and their INN comments."""
import os, time, requests
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

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.on("request", _cap)
    from brizo import login
    login(page)
    time.sleep(2)
    browser.close()

if not token["bearer"]:
    print("No token captured")
    exit(1)

sess = requests.Session()
sess.headers["Authorization"] = token["bearer"]
sess.headers["Accept"] = "application/json"

for deal_id in ["1743067", "1743065", "1743064", "1743071", "1743068", "1743066"]:
    r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=15)
    if r.status_code == 200:
        cs = r.json().get("contragents", [])
        d = r.json()
        dname = d.get("name", "?")
        print(f"\nDeal {deal_id} «{dname}»: {len(cs)} contact(s)")
        for c in cs:
            print(f"  [{c['id']}] {c['name']}")
            rc = sess.get(f"{BRIZO_URL}/api/contragents/{c['id']}/comments",
                          params={"limit": 10}, timeout=10)
            if rc.status_code == 200:
                msgs = [x.get("message", "") for x in rc.json().get("data", [])]
                print(f"    INN comment: {msgs or '(none)'}")
    else:
        print(f"Deal {deal_id}: HTTP {r.status_code}")
