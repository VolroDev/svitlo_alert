"""Обробники команд Telegram-бота."""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import KYIV, LEAD_OPTIONS
from .schedule import ScheduleService
from .storage import Storage
from .texts import HELP, status_message


def _groups_keyboard(service: ScheduleService) -> InlineKeyboardMarkup | None:
    snapshot = service.snapshot
    if not snapshot or not snapshot.queues:
        return None
    items = sorted(snapshot.queues.items(), key=lambda kv: kv[1])
    buttons = [
        InlineKeyboardButton(text=name, callback_data=f"grp:{qid}") for qid, name in items
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _lead_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{m} хв", callback_data=f"lead:{m}") for m in LEAD_OPTIONS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def build_router(storage: Storage, service: ScheduleService) -> Router:
    router = Router()

    async def ask_group(message: Message) -> None:
        keyboard = _groups_keyboard(service)
        if keyboard is None:
            await message.answer("Не вдалося отримати список груп із сайту. Спробуйте трохи пізніше.")
            return
        await message.answer("Оберіть свою групу (чергу) відключень:", reply_markup=keyboard)

    async def ask_lead(message: Message) -> None:
        await message.answer(
            "За скільки хвилин до зміни зони надсилати сповіщення?",
            reply_markup=_lead_keyboard(),
        )

    async def send_status(message: Message, chat_id: int) -> None:
        user = storage.get_user(chat_id)
        snapshot = service.snapshot
        if not user or user.queue_id is None:
            await message.answer("Групу ще не обрано. Натисніть /start.")
            return
        if snapshot is None:
            await message.answer("Графік ще не завантажено. Спробуйте трохи пізніше.")
            return
        now = datetime.now(KYIV)
        slots = snapshot.timeline(user.queue_id, now)
        await message.answer(
            status_message(slots, now, snapshot.queue_name(user.queue_id), user.lead_minutes)
        )

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        user = storage.get_user(message.chat.id)
        if user and user.configured:
            await message.answer("Ви вже підписані.\n\n" + HELP)
            await send_status(message, message.chat.id)
            return
        storage.ensure_user(message.chat.id)
        await message.answer("Вітаю! " + HELP)
        if user and user.queue_id is not None:
            await ask_lead(message)
        else:
            await ask_group(message)

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("group"))
    async def on_group(message: Message) -> None:
        await ask_group(message)

    @router.message(Command("time"))
    async def on_time(message: Message) -> None:
        await ask_lead(message)

    @router.message(Command("status"))
    async def on_status(message: Message) -> None:
        await send_status(message, message.chat.id)

    @router.message(Command("stop"))
    async def on_stop(message: Message) -> None:
        storage.delete_user(message.chat.id)
        await message.answer(
            "Ви відписалися. Щоб підписатися знову, натисніть /start "
            "(групу та час сповіщення доведеться обрати заново)."
        )

    @router.callback_query(F.data.startswith("grp:"))
    async def on_group_chosen(callback: CallbackQuery) -> None:
        queue_id = int(callback.data.split(":", 1)[1])
        user = storage.set_queue(callback.message.chat.id, queue_id)
        name = service.snapshot.queue_name(queue_id) if service.snapshot else str(queue_id)
        await callback.answer()
        await callback.message.edit_text(f"Група: <b>{name}</b> ✅")
        if user.lead_minutes is None:
            await ask_lead(callback.message)
        else:
            await send_status(callback.message, callback.message.chat.id)

    @router.callback_query(F.data.startswith("lead:"))
    async def on_lead_chosen(callback: CallbackQuery) -> None:
        minutes = int(callback.data.split(":", 1)[1])
        if minutes not in LEAD_OPTIONS:
            await callback.answer("Невідомий варіант")
            return
        user = storage.set_lead(callback.message.chat.id, minutes)
        await callback.answer()
        await callback.message.edit_text(f"Попереджатиму за <b>{minutes} хв</b> ✅")
        if user.queue_id is None:
            await ask_group(callback.message)
        else:
            await send_status(callback.message, callback.message.chat.id)

    return router
