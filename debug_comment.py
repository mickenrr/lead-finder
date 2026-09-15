"""debug_comment.py — find correct POST body for contact comments."""
import json, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _get_api_session
import checko as checko_module

load_dotenv()

CONTACT_ID = "837278"

# Login to get Bearer token
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    # Intercept actual comment POST from UI
    captured = []
    def on_req(req):
        if f"/api/contragents/{CONTACT_ID}/comments" in req.url and req.method == "POST":
            captured.append({"url": req.url, "body": req.post_data})

    page.on("request", on_req)
    login(page)

    # Open contact page and submit a comment via UI to capture the call
    page.goto(f"{BRIZO_URL}/cabinet/contragents/{CONTACT_ID}",
              wait_until="domcontentloaded", timeout=30_000)
    time.sleep(3)

    # Find the comment textarea and type
    comment_area = page.locator("textarea.comment-input__field, textarea[placeholder*='коммент'], textarea[placeholder*='Новый']").first
    try:
        comment_area.scroll_into_view_if_needed(timeout=3_000)
        comment_area.click(timeout=3_000)
        comment_area.fill("DEBUG_TEST_COMMENT_12345", timeout=3_000)
        time.sleep(0.5)
        # Submit with Ctrl+Enter
        page.keyboard.press("Control+Enter")
        time.sleep(2)
        print(f"Captured POST calls: {captured}")
    except Exception as e:
        print(f"UI approach failed: {e}")

    browser.close()

sess = _get_api_session()

# Try API formats
print("\n=== Trying POST /api/contragents/{id}/comments variants ===")
for body in [
    {"message": "TEST_INN_API_001"},
    {"text": "TEST_INN_API_002"},
    {"body": "TEST_INN_API_003"},
    {"comment": "TEST_INN_API_004"},
    {"content": "TEST_INN_API_005"},
]:
    r = sess.post(f"{BRIZO_URL}/api/contragents/{CONTACT_ID}/comments",
                  json=body, timeout=10)
    print(f"  {body} → {r.status_code}: {r.text[:200]}")
    if r.status_code in (200, 201):
        print("  *** SUCCESS ***")
        break

# Check current comments
print(f"\n=== GET /api/contragents/{CONTACT_ID}/comments ===")
r2 = sess.get(f"{BRIZO_URL}/api/contragents/{CONTACT_ID}/comments",
              params={"order_by": "desc", "limit": 5}, timeout=10)
data = r2.json()
comments = data.get("data", [])
print(f"Latest {len(comments)} comments:")
for c in comments[:5]:
    print(f"  id={c.get('id')} message={c.get('message', c.get('text', c.get('body', '?')))!r}")
