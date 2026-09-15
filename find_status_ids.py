"""find_status_ids.py — найти status_id всех стадий через канбан DOM."""
import os, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import brizo

load_dotenv()
BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu", "--no-sandbox", "--disable-setuid-sandbox"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    page.route("**", lambda r: r.abort() if any(d in r.request.url for d in ["yandex.ru","mail.ru","tg-desk.com"]) else r.continue_())

    brizo.login(page)
    print(f"Страница после логина: {page.url}")

    # Kanban board is loaded — now inspect all columns
    time.sleep(2)

    # Strategy 1: find kanban columns with data attributes
    col_data = page.evaluate("""() => {
        const results = [];
        // Try various selectors for kanban columns
        const selectors = [
            '.kanban-col',
            '.kanban-column',
            '[class*="kanban-col"]',
            '[data-status-id]',
            '[data-id]',
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            if (els.length > 0) {
                results.push({
                    selector: sel,
                    count: els.length,
                    items: Array.from(els).slice(0, 15).map(el => ({
                        dataStatusId: el.getAttribute('data-status-id'),
                        dataId: el.getAttribute('data-id'),
                        id: el.id,
                        cls: el.className.slice(0, 80),
                        text: el.innerText.slice(0, 60).trim(),
                        attrs: Array.from(el.attributes).map(a => a.name + '=' + a.value).join('; '),
                    }))
                });
            }
        }
        return results;
    }""")

    print("\n=== КАНБАН КОЛОНКИ ===")
    for group in col_data:
        print(f"\nSelector: {group['selector']} (count={group['count']})")
        for item in group['items']:
            if item.get('dataStatusId') or item.get('dataId'):
                print(f"  data-status-id={item['dataStatusId']} data-id={item['dataId']} text={repr(item['text'][:40])}")

    # Strategy 2: find any element containing stage names with data attributes
    stages = page.evaluate("""() => {
        const stageNames = ['База', 'Парсю', 'Проиграно', 'Выиграно', 'Квалификация'];
        const results = {};
        for (const name of stageNames) {
            // Find all elements that contain this stage name
            const xpath = `//*[contains(text(),'${name}')]`;
            const iter = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            for (let i = 0; i < iter.snapshotLength; i++) {
                const el = iter.snapshotItem(i);
                // Walk up to find any element with a data attribute
                let parent = el;
                for (let d = 0; d < 6; d++) {
                    if (!parent) break;
                    const attrs = {};
                    Array.from(parent.attributes || []).forEach(a => {
                        if (a.name.startsWith('data-')) attrs[a.name] = a.value;
                    });
                    if (Object.keys(attrs).length > 0) {
                        if (!results[name]) results[name] = [];
                        results[name].push({
                            depth: d,
                            tag: parent.tagName,
                            attrs: attrs,
                            cls: parent.className.slice(0, 60),
                        });
                        break;
                    }
                    parent = parent.parentElement;
                }
            }
        }
        return results;
    }""")

    print("\n=== СТАДИИ И ИХ DATA-АТРИБУТЫ ===")
    for name, matches in stages.items():
        print(f"\n{name}:")
        for m in matches[:3]:
            print(f"  depth={m['depth']} tag={m['tag']} cls={m['cls'][:50]}")
            print(f"  attrs={m['attrs']}")

    # Strategy 3: check HTML source for status IDs in the page source
    html = page.content()
    import re
    # Look for status_id patterns near stage names
    for stage in ['Проиграно', 'Парсю', 'База']:
        idx = html.find(stage)
        if idx >= 0:
            window = html[max(0, idx-200):idx+200]
            ids = re.findall(r'"?(?:status_id|id)"?\s*:\s*(\d{5,})', window)
            print(f"\n'{stage}' в HTML — соседние id: {ids}")

    # Strategy 4: look at API — try /api/deals with filters
    import requests
    sess = requests.Session()
    sess.headers.update({
        "Authorization": brizo._api_state.get("bearer", ""),
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    })

    print("\n=== API ENDPOINTS ===")
    for ep in [
        "/api/statuses",
        "/api/deal_statuses",
        "/api/pipelines",
        "/api/funnels",
        "/api/stages",
    ]:
        r = sess.get(f"{BRIZO_URL}{ep}", timeout=10)
        print(f"GET {ep} → {r.status_code}: {r.text[:200]}")

    browser.close()
