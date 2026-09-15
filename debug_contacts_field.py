"""Debug script: inspect the 'Контакты' field structure in a deal."""
import logging, sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, _open_deal, _wait_for_kanban
import checko as checko_module

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("debug")

BRIZO_URL = "https://sad1.brizo.ru"
# One lead from Парсю that we know exists
TEST_LEAD_ID = "1742889"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = ctx.new_page()
        checko_page = ctx.new_page()
        checko_module.set_pw_page(checko_page)

        login(page)
        _open_deal(page, TEST_LEAD_ID)
        time.sleep(2)

        # ── 1. Dump the Контакты container HTML + children ────────────────
        result = page.evaluate("""() => {
            for (const lbl of document.querySelectorAll('.base-input__label-text')) {
                if (lbl.innerText.trim() !== 'Контакты') continue;
                const container = lbl.closest('.base-input');
                if (!container) return {found: false};

                // Scroll into view
                lbl.scrollIntoView({behavior: 'instant', block: 'center'});

                // Get all children info
                const allEls = [];
                for (const el of container.querySelectorAll('*')) {
                    const r = el.getBoundingClientRect();
                    const tag = el.tagName;
                    const cls = (el.className || '').toString().slice(0,80);
                    const txt = (el.innerText || el.textContent || '').trim().slice(0,60);
                    const role = el.getAttribute('role') || '';
                    allEls.push({tag, cls, txt, role,
                                 x: Math.round(r.left + r.width/2),
                                 y: Math.round(r.top + r.height/2),
                                 w: Math.round(r.width), h: Math.round(r.height)});
                }

                // Container HTML (first 2000 chars)
                const html = container.outerHTML.slice(0, 2000);
                const lblR = lbl.getBoundingClientRect();
                const cR = container.getBoundingClientRect();

                return {
                    found: true,
                    containerCls: container.className,
                    html: html,
                    labelY: Math.round(lblR.top + lblR.height/2),
                    containerY: Math.round(cR.top + cR.height/2),
                    containerH: Math.round(cR.height),
                    allEls: allEls,
                };
            }
            return {found: false, reason: 'label not found'};
        }""")

        log.info("Container class: %s", result.get("containerCls", ""))
        log.info("Label at y=%s, Container center y=%s, height=%s",
                 result.get("labelY"), result.get("containerY"), result.get("containerH"))
        log.info("HTML:\n%s", result.get("html", ""))
        log.info("All child elements:")
        for el in result.get("allEls", []):
            if el["w"] > 5 and el["h"] > 5:
                log.info("  %s  cls=%-50s  txt=%-40s  role=%s  x=%d y=%d w=%d h=%d",
                         el["tag"], el["cls"][:50], el["txt"][:40], el["role"],
                         el["x"], el["y"], el["w"], el["h"])

        time.sleep(0.5)

        # ── 2. Screenshot of just the Контакты area ───────────────────────
        page.screenshot(path="/private/tmp/brizo_contacts_area.png")
        log.info("Screenshot: /private/tmp/brizo_contacts_area.png")

        # ── 3. Click the Контакты field and see what happens ─────────────
        label_y = result.get("labelY", 800)
        container_y = result.get("containerY", 850)
        # Click below the label (in the field area)
        page.mouse.click(720, container_y)
        time.sleep(1.5)
        page.screenshot(path="/private/tmp/brizo_contacts_after_click.png")
        log.info("Screenshot after click: /private/tmp/brizo_contacts_after_click.png")

        # Dump what appeared
        after_click = page.evaluate("""() => {
            const btns = [];
            for (const el of document.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) continue;
                if (r.top < 0 || r.bottom > 1200) continue;
                const txt = (el.innerText || '').trim();
                if (!txt || txt.length > 50) continue;
                const cls = (el.className || '').toString();
                btns.push({tag: el.tagName, txt: txt.slice(0,50),
                           cls: cls.slice(0,80),
                           x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)});
            }
            return btns;
        }""")
        log.info("Elements after clicking Контакты area: (short text only)")
        for el in after_click:
            if any(k in el["txt"].lower() for k in ("создать", "добавить", "контакт", "new", "add")):
                log.info("  RELEVANT: %s", el)

        browser.close()
    log.info("Done.")

if __name__ == "__main__":
    main()
