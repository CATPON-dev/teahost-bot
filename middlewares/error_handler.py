import traceback
import math
import logging
from aiogram import Bot, F, html  # Заменено
from aiogram.types import ErrorEvent, Message, CallbackQuery, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from admin_manager import get_all_admins

TRACEBACK_LINES_PER_PAGE = 30
MAX_CACHE_SIZE = 100
error_cache = {}


def get_traceback_paginator_keyboard(
        error_id: str,
        page: int,
        total_pages: int):
    # ... (код без изменений)
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="« 1",
                callback_data=f"error_page:{error_id}:1"))
        nav_buttons.append(
            InlineKeyboardButton(
                text="‹",
                callback_data=f"error_page:{error_id}:{page-1}"))
    nav_buttons.append(
        InlineKeyboardButton(
            text=f"· {page}/{total_pages} ·",
            callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(
                text="›",
                callback_data=f"error_page:{error_id}:{page+1}"))
        nav_buttons.append(
            InlineKeyboardButton(
                text=f"{total_pages} »",
                callback_data=f"error_page:{error_id}:{total_pages}"))
    builder.row(*nav_buttons)
    return builder.as_markup()


async def handle_errors(event: ErrorEvent, bot: Bot):
    # ... (код без изменений)
    if len(error_cache) >= MAX_CACHE_SIZE:
        try:
            del error_cache[next(iter(error_cache))]
        except StopIteration:
            pass

    logging.exception(
        f"Cause exception: {event.exception}\nUpdate: {event.update}")
    exception_traceback = traceback.format_exc()
    error_id = str(event.update.update_id)
    error_cache[error_id] = exception_traceback.strip().split('\n')

    user_info, user_id, update_text = "N/A", "N/A", "N/A"

    if isinstance(event.update.message, Message):
        user = event.update.message.from_user
        user_id = user.id
        user_info = f"@{user.username}" if user.username else user.full_name
        update_text = event.update.message.text or "[не_текст]"
    elif isinstance(event.update.callback_query, CallbackQuery):
        user = event.update.callback_query.from_user
        user_id = user.id
        user_info = f"@{user.username}" if user.username else user.full_name
        update_text = f"Callback: {event.update.callback_query.data}"

    admin_error_text = (
        f"<b>⚠️ Произошла ошибка!</b>\n\n"
        f"<b>Пользователь:</b> {html.quote(user_info)} (<code>{user_id}</code>)\n"
        f"<b>Действие:</b> <pre>{html.quote(update_text)}</pre>\n\n"
        f"<b>Traceback (ID: {error_id}):</b>")

    total_pages = math.ceil(
        len(error_cache[error_id]) / TRACEBACK_LINES_PER_PAGE)
    page_lines = error_cache[error_id][:TRACEBACK_LINES_PER_PAGE]
    page_content = "\n".join(page_lines)
    full_admin_text = f"{admin_error_text}\n<pre>{html.quote(page_content)}</pre>"

    admins_to_notify = get_all_admins()
    for admin_id in admins_to_notify:
        try:
            markup = get_traceback_paginator_keyboard(
                error_id, 1, total_pages) if total_pages > 1 else None
            await bot.send_message(chat_id=admin_id, text=full_admin_text, reply_markup=markup)
        except TelegramForbiddenError:
            logging.warning(
                f"Не удалось отправить уведомление об ошибке админу {admin_id}: пользователь не начал диалог с ботом")
        except Exception as e:
            logging.error(
                f"Не удалось отправить уведомление об ошибке админу {admin_id}: {e}")

    user_error_text = "<b>🚫 Error!</b>\n\nI messaged admins about it."

    if isinstance(event.update.message, Message):
        try:
            await event.update.message.answer(user_error_text)
        except Exception:
            pass
    elif isinstance(event.update.callback_query, CallbackQuery):
        try:
            await event.update.callback_query.message.answer(user_error_text)
        except Exception:
            pass


async def handle_error_page_callback(call: CallbackQuery):
    _, error_id, page_str = call.data.split(":")
    page = int(page_str)

    error_lines = error_cache.get(error_id)
    if not error_lines:
        await call.answer("Лог этой ошибки устарел и был очищен.", show_alert=True)
        return

    total_pages = math.ceil(len(error_lines) / TRACEBACK_LINES_PER_PAGE)
    start_index = (page - 1) * TRACEBACK_LINES_PER_PAGE
    end_index = start_index + TRACEBACK_LINES_PER_PAGE
    page_lines = error_lines[start_index:end_index]
    page_content = "\n".join(page_lines)

    original_text_parts = call.message.html_text.split('<pre>')
    if len(original_text_parts) > 0:
        original_text = original_text_parts[0]
        new_text = f"{original_text}<pre>{html.quote(page_content)}</pre>"
        markup = get_traceback_paginator_keyboard(error_id, page, total_pages)
        try:
            await call.message.edit_text(new_text, reply_markup=markup)
        except Exception:
            await call.answer()
    else:
        await call.answer("Не удалось обновить лог.", show_alert=True)
