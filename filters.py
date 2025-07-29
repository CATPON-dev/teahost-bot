# --- START OF FILE filters.py ---
import logging
from aiogram.filters import BaseFilter
from aiogram import types, html, Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_manager import get_all_admins
from middlewares import techwork as maintenance_manager
from config_manager import config
import database as db
import keyboards as kb

class IsBotEnabled(BaseFilter):
    async def __call__(self, update: types.Update) -> bool:
        user = getattr(update, 'from_user', None)
        if not user:
            return False

        # Администраторы всегда имеют доступ
        if user.id in get_all_admins():
            return True
            
        # Если режим техработ включен
        if maintenance_manager.is_maintenance_mode():
            # Определяем чат, в котором произошло событие
            chat = None
            if isinstance(update, types.Message):
                chat = update.chat
            elif isinstance(update, types.CallbackQuery):
                chat = update.message.chat
            
            # Если это личные сообщения, отправляем уведомление о техработах
            if chat and chat.type == "private":
                text = (
                    "<b>⚠️ SharkHost is undergoing maintenance</b>\n\n"
                    "<i>We will notify you about the completion of maintenance in the channel or support chat.</i>"
                )
                
                builder = InlineKeyboardBuilder()
                builder.button(text="💬 Support Chat", url="https://t.me/SharkHost_support")
                builder.button(text="📢 Channel", url="https://t.me/Shark_Host")
                builder.adjust(2)
                markup = builder.as_markup()

                if isinstance(update, types.CallbackQuery):
                    await update.answer("Бот на технических работах.", show_alert=True)
                elif isinstance(update, types.Message):
                    await update.answer(text, reply_markup=markup)
            
            # В любом случае (и в ЛС, и в чате) блокируем дальнейшую обработку
            return False
            
        # Если техработы выключены, разрешаем обработку
        return True

class IsAdmin(BaseFilter):
    async def __call__(self, update: types.Update) -> bool:
        user = getattr(update, 'from_user', None)
        if not user:
            return False
        return user.id in get_all_admins()

class IsSuperAdmin(BaseFilter):
    async def __call__(self, update: types.Update) -> bool:
        user = getattr(update, 'from_user', None)
        if not user:
            return False
        return user.id in config.SUPER_ADMIN_IDS

class IsSubscribed(BaseFilter):
    async def __call__(self, update: types.Update, bot: Bot) -> bool:
        user = getattr(update, 'from_user', None)
        if not user:
            return False

        if user.id in get_all_admins():
            return True
            
        if config.TEST_MODE:
            return True

        try:
            member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user.id)
            if member.status in ["left", "kicked"]:
                text = (
                    "<b>🚫 Доступ ограничен!</b>\n\n"
                    "Для использования этой функции, пожалуйста, подпишитесь на наш канал."
                )
                markup = kb.get_subscribe_keyboard(config.CHANNEL_ID)
                
                if isinstance(update, types.CallbackQuery):
                    await update.answer("Для продолжения нужна подписка.", show_alert=True)
                    await update.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
                elif isinstance(update, types.Message):
                    await update.answer(text, reply_markup=markup, disable_web_page_preview=True)
                
                return False
        except Exception as e:
            logging.error(f"Ошибка проверки подписки в фильтре IsSubscribed для user_id {user.id}: {e}")
            return True

        return True
# --- END OF FILE filters.py ---