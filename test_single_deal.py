"""Quick test: add contacts to one specific deal."""
import sys, logging, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, get_lead_details, add_lpr_contacts
import checko as checko_module
from checko import get_company_data, get_lpr_contacts

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

DEAL_ID = sys.argv[1] if len(sys.argv) > 1 else "1742889"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())
    login(page)

    details = get_lead_details(page, DEAL_ID)
    inn = details.get("inn", "").strip()
    print(f"INN: {inn}")

    company = get_company_data(inn)
    lpr = get_lpr_contacts(company)
    print(f"LPRs: {[(c['name'], c['role'], c.get('share_pct',''), c.get('inn','')) for c in lpr]}")

    if lpr:
        add_lpr_contacts(page, DEAL_ID, lpr)

    # Check result
    page.screenshot(path=f"/private/tmp/single_{DEAL_ID}.png")
    txt = page.evaluate("""() => {
        for (const lbl of document.querySelectorAll('.base-input__label-text')) {
            if (lbl.innerText.trim().toLowerCase() !== 'контакты') continue;
            const r = lbl.getBoundingClientRect();
            if (r.width < 5 || r.height < 5) continue;
            return lbl.closest('.base-input')?.innerText?.trim() || '';
        }
        return 'not found';
    }""")
    print(f"Contacts field: {txt}")
    browser.close()
