from __future__ import annotations

import json
import requests
from typing import Iterable

from .models import Item
from .config import Settings


def format_item(it: Item) -> str:
    s = it.score if it.score is not None else 0.0
    lines = [
        f"[{it.source}] score={s:.2f}",
        it.title.strip(),
        it.url,
    ]
    return "\n".join(lines)


def send_stdout(items: Iterable[Item]) -> None:
    for it in items:
        print("-" * 60)
        print(format_item(it))


def send_discord(webhook_url: str, items: Iterable[Item]) -> None:
    content = "\n\n".join(format_item(it) for it in items)
    if not content.strip():
        return
    # Discord has 2000 char limit; keep it small.
    content = content[:1900]
    r = requests.post(webhook_url, json={"content": content}, timeout=30)
    r.raise_for_status()


def send_telegram(bot_token: str, chat_id: str, items: Iterable[Item]) -> None:
    text = "\n\n".join(format_item(it) for it in items)
    if not text.strip():
        return
    text = text[:3500]
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False}, timeout=30)
    r.raise_for_status()


def alert(settings: Settings, items: list[Item], channel: str = "auto") -> None:
    if channel == "stdout":
        send_stdout(items)
        return

    if channel == "discord":
        if not settings.discord_webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL not set")
        send_discord(settings.discord_webhook_url, items)
        return

    if channel == "telegram":
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            raise ValueError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")
        send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, items)
        return

    # auto: prefer telegram then discord else stdout
    if settings.telegram_bot_token and settings.telegram_chat_id:
        send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, items)
    elif settings.discord_webhook_url:
        send_discord(settings.discord_webhook_url, items)
    else:
        send_stdout(items)
