"""Тексти повідомлень бота."""
from __future__ import annotations

from datetime import datetime

from .schedule import Change, Slot, Zone, current_slot, merge_slots, next_change

ZONE_ICON = {Zone.GREEN: "🟢", Zone.YELLOW: "🟡", Zone.RED: "🔴"}
ZONE_NAME = {
    Zone.GREEN: "зелена зона (є світло)",
    Zone.YELLOW: "жовта зона (електропостачання можливе)",
    Zone.RED: "червона зона (відключення)",
}


def hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def change_message(change: Change, queue_name: str) -> str | None:
    """Текст сповіщення про зміну зони; None — якщо сповіщати не треба."""
    t = hhmm(change.at)
    old, new = change.old, change.new
    if old == new:
        return None
    if new == Zone.YELLOW and old == Zone.GREEN:
        return (
            f"🟡 Група {queue_name}: о {t} починається жовта зона — "
            f"можливе відключення світла."
        )
    if new == Zone.RED:
        return f"🔴 Група {queue_name}: о {t} починається червона зона — відключення світла."
    # Перехід у кращий бік: червона→жовта, жовта→зелена, червона→зелена.
    return f"💡 Група {queue_name}: о {t} можливе світло ({ZONE_ICON[new]} {ZONE_NAME[new]})."


def status_message(slots: list[Slot], now: datetime, queue_name: str, lead: int | None) -> str:
    lines = [f"Ваша група: <b>{queue_name}</b>"]
    if lead is not None:
        lines.append(f"Попереджати за: <b>{lead} хв</b>")
    current = current_slot(slots, now)
    if current is None:
        lines.append("\nДаних графіка на зараз немає.")
        return "\n".join(lines)

    lines.append(f"\nЗараз: {ZONE_ICON[current.zone]} {ZONE_NAME[current.zone]}")
    change = next_change(slots, now)
    if change:
        lines.append(f"Далі: {ZONE_ICON[change.new]} з {hhmm(change.at)}")
    else:
        lines.append("Змін до кінця відомого графіка не очікується.")

    today = now.date()
    lines.append(f"\n<b>Графік на {today.strftime('%d.%m')}:</b>")
    for part in merge_slots([s for s in slots if s.start.date() == today]):
        lines.append(f"{ZONE_ICON[part.zone]} {hhmm(part.start)}–{hhmm(part.end)}")
    return "\n".join(lines)


HELP = (
    "Я попереджаю про зміну зон у графіку відключень АТ «Миколаївобленерго».\n\n"
    "/start — підписатися та налаштувати\n"
    "/status — поточна зона та графік на сьогодні\n"
    "/group — змінити групу\n"
    "/time — змінити, за скільки хвилин попереджати\n"
    "/stop — відписатися"
)
