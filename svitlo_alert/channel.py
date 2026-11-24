"""Відстеження нових записів у публічному Telegram-каналі (через t.me/s/<канал>)."""
from __future__ import annotations

import re

import aiohttp

_POST_RE = re.compile(r'data-post="[^"/]+/(\d+)"')


async def latest_post_id(session: aiohttp.ClientSession, channel: str) -> int | None:
    async with session.get(f"https://t.me/s/{channel}") as resp:
        resp.raise_for_status()
        html = await resp.text()
    ids = [int(m.group(1)) for m in _POST_RE.finditer(html)]
    return max(ids) if ids else None
