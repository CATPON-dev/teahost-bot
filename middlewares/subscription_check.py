
import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware, Bot, types
from aiogram.types import Update, Message, CallbackQuery, User

from admin_manager import get_all_admins
from config_manager import config
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest


def get_subscribe_keyboard(channel_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подписаться", url=f"https://t.me/{channel_id.lstrip('@')}")
    builder.button(text="🔄 Я подписался", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        
        # Пропускаем любую проверку для публичной кнопки обновления
        if isinstance(event, types.CallbackQuery) and event.data == "refresh_public_status":
            return await handler(event, data)

        user: User | None = data.get("event_from_user")

        if user and user.id in get_all_admins():
            return await handler(event, data)
        
        if config.TEST_MODE:
            logging.info(f"Test mode is ON. Ignoring update from non-admin user {user.id if user else 'Unknown'}.")
            return 

        if not user:
            return await handler(event, data) 
       
        bot: Bot = data.get("bot")
        try:
            member = await bot.get_chat_member(chat_id=self.channel_id, user_id=user.id)
            if member.status in ["left", "kicked"]:
                text = (
                    "<b>🚫 Доступ ограничен!</b>\n\n"
                    "Для использования этого бота, подпишитесь на наш канал."
                )
                markup = get_subscribe_keyboard(self.channel_id)

                if isinstance(event, Message):
                    await event.answer(text, reply_markup=markup, disable_web_page_preview=True)
                elif isinstance(event, CallbackQuery):
                    await event.answer("Для продолжения нужна подписка.", show_alert=True)
                
                return
        except TelegramBadRequest as e:
            logging.error(f"Ошибка проверки подписки: {e}. Убедитесь, что бот является администратором канала {self.channel_id}")
        except Exception as e:
            logging.error(f"Непредвиденная ошибка в SubscriptionMiddleware: {e}", exc_info=True)

        return await handler(event, data)