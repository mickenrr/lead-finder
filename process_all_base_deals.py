"""
process_all_base_deals.py — Полная обработка ВСЕХ сделок в «База»
где ответственная — Ника Серафимова.

Прогоняет полный пайплайн (c-i) для каждой сделки.
НЕ перемещает в «Парсю» (шаг h отключён по требованию пользователя).

Защита от дублей:
  - Перед добавлением ЛПРов проверяет, есть ли уже контакты у сделки.
  - Перед добавлением tz-комментария проверяет, нет ли уже похожего.
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
    format="%(asctime)s [proc] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("proc")

REASON_NO_WEBSITE = "Нет КД"
REASON_TOO_BIG    = "Интересные, но ярд"
REASON_LOW_TAX    = "Маленькая выручка/мало налогов"
REASON_NON_TARGET = "Нецелевой"

# Паттерны tz-комментариев (чтобы не добавлять повторно)
_TZ_PATTERNS = re.compile(
    r'\b(мск|[-+]\d+ч)\b',
    re.IGNORECASE
)


def _pause(lo=1.0, hi=2.0):
    time.sleep(random.uniform(lo, hi))


def _fmt(value) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ")


def find_all_base_deals(sess) -> list[dict]:
    """Находит все сделки в «База» с ответственной Ника.

    Сначала пробует фильтрацию через /api/funnels (быстро).
    Если не работает — сканирует оффсеты (медленнее, но надёжно).
    """
    log.info("Ищем все сделки в «База» с ответственной Ника...")

    # ── Стратегия 1: фильтр через таблицу воронки ─────────────────────────
    found = []
    try:
        r = sess.get(
            f"{BRIZO_URL}/api/funnels/21480/deals/table",
            params={
                "status_id": BASE_STATUS_ID,
                "responsible_id": MY_USER_ID,
                "limit": 200,
            },
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("data", [])
            if items:
                log.info("  Фильтр API нашёл %d сделок", len(items))
                for it in items:
                    if (it.get("responsible_id") == MY_USER_ID
                            and it.get("status_id") == BASE_STATUS_ID):
                        found.append({
                            "id": it["id"],
                            "name": it.get("name", ""),
                            "inn": "",
                        })
                if found:
                    return found
    except Exception as e:
        log.warning("  Фильтр API не сработал: %s", e)

    # ── Стратегия 2: сканирование оффсетов ────────────────────────────────
    log.info("  Переходим к сканированию оффсетов...")
    seen_ids = set()
    deals = []

    # Сканируем широкий диапазон — охватывает все известные ID 1788xxx-1795xxx
    scan_ranges = [
        (24000, 27500),   # ID ~1792xxx-1794xxx (основная область)
        (20000, 24000),   # ID ~1789xxx-1792xxx (более ранние прогоны)
        (27500, 30000),   # ID ~1794xxx-1796xxx (более новые)
        (0,     20000),   # Всё остальное (на всякий случай, быстро)
    ]

    for start, end in scan_ranges:
        found_in_range = 0
        for offset in range(start, end, 20):
            try:
                r = sess.get(
                    f"{BRIZO_URL}/api/deals",
                    params={"offset": offset},
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                items = r.json().get("data", [])
                if not items:
                    break  # Дошли до конца списка
                for it in items:
                    if (it.get("responsible_id") == MY_USER_ID
                            and it.get("status_id") == BASE_STATUS_ID
                            and it["id"] not in seen_ids):
                        seen_ids.add(it["id"])
                        deals.append({
                            "id": it["id"],
                            "name": it.get("name", ""),
                            "inn": "",
                        })
                        found_in_range += 1
            except Exception:
                pass
        if found_in_range > 0:
            log.info("  Диапазон %d-%d: найдено %d сделок", start, end, found_in_range)

    return deals


def _get_existing_contacts(sess, deal_id: str) -> list[str]:
    """Возвращает имена контактов, уже привязанных к сделке."""
    try:
        r = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}/contragents", timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", [])
            return [c.get("name", "") for c in items if c.get("name")]
    except Exception:
        pass
    return []


def _has_tz_comment(sess, deal_id: str) -> bool:
    """Проверяет, есть ли уже tz-комментарий у сделки."""
    try:
        rc = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}/comments", timeout=10)
        if rc.status_code == 200:
            for c in rc.json().get("data", []):
                msg = c.get("message", "") or c.get("text", "") or ""
                if _TZ_PATTERNS.search(msg):
                    return True
    except Exception:
        pass
    return False


def process_deal(page, sess, deal: dict, stats: dict):
    """Обрабатывает одну сделку по полному пайплайну c-i."""
    deal_id = str(deal["id"])
    name    = deal.get("name", deal_id)

    log.info("─" * 64)
    log.info("Обрабатываем #%s  «%s»", deal_id, name)

    # Проверяем статус и ответственного
    rd = sess.get(f"{BRIZO_URL}/api/deals/{deal_id}", timeout=10)
    if rd.status_code != 200:
        log.warning("  Не удалось получить сделку #%s — пропускаем", deal_id)
        stats["errors"] += 1
        return
    deal_data = rd.json()
    if deal_data.get("status_id") != BASE_STATUS_ID:
        log.info("  #%s уже не в «База» (status=%s) — пропускаем",
                 deal_id, deal_data.get("status_id"))
        stats["skipped"] += 1
        return
    if deal_data.get("responsible_id") != MY_USER_ID:
        log.info("  #%s: ответственная сменилась — пропускаем", deal_id)
        stats["skipped"] += 1
        return

    # ── b. Детали сделки ──────────────────────────────────────────────────
    _pause(0.3, 0.7)
    details = get_lead_details(page, deal_id)
    inn = details.get("inn", "").strip()

    if not inn:
        log.warning("  ИНН не найден в карточке — пропускаем #%s", deal_id)
        stats["errors"] += 1
        return

    log.info("  ИНН: %s", inn)

    # ── c. Проверить сайт и почту ─────────────────────────────────────────
    deal_website = details.get("website_field", "").strip()
    deal_email   = details.get("email_field", "").strip()
    if not deal_website and not deal_email:
        log.info("  Нет сайта и почты → Проиграно 'Нет КД'")
        _pause()
        reject_lead(page, deal_id, REASON_NO_WEBSITE)
        stats["rejected"][REASON_NO_WEBSITE] += 1
        return

    log.info("  Сайт: %r  Почта: %r",
             (deal_website[:50] if deal_website else ""),
             (deal_email[:50] if deal_email else ""))

    # ── d. Получить данные из Чекко ───────────────────────────────────────
    existing_checko = details.get("checko_url_field", "").strip()
    log.info("  Запрашиваем Чекко для ИНН %s%s",
             inn, " (уже есть URL)" if existing_checko else "")

    if existing_checko:
        company = get_company_data_from_url(existing_checko, inn)
    else:
        company = get_company_data(inn)

    if not company:
        log.warning("  Компания НЕ найдена на Чекко — оставляем в «База» без изменений")
        stats["errors"] += 1
        return

    checko_url = company.get("checko_url", "")
    revenue    = company.get("revenue")
    income_tax = company.get("income_tax_amounts") or []

    log.info("  Чекко: выручка=%s  налог=%s",
             _fmt(revenue), [_fmt(t) for t in income_tax[:3]])

    # ── d.5. ОКВЭД → Сколково ─────────────────────────────────────────────
    okved_codes = company.get("okved_codes", [])
    log.info("  ОКВЭД: %s", okved_codes[:5])
    skolkovo = check_okved_skolkovo(okved_codes)
    log.info("  Сколково: %s", "Подходит" if skolkovo else "Нецелевой")

    if not skolkovo:
        _pause()
        reject_lead(page, deal_id, REASON_NON_TARGET)
        stats["rejected"][REASON_NON_TARGET] += 1
        return

    # ── e. Заполнить ссылку Чекко ─────────────────────────────────────────
    if checko_url and not existing_checko:
        log.info("  Заполняем поле Чекко: %s", checko_url)
        _pause(0.5, 1.0)
        fill_checko_field(page, deal_id, checko_url)

    # ── f. Финансовая квалификация ────────────────────────────────────────
    passed, reason = qualify_company(company)
    log.info("  Квалификация: %s (%s)",
             "✓ Подходит" if passed else "✗ Не подходит", reason)

    if not passed:
        _pause()
        reject_lead(page, deal_id, reason)
        stats["rejected"][reason] += 1
        return

    stats["qualified"] += 1

    # ── f.5. Дубли ────────────────────────────────────────────────────────
    if check_duplicate_by_inn(inn, deal_id):
        log.info("  Найден дубль по ИНН %s", inn)
        add_comment(page, deal_id, "Есть дубль")

    # ── g. Часовой пояс (только если ещё не добавлен) ───────────────────
    if _has_tz_comment(sess, deal_id):
        log.info("  Tz-комментарий уже есть — пропускаем")
    else:
        legal_address = company.get("legal_address", "")
        tz_comment = get_timezone_comment(legal_address)
        log.info("  Адрес: %s → %s",
                 (legal_address[:60] if legal_address else "не найден"), tz_comment)
        _pause(0.3, 0.7)
        add_comment(page, deal_id, tz_comment)

    # ── h. НЕ перемещаем в «Парсю» ───────────────────────────────────────

    # ── i. ЛПРы (только если контактов ещё нет) ──────────────────────────
    existing_contacts = _get_existing_contacts(sess, deal_id)
    lpr_contacts = get_lpr_contacts(company)
    log.info("  ЛПРы из Чекко: %s",
             [(c["name"], c["role"]) for c in lpr_contacts] or "не найдены")

    if existing_contacts:
        log.info("  У сделки уже %d контакт(ов): %s — добавляем только новых",
                 len(existing_contacts), existing_contacts[:3])
        # Добавляем только тех ЛПРов, чьё имя (без роли) ещё не в контактах
        existing_names_lower = {n.lower() for n in existing_contacts}
        new_lprs = []
        for lpr in lpr_contacts:
            base_name = lpr["name"].lower()
            if not any(base_name in ex for ex in existing_names_lower):
                new_lprs.append(lpr)
            else:
                log.info("  Пропускаем дубль контакта: %s", lpr["name"])
        lpr_contacts = new_lprs

    if lpr_contacts:
        _pause(0.5, 1.0)
        add_lpr_contacts(page, deal_id, lpr_contacts)
    else:
        log.info("  Новых ЛПРов нет — пропускаем")

    log.info("  ✅ Сделка #%s успешно обработана", deal_id)


def main():
    stats = {
        "total":     0,
        "qualified": 0,
        "skipped":   0,
        "errors":    0,
        "rejected":  defaultdict(int),
    }

    sess = _get_api_session()
    if not sess:
        log.error("Не удалось получить API-сессию. Проверьте .env")
        return

    # 1. Находим все сделки
    deals = find_all_base_deals(sess)

    if not deals:
        log.info("Сделок в «База» с ответственной Ника не найдено.")
        return

    # Сортируем по ID для предсказуемого порядка
    deals.sort(key=lambda d: d["id"])

    print("\n" + "═" * 64)
    print(f"  Найдено сделок в «База»: {len(deals)}")
    print("═" * 64)
    for d in deals:
        print(f"  #{d['id']}  {d['name'][:50]}")
    print("═" * 64 + "\n")

    # 2. Playwright для UI-операций
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
            if any(d in route.request.url for d in
                   ["yandex.ru", "mail.ru", "tg-desk.com", "mc.yandex"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block_analytics)

        log.info("Авторизация в Brizo...")
        login(page)
        log.info("Авторизован.")

        # 3. Обрабатываем
        for i, deal in enumerate(deals, 1):
            log.info("\n[%d/%d]", i, len(deals))
            stats["total"] += 1
            try:
                process_deal(page, sess, deal, stats)
            except Exception as e:
                log.error("  ОШИБКА при обработке #%s: %s", deal["id"], e)
                stats["errors"] += 1
            _pause(1.0, 2.0)

        browser.close()

    # Итог
    print("\n" + "═" * 55)
    print("  ИТОГ")
    print("═" * 55)
    print(f"  Обработано всего          : {stats['total']}")
    print(f"  → квалифицированы (База)  : {stats['qualified']}")
    print(f"  → пропущены               : {stats['skipped']}")
    for reason, cnt in stats["rejected"].items():
        print(f"  ❌ {reason[:35]:35}: {cnt}")
    if stats["errors"]:
        print(f"  ⚠️  Ошибок                   : {stats['errors']}")
    print("═" * 55)


if __name__ == "__main__":
    main()
