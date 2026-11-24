"""Збереження підписників та вже надісланих сповіщень (SQLite)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class User:
    chat_id: int
    queue_id: int | None
    lead_minutes: int | None

    @property
    def configured(self) -> bool:
        return self.queue_id is not None and self.lead_minutes is not None


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id      INTEGER PRIMARY KEY,
                queue_id     INTEGER,
                lead_minutes INTEGER,
                created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sent (
                chat_id   INTEGER NOT NULL,
                change_at TEXT NOT NULL,
                zone      TEXT NOT NULL,
                PRIMARY KEY (chat_id, change_at, zone)
            );
            """
        )
        self._db.commit()

    def get_user(self, chat_id: int) -> User | None:
        row = self._db.execute(
            "SELECT chat_id, queue_id, lead_minutes FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return User(*row) if row else None

    def ensure_user(self, chat_id: int) -> User:
        self._db.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
        self._db.commit()
        return self.get_user(chat_id)

    def set_queue(self, chat_id: int, queue_id: int) -> User:
        self.ensure_user(chat_id)
        self._db.execute("UPDATE users SET queue_id = ? WHERE chat_id = ?", (queue_id, chat_id))
        # Нова група — старі позначки про надіслане вже не актуальні.
        self._db.execute("DELETE FROM sent WHERE chat_id = ?", (chat_id,))
        self._db.commit()
        return self.get_user(chat_id)

    def set_lead(self, chat_id: int, minutes: int) -> User:
        self.ensure_user(chat_id)
        self._db.execute("UPDATE users SET lead_minutes = ? WHERE chat_id = ?", (minutes, chat_id))
        self._db.commit()
        return self.get_user(chat_id)

    def delete_user(self, chat_id: int) -> None:
        self._db.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        self._db.execute("DELETE FROM sent WHERE chat_id = ?", (chat_id,))
        self._db.commit()

    def configured_users(self) -> list[User]:
        rows = self._db.execute(
            "SELECT chat_id, queue_id, lead_minutes FROM users "
            "WHERE queue_id IS NOT NULL AND lead_minutes IS NOT NULL"
        ).fetchall()
        return [User(*row) for row in rows]

    def was_sent(self, chat_id: int, change_at: datetime, zone: str) -> bool:
        return self._db.execute(
            "SELECT 1 FROM sent WHERE chat_id = ? AND change_at = ? AND zone = ?",
            (chat_id, change_at.isoformat(), zone),
        ).fetchone() is not None

    def mark_sent(self, chat_id: int, change_at: datetime, zone: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO sent (chat_id, change_at, zone) VALUES (?, ?, ?)",
            (chat_id, change_at.isoformat(), zone),
        )
        self._db.commit()

    def cleanup_sent(self, now: datetime) -> None:
        cutoff = (now - timedelta(days=2)).isoformat()
        self._db.execute("DELETE FROM sent WHERE change_at < ?", (cutoff,))
        self._db.commit()
