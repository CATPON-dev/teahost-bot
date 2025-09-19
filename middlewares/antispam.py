import asyncio
from typing import Callable, Dict, Any, Awaitable

try:
    from cachetools import TTLCache
except ImportError:
    import subprocess
    import sys
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "cachetools"])
    from cachetools import TTLCache

from aiogram import BaseMiddleware, types

CACHE = TTLCache(maxsize=10000, ttl=1.0)


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 1.0):
        self.limit = limit

    async def __call__(
        self,
        handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
        event: types.Update,
        data: Dict[str, Any]
    ) -> Any:

        if isinstance(event, types.Message):
            user = data.get("event_from_user")

            if not user:
                return await handler(event, data)

            user_id = user.id

            if user_id in CACHE:
                return

            CACHE[user_id] = True

        return await handler(event, data)
