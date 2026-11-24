"""Налаштування з .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

KYIV = ZoneInfo("Europe/Kyiv")

# За скільки хвилин до зміни зони можна попереджати.
LEAD_OPTIONS = (5, 10, 15, 30, 60)


@dataclass(frozen=True)
class Config:
    bot_token: str
    data_dir: Path
    site_url: str
    channel: str
    channel_poll_seconds: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "svitlo.db"

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "schedule_cache.json"


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задано. Скопіюйте .env.example у .env і вкажіть токен бота.")
    return Config(
        bot_token=token,
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        site_url=os.getenv("SITE_URL", "https://off.energy.mk.ua").rstrip("/"),
        channel=os.getenv("TG_CHANNEL", "mk_energy_ua"),
        channel_poll_seconds=int(os.getenv("CHANNEL_POLL_SECONDS", "60")),
    )
