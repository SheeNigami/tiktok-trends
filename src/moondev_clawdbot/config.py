from __future__ import annotations

from pydantic import BaseModel
from dotenv import load_dotenv
import os
from pathlib import Path


class Settings(BaseModel):
    db_path: str = "./data/clawdbot.sqlite"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    discord_webhook_url: str | None = None

    # Placeholder (not used in this repo yet, but matches the "auth via env vars" constraint)
    x_bearer_token: str | None = None


def load_settings(env_file: str | None = None) -> Settings:
    # Load .env if present
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    s = Settings(
        db_path=os.getenv("CLAWDBOT_DB_PATH", "./data/clawdbot.sqlite"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        x_bearer_token=os.getenv("X_BEARER_TOKEN") or None,
    )

    # Ensure parent dir exists
    Path(s.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return s
