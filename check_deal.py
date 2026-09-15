"""Quick check: open deal and take screenshot of Contacts field."""
import sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal
import checko as checko_module
load_dotenv()

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1742781"

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

    # Scroll to Contacts field
    page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() === 'контакты')
                lbl.scrollIntoView({behavior: 'instant', block: 'center'});
        }
    }""")
    time.sleep(0.5)
    page.screenshot(path=f"/private/tmp/check_deal_{DEAL_ID}.png")
    print(f"Screenshot: /private/tmp/check_deal_{DEAL_ID}.png")

    # Also print Contacts field text
    txt = page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
            const r = lbl.getBoundingClientRect();
            if (r.width < 5 || r.height < 5) continue;  // skip invisible sidebar label
            const c = lbl.closest('.base-input');
            return c ? c.innerText.trim() : 'container not found';
        }
        return 'label not found';
    }""")
    print(f"Contacts text: {txt}")
    browser.close()
