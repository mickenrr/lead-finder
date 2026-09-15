"""debug_checko_search.py — как Checko ищет по ИНН."""
import os, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
BASE_URL = os.getenv("CHECKO_URL", "https://checko.ru").rstrip("/")
INN = "2332017604"  # СХП ДМИТРИЕВСКОЕ

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-gpu","--no-sandbox"])
    page = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    ).new_page()

    def _block(route):
        if any(d in route.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]):
            route.abort()
        else:
            route.continue_()
    page.route("**", _block)

    # Тест 1: Главная + автодополнение
    print("=== ТЕСТ 1: автодополнение на главной ===")
    page.goto(f"{BASE_URL}/", timeout=30000, wait_until="commit")
    time.sleep(2)
    inp = page.query_selector('input[placeholder*="Поиск"], input[placeholder*="ИНН"], input[type="search"]')
    if inp:
        inp.fill(INN)
        time.sleep(5)
        links = page.evaluate(f"""() => {{
            return Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.href.includes('/company/'))
                .map(a => ({{href: a.href, text: a.innerText.slice(0,60)}}))
                .slice(0, 10);
        }}""")
        print(f"Все /company/ ссылки после набора ИНН ({len(links)}):")
        for l in links:
            print(f"  {l['href']}  text={repr(l['text'][:50])}")
        page.screenshot(path="/private/tmp/checko_autocomplete.png")
        print("Скрин: /private/tmp/checko_autocomplete.png")
    else:
        print("Поисковый инпут не найден")

    # Тест 2: Страница поиска
    print(f"\n=== ТЕСТ 2: /search?q={INN} (networkidle) ===")
    page.goto(f"{BASE_URL}/search?q={INN}", timeout=30000, wait_until="networkidle")
    time.sleep(2)
    links2 = page.evaluate(f"""() => {{
        return Array.from(document.querySelectorAll('a[href]'))
            .filter(a => a.href.includes('/company/') && !a.href.includes('/select'))
            .map(a => ({{href: a.href, text: a.innerText.slice(0,80)}}))
            .slice(0, 10);
    }}""")
    print(f"Ссылки /company/ на странице поиска ({len(links2)}):")
    for l in links2:
        print(f"  {l['href']}  text={repr(l['text'][:60])}")
    page.screenshot(path="/private/tmp/checko_search.png")
    print("Скрин: /private/tmp/checko_search.png")

    # Тест 3: Прямая навигация по ИНН
    print(f"\n=== ТЕСТ 3: /company/{INN} (прямая ссылка) ===")
    r3 = page.goto(f"{BASE_URL}/company/{INN}", timeout=30000, wait_until="domcontentloaded")
    print(f"URL после навигации: {page.url}")
    print(f"Status: {r3.status if r3 else '?'}")

    browser.close()
    print("\nГотово.")
