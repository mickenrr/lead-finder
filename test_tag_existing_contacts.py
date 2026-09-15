"""test_tag_existing_contacts.py
For deals already in 'Парсю', get their linked contacts via GET /api/deals/{id},
match by name to checko LPRs, and assign each person's INN as a Метки tag.
"""
import logging, sys, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from brizo import (
    login, get_lead_details, _wait_for_kanban,
    _get_api_session, _post_contact_comment,
    BRIZO_URL,
)
import checko as checko_module
from checko import get_company_data, get_lpr_contacts

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tag_contacts")

PARSY_COL = "Парсю"
LIMIT = 10


def get_leads_from_parsy(page, limit: int) -> list[dict]:
    if "/cabinet/deals" not in page.url:
        page.goto(f"{BRIZO_URL}/cabinet/deals", timeout=30_000)
    _wait_for_kanban(page)

    seen: set[str] = set()
    leads: list[dict] = []

    js_collect = f"""() => {{
        let col = null;
        for (const c of document.querySelectorAll('.dnd__column')) {{
            if (c.innerText.trim().startsWith('{PARSY_COL}')) {{ col = c; break; }}
        }}
        if (!col) return [];
        const out = [];
        for (const card of col.querySelectorAll('a.kanban-card-deal')) {{
            const titleEl = card.querySelector('.kanban-card-deal__title');
            const title   = titleEl ? titleEl.innerText.trim() : '';
            const href    = card.getAttribute('href') || '';
            const m       = href.match(/deal\\/(\\d+)/);
            if (m) out.push({{id: m[1], name: title}});
        }}
        return out;
    }}"""

    js_scroll = f"""(step) => {{
        for (const c of document.querySelectorAll('.dnd__column')) {{
            if (c.innerText.trim().startsWith('{PARSY_COL}')) {{
                function findScroll(el) {{
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 10) return el;
                    for (const ch of el.children) {{
                        const f = findScroll(ch);
                        if (f) return f;
                    }}
                    return null;
                }}
                const sc = findScroll(c) || c;
                sc.scrollTop += step;
                return sc.scrollTop;
            }}
        }}
        return null;
    }}"""

    empty = 0
    while empty < 4 and len(leads) < limit:
        batch = page.evaluate(js_collect)
        new_count = 0
        for item in batch:
            if item["id"] not in seen:
                seen.add(item["id"])
                leads.append({"id": item["id"], "name": item["name"]})
                new_count += 1
                if len(leads) >= limit:
                    break
        empty = 0 if new_count else empty + 1
        page.evaluate(js_scroll, 600)
        time.sleep(0.8)

    return leads[:limit]


def get_deal_contacts(deal_id: str) -> dict[str, str]:
    """Return {contact_name: contragent_id} from GET /api/deals/{id}."""
    sess = _get_api_session()
    if not sess:
        return {}
    r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=10)
    if r.status_code != 200:
        log.warning("  GET /api/deals/%s → %s", deal_id, r.status_code)
        return {}
    contacts = {}
    for c in r.json().get("contragents", []):
        cid = str(c.get("id", ""))
        name = (c.get("name") or "").strip()
        if cid and name:
            contacts[name] = cid
    return contacts


def find_cid(lpr_name: str, deal_contacts: dict[str, str]) -> str | None:
    """Exact or fuzzy match of lpr_name against deal contacts dict."""
    # exact
    if lpr_name in deal_contacts:
        return deal_contacts[lpr_name]
    # all words present
    words = lpr_name.strip().lower().split()
    for dname, did in deal_contacts.items():
        if all(w in dname.lower() for w in words):
            log.info("  Fuzzy match: '%s' → '%s'", lpr_name, dname)
            return did
    return None



def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = ctx.new_page()
        checko_module.set_pw_page(ctx.new_page())

        try:
            login(page)

            leads = get_leads_from_parsy(page, LIMIT)
            log.info("Found %d leads in '%s'", len(leads), PARSY_COL)

            tagged = already = skipped = not_found = 0

            for lead in leads:
                lead_id = lead["id"]
                log.info("─" * 55)
                log.info("Deal %s: %s", lead_id, lead["name"])

                # Company INN from deal page fields
                details = get_lead_details(page, lead_id)
                inn = (details.get("inn") or details.get("инн компании") or "").strip()
                if not inn:
                    log.warning("  No INN in deal — skip")
                    skipped += 1
                    continue
                log.info("  Company INN: %s", inn)

                # Existing contacts in this deal (name → contragent_id)
                deal_contacts = get_deal_contacts(lead_id)
                if not deal_contacts:
                    log.warning("  No contacts linked to deal — skip")
                    skipped += 1
                    continue
                log.info("  Contacts in deal: %s", list(deal_contacts.keys()))

                # LPR data from checko (with personal INNs)
                company = get_company_data(inn)
                if not company:
                    log.warning("  Checko returned nothing — skip")
                    skipped += 1
                    continue
                lpr = get_lpr_contacts(company)
                if not lpr:
                    log.warning("  No LPRs found in checko — skip")
                    skipped += 1
                    continue

                for contact in lpr:
                    lpr_inn = contact.get("inn", "").strip()
                    name = contact.get("name", "")

                    cid = find_cid(name, deal_contacts)
                    if not cid:
                        log.warning("  '%s' not linked to this deal — not found", name)
                        not_found += 1
                        continue

                    if lpr_inn:
                        _post_contact_comment(cid, lpr_inn)
                        tagged += 1
                    else:
                        log.info("  '%s' has no INN on Checko — comment skipped", name)
                        skipped += 1

        except Exception as exc:
            log.error("Fatal: %s", exc, exc_info=True)
        finally:
            browser.close()

    log.info("═" * 55)
    log.info("Done. Processed: %d  Not found: %d  Skipped: %d",
             tagged, not_found, skipped)


if __name__ == "__main__":
    main()
