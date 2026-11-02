"""Tiny Telegram Bot API client + the bot's commands.

How linking works:
  1. On the website someone clicks "Set alert". We create an Alert with a random token.
  2. They open t.me/<bot>?start=<token> and press Start. Telegram sends us "/start <token>".
  3. We store their chat id on that alert. From then on we can message them.

Commands the bot understands: /start <token>, /list, /stop

Updates arrive either by polling (laptop, GitHub Actions) or by webhook (hosted site).
To switch a hosted site to webhook mode:  python -m app.telegram set-webhook https://your-site.onrender.com
"""

from __future__ import annotations

import html
import logging
import secrets
import sys
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal
from .models import Alert

log = logging.getLogger("asol_dam.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
_username_cache: str | None = None
_stop = threading.Event()


class TelegramError(Exception):
    pass


def enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN)


def call(method: str, http_timeout: float = 15, **params) -> dict | list | bool:
    if not enabled():
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set.")
    try:
        response = httpx.post(
            API.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=params, timeout=http_timeout
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TelegramError(f"{method} failed: {exc.__class__.__name__}") from exc
    if not body.get("ok"):
        raise TelegramError(f"{method} failed: {body.get('description', 'unknown error')}")
    return body["result"]


def send(chat_id: str | int, text: str) -> None:
    call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)


def bot_username() -> str:
    global _username_cache
    if config.TELEGRAM_BOT_USERNAME:
        return config.TELEGRAM_BOT_USERNAME
    if _username_cache is None:
        _username_cache = call("getMe")["username"]
    return _username_cache


def new_token() -> str:
    return secrets.token_urlsafe(12)  # 16 chars, fits Telegram's 64-char start parameter


def start_link(token: str) -> str:
    return f"https://t.me/{bot_username()}?start={token}"


# ---- commands ------------------------------------------------------------

HELP = (
    "Hi! I'm the Ashol Dam bot. I message you when a Daraz price you're watching really drops.\n\n"
    "To set an alert, open a product on the Ashol Dam website and press <b>Set alert</b>.\n\n"
    "/list shows your alerts\n/stop turns them all off"
)


def handle_update(session: Session, update: dict) -> None:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if not text or not chat_id:
        return

    command, _, argument = text.partition(" ")
    command = command.split("@")[0].lower()

    if command == "/start" and argument:
        alert = session.scalar(select(Alert).where(Alert.token == argument.strip()))
        if alert is None:
            send(chat_id, "That alert link has expired. Set the alert again on the website.")
            return
        if alert.chat_id == chat_id and alert.active:
            return  # same Start pressed twice (or update delivered twice)
        alert.chat_id = chat_id
        alert.active = True
        session.commit()
        from .alerts import describe  # local import avoids a cycle

        send(chat_id, f"✅ Alert set.\n\n{describe(alert)}\n\nI'll message you here. Send /stop to turn alerts off.")
    elif command == "/start":
        send(chat_id, HELP)
    elif command == "/list":
        alerts = session.scalars(select(Alert).where(Alert.chat_id == chat_id, Alert.active.is_(True))).all()
        if not alerts:
            send(chat_id, "You have no active alerts.")
        else:
            from .alerts import describe

            send(chat_id, "Your alerts:\n\n" + "\n\n".join(describe(a) for a in alerts))
    elif command == "/stop":
        alerts = session.scalars(select(Alert).where(Alert.chat_id == chat_id, Alert.active.is_(True))).all()
        for alert in alerts:
            alert.active = False
        session.commit()
        send(chat_id, f"Turned off {len(alerts)} alert{'s' if len(alerts) != 1 else ''}. Set new ones any time on the website.")
    else:
        send(chat_id, HELP)


def process_updates(session: Session, timeout: int = 0) -> int:
    """Fetch waiting messages, handle them, then confirm them so they aren't sent again."""
    updates = call("getUpdates", http_timeout=timeout + 10, timeout=timeout, allowed_updates=["message"])
    for update in updates:
        try:
            handle_update(session, update)
        except TelegramError as exc:
            log.warning("Couldn't answer a Telegram message: %s", exc)
    if updates:
        call("getUpdates", offset=updates[-1]["update_id"] + 1, timeout=0)
    return len(updates)


def _poll_loop() -> None:
    while not _stop.is_set():
        try:
            with SessionLocal() as session:
                process_updates(session, timeout=25)
        except TelegramError as exc:
            log.warning("Telegram polling: %s", exc)
            _stop.wait(30)


def start_polling() -> None:
    if not enabled() or config.TELEGRAM_MODE != "polling":
        return
    try:
        call("deleteWebhook")  # polling and webhooks can't be used at the same time
    except TelegramError as exc:
        log.warning("Telegram: %s", exc)
    _stop.clear()
    threading.Thread(target=_poll_loop, name="telegram-poll", daemon=True).start()


def stop_polling() -> None:
    _stop.set()


def escape(text: str) -> str:
    return html.escape(text, quote=False)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "set-webhook":
        if not config.TELEGRAM_WEBHOOK_SECRET:
            sys.exit("Set TELEGRAM_WEBHOOK_SECRET first (any long random string).")
        url = sys.argv[2].rstrip("/") + f"/api/telegram/webhook/{config.TELEGRAM_WEBHOOK_SECRET}"
        call("setWebhook", url=url, allowed_updates=["message"])
        print(f"Webhook set. Telegram will now send messages to {url}")
    elif len(sys.argv) == 2 and sys.argv[1] == "delete-webhook":
        call("deleteWebhook")
        print("Webhook removed. Polling mode works again.")
    else:
        print("Usage: python -m app.telegram set-webhook https://your-site  |  delete-webhook")
