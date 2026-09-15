"""
setup_tg.py — ONE-TIME setup: log in to Telegram Web in our Playwright browser.
After this, tg_bot.py reuses the saved session automatically.

Run:  python3 setup_tg.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

TG_PROFILE_DIR = str(Path(__file__).parent / "tg_profile")
TG_URL = "https://web.telegram.org/a/"


def main() -> None:
    print("Opening Telegram Web...")
    print(f"Profile will be saved to: {TG_PROFILE_DIR}")
    print()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            TG_PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.goto(TG_URL, wait_until="domcontentloaded")
        print("Browser opened. Log in to Telegram Web (scan QR code).")
        print("When you see your chats — press Enter here to save and close.")
        input()
        ctx.close()
    print("Session saved. You can now use tg_bot.py.")


if __name__ == "__main__":
    main()
