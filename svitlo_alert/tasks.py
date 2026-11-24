"""Фонові задачі: оновлення графіка, стеження за каналом, розсилка сповіщень."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from .channel import latest_post_id
from .config import KYIV
from .schedule import ScheduleService, next_change
from .storage import Storage
from .texts import change_message

log = logging.getLogger(__name__)

# Через скільки повторно перечитати сайт після нового запису в каналі
# (сайт інколи оновлюється трохи пізніше за пост).
RECHECK_AFTER_POST = timedelta(minutes=5)


async def _sleep_until_next(step_minutes: int) -> None:
    """Спить до наступної «круглої» позначки: :00, :15, :30, :45 (для step=15)."""
    now = datetime.now(KYIV)
    minute = (now.minute // step_minutes + 1) * step_minutes
    target = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    await asyncio.sleep((target - now).total_seconds())


async def schedule_loop(service: ScheduleService) -> None:
    """Кожні 15 хв (00:00, 00:15, ...) перечитує графік із сайту."""
    while True:
        await _sleep_until_next(15)
        await service.refresh("за розкладом")


async def channel_loop(
    service: ScheduleService, session: aiohttp.ClientSession, channel: str, poll_seconds: int
) -> None:
    """Перечитує графік одразу, як у каналі з'являється новий запис."""
    last_id: int | None = None
    while True:
        try:
            post_id = await latest_post_id(session, channel)
            if post_id is not None:
                if last_id is not None and post_id > last_id:
                    log.info("Новий запис у каналі @%s: %s", channel, post_id)
                    await service.refresh("новий пост у каналі")
                    asyncio.get_running_loop().call_later(
                        RECHECK_AFTER_POST.total_seconds(),
                        lambda: asyncio.ensure_future(service.refresh("повторно після посту")),
                    )
                last_id = post_id
        except Exception:
            log.warning("Не вдалося перевірити канал @%s", channel, exc_info=True)
        await asyncio.sleep(poll_seconds)


async def notify_once(bot: Bot, storage: Storage, service: ScheduleService, now: datetime) -> None:
    snapshot = service.snapshot
    if snapshot is None:
        return
    for user in storage.configured_users():
        slots = snapshot.timeline(user.queue_id, now)
        change = next_change(slots, now)
        if change is None:
            continue
        if change.at - now > timedelta(minutes=user.lead_minutes):
            continue
        if storage.was_sent(user.chat_id, change.at, change.new.value):
            continue
        text = change_message(change, snapshot.queue_name(user.queue_id))
        if text is None:
            continue
        try:
            await bot.send_message(user.chat_id, text)
            storage.mark_sent(user.chat_id, change.at, change.new.value)
        except TelegramForbiddenError:
            log.info("Користувач %s заблокував бота — видаляю підписку", user.chat_id)
            storage.delete_user(user.chat_id)
        except Exception:
            log.exception("Не вдалося надіслати сповіщення %s", user.chat_id)


async def notify_loop(bot: Bot, storage: Storage, service: ScheduleService) -> None:
    """Щохвилини перевіряє, кого час попередити про зміну зони."""
    while True:
        now = datetime.now(KYIV)
        try:
            await notify_once(bot, storage, service, now)
            storage.cleanup_sent(now)
        except Exception:
            log.exception("Помилка під час розсилки")
        await _sleep_until_next(1)
