# --- START OF FILE user_handlers.py ---
import logging
import asyncio
import secrets
from datetime import datetime, timedelta
import re
import time
from datetime import datetime
import pytz
import locale
import secrets
from collections import defaultdict
from aiogram import Bot, Router, types, F, html
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramForbiddenError
from aiogram.types import InputMediaPhoto, FSInputFile, InputFile
from aiogram.types import InlineQuery, InputTextMessageContent, InlineQueryResultArticle, InlineQueryResultPhoto, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hlink
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
import html as py_html
import traceback

import keyboards as kb
import system_manager as sm
import server_config
import database as db
from states import UserBotSetup, UserBotTransfer, UserReview, CommitEditing, APITokenManagement
from admin_manager import get_all_admins
from config_manager import config
from channel_logger import log_event
from filters import IsBotEnabled, IsSubscribed
from system_manager import get_service_process_uptime

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsBotEnabled())
router.callback_query.filter(IsBotEnabled())

LOG_LINES_PER_PAGE = 25

review_warned_users = defaultdict(lambda: False)

class UserBotShare(StatesGroup):
    ConfirmingRevoke = State()
    WaitingForShareUserID = State()
    ConfirmingShare = State()
    WaitingForShareAccept = State()

def _create_progress_bar(percent_str: str, length: int = 10) -> str:
    try:
        percent = float(str(percent_str).replace('%',''))
        filled_length = int(length * percent / 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}]"
    except (ValueError, TypeError):
        return f"[{'?' * length}]"

def get_greeting():
    now = datetime.now(pytz.timezone("Europe/Moscow"))
    if 5 <= now.hour < 12: return "☀️ Доброе утро"
    elif 12 <= now.hour < 17: return "👋 Добрый день"
    elif 17 <= now.hour < 23: return "🌃 Добрый вечер"
    else: return "🌙 Доброй ночи"

def seconds_to_human_readable(seconds):
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{int(days)}d")
    if hours:
        parts.append(f"{int(hours)}h")
    if minutes:
        parts.append(f"{int(minutes)}m")
    return " ".join(parts) if parts else "~1m"

async def _show_main_panel(bot: Bot, chat_id: int, user_id: int, user_name: str, state: FSMContext, message_id: int = None, topic_id: int = None, owner_id: int = None):
    from bot import BANNER_FILE_IDS
    await state.clear()
    user_bots = await db.get_userbots_by_tg_id(user_id)
    is_chat = False
    if owner_id is None:
        owner_id = user_id
    if str(chat_id).startswith("-"):
        is_chat = True
    text = (f"<b>{get_greeting()}, {html.quote(user_name)}!</b>\n\n"
            f"<blockquote>🦈 Добро пожаловать в панель управления хостингом <b>SharkHost</b>. "
            f"Здесь вы можете легко управлять своими юзерботами.</blockquote>")
    markup = kb.get_main_panel_keyboard(has_bots=bool(user_bots), user_id=owner_id, chat_id=chat_id, is_chat=is_chat)
    photo = BANNER_FILE_IDS.get("main_panel") or FSInputFile("banners/select_action.png")

    if message_id:
        try:
            await bot.edit_message_media(
                media=InputMediaPhoto(media=photo, caption=text),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup
            )
        except TelegramBadRequest:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramNotFound):
                pass
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=text, reply_markup=markup, message_thread_id=topic_id)
    else:
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=text, reply_markup=markup, message_thread_id=topic_id)
        
async def show_management_panel(call_or_message: types.Message | types.CallbackQuery, ub_username: str, state: FSMContext = None):
    from bot import BANNER_FILE_IDS
    is_callback = isinstance(call_or_message, types.CallbackQuery)
    message = call_or_message.message if is_callback else call_or_message
    user = call_or_message.from_user
    bot = message.bot
    
    if state: await state.clear()
        
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        if isinstance(call_or_message, types.CallbackQuery):
            await call_or_message.answer("❌ Этот юзербот был удален или у вас нет доступа.", show_alert=True)
        await _show_main_panel(bot=bot, chat_id=message.chat.id, user_id=user.id, user_name=user.full_name, state=state, message_id=message.message_id, topic_id=message.message_thread_id)
        return

    if ub_data.get('status') == 'installing':
        if isinstance(call_or_message, types.CallbackQuery):
            await call_or_message.answer("⏳ Установка юзербота в процессе...\n\nПанель управления будет доступна после завершения установки.", show_alert=True)
        else:
            await message.answer("⏳ <b>Установка юзербота в процессе...</b>\n\nПанель управления будет доступна после завершения установки и настройки всех систем безопасности.", parse_mode="HTML")
        return
    
    if ub_data.get('status') == 'deleting':
        if isinstance(call_or_message, types.CallbackQuery):
            await call_or_message.answer("🗑️ Удаление юзербота в процессе...\n\nПанель управления недоступна во время удаления.", show_alert=True)
        else:
            await message.answer("🗑️ <b>Удаление юзербота в процессе...</b>\n\nПанель управления недоступна во время удаления юзербота.", parse_mode="HTML")
        return
    
    server_ip = ub_data.get('server_ip', 'N/A')
    
    is_server_active_str = server_config.get_server_status_by_ip(server_ip)
    is_server_active = is_server_active_str not in ["false", "not_found"]
    
    is_running = await sm.is_service_active(f"hikka-{ub_username}.service", server_ip) if is_server_active else False
    
    server_details = server_config.get_servers().get(server_ip, {})
    flag = server_details.get("flag", "🏳️")
    server_code = server_details.get("code", "N/A")
    server_display = f"{flag} {server_code}"
    server_location = f"{server_details.get('country', 'N/A')}, {server_details.get('city', 'N/A')}"
    
    ping_ms_val = await sm.get_server_ping(server_ip)
    resources = await sm.get_userbot_resource_usage(ub_username, server_ip)
    webui_port = ub_data.get('webui_port')

    rom_info = await get_userbot_rom_usage(ub_username, server_ip)
    def make_bar(percent, length=10):
        filled = int(percent * length / 100)
        return '█' * filled + '░' * (length - filled)
    rom_bar = make_bar(rom_info['percent'])
    rom_str = f'💽 ROM: [{rom_bar}] ({rom_info["used"]} / {rom_info["total"]} МБ)'

    if not is_server_active:
        status_text = "⚪️ Сервер отключен"
    elif is_running:
        status_text = "🟢 Включен"
    else:
        status_text = "🔴 Выключен"
        
    creation_date_str = "Неизвестно"
    if ub_data.get('created_at'):
        try:
            creation_date = ub_data['created_at']
            creation_date_str = creation_date.strftime('%d.%m.%Y в %H:%M')
        except (ValueError, TypeError):
            pass

    ram_bar = _create_progress_bar(resources['ram_percent'])

    uptime_str = None
    if is_running:
        service_name = f"hikka-{ub_username}.service"
        etime = await get_service_process_uptime(service_name, server_ip)
        if etime:
            uptime_str = parse_ps_etime_to_human(etime)

    is_owner = ub_data.get('tg_user_id') == user.id
    is_super_admin = user.id in config.SUPER_ADMIN_IDS
    all_shared_users = await db.get_userbot_shared_users(ub_username) if is_owner else []
    shared_users = [uid for uid in all_shared_users if uid != user.id]
    shared_count = len(shared_users)
    def pluralize_user(n):
        n = abs(n)
        if n % 10 == 1 and n % 100 != 11:
            return "пользователю"
        elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
            return "пользователям"
        else:
            return "пользователям"

    shared_usernames = []
    if is_owner and shared_count > 0:
        for uid in shared_users:
            user_data = await db.get_user_data(uid)
            username = user_data.get('username', f'ID {uid}')
            shared_usernames.append(f"• @{username}")
    shared_users_str = '\n'.join(shared_usernames) if shared_usernames else ""

    ping_display = f"📡 Пинг: {ping_ms_val:.1f} мс" if ping_ms_val is not None else "📡 Пинг: N/A"

    server_info_parts = [
        "<blockquote><b>Информация о сервере:</b>",
        f"🖥 Сервер: {server_display}",
        f"🌍 Локация: {server_location}",
        ping_display
    ]
    if is_owner and shared_count > 0:
        server_info_parts.append(f"\n<b>Доступ имеют:</b>\n{shared_users_str}")
    server_info_parts.append("</blockquote>")
    server_info_block = "\n".join(server_info_parts)

    text_lines = [
        "<b>🎛 Панель управления</b>\n",
        "<blockquote>"
        "<b>Основная информация:</b>\n"
        f"🤖 Юзербот: {html.quote(ub_username)}\n"
        f"💡 Статус: {status_text}\n"
        f"⚙️ Тип: {ub_data.get('ub_type', 'N/A').capitalize()}\n"
        f"📅 Создан: {creation_date_str}"
        + (f"\n🧭 Аптайм: {uptime_str}" if uptime_str else "")
        + (f"\n\n🌐 <b>WebUI:</b> <code>http://{server_ip}:{webui_port}</code>" if webui_port else "")
        + (f"\n🗂 Панель управления доступна: {shared_count} {pluralize_user(shared_count)}" if is_owner and shared_count > 0 else "") +
        "</blockquote>",
        server_info_block,
        "<blockquote>"
        "<b>Потребление ресурсов:</b>\n"
        f"🧠 CPU: {resources['cpu']}%\n"
        f"💾 RAM: {ram_bar} ({resources['ram_used']} / {resources['ram_limit']} МБ)\n"
        f"{rom_str}"
        "</blockquote>\n"
    ]
    update_time_str = datetime.now(pytz.timezone("Europe/Moscow")).strftime('%H:%M:%S')
    text_lines.append(f"\n<i>Последнее обновление: {update_time_str} MSK</i>")
    text = "\n".join(text_lines)
    
    markup = kb.get_management_keyboard(
        is_running=is_running, ub_username=ub_username,
        ub_type=ub_data.get('ub_type', 'N/A'), is_server_active=is_server_active,
        is_owner=is_owner,
        is_private=message.chat.type == 'private',
        owner_id=user.id,
        is_shared=(not is_owner and await db.has_userbot_shared_access(ub_username, user.id)),
        is_installing=(ub_data.get('status') == 'installing'),
        is_deleting=(ub_data.get('status') == 'deleting'),
        is_super_admin=is_super_admin
    )

    photo = BANNER_FILE_IDS.get("panel_userbot") or FSInputFile("banners/panel_userbot.png")
    try:
        if is_callback:
            await message.edit_media(media=InputMediaPhoto(media=photo, caption=text), reply_markup=markup)
        else:
            await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text, reply_markup=markup, message_thread_id=message.message_thread_id)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            if is_callback:
                await call_or_message.answer()
            return
        logging.warning(f"Could not edit message to panel. Re-sending. Error: {e}")
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except (TelegramBadRequest, TelegramNotFound):
            pass
        finally:
            await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text, reply_markup=markup, message_thread_id=message.message_thread_id)
            
    if not is_owner:
        markup.inline_keyboard = [row for row in markup.inline_keyboard if not any(
            (b.text and ("Терминал" in b.text or "Inline действие" in b.text)) for b in row)]
    if is_owner:
        shared_users = await db.get_userbot_shared_users(ub_username)
        if shared_users:
            text += f"\n\n<b>Доступ имеют: {len(shared_users)} пользователь(ей)</b>"
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="Управление доступом", callback_data=f"manage_shared_access:{ub_username}")
            ])

async def _safe_cleanup_on_failure(ub_username: str, server_ip: str, state: FSMContext):
    if await db.get_userbot_data(ub_username=ub_username):
        await sm.delete_userbot_full(ub_username, server_ip)
    await state.clear()

async def _show_login_link_success_from_new_message(bot: Bot, chat_id: int, ub_username: str, login_url: str | None, state: FSMContext):
    data = await state.get_data()
    ub_type = data.get("selected_ub_type")
    server_ip = data.get("server_ip")

    text_parts = ["<b>✅ Установка завершена</b>\n"]

    if login_url:
        text_parts.append(f"\nПерейдите по этой <a href='{login_url}'>ссылке</a>.\n")

    text_parts.append("\n<i>Для управления юзерботом > /start > Панель управление</i>\n\n")
    text_parts.append("<u><b>❤️ Спасибо что выбрали SharkHost!</b></u>")

    await bot.send_message(
        chat_id=chat_id, text="".join(text_parts), 
        reply_markup=kb.get_login_link_success_keyboard(), disable_web_page_preview=True
    )
    await state.clear()

async def _show_login_link_fail_from_message(bot: Bot, chat_id: int, message_id: int, ub_username: str, timeout: bool = False):
    if timeout:
        text = (f"⏳ <b>Время вышло.</b>\n\nНе удалось автоматически найти ссылку для <code>{html.quote(ub_username)}</code> за 2 минуты. "
                f"Попробуйте запросить ссылку снова.")
    else:
        text = (f"⚠️ <b>Не удалось найти ссылку для <code>{html.quote(ub_username)}</code>.</b>\n\n"
                f"Попробуйте поискать ссылку еще раз.")
    await bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=kb.get_retry_login_link_keyboard(ub_username))
    
async def perform_installation_and_find_link(tg_user_id: int, chat_id: int, message_id: int, state: FSMContext, bot: Bot, is_private: bool = True):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    ub_type = data.get("selected_ub_type")
    server_ip = data.get("server_ip")
    service_name = f"hikka-{ub_username}.service"
        
    install_result = await sm.create_server_user_and_setup_hikka(tg_user_id, data.get("chosen_username_base"), ub_type, server_ip)

    user_data = {"id": tg_user_id}
    try:
        user_chat = await bot.get_chat(tg_user_id)
        user_data["full_name"] = user_chat.full_name
    except Exception:
        pass
        
    server_details = server_config.get_servers().get(server_ip, {})
    log_data = {
        "user_data": user_data,
        "ub_info": {"name": ub_username, "type": ub_type},
        "server_info": {"ip": server_ip, "code": server_details.get("code", "N/A")}
    }

    if not install_result.get("success"):
        err = install_result.get('message', 'Неизвестная ошибка.')
        await bot.edit_message_caption(caption=f"❌ <b>Ошибка установки:</b>\n{html.quote(err)}\n\n/start", chat_id=chat_id, message_id=message_id)
        log_data["error"] = err
        await log_event(bot, "installation_failed", log_data)
        await _safe_cleanup_on_failure(ub_username, server_ip, state)
        return

    webui_port = install_result.get("webui_port")

    if webui_port:
        login_url = f"http://{server_ip}:{webui_port}"
        await bot.delete_message(chat_id, message_id)
        if is_private:
            await _show_login_link_success_from_new_message(bot, chat_id, ub_username, login_url, state)
        else:
            await _show_login_link_success_from_new_message(bot, tg_user_id, ub_username, login_url, state)
            await bot.send_message(
                chat_id=chat_id,
                text="✅ Установка завершена. Продолжите авторизацию в личных сообщениях с ботом."
            )
        await log_event(bot, "installation_success", log_data)
        return

    await bot.edit_message_caption(
        caption="<b>⏳ Идет поиск ссылки для входа...</b>\n\n<blockquote>Это займет до 2 минут. Подождите.</blockquote>",
        chat_id=chat_id, message_id=message_id, reply_markup=kb.get_loading_keyboard()
    )
    
    await sm.manage_ub_service(ub_username, "stop", server_ip)
    await sm.clear_journal_logs_for_service(service_name, server_ip)
    await asyncio.sleep(1)
    await sm.manage_ub_service(ub_username, "start", server_ip)

    if ub_type == "fox":
        await asyncio.sleep(5)
    
    try:
        login_url = await asyncio.wait_for(sm.find_login_url_in_loop(ub_username, server_ip, ub_type), timeout=120.0)
        await bot.delete_message(chat_id, message_id)
        if is_private:
            await _show_login_link_success_from_new_message(bot, chat_id, ub_username, login_url, state)
        else:
            await _show_login_link_success_from_new_message(bot, tg_user_id, ub_username, login_url, state)
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption="✅ Установка завершена. Продолжите авторизацию в личных сообщениях с ботом."
            )
        await log_event(bot, "installation_success", log_data)
    except asyncio.TimeoutError:
        await _show_login_link_fail_from_message(bot, chat_id, message_id, ub_username, timeout=True)
        log_data["error"] = "Таймаут поиска ссылки для входа"
        await log_event(bot, "installation_failed", log_data)

@router.message(Command("start"), F.chat.type != "private")
async def cmd_start_in_chat(message: types.Message):
    pass

@router.message(Command("review"), F.chat.type != "private")
async def cmd_review_in_chat(message: types.Message):
    pass

@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    user = message.from_user
    if await db.is_user_banned(user.id):
        ban_message = "❌ <b>Вы забанены.</b>\n\nДоступ к боту для вас ограничен."
        await message.answer(ban_message, message_thread_id=message.message_thread_id)
        return
    is_new_user = not await db.get_user_data(user.id)
    await db.register_or_update_user(tg_user_id=user.id, username=user.username, full_name=user.full_name)
    if not await db.has_user_accepted_agreement(user.id) and not config.TEST_MODE:
        if is_new_user:
            user_data_for_log = {"id": user.id, "full_name": user.full_name}
            await log_event(bot, "new_user_registered", {"user_data": user_data_for_log})
        text = ("👋 <b>Добро пожаловать в SharkHost!</b>\n\n"
                "Прежде чем мы начнем, ознакомьтесь с нашим пользовательским соглашением. "
                "Нажимая кнопку «Принять и продолжить», вы подтверждаете, что прочитали и согласны с нашими правилами.")
        await message.answer(text, reply_markup=kb.get_agreement_keyboard())
    else:
        await _show_main_panel(bot=bot, chat_id=message.chat.id, user_id=user.id, user_name=user.full_name, state=state, topic_id=message.message_thread_id, owner_id=user.id)

@router.message(Command("review"), F.chat.type == "private")
async def cmd_review(message: types.Message, state: FSMContext):
    text = (
        "✍️ <b>Напишите отзыв о SharkHost</b>\n\n"
        "ℹ️ В отзыве можете рассказать о том, сколько пользуетесь SharkHost, какие отличия заметили от предыдущего хостинга и т.д.\n\n"
        "📅 В ближайшее время отзыв будет опубликован на @SharkHost_reviews."
    )
    sent_message = await message.reply(text, reply_markup=kb.get_cancel_review_keyboard())
    await state.update_data(original_bot_message_id=sent_message.message_id)
    await state.set_state(UserReview.WaitingForReview)

@router.callback_query(F.data == "accept_agreement")
async def cq_accept_agreement(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    user = call.from_user
    await db.register_or_update_user(tg_user_id=user.id, username=user.username, full_name=user.full_name)
    await db.set_user_agreement_accepted(user.id)
    await call.answer("Спасибо! Теперь вы можете пользоваться всеми функциями бота.", show_alert=True)
    await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=user.id, user_name=user.full_name, state=state, message_id=call.message.message_id, topic_id=call.message.message_thread_id)

@router.callback_query(F.data == "back_to_main_panel")
async def cq_back_to_main_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id, user_name=call.from_user.full_name, state=state, message_id=call.message.message_id, topic_id=call.message.message_thread_id)
    await call.answer()

@router.callback_query(F.data == "back_to_main_panel_delete")
async def cq_back_to_main_panel_delete(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.delete()
    await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id, user_name=call.from_user.full_name, state=state, topic_id=call.message.message_thread_id)
    await call.answer()

async def _start_installation_flow(call: types.CallbackQuery, state: FSMContext):
    from bot import BANNER_FILE_IDS
    photo_file = BANNER_FILE_IDS.get("select_server") or FSInputFile("banners/select_server.png")
    message_to_edit_id = call.message.message_id
    try:
        await call.message.edit_media(
            media=InputMediaPhoto(media=photo_file, caption="<b>[Шаг 1/3] Выбор сервера</b>\n\nЗагружаю список доступных серверов..."),
            reply_markup=kb.get_loading_keyboard()
        )
    except TelegramBadRequest:
        await call.message.delete()
        new_msg = await call.message.answer_photo(
            photo=photo_file, 
            caption="<b>[Шаг 1/3] Выбор сервера</b>\n\nЗагружаю список доступных серверов...",
            reply_markup=kb.get_loading_keyboard()
        )
        message_to_edit_id = new_msg.message_id

    await state.update_data(message_id_to_edit=message_to_edit_id)

    servers = server_config.get_servers()
    installed_bots_map = {ip: len(await db.get_userbots_by_server_ip(ip)) for ip in servers.keys()}
    tasks = [sm.get_server_stats(ip) for ip in servers.keys()]
    stats_results = await asyncio.gather(*tasks)
    server_stats = dict(zip(servers.keys(), stats_results))
    
    await state.update_data(server_stats=server_stats)
    
    text = "<b>⬇️ Установка</b>\n\n<b>💻 Выберите сервер, на который хотите установить юзербот</b>"
    
    await call.bot.edit_message_media(
        chat_id=call.message.chat.id, message_id=message_to_edit_id,
        media=InputMediaPhoto(media=photo_file, caption=text),
        reply_markup=kb.get_server_selection_keyboard(call.from_user.id, installed_bots_map, server_stats)
    )
    await state.set_state(UserBotSetup.ChoosingServer)

@router.callback_query(F.data == "create_userbot_start", IsSubscribed(), StateFilter("*"))
async def cq_create_userbot_start(call: types.CallbackQuery, state: FSMContext):
    if len(await db.get_userbots_by_tg_id(call.from_user.id)) >= 1:
        await call.answer("❌ У вас уже есть юзербот. Вы можете установить только одного.", show_alert=True)
        return
    
    await state.clear()
    await call.answer()
    await _start_installation_flow(call, state)

class ReinstallUBCallback(CallbackData, prefix="reinstall_ub_start_request"):
    ub_username: str
    owner_id: int

@router.callback_query(ReinstallUBCallback.filter())
async def cq_reinstall_ub_start_request(call: types.CallbackQuery, callback_data: ReinstallUBCallback, state: FSMContext, bot: Bot):
    ub_username = callback_data.ub_username
    owner_id = callback_data.owner_id
    if not check_panel_owner(call, owner_id):
        return
    await call.answer("Функция переустановки временно недоступна.", show_alert=True)

@router.callback_query(F.data.in_({"server_unavailable", "server_test_unavailable", "server_noub", "server_full"}), UserBotSetup.ChoosingServer)
async def cq_server_unavailable(call: types.CallbackQuery):
    alerts = {
        "server_unavailable": "🔴 Этот сервер временно недоступен для выбора.",
        "server_test_unavailable": "🧪 Нельзя выбрать тестовый сервер!",
        "server_noub": "🟢 Установка новых юзерботов на этот сервер временно отключена.",
        "server_full": "❌ Сервера переполнен\n\nВыберите другой сервер."
    }
    await call.answer(alerts.get(call.data, "Это действие сейчас недоступно."), show_alert=True)

@router.callback_query(F.data == "server_is_service", UserBotSetup.ChoosingServer)
async def cq_service_server_selected(call: types.CallbackQuery):
    await call.answer("ℹ️ Это сервисный сервер, на котором работает бот.\n\nУстановка юзерботов на него невозможна.", show_alert=True)

@router.callback_query(F.data.startswith("confirm_unstable:"), UserBotSetup.ChoosingServer)
async def cq_confirm_unstable_server(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Хорошо, продолжаю установку.")
    server_ip = call.data.split(":")[1]
    await _proceed_to_type_selection(call, state, server_ip)
    
@router.callback_query(F.data.startswith("ub_type:"), UserBotSetup.ChoosingUserBotType)
async def cq_process_ub_type_selection(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()
    _, ub_type, server_ip = call.data.split(":")
    await state.update_data(selected_ub_type=ub_type)
    
    user = call.from_user
    name_base = str(user.id)
    ub_username = f"ub{name_base}"

    await state.update_data(chosen_username_base=name_base, ub_username=ub_username)

    current_state = await state.get_state()
    if current_state != UserBotSetup.Reinstalling.state and await db.get_userbot_data(ub_username=ub_username):
        await call.message.edit_caption(
            caption="❌ <b>Ошибка:</b> У вас уже есть юзербот с таким системным именем.\n\n"
                    "Это могло произойти, если была прервана предыдущая установка. "
                    "Обратитесь в поддержку для решения проблемы.",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )
        await state.clear()
        return

    data = await state.get_data()
    message_id = data.get("message_id_to_edit", call.message.message_id)

    try:
        await bot.edit_message_caption(
            chat_id=call.message.chat.id, message_id=message_id,
            caption="<b>[Шаг 3/3] Установка...</b>\n\n<blockquote>Этот процесс может занять несколько минут. Подождите.</blockquote>",
            reply_markup=kb.get_loading_keyboard()
        )
    except Exception as e:
        from aiogram.exceptions import TelegramBadRequest
        if isinstance(e, TelegramBadRequest) and "message is not modified" in str(e):
            pass
        else:
            raise

    await state.set_state(UserBotSetup.InstallingUserBot)
    asyncio.create_task(perform_installation_and_find_link(call.from_user.id, call.message.chat.id, message_id, state, bot, is_private=(call.message.chat.type == 'private')))

async def monitor_for_restart(user_id: int, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ub_username, msg_id, server_ip = data.get("ub_username"), data.get("status_message_id"), data.get("server_ip")
    if not all([ub_username, msg_id, server_ip]): return

    end_time = asyncio.get_event_loop().time() + 300
    is_restarted = False
    while asyncio.get_event_loop().time() < end_time:
        if await sm.check_journal_for_restart(ub_username, server_ip):
            is_restarted = True
            break
        await asyncio.sleep(5)
    
    try: await bot.delete_message(chat_id=user_id, message_id=msg_id)
    except Exception: pass
    
    if is_restarted:
        await bot.send_message(chat_id=user_id, text="✅ <b>Авторизация прошла успешно!</b>")
    
    await _show_main_panel(bot=bot, chat_id=user_id, user_id=user_id, user_name=(await bot.get_chat(user_id)).full_name, state=state)
  
@router.callback_query(F.data == "go_to_control_panel", IsSubscribed(), StateFilter("*"))
async def cq_go_to_control_panel(call: types.CallbackQuery, state: FSMContext):
    if call.message.chat.type != "private":
        if call.message.reply_to_message:
            owner_id = call.message.reply_to_message.from_user.id
            if call.from_user.id != owner_id:
                await call.answer("Только тот, кто вызвал /start, может использовать эти кнопки!", show_alert=True)
                return
        else:
            await call.answer("Только тот, кто вызвал /start, может использовать эти кнопки!", show_alert=True)
            return
    
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())

    all_bots = await db.get_userbots_by_tg_id(call.from_user.id)
    
    if not all_bots:
        await call.answer("❌ Юзербот не найден. Возможно, он был удален.", show_alert=True)
        await _show_main_panel(call.bot, call.message.chat.id, call.from_user.id, call.from_user.full_name, state, call.message.message_id)
        return

    the_only_bot = all_bots[0]
    ub_username = the_only_bot['ub_username']
    server_ip = the_only_bot['server_ip']
    service_name = f"hikka-{ub_username}.service"
    
    service_file_exists = await sm.check_systemd_file_exists(service_name, server_ip)
    disk_space_ok = True  # Упрощенная проверка

    if not service_file_exists or not disk_space_ok:
        error_text = (
            f"<b>🎛 Панель управления</b>\n\n"
            f"<i>😢 На данный момент наблюдаются сбои в работе юзербота/сервера.</i>\n\n"
            f"<b>Повторите попытку через <code>10-15</code> минут</b>"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data=f"health_check_retry:{ub_username}")
        builder.button(text="🔙 Назад", callback_data="back_to_main_panel")
        await call.message.edit_caption(caption=error_text, reply_markup=builder.as_markup())
        return
    
    if len(all_bots) == 1:
        await show_management_panel(call, ub_username, state)
        return

    text = "<b>Выберите юзербота для управления:</b>"
    markup = kb.get_user_bots_list_keyboard(all_bots, call.from_user.id)
    await call.message.edit_caption(caption=text, reply_markup=markup)

@router.callback_query(F.data.startswith("select_ub_panel:"))
async def cq_select_ub_panel(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await show_management_panel(call, ub_username, state)
    await call.answer()

@router.callback_query(F.data.startswith("refresh_panel:"))
async def cq_refresh_panel(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer("Кнопка устарела, обновите панель.", show_alert=True)
        return
    _, ub_username, owner_id_str = parts
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    await show_management_panel(call, ub_username, state)
    
@router.callback_query(F.data.startswith("show_user_logs:"))
async def cq_show_user_logs(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, log_type, ub_username, owner_id_str, page = call.data.split(":")
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    await call.answer()
    
    try:
        page = int(page)
    except ValueError:
        await call.answer("Ошибка данных.", show_alert=True)
        return

    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("🚫 У вас нет доступа к этому юзерботу.", show_alert=True)
        return

    is_pagination = call.message.text is not None

    msg_to_edit = call.message
    if not is_pagination:
        await call.message.delete()
        msg_to_edit = await bot.send_message(call.from_user.id, "⏳ Загружаю логи...", reply_markup=kb.get_loading_keyboard())
    else:
        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())

    logs = await sm.get_journal_logs(ub_username, ub_data['server_ip'], lines=1000)

    if not logs:
        await msg_to_edit.delete()
        await show_management_panel(call, ub_username, state)
        await bot.send_message(call.from_user.id, "📜 Логи для этого юзербота пусты.")
        return
    
    log_lines = logs.strip().split('\n')
    total_pages = max(1, (len(log_lines) + LOG_LINES_PER_PAGE - 1) // LOG_LINES_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_index = (page - 1) * LOG_LINES_PER_PAGE
    end_index = start_index + LOG_LINES_PER_PAGE
    page_content = "\n".join(log_lines[start_index:end_index])
    
    text = (f"📜 <b>Логи ({log_type.capitalize()}) для <code>{html.quote(ub_username)}</code></b>\n"
            f"<i>(Стр. {page}/{total_pages}, новые логи сверху)</i>\n\n"
            f"<pre>{html.quote(page_content)}</pre>")
            
    if len(text) > 4096:
        text = text[:4090] + "...</pre>"

    markup = kb.get_user_logs_paginator_keyboard(log_type, ub_username, page, total_pages, owner_id)
    
    try:
        await msg_to_edit.edit_text(text=text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Error editing message with logs: {e}")
            await call.answer("Произошла ошибка при отображении логов.", show_alert=True)

@router.callback_query(F.data.startswith("manage_ub:"))
async def cq_manage_userbot(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    parts = call.data.split(":")
    if len(parts) < 4:
        await call.answer("Кнопка устарела или повреждена, обновите панель.", show_alert=True)
        return
    _, action, ub_username, owner_id_str = parts
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    
    ub_data = await db.get_userbot_data(ub_username)
    server_ip = ub_data['server_ip']
    is_server_active_str = server_config.get_server_status_by_ip(server_ip)
    if is_server_active_str in ["false", "not_found"]:
        await call.answer("🔴 Управление невозможно, так как сервер отключен.", show_alert=True)
        return

    try:
        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        await call.answer()
    except TelegramBadRequest:
        await call.answer("Выполняю команду...")

    await sm.manage_ub_service(ub_username, action, server_ip)

    try:
        user_data_log = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        ub_info_log = {"name": ub_username}
        log_data = {"user_data": user_data_log, "ub_info": ub_info_log, "action": action}
        await log_event(bot, "user_action_manage_ub", log_data)
    except Exception as e:
        logging.error(f"Failed to log user action: {e}")

    if action == 'restart':
        await db.update_userbot_started_time(ub_username, datetime.now(pytz.utc))

    await asyncio.sleep(1.5) 
    await show_management_panel(call, ub_username, state)

@router.callback_query(F.data.startswith("delete_ub_confirm_request:"))
async def cq_delete_ub_confirm_request(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer("Кнопка устарела, обновите панель.", show_alert=True)
        return
    _, ub_username, owner_id_str = parts
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    text = (
        f"<b>⚠️ Вы уверены, что хотите удалить ваш юзербот?</b>\n\n"
        f"❗️ Все ваши модули и настройки будут <b>безвозвратно удалены</b>."
    )
    markup = kb.get_confirm_delete_keyboard(ub_username)
    try:
        await call.message.edit_caption(caption=text, reply_markup=markup)
        await call.answer()
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await call.answer("Нажмите на кнопку ниже для подтверждения.")
        else:
            logging.error(f"Error in delete confirmation: {e}")
            await call.answer("Произошла ошибка, попробуйте снова.", show_alert=True)
    await state.set_state(UserBotSetup.ConfirmDeleteUserBot)

@router.callback_query(F.data.startswith("delete_ub_cancel:"), UserBotSetup.ConfirmDeleteUserBot)
async def cq_delete_ub_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer("🚫 Удаление отменено.")
    ub_username = call.data.split(":")[1]
    await show_management_panel(call, ub_username, state)

@router.callback_query(F.data.startswith("delete_ub_execute:"), UserBotSetup.ConfirmDeleteUserBot)
async def cq_delete_ub_execute(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer()

    await call.message.edit_caption(
        caption="🗑️ <b>Удаление юзербота...</b>\n\n<blockquote>Этот процесс может занять до минуты.</blockquote>",
        reply_markup=kb.get_loading_keyboard()
    )

    ub_username = call.data.split(":")[1]
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.message.edit_caption(
            caption="❌ <b>Ошибка:</b> Юзербот не найден или у вас больше нет к нему доступа.",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )
        return

    # Устанавливаем статус "deleting" перед началом удаления
    await db.update_userbot_status(ub_username, "deleting")
    
    res = await sm.delete_userbot_full(ub_username, ub_data['server_ip'])
    
    if res["success"]:
        user_data = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        server_details = server_config.get_servers().get(ub_data['server_ip'], {})
        log_data = {
            "user_data": user_data,
            "ub_info": {"name": ub_username},
            "server_info": {"ip": ub_data['server_ip'], "code": server_details.get("code", "N/A")}
        }
        await log_event(bot, "deletion_by_owner", log_data)
        
        await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id,
            user_name=call.from_user.full_name, state=state, message_id=call.message.message_id
        )
    else:
        error_message = res.get('message', 'Произошла неизвестная ошибка.')
        await call.message.edit_caption(
            caption=f"❌ <b>Ошибка при удалении:</b>\n\n<pre>{html.quote(error_message)}</pre>",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    user_id = call.from_user.id
    
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        if member.status not in ["left", "kicked"]:
            await call.answer("✅ Спасибо за подписку!", show_alert=True)
            await call.message.delete()
            await call.answer("Запустите бота снова /start")
        else:
            await call.answer("🚫 Вы еще не подписаны. Подпишитесь и попробуйте снова.", show_alert=True)
    except Exception as e:
        await call.answer("Произошла ошибка при проверке. Попробуйте снова.", show_alert=True)
        logging.error(f"Ошибка проверки подписки по кнопке: {e}")

@router.callback_query(F.data.startswith("share_panel_start:"))
async def cq_share_panel_start(call: types.CallbackQuery, state: FSMContext):
    logger.info(f"share_panel_start: chat.type={getattr(call.message.chat, 'type', None)}, user={call.from_user.id}")
    if getattr(call.message.chat, 'type', None) != "private":
        await call.answer("⚠️ Функция 'Поделиться панелью' работает только в личных сообщениях с ботом.", show_alert=True)
        return
    ub_username = call.data.split(":")[1]
    await state.set_state(UserBotShare.WaitingForShareUserID)
    await state.update_data(ub_username=ub_username, message_id_to_edit=call.message.message_id)
    text = "Введите ID пользователя, которому хотите выдать доступ к панели управления этим юзерботом."
    markup = kb.get_cancel_revoke_shared_keyboard(ub_username)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await call.answer()

@router.message(StateFilter(UserBotShare.WaitingForShareUserID))
async def msg_process_share_user_id(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    message_id_to_edit = data.get("message_id_to_edit")
    await message.delete()
    if not message.text or not message.text.isdigit():
        await bot.edit_message_caption(caption="❌ ID пользователя должен быть числом. Попробуйте снова.",
            chat_id=message.chat.id, message_id=message_id_to_edit,
            reply_markup=kb.get_cancel_revoke_shared_keyboard(ub_username)
        )
        return
    share_user_id = int(message.text)
    if share_user_id == message.from_user.id:
        await bot.edit_message_caption(caption="❌ Вы не можете поделиться панелью с самим собой.",
            chat_id=message.chat.id, message_id=message_id_to_edit)
        await show_management_panel(message, ub_username, state)
        return
    if await db.has_userbot_shared_access(ub_username, share_user_id):
        await bot.edit_message_caption(caption="❗️ У пользователя уже есть доступ к этой панели.",
            chat_id=message.chat.id, message_id=message_id_to_edit)
        await show_management_panel(message, ub_username, state)
        return
    await state.update_data(share_user_id=share_user_id)
    await state.set_state(UserBotShare.ConfirmingShare)
    user = await bot.get_chat(share_user_id)
    user_display = f"@{user.username}" if user.username else user.full_name
    text = f"Вы точно хотите выдать доступ к панели <code>{html.quote(ub_username)}</code> пользователю {html.quote(user_display)} (<code>{share_user_id}</code>)?"
    markup = kb.get_confirm_share_panel_keyboard(ub_username, share_user_id)
    await bot.edit_message_caption(caption=text, chat_id=message.chat.id, message_id=message_id_to_edit, reply_markup=markup)

@router.callback_query(F.data.startswith("confirm_share_panel:"), UserBotShare.ConfirmingShare)
async def cq_confirm_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, ub_username, share_user_id_str = call.data.split(":")
    share_user_id = int(share_user_id_str)
    owner = call.from_user
    text = (f"Пользователь {html.quote(owner.full_name)} (<code>{owner.id}</code>) хочет поделиться с вами панелью управления юзерботом <code>{html.quote(ub_username)}</code>.\n\n"
            "Вы хотите принять доступ? Вы сможете отказаться в любой момент.")
    markup = kb.get_accept_share_panel_keyboard(ub_username, owner.id)
    
    try:
        await bot.send_message(chat_id=share_user_id, text=text, reply_markup=markup)
        await call.message.edit_caption(caption="⏳ Ожидание подтверждения вторым пользователем...", reply_markup=kb.get_back_to_main_panel_keyboard())
    except TelegramForbiddenError:
        await call.answer("❌ Не удалось отправить приглашение. Пользователь должен сначала начать диалог с ботом.", show_alert=True)
        await call.message.edit_caption(caption="❌ Ошибка: пользователь не начал диалог с ботом", reply_markup=kb.get_back_to_main_panel_keyboard())
    except Exception as e:
        logging.error(f"Ошибка при отправке приглашения пользователю {share_user_id}: {e}")
        await call.answer("❌ Произошла ошибка при отправке приглашения", show_alert=True)
        await call.message.edit_caption(caption="❌ Ошибка при отправке приглашения", reply_markup=kb.get_back_to_main_panel_keyboard())
    
    await state.clear()

@router.callback_query(F.data.startswith("accept_share_panel:"), F.chat.type == "private")
async def cq_accept_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, ub_username, owner_id_str = call.data.split(":")
    await db.add_userbot_shared_access(ub_username, call.from_user.id)
    
    try:
        owner_id = int(owner_id_str)
        sharer_data_log = {"id": owner_id, "full_name": (await bot.get_chat(owner_id)).full_name}
        user_data_log = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        ub_info_log = {"name": ub_username}
        log_data = {"sharer_data": sharer_data_log, "user_data": user_data_log, "ub_info": ub_info_log}
        await log_event(bot, "panel_shared_accepted", log_data)
    except Exception as e:
        logging.error(f"Failed to log panel share event: {e}")

    await call.answer("✅ Доступ выдан! Теперь вы можете управлять этим юзерботом.", show_alert=True)
    await show_management_panel(call, ub_username, state)
    
    try:
        await bot.send_message(chat_id=int(owner_id_str), text=f"Пользователь <code>{call.from_user.id}</code> принял доступ к панели <code>{html.quote(ub_username)}</code>.")
    except TelegramForbiddenError:
        logging.warning(f"Не удалось уведомить владельца {owner_id_str} о принятии доступа: пользователь не начал диалог с ботом")
    except Exception as e:
        logging.error(f"Ошибка при уведомлении владельца {owner_id_str}: {e}")

@router.callback_query(F.data.startswith("accept_share_panel:"))
async def cq_accept_share_panel_fallback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    chat = getattr(call.message, "chat", None)
    if chat and chat.type == "private":
        await cq_accept_share_panel(call, state, bot)
    else:
        await call.answer(
            "⚠️ Функция 'Поделиться панелью' работает только в личных сообщениях с ботом.",
            show_alert=True
        )

@router.callback_query(F.data.startswith("decline_share_panel:"), F.chat.type == "private")
async def cq_decline_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.answer("Вы отклонили приглашение.", show_alert=True)
    await call.message.edit_text("❌ Вы отклонили приглашение к совместному управлению этим юзерботом.")

@router.callback_query(F.data.startswith("decline_share_panel:"), F.chat.type != "private")
async def cq_decline_share_panel_in_chat(call: types.CallbackQuery):
    await call.answer(
        "⚠️ Функция 'Поделиться панелью' работает только в личных сообщениях с ботом.",
        show_alert=True
    )

@router.message(Command("ping"))
async def cmd_ping(message: types.Message):
    start_time = time.perf_counter()
    msg = await message.reply("...")
    end_time = time.perf_counter()
    delay = (end_time - start_time) * 1000
    await msg.edit_text(f"🏓 <b>Понг!</b>\nЗадержка: <code>{delay:.2f} мс</code>")
   
@router.message(Command("review"), F.chat.type == "private")
async def cmd_review(message: types.Message, state: FSMContext):
    text = (
        "✍️ <b>Напишите отзыв о SharkHost</b>\n\n"
        "ℹ️ В отзыве можете рассказать о том, сколько пользуетесь SharkHost, какие отличия заметили от предыдущего хостинга и т.д.\n\n"
        "📅 В ближайшее время отзыв будет опубликован на @SharkHost_reviews."
    )
    sent_message = await message.reply(text, reply_markup=kb.get_cancel_review_keyboard())
    await state.update_data(original_bot_message_id=sent_message.message_id)
    await state.set_state(UserReview.WaitingForReview)

@router.message(Command("review"), F.chat.type != "private")
async def cmd_review_in_chat(message: types.Message):
    key = (message.chat.id, message.from_user.id)
    if review_warned_users[key]:
        return
    await message.reply(
        "⚠️ Команда /review работает только в личных сообщениях с ботом."
    )
    review_warned_users[key] = True

@router.message(F.chat.type != "private")
async def reset_review_warn_flag(message: types.Message):
    if message.text and message.text.strip().startswith("/review"):
        return
    key = (message.chat.id, message.from_user.id)
    if review_warned_users[key]:
        review_warned_users[key] = False

@router.callback_query(F.data == "cancel_review", StateFilter(UserReview.WaitingForReview))
async def cq_cancel_review(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Действие отменено.")
    await call.answer("Отменено.")

@router.message(StateFilter(UserReview.WaitingForReview))
async def process_review_text(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    original_bot_message_id = data.get("original_bot_message_id")
    
    await state.clear()
    admins = get_all_admins()
    
    for admin_id in admins:
        try:
            forwarded_msg = await bot.forward_message(
                chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id
            )
            await bot.send_message(
                chat_id=admin_id, text="Опубликовать этот отзыв?",
                reply_to_message_id=forwarded_msg.message_id,
                reply_markup=kb.get_review_approval_keyboard(message.from_user.id, message.message_id)
            )
        except TelegramForbiddenError:
            logging.warning(f"Не удалось отправить отзыв на модерацию администратору {admin_id}: пользователь не начал диалог с ботом")
        except Exception as e:
            logging.error(f"Не удалось отправить отзыв на модерацию администратору {admin_id}: {e}")
            
    await message.reply("✅ Отправлен на модерацию.")
    
    if original_bot_message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=original_bot_message_id, reply_markup=None
            )
        except Exception as e:
            logging.error(f"Не удалось удалить клавиатуру у сообщения с отзывом: {e}")

@router.message(Command("commits"))
async def cmd_commits(message: types.Message):
    text, markup = await _get_commits_list_message()
    await message.answer(text, reply_markup=markup)

@router.callback_query(F.data.startswith("view_commit:"))
async def cq_view_commit(call: types.CallbackQuery):
    await call.answer()
    commit_id = call.data.split(":")[1]
    await _display_commit_details(call, commit_id)

@router.callback_query(F.data.startswith("vote_commit:"))
async def cq_vote_commit(call: types.CallbackQuery):
    _, commit_id, vote_type_str = call.data.split(":")
    vote_type = int(vote_type_str)
    
    await db.set_vote(commit_id, call.from_user.id, vote_type)
    
    alert_text = "Ваш 👍 поставлен на коммит!" if vote_type == 1 else "Ваш 👎 поставлен на коммит!"
    await call.answer(alert_text, show_alert=False)
    
    await _display_commit_details(call, commit_id)

@router.callback_query(F.data == "back_to_commits")
async def cq_back_to_commits(call: types.CallbackQuery):
    await call.answer()
    text, markup = await _get_commits_list_message()
    await call.message.edit_text(text, reply_markup=markup)

@router.callback_query(F.data == "hide_commits")
async def cq_hide_commits(call: types.CallbackQuery):
    await call.answer()
    await call.message.delete()

async def _get_commits_list_message():
    commits = await db.get_all_commits()
    if not commits:
        return "<b>📜 История обновлений</b>\n\nПока не было ни одного коммита.", None
    
    text = "<b>📜 История обновлений</b>\n\nВыберите коммит для просмотра деталей."
    markup = kb.get_commits_list_keyboard(commits)
    return text, markup

async def _send_commit_details_new_message(bot: Bot, chat_id: int, commit_id: str, user_id_for_admin_check: int):
    commit = await db.get_commit_by_id(commit_id)
    if not commit:
        await bot.send_message(chat_id, "❌ Этот коммит не найден. Возможно, он был удален.")
        return

    admin_name = html.quote(commit['admin_name'])
    admin_info = f"<a href='tg://user?id={commit['admin_id']}'>{admin_name}</a>"
    if commit['admin_username']:
        admin_info += f" (@{html.quote(commit['admin_username'])})"
    
    try:
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except locale.Error:
        pass

    commit_date = datetime.strptime(commit['created_at'], '%Y-%m-%d %H:%M:%S')
    formatted_date = commit_date.strftime('%d %B %Y в %H:%M')
    
    vote_counts = await db.get_vote_counts(commit_id)
    is_admin = user_id_for_admin_check in get_all_admins()

    text = (f"<b>Commit <code>#{commit['commit_id']}</code> by {admin_info}</b>\n\n"
            f"🕕 <b>Дата коммита:</b> {formatted_date}\n\n"
            f"<b>✍️ ChangeLog:</b>\n"
            f"<blockquote>{html.quote(commit['commit_text'])}</blockquote>")
    
    markup = kb.get_commit_details_keyboard(commit_id, vote_counts['likes'], vote_counts['dislikes'], is_admin)
    await bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

async def _display_commit_details(call: types.CallbackQuery, commit_id: str):
    commit = await db.get_commit_by_id(commit_id)
    if not commit:
        await call.message.edit_text("❌ Этот коммит не найден. Возможно, он был удален.")
        return

    admin_name = html.quote(commit['admin_name'])
    admin_info = f"<a href='tg://user?id={commit['admin_id']}'>{admin_name}</a>"
    if commit['admin_username']:
        admin_info += f" (@{html.quote(commit['admin_username'])})"
    
    try:
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except locale.Error:
        pass

    commit_date = commit.get('created_at')
    formatted_date = "Неизвестно"
    if isinstance(commit_date, datetime):
        formatted_date = commit_date.strftime('%d %B %Y в %H:%M')
    
    vote_counts = await db.get_vote_counts(commit_id)
    is_admin = call.from_user.id in get_all_admins()

    text = (f"<b>Commit <code>#{commit['commit_id']}</code> by {admin_info}</b>\n\n"
            f"🕕 <b>Дата коммита:</b> {formatted_date}\n\n"
            f"<b>✍️ ChangeLog:</b>\n"
            f"<blockquote>{html.quote(commit['commit_text'])}</blockquote>")
    
    markup = kb.get_commit_details_keyboard(commit_id, vote_counts['likes'], vote_counts['dislikes'], is_admin)
    
    try:
        await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Ошибка обновления деталей коммита: {e}")
         
@router.inline_query(F.query.startswith("exec"))
async def inline_exec_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    user_bots = await db.get_userbots_by_tg_id(user_id)

    if not user_bots:
        result = InlineQueryResultArticle(id=str(user_id), title="Ошибка", description="У вас нет юзербота для выполнения команд.", input_message_content=InputTextMessageContent(message_text="❌ <b>У вас нет юзербота.</b>", parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    the_only_bot = user_bots[0]
    ub_username = the_only_bot['ub_username']
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data or ub_data.get('tg_user_id') != user_id:
        result = InlineQueryResultArticle(id=str(user_id), title="Ошибка", description="Только владелец может использовать терминал.", input_message_content=InputTextMessageContent(message_text="❌ <b>Только владелец может использовать терминал.</b>", parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    # Проверка статуса юзербота - терминал недоступен во время установки или удаления
    if ub_data.get('status') == 'installing':
        result = InlineQueryResultArticle(
            id=str(user_id), 
            title="⏳ Установка в процессе", 
            description="Терминал будет доступен после завершения установки",
            input_message_content=InputTextMessageContent(
                message_text="⏳ <b>Установка юзербота в процессе...</b>\n\nТерминал будет доступен после завершения установки и настройки всех систем безопасности.", 
                parse_mode="HTML"
            )
        )
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return
    
    if ub_data.get('status') == 'deleting':
        result = InlineQueryResultArticle(
            id=str(user_id), 
            title="🗑️ Удаление в процессе", 
            description="Терминал недоступен во время удаления",
            input_message_content=InputTextMessageContent(
                message_text="🗑️ <b>Удаление юзербота в процессе...</b>\n\nТерминал недоступен во время удаления юзербота.", 
                parse_mode="HTML"
            )
        )
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    command_str = inline_query.query[len("exec"):].strip()

    if not command_str:
        result = InlineQueryResultArticle(id=str(user_id), title="Введите команду", description="Напишите команду, которую хотите выполнить на сервере.", input_message_content=InputTextMessageContent(message_text="ℹ️ Введите команду после `exec ` для выполнения на сервере."))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return
        
    server_ip = the_only_bot['server_ip']
    system_user = the_only_bot['ub_username']

    res = await sm.run_command_async(command_str, server_ip, timeout=60, user=system_user)
    
    output = res.get('output', '')
    error = res.get('error', '')
    exit_code = res.get('exit_status', 'N/A')

    header = (
        f"<b>Команда:</b> <pre>{html.quote(command_str)}</pre>\n"
        f"<b>Код выхода:</b> <code>{exit_code}</code>\n"
    )
    
    full_content = ""
    if output:
        full_content += f"\n<b>STDOUT:</b>\n{html.quote(output)}"
    if error:
        full_content += f"\n<b>STDERR:</b>\n{html.quote(error)}"
    if not output and not error:
        full_content = "\n<i>(Нет вывода в STDOUT или STDERR)</i>"

    content_prefix = "<pre>"
    content_suffix = "</pre>"
    TELEGRAM_MSG_LIMIT = 4096
    
    available_space = TELEGRAM_MSG_LIMIT - len(header) - len(content_prefix) - len(content_suffix)

    if len(full_content) > available_space:
        truncated_content = full_content[:available_space - 15] + "\n[...обрезано]"
    else:
        truncated_content = full_content
    
    if full_content.strip() and not full_content.startswith("\n<i>"):
        response_text = header + content_prefix + truncated_content + content_suffix
    else:
        response_text = header + truncated_content
        
    result = InlineQueryResultArticle(id=str(user_id), title=f"Выполнить: {command_str[:50]}...", description="Результат выполнения команды", input_message_content=InputTextMessageContent(message_text=response_text, parse_mode="HTML"))

    try:
        await inline_query.answer([result], cache_time=1, is_personal=True)
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            return
        else:
            raise

@router.callback_query(F.data.startswith("revoke_shared_access:"))
async def cq_revoke_shared_access(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await state.set_state(UserBotShare.ConfirmingRevoke)
    await state.update_data(ub_username=ub_username)
    text = f"Вы уверены, что хотите отказаться от управления юзерботом <code>{html.quote(ub_username)}</code>?"
    markup = kb.get_confirm_revoke_shared_keyboard(ub_username)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await call.answer()

@router.callback_query(F.data.startswith("confirm_revoke_shared:"), UserBotShare.ConfirmingRevoke)
async def cq_confirm_revoke_shared(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    ub_username = call.data.split(":")[1]
    await db.remove_userbot_shared_access(ub_username, call.from_user.id)
    await state.clear()
    await call.message.edit_caption(
        caption=f"✅ Вы больше не управляете юзерботом <code>{html.quote(ub_username)}</code>.",
        reply_markup=kb.get_back_to_main_panel_keyboard()
    )
    await call.answer()

@router.callback_query(F.data.startswith("cancel_revoke_shared:"), UserBotShare.ConfirmingRevoke)
async def cq_cancel_revoke_shared(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await state.clear()
    await show_management_panel(call, ub_username, state)
    await call.answer()

@router.callback_query(F.data.startswith("owner_revoke_shared:"))
async def cq_owner_revoke_shared(call: types.CallbackQuery, state: FSMContext):
    _, ub_username, shared_id = call.data.split(":")
    shared_id = int(shared_id)
    await db.remove_userbot_shared_access(ub_username, shared_id)
    await call.answer("Доступ отозван.", show_alert=True)
    await show_management_panel(call, ub_username, state)

def check_panel_owner(call, owner_id: int) -> bool:
    if call.from_user.id != owner_id:
        import asyncio
        coro = call.answer("Это не ваша панель!", show_alert=True)
        if asyncio.iscoroutine(coro):
            asyncio.create_task(coro)
        return False
    return True

@router.callback_query(F.data.startswith("shared_reject_access:"))
async def cq_shared_reject_access(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    ub_username = call.data.split(":")[1]
    await db.remove_userbot_shared_access(ub_username, call.from_user.id)
    await call.answer("Вы отказались от доступа к панели.", show_alert=True)
    ub_data = await db.get_userbot_data(ub_username)
    owner_id = ub_data.get('tg_user_id') if ub_data else None
    if owner_id and owner_id != call.from_user.id:
        user = call.from_user
        user_display = f"@{user.username}" if user.username else user.full_name
        try:
            await bot.send_message(owner_id, f"ℹ️ Пользователь {user_display} (<code>{user.id}</code>) отказался от доступа к вашей панели <code>{html.quote(ub_username)}</code>.")
        except Exception:
            pass
    await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id, user_name=call.from_user.full_name, state=state, message_id=call.message.message_id)

def get_cancel_revoke_shared_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"cancel_share_panel:{ub_username}")
    return builder.as_markup()

@router.callback_query(F.data.startswith("cancel_share_panel:"))
async def cq_cancel_share_panel(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await state.clear()
    await show_management_panel(call, ub_username, state)
    await call.answer()

@router.callback_query(F.data.startswith("accept_share_panel:"), F.chat.type == "private")
async def cq_accept_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, ub_username, owner_id_str = call.data.split(":")
    await db.add_userbot_shared_access(ub_username, call.from_user.id)
    
    try:
        owner_id = int(owner_id_str)
        sharer_data_log = {"id": owner_id, "full_name": (await bot.get_chat(owner_id)).full_name}
        user_data_log = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        ub_info_log = {"name": ub_username}
        log_data = {"sharer_data": sharer_data_log, "user_data": user_data_log, "ub_info": ub_info_log}
        await log_event(bot, "panel_shared_accepted", log_data)
    except Exception as e:
        logging.error(f"Failed to log panel share event: {e}")

    await call.answer("✅ Доступ выдан! Теперь вы можете управлять этим юзерботом.", show_alert=True)
    await show_management_panel(call, ub_username, state)
    
    try:
        await bot.send_message(chat_id=int(owner_id_str), text=f"Пользователь <code>{call.from_user.id}</code> принял доступ к панели <code>{html.quote(ub_username)}</code>.")
    except TelegramForbiddenError:
        logging.warning(f"Не удалось уведомить владельца {owner_id_str} о принятии доступа: пользователь не начал диалог с ботом")
    except Exception as e:
        logging.error(f"Ошибка при уведомлении владельца {owner_id_str}: {e}")

@router.callback_query(F.data.startswith("manage_shared_access:"))
async def cq_manage_shared_access(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    shared_users = await db.get_userbot_shared_users(ub_username)
    if not shared_users:
        await call.answer("Нет пользователей с доступом.", show_alert=True)
        await show_management_panel(call, ub_username, state)
        return
    text = "<b>У кого есть доступ:</b>"
    buttons = []
    for shared_id in shared_users:
        shared_user = await db.get_user_data(shared_id)
        if shared_user:
            name = shared_user.get('full_name') or f"ID {shared_id}"
            username = shared_user.get('username')
            user_display = f"@{username}" if username else name
        else:
            user_display = f"ID {shared_id}"
        text += f"\n• {user_display} (<code>{shared_id}</code>)"
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ {user_display}",
                callback_data=f"remove_shared_access:{ub_username}:{shared_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_panel:{ub_username}")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await call.answer()

@router.callback_query(F.data.startswith("remove_shared_access:"))
async def cq_remove_shared_access(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, ub_username, shared_id = call.data.split(":")
    shared_id = int(shared_id)
    await db.remove_userbot_shared_access(ub_username, shared_id)

    try:
        sharer_data_log = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        shared_user_data = await db.get_user_data(shared_id)
        user_data_log = {"id": shared_id, "full_name": shared_user_data.get("full_name") if shared_user_data else str(shared_id)}
        ub_info_log = {"name": ub_username}
        log_data = {"sharer_data": sharer_data_log, "user_data": user_data_log, "ub_info": ub_info_log}
        await log_event(bot, "panel_share_revoked", log_data)
    except Exception as e:
        logging.error(f"Failed to log panel revoke event: {e}")

    await call.answer("Доступ отозван.", show_alert=True)
    await cq_manage_shared_access(call, state)

@router.callback_query(F.data.startswith("back_to_panel:"))
async def cq_back_to_panel_from_shared(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    await show_management_panel(call, ub_username, state)
    await call.answer()

@router.callback_query(F.data.startswith("reinstall_ub_start_request:"))
async def cq_reinstall_ub_start_request_fallback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer("Кнопка устарела, обновите панель.", show_alert=True)
        return
    _, ub_username, owner_id_str = parts
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    await call.answer("Функция переустановки временно недоступна.", show_alert=True)

async def get_userbot_rom_usage(ub_username: str, server_ip: str) -> dict:
    home_dir = f"/home/{ub_username}"
    cmd = f"df -m {home_dir} | awk 'NR==2{{print $3, $2}}'"
    res = await sm.run_command_async(cmd, server_ip)
    if res.get('success') and res.get('output'):
        try:
            used, total = map(int, res['output'].strip().split())
            percent = int(used / total * 100) if total else 0
            return {'used': used, 'total': total, 'percent': percent}
        except Exception:
            pass
    return {'used': 0, 'total': 0, 'percent': 0}
    
@router.callback_query(F.data.startswith("health_check_retry:"))
async def cq_health_check_retry(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Проверяю снова...")
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())

    ub_username = call.data.split(":")[1]
    ub_data = await db.get_userbot_data(ub_username)
    
    if not ub_data:
        await call.answer("❌ Юзербот не найден.", show_alert=True)
        await _show_main_panel(call.bot, call.message.chat.id, call.from_user.id, call.from_user.full_name, state, call.message.message_id)
        return

    server_ip = ub_data['server_ip']
    service_name = f"hikka-{ub_username}.service"
    
    service_file_exists = await sm.check_systemd_file_exists(service_name, server_ip)
    disk_space_ok = True  # Упрощенная проверка

    if not service_file_exists or not disk_space_ok:
        error_text = (
            f"<b>🎛 Панель управления</b>\n\n"
            f"<i>😢 На данный момент наблюдаются сбои в работе юзербота/сервера.</i>\n\n"
            f"<b>Повторите попытку через <code>10-15</code> минут</b>"
        )
        try:
            from config_manager import Config
            config = Config()
            admin_ids = getattr(config, 'SUPER_ADMIN_IDS', [])
            for admin_id in admin_ids:
                await bot.send_message(
                    admin_id,
                    f"⚠️ <b>Сбой юзербота/сервера</b>\n\n"
                    f"chat_id: <code>{chat_id}</code>\n"
                    f"service_file_exists: <code>{service_file_exists}</code>\n"
                    f"disk_space_ok: <code>{disk_space_ok}</code>\n"
                    f"Панель управления уведомила пользователя об ошибке."
                )
        except Exception as e:
            import logging
            logging.error(f"Не удалось отправить уведомление админам: {e}")
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data=f"health_check_retry:{ub_username}")
        builder.button(text="🔙 Назад", callback_data="back_to_main_panel")
        await call.message.edit_caption(caption=error_text, reply_markup=builder.as_markup())
    else:
        await show_management_panel(call, ub_username, state)

class HerokuBackupType(CallbackData, prefix="heroku_backup_type"):
    ub_username: str
    owner_id: int
    backup_type: str

@router.callback_query(F.data.startswith("heroku_backup:"))
async def cq_heroku_backup_start(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    _, ub_username, owner_id_str = call.data.split(":")
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    builder = InlineKeyboardBuilder()
    for btype, label in [("all", "all"), ("db", "db"), ("mods", "mods")]:
        builder.row(InlineKeyboardButton(text=label, callback_data=HerokuBackupType(ub_username=ub_username, owner_id=owner_id, backup_type=btype).pack()))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"refresh_panel:{ub_username}:{owner_id}"))
    await call.message.edit_caption(
        caption="<b>Выберите тип Бекапа:</b>",
        reply_markup=builder.as_markup()
    )
    await call.answer()

@router.callback_query(HerokuBackupType.filter())
async def cq_heroku_backup_type(call: types.CallbackQuery, callback_data: HerokuBackupType, bot: Bot):
    ub_username = callback_data.ub_username
    owner_id = callback_data.owner_id
    backup_type = callback_data.backup_type
    if not check_panel_owner(call, owner_id):
        return
    await call.answer("Создаю Бекап...", show_alert=False)
    await call.message.edit_caption(
        caption="<b>⏳ Создание Бекапа...</b>",
        reply_markup=kb.get_loading_keyboard()
    )
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data or ub_data.get("ub_type") != "heroku":
        await call.message.edit_caption(
            caption="❌ Бекап доступен только для Heroku-юзерботов.",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )
        return
    server_ip = ub_data["server_ip"]
    try:
        backup_path, backup_name = await sm.make_heroku_backup_ssh(ub_username, server_ip, backup_type)
        with open(backup_path, "rb") as f:
            await bot.send_document(
                chat_id=call.from_user.id,
                document=FSInputFile(backup_path, filename=backup_name),
                caption=f"<b>Backup ({backup_type})</b>",
                parse_mode="HTML"
            )
        sm.cleanup_heroku_backup_file(backup_path)
        await call.message.edit_caption(
            caption=f"✅ Бекап отправлен! Файл: <code>{backup_name}</code>",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )
    except Exception as e:
        logging.error(f"Ошибка при создании/отправке Бекапа: {e}\n{traceback.format_exc()}")
        # Truncate error message to avoid Telegram caption length limit
        error_msg = str(e)
        if len(error_msg) > 200:
            error_msg = error_msg[:197] + "..."
        
        await call.message.edit_caption(
            caption=f"❌ Ошибка при создании или отправке Бекапа: <code>{py_html.escape(error_msg)}</code>",
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )

@router.callback_query(F.data.startswith("select_server:"), UserBotSetup.ChoosingServer)
async def cq_select_server(call: types.CallbackQuery, state: FSMContext):
    server_ip = call.data.split(":")[1]
    await _proceed_to_type_selection(call, state, server_ip)

async def _proceed_to_type_selection(call: types.CallbackQuery, state: FSMContext, server_ip: str):
    from bot import BANNER_FILE_IDS
    await state.update_data(server_ip=server_ip)
    text = (
        "<b>[Шаг 2/3] Выбор типа юзербота</b>\n\n"
        "<blockquote><b>🌘 Hikka</b> - The most fresh and updateable developer-oriented Telegram userbot</blockquote>\n\n"
        "<blockquote><b>🪐 Heroku</b> — is the latest fork of Hikka with updates and endless fun!</blockquote>\n\n"
        "<blockquote><b>🦊 FoxUserbot</b> - Telegram Userbot built with Kurigram (Pyrogram).</blockquote>\n\n"
        "<blockquote><b>🌙 Legacy</b> —  modern, developer-oriented Telegram userbot with numerous bug fixes and up-to-date improvements, continuously maintained for the latest features and stability.</blockquote>"
    )
    photo = BANNER_FILE_IDS.get("select_userbot") or FSInputFile("banners/select_userbot.png")
    
    data = await state.get_data()
    message_id = data.get("message_id_to_edit", call.message.message_id)

    try:
        await call.bot.edit_message_media(
            chat_id=call.message.chat.id, message_id=message_id,
            media=InputMediaPhoto(media=photo, caption=text),
            reply_markup=kb.get_select_ub_type_keyboard(server_ip),
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await call.answer()
        else:
            raise

    await state.set_state(UserBotSetup.ChoosingUserBotType)

def parse_ps_etime_to_human(etime: str) -> str:
    etime = etime.strip()
    days = 0
    hours = 0
    minutes = 0
    if '-' in etime:
        days_part, time_part = etime.split('-', 1)
        try:
            days = int(days_part)
        except Exception:
            days = 0
    else:
        time_part = etime
    parts = time_part.split(':')
    if len(parts) == 3:
        hours, minutes, _ = parts
    elif len(parts) == 2:
        hours, minutes = parts
    else:
        hours = 0
        minutes = 0
    try:
        hours = int(hours)
        minutes = int(minutes)
    except Exception:
        hours = 0
        minutes = 0
    result = []
    if days:
        result.append(f"{days}d")
    if hours:
        result.append(f"{hours}h")
    if minutes:
        result.append(f"{minutes}m")
    return ' '.join(result) if result else '~1m'

async def _generate_and_save_token(user: types.User) -> str:
    username = user.username or f"user{user.id}"
    random_part = secrets.token_hex(18)
    new_token = f"{username}:{user.id}:{random_part}"
    await db.set_api_token(user.id, new_token)
    return new_token
    
def _mask_token(token: str) -> str:
    if not token or ':' not in token:
        return "********************"
    parts = token.split(':')
    if len(parts) < 3:
        return "********************"
    return f"{parts[0]}:{parts[1]}:{'*' * len(parts[2])}"

async def _get_or_create_token(user: types.User) -> str:
    user_data = await db.get_user_data(user.id)
    token = user_data.get("api_token")
    if not token:
        token = await _generate_and_save_token(user)
    return token

@router.callback_query(F.data == "api_panel_show")
async def cq_show_api_panel(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    token = await _get_or_create_token(call.from_user)
    
    text = (
        "🔑 <b>Ваш персональный API-токен</b>\n\n"
        "Этот токен используется для доступа к API SharkHost из внешних приложений.\n\n"
        "<b>Никому не передавайте этот токен!</b>\n\n"
        "Ваш токен:\n"
        f"<code>{html.quote(_mask_token(token))}</code>"
    )
    
    markup = kb.get_api_token_keyboard(is_shown=False)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await state.set_state(APITokenManagement.TokenHidden)
    
@router.callback_query(F.data == "toggle_api_token_visibility", StateFilter(APITokenManagement.TokenHidden, APITokenManagement.TokenShown))
async def cq_toggle_api_token_visibility(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    current_state = await state.get_state()
    token = await _get_or_create_token(call.from_user)
    
    is_currently_shown = current_state == APITokenManagement.TokenShown
    
    new_text_token = _mask_token(token) if is_currently_shown else token
    new_is_shown = not is_currently_shown
    new_state = APITokenManagement.TokenHidden if is_currently_shown else APITokenManagement.TokenShown

    text = (
        "🔑 <b>Ваш персональный API-токен</b>\n\n"
        "Этот токен используется для доступа к API SharkHost из внешних приложений.\n\n"
        "<b>Никому не передавайте этот токен!</b>\n\n"
        "Ваш токен:\n"
        f"<code>{html.quote(new_text_token)}</code>"
    )
    
    markup = kb.get_api_token_keyboard(is_shown=new_is_shown)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await state.set_state(new_state)

@router.callback_query(F.data == "regenerate_api_token", StateFilter(APITokenManagement.TokenHidden, APITokenManagement.TokenShown))
async def cq_regenerate_api_token(call: types.CallbackQuery, state: FSMContext):
    user = call.from_user
    new_token = secrets.token_urlsafe(32)
    
    if await db.regenerate_user_token(user.id, new_token):
        await state.update_data(token=new_token)
        await call.answer("✅ API токен успешно обновлен!")
        await cq_show_api_panel(call, state)
    else:
        await call.answer("❌ Ошибка обновления токена", show_alert=True)



# --- END OF FILE user_handlers.py ---