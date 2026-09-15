"""
Тест check_duplicate: полное название + увеличенное ожидание.
python3 test_dup.py [«Название сделки»]
"""
import sys
import time
import logging
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _norm_deal_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

SEARCH_NAME = sys.argv[1] if len(sys.argv) > 1 else 'ООО "ГИС-КОМПЛЕКТ"'


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
        login(page)
        page.goto(f"{BRIZO_URL}/cabinet/deals", wait_until="domcontentloaded", timeout=30_000)
        time.sleep(3)

        # Считаем карточки до поиска
        before = page.evaluate("""() =>
            [...document.querySelectorAll('a.kanban-card-deal')]
                .filter(el => el.offsetParent !== null).length""")
        print(f"\nКарточек ДО поиска: {before}")

        # Вводим полное название + Enter
        term = SEARCH_NAME.strip()
        print(f"Ищем: «{term}»")
        search_inp = page.locator('.search-panel__input')
        search_inp.fill(term)
        time.sleep(1)
        page.screenshot(path="/tmp/brizo_dup_1_typed.png")
        print("→ /tmp/brizo_dup_1_typed.png (после ввода)")

        search_inp.press("Enter")
        time.sleep(6)

        page.screenshot(path="/tmp/brizo_dup_2_after_enter.png")
        print("→ /tmp/brizo_dup_2_after_enter.png (после Enter+6с)")

        after = page.evaluate("""() =>
            [...document.querySelectorAll('a.kanban-card-deal')]
                .filter(el => el.offsetParent !== null).length""")

        # Также прочитаем текст счётчика из хедера
        counter_text = page.evaluate("""() => {
            const el = document.querySelector('[class*="deals-count"], [class*="header"] [class*="count"]');
            return el ? el.innerText : null;
        }""")

        print(f"\nКарточек ПОСЛЕ поиска: {after}")
        print(f"Текст счётчика: {counter_text}")
        print(f"\nРезультат check_duplicate: {'ДУБЛЬ' if after > 1 else 'нет дублей'}")
        print(f"URL: {page.url}")

        browser.close()


if __name__ == "__main__":
    main()
