"""Debug: print raw Checko text around director/founder sections."""
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL
import checko as checko_module
from checko import get_company_data, _resolve_url, _get

load_dotenv()

# ООО "ПРОГРЕСС ЛИФТ" — INN 7733615696; Жуляев should have INN
TEST_INN = "7733615696"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    checko_page = ctx.new_page()
    checko_module.set_pw_page(checko_page)
    login(page)

    print(f"\n=== Resolving URL for INN {TEST_INN} ===")
    url = _resolve_url(TEST_INN)
    print(f"URL: {url}")
    browser.close()

if url:
    resp = _get(url)
    if resp:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        # Print 500 chars around each occurrence of "учредитель" (case-insensitive)
        print(f"\n=== All 'учредитель' occurrences ===")
        for m in re.finditer(r"[Уу]чредитель", text):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 300)
            print(f"\n[pos {m.start()}]")
            print(repr(text[start:end]))
            print()

        # Print 500 chars around "директор"
        print(f"\n=== All 'директор' occurrences ===")
        for m in re.finditer(r"[Дд]иректор", text):
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 300)
            print(f"\n[pos {m.start()}]")
            print(repr(text[start:end]))
            print()

        # What does current parser extract from text?
        import json
        from checko import _parse_company_page
        parsed = _parse_company_page(text, url)
        print("\n=== Current parser result ===")
        print(json.dumps({
            "director_name": parsed.get("director_name"),
            "director_inn": parsed.get("director_inn"),
            "founders": parsed.get("founders"),
        }, ensure_ascii=False, indent=2))
