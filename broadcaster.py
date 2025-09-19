# broadcaster.py

import asyncio
import logging
from typing import List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound, TelegramBadRequest

logger = logging.getLogger(__name__)


async def broadcast_message(
    bot: Bot,
    users: list,
    from_chat_id: int,
    message_id: int,
    disable_notification: bool = False
):
    """
    Копирует сообщение для всех пользователей из списка.
    Сохраняет абсолютно весь контент: фото, видео, текст, форматирование, кнопки и т.д.
    """
    sent_count = 0
    failed_count = 0

    for user_id in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                disable_notification=disable_notification
            )

            sent_count += 1
            await asyncio.sleep(0.1)

        except (TelegramForbiddenError, TelegramNotFound):
            logger.info(
                f"Рассылка: пользователь {user_id} заблокировал бота или не найден.")
            failed_count += 1
        except TelegramBadRequest as e:
            logger.warning(
                f"Рассылка: не удалось отправить сообщение пользователю {user_id}. Ошибка: {e}")
            failed_count += 1
        except Exception as e:
            logger.error(
                f"Рассылка: неизвестная ошибка для пользователя {user_id}: {e}",
                exc_info=True)
            failed_count += 1

    return {"sent": sent_count, "failed": failed_count}
