"""lead_finder.py — Autonomous Checko.ru scraper → Brizo lead creator.

Searches Checko.ru category pages by OKVED code, filters companies by
financial criteria (income_tax ≥ 4.7 M, revenue < 1 B), and creates new
deals in Brizo «База» column assigned to Серафим Саровский — where the
existing main.py parser picks them up for full qualification.

Usage:
    python3 lead_finder.py                        # run once with defaults
    python3 lead_finder.py --max 50               # stop after 50 created deals
    python3 lead_finder.py --autonomous            # loop forever
    python3 lead_finder.py --codes 62.01 26       # custom OKVED list
    python3 lead_finder.py --reset                 # ignore previously visited URLs
    python3 app_finder.py                          # web UI → http://localhost:8082

Фильтрация гигантов (≥ 1 млрд выручки):
    Checko сортирует компании по выручке убыванию. Ранние страницы — гиганты.
    Парсер читает выручку прямо из листинга (без загрузки страницы компании):
    если выручка ≥ 1 млрд — пропускает без запроса. Таким образом, стартуем
    всегда со стр. 1 — гиганты отфильтруются автоматически, без пропуска страниц.
"""

import argparse
import json
import logging
import re
import sys
import time
import random
from pathlib import Path

import requests as _req
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from checko import BASE_URL, SESSION, get_company_data_from_url, enrich_with_taxes, _pause, get_lpr_contacts, rotate_proxy, _proxy
from qualifier import qualify_company, check_okved_skolkovo
from brizo import is_inn_in_brizo, create_deal, create_contact_rest

# Ответственный за новые сделки — задаётся через --responsible (CLI) или UI.
# None = использовать SERAFIM_USER_ID по умолчанию (из brizo.py).
_responsible_id: int | None = None

# ── Playwright browser (листинговые страницы Checko без HTTP-блокировок) ───
# Один браузер на весь прогон: открывает Checko один раз, потом листает.
# Не закрывает и не переоткрывает сайт → не триггерит rate-limit.
_pw_instance  = None
_pw_browser   = None
_listing_page = None   # Playwright page для ОКВЭД-листингов


def _setup_playwright() -> bool:
    """Запускает браузер и открывает Checko. Возвращает True если успешно."""
    global _pw_instance, _pw_browser, _listing_page
    try:
        from playwright.sync_api import sync_playwright
        _pw_instance = sync_playwright().start()
        _pw_browser  = _pw_instance.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ],
        )
        ctx = _pw_browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        _listing_page = ctx.new_page()

        # Блокируем тяжёлые ресурсы — нужен только HTML
        def _block_heavy(route):
            if route.request.resource_type in ("image", "stylesheet", "font", "media"):
                route.abort()
            elif any(d in route.request.url for d in ["yandex.ru", "mail.ru", "mc.yandex"]):
                route.abort()
            else:
                route.continue_()
        _listing_page.route("**", _block_heavy)

        # Открываем Checko один раз — дальше листаем внутри
        _listing_page.goto(f"{BASE_URL}/", timeout=30_000, wait_until="domcontentloaded")
        time.sleep(2)
        log.info("[PW] Checko открыт в браузере — листинги без HTTP rate-limit")

        # Сообщаем checko.py об этой странице — он будет использовать её как резерв
        import checko as _checko_mod
        _checko_mod.set_pw_page(_listing_page)
        return True
    except Exception as e:
        log.warning("[PW] Не удалось запустить браузер: %s — работаем через HTTP", e)
        return False


def _teardown_playwright() -> None:
    global _pw_instance, _pw_browser, _listing_page
    try:
        if _pw_browser:
            _pw_browser.close()
    except Exception:
        pass
    try:
        if _pw_instance:
            _pw_instance.stop()
    except Exception:
        pass
    _listing_page = _pw_browser = _pw_instance = None

# ── Default OKVED codes ────────────────────────────────────────────────────
# Ordered from niche (few/small companies → qualifying ones appear early)
# to broad (many huge companies → need --start-page to skip giants).
#
# Тест показал: Checko сортирует по выручке убывающе. Нишевые ОКВЭДы
# (72.x, 71.x) идут первыми — там мало гигантов. Широкие IT-коды (62.01)
# идут последними — там первые 50+ страниц это Яндекс, ВК, Сбер.
DEFAULT_OKVED_CODES: list[str] = [
    # ══ ПРИОРИТЕТ 1: 100% профиль Сколково — собственный продукт/разработка ══
    #
    # Тест lf_test3: 72.19 дал все 5 сделок (475 компаний → 5 создано, ~1%).
    # 72.11 (биотех) — 500 компаний, 0 сделок: академические лабы без прибыли.
    # Строительство (41/42/43) — удалено: все падают на ОКВЭД-фильтре Сколково.
    # 2-значные коды (21, 20, 28...) — удалено: Checko не находит по ним компании.
    #
    "72.19",  # Науч. исследования и разработки прочие (физика, химия, инженерия, IT)
    "26.51",  # Производство приборов для измерений и навигации
    "26.60",  # Производство медицинской аппаратуры и оборудования
    "21.20",  # Производство лекарственных препаратов (собственные разработки)
    "26.30",  # Производство телекоммуникационного оборудования
    "26.20",  # Производство компьютеров и периферийного оборудования
    # ── IT (широкие коды, много гигантов → нужен --start-page) ───────────
    "62.01",  # Разработка компьютерного ПО  ← 1509 страниц, гиганты первые
    # ══ ПРИОРИТЕТ 2: могут подойти ═══════════════════════════════════════════
    "26.70",  # Производство оптических приборов и фотоаппаратуры
    "26.10",  # Производство электронных компонентов
    "71.20",  # Технические испытания и анализ
    "62.02",  # Консультирование в области ИТ
    "63.11",  # Обработка данных, предоставление услуг по размещению информации
    "62.09",  # Деятельность в области ИТ прочая
]

# Default: process at most this many pages per OKVED before moving on to the next.
# Prevents spending too long on unproductive OKVEDs (e.g. research orgs with tiny revenue).
# 0 = no limit (process all pages).
DEFAULT_MAX_PAGES_PER_OKVED = 30

STATE_FILE = Path(__file__).parent / "lead_finder_state.json"

# ── Паузы ──────────────────────────────────────────────────────────────────
# Между страницами ЛИСТИНГА (GET /company/select?code=…&page=N)
_LISTING_PAUSE_SEC = (3.0, 5.0)

# Между страницами КОМПАНИЙ (GET /company/{slug})
# Тест: 0.5–1.0 с → 429 через ~75 запросов. 1.0–1.5 с → безопасно.
_COMPANY_PAUSE_SEC = (1.0, 1.5)

# Пауза при СМЕНЕ ОКВЭД — ключевая дыра которой не было раньше.
# Без неё переход 72.19→26.51 делает несколько listing-запросов подряд без пауз.
_OKVED_SWITCH_PAUSE_SEC = (60.0, 90.0)

# "Дыхательная" пауза каждые N компаний — имитирует человека который
# отвлёкся, сделал что-то другое. Снижает монотонность паттерна.
_BREATH_EVERY_N   = 25
_BREATH_PAUSE_SEC = (30.0, 60.0)


# ── Helpers ────────────────────────────────────────────────────────────────

def _emit(event_type: str, **kwargs) -> None:
    """Print a structured PIPELINE_EVENT line for the web UI to consume."""
    print(f"PIPELINE_EVENT:{json.dumps({'type': event_type, **kwargs}, ensure_ascii=False)}", flush=True)


def _okved_to_checko_code(okved: str) -> str:
    """Convert OKVED like '62.01' → '620100', '26' → '260000'."""
    digits = re.sub(r"[^\d]", "", okved)
    return digits.ljust(6, "0")


def _load_settings() -> dict:
    """Загружает настройки из settings.json рядом со скриптом (VPS: /opt/lead_finder/settings.json)."""
    for path in [
        STATE_FILE.parent.parent / "settings.json",   # /opt/lead_finder/settings.json
        Path(__file__).parent / "settings.json",       # локальная разработка
    ]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"visited_urls": [], "created_deals": [], "okved_pages": {}}


def _save_state(visited_set: set, created_deals: list, okved_pages: dict | None = None) -> None:
    try:
        data: dict = {"visited_urls": list(visited_set), "created_deals": created_deals}
        if okved_pages is not None:
            data["okved_pages"] = okved_pages
        STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("Could not save state: %s", e)


# ── Listing page scraper ───────────────────────────────────────────────────

# Пауза между запросами СТРАНИЦ компаний (не листинга).
# Тест test5 показал: 0.5–1.0 с вызывает 429 после ~75 запросов.
# Возвращаем безопасные 1.0–1.5 с — всё равно быстрее исходных 1.5–2.5 с.
# Основная экономия достигается пре-фильтром (пропуск убыточных без загрузки).
_COMPANY_PAUSE_SEC = (1.0, 1.5)

# Если медианная выручка на листинг-странице опускается ниже этого порога,
# компании слишком мелкие — ОКВЭД прекращаем досрочно.
_REVENUE_STOP_THRESHOLD = 0  # отключён — досрочная остановка по выручке убирала часть ОКВЭДов

# Минимальная чистая прибыль на листинг-странице для предварительного пропуска.
# Компании с отрицательной прибылью точно не платят 4.7 млн налога.
_PREFILTER_MIN_PROFIT = 0   # пропускать только убыточные (чистая прибыль < 0)

# Максимальная выручка для пре-фильтра по листингу (без загрузки страницы).
# Checko сортирует по выручке убыванию → на ранних страницах гиганты (> 1 млрд).
# Если выручка видна в листинге и она >= 1 млрд, компанию пропускаем сразу —
# экономим запрос к странице компании (~3–4 с) и запрос к Brizo.
_PREFILTER_MAX_REVENUE = 1_000_000_000  # 1 млрд руб. → "Интересные, но ярд"


def _parse_amount_listing(text: str) -> int | None:
    """Parse '5,3 млн' / '-72,9 млн' / '314 тыс' → int рублей, или None."""
    text = text.replace(" ", " ").replace(",", ".")
    for pat, mul in [
        (r"(-?[\d.]+)\s*млрд", 1_000_000_000),
        (r"(-?[\d.]+)\s*млн",  1_000_000),
        (r"(-?[\d.]+)\s*тыс",  1_000),
        (r"(-?[\d.]+)\s*руб",  1),
    ]:
        m = re.search(pat, text)
        if m:
            try:
                return int(float(m.group(1)) * mul)
            except ValueError:
                pass
    return None


def get_company_cards(okved_code: str, page_num: int = 1) -> tuple[list[dict], int]:
    """
    Scrape company cards from a Checko OKVED listing page.

    Each card is a dict: {"url": str, "revenue": int|None, "profit": int|None}
    Returns (cards, total_pages).

    Extracts financial hints (Выручка, Чистая прибыль) directly from the
    listing HTML — no extra HTTP requests needed. Used for pre-filtering:
    companies with clearly negative profit are skipped without fetching their
    individual pages (saves 3–5 sec each).

    On 429 waits 60 s × attempt, then retries up to 3 times.
    """
    checko_code = _okved_to_checko_code(okved_code)
    url = f"{BASE_URL}/company/select?code={checko_code}&page={page_num}"
    log.info("Listing ОКВЭД %s (code %s) стр. %d", okved_code, checko_code, page_num)

    html: str | None = None

    # ── Попытка 1: Playwright (браузер открыт, не банит) ─────────────────────
    if _listing_page is not None:
        try:
            _listing_page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            time.sleep(random.uniform(1.5, 2.5))   # пауза как у человека
            html = _listing_page.content()
            log.debug("[PW] listing получен через браузер")
        except Exception as e:
            log.warning("[PW] listing browser error: %s — пробуем HTTP", e)

    # ── Попытка 2: HTTP SESSION (резерв) ─────────────────────────────────────
    if html is None:
        for attempt in range(1, 4):
            try:
                resp = SESSION.get(url, timeout=20, proxies=_proxy())
                if resp.status_code == 429:
                    rotate_proxy()
                    from checko import _PROXIES
                    wait = 15 if _PROXIES else 60 * attempt
                    log.warning("Checko 429 — ждём %d сек (попытка %d/3)...", wait, attempt)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                html = resp.text
                break
            except Exception as e:
                log.warning("Listing page error (попытка %d/3): %s", attempt, e)
                rotate_proxy()
                if attempt < 3:
                    time.sleep(15 * attempt)
                else:
                    return [], 0

    if html is None:
        return [], 0

    soup = BeautifulSoup(html, "html.parser")

    # Each company card lives inside a <td> that contains a /company/ link.
    # Structure:
    #   <td>
    #     <a href="/company/{slug}-{ogrn}">Name</a>
    #     <div>Address</div>
    #     <div>Director  Дата регистрации ...</div>
    #     <div>Выручка X млн руб.  Чистая прибыль Y млн руб.  Капитал Z млн руб.</div>
    #   </td>
    cards: list[dict] = []
    seen:  set[str]  = set()

    for td in soup.find_all("td"):
        a_tag = td.find("a", href=re.compile(r"^/company/[^/?#]+-\d{13,15}$"))
        if not a_tag:
            continue
        href = a_tag["href"]
        full_url = BASE_URL + href
        if full_url in seen:
            continue
        seen.add(full_url)

        # Find the financial summary div (contains "Выручка")
        revenue = profit = None
        for div in td.find_all("div"):
            text = div.get_text(" ", strip=True)
            if "Выручка" in text and "прибыль" in text.lower():
                # Parse each metric separately from the raw text
                rev_m = re.search(r"Выручка\s+([-\d,.\s]+(?:млн|тыс|млрд|руб))", text)
                if rev_m:
                    revenue = _parse_amount_listing(rev_m.group(1))
                pro_m = re.search(r"[Пп]рибыль\s+([-\d,.\s]+(?:млн|тыс|млрд|руб))", text)
                if pro_m:
                    profit = _parse_amount_listing(pro_m.group(1))
                break

        cards.append({"url": full_url, "revenue": revenue, "profit": profit})

    # Total pages from pagination links
    total_pages = page_num
    for a in soup.find_all("a", href=re.compile(r"page=\d+")):
        m = re.search(r"page=(\d+)", a["href"])
        if m:
            total_pages = max(total_pages, int(m.group(1)))

    log.info("  → %d компаний, всего страниц: %d", len(cards), total_pages)
    return cards, total_pages


def get_company_urls(okved_code: str, page_num: int = 1) -> tuple[list[str], int]:
    """Legacy wrapper — returns only URLs. Used internally where cards not needed."""
    cards, total = get_company_cards(okved_code, page_num)
    return [c["url"] for c in cards], total


# ── Company pipeline ───────────────────────────────────────────────────────

def process_company(
    url: str,
    visited_set: set,
    created_deals: list,
    revenue_max: int | None = None,
    income_tax_min: int | None = None,      # backward compat
    income_tax_rule: dict | None = None,
    advanced_finance: dict | None = None,
) -> str:
    """
    Full qualification + deal-creation pipeline for one company URL.

    Steps:
      1. Skip if already visited
      2. Fetch & parse Checko page → extract INN, name, financials, OKVEDs
      3. Skip if no INN
      4. Skip if INN already in Brizo (duplicate)
      5. Skip if OKVEDs don't match Skolkovo list
      6. Skip if financials don't pass (income_tax < 4.7 M or revenue ≥ 1 B)
      7. Create deal in Brizo «База» → Серафим Саровский

    Returns: "created" | "duplicate" | "no_inn" | "okved_fail" |
             "rejected" | "error" | "visited"
    """
    if url in visited_set:
        return "visited"

    visited_set.add(url)  # mark immediately so reruns skip it

    # ── Fetch basic data (no taxes yet — saves a request for duplicates) ────
    try:
        data = get_company_data_from_url(url, fetch_taxes=False)
    except Exception as e:
        log.warning("fetch error %s: %s", url, e)
        _emit("company_result", url=url, name="", result="error", reason=str(e))
        return "error"

    if not data:
        _emit("company_result", url=url, name="", result="error", reason="Пустой ответ")
        return "error"

    inn  = data.get("inn",  "").strip()
    name = data.get("name", url.split("/")[-1])

    log.info("Компания: %s  ИНН: %s", name, inn or "—")
    _emit("company_checked", url=url, name=name, inn=inn)

    # ── Duplicate check (before taxes fetch to save a request) ────────────
    if is_inn_in_brizo(inn):
        log.info("  → ИНН %s уже в Brizo — дубль", inn)
        _emit("company_result", url=url, name=name, inn=inn, result="duplicate",
              reason="Уже в Brizo")
        return "duplicate"

    # ── OKVED filter ───────────────────────────────────────────────────────
    okved_codes = data.get("okved_codes", [])
    if not check_okved_skolkovo(okved_codes):
        log.info("  → ОКВЭД не проходит: %s", okved_codes[:5])
        _emit("company_result", url=url, name=name, inn=inn, result="okved_fail",
              reason=f"ОКВЭД не по списку ({', '.join(okved_codes[:3])})")
        return "okved_fail"

    # ── Fetch taxes (only for new companies that passed OKVED) ───────────
    enrich_with_taxes(data, url)

    # ── Financial filter ───────────────────────────────────────────────────
    kwargs: dict = {}
    if revenue_max        is not None: kwargs["revenue_max"]       = revenue_max
    if income_tax_rule    is not None: kwargs["income_tax_rule"]   = income_tax_rule
    elif income_tax_min   is not None: kwargs["income_tax_min"]    = income_tax_min
    if advanced_finance   is not None: kwargs["advanced_finance"]  = advanced_finance
    passed, reason = qualify_company(data, **kwargs)
    if not passed:
        log.info("  → финансы не проходят: %s", reason)
        _emit("company_result", url=url, name=name, inn=inn, result="rejected",
              reason=reason)
        return "rejected"

    # ── Create deal ────────────────────────────────────────────────────────
    website      = data.get("website",        "")
    revenue      = data.get("revenue")
    income_tax   = data.get("income_tax_amount")
    director_name = data.get("director_name", "")
    director_inn  = data.get("director_inn",  "")

    # Регион: первый значимый элемент после 6-значного почтового индекса
    # Пример: "394000, Воронежская область, г. Воронеж, ..." → "Воронежская область"
    legal_address = data.get("legal_address", "")
    region_m = re.search(r"\d{6},\s*([^,]+)", legal_address)
    region   = region_m.group(1).strip() if region_m else ""

    emails = data.get("emails") or []

    log.info("  ✅ ПОДХОДИТ — создаём сделку в Brizo...")
    deal_id = create_deal(
        name=name,
        inn=inn,
        website=website,
        checko_url=url,
        region=region,
        director_name=director_name,
        director_inn=director_inn,
        emails=emails,
        responsible_id=_responsible_id,
    )

    if not deal_id:
        log.error("  Ошибка создания сделки для %s", name)
        _emit("company_result", url=url, name=name, inn=inn, result="error",
              reason="Ошибка создания сделки в Brizo")
        return "error"

    created_deals.append(deal_id)
    log.info("  ✅ Сделка #%s создана ✓", deal_id)

    # ── Добавляем ЛПРов как контакты (все директора и учредители) ─────────────
    lpr_contacts = get_lpr_contacts(data)
    if lpr_contacts:
        log.info("  → добавляем %d ЛПР контакт(ов)...", len(lpr_contacts))
        for contact in lpr_contacts:
            raw_role  = contact.get("role", "")
            share_pct = contact.get("share_pct", "")
            c_name    = contact.get("name", "")
            c_inn     = contact.get("inn", "")

            # Формат имени такой же, как в Playwright-версии:
            #   Генеральный директор → "Иванов И.И. гендир"
            #   Учредитель с долей   → "Петров П.П. учред 45%"
            #   Учредитель без доли  → "Петров П.П. учред"
            if "генеральный директор" in raw_role.lower():
                display = f"{c_name} гендир"
            elif "учредитель" in raw_role.lower():
                display = f"{c_name} учред {share_pct}%" if share_pct else f"{c_name} учред"
            else:
                display = c_name

            cid = create_contact_rest(deal_id, display, c_inn)
            if cid:
                log.info("    ✓ контакт '%s' id=%s", display, cid)
    else:
        log.info("  → ЛПРы на Checko не найдены")

    _emit("company_result",
          url=url, name=name, inn=inn, result="created",
          reason="Подходит", deal_id=deal_id,
          revenue=revenue, income_tax=income_tax, website=website)
    return "created"


# ── Main orchestration ─────────────────────────────────────────────────────

def main(
    okved_codes: list[str] | None = None,
    max_leads: int = 0,
    autonomous: bool = False,
    reset_state: bool = False,
    start_page: int = 1,
    max_pages_per_okved: int = DEFAULT_MAX_PAGES_PER_OKVED,
    responsible_id: int | None = None,
) -> None:
    """
    Main loop.

    okved_codes          — OKVED list to search (default: DEFAULT_OKVED_CODES)
    max_leads            — stop after this many deals created (0 = unlimited)
    autonomous           — if True, restart from page 1 after exhausting all codes
    reset_state          — if True, ignore previously visited URLs
    start_page           — skip to this page for each OKVED (useful to bypass giant companies
                           that dominate early pages). For OKVEDs with fewer total pages than
                           start_page, falls back to page 1 automatically.
    max_pages_per_okved  — max pages to check per OKVED before moving to the next one
                           (0 = no limit). Helps skip over unproductive OKVEDs quickly.
    responsible_id       — Brizo user ID to assign as responsible for created deals
                           (default: SERAFIM_USER_ID from brizo.py)
    """
    # Записываем responsible_id в глобал — process_company использует его
    global _responsible_id
    _responsible_id = responsible_id
    # ── Загружаем настройки из settings.json ──────────────────────────────────
    settings = _load_settings()
    if settings:
        log.info("Настройки загружены из settings.json")

    # OKVEDs: CLI --codes > settings.json > DEFAULT_OKVED_CODES
    if okved_codes:
        codes = okved_codes
    elif settings.get("okved_codes"):
        codes = settings["okved_codes"]
        log.info("ОКВЭДы из настроек: %s", codes)
    else:
        codes = DEFAULT_OKVED_CODES

    # Финансовые пороги из настроек (иначе — значения из qualifier.py по умолчанию)
    from qualifier import REVENUE_LIMIT as _DEFAULT_REV_MAX, INCOME_TAX_MIN as _DEFAULT_TAX_MIN
    _revenue_max     = int(settings.get("revenue_max", _DEFAULT_REV_MAX))
    _revenue_min     = int(settings.get("revenue_min", 0))
    _income_tax_rule = settings.get("income_tax_rule") or None
    _advanced_finance = settings.get("advanced_finance") or None
    # Backward compat: если новый формат не задан, читаем старый income_tax_min
    _income_tax_min  = int(settings.get("income_tax_min", _DEFAULT_TAX_MIN))
    if _income_tax_rule:
        log.info("Финансовые пороги: выручка %d – %d, налог (режим=%s лет=%d мин=%d)",
                 _revenue_min, _revenue_max,
                 _income_tax_rule.get("mode","any"),
                 _income_tax_rule.get("years", 3),
                 _income_tax_rule.get("min_amount", _DEFAULT_TAX_MIN))
    else:
        log.info("Финансовые пороги: выручка %d – %d, налог >= %d",
                 _revenue_min, _revenue_max, _income_tax_min)

    start_page          = max(1, start_page)
    max_pages_per_okved = max(0, max_pages_per_okved)

    log.info("═" * 60)
    log.info("  LEAD FINDER  |  ОКВЭДов: %d  |  лимит: %s  |  режим: %s  |  старт стр: %d  |  макс стр/ОКВЭД: %s",
             len(codes), max_leads or "∞", "автономный" if autonomous else "однократно",
             start_page, max_pages_per_okved or "∞")
    log.info("═" * 60)

    # Запускаем браузер — Checko открывается один раз, потом листаем внутри.
    # Не нужны прокси и сервер: браузер выглядит как человек, не банит.
    _setup_playwright()

    state = {} if reset_state else _load_state()
    visited_set:   set  = set(state.get("visited_urls",  []))
    created_deals: list = list(state.get("created_deals", []))
    okved_pages:   dict = dict(state.get("okved_pages",  {}))  # {okved: next_page_to_fetch}

    stats: dict[str, int] = {
        "checked":    0,
        "created":    0,
        "duplicate":  0,
        "rejected":   0,
        "okved_fail": 0,
        "error":      0,
    }

    _emit("started", codes=codes, max_leads=max_leads, autonomous=autonomous,
          start_page=start_page, max_pages_per_okved=max_pages_per_okved)

    def _done() -> bool:
        return max_leads > 0 and stats["created"] >= max_leads

    try:
        while True:   # outer loop for autonomous mode
            for okved in codes:
                if _done():
                    break

                # For large OKVEDs: start from start_page to skip giant companies.
                # For small OKVEDs (fewer total pages): fall back to page 1.
                #
                # Key optimisation: peek at page 1 to get total_pages.
                # If total_pages < start_page reuse peek cards (no second request).
                peek_cards: list[dict] = []
                peek_total: int        = 0

                # Начинаем с сохранённого прогресса для этого ОКВЭД,
                # иначе с start_page (аргумент CLI, по умолчанию 1).
                effective_start = okved_pages.get(okved, start_page)

                if effective_start > 1:
                    peek_cards, peek_total = get_company_cards(okved, 1)
                    time.sleep(random.uniform(*_LISTING_PAUSE_SEC))

                    if peek_total >= effective_start:
                        log.info("ОКВЭД %s: %d стр. всего → продолжаем с стр. %d (сохранённый прогресс)",
                                 okved, peek_total, effective_start)
                        page_num    = effective_start
                        total_pages = peek_total
                        peek_cards  = []   # страница 1 уже обработана — отбрасываем
                    else:
                        log.info("ОКВЭД %s: только %d стр., сохр. стр. %d > всего → сброс на стр. 1",
                                 okved, peek_total, effective_start)
                        page_num    = 1
                        total_pages = max(peek_total, 1)
                        # peek_cards has page-1 companies — injected below
                else:
                    page_num    = 1
                    total_pages = 1

                # Cap end page based on max_pages_per_okved
                pages_done_this_okved = 0

                while page_num <= total_pages:
                    if _done():
                        break
                    if max_pages_per_okved > 0 and pages_done_this_okved >= max_pages_per_okved:
                        log.info("ОКВЭД %s: достигнут лимит %d стр. → следующий ОКВЭД",
                                 okved, max_pages_per_okved)
                        break

                    # Reuse page-1 cards from peek if available (avoids double request)
                    if peek_cards and page_num == 1:
                        company_cards = peek_cards
                        peek_cards    = []
                        log.info("  → %d компаний (из peek, без доп. запроса)", len(company_cards))
                    else:
                        company_cards, total_pages = get_company_cards(okved, page_num)
                        if not company_cards:
                            log.warning("ОКВЭД %s стр.%d: нет ссылок — пропуск", okved, page_num)
                            break
                        time.sleep(random.uniform(*_LISTING_PAUSE_SEC))

                    # ── Авто-стоп: компании слишком мелкие на этой странице ──────
                    revenues_on_page = [
                        c["revenue"] for c in company_cards
                        if c.get("revenue") is not None and c["revenue"] > 0
                    ]
                    if revenues_on_page:
                        median_rev = sorted(revenues_on_page)[len(revenues_on_page) // 2]
                        if median_rev < _REVENUE_STOP_THRESHOLD:
                            log.info(
                                "ОКВЭД %s стр.%d: медианная выручка %.1f млн < порога %.0f млн — "
                                "компании слишком мелкие, переходим к следующему ОКВЭД",
                                okved, page_num,
                                median_rev / 1_000_000,
                                _REVENUE_STOP_THRESHOLD / 1_000_000,
                            )
                            break

                    _emit("page_scraped", okved=okved, page=page_num,
                          total_pages=total_pages, count=len(company_cards))

                    prefiltered = 0
                    for card in company_cards:
                        url    = card["url"]
                        profit = card.get("profit")
                        rev    = card.get("revenue")

                        if _done():
                            break
                        if url in visited_set:
                            continue

                        # ── Пре-фильтр по данным листинга (без загрузки страницы) ──
                        # Отрицательная чистая прибыль → налог на прибыль точно 0.
                        # Нулевая выручка → компания ничего не зарабатывает.
                        # Выручка ≥ 1 млрд → слишком большая (qualifier всё равно
                        #   отклонит как "Интересные, но ярд"), и мы не тратим запрос.
                        if profit is not None and profit < _PREFILTER_MIN_PROFIT:
                            visited_set.add(url)
                            prefiltered += 1
                            continue
                        if rev is not None and rev == 0:
                            visited_set.add(url)
                            prefiltered += 1
                            continue
                        if rev is not None and rev >= _revenue_max:
                            visited_set.add(url)
                            prefiltered += 1
                            continue
                        if rev is not None and _revenue_min > 0 and rev < _revenue_min:
                            visited_set.add(url)
                            prefiltered += 1
                            continue

                        stats["checked"] += 1
                        result = process_company(
                            url, visited_set, created_deals,
                            revenue_max=_revenue_max,
                            income_tax_rule=_income_tax_rule,
                            income_tax_min=_income_tax_min if not _income_tax_rule else None,
                            advanced_finance=_advanced_finance,
                        )

                        key = result if result in stats else "error"
                        stats[key] = stats.get(key, 0) + 1

                        _emit("stats_update", **stats)
                        _save_state(visited_set, created_deals, okved_pages)

                        # Пауза между компаниями (1.0–1.5 сек).
                        time.sleep(random.uniform(*_COMPANY_PAUSE_SEC))

                        # ── "Дыхательная" пауза каждые N компаний ─────────────
                        # Имитирует человека: поработал, отвлёкся, вернулся.
                        # Разбивает монотонный паттерн запросов.
                        if stats["checked"] % _BREATH_EVERY_N == 0:
                            breath = random.uniform(*_BREATH_PAUSE_SEC)
                            log.info(
                                "  ··· дыхательная пауза %.0f сек (проверено %d компаний) ···",
                                breath, stats["checked"],
                            )
                            time.sleep(breath)

                    if prefiltered:
                        log.info("  → пре-фильтр отсеял %d компаний (убыточные / нулевая выручка / ярд+)",
                                 prefiltered)

                    page_num += 1
                    pages_done_this_okved += 1

                # ── Сохраняем прогресс страниц для этого ОКВЭД ──────────────
                # page_num уже увеличен на 1 после последней обработанной страницы.
                # Если page_num > total_pages — цикл завершён, следующий раз с 1.
                # Иначе — продолжим отсюда в следующем цикле.
                if page_num > total_pages:
                    okved_pages[okved] = 1
                    log.info("ОКВЭД %s: обработано все %d стр. → следующий цикл начнёт со стр. 1",
                             okved, total_pages)
                else:
                    okved_pages[okved] = page_num
                    log.info("ОКВЭД %s: прогресс сохранён → следующий цикл продолжит со стр. %d",
                             okved, page_num)
                _save_state(visited_set, created_deals, okved_pages)

                # ── Пауза при смене ОКВЭД ────────────────────────────────────
                # Критически важна: без неё переход между ОКВЭДами делает
                # несколько listing-запросов подряд почти без паузы.
                if not _done():
                    okved_pause = random.uniform(*_OKVED_SWITCH_PAUSE_SEC)
                    log.info(
                        "ОКВЭД %s завершён → пауза %.0f сек перед следующим ОКВЭД",
                        okved, okved_pause,
                    )
                    time.sleep(okved_pause)

            if not autonomous or _done():
                break

            log.info("Цикл завершён, перезапуск через 5 минут...")
            _emit("cycle_done", **stats)
            time.sleep(300)

    except KeyboardInterrupt:
        log.info("Остановлено пользователем")

    finally:
        _teardown_playwright()
        _save_state(visited_set, created_deals, okved_pages)
        log.info("═" * 60)
        log.info(
            "  ИТОГ  |  проверено=%d  создано=%d  дубли=%d  "
            "отклонено=%d  оквэд=%d  ошибок=%d",
            stats["checked"],  stats["created"],    stats["duplicate"],
            stats["rejected"], stats["okved_fail"], stats["error"],
        )
        log.info("═" * 60)
        _emit("finished", **stats)


# ── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Brizo Lead Finder — Checko OKVED scraper")
    ap.add_argument("--max",        type=int, default=0,  dest="max_leads",
                    metavar="N",    help="Создать не более N сделок (0 = без лимита)")
    ap.add_argument("--autonomous", action="store_true",
                    help="Автономный режим: цикл не останавливается")
    ap.add_argument("--codes",      nargs="+", metavar="OKVED",
                    help="Список ОКВЭД через пробел (например: 62.01 26 28)")
    ap.add_argument("--reset",      action="store_true",
                    help="Сбросить список уже проверенных URL")
    ap.add_argument("--start-page", type=int, default=1, dest="start_page",
                    metavar="N",
                    help="Начать с N-й страницы каждого ОКВЭД (1 = сначала). "
                         "Для ОКВЭДов с менее чем N страниц используется стр. 1.")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES_PER_OKVED,
                    dest="max_pages_per_okved", metavar="N",
                    help=f"Макс. страниц на один ОКВЭД (0 = без лимита, по умолч. {DEFAULT_MAX_PAGES_PER_OKVED}).")
    ap.add_argument("--state-file", type=str, default=None, dest="state_file",
                    metavar="PATH",
                    help="Путь к файлу состояния (по умолч. lead_finder_state.json рядом со скриптом).")
    ap.add_argument("--responsible", type=int, default=None, dest="responsible_id",
                    metavar="USER_ID",
                    help="Brizo ID пользователя, назначаемого ответственным за новые сделки.")
    args = ap.parse_args()
    if args.state_file:
        STATE_FILE = Path(args.state_file)
    main(
        okved_codes          = args.codes,
        max_leads            = args.max_leads,
        autonomous           = args.autonomous,
        reset_state          = args.reset,
        start_page           = args.start_page,
        max_pages_per_okved  = args.max_pages_per_okved,
        responsible_id       = args.responsible_id,
    )
