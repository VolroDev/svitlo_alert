"""svitlo_alert — Telegram-бот із попередженнями про зміну зон у графіку відключень."""
import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from svitlo_alert.bot import build_router
from svitlo_alert.config import load_config
from svitlo_alert.schedule import ScheduleService
from svitlo_alert.storage import Storage
from svitlo_alert.tasks import channel_loop, notify_loop, schedule_loop

COMMANDS = [
    BotCommand(command="status", description="Поточна зона та графік"),
    BotCommand(command="group", description="Змінити групу"),
    BotCommand(command="time", description="Змінити час попередження"),
    BotCommand(command="stop", description="Відписатися"),
    BotCommand(command="help", description="Довідка"),
]


async def run() -> None:
    config = load_config()
    storage = Storage(config.db_path)
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (svitlo_alert bot)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        service = ScheduleService(session, config.site_url, config.cache_path)
        service.load_cache()
        # Під час запуску одразу аналізуємо таблицю з сайту.
        await service.refresh("запуск")

        bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        dp.include_router(build_router(storage, service))
        await bot.set_my_commands(COMMANDS)

        background = [
            asyncio.create_task(schedule_loop(service)),
            asyncio.create_task(
                channel_loop(service, session, config.channel, config.channel_poll_seconds)
            ),
            asyncio.create_task(notify_loop(bot, storage, service)),
        ]
        try:
            await dp.start_polling(bot)
        finally:
            for task in background:
                task.cancel()
            await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run())
