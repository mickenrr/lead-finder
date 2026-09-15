"""
tg_bot.py — phone lookup via @pupupu_555_bot (zerkalo) in Telegram Web A.

Requires tg_profile/ to exist — run setup_tg.py once first.

Fixed bugs:
  1. TG chat list not loaded in time → wait_for_selector instead of sleep(4)
  2. "CONFIRM" dialog not dismissed → added to confirmation texts
  3. Cached report URL (bot slow to update) → poll for message change, up to 60s
  4. INN digits matched as phone → filter numbers that are substrings of the INN
"""
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

TG_PROFILE_DIR = str(Path(__file__).parent / "tg_profile")
TG_URL         = "https://web.telegram.org/a/"
BOT_CHAT_NAME  = "zerkalo"

_PHONE_RE = re.compile(
    r'(?<!\d)(?:\+?[78][\s\-]?(?:\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}))(?!\d)'
)

# Все варианты текста кнопки подтверждения диалога открытия ссылки/веб-приложения
_CONFIRM_TEXTS = ("CONFIRM", "OPEN LINK", "Open", "Открыть", "OK", "Continue")


def _normalize(raw: str) -> str | None:
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits[0] in ('7', '8'):
        result = '+7' + digits[1:]
    elif len(digits) == 10:
        result = '+7' + digits
    else:
        return None
    # Только мобильные (+79...) и Сибирь/Урал/ДВ (+73...).
    # +74... — городские (495, 499 и т.д.), +78... — включают 8-800 и
    # городские (812 СПб и др.), +77... — Казахстан или несуществующий
    # российский диапазон. Для контактов ЛПР они не подходят.
    if result[2] not in ('3', '9'):
        return None
    return result


def _extract_phones(text: str, inn: str = "",
                    block_inns: list[str] | None = None) -> list[str]:
    """Extract phone numbers from bot report, validating each against its surrounding record.

    The Dyxless report consists of database records; each record contains
    ИНН, ФИО, and optionally a phone — all within ~15 lines of each other.
    Two filters applied:

    1. INN-context check: for each phone, look at surrounding ±15 lines.
       If the nearest INN found there is NOT our target inn → skip (the phone
       belongs to a different person's record, e.g. a co-founder). If no INN
       found in context → accept (summary section sometimes puts INN later).

    2. INN-artifact check: phone digits must not be a substring/prefix of
       ANY INN of contacts in this deal (catches INN written as phone in DBs).
    """
    inn_digits = re.sub(r'\D', '', inn)

    # All deal INNs for artifact check
    all_deal_inns = [inn_digits] if inn_digits else []
    for extra in (block_inns or []):
        d = re.sub(r'\D', '', extra)
        if d and d not in all_deal_inns:
            all_deal_inns.append(d)

    lines = text.split('\n')
    seen: set[str] = set()
    result: list[str] = []

    # Precompute INN positions for fast lookup.
    # Personal INN (ИНН физлица) is always 12 digits — we search by personal INN.
    # 10-digit numbers could be company INN, passport, or other IDs → skip to avoid
    # false positives (e.g. паспорт 7315106237 looks like a 10-digit INN).
    inn_positions: list[tuple[int, str]] = []   # (line_idx, inn_digits)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.isdigit() and len(stripped) == 12:
            inn_positions.append((i, stripped))

    for i, line in enumerate(lines):
        for m in _PHONE_RE.finditer(line):
            p = _normalize(m.group())
            if not p:
                continue

            # ── Filter 1: INN-context check ───────────────────────────────
            # Find the nearest INN value within ±15 lines of this phone.
            WINDOW = 15
            nearest_inn: str | None = None
            nearest_dist = WINDOW + 1
            for pos, pos_inn in inn_positions:
                dist = abs(pos - i)
                if dist <= WINDOW and dist < nearest_dist:
                    nearest_dist = dist
                    nearest_inn = pos_inn

            if nearest_inn is not None and inn_digits:
                if nearest_inn != inn_digits:
                    # Nearest INN belongs to someone else → this phone is theirs
                    log.debug("[TG] Skipping %s — nearest INN %s ≠ our INN %s "
                              "(line %d, INN at %d)", p, nearest_inn, inn_digits,
                              i, i + (nearest_dist if nearest_inn > inn_digits else -nearest_dist))
                    continue

            # ── Filter 2: INN-artifact check ─────────────────────────────
            phone_digits = re.sub(r'\D', '', p)
            phone_core   = phone_digits[1:] if phone_digits[:1] in ('7', '8') else phone_digits
            blocked = False
            for d in all_deal_inns:
                if (d.startswith(phone_digits) or phone_digits in d
                        or d.startswith(phone_core) or phone_core in d):
                    log.debug("[TG] Skipping %s — INN artifact (matched %s)", p, d)
                    blocked = True
                    break
            if blocked:
                continue

            if p not in seen:
                seen.add(p)
                result.append(p)

    return result


def _save_screenshot(page, label: str) -> None:
    path = f"/tmp/tg_debug_{label}.png"
    try:
        page.screenshot(path=path)
        log.info("[TG] Screenshot: %s", path)
    except Exception:
        pass



def _open_bot_chat(page, ctx) -> None:
    """
    Open the bot chat. First try visible chat list; fall back to search bar.

    FIX #1: wait for chat list to render (was: bare time.sleep(4) which
    isn't enough → list appears blank → locator times out).
    """
    # Wait for at least one chat to appear in the sidebar
    try:
        page.wait_for_selector('.ListItem.Chat', timeout=20_000)
    except Exception:
        log.warning("[TG] Chat list didn't appear in 20s — will try search anyway")

    # Try to find bot in visible list first
    bot_item = page.locator('.ListItem.Chat', has_text=BOT_CHAT_NAME).first
    if bot_item.is_visible():
        bot_item.click()
        log.info("[TG] Opened bot from chat list")
        return

    # Fallback: use the search bar
    log.info("[TG] Bot not visible in list — using search")
    for sel in [
        'input[placeholder*="Search"], input[placeholder*="Поиск"]',
        '.search-input input',
        '.input-search input',
    ]:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=2_000):
                inp.click()
                inp.fill(BOT_CHAT_NAME)
                time.sleep(1.5)
                bot_item = page.locator('.ListItem.Chat', has_text=BOT_CHAT_NAME).first
                bot_item.wait_for(state="visible", timeout=8_000)
                bot_item.click()
                log.info("[TG] Opened bot via search")
                return
        except Exception:
            continue

    # Last resort: direct click without check
    log.warning("[TG] Search fallback failed, trying direct locator wait")
    bot_item = page.locator('.ListItem.Chat', has_text=BOT_CHAT_NAME).first
    bot_item.wait_for(state="visible", timeout=15_000)
    bot_item.click()


def get_phones_for_inn(inn: str, block_inns: list[str] | None = None) -> list[str]:
    """
    Send LPR INN to @pupupu_555_bot, open the web report in a new tab,
    extract and return the first 3 phone numbers found.
    """
    if not Path(TG_PROFILE_DIR).exists():
        log.error("[TG] Profile missing — run python3 setup_tg.py first")
        return []

    phones: list[str] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            TG_PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-popup-blocking",
                  "--window-position=0,0", "--window-size=1280,800"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = ctx.new_page()
            log.info("[TG] Opening Telegram Web for INN %s", inn)
            page.goto(TG_URL, timeout=45_000, wait_until="domcontentloaded")

            # ── 1. Open bot chat (with proper wait + search fallback) ──────
            _open_bot_chat(page, ctx)
            time.sleep(2)  # let chat fully render

            # ── 2. Считаем кнопки «Посмотреть» до отправки ──────────────
            # FIX #3 (v3): CSS-класс .Message.is-in сломался после обновления TG Web A.
            # Вместо подсчёта сообщений считаем кнопки «Посмотреть» (кнопка бота).
            # Когда бот ответит на НАШ запрос → появится НОВАЯ кнопка → count растёт.
            # Работает вне зависимости от CSS-классов TG Web A.
            _view_sel = 'button, a'
            _view_text = 'Посмотреть'
            n_btns_before = page.locator(_view_sel, has_text=_view_text).count()
            log.info("[TG] 'Посмотреть' buttons before query: %d", n_btns_before)

            # ── 3. Find compose box and send INN ──────────────────────────
            inp = page.locator('.ProseMirror[contenteditable="true"]').last
            inp.wait_for(state="visible", timeout=15_000)
            inp.click()
            time.sleep(0.3)

            # FIX #6: ctrl+a + backspace ненадёжно очищает ProseMirror —
            # TG Web сохраняет состояние поля в профиль и оно восстанавливается.
            # Принудительно очищаем через JS, затем дополнительно ctrl+a+del.
            page.evaluate(
                "() => {"
                "  const el = document.querySelector('.ProseMirror[contenteditable]');"
                "  if (el) { el.innerHTML = ''; el.textContent = '';"
                "    el.dispatchEvent(new Event('input', {bubbles:true})); }"
                "}"
            )
            time.sleep(0.2)
            inp.press('Control+a')
            inp.press('Delete')
            time.sleep(0.2)

            # Проверяем что поле пусто
            leftover = inp.inner_text().strip()
            if leftover:
                log.warning("[TG] Field not empty after clear: %r — retrying JS clear", leftover)
                page.evaluate(
                    "() => { document.querySelectorAll('.ProseMirror[contenteditable]')"
                    ".forEach(e => { e.innerHTML=''; e.textContent=''; }); }"
                )
                time.sleep(0.3)

            # FIX INPUT: вставляем ИНН через execCommand — атомарно, без
            # перехвата TG Web A. keyboard.type по символу даёт race condition
            # (автозамена, история) → усечённый текст.
            page.evaluate(f"document.execCommand('insertText', false, '{inn}')")
            time.sleep(0.3)

            typed = inp.inner_text().strip()
            if inn not in typed:
                # Второй шанс: на некоторых платформах execCommand не работает →
                # fallback к медленному keyboard.type с большим delay
                log.warning("[TG] execCommand gave %r — fallback to keyboard.type", typed)
                # очищаем снова и пробуем печатать
                page.evaluate(
                    "() => { const el = document.querySelector('.ProseMirror[contenteditable]');"
                    " if (el) { el.innerHTML=''; el.textContent='';"
                    "   el.dispatchEvent(new Event('input',{bubbles:true})); } }"
                )
                time.sleep(0.4)
                inp.press('Control+a')
                inp.press('Delete')
                time.sleep(0.2)
                page.keyboard.type(inn, delay=80)
                time.sleep(0.5)
                typed = inp.inner_text().strip()

            if inn not in typed:
                log.error("[TG] Input rejected — got %r, expected INN %s", typed, inn)
                _save_screenshot(page, inn + "_input_fail")
                return []

            log.info("[TG] INN %s typed OK, sending…", inn)
            page.keyboard.press("Enter")

            # ── 4. Ждём НОВУЮ кнопку «Посмотреть» с НАШИМ ИНН ──────────────
            # FIX RACE: несколько пользователей могут использовать бота одновременно.
            # Когда появляется новая кнопка — проверяем, содержит ли страница НАШ ИНН
            # (бот показывает ИНН в тексте ответного сообщения).
            # Если нет — это ответ на чужой запрос: поднимаем планку и ждём дальше.
            log.info("[TG] Waiting for bot response for INN %s (buttons before: %d)…",
                     inn, n_btns_before)
            deadline = time.time() + 90
            new_btn_appeared = False
            while time.time() < deadline:
                n_now = page.locator(_view_sel, has_text=_view_text).count()
                if n_now > n_btns_before:
                    # Новая кнопка есть — проверяем, наш ли это ответ
                    page_text = page.evaluate("() => document.body.innerText")
                    if inn in page_text:
                        log.info("[TG] Bot responded for INN %s (%d → %d) ✓",
                                 inn, n_btns_before, n_now)
                        new_btn_appeared = True
                        break
                    else:
                        log.info("[TG] New button (%d → %d) but INN %s not in page"
                                 " — likely colleague's query, waiting…",
                                 n_btns_before, n_now, inn)
                        n_btns_before = n_now  # поднимаем планку, ждём наш
                time.sleep(1)

            if not new_btn_appeared:
                log.warning("[TG] No bot response for INN %s in 90s — aborting", inn)
                _save_screenshot(page, inn + "_no_response")
                return []

            # ── 5. Set up window.open intercept and click "Посмотреть" ─────
            page.evaluate(
                "() => { window._tg_opened_url = null;"
                " const orig = window.open;"
                " window.open = function(url, ...a) { window._tg_opened_url = url;"
                " return orig.call(window, url, ...a); }; }"
            )

            n_pages_before = len(ctx.pages)
            view_btn = page.locator('button, a', has_text='Посмотреть').last
            view_btn.wait_for(state="visible", timeout=10_000)
            view_btn.click()

            # TG may show an external-link OR a web-app confirmation dialog.
            # FIX #2: include "CONFIRM" (web-app dialog) in the list.
            time.sleep(1)
            for confirm_text in _CONFIRM_TEXTS:
                try:
                    dlg = page.locator(f'button:has-text("{confirm_text}")').first
                    if dlg.is_visible():
                        dlg.click()
                        log.info("[TG] Dismissed dialog: %s", confirm_text)
                        break
                except Exception:
                    pass

            time.sleep(2)

            # Strategy A: window.open intercepted
            report_url = page.evaluate("() => window._tg_opened_url")
            log.info("[TG] Intercepted window.open URL: %s", report_url)

            # Strategy B: new tab opened
            if not report_url:
                new_tabs = [pg for pg in ctx.pages if pg != page]
                if len(new_tabs) > (n_pages_before - 1):
                    report_url = new_tabs[-1].url
                    new_tabs[-1].close()
                    log.info("[TG] Got URL from new tab: %s", report_url)

            if not report_url:
                log.error("[TG] Could not get report URL")
                _save_screenshot(page, inn + "_no_url")
                return []

            # ── 6. Load report and extract phones ─────────────────────────
            report_tab = ctx.new_page()
            try:
                report_tab.goto(report_url, wait_until="load", timeout=30_000)
                time.sleep(2)
                html_text = report_tab.inner_text("body")
                log.info("[TG] Report content (%d chars): %r", len(html_text), html_text[:300])
                # Сохраняем полный текст для отладки
                _debug_path = f"/tmp/tg_report_{inn}.txt"
                try:
                    with open(_debug_path, "w", encoding="utf-8") as _f:
                        _f.write(html_text)
                    log.info("[TG] Full report saved → %s", _debug_path)
                except Exception:
                    pass
                report_tab.close()
            except Exception as e:
                log.error("[TG] Failed to load report: %s", e)
                _save_screenshot(page, inn + "_report_fail")
                try:
                    report_tab.close()
                except Exception:
                    pass
                return []

            # ── 7. Extract phones, filter INN-derived false positives ──────
            phones = _extract_phones(html_text, inn=inn, block_inns=block_inns)[:3]
            log.info("[TG] Phones for INN %s: %s", inn, phones)

        except Exception as e:
            log.error("[TG] Error for INN %s: %s", inn, e)
            try:
                _save_screenshot(page, inn + "_error")
            except Exception:
                pass
        finally:
            ctx.close()

    return phones
