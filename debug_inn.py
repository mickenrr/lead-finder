"""debug_inn.py — проверяем, есть ли ИНН в карточке сделки и в каком виде."""

import json
import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BRIZO_URL = os.getenv("BRIZO_URL", "https://sad1.brizo.ru").rstrip("/")
LOGIN_URL  = f"{BRIZO_URL}/cabinet/login"

DEAL_ID = "1742291"  # ООО "МАКСИМУМ" — первый лид из run17


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        _bearer = {"v": ""}
        def _on_req(req):
            if "sad1.brizo.ru/api" in req.url:
                a = req.headers.get("authorization", "")
                if a.startswith("Bearer "):
                    _bearer["v"] = a
        page.on("request", _on_req)

        def _block(route):
            if any(d in route.request.url for d in ["yandex.ru", "mail.ru", "tg-desk.com"]):
                route.abort()
            else:
                route.continue_()
        page.route("**", _block)

        print("Логинимся...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector('input[type="email"]', timeout=30_000)
        page.locator('input[type="email"]').fill(os.getenv("BRIZO_EMAIL", ""))
        page.locator('input[type="password"]').fill(os.getenv("BRIZO_PASSWORD", ""))
        page.locator('button[type="submit"]').click()
        page.wait_for_url(lambda u: "/cabinet/" in u and "login" not in u, timeout=60_000)
        print(f"Зашли: {page.url}")
        time.sleep(3)

        # Открываем сделку
        print(f"\nОткрываем сделку {DEAL_ID}...")
        page.goto(f"{BRIZO_URL}/cabinet/deals#deal/{DEAL_ID}/main", timeout=60_000)
        time.sleep(4)

        # 1. Все .base-input поля — с ЛЮБЫМ значением или без
        print("\n=== ВСЕ .base-input ПОЛЯ (включая пустые) ===")
        all_fields = page.evaluate("""() => {
            const result = [];
            for (const c of document.querySelectorAll('.base-input')) {
                const lbl = c.querySelector('.base-input__label-text');
                const inp = c.querySelector('input, textarea, select');
                const r = c.getBoundingClientRect();
                if (!lbl || r.height < 1) continue;
                result.push({
                    label: lbl.innerText.trim(),
                    value: inp ? inp.value : '',
                    tagName: inp ? inp.tagName : 'NO_INPUT',
                    classes: inp ? inp.className.slice(0, 80) : '',
                    readonly: inp ? inp.readOnly : null,
                    visible: r.height > 0,
                });
            }
            return result;
        }""")
        for f in all_fields:
            print(json.dumps(f, ensure_ascii=False))

        # 2. Текст в карточке, который может содержать ИНН (10 цифр)
        print("\n=== ТЕКСТ НА СТРАНИЦЕ, ПОХОЖИЙ НА ИНН (10 цифр) ===")
        inn_candidates = page.evaluate("""() => {
            const text = document.body.innerText;
            const matches = [...text.matchAll(/\\b\\d{10,12}\\b/g)];
            return matches.map(m => ({
                match: m[0],
                context: text.slice(Math.max(0, m.index - 30), m.index + 40).replace(/\\n/g, ' ')
            }));
        }""")
        for c in inn_candidates[:20]:
            print(json.dumps(c, ensure_ascii=False))

        # 3. REST API — GET /api/deals/{id}
        if _bearer["v"]:
            import requests as _req
            sess = _req.Session()
            sess.headers.update({
                "Authorization": _bearer["v"],
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            })
            print(f"\n=== REST API: GET /api/deals/{DEAL_ID} ===")
            r = sess.get(f"{BRIZO_URL}/api/deals/{DEAL_ID}", timeout=10)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                # Печатаем ключи верхнего уровня
                print("Ключи:", list(data.keys()))
                # Кастомные поля
                for k in ("custom_fields", "fields", "properties", "attributes"):
                    if data.get(k):
                        print(f"  {k}:", json.dumps(data[k], ensure_ascii=False)[:500])
                # Полный ответ (первые 2000 символов)
                print("\nПолный ответ (2000 символов):")
                print(json.dumps(data, ensure_ascii=False)[:2000])
        else:
            print("\nBearer не захвачен — API тест пропущен")

        # 4. Маппинг field_id → name
        if _bearer["v"]:
            import requests as _req
            sess = _req.Session()
            sess.headers.update({
                "Authorization": _bearer["v"],
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            })
            print("\n=== МАППИНГ field_id → name (GET /api/fields?model_id=1) ===")
            rf = sess.get(f"{BRIZO_URL}/api/fields?model_id=1", timeout=10)
            field_map = {}
            for f in rf.json().get("data", []):
                field_map[f["id"]] = f["name"]
                print(f"  {f['id']}  type={f['type_id']}  name={f['name']}")

            print("\n=== СДЕЛКА 1742291 С ИМЕНАМИ ПОЛЕЙ ===")
            r2 = sess.get(f"{BRIZO_URL}/api/deals/1742291", timeout=10)
            for f in r2.json().get("fields", []):
                print(f"  [{f['id']}] {field_map.get(f['id'], '???')}: {repr(f['value'])}")

        browser.close()
        print("\nГотово.")


if __name__ == "__main__":
    main()
