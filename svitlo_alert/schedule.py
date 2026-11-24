"""Отримання графіка з off.energy.mk.ua та розрахунок зон (зелена/жовта/червона)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path

import aiohttp

from .config import KYIV

log = logging.getLogger(__name__)

QUEUES_PATH = "/api/outage-queue/by-type/3"  # черги ГПВ (1.1, 1.2, ... 5.2)
TIME_SERIES_PATH = "/api/schedule/time-series"  # 48 півгодинних слотів доби
SCHEDULES_PATH = "/api/v2/schedule/active"  # активні графіки на сьогодні/завтра


class Zone(str, Enum):
    GREEN = "green"  # є світло
    YELLOW = "yellow"  # електропостачання можливе
    RED = "red"  # відключення (заплановане або актуальне)


# Відповідність типів з API кольорам на сайті (див. легенду під таблицею).
ZONE_BY_TYPE = {
    "ENABLE": Zone.GREEN,
    "PROBABLY_OFF": Zone.YELLOW,
    "OFF": Zone.RED,
    "SURE_OFF": Zone.RED,
}


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    zone: Zone


@dataclass(frozen=True)
class Change:
    at: datetime
    old: Zone
    new: Zone


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _parse_iso(value: str) -> datetime:
    # "2026-11-24T22:00:00.000000Z" -> aware datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Snapshot:
    """Знімок даних із сайту на певний момент часу."""

    queues: dict[int, str]  # id черги -> назва ("4.1")
    time_series: list[tuple[int, time, time]]  # (id слоту, початок, кінець)
    days: dict[date, dict[tuple[int, int], str]]  # дата -> (черга, слот) -> тип
    fetched_at: datetime
    digest: str

    @classmethod
    def from_raw(cls, raw: dict) -> Snapshot:
        queues = {
            q["id"]: q["name"]
            for q in raw["queues"]
            if not q.get("deleted")
        }
        time_series = sorted(
            (
                (t["id"], _parse_time(t["start"]), _parse_time(t["end"]))
                for t in raw["time_series"]
            ),
            key=lambda item: item[1],
        )
        days: dict[date, dict[tuple[int, int], str]] = {}
        for schedule in raw["schedules"]:
            day = _parse_iso(schedule["from"]).astimezone(KYIV).date()
            cells = days.setdefault(day, {})
            for item in schedule.get("series") or []:
                key = (item["outage_queue_id"], item["time_series_id"])
                # Як на сайті: SURE_OFF не перезаписується, інакше діє останній запис.
                if cells.get(key) != "SURE_OFF":
                    cells[key] = item["type"]
        digest = hashlib.sha256(
            json.dumps(raw["schedules"], sort_keys=True).encode()
        ).hexdigest()
        return cls(
            queues=queues,
            time_series=time_series,
            days=days,
            fetched_at=_parse_iso(raw["fetched_at"]),
            digest=digest,
        )

    def queue_name(self, queue_id: int) -> str:
        return self.queues.get(queue_id, f"#{queue_id}")

    def day_slots(self, queue_id: int, day: date, *, missing_is_green: bool) -> list[Slot] | None:
        cells = self.days.get(day)
        if cells is None:
            if not missing_is_green:
                return None
            cells = {}
        slots = []
        for ts_id, start, end in self.time_series:
            end_day = day + timedelta(days=1) if end == time(0) else day
            type_ = cells.get((queue_id, ts_id), "ENABLE")
            slots.append(
                Slot(
                    start=datetime.combine(day, start, KYIV),
                    end=datetime.combine(end_day, end, KYIV),
                    zone=ZONE_BY_TYPE.get(type_, Zone.GREEN),
                )
            )
        return slots

    def timeline(self, queue_id: int, now: datetime) -> list[Slot]:
        """Слоти на сьогодні та (якщо вже опубліковано) на завтра."""
        today = now.astimezone(KYIV).date()
        # Якщо графіка на сьогодні немає, сайт показує всю добу зеленою.
        slots = self.day_slots(queue_id, today, missing_is_green=True) or []
        # Завтрашній день враховуємо лише якщо графік на нього вже є.
        slots += self.day_slots(queue_id, today + timedelta(days=1), missing_is_green=False) or []
        return slots


def current_slot(slots: list[Slot], now: datetime) -> Slot | None:
    return next((s for s in slots if s.start <= now < s.end), None)


def next_change(slots: list[Slot], now: datetime) -> Change | None:
    """Найближча зміна кольору зони після поточного моменту."""
    current = current_slot(slots, now)
    if current is None:
        return None
    for slot in slots[slots.index(current) + 1:]:
        if slot.zone != current.zone:
            return Change(at=slot.start, old=current.zone, new=slot.zone)
    return None


def merge_slots(slots: list[Slot]) -> list[Slot]:
    """Зливає сусідні слоти однакового кольору в інтервали."""
    merged: list[Slot] = []
    for slot in slots:
        if merged and merged[-1].zone == slot.zone and merged[-1].end == slot.start:
            merged[-1] = Slot(merged[-1].start, slot.end, slot.zone)
        else:
            merged.append(slot)
    return merged


async def fetch_raw(session: aiohttp.ClientSession, base_url: str) -> dict:
    async def get(path: str):
        async with session.get(base_url + path) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    queues, time_series, schedules = await asyncio.gather(
        get(QUEUES_PATH), get(TIME_SERIES_PATH), get(SCHEDULES_PATH)
    )
    return {
        "fetched_at": datetime.now(KYIV).isoformat(),
        "queues": queues,
        "time_series": time_series,
        "schedules": schedules,
    }


class ScheduleService:
    """Зберігає останній знімок у пам'яті та у файлі-кеші."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, cache_path: Path):
        self._session = session
        self._base_url = base_url
        self._cache_path = cache_path
        self._lock = asyncio.Lock()
        self.snapshot: Snapshot | None = None

    def load_cache(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            self.snapshot = Snapshot.from_raw(raw)
            log.info("Графік завантажено з кешу (%s)", self.snapshot.fetched_at)
        except Exception:
            log.exception("Не вдалося прочитати кеш графіка")

    async def refresh(self, reason: str = "") -> bool:
        """Повертає True, якщо графік змінився."""
        async with self._lock:
            try:
                raw = await fetch_raw(self._session, self._base_url)
                snapshot = Snapshot.from_raw(raw)
            except Exception:
                log.exception("Не вдалося оновити графік з сайту")
                return False
            changed = self.snapshot is None or self.snapshot.digest != snapshot.digest
            self.snapshot = snapshot
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            log.info(
                "Графік оновлено%s: %s",
                f" ({reason})" if reason else "",
                "є зміни" if changed else "без змін",
            )
            return changed
