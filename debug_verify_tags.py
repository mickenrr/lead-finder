"""Try model_id=2 for tags — that's what the contact page tag dropdown uses."""
import json
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _get_api_session
import checko as checko_module

load_dotenv()
CONTACT_ID = "837278"

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

# 1. Create a tag with model_id=2
print("=== POST /api/tags with model_id=2 ===")
r1 = sess.post(f"{BRIZO_URL}/api/tags",
               json={"name": "test_inn_m2", "color_id": 1, "model_id": 2}, timeout=10)
print(f"Status: {r1.status_code}")
print(f"Body: {r1.text[:300]}")
tag_m2_id = None
try:
    d1 = r1.json()
    tag_m2_id = d1.get("id")
    print(f"Created tag id: {tag_m2_id}")
except:
    pass

# 2. Try to PUT this tag to the contact
if tag_m2_id:
    print(f"\n=== PUT /api/contragents/{CONTACT_ID}/tags with model_id=2 tag id={tag_m2_id} ===")
    r2 = sess.put(f"{BRIZO_URL}/api/contragents/{CONTACT_ID}/tags",
                  json={"ids": [tag_m2_id]}, timeout=10)
    print(f"Status: {r2.status_code}")
    print(f"Body: {r2.text[:400]}")

    # Verify
    r3 = sess.get(f"{BRIZO_URL}/api/contragents/{CONTACT_ID}", timeout=10)
    print(f"\nAfter PUT — tags: {r3.json().get('tags')}")

    # Check if tag shows in model_id=2 list
    print(f"\n=== GET /api/tags?model_id=2 ===")
    r4 = sess.get(f"{BRIZO_URL}/api/tags?model_id=2", timeout=10)
    print(f"Status: {r4.status_code}, Body: {r4.text[:300]}")
