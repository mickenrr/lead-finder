"""debug_deal_contacts.py — show full contragents list from deal API."""
import json
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _get_api_session
import checko as checko_module

load_dotenv()

DEAL_ID = "1742889"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())
    login(page)
    browser.close()

sess = _get_api_session()
r = sess.get(f"{BRIZO_URL}/api/deals/{DEAL_ID}", timeout=10)
data = r.json()
print("Status:", r.status_code)
print("Keys:", list(data.keys()))
print("\ncontragents:")
print(json.dumps(data.get("contragents", []), ensure_ascii=False, indent=2))
print("\nclient_type:", data.get("client_type"))
print("client_id:", data.get("client_id"))
