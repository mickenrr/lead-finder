"""
One-time Telegram authorization.
Run: python3 tg_auth.py
Telegram will send a code to your account — enter it here.
Session saved to tg_session.session (reused automatically by tg_phones.py).
"""
import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient

load_dotenv()

client = TelegramClient(
    "tg_session",
    int(os.environ["TG_API_ID"]),
    os.environ["TG_API_HASH"],
)

with client:
    client.start(phone=os.environ["TG_PHONE"])
    me = client.get_me()
    print(f"\n✓ Авторизован как: {me.first_name} {me.last_name or ''} (@{me.username})")
    print("Сессия сохранена в tg_session.session — повторная авторизация не нужна.")
