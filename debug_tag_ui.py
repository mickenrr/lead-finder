"""debug_tag_ui.py — inspect Vue data of tag-select and GET funnels + project tags."""
import json, time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from brizo import login, BRIZO_URL, _get_api_session
import checko as checko_module

load_dotenv()

CONTACT_ID = "837278"
all_resp = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()
    checko_module.set_pw_page(ctx.new_page())

    def on_resp(resp):
        if "sad1.brizo.ru/api" in resp.url:
            try:
                all_resp[resp.url] = resp.json()
            except:
                pass

    page.on("response", on_resp)
    login(page)

    page.goto(f"{BRIZO_URL}/cabinet/contragents/{CONTACT_ID}",
              wait_until="domcontentloaded", timeout=30_000)
    time.sleep(3)

    # Click tag-select to trigger the GET
    tag_inp = page.locator(".tag-select input").first
    tag_inp.scroll_into_view_if_needed()
    tag_inp.click()
    time.sleep(2)

    # Deep inspect Vue component tree to find where "САД" and "FL" come from
    vue_inspect = page.evaluate("""() => {
        function getVm(el) {
            if (!el) return null;
            if (el.__vue__) return el.__vue__;
            if (el.__vueParentComponent) return el.__vueParentComponent;
            return null;
        }
        function findOptions(vm, depth=0) {
            if (!vm || depth > 10) return null;
            const d = vm.$data || {};
            for (const key of Object.keys(d)) {
                const val = d[key];
                if (Array.isArray(val) && val.length > 0 && val.length < 50) {
                    const sample = val[0];
                    if (sample && typeof sample === 'object' && ('name' in sample || 'title' in sample)) {
                        return {key, depth, sample: val.slice(0,5)};
                    }
                }
            }
            return findOptions(vm.$parent, depth+1);
        }
        const el = document.querySelector('.tag-select');
        const vm = getVm(el);
        if (!vm) return 'no vm';
        // Walk up to find data with tag list
        let result = findOptions(vm);
        return result;
    }""")
    print(f"Vue option data found: {json.dumps(vue_inspect, ensure_ascii=False, indent=2)[:1000]}")

    # Also look at the tag select that's opened and find its options via __vue__
    options_from_vue = page.evaluate("""() => {
        // Find the opened dropdown
        const opened = document.querySelector('.base-input_opened-dropdown');
        if (!opened) return 'no opened dropdown';
        function getVm(el) {
            if (el.__vue__) return el.__vue__;
            if (el.__vueParentComponent) return el.__vueParentComponent;
            return null;
        }
        const vm = getVm(opened);
        if (!vm) return 'no vue on opened';
        // Look for 'options', 'items', 'tags', etc in data chain
        const results = [];
        let cur = vm;
        let depth = 0;
        while (cur && depth < 15) {
            const d = cur.$data || cur.data || {};
            for (const k of Object.keys(d)) {
                if (['options','items','tags','list','values','choices'].includes(k) && Array.isArray(d[k])) {
                    results.push({depth, key: k, len: d[k].length, sample: d[k].slice(0,3)});
                }
            }
            // Also check props
            const p = cur.$props || {};
            for (const k of Object.keys(p)) {
                if (['options','items','tags','list','values','choices'].includes(k) && Array.isArray(p[k])) {
                    results.push({depth, key: 'PROP:'+k, len: p[k].length, sample: p[k].slice(0,3)});
                }
            }
            cur = cur.$parent;
            depth++;
        }
        return results;
    }""")
    print(f"\nOptions found in Vue chain: {json.dumps(options_from_vue, ensure_ascii=False, indent=2)[:1000]}")

    page.keyboard.press("Escape")
    browser.close()

# Check funnels and project tags
sess = _get_api_session()
print("\n=== GET /api/funnels ===")
r = sess.get(f"{BRIZO_URL}/api/funnels", timeout=10)
d = r.json()
print(json.dumps(d, ensure_ascii=False, indent=2)[:2000])

print("\n=== GET /api/purposes ===")
r2 = sess.get(f"{BRIZO_URL}/api/purposes", timeout=10)
print(f"Status: {r2.status_code}, Body: {r2.text[:500]}")

print("\n=== GET /api/tags?model_id=2 ===")
r3 = sess.get(f"{BRIZO_URL}/api/tags?model_id=2", timeout=10)
print(f"Status: {r3.status_code}, Body: {r3.text[:500]}")
