"""debug_api.py — intercept Brizo API calls when interacting with Метки field.
Manually interact with the contact Метки after script opens the form.
"""
import sys, time, json
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module

load_dotenv()

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1743030"

api_calls = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    # Intercept all requests
    def on_request(req):
        url = req.url
        if any(x in url for x in ["brizo.ru/api", "brizo.ru/v", ".brizo.ru/api"]):
            api_calls.append({
                "method": req.method,
                "url": url,
                "post_data": req.post_data[:200] if req.post_data else None,
            })

    page.on("request", on_request)

    login(page)
    api_calls.clear()  # clear login calls

    _open_deal(page, DEAL_ID)
    time.sleep(2)
    api_calls.clear()

    # Open contact form
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
    if not create_btn:
        print("ERROR: create button not found"); browser.close(); sys.exit(1)
    page.mouse.click(create_btn["x"], create_btn["y"])
    time.sleep(2.0)
    api_calls.clear()

    name_loc = page.locator("textarea.contact__name").first
    name_loc.wait_for(state="visible", timeout=5000)
    name_loc.fill("Апи Тест")
    time.sleep(0.5)
    api_calls.clear()

    print("=== Form is ready. Pausing 30s for MANUAL interaction ===")
    print("Please MANUALLY click Метки, add a tag, and observe the result.")
    print("The script will print all API calls made during this time.")
    time.sleep(30)

    print("\n=== API calls during Метки interaction ===")
    for c in api_calls:
        print(f"  {c['method']} {c['url']}")
        if c["post_data"]:
            print(f"    body: {c['post_data']}")

    # Also check current state of page
    all_requests = page.evaluate("""() => {
        return window.performance.getEntriesByType('resource')
            .filter(r => r.name.includes('brizo') && r.name.includes('api'))
            .map(r => r.name)
            .slice(-20);
    }""")
    print(f"\nRecent API URLs from performance: {all_requests}")

    browser.close()
    print("\nDone.")
