"""
test_add_contacts.py — test adding LPR contacts to 5 leads already in "Парсю".

Workflow per lead:
  1. Open deal → get INN
  2. Query Checko for director + founders
  3. Call add_lpr_contacts() to add each person to the "Контакты" field
"""

import logging
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from brizo import login, get_lead_details, add_lpr_contacts, reject_lead, _open_deal, _wait_for_kanban, _get_api_session
import checko as checko_module
from checko import get_company_data, get_lpr_contacts

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("test_contacts")

BRIZO_URL            = "https://sad1.brizo.ru"
PARSY_COL            = "Парсю"
LIMIT                = 60   # target: process up to 60 deals WITHOUT contacts
SCAN_LIMIT           = 500  # scan up to this many deals to find LIMIT without contacts
SERAFIMOVA_ID        = 50738  # responsible_id for Ника Серафимова
REASON_NO_KD         = "Нет КД"


def check_deal(deal_id: str) -> tuple[bool, bool]:
    """Return (is_nika_responsible, has_contacts) with a single API call."""
    sess = _get_api_session()
    if not sess:
        return False, False
    try:
        r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=10)
    except Exception:
        return False, False
    if r.status_code != 200:
        return False, False
    d = r.json()
    return d.get("responsible_id") == SERAFIMOVA_ID, bool(d.get("contragents"))


def get_leads_from_parsy(page, limit: int = 5) -> list[dict]:
    """Collect first `limit` lead IDs from the 'Парсю' column (virtual scroll)."""
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
        new = 0
        for item in batch:
            if item["id"] not in seen:
                seen.add(item["id"])
                leads.append({"id": item["id"], "name": item["name"]})
                new += 1
                if len(leads) >= limit:
                    break
        empty = 0 if new else empty + 1
        page.evaluate(js_scroll, 600)
        time.sleep(0.8)

    log.info("Found %d leads in '%s'", len(leads), PARSY_COL)
    return leads[:limit]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page    = context.new_page()
        checko_page = context.new_page()
        checko_module.set_pw_page(checko_page)

        try:
            log.info("Logging in…")
            login(page)

            log.info("Scanning up to %d leads from '%s' for Ника Серафимова's deals without contacts…", SCAN_LIMIT, PARSY_COL)
            all_leads = get_leads_from_parsy(page, SCAN_LIMIT)

            # Keep only deals where Ника Серафимова is responsible AND there are no contacts yet
            leads = []
            for candidate in all_leads:
                is_mine, has_contacts = check_deal(candidate["id"])
                if not is_mine:
                    log.info("Deal %s — не Никин лид, пропускаем", candidate["id"])
                elif has_contacts:
                    log.info("Deal %s — уже есть контакты, пропускаем", candidate["id"])
                else:
                    leads.append(candidate)
                if len(leads) >= LIMIT:
                    break

            log.info("Found %d Ника's deals without contacts to process", len(leads))
            if not leads:
                log.info("No unprocessed leads in '%s'. Exiting.", PARSY_COL)
                return

            for lead in leads:
                lead_id = lead["id"]
                name    = lead["name"]
                log.info("─" * 60)
                log.info("Lead #%s  «%s»", lead_id, name)

                details = get_lead_details(page, lead_id)
                inn = (
                    details.get("inn")
                    or details.get("инн компании")
                    or ""
                ).strip()
                log.info("  INN: %s", inn or "NOT FOUND")

                if not inn:
                    log.warning("  Skipping — no INN in deal card")
                    continue

                # --- Checko lookup ---
                company = get_company_data(inn)
                lpr = []

                if company:
                    lpr = get_lpr_contacts(company)
                    log.info("  LPRs from Checko: %s",
                             [(c["name"], c["role"]) for c in lpr] or "none found")
                else:
                    log.warning("  Checko returned no data for INN %s", inn)

                # --- Fallback: use deal card fields when Checko has no LPR ---
                if not lpr:
                    card_contact = details.get("contact_name", "").strip()
                    card_inn     = details.get("inn_director", "").strip()
                    if card_contact:
                        log.info("  No LPR from Checko — using card contact '%s'", card_contact)
                        lpr = [{"name": card_contact, "role": "Генеральный директор",
                                "inn": card_inn, "share_pct": ""}]
                    else:
                        log.warning("  No LPR and no card contact → Проиграно '%s'", REASON_NO_KD)
                        reject_lead(page, lead_id, REASON_NO_KD)
                        time.sleep(1.0)
                        continue

                add_lpr_contacts(page, lead_id, lpr)
                time.sleep(1.5)

        except Exception as exc:
            log.error("Fatal error: %s", exc, exc_info=True)
        finally:
            browser.close()

    log.info("Done.")


if __name__ == "__main__":
    main()
