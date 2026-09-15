"""
fix_checko_errors.py — Ручная обработка сделок с ошибкой «Не найдено в Чекко».

Находит все сделки в «База» с комментарием «Не найдено в Чекко»,
где ответственная — Ника Серафимова, и обрабатывает их по полному пайплайну:
  с. Проверка сайта/почты
  d. Поиск на Checko
  e. Заполнить поле Чекко
  f. ОКВЭД / финансовая квалификация
  g. Комментарий с часовым поясом
  i. Добавление ЛПРов

НЕ изменяет parser/main.py, brizo.py, checko.py, qualifier.py.
"""

import sys, os, re, time, random, logging
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from playwright.sync_api import sync_playwright

import brizo as brizo_module
from brizo import (
    _get_api_session, _ensure_bearer,
    BRIZO_URL, MY_USER_ID, MY_NAME, BASE_STATUS_ID,
    get_lead_details, reject_lead, add_comment, fill_checko_field,
    add_lpr_contacts, check_duplicate_by_inn,
    login,
)
import checko as checko_module
from checko import (
    get_company_data, get_company_data_from_url, get_lpr_contacts,
    get_timezone_comment,
)
from qualifier import qualify_company, check_okved_skolkovo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [fix] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fix")

REASON_NO_WEBSITE  = "Нет КД"
REASON_TOO_BIG     = "Интересные, но ярд"
REASON_LOW_TAX     = "Маленькая выручка/мало налогов"
REASON_NON_TARGET  = "Нецелевой"


def _pause(lo=1.0, hi=2.0):
    time.sleep(random.uniform(lo, hi))


def _fmt(value) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ")


def find_error_deals(sess) -> list[dict]:
    """Находит все сделки в «База» с ответственной Ника + комментарий «Не найдено в Чекко»."""
    log.info("Поиск сделок с ошибкой Чекко в колонке «База»...")
    error_deals = []

    # Диапазон offset для поиска наших сделок.
    # Новые лиды (1792xxx, 1793xxx) — в начале списка (малый offset).
    # Более старые сделки — глубже.
    scan_ranges = [
        (0,     2000),    # самые новые лиды (1792xxx+)
        (24800, 26600),   # ID 1793xxx (предыдущая крупная сессия)
        (20000, 24800),   # ID 1790xxx-1793xxx (ранние прогоны)
    ]

    seen_ids = set()
    candidates = []

    for start, end in scan_ranges:
        for offset in range(start, end, 20):
            r = sess.get(f"{BRIZO_URL}/api/deals", params={"offset": offset}, timeout=10)
            if r.status_code != 200:
                continue
            items = r.json().get('data', [])
            for it in items:
                if (it.get('responsible_id') == MY_USER_ID
                        and it.get('status_id') == BASE_STATUS_ID
                        and it['id'] not in seen_ids):
                    seen_ids.add(it['id'])
                    candidates.append(it)

    log.info("Кандидаты (Ника + База): %d сделок", len(candidates))

    for deal in candidates:
        deal_id = deal['id']
        rc = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}/comments", timeout=10)
        if rc.status_code != 200:
            continue
        comments = rc.json().get('data', [])
        for c in comments:
            msg = c.get('message', '') or c.get('text', '') or ''
            if 'Не найдено в Чекко' in msg:
                inn_m = re.search(r'ИНН\s+(\d{10,12})', msg)
                inn = inn_m.group(1) if inn_m else ''
                error_deals.append({
                    'id': deal_id,
                    'name': deal.get('name', ''),
                    'inn': inn,
                })
                log.info("  ⚠️  #%s %s  INN=%s", deal_id, deal.get('name', '')[:40], inn)
                break

    return error_deals


def process_error_deal(page, sess, deal: dict, stats: dict):
    """Обрабатывает одну сделку с ошибкой Чекко по полному пайплайну."""
    deal_id = str(deal['id'])
    name    = deal.get('name', deal_id)
    inn_from_comment = deal.get('inn', '')

    log.info("─" * 64)
    log.info("Обрабатываем #%s  «%s»  INN=%s", deal_id, name, inn_from_comment)

    # Проверяем что сделка всё ещё в «База» и ответственная всё ещё Ника
    rd = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=10)
    if rd.status_code != 200:
        log.warning("  Не удалось получить сделку #%s — пропускаем", deal_id)
        stats['errors'] += 1
        return

    deal_data = rd.json()
    if deal_data.get('status_id') != BASE_STATUS_ID:
        log.info("  Сделка #%s уже не в «База» (status=%s) — пропускаем", deal_id, deal_data.get('status_id'))
        stats['skipped'] += 1
        return
    if deal_data.get('responsible_id') != MY_USER_ID:
        log.info("  Ответственная сменилась для #%s — пропускаем", deal_id)
        stats['skipped'] += 1
        return

    # ── b. Получить детали сделки ─────────────────────────────────────────
    _pause(0.5, 1.0)
    details = get_lead_details(page, deal_id)
    inn = (details.get('inn') or inn_from_comment).strip()

    if not inn:
        log.warning("  ИНН не найден в карточке и комментарии — пропускаем #%s", deal_id)
        stats['errors'] += 1
        return

    log.info("  ИНН: %s", inn)

    # ── c. Проверить наличие сайта и почты ───────────────────────────────
    deal_website = details.get('website_field', '').strip()
    deal_email   = details.get('email_field', '').strip()
    if not deal_website and not deal_email:
        log.info("  Нет сайта и почты → Проиграно 'Нет КД'")
        _pause()
        reject_lead(page, deal_id, REASON_NO_WEBSITE)
        stats['rejected'][REASON_NO_WEBSITE] += 1
        return

    log.info("  Сайт: %r  Почта: %r", deal_website[:40] if deal_website else '', deal_email[:40] if deal_email else '')

    # ── d. Получить данные из Чекко ──────────────────────────────────────
    existing_checko = details.get('checko_url_field', '').strip()
    log.info("  Запрашиваем Чекко для ИНН %s", inn)

    if existing_checko:
        company = get_company_data_from_url(existing_checko, inn)
    else:
        company = get_company_data(inn)

    if not company:
        log.warning("  Компания НЕ найдена на Чекко — оставляем в «База» без изменений")
        stats['errors'] += 1
        return

    checko_url = company.get('checko_url', '')
    revenue    = company.get('revenue')
    income_tax = company.get('income_tax_amounts') or []

    log.info("  Чекко: выручка=%s  налог=%s",
             _fmt(revenue), [_fmt(t) for t in income_tax[:3]])

    # ── d.5. ОКВЭД → Сколково ────────────────────────────────────────────
    okved_codes = company.get('okved_codes', [])
    log.info("  ОКВЭД: %s", okved_codes[:5])
    skolkovo = check_okved_skolkovo(okved_codes)
    log.info("  Сколково: %s", "Подходит" if skolkovo else "Нецелевой")

    if not skolkovo:
        _pause()
        reject_lead(page, deal_id, REASON_NON_TARGET)
        stats['rejected'][REASON_NON_TARGET] += 1
        return

    # ── e. Заполнить ссылку Чекко ────────────────────────────────────────
    if checko_url and not existing_checko:
        log.info("  Заполняем поле Чекко: %s", checko_url)
        _pause(0.5, 1.0)
        fill_checko_field(page, deal_id, checko_url)

    # ── f. Финансовая квалификация ────────────────────────────────────────
    passed, reason = qualify_company(company)
    log.info("  Квалификация: %s (%s)", "✓ Подходит" if passed else "✗ Не подходит", reason)

    if not passed:
        _pause()
        reject_lead(page, deal_id, reason)
        stats['rejected'][reason] += 1
        return

    stats['qualified'] += 1

    # ── f.5. Дубли ───────────────────────────────────────────────────────
    if check_duplicate_by_inn(inn, deal_id):
        log.info("  Найден дубль по ИНН %s", inn)
        add_comment(page, deal_id, "Есть дубль")

    # ── g. Часовой пояс ──────────────────────────────────────────────────
    legal_address = company.get('legal_address', '')
    tz_comment = get_timezone_comment(legal_address)
    log.info("  Адрес: %s → %s", legal_address[:60] if legal_address else 'не найден', tz_comment)
    _pause(0.3, 0.7)
    add_comment(page, deal_id, tz_comment)

    # ── h. Не перемещаем в «Парсю» — остаётся в «База» ──────────────────

    # ── i. ЛПРы ──────────────────────────────────────────────────────────
    lpr_contacts = get_lpr_contacts(company)
    log.info("  ЛПРы: %s", [(c['name'], c['role']) for c in lpr_contacts] or "не найдены")
    if lpr_contacts:
        _pause(0.5, 1.0)
        add_lpr_contacts(page, deal_id, lpr_contacts)

    log.info("  ✅ Сделка #%s успешно обработана", deal_id)


def main():
    stats = {
        'total': 0,
        'qualified': 0,
        'skipped': 0,
        'errors': 0,
        'rejected': defaultdict(int),
    }

    sess = _get_api_session()
    if not sess:
        log.error("Не удалось получить API-сессию. Проверьте .env")
        return

    # 1. Находим все проблемные сделки
    error_deals = find_error_deals(sess)
    if not error_deals:
        log.info("Сделок с ошибкой Чекко не найдено. Всё чисто!")
        return

    log.info("\n" + "═" * 64)
    log.info("Найдено сделок для обработки: %d", len(error_deals))
    log.info("═" * 64)

    # 2. Запускаем Playwright для UI-операций (добавление ЛПРов)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=True,
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        def _block_analytics(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block_analytics)

        # Логинимся
        log.info("Авторизация в Brizo...")
        login(page)
        log.info("Авторизован.")

        # Checko-страница (нужна для UI-операций ЛПРов — этот скрипт не использует Playwright для Чекко)
        # Checko теперь работает через requests, поэтому отдельная вкладка не нужна

        # 3. Обрабатываем каждую сделку
        for i, deal in enumerate(error_deals, 1):
            log.info("\n[%d/%d]", i, len(error_deals))
            stats['total'] += 1
            try:
                process_error_deal(page, sess, deal, stats)
            except Exception as e:
                log.error("  ОШИБКА при обработке #%s: %s", deal['id'], e)
                stats['errors'] += 1
            _pause(1.0, 2.0)

        browser.close()

    # Статистика
    print("\n" + "═" * 55)
    print("  РЕЗУЛЬТАТ ИСПРАВЛЕНИЯ")
    print("═" * 55)
    print(f"  Обработано всего           : {stats['total']}")
    print(f"  → успешно (остались в База): {stats['qualified']}")
    print(f"  → пропущено (уже обработан): {stats['skipped']}")
    for reason, cnt in stats['rejected'].items():
        print(f"  ❌ {reason[:35]:35}: {cnt}")
    if stats['errors']:
        print(f"  ⚠️  Ошибок                    : {stats['errors']}")
    print("═" * 55)


if __name__ == "__main__":
    main()
