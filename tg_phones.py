"""
Lookup phone numbers via a Telegram bot by company INN.

Required .env variables:
    TG_API_ID        — from https://my.telegram.org
    TG_API_HASH      — from https://my.telegram.org
    TG_PHONE         — your Telegram account phone, e.g. +79161234567
    TG_BOT_USERNAME  — bot username without @

First run: Telegram sends a login code to your account; enter it in the terminal.
The session is saved to tg_session.session and reused on all subsequent runs.
"""

import os
import re
import time
import logging

from telethon.sync import TelegramClient

log = logging.getLogger(__name__)

_SESSION  = os.path.join(os.path.dirname(__file__), "tg_session")
_POLL     = 0.5   # seconds between polls
_TIMEOUT  = 20.0  # max seconds to wait for each bot response

_PHONE_RE = re.compile(
    r'(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}'
)


def _parse_phones(text: str) -> list[str]:
    seen, result = set(), []
    for raw in _PHONE_RE.findall(text):
        digits = re.sub(r'\D', '', raw)
        norm = f"+7{digits[-10:]}"
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def _wait_update(client, entity, after_id: int, after_text: str = "",
                 timeout: float = _TIMEOUT):
    """
    Poll until the bot either:
      - sends a new message (id > after_id), or
      - edits the last message (same id, different text).
    Returns the message, or None on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = client.get_messages(entity, limit=5)
        for m in sorted(msgs, key=lambda x: x.id, reverse=True):
            if not m.text:
                continue
            if m.id > after_id:
                return m
            if m.id == after_id and m.text != after_text:
                return m
        time.sleep(_POLL)
    return None


def _click_button(client, entity, msg, text: str, after_id: int, after_text: str):
    """
    Try to click an inline keyboard button by text.
    Falls back to sending the button text as a message (for reply-keyboard bots).
    Returns the next message from the bot.
    """
    try:
        msg.click(text=text)
        log.info("TG: clicked inline button '%s'", text)
    except Exception as e:
        log.info("TG: inline click failed (%s), sending text '%s' instead", e, text)
        client.send_message(entity, text)

    return _wait_update(client, entity, after_id, after_text)


def get_phones_by_inn(inn: str) -> list[str]:
    """
    Send INN to the lookup bot, navigate its menu, return all phone numbers found.

    Flow:
      1. Send INN text
      2. Click "ИНН" button in bot response
      3. Click "Обычный поиск" button in next response
      4. Parse phone numbers from final response
    """
    bot   = os.environ["TG_BOT_USERNAME"]
    phone = os.environ["TG_PHONE"]

    client = TelegramClient(
        _SESSION,
        int(os.environ["TG_API_ID"]),
        os.environ["TG_API_HASH"],
    )
    client.start(phone=phone)

    try:
        # Baseline: remember last message before we send anything
        history = client.get_messages(bot, limit=1)
        last_id   = history[0].id   if history else 0
        last_text = history[0].text if history else ""

        # Step 1: send INN
        log.info("TG: → %s  INN=%s", bot, inn)
        client.send_message(bot, inn)

        # Step 2: wait for bot response with "ИНН" button
        msg = _wait_update(client, bot, last_id, last_text)
        if msg is None:
            log.warning("TG: no response after sending INN %s", inn)
            return []
        log.info("TG: response #%d received", msg.id)
        last_id, last_text = msg.id, msg.text or ""

        # Step 3: click "ИНН"
        msg = _click_button(client, bot, msg, "ИНН", last_id, last_text)
        if msg is None:
            log.warning("TG: no response after clicking ИНН (INN=%s)", inn)
            return []
        log.info("TG: response #%d received", msg.id)
        last_id, last_text = msg.id, msg.text or ""

        # Step 4: click "Обычный поиск"
        msg = _click_button(client, bot, msg, "Обычный поиск", last_id, last_text)
        if msg is None:
            log.warning("TG: no result after 'Обычный поиск' (INN=%s)", inn)
            return []
        log.info("TG: final response #%d received", msg.id)

        phones = _parse_phones(msg.text or "")
        log.info("TG: INN %s → %d phone(s): %s", inn, len(phones), phones)
        return phones

    finally:
        client.disconnect()
