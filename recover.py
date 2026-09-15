"""recover.py — Re-process leads that failed Checko lookup, using direct URLs."""

import logging
import random
import sys
import time

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from brizo import (
    login,
    get_lead_details,
    assign_to_me,
    move_to_stage,
    reject_lead,
    fill_checko_field,
    add_lpr_contacts,
)
import checko as checko_module
from checko import get_company_data_from_url, get_lpr_contacts
from qualifier import qualify_company

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

STAGE_PARSING = "Парсю"

# Leads that failed Checko lookup + their known Checko URLs.
# nontarget_done=True means "Нецелевой" comment was already added in the previous run.
RECOVERY_LEADS = [
    {
        "id": "1742324",
        "name": "ИНТЕРКАБЕЛЬ",
        "checko_url": "https://checko.ru/company/interkabel-1072536002660",
        "nontarget_done": False,
    },
    {
        "id": "1742326",
        "name": "ТЕХНОСТАЙЛ",
        "checko_url": "https://checko.ru/company/tekhnostayl-1072540009376",
        "nontarget_done": False,
    },
    {
        "id": "1742329",
        "name": "СТРОЙАГРО",
        "checko_url": "https://checko.ru/company/stroyagro-1072635007158",
        "nontarget_done": True,  # "Нецелевой" comment already added
    },
    {
        "id": "1742342",
        "name": "УКЖКХ СЕРВИС-ЦЕНТР",
        "checko_url": "https://checko.ru/company/ukzhkh-servis-centr-1072721019018",
        "nontarget_done": False,
    },
    {
        "id": "1742381",
        "name": "АМБРЭНДО",
        "checko_url": "https://checko.ru/company/ambrehndo-1073667028764",
        "nontarget_done": False,
    },
]


def _pause(lo: float = 1.0, hi: float = 2.0) -> None:
    time.sleep(random.uniform(lo, hi))


def _fmt(value) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ")


def process_recovery_lead(page, lead: dict) -> None:
    lead_id = lead["id"]
    name = lead["name"]
    checko_url = lead["checko_url"]

    log.info("─" * 64)
    log.info("RECOVERY Лид #%s  «%s»", lead_id, name)

    # a. Assign to me
    _pause()
    assign_to_me(page, lead_id)

    # b. Get INN from deal details
    _pause()
    details = get_lead_details(page, lead_id)
    inn = (
        details.get("inn")
        or details.get("инн компании")
        or ""
    ).strip()
    log.info("  ИНН: %s", inn)

    # c. Fetch Checko data from the provided URL directly
    log.info("  Checko URL: %s", checko_url)
    _pause()
    company = get_company_data_from_url(checko_url, inn=inn)

    if not company:
        log.error("  Не удалось получить данные с Checko — пропускаем")
        return

    log.info(
        "  Чекко: выручка=%s  налог_3года=%s",
        _fmt(company.get("revenue")),
        company.get("income_tax_amounts"),
    )

    # d. Fill the Checko field in Brizo
    _pause()
    fill_checko_field(page, lead_id, checko_url)

    # e. Financial qualification
    passed, reason = qualify_company(company)
    log.info("  Квалификация: %s  (%s)", "✓ Подходит" if passed else "✗ Не подходит", reason)

    if not passed:
        _pause()
        reject_lead(page, lead_id, reason)
        log.info("  → Проиграно (%s)", reason)
        return

    # f. Move to Парсю
    _pause()
    move_to_stage(page, lead_id, STAGE_PARSING)
    log.info("  → Парсю ✓")

    # g. Add LPR contacts
    lpr_contacts = get_lpr_contacts(company)
    log.info(
        "  ЛПРы: %s",
        [(c["name"], c["role"]) for c in lpr_contacts] or "не найдены",
    )
    if lpr_contacts:
        _pause(0.5, 1.0)
        add_lpr_contacts(page, lead_id, lpr_contacts)


def main() -> None:
    log.info("═" * 64)
    log.info("  RECOVERY — %d лидов", len(RECOVERY_LEADS))
    log.info("═" * 64)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        def _block_analytics(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block_analytics)

        checko_page = context.new_page()
        checko_page.route("**", _block_analytics)
        checko_module.set_pw_page(checko_page)

        try:
            login(page)
            for lead in RECOVERY_LEADS:
                try:
                    process_recovery_lead(page, lead)
                except PlaywrightTimeout as exc:
                    log.error("Playwright timeout для лида %s: %s", lead["id"], exc)
                except Exception as exc:
                    log.error("Ошибка для лида %s: %s", lead["id"], exc, exc_info=True)
                finally:
                    _pause(1.5, 2.5)
        except Exception as exc:
            log.critical("Критическая ошибка: %s", exc, exc_info=True)
        finally:
            browser.close()

    log.info("═" * 64)
    log.info("  RECOVERY ЗАВЕРШЁН")
    log.info("═" * 64)


if __name__ == "__main__":
    main()
