"""add_phones.py — Add phones to LPR contacts in «Парсю» via @pupupu_555_bot.

Run AFTER the main parser has processed and you've manually reviewed the deals:
    python3 add_phones.py
    python3 app_phones.py   ← web UI
"""

import concurrent.futures
import json as _json
import logging
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from brizo import _get_api_session, BRIZO_URL, MY_USER_ID, add_phones_to_contact

PARSYU_STATUS_ID = 168873
PAGE_SIZE = 100
MIN_FOUNDER_SHARE = 20  # учредителей с долей < 20% пропускаем — они не ЛПР


def _emit(event_type: str, **kwargs) -> None:
    print(f"PIPELINE_EVENT:{_json.dumps({'type': event_type, **kwargs})}", flush=True)


def _get_parsyu_deals() -> list[dict]:
    """Return all deals in «Парсю» where responsible is Ника (MY_USER_ID)."""
    sess = _get_api_session()
    if not sess:
        log.error("No API session — check .env credentials")
        return []

    deals: list[dict] = []
    offset = 0

    while True:
        r = sess.get(
            f"{BRIZO_URL}/api/funnels/21480/deals/table",
            params={
                "statuses[0]": PARSYU_STATUS_ID,
                "limit": PAGE_SIZE,
                "offset": offset,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("data", [])
        if not batch:
            break

        for deal in batch:
            # API returns flat dot-notation keys: "responsible.id", "responsible.name"
            resp_id = deal.get("responsible.id")
            if resp_id == MY_USER_ID:
                deals.append({"id": str(deal["id"]), "name": deal.get("name", "")})

        total = data.get("meta", {}).get("overal_count", 0)
        offset += len(batch)
        if offset >= total:
            break

    log.info("Found %d Парсю deals for Ника Серафимова", len(deals))
    return deals


def _get_contacts_without_phones(deal_id: str) -> tuple[list[dict], int]:
    """Return (contacts_without_phones, skipped_count) for this deal."""
    sess = _get_api_session()
    if not sess:
        return [], 0

    r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}/contragents", timeout=10)
    if not r.ok:
        log.warning("GET /api/deals/%s/contragents → %s", deal_id, r.status_code)
        return [], 0

    result = []
    skipped = 0
    for c in r.json().get("data", []):
        name   = c.get("name", "")
        phones = c.get("phones") or []

        # Пропускаем учредителей с долей < MIN_FOUNDER_SHARE%
        m = re.search(r'учред\s+(\d+)%', name, re.IGNORECASE)
        if m and int(m.group(1)) < MIN_FOUNDER_SHARE:
            log.info("  Contact %s (%s): учред %s%% < %d%% — skip",
                     c["id"], name, m.group(1), MIN_FOUNDER_SHARE)
            skipped += 1
            continue

        if phones:
            log.info("  Contact %s (%s): already has %d phone(s) — skip",
                     c["id"], name, len(phones))
            skipped += 1
        else:
            result.append({"id": str(c["id"]), "name": name})
    return result, skipped


def _get_inn_from_comments(contact_id: str) -> str:
    """Read INN from contact comments (the parser posts it as bare digits)."""
    sess = _get_api_session()
    if not sess:
        return ""

    r = sess.get(
        f"{BRIZO_URL}/api/contragents/{contact_id}/comments",
        params={"order_by": "asc", "limit": 50},
        timeout=10,
    )
    if not r.ok:
        return ""

    for comment in r.json().get("data", []):
        text = (comment.get("message") or "").strip()
        if text.isdigit() and len(text) in (10, 12):
            return text
    return ""


def _get_all_deal_inns(deal_id: str) -> list[str]:
    """Return INN list for all contacts in this deal (from comments).
    Used to filter INN-derived false phone numbers across co-founders/directors.
    """
    sess = _get_api_session()
    if not sess:
        return []
    r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}/contragents", timeout=10)
    if not r.ok:
        return []
    inns = []
    for c in r.json().get("data", []):
        cid = str(c.get("id", ""))
        if not cid:
            continue
        r2 = sess.get(
            f"{BRIZO_URL}/api/contragents/{cid}/comments",
            params={"order_by": "asc", "limit": 50},
            timeout=10,
        )
        if not r2.ok:
            continue
        for comment in r2.json().get("data", []):
            text = (comment.get("message") or "").strip()
            if text.isdigit() and len(text) in (10, 12):
                if text not in inns:
                    inns.append(text)
                break
    return inns


def _lookup_and_add(contact_id: str, name: str, inn: str,
                    block_inns: list[str] | None = None) -> str:
    """Query @pupupu_555_bot for phones. Returns status: added|no_inn|no_phones|error."""
    if not inn:
        log.info("  Contact %s (%s): no INN in comments — skip", contact_id, name)
        return "no_inn"

    log.info("  Ищем телефоны для «%s» (ИНН %s)…", name, inn)
    try:
        from tg_bot import get_phones_for_inn
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            phones = ex.submit(get_phones_for_inn, inn, block_inns).result(timeout=120)
    except ImportError:
        log.error("tg_bot.py not found — cannot look up phones")
        return "error"
    except Exception as e:
        log.warning("  TG lookup failed for «%s» (INN %s): %s", name, inn, e)
        return "error"

    if not phones:
        log.info("  Телефоны не найдены для ИНН %s", inn)
        return "no_phones"

    log.info("  Найдено %d телефонов → добавляем в контакт %s", len(phones), contact_id)
    add_phones_to_contact(contact_id, phones)
    return "added"


def main(limit: int = 0, offset: int = 0) -> None:
    if not Path("tg_profile").exists():
        log.error("TG profile не настроен. Сначала запустите setup_tg.py.")
        sys.exit(1)

    log.info("═" * 60)
    log.info("  ADD PHONES — Парсю → Ника Серафимова%s%s",
             f"  (offset: {offset})" if offset else "",
             f"  (лимит: {limit})" if limit else "")
    log.info("═" * 60)

    deals = _get_parsyu_deals()
    if not deals:
        log.info("Сделок не найдено.")
        _emit("total_deals", total=0)
        return

    if offset:
        deals = deals[offset:]
    if limit:
        deals = deals[:limit]

    _emit("total_deals", total=len(deals))

    total_added = 0
    total_skipped = 0
    total_no_inn = 0
    total_no_phones = 0

    for num, deal in enumerate(deals, 1):
        log.info("─" * 60)
        log.info("Сделка %d/%d  #%s  «%s»", num, len(deals), deal["id"], deal["name"])
        _emit("deal_start", num=num, total=len(deals), deal_id=deal["id"], name=deal["name"])

        contacts, skipped_count = _get_contacts_without_phones(deal["id"])
        total_skipped += skipped_count

        if not contacts and skipped_count == 0:
            log.info("  Нет контактов")
            _emit("deal_done", num=num, deal_id=deal["id"], added=0, skipped=0, no_inn=0, no_phones=0)
            continue

        # Собираем ИНН всех контактов сделки — передаём в фильтр тг_бота
        # чтобы исключить ИНН-артефакты от ДРУГИХ ЛПРов (соучредители, гендир)
        deal_all_inns = _get_all_deal_inns(deal["id"])
        log.info("  ИНН всех ЛПРов сделки для фильтра: %s", deal_all_inns)

        deal_added = 0
        deal_no_inn = 0
        deal_no_phones = 0

        for ct in contacts:
            inn = _get_inn_from_comments(ct["id"])
            status = _lookup_and_add(ct["id"], ct["name"], inn, block_inns=deal_all_inns)
            _emit("contact_done",
                  deal_id=deal["id"],
                  contact_id=ct["id"],
                  name=ct["name"],
                  inn=inn,
                  status=status)
            if status == "added":
                deal_added += 1
                total_added += 1
            elif status == "no_inn":
                deal_no_inn += 1
                total_no_inn += 1
            elif status == "no_phones":
                deal_no_phones += 1
                total_no_phones += 1

        _emit("deal_done", num=num, deal_id=deal["id"],
              added=deal_added, skipped=skipped_count,
              no_inn=deal_no_inn, no_phones=deal_no_phones)

    log.info("═" * 60)
    log.info("  ГОТОВО  |  добавлено=%d  уже есть=%d  нет ИНН=%d  нет телефонов=%d",
             total_added, total_skipped, total_no_inn, total_no_phones)
    log.info("═" * 60)
    _emit("finished", added=total_added, skipped=total_skipped,
          no_inn=total_no_inn, no_phones=total_no_phones)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="Обработать не более N сделок (0 = все)")
    ap.add_argument("--offset", type=int, default=0, metavar="N",
                    help="Пропустить первые N сделок")
    args = ap.parse_args()
    main(limit=args.limit, offset=args.offset)
