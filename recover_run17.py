"""recover_run17.py — обрабатываем 20 лидов из run17 (ИНН теперь читается через API)."""

import logging
import sys
import time
import random
from collections import defaultdict

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from brizo import (
    login,
    get_lead_details,
    assign_to_me,
    move_to_stage,
    reject_lead,
    fill_checko_field,
    add_comment,
    add_lpr_contacts,
    _get_api_session,
    BRIZO_URL,
)
import checko as checko_module
from checko import get_company_data, get_lpr_contacts
from qualifier import qualify_company, check_site_for_production

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [brizo] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

STAGE_LOST    = "Проиграно"
STAGE_PARSING = "Парсю"
REASON_NO_WEBSITE = "Нет КД"

# Лиды из run17 — назначение ответственной уже сделано
RUN17_LEADS = [
    {"id": "1742291", "name": "ООО \"МАКСИМУМ\""},
    {"id": "1742295", "name": "АО \"ЮГСУ\""},
    {"id": "1742299", "name": "ОАО \"НИВА КУБАНИ\""},
    {"id": "1742301", "name": "ООО \"СХП ДМИТРИЕВСКОЕ\""},
    {"id": "1742304", "name": "ООО \"КФ КОМУС-УПАКОВКА\""},
    {"id": "1742306", "name": "ООО \"ЦЕНТРПЛАСТ\""},
    {"id": "1742307", "name": "ООО \"МАЛТАТ\""},
    {"id": "1742308", "name": "ООО \"ЦЕНТР ИНЖИНИРИНГА\""},
    {"id": "1742309", "name": "ООО \"КСК\""},
    {"id": "1742310", "name": "ООО \"СОДРУЖЕСТВО\""},
    {"id": "1742311", "name": "ООО \"ДАЛС\""},
    {"id": "1742312", "name": "ООО \"СНТ\""},
    {"id": "1742313", "name": "ООО \" СИГМА - С \""},
    {"id": "1742314", "name": "ООО \"КРАСНОЯРСКИНВЕСТ\""},
    {"id": "1742315", "name": "ООО \"КОЛОС\""},
    {"id": "1742288", "name": "ООО \"МЕМОРИАЛ\""},
    {"id": "1742286", "name": "ООО \"КУБАНЬСТРОЙМАРКЕТ\""},
    {"id": "1742285", "name": "ООО \"ИРБИС\""},
    {"id": "1742282", "name": "ООО \"КУБАНЬ-ДИАЛОГ\""},
    {"id": "1742281", "name": "ООО \"ОМЕГА\""},
]


def _pause(lo=1.0, hi=2.0):
    time.sleep(random.uniform(lo, hi))


def _fmt(v):
    return "нет данных" if v is None else f"{int(v):,}".replace(",", " ")


def _delete_inn_warning(lead_id: str) -> None:
    """Удаляем комментарий '⚠️ ИНН компании не найден' добавленный в run17."""
    sess = _get_api_session()
    if not sess:
        return
    try:
        rc = sess.get(f"{BRIZO_URL}/api/deals/{lead_id}/comments",
                      params={"limit": 20}, timeout=10)
        if rc.status_code != 200:
            return
        for c in rc.json().get("data", []):
            msg = (c.get("message") or "").strip()
            if "ИНН компании не найден" in msg:
                cid = c.get("id")
                rd = sess.delete(f"{BRIZO_URL}/api/deals/{lead_id}/comments/{cid}", timeout=10)
                if rd.status_code in (200, 204):
                    log.info("Deal %s: удалён комментарий 'ИНН не найден' ✓", lead_id)
                else:
                    log.warning("Deal %s: не удалось удалить комментарий %s: %s",
                                lead_id, cid, rd.status_code)
    except Exception as e:
        log.warning("Deal %s: ошибка при удалении комментария: %s", lead_id, e)


def process_lead(page, lead: dict, stats: dict) -> None:
    lead_id = str(lead["id"])
    name    = lead["name"]

    log.info("─" * 64)
    log.info("Лид #%s  «%s»", lead_id, name)
    stats["total"] += 1

    # Убираем ошибочный комментарий из run17
    _delete_inn_warning(lead_id)

    # Назначение ответственной (идемпотентно)
    _pause()
    assign_to_me(page, lead_id)

    # Получаем детали сделки (теперь через REST API)
    _pause()
    details = get_lead_details(page, lead_id)
    inn = details.get("inn", "").strip()

    if not inn:
        log.warning("  ИНН не найден даже через API — пропускаем")
        add_comment(page, lead_id, "⚠️ ИНН компании не найден в карточке сделки.")
        stats["errors"] += 1
        return

    log.info("  ИНН компании: %s", inn)

    # Сайт
    deal_website = details.get("website_field", "").strip()
    if not deal_website:
        log.info("  Поле «Сайт» пустое → Проиграно 'Нет КД'")
        _pause()
        reject_lead(page, lead_id, REASON_NO_WEBSITE)
        stats["rejected"][REASON_NO_WEBSITE] += 1
        return

    # ФИО контактного лица
    contact_name = details.get("contact_name", "").strip()
    if not contact_name:
        log.info("  ФИО контактного лица пустое → Проиграно 'Нет КД'")
        _pause()
        reject_lead(page, lead_id, REASON_NO_WEBSITE)
        stats["rejected"][REASON_NO_WEBSITE] += 1
        return

    # Целевой продукт
    log.info("  Проверяем целевой ли продукт: %s", deal_website)
    has_production = check_site_for_production(deal_website)
    if has_production:
        log.info("  Найдено собственное производство")
        _pause()
        add_comment(page, lead_id, "Подходит, уникальное производство")

    # Checko
    log.info("  Запрашиваем Чекко для ИНН %s", inn)
    company = get_company_data(inn)

    if not company:
        log.warning("  Чекко вернул пустой ответ")
        add_comment(page, lead_id, f"⚠️ Нет данных в Чекко для ИНН {inn}.")
        stats["errors"] += 1
        return

    checko_url = company.get("checko_url", "")
    log.info("  Чекко: выручка=%s  налог_3года=%s",
             _fmt(company.get("revenue")), company.get("income_tax_amounts"))

    if checko_url:
        _pause()
        fill_checko_field(page, lead_id, checko_url)

    # Квалификация
    passed, reason = qualify_company(company)
    log.info("  Квалификация: %s (%s)", "✓ Подходит" if passed else "✗ Не подходит", reason)

    if not passed:
        _pause()
        reject_lead(page, lead_id, reason)
        stats["rejected"][reason] += 1
        return

    stats["qualified"] += 1

    # Перемещаем в Парсю
    _pause()
    move_to_stage(page, lead_id, STAGE_PARSING)
    log.info("  → Парсю ✓")

    # ЛПРы
    lpr_contacts = get_lpr_contacts(company)
    log.info("  ЛПРы: %s", [(c["name"], c["role"]) for c in lpr_contacts] or "не найдены")
    if lpr_contacts:
        _pause(0.5, 1.0)
        add_lpr_contacts(page, lead_id, lpr_contacts)


def main():
    stats: dict = {
        "total": 0, "qualified": 0, "non_target": 0, "errors": 0,
        "rejected": defaultdict(int),
    }

    log.info("═" * 64)
    log.info("  RECOVER run17 — %d лидов", len(RUN17_LEADS))
    log.info("═" * 64)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-software-rasterizer",
                  "--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        def _block(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block)

        checko_page = context.new_page()
        checko_page.route("**", _block)
        checko_module.set_pw_page(checko_page)

        try:
            login(page)
            for lead in RUN17_LEADS:
                try:
                    process_lead(page, lead, stats)
                except PlaywrightTimeout as exc:
                    log.error("Playwright timeout для лида %s: %s", lead["id"], exc)
                    stats["errors"] += 1
                except Exception as exc:
                    log.error("Ошибка для лида %s: %s", lead["id"], exc, exc_info=True)
                    stats["errors"] += 1
                finally:
                    _pause(1.5, 2.5)
        except Exception as exc:
            log.critical("Критическая ошибка: %s", exc, exc_info=True)
        finally:
            browser.close()

    total      = stats["total"]
    qualified  = stats["qualified"]
    no_kd      = stats["rejected"].get("Нет КД", 0)
    low_tax    = stats["rejected"].get("Маленькая выручка/мало налогов", 0)
    errors     = stats["errors"]
    non_target = stats["non_target"]
    other_rej  = sum(v for k, v in stats["rejected"].items()
                     if k not in ("Нет КД", "Маленькая выручка/мало налогов"))

    lines = [
        "", "═" * 55, "  СТАТИСТИКА (recover run17)", "═" * 55,
        f"  Обработано всего              : {total}",
        f"  → Парсю (прошли квалиф.)      : {qualified}",
        f"  🚫 Нецелевой (комментарий)    : {non_target}",
        f"  ❌ Нет КД → Проиграно          : {no_kd}",
        f"  ❌ Мало налогов → Проиграно    : {low_tax}",
    ]
    if other_rej:
        lines.append(f"  ❌ Иные отказы                 : {other_rej}")
    if errors:
        lines.append(f"  ⚠️  Ошибок (пропущено)          : {errors}")
    lines.append("═" * 55)
    output = "\n".join(lines)
    log.info(output)
    print(output)


if __name__ == "__main__":
    main()
