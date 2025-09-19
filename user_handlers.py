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
from aiogram.filters import Command, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramForbiddenError
from aiogram.types import InputMediaPhoto, FSInputFile, InputFile
from aiogram.types import InlineQuery, InputTextMessageContent, InlineQueryResultArticle, InlineQueryResultPhoto, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hlink
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramBadRequest
import html as py_html
import traceback

import keyboards as kb
import system_manager as sm
import server_config
import database as db
from api_manager import api_manager
from states import UserBotSetup, UserBotTransfer, UserReview, CommitEditing, APITokenManagement
from admin_manager import get_all_admins
from config_manager import config
from channel_logger import log_event
import math
from utils.copy import CopyTextButton
from filters import IsBotEnabled, IsSubscribed, IsAdmin
import time
# from system_manager import get_service_process_uptime

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsBotEnabled())
router.callback_query.filter(IsBotEnabled())

LOG_LINES_PER_PAGE = 25
SERVERS_PER_PAGE = 10

PING_COOLDOWN_SECONDS = 5
PING_TIMESTAMPS = {}

async def _show_server_selection_page(call: types.CallbackQuery, state: FSMContext, page: int = 1):
    from bot import BANNER_FILE_IDS
    
    user_id = call.from_user.id
    has_premium = await db.check_premium_access(user_id)
    
    all_servers = server_config.get_servers()
    all_userbots = await db.get_all_userbots_full_info()
    installed_bots_map = defaultdict(int)
    for ub in all_userbots:
        installed_bots_map[ub['server_ip']] += 1

    server_ips = [ip for ip in all_servers if ip != sm.LOCAL_IP]
    
    available_servers_filtered = []
    for ip in server_ips:
        details = all_servers[ip]
        status = details.get("status")
        if status == 'false':
            continue
        if status == 'test' and user_id not in get_all_admins():
            continue
        available_servers_filtered.append((ip, details))

    def sort_key(server_info):
        ip, details = server_info
        slots = details.get('slots', 0)
        installed = installed_bots_map.get(ip, 0)
        is_full = slots > 0 and installed >= slots
        free_slots = slots - installed if slots > 0 else float('inf')
        return is_full, -free_slots

    sorted_servers = sorted(available_servers_filtered, key=sort_key)
    
    total_pages = math.ceil(len(sorted_servers) / SERVERS_PER_PAGE) if sorted_servers else 1
    page = max(1, min(page, total_pages))
    start_index = (page - 1) * SERVERS_PER_PAGE
    end_index = start_index + SERVERS_PER_PAGE
    servers_on_page = sorted_servers[start_index:end_index]
    
    data = await state.get_data()
    server_stats = data.get("server_stats", {})
    
    markup = kb.get_server_selection_keyboard(
        user_id=user_id,
        installed_bots_map=installed_bots_map,
        server_stats=server_stats,
        servers_on_page=servers_on_page,
        page=page,
        total_pages=total_pages,
        has_premium_access=has_premium
    )
    
    text = "<b>⬇️ Установка</b>\n\n<b>💻 Выберите сервер, на который хотите установить юзербот</b>"
    photo = BANNER_FILE_IDS.get("select_server") or FSInputFile("banners/select_server.png")
    message_id = data.get("message_id_to_edit", call.message.message_id)

    try:
        await call.bot.edit_message_media(
            chat_id=call.message.chat.id, message_id=message_id,
            media=InputMediaPhoto(media=photo, caption=text),
            reply_markup=markup
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Error editing server selection page: {e}")
            
@router.callback_query(F.data == "premium_server_locked", UserBotSetup.ChoosingServer)
async def cq_premium_server_locked(call: types.CallbackQuery):
    await call.answer(
        "Данный сервер является премиум, для покупки доступа к нему обратитесь: @nloveuser",
        show_alert=True
    )

@router.callback_query(F.data.startswith("select_server_page:"), UserBotSetup.ChoosingServer)
async def cq_select_server_page(call: types.CallbackQuery, state: FSMContext):
    try:
        page = int(call.data.split(":")[1])
        await call.answer()
        await _show_server_selection_page(call, state, page)
    except (ValueError, IndexError):
        await call.answer("Ошибка данных пагинации.", show_alert=True)

review_warned_users = defaultdict(lambda: False)

async def safe_callback_answer(call: types.CallbackQuery, text: str, show_alert: bool = False) -> bool:
    """
    Безопасно отвечает на callback query, обрабатывая устаревшие queries
    
    Args:
        call: CallbackQuery объект
        text: Текст ответа
        show_alert: Показывать ли alert
        
    Returns:
        True если ответ успешен, False если произошла ошибка
    """
    try:
        await call.answer(text, show_alert=show_alert)
        return True
    except TelegramBadRequest as tg_error:
        if "query is too old" in str(tg_error).lower() or "response timeout expired" in str(tg_error).lower():
            logging.warning(f"Callback query устарел для пользователя {call.from_user.id}: {tg_error}")
        else:
            logging.error(f"TelegramBadRequest при ответе на callback: {tg_error}")
        return False
    except Exception as e:
        logging.error(f"Не удалось ответить на callback query: {e}")
        return False

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

def format_container_stats(stats_data: dict) -> str:
    """Форматирует статистику контейнера в читаемый вид (поддержка нового формата /api/host/cont_stat)"""
    if not stats_data:
        return "❌ Статистика недоступна"

    # Новый формат: ключ info
    info = stats_data.get("info")
    if info:
        container_name = info.get("container", "N/A")
        cpu_percent = info.get("cpu_percent", 0)
        cpu_limit = info.get("cpu_limit", 0)
        ram_usage = info.get("ram_usage_mb", 0)
        ram_limit = info.get("ram_limit_mb", 0)
        ram_percent = info.get("ram_percent", 0)
        disk_usage = info.get("disk_usage_mb", 0)
        disk_limit = info.get("disk_limit_mb", 0)
        disk_percent = info.get("disk_percent", 0)

        result = f"📊 <b>Статистика контейнера</b>\n\n"
        result += f"🔸 <b>Имя:</b> <code>{container_name}</code>\n"
        result += f"🔸 <b>CPU:</b> {cpu_percent:.2f}% (лимит: {cpu_limit})\n"
        result += f"🔸 <b>RAM:</b> {ram_percent:.2f}% ({ram_usage:.1f}MB / {ram_limit:.1f}MB)\n"
        result += f"🔸 <b>ROM:</b> {disk_percent:.2f}% ({disk_usage}MB / {disk_limit}MB)\n"
        return result

    # Старый формат (оставляем для обратной совместимости)
    if "stats" not in stats_data:
        return "❌ Статистика недоступна"
    stats = stats_data["stats"]
    inspect = stats_data.get("inspect", {})
    container_name = stats.get("name", "N/A").replace("/", "")
    status = "🟢 Работает" if inspect.get("State", {}).get("Running", False) else "🔴 Остановлен"
    memory_stats = stats.get("memory_stats", {})
    memory_usage = memory_stats.get("usage", 0)
    memory_limit = memory_stats.get("limit", 1)
    memory_percent = (memory_usage / memory_limit * 100) if memory_limit > 0 else 0
    cpu_stats = stats.get("cpu_stats", {})
    cpu_usage = cpu_stats.get("cpu_usage", {})
    total_cpu_usage = cpu_usage.get("total_usage", 0)
    system_cpu_usage = cpu_stats.get("system_cpu_usage", 1)
    cpu_percent = (total_cpu_usage / system_cpu_usage * 100) if system_cpu_usage > 0 else 0
    networks = stats.get("networks", {})
    eth0_stats = networks.get("eth0", {})
    rx_bytes = eth0_stats.get("rx_bytes", 0)
    tx_bytes = eth0_stats.get("tx_bytes", 0)
    pids_stats = stats.get("pids_stats", {})
    current_pids = pids_stats.get("current", 0)
    created = inspect.get("Created", "")
    started_at = inspect.get("State", {}).get("StartedAt", "")
    result = f"📊 <b>Статистика контейнера</b>\n\n"
    result += f"🔸 <b>Имя:</b> <code>{container_name}</code>\n"
    result += f"🔸 <b>Статус:</b> {status}\n"
    result += f"🔸 <b>Память:</b> {memory_percent:.1f}% ({memory_usage // 1024 // 1024}MB / {memory_limit // 1024 // 1024}MB)\n"
    result += f"🔸 <b>CPU:</b> {cpu_percent:.1f}%\n"
    result += f"🔸 <b>Процессы:</b> {current_pids}\n"
    result += f"🔸 <b>Сеть:</b> ↓{rx_bytes // 1024}KB ↑{tx_bytes // 1024}KB\n"
    if created:
        result += f"🔸 <b>Создан:</b> {created[:19].replace('T', ' ')}\n"
    if started_at:
        result += f"🔸 <b>Запущен:</b> {started_at[:19].replace('T', ' ')}\n"
    return result

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
            f"<blockquote>☕ Добро пожаловать в панель управления хостингом <b>TeaHost</b>. "
            f"Здесь вы можете легко управлять своими юзерботами.</blockquote>")
    markup = kb.get_main_panel_keyboard(has_bots=bool(user_bots), user_id=owner_id, chat_id=chat_id, is_chat=is_chat)
    photo = BANNER_FILE_IDS.get("main_panel") or FSInputFile("banners/select_action.png")

    if message_id:
        try:
            # Простое решение: всегда пытаемся обновить только caption и markup
            # Если это не работает, то отправляем новое сообщение с фото
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=markup
                )
            except TelegramBadRequest:
                # Если не удалось обновить caption, отправляем новое сообщение с фото
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
       

async def _parse_container_stats(stats_data: dict) -> dict:
    resources = {'cpu_percent': '0.0', 'ram_percent': '0.0', 'ram_used': 0, 'ram_limit': 0}

    if not stats_data:
        return resources

    info = stats_data.get("info")
    if info and isinstance(info, dict):
        resources['cpu_percent'] = round(info.get("cpu_percent", 0), 1)
        resources['ram_used'] = round(info.get("ram_usage_mb", 0))
        resources['ram_limit'] = round(info.get("ram_limit_mb", 0))
        resources['ram_percent'] = round(info.get("ram_percent", 0), 1)
        if resources['cpu_percent'] > 0 or resources['ram_used'] > 0:
            return resources
            
    stats = stats_data.get("stats")
    if not stats or not isinstance(stats, dict):
        return resources 

    try:
        memory_stats = stats.get("memory_stats", {})
        memory_usage = memory_stats.get("usage", 0)
        memory_limit = memory_stats.get("limit", 1)
        
        if memory_limit > 0 and memory_usage > 0:
            resources['ram_used'] = round(memory_usage / (1024 * 1024))
            resources['ram_limit'] = round(memory_limit / (1024 * 1024))
            resources['ram_percent'] = round((memory_usage / memory_limit * 100), 1) if memory_limit > 0 else 0.0

        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        online_cpus = cpu_stats.get("online_cpus", 1)
        
        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        system_cpu_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

        if system_cpu_delta > 0 and cpu_delta > 0:
            cpu_percent = (cpu_delta / system_cpu_delta) * online_cpus * 100.0
            resources['cpu_percent'] = round(cpu_percent, 1)
            
    except (TypeError, KeyError, IndexError, ZeroDivisionError) as e:
        logging.error(f"Не удалось полностью разобрать статистику Docker: {e}")

    return resources
        
async def show_management_panel(call_or_message: types.Message | types.CallbackQuery, ub_username: str, state: FSMContext = None):
    from bot import BANNER_FILE_IDS
    is_callback = isinstance(call_or_message, types.CallbackQuery)
    message = call_or_message.message if is_callback else call_or_message
    user = call_or_message.from_user
    bot = message.bot

    if state:
        await state.clear()

    ub_data = await db.get_userbot_data(ub_username)

    if not ub_data:
        if is_callback:
            await safe_callback_answer(call_or_message, "❌ Этот юзербот был удален или у вас нет доступа.", show_alert=True)
        await _show_main_panel(bot=bot, chat_id=message.chat.id, user_id=user.id, user_name=user.full_name, state=state, message_id=message.message_id, topic_id=message.message_thread_id)
        return

    if ub_data.get('status') == 'installing':
        if is_callback:
            await safe_callback_answer(call_or_message, "⏳ Установка юзербота в процессе...\n\nПанель управления будет доступна после завершения установки.", show_alert=True)
        else:
            await message.answer("⏳ <b>Установка юзербота в процессе...</b>\n\nПанель управления будет доступна после завершения установки и настройки всех систем безопасности.", parse_mode="HTML")
        return

    if ub_data.get('status') == 'deleting':
        if is_callback:
            await safe_callback_answer(call_or_message, "🗑️ Удаление юзербота в процессе...\n\nПанель управления недоступна во время удаления.", show_alert=True)
        else:
            await message.answer("🗑️ <b>Удаление юзербота в процессе...</b>\n\nПанель управления недоступна во время удаления юзербота.", parse_mode="HTML")
        return

    server_ip = ub_data.get('server_ip', 'N/A')
    is_server_active = server_config.get_server_status_by_ip(server_ip) not in ["false", "not_found"]
    
    is_running = False
    if is_server_active:
        container_status = await api_manager.get_container_status(ub_username, server_ip)
        if not container_status.get("success"):
            is_running = False
            error_msg = container_status.get("error", "Неизвестная ошибка")
            if "404" in error_msg or "not found" in error_msg.lower():
                user_data_for_log = {"id": user.id, "full_name": user.full_name}
                server_details_for_log = server_config.get_servers().get(server_ip, {})
                log_data = {
                    "user_data": user_data_for_log,
                    "ub_info": {"name": ub_username},
                    "server_info": {"ip": server_ip, "code": server_details_for_log.get("code", "N/A")},
                    "error": error_msg
                }
                asyncio.create_task(log_event(bot, "api_container_error", log_data))
        else:
            is_running = container_status.get("data", {}).get("status") == "running"
    
    server_details = server_config.get_servers().get(server_ip, {})
    server_display = f"{server_details.get('flag', '🏳️')} {server_details.get('code', 'N/A')}"
    server_location = f"{server_details.get('country', 'N/A')}, {server_details.get('city', 'N/A')}"
    
    ping_ms_val = await api_manager.get_server_ping(server_ip) if is_server_active else None
    
    resources = {
        'cpu_percent': '0.0', 
        'ram_percent': '0.0', 'ram_used': 0, 'ram_limit': 0,
        'disk_percent': '0.0', 'disk_used': 0, 'disk_limit': 0
    }
    
    if is_server_active and is_running:
        stats_result = await api_manager.get_container_stats(ub_username, server_ip)
        if stats_result.get("success"):
            info = stats_result.get("data", {}).get("info", {})
            if info:
                resources['cpu_percent'] = round(info.get("cpu_percent") or 0.0, 1)
                resources['ram_used'] = round(info.get("ram_usage_mb") or 0)
                resources['ram_limit'] = round(info.get("ram_limit_mb") or 0)
                resources['ram_percent'] = round(info.get("ram_percent") or 0.0, 1)
                resources['disk_used'] = round(info.get("disk_usage_mb") or 0)
                resources['disk_limit'] = round(info.get("disk_limit_mb") or 0)
                resources['disk_percent'] = round(info.get("disk_percent") or 0.0, 1)

    webui_port = ub_data.get('webui_port')
    
    if not is_server_active:
        status_text = "⚪️ Сервер отключен"
    elif is_running:
        status_text = "🟢 Включен"
    else:
        status_text = "🔴 Выключен"
        
    creation_date_str = ub_data['created_at'].strftime('%d.%m.%Y в %H:%M') if ub_data.get('created_at') else "Неизвестно"
    
    ping_display = f"📡 Пинг: {ping_ms_val:.1f} мс" if ping_ms_val is not None else "📡 Пинг: N/A"

    server_info_block = (
        "<blockquote expandable><b>Информация о сервере:</b>\n"
        f"🖥 Сервер: {server_display}\n"
        f"🌍 Локация: {server_location}\n"
        f"{ping_display}"
        "</blockquote>"
    )

    text_lines = [
        "<b>🎛 Панель управления</b>\n",
        "<blockquote expandable>"
        "<b>Основная информация:</b>\n"
        f"🤖 Юзербот: {html.quote(ub_username)}\n"
        f"💡 Статус: {status_text}\n"
        f"⚙️ Тип: {ub_data.get('ub_type', 'N/A').capitalize()}\n"
        f"📅 Создан: {creation_date_str}"
        "</blockquote>",
        server_info_block,
        "<blockquote expandable>"
        "<b>Потребление ресурсов:</b>\n"
        f"🧠 CPU: {_create_progress_bar(str(resources.get('cpu_percent', 0)))} ({resources.get('cpu_percent', 0)}%)\n"
        f"💾 RAM: {_create_progress_bar(str(resources.get('ram_percent', 0)))} ({resources.get('ram_used', 0)} / {resources.get('ram_limit', 0)} МБ)\n"
        f"💽 ROM: {_create_progress_bar(str(resources.get('disk_percent', 0)))} ({resources.get('disk_used', 0)} / {resources.get('disk_limit', 0)} МБ)"
        "</blockquote>\n"
    ]
    update_time_str = datetime.now(pytz.timezone("Europe/Moscow")).strftime('%H:%M:%S')
    text_lines.append(f"<i>Последнее обновление: {update_time_str} MSK</i>")
    text = "\n".join(text_lines)
    
    is_owner = ub_data.get('tg_user_id') == user.id
    is_super_admin = user.id in config.SUPER_ADMIN_IDS
    
    markup = kb.get_management_keyboard(
        ip=server_ip, port=webui_port,
        is_running=is_running, ub_username=ub_username,
        ub_type=ub_data.get('ub_type', 'N/A'), is_server_active=is_server_active,
        is_owner=is_owner, is_private=message.chat.type == 'private',
        owner_id=user.id, is_shared=False,
        is_installing=(ub_data.get('status') == 'installing'),
        is_deleting=(ub_data.get('status') == 'deleting'),
        is_super_admin=is_super_admin
    )
    
    photo = BANNER_FILE_IDS.get("panel_userbot") or FSInputFile("banners/panel_userbot.png")
    
    try:
        if is_callback:
            try:
                await message.edit_caption(caption=text, reply_markup=markup)
            except TelegramBadRequest as edit_error:
                if "message is not modified" in str(edit_error).lower():
                    await safe_callback_answer(call_or_message, "", show_alert=True)
                    return
                await message.edit_media(media=InputMediaPhoto(media=photo, caption=text), reply_markup=markup)
        else:
            await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text, reply_markup=markup, message_thread_id=message.message_thread_id)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            if is_callback:
                await safe_callback_answer(call_or_message, "", show_alert=True)
            return
        logging.warning(f"Could not edit message to panel. Re-sending. Error: {e}")
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except (TelegramBadRequest, TelegramNotFound):
            pass
        finally:
            await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text, reply_markup=markup, message_thread_id=message.message_thread_id)
            
async def _safe_cleanup_on_failure(ub_username: str, server_ip: str, state: FSMContext):
    # Удаляем контейнер через API
    await api_manager.delete_container(ub_username, server_ip)
    
    # Удаляем запись из базы данных
    if await db.get_userbot_data(ub_username=ub_username):
        await db.delete_userbot_record(ub_username)
    
    await state.clear()

async def _show_login_link_success_from_new_message(
    bot: Bot,
    chat_id: int,
    ub_username: str,
    login_url: str | None,
    state: FSMContext
):
    data = await state.get_data()
    ub_type = data.get("selected_ub_type")
    server_ip = data.get("server_ip")

    ub_data = await db.get_userbot_data(ub_username=ub_username)
    auth_data = await db.get_password(chat_id)
    username = auth_data.get("username", "unknown")
    password = auth_data.get("password", "unknown")

    final_url = None
    if ub_data and ub_data.get("webui_port"):
        final_url = f"https://{ub_username}.sharkhost.space"
    elif login_url:
        final_url = login_url

    text_parts = [
        "<blockquote>🌟 <b>Установка успешно завершена!</b></blockquote>\n",
        "<blockquote>🎉 Ваш юзербот готов к работе!</blockquote>\n",
        "<blockquote>🔑 Ваш пароль для авторизации ниже, вы можете его скопировать нажав на кнопку</blockquote>\n",
        "<blockquote>⚠️ <b>Важная информация:</b>\n"
        "• Если возникает ошибка <b>401</b> - используйте браузер <b>Chrome</b>\n"
        "• Данные для авторизации можно посмотреть в панели управления бота\n"
        "• Логин и пароль генерируются автоматически\n"
        "• Если не работает сайт - используйте VPN из панели управления\n"
        "• Для VPN скачайте v2raytun или hiddify</blockquote>\n",
        "<blockquote>🎯 <b>Управление юзерботом:</b>\n"
        "• Для управления перейдите в /start → Панель управления\n"
        "• Там вы найдете все необходимые инструменты</blockquote>\n",
        "<blockquote>💫 <b>Спасибо, что выбрали TeaHost!</b>\n"
        "Мы ценим ваше доверие ❤️</blockquote>",
    ]

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

    buttons: list[list[InlineKeyboardButton]] = []

    if final_url:
        buttons.append([
            InlineKeyboardButton(
                text="🚀 Перейти в панель управления",
                web_app=WebAppInfo(url=final_url)
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔑 Скопировать пароль",
            copy_text=CopyTextButton(text=password)
        )
    ])

    panel = kb.userbot_panel()
    if isinstance(panel, InlineKeyboardMarkup):
        buttons.extend(panel.inline_keyboard)

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await bot.send_message(
        chat_id=chat_id,
        text="".join(text_parts),
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode="HTML",
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
    
async def wait_for_webui_ready(ub_username: str, server_ip: str, max_wait_time: int = 120) -> str | None:
    """
    Ждет готовности веб-интерфейса, проверяя логи каждые 10 секунд
    Возвращает URL для входа или None если не удалось найти
    """
    import re
    
    # Паттерны для поиска готовности веб-интерфейса
    ready_patterns = [
        r'🔎 Web mode ready for configuration',
        r'🔗 Please visit http://',
        r'Heroku Userbot Web Interface running on',
        r'Web mode ready for configuration',
        r'Please visit http://',
        r'Running on http://127\.0\.0\.1:\d+',  # Fox Userbot
        r'Running on http://localhost:\d+'  # Fox Userbot альтернативный вариант
    ]
    
    start_time = time.time()
    check_interval = 10
    
    while time.time() - start_time < max_wait_time:
        try:
            # Получаем логи контейнера
            logs_result = await api_manager.get_container_logs(ub_username, server_ip)
            
            if not logs_result.get("success"):
                logger.warning(f"Не удалось получить логи для {ub_username}: {logs_result.get('error')}")
                await asyncio.sleep(check_interval)
                continue
            
            logs_data = logs_result.get("data", {})
            logs_text = logs_data.get("logs", "")
            
            if not logs_text:
                logger.debug(f"Логи пусты для {ub_username}")
                await asyncio.sleep(check_interval)
                continue
            
            # Ищем признаки готовности веб-интерфейса
            for pattern in ready_patterns:
                if re.search(pattern, logs_text, re.IGNORECASE):
                    # Ищем URL в логах
                    url_match = re.search(r'http://[^\s]+', logs_text)
                    if url_match:
                        login_url = url_match.group(0)
                        logger.info(f"Веб-интерфейс готов для {ub_username}: {login_url}")
                        return login_url
            
            logger.debug(f"Веб-интерфейс еще не готов для {ub_username}, продолжаем ожидание...")
            await asyncio.sleep(check_interval)
            
        except Exception as e:
            logger.error(f"Ошибка при проверке готовности веб-интерфейса для {ub_username}: {e}")
            await asyncio.sleep(check_interval)
    
    logger.warning(f"Таймаут ожидания готовности веб-интерфейса для {ub_username}")
    return None

async def perform_installation_and_find_link(tg_user_id: int, chat_id: int, message_id: int, state: FSMContext, bot: Bot, is_private: bool = True):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    ub_type = data.get("selected_ub_type")
    server_ip = data.get("server_ip")
    
    # Генерируем случайный порт
    port = await db.generate_random_port()
    if port is None:
        await bot.edit_message_caption(
            caption="❌ <b>Ошибка:</b> Не удалось найти свободный порт. Попробуйте позже.\n\n/start",
            chat_id=chat_id, message_id=message_id
        )
        return

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

    # Создаем контейнер через API
    container_result = await api_manager.create_container(
        name=ub_username,
        port=port,
        userbot=ub_type,
        server_ip=server_ip
    )
    vpn_result = await api_manager.create_vpn(f"ub{tg_user_id}")
    vless_link = None
    for link in vpn_result.get("data", {}).get("links", []):
        vless_link = link
        await db.add_vpn(tg_user_id, link)
        continue

    if not container_result.get("success"):
        err = container_result.get('error', 'Неизвестная ошибка.')
        await bot.edit_message_caption(
            caption=f"❌ <b>Ошибка создания контейнера:</b>\n{html.quote(err)}\n\n/start",
            chat_id=chat_id, message_id=message_id
        )
        # Сохраняем пароль даже при ошибке (если он есть в ответе)
        container_data = container_result.get("data", {}).get("data", {})
        username = container_data.get("username")
        password = container_data.get("password")
        if username and password:
            await db.add_password(tg_user_id, username, password)
        log_data["error"] = err
        await log_event(bot, "installation_failed", log_data)
        return

    # Извлекаем данные из успешного ответа
    container_data = container_result.get("data", {}).get("data", {})
    username = container_data.get("username")
    password = container_data.get("password")
    subdomain = container_data.get("subdomain")
    
    # Сохраняем пароль в базу данных
    if username and password:
        await db.add_password(tg_user_id, username, password)

    # Добавляем запись в базу данных
    db_success = await db.add_userbot_record(
        tg_user_id=tg_user_id,
        ub_username=ub_username,
        ub_type=ub_type,
        server_ip=server_ip,
        webui_port=port
    )

    if not db_success:
        # Если не удалось добавить в БД, удаляем контейнер
        await api_manager.delete_container(ub_username, server_ip)
        await bot.edit_message_caption(
            caption="❌ <b>Ошибка:</b> Не удалось сохранить данные в базе. Попробуйте позже.\n\n/start",
            chat_id=chat_id, message_id=message_id
        )
        return

    # Обновляем сообщение о том, что ждем готовности веб-интерфейса
    await bot.edit_message_caption(
        caption="⏳ <b>Идет запуск веб-интерфейса!</b>\n\n<blockquote>Это займет примерно 30 секунд. Подождите.</blockquote>",
        chat_id=chat_id, message_id=message_id
    )

    # Ждем готовности веб-интерфейса
    login_url = await wait_for_webui_ready(ub_username, server_ip)
    
    if login_url:
        # Веб-интерфейс готов - обновляем статус на running
        await db.update_userbot_status(ub_username, "running")
        
        # Веб-интерфейс готов
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
    else:
        # Таймаут - обновляем статус на stopped и показываем сообщение с возможностью повторить
        await db.update_userbot_status(ub_username, "stopped")
        
        await bot.edit_message_caption(
            caption="⏳ <b>Время вышло.</b>\n\nНе удалось автоматически найти ссылку для входа за 2 минуты. "
                    f"Попробуйте запросить ссылку снова.",
            chat_id=chat_id, message_id=message_id,
            reply_markup=kb.get_retry_login_link_keyboard(ub_username)
        )
        await log_event(bot, "installation_timeout", log_data)

@router.message(Command("start"), F.chat.type != "private")
async def cmd_start_in_chat(message: types.Message):
    pass

@router.message(Command("review"), F.chat.type != "private")
async def cmd_review_in_chat(message: types.Message):
    pass

@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot, command: CommandObject):
    print(f"DEBUG: Получена команда /start от пользователя {message.from_user.id}")
    try:
        user = message.from_user
        if await db.is_user_banned(user.id):
            ban_message = "❌ <b>Вы забанены.</b>\n\nДоступ к боту для вас ограничен."
            await message.answer(ban_message, message_thread_id=message.message_thread_id)
            return
        
        is_new_user = not await db.get_user_data(user.id)
        
        # Обработка реферальной ссылки
        ref_name = None
        if command.args and command.args.startswith("ref_"):
            ref_name = command.args[4:]  # Убираем "ref_" префикс
            if is_new_user:
                await db.add_referral_activation(ref_name, user.id)
                logging.info(f"Новый пользователь {user.id} активировал бота по реферальной ссылке: {ref_name}")
        
        await db.register_or_update_user(tg_user_id=user.id, username=user.username, full_name=user.full_name)
        if not await db.has_user_accepted_agreement(user.id) and not config.TEST_MODE:
            if is_new_user:
                user_data_for_log = {"id": user.id, "full_name": user.full_name}
                if ref_name:
                    user_data_for_log["referral"] = ref_name
                await log_event(bot, "new_user_registered", {"user_data": user_data_for_log})
            text = ("👋 <b>Добро пожаловать в TeaHost!</b>\n\n"
                    "Прежде чем мы начнем, ознакомьтесь с нашим пользовательским соглашением. "
                    "Нажимая кнопку «Принять и продолжить», вы подтверждаете, что прочитали и согласны с нашими правилами.")
            await message.answer(text, reply_markup=kb.get_agreement_keyboard())
        else:
            await _show_main_panel(bot=bot, chat_id=message.chat.id, user_id=user.id, user_name=user.full_name, state=state, topic_id=message.message_thread_id, owner_id=user.id)
    except Exception as e:
        logging.error(f"Ошибка при обработке команды /start: {e}")
        await message.answer("Произошла ошибка при обработке команды /start, Попробуйте еще раз.")

@router.message(Command("review"), F.chat.type == "private")
async def cmd_review(message: types.Message, state: FSMContext):
    text = (
        "✍️ <b>Напишите отзыв о TeaHost</b>\n\n"
        "ℹ️ В отзыве можете рассказать о том, сколько пользуетесь TeaHost, какие отличия заметили от предыдущего хостинга и т.д.\n\n"
        "📅 В ближайшее время отзыв будет опубликован на @TeaHostReviews."
    )
    sent_message = await message.reply(text, reply_markup=kb.get_cancel_review_keyboard())
    await state.update_data(original_bot_message_id=sent_message.message_id)
    await state.set_state(UserReview.WaitingForReview)

@router.callback_query(F.data == "accept_agreement")
async def cq_accept_agreement(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        user = call.from_user
        await db.register_or_update_user(tg_user_id=user.id, username=user.username, full_name=user.full_name)
        await db.set_user_agreement_accepted(user.id)
        await safe_callback_answer(call, "Спасибо! Теперь вы можете пользоваться всеми функциями бота.", show_alert=True)
        await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=user.id, user_name=user.full_name, state=state, message_id=call.message.message_id, topic_id=call.message.message_thread_id)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data == "back_to_main_panel")
async def cq_back_to_main_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await safe_callback_answer(call, "", show_alert=True)
        await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id, user_name=call.from_user.full_name, state=state, message_id=call.message.message_id, topic_id=call.message.message_thread_id)
        await safe_callback_answer(call, "", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data == "back_to_main_panel_delete")
async def cq_back_to_main_panel_delete(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await safe_callback_answer(call, "", show_alert=True)
        await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id, user_name=call.from_user.full_name, state=state, topic_id=call.message.message_thread_id)
        await safe_callback_answer(call, "", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

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
    tasks = [sm.get_server_stats(ip) for ip in servers.keys()]
    stats_results = await asyncio.gather(*tasks, return_exceptions=True)
    server_stats = {ip: result for ip, result in zip(servers.keys(), stats_results) if not isinstance(result, Exception)}
    await state.update_data(server_stats=server_stats)
    
    await _show_server_selection_page(call, state, page=1)
    await state.set_state(UserBotSetup.ChoosingServer)

@router.callback_query(F.data == "create_userbot_start", IsSubscribed(), StateFilter("*"))
async def cq_create_userbot_start(call: types.CallbackQuery, state: FSMContext):
    try:
        if len(await db.get_userbots_by_tg_id(call.from_user.id)) >= 1:
            await safe_callback_answer(call, "❌ У вас уже есть юзербот. Вы можете установить только одного.", show_alert=True)
            return
        
        await state.clear()
        await safe_callback_answer(call, "", show_alert=True)
        await _start_installation_flow(call, state)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

class ReinstallUBCallback(CallbackData, prefix="reinstall_ub_start_request"):
    ub_username: str
    owner_id: int
    
@router.callback_query(ReinstallUBCallback.filter())
async def cq_reinstall_ub_start_request(call: types.CallbackQuery, callback_data: ReinstallUBCallback, state: FSMContext, bot: Bot):
    try:
        ub_username = callback_data.ub_username
        owner_id = callback_data.owner_id
        if not check_panel_owner(call, owner_id):
            return
        await safe_callback_answer(call, "Функция переустановки временно недоступна.", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.in_({"server_unavailable", "server_test_unavailable", "server_noub", "server_full"}), UserBotSetup.ChoosingServer)
async def cq_server_unavailable(call: types.CallbackQuery):
    try:
        alerts = {
            "server_unavailable": "🔴 Этот сервер временно недоступен для выбора.",
            "server_test_unavailable": "🧪 Нельзя выбрать тестовый сервер!",
            "server_noub": "🟢 Установка новых юзерботов на этот сервер временно отключена.",
            "server_full": "❌ Сервера переполнен\n\nВыберите другой сервер."
        }
        await safe_callback_answer(call, alerts.get(call.data, "Это действие сейчас недоступно."), show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data == "server_is_service", UserBotSetup.ChoosingServer)
async def cq_service_server_selected(call: types.CallbackQuery):
    try:
        await safe_callback_answer(call, "ℹ️ Это сервисный сервер, на котором работает бот.\n\nУстановка юзерботов на него невозможна.", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("confirm_unstable:"), UserBotSetup.ChoosingServer)
async def cq_confirm_unstable_server(call: types.CallbackQuery, state: FSMContext):
    try:
        await safe_callback_answer(call, "Хорошо, продолжаю установку.", show_alert=True)
        server_ip = call.data.split(":")[1]
        await _proceed_to_type_selection(call, state, server_ip)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("ub_type:"), UserBotSetup.ChoosingUserBotType)
async def cq_process_ub_type_selection(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await safe_callback_answer(call, "", show_alert=True)
        # Показываем индикатор загрузки вместо всех кнопок
        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        _, ub_type, server_ip = call.data.split(":")
        await state.update_data(selected_ub_type=ub_type)
        
        user = call.from_user
        name_base = str(user.id)
        ub_username = f"ub{name_base}"

        await state.update_data(chosen_username_base=name_base, ub_username=ub_username)

        current_state = await state.get_state()
        if current_state != UserBotSetup.Reinstalling.state and await db.get_userbot_data(ub_username=ub_username):
            await safe_callback_answer(call, "❌ <b>Ошибка:</b> У вас уже есть юзербот с таким системным именем.\n\n"
                        "Это могло произойти, если была прервана предыдущая установка. "
                        "Обратитесь в поддержку для решения проблемы.", show_alert=True)
            await state.clear()
            return

        data = await state.get_data()
        message_id = data.get("message_id_to_edit", call.message.message_id)

        try:
            await safe_callback_answer(call, "", show_alert=True)
            await call.bot.edit_message_caption(
                chat_id=call.message.chat.id, message_id=message_id,
                caption="<b>[Шаг 3/3] Установка...</b>\n\n<blockquote>Этот процесс может занять до 30 секунд. Подождите.</blockquote>",
                reply_markup=kb.get_loading_keyboard()
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                pass
            else:
                raise

        await state.set_state(UserBotSetup.InstallingUserBot)
        asyncio.create_task(perform_installation_and_find_link(call.from_user.id, call.message.chat.id, message_id, state, bot, is_private=(call.message.chat.type == 'private')))
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data == "go_to_control_panel", IsSubscribed(), StateFilter("*"))
async def cq_go_to_control_panel(call: types.CallbackQuery, state: FSMContext):
    try:
        # Показываем пользователю только одну кнопку 'Загрузка...' на время загрузки панели
        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Начинаем обработку callback\n")
        
        if call.message.chat.type != "private":
            with open("/tmp/bot_debug.log", "a") as f:
                f.write(f"{datetime.now()}: Проверка чата - не приватный\n")
            if call.message.reply_to_message:
                owner_id = call.message.reply_to_message.from_user.id
                if call.from_user.id != owner_id:
                    await safe_callback_answer(call, "Только тот, кто вызвал /start, может использовать эти кнопки!", show_alert=True)
                    return
            else:
                await safe_callback_answer(call, "Только тот, кто вызвал /start, может использовать эти кнопки!", show_alert=True)
                return
        
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Отвечаем на callback\n")
        await safe_callback_answer(call, "", show_alert=True)
        
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Показываем загрузку\n")
        await safe_callback_answer(call, "", show_alert=True)

        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Получаем юзерботы для пользователя {call.from_user.id}\n")
        print(f"DEBUG: Получаем юзерботы для пользователя {call.from_user.id}")
        all_bots = await db.get_userbots_by_tg_id(call.from_user.id)
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Найдено юзерботов: {len(all_bots)}\n")
        print(f"DEBUG: Найдено юзерботов: {len(all_bots)}")
        
        if not all_bots:
            with open("/tmp/bot_debug.log", "a") as f:
                f.write(f"{datetime.now()}: Юзерботы не найдены\n")
            print(f"DEBUG: Юзерботы не найдены")
            await safe_callback_answer(call, "❌ Юзербот не найден. Возможно, он был удален.", show_alert=True)
            await _show_main_panel(call.bot, call.message.chat.id, call.from_user.id, call.from_user.full_name, state, call.message.message_id)
            return

        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Берем первый юзербот\n")
        print(f"DEBUG: Берем первый юзербот")
        the_only_bot = all_bots[0]
        ub_username = the_only_bot['ub_username']
        server_ip = the_only_bot['server_ip']
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Юзербот: {ub_username}, сервер: {server_ip}\n")
        print(f"DEBUG: Юзербот: {ub_username}, сервер: {server_ip}")
        service_name = f"hikka-{ub_username}.service"
        
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Проверяем статус контейнера\n")
        print(f"DEBUG: Проверяем статус контейнера")
        
        # Временно отключаем проверку статуса контейнера для ускорения загрузки
        container_exists = True  # Считаем что контейнер работает
        disk_space_ok = True  # Упрощенная проверка
        
        with open("/tmp/bot_debug.log", "a") as f:
            f.write(f"{datetime.now()}: Статус контейнера проверен\n")
        print(f"DEBUG: Статус контейнера проверен")

        # if not container_exists or not disk_space_ok:
        #     error_text = (
        #         f"<b>🎛 Панель управления</b>\n\n"
        #         f"<i>😢 На данный момент наблюдаются сбои в работе юзербота/сервера.</i>\n\n"
        #         f"<b>Повторите попытку через <code>10-15</code> минут</b>"
        #     )
        #     builder = InlineKeyboardBuilder()
        #     builder.button(text="🔄 Обновить", callback_data=f"health_check_retry:{ub_username}")
        #     builder.button(text="🔙 Назад", callback_data="back_to_main_panel")
        #     await call.message.edit_caption(caption=error_text, reply_markup=builder.as_markup())
        #     return
        
        if len(all_bots) == 1:
            with open("/tmp/bot_debug.log", "a") as f:
                f.write(f"{datetime.now()}: Показываем панель управления для единственного юзербота {ub_username}\n")
            print(f"DEBUG: Показываем панель управления для единственного юзербота {ub_username}")
            await show_management_panel(call, ub_username, state)
            return

        logging.info(f"Показываем список юзерботов для выбора")
        text = "<b>Выберите юзербота для управления:</b>"
        markup = kb.get_user_bots_list_keyboard(all_bots, call.from_user.id)
        await safe_callback_answer(call, text, show_alert=True)
        await call.message.edit_caption(caption=text, reply_markup=markup)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("select_ub_panel:"))
async def cq_select_ub_panel(call: types.CallbackQuery, state: FSMContext):
    try:
        ub_username = call.data.split(":")[1]
        await show_management_panel(call, ub_username, state)
        await safe_callback_answer(call, "", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("refresh_panel:"))
async def cq_refresh_panel(call: types.CallbackQuery, state: FSMContext):
    try:
        await call.answer()

        parts = call.data.split(":")
        ub_username = parts[1]
        
        owner_id_str = parts[2] if len(parts) >= 3 else str(call.from_user.id)
        owner_id = int(owner_id_str)

        if not check_panel_owner(call, owner_id):
            return

        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        await show_management_panel(call, ub_username, state)

    except (TelegramBadRequest, ValueError, IndexError) as e:
        if isinstance(e, TelegramBadRequest) and "message is not modified" in str(e).lower():
            return
        
        logging.error(f"Ошибка при обновлении панели управления: {e}")
        await call.answer("Упс... кажется, эти кнопки устарели. Вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("show_user_logs:"))
async def cq_show_user_logs(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, log_type, ub_username, owner_id_str, page = call.data.split(":")
        owner_id = int(owner_id_str)
        if not check_panel_owner(call, owner_id):
            return
        await safe_callback_answer(call, "", show_alert=True)
        try:
            page = int(page)
        except ValueError:
            await safe_callback_answer(call, "Ошибка данных.", show_alert=True)
            return
        ub_data = await db.get_userbot_data(ub_username)
        if not ub_data:
            await safe_callback_answer(call, "🚫 У вас нет доступа к этому юзерботу.", show_alert=True)
            return
        is_pagination = call.message.text is not None
        msg_to_edit = call.message
        if not is_pagination:
            await safe_callback_answer(call, "", show_alert=True)
            msg_to_edit = await call.bot.send_message(call.from_user.id, "⏳ Загружаю логи...", reply_markup=kb.get_loading_keyboard())
            # Удаляем исходное сообщение после отправки нового
            try:
                await call.message.delete()
            except Exception:
                pass
        else:
            await safe_callback_answer(call, "", show_alert=True)
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        # Используем API для получения логов контейнера
        if log_type == "docker":
            # Проверяем статус сервера
            server_status = server_config.get_server_status_by_ip(ub_data['server_ip'])
            if server_status in ["false", "not_found"]:
                logs = f"❌ Сервер {ub_data['server_ip']} недоступен"
            else:
                container_name = ub_username  # Имя контейнера = имя юзербота
                logs_result = await api_manager.get_container_logs(container_name, ub_data['server_ip'])
                
                if logs_result.get("success"):
                    logs_data = logs_result.get("data", {})
                    logs = logs_data.get("logs", "")
                else:
                    error_msg = logs_result.get('error', 'Неизвестная ошибка')
                    if "No such container" in error_msg or "404" in error_msg:
                        logs = f"❌ Контейнер {container_name} не найден на сервере"
                    else:
                        logs = f"❌ Ошибка получения логов: {error_msg}"
        else:
            logs = await sm.get_userbot_logs(ub_username, ub_data['server_ip'], log_type, 1000)

        if not logs or logs.startswith("❌") or logs.startswith("📜 Логи"):
            await safe_callback_answer(call, f"📜 {logs}", show_alert=True)
            await show_management_panel(call, ub_username, state)
            await call.bot.send_message(call.from_user.id, f"📜 {logs}")
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
            await safe_callback_answer(call, text, show_alert=True)
            await msg_to_edit.edit_text(text=text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                if "message to edit not found" in str(e).lower():
                    # Если сообщение не найдено, отправляем новое
                    await safe_callback_answer(call, text, show_alert=True)
                    await call.bot.send_message(call.from_user.id, text=text, reply_markup=markup)
                else:
                    logging.error(f"Error editing message with logs: {e}")
                    await safe_callback_answer(call, "Произошла ошибка при отображении логов.", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("show_container_stats:"))
async def cq_show_container_stats(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, ub_username, owner_id_str = call.data.split(":")
        owner_id = int(owner_id_str)
        if not check_panel_owner(call, owner_id):
            return
        await safe_callback_answer(call, "Загружаю статистику...", show_alert=True)
        
        ub_data = await db.get_userbot_data(ub_username)
        if not ub_data:
            await safe_callback_answer(call, "🚫 У вас нет доступа к этому юзерботу.", show_alert=True)
            return

        server_ip = ub_data.get('server_ip')
        if not server_ip:
            await safe_callback_answer(call, "❌ Сервер не найден", show_alert=True)
            return

        await safe_callback_answer(call, "", show_alert=True)
        
        try:
            # Получаем статистику контейнера через API
            stats_result = await api_manager.get_container_stats(ub_username, server_ip)
            
            if not stats_result.get("success"):
                error_msg = stats_result.get("error", "Неизвестная ошибка")
                await safe_callback_answer(call, f"❌ <b>Ошибка при получении статистики:</b>\n\n<pre>{html.quote(error_msg)}</pre>", show_alert=True)
                return
            
            stats_data = stats_result.get("data", {})
            formatted_stats = format_container_stats(stats_data)
            
            # Добавляем кнопку обновления
            builder = InlineKeyboardBuilder()
            builder.button(text="🔄 Обновить", callback_data=f"show_container_stats:{ub_username}:{owner_id_str}")
            builder.button(text="🔙 Назад", callback_data=f"refresh_panel:{ub_username}:{owner_id_str}")
            builder.adjust(2)
            
            await safe_callback_answer(call, formatted_stats, show_alert=True)
            await call.message.edit_caption(
                caption=formatted_stats,
                reply_markup=builder.as_markup()
            )
            
        except Exception as e:
            logging.error(f"Ошибка при получении статистики: {e}")
            await safe_callback_answer(call, f"❌ <b>Ошибка при получении статистики:</b>\n\n<pre>{html.quote(str(e))}</pre>", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("manage_ub:"))
async def cq_manage_container(call: types.CallbackQuery, state: FSMContext):
    try:
        parts = call.data.split(":")
        action = parts[1]
        ub_username = parts[2]
        owner_id_str = parts[3]
        owner_id = int(owner_id_str)

        if not check_panel_owner(call, owner_id):
            return

        ub_data = None
        server_ip = None
        if action not in ["recreate"]:
            ub_data = await db.get_userbot_data(ub_username)
            if not ub_data:
                await safe_callback_answer(call, "❌ Юзербот не найден", show_alert=True)
                return

            server_ip = ub_data.get('server_ip')
            if not server_ip:
                await safe_callback_answer(call, "❌ Сервер не найден", show_alert=True)
                return

        if action == "start":
            await safe_callback_answer(call, "", show_alert=True)
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
            result = await api_manager.start_container(ub_username, server_ip)
            action_text = "запуск"

        elif action == "stop":
            await safe_callback_answer(call, "", show_alert=True)
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
            result = await api_manager.stop_container(ub_username, server_ip)
            action_text = "остановка"

        elif action == "restart":
            await safe_callback_answer(call, "", show_alert=True)
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
            result = await api_manager.restart_container(ub_username, server_ip)
            action_text = "перезапуск"

        elif action == "recreate":
            await call.message.edit_caption(
                caption="🔄 <b>Переустановка юзербота</b>\n\nВыберите юзербота для переустановки:",
                reply_markup=kb.get_reinstall_userbot(ub_username, owner_id_str)
            )
            return

        elif action == "reinstall":
            _, _, ub_username, owner_id_str, userbot = parts

            await safe_callback_answer(call, "", show_alert=True)
            ub_data = await db.get_userbot_data(ub_username)
            server_ip = ub_data.get('server_ip')
            await call.message.edit_caption(caption="🔄 <b>Переустановка юзербота</b>\n\nИдёт переустановка вашего юзербота")
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
            result = await api_manager.reinstall_ub(ub_username, userbot, server_ip)
            update_info = await db.update_type(ub_username, userbot)
            action_text = f"переустановка ({userbot})"

        elif action == "vpn":
            tg_id = call.from_user.id
            vpn_data = await db.get_vpn(tg_id)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            if not vpn_data:
                name = f"ub{tg_id}"
                vpn_result = await api_manager.create_vpn(name)
                if vpn_result.get("success"):
                    vless_link = None
                    for link in vpn_result.get("data", {}).get("links", []):
                        if link.startswith("vless://"):
                            vless_link = link
                            break
                    if vless_link:
                        await db.add_vpn(tg_id, vless_link)
                        vpn_data = vless_link
                    else:
                        await safe_callback_answer(call, "❌ Не удалось получить VPN ссылку", show_alert=True)
                        return
                else:
                    error_msg = vpn_result.get("error", "Неизвестная ошибка")
                    await safe_callback_answer(call, f"❌ Ошибка создания VPN: {error_msg}", show_alert=True)
                    return

            vpn_text = (
                "<b>🔐 Ваш VPN доступ</b>\n\n"
                "<blockquote>"
                "<b>Ссылка для подключения:</b>\n"
                f"<code>{vpn_data}</code>\n\n"
                "<b>Как подключиться:</b>\n"
                "1. Скачайте подходящий клиент для вашего устройства:\n"
                "\n"
                "<b>iOS/Mac:</b>\n"
                "- <a href='https://apps.apple.com/ru/app/v2raytun/id6476628951'>V2RayTun (App Store)</a>\n"
                "\n"
                "<b>Android:</b>\n"
                "- <a href='https://play.google.com/store/apps/details?id=com.v2raytun.android&hl=ru'>V2RayTun (Google Play)</a>\n"
                "- <a href='https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/download/1.3.9/NekoBox-1.3.9-arm64-v8a.apk'>NekoBox (arm64)</a>\n"
                "- <a href='https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/download/1.3.9/NekoBox-1.3.9-x86_64.apk'>NekoBox (x86_64)</a>\n"
                "\n"
                "<b>Windows:</b>\n"
                "- <a href='https://github.com/MatsuriDayo/nekoray/releases/download/4.0.1/nekoray-4.0.1-2024-12-12-windows64.zip'>Nekoray (Windows)</a>\n"
                "\n"
                "<b>Linux:</b>\n"
                "- <a href='https://github.com/MatsuriDayo/nekoray/releases/download/4.0.1/nekoray-4.0.1-2024-12-12-linux-x64.AppImage'>Nekoray (Linux x64)</a>\n"
                "\n"
                "2. Откройте приложение и выберите импорт по ссылке\n"
                "3. Вставьте ссылку выше и подключитесь\n"
                "\n"
                "<b>ℹ️ Если не удаётся подключиться:</b>\n"
                "- Попробуйте другой клиент (например, Hiddify)\n"
                "- Проверьте интернет\n"
                "- Обратитесь в поддержку @TeaHostSupport"
                "</blockquote>"
            )
            buttons = [
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_control_panel")]
            ]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await call.message.edit_caption(
                caption=vpn_text,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        elif action == "auth":
            tg_id = call.from_user.id
            auth_data = await db.get_password(tg_id)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            if not auth_data:
                auth_message = "❌ Нет данных для авторизации."
                markup = kb.back_to_panel()
            else:
                password = auth_data.get('password', 'Не указан')
                auth_message = (
                    "<b>🔑 Ваш пароль для входа</b>\n\n"
                    f"<b>Пароль:</b> <tg-spoiler>{password}</tg-spoiler>\n\n"
                    "<i>Скопируйте пароль кнопкой ниже и вставьте его в форму входа на панели управления.</i>\n\n"
                    "<b>❗️ Не делитесь этим паролем с другими!</b>"
                )
                buttons = [
                    [InlineKeyboardButton(text="🔑 Скопировать пароль", copy_text=CopyTextButton(text=password))],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="go_to_control_panel")]
                ]
                markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await call.message.edit_caption(
                caption=auth_message,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return

        else:
            await safe_callback_answer(call, "❌ Неизвестное действие", show_alert=True)
            return

        if result.get("success"):
            try:
                await show_management_panel(call, ub_username, state)
            except Exception as e:
                logging.error(f"Ошибка при обновлении панели: {e}")
                await safe_callback_answer(call, f"✅ {action_text.capitalize()} выполнена успешно", show_alert=True)
        else:
            error_msg = result.get("error", "неизвестная ошибка").lower()
            server_details = server_config.get_servers().get(server_ip, {})
            server_code = server_details.get("code", "N/A")
            
            log_data = {
                "user_data": {"id": call.from_user.id, "full_name": call.from_user.full_name},
                "ub_info": {"name": ub_username},
                "server_info": {"ip": server_ip, "code": server_code},
                "error": f"Действие '{action}': {result.get('error', 'N/A')}"
            }
            asyncio.create_task(log_event(call.bot, "api_container_error", log_data))

            if "invalid token" in error_msg or "403" in error_msg:
                text = f"На сервере {server_code} установлен неверный API токен. Обратитесь к администратору @aloya_uwu или @nloveuser."
                await call.message.edit_caption(caption=text, reply_markup=kb.get_back_to_main_panel_keyboard())
                return
            elif "connection refused" in error_msg or "cannot connect" in error_msg:
                text = "Сервер не отвечает, обратитесь к администратору @aloya_uwu, @nloveuser или @EXPERT_CATPON."
                await call.message.edit_caption(caption=text, reply_markup=kb.get_back_to_main_panel_keyboard())
                return
            elif "internal server error" in error_msg or "not found" in error_msg or "resource temporarily unavailable" in error_msg:
                text = "Брат, у тебя пиздец случился, обратись к @aloya_uwu или @nloveuser."
                await call.message.edit_caption(caption=text, reply_markup=kb.get_back_to_main_panel_keyboard())
                return
            
            try:
                await safe_callback_answer(call, f"❌ Ошибка {action_text}: {result.get('error')}", show_alert=True)
            except Exception:
                pass
            try:
                await show_management_panel(call, ub_username, state)
            except Exception as e:
                logging.error(f"Ошибка при обновлении панели после ошибки: {e}")

    except Exception as e:
        logging.error(f"Ошибка при управлении контейнером: {e}")
        try:
            await safe_callback_answer(call, "❌ Произошла ошибка при выполнении действия", show_alert=True)
        except aiogram.exceptions.TelegramBadRequest as tg_error:
            if "query is too old" in str(tg_error).lower() or "response timeout expired" in str(tg_error).lower():
                logging.warning(f"Callback query устарел для пользователя {call.from_user.id}: {tg_error}")
            else:
                logging.error(f"TelegramBadRequest при ответе на callback: {tg_error}")
        except Exception as answer_error:
            logging.error(f"Не удалось ответить на callback query: {answer_error}")

        try:
            await show_management_panel(call, ub_username, state)
        except Exception as panel_error:
            logging.error(f"Ошибка при обновлении панели после исключения: {panel_error}")

@router.callback_query(F.data.startswith("inline_btn_manage:"))
async def cq_inline_manage_container(call: types.CallbackQuery, state: FSMContext):
    """Обработчик для inline управления контейнером"""
    try:
        # Парсим данные из callback
        _, action, ub_username, owner_id_str, inline_message_id = call.data.split(":")
        owner_id = int(owner_id_str)
        
        # Проверяем права доступа
        if not check_panel_owner(call, owner_id):
            return
        
        # Получаем данные юзербота
        ub_data = await db.get_userbot_data(ub_username)
        if not ub_data:
            await safe_callback_answer(call, "❌ Юзербот не найден", show_alert=True)
            return
        
        server_ip = ub_data.get('server_ip')
        if not server_ip:
            await safe_callback_answer(call, "❌ Сервер не найден", show_alert=True)
            return
        
        # Сразу заменяем клавиатуру на "Загрузка..."
        try:
            await safe_callback_answer(call, "", show_alert=True)
            await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        except Exception as e:
            # Если не удалось отредактировать сообщение, просто отвечаем на callback
            await safe_callback_answer(call, "⏳ Выполняю команду...", show_alert=True)
        
        # Выполняем действие в зависимости от типа
        if action == "start":
            result = await api_manager.start_container(ub_username, server_ip)
            action_text = "запуск"
        elif action == "stop":
            result = await api_manager.stop_container(ub_username, server_ip)
            action_text = "остановка"
        elif action == "restart":
            result = await api_manager.restart_container(ub_username, server_ip)
            action_text = "перезапуск"
        else:
            await safe_callback_answer(call, "❌ Неизвестное действие", show_alert=True)
            return
        
        if result.get("success"):
            # Обновляем inline сообщение
            try:
                await show_management_panel(call, ub_username, state)
            except Exception as e:
                logging.error(f"Ошибка при обновлении inline панели: {e}")
                await safe_callback_answer(call, "✅ Действие выполнено успешно", show_alert=True)
        else:
            error_msg = result.get("error", "Неизвестная ошибка")
            try:
                await safe_callback_answer(call, f"❌ Ошибка {action_text}: {error_msg}", show_alert=True)
            except Exception:
                # Если callback query устарел, логируем ошибку
                pass
            # В случае ошибки тоже обновляем панель, чтобы показать актуальное состояние
            try:
                await show_management_panel(call, ub_username, state)
            except Exception as e:
                logging.error(f"Ошибка при обновлении inline панели после ошибки: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка при inline управлении контейнером: {e}")
        try:
            await safe_callback_answer(call, "❌ Произошла ошибка при выполнении действия", show_alert=True)
        except aiogram.exceptions.TelegramBadRequest as tg_error:
            # Если callback query устарел, логируем ошибку
            if "query is too old" in str(tg_error).lower() or "response timeout expired" in str(tg_error).lower():
                logging.warning(f"Callback query устарел для пользователя {call.from_user.id}: {tg_error}")
            else:
                logging.error(f"TelegramBadRequest при ответе на callback: {tg_error}")
        except Exception as answer_error:
            # Если callback query устарел, логируем ошибку
            logging.error(f"Не удалось ответить на callback query: {answer_error}")
        # В случае исключения тоже обновляем панель
        try:
            await show_management_panel(call, ub_username, state)
        except Exception as panel_error:
            logging.error(f"Ошибка при обновлении inline панели после исключения: {panel_error}")

@router.callback_query(F.data.startswith("noop"))
async def noop_handler(call: types.CallbackQuery):
    await call.answer()

@router.callback_query(F.data.startswith("delete_ub_confirm_request:"))
async def cq_delete_ub_confirm_request(call: types.CallbackQuery, state: FSMContext):
    try:
        parts = call.data.split(":")
        if len(parts) < 3:
            await safe_callback_answer(call, "Кнопка устарела, обновите панель.", show_alert=True)
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
            if call.message.text:
                await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            elif call.message.caption:
                await call.message.edit_caption(caption=text, reply_markup=markup, parse_mode="HTML")
            else:
                await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as e:
            err_str = str(e).lower()
            if "message is not modified" in err_str:
                pass
            else:
                await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
        await state.set_state(UserBotSetup.ConfirmDeleteUserBot)
    except Exception as e:
        logging.error(f"Неожиданная ошибка в cq_delete_ub_confirm_request: {e}")
        await safe_callback_answer(call, "Произошла ошибка, попробуйте снова через /start", show_alert=True)

@router.callback_query(F.data.startswith("delete_ub_cancel:"), UserBotSetup.ConfirmDeleteUserBot)
async def cq_delete_ub_cancel(call: types.CallbackQuery, state: FSMContext):
    try:
        await call.answer(
            "Удаление отменено, будьте осторожны при удалении как бы сносит весь контейнер/юзербот!",
            show_alert=True
        )

        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())

        ub_username = call.data.split(":")[1]

        await asyncio.sleep(0.5)

        await show_management_panel(call, ub_username, state)

    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Ошибка в cq_delete_ub_cancel: {e}")
            await call.answer("Упс... кажется, эти кнопки устарели. Вызовите новые через /start", show_alert=True)
    except Exception as e:
        logging.error(f"Неожиданная ошибка в cq_delete_ub_cancel: {e}")
        await call.answer("Произошла ошибка, попробуйте снова.", show_alert=True)
        
@router.callback_query(F.data.startswith("delete_ub_execute:"), UserBotSetup.ConfirmDeleteUserBot)
async def cq_delete_ub_execute(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        # Показываем индикатор загрузки вместо всех кнопок
        await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
        await safe_callback_answer(call, "", show_alert=True)

        await safe_callback_answer(call, "🗑️ <b>Удаление юзербота...</b>\n\n<blockquote>Этот процесс может занять до минуты.</blockquote>", show_alert=True)

        ub_username = call.data.split(":")[1]
        
        ub_data = await db.get_userbot_data(ub_username)
        if not ub_data:
            await safe_callback_answer(call, "❌ <b>Ошибка:</b> Юзербот не найден или у вас больше нет к нему доступа.", show_alert=True)
            return

        await db.update_userbot_status(ub_username, "deleting")
        
        # Удаляем контейнер через API
        tg_id = call.from_user.id
        delete_result = await api_manager.delete_container(ub_username, ub_data['server_ip'])
        await db.delete_password(tg_id)
        await db.delete_vpn(tg_id)
        await api_manager.delete_vpn(f"ub{tg_id}")
        
        if delete_result.get("success"):
            # Удаляем запись из базы данных
            await db.delete_userbot_record(ub_username)
            
            user_data = {"id": call.from_user.id, "full_name": call.from_user.full_name}
            server_details = server_config.get_servers().get(ub_data['server_ip'], {})
            log_data = {
                "user_data": user_data,
                "ub_info": {"name": ub_username},
                "server_info": {"ip": ub_data['server_ip'], "code": server_details.get("code", "N/A")}
            }
            await log_event(call.bot, "deletion_by_owner", log_data)
            
            await _show_main_panel(bot=bot, chat_id=call.message.chat.id, user_id=call.from_user.id,
                user_name=call.from_user.full_name, state=state, message_id=call.message.message_id
            )
        else:
            error_message = delete_result.get('error', 'Произошла неизвестная ошибка.')
            await safe_callback_answer(call, f"❌ <b>Ошибка при удалении:</b>\n\n<pre>{html.quote(error_message)}</pre>", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    try:
        user_id = call.from_user.id
        try:
            member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
            if member.status not in ["left", "kicked"]:
                await safe_callback_answer(call, "✅ Спасибо за подписку!", show_alert=True)
                await call.message.delete()
                await safe_callback_answer(call, "Запустите бота снова /start", show_alert=True)
            else:
                await safe_callback_answer(call, "🚫 Вы еще не подписаны. Подпишитесь и попробуйте снова.", show_alert=True)
        except Exception as e:
            await safe_callback_answer(call, "Произошла ошибка при проверке. Попробуйте снова.", show_alert=True)
            logging.error(f"Ошибка проверки подписки по кнопке: {e}")
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("share_panel_start:"))
async def cq_share_panel_start(call: types.CallbackQuery, state: FSMContext):
    """Временный обработчик для кнопки 'Поделиться панелью'"""
    await safe_callback_answer(call, "⚠️ Функция 'Поделиться панелью' временно недоступна.\n\nМы работаем над её реализацией. Следите за обновлениями!", show_alert=True)

@router.message(StateFilter(UserBotShare.WaitingForShareUserID))
async def msg_process_share_user_id(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    message_id_to_edit = data.get("message_id_to_edit")
    await message.delete()
    if not message.text or not message.text.isdigit():
        await safe_callback_answer(message, "❌ ID пользователя должен быть числом. Попробуйте снова.",
            chat_id=message.chat.id, message_id=message_id_to_edit,
            reply_markup=kb.get_cancel_revoke_shared_keyboard(ub_username)
        )
        return
    share_user_id = int(message.text)
    if share_user_id == message.from_user.id:
        await safe_callback_answer(message, "❌ Вы не можете поделиться панелью с самим собой.",
            chat_id=message.chat.id, message_id=message_id_to_edit)
        await show_management_panel(message, ub_username, state)
        return
    if await db.has_userbot_shared_access(ub_username, share_user_id):
        await safe_callback_answer(message, "❗️ У пользователя уже есть доступ к этой панели.",
            chat_id=message.chat.id, message_id=message_id_to_edit)
        await show_management_panel(message, ub_username, state)
        return
    await state.update_data(share_user_id=share_user_id)
    await state.set_state(UserBotShare.ConfirmingShare)
    user = await bot.get_chat(share_user_id)
    user_display = f"@{user.username}" if user.username else user.full_name
    text = f"Вы точно хотите выдать доступ к панели <code>{html.quote(ub_username)}</code> пользователю {html.quote(user_display)} (<code>{share_user_id}</code>)?"
    markup = kb.get_confirm_share_panel_keyboard(ub_username, share_user_id)
    await safe_callback_answer(message, text, chat_id=message.chat.id, message_id=message_id_to_edit, reply_markup=markup)
    

@router.callback_query(F.data.startswith("confirm_share_panel:"), UserBotShare.ConfirmingShare)
async def cq_confirm_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, ub_username, share_user_id_str = call.data.split(":")
        share_user_id = int(share_user_id_str)
        owner = call.from_user
        text = (f"Пользователь {html.quote(owner.full_name)} (<code>{owner.id}</code>) хочет поделиться с вами панелью управления юзерботом <code>{html.quote(ub_username)}</code>.\n\n"
                "Вы хотите принять доступ? Вы сможете отказаться в любой момент.")
        markup = kb.get_accept_share_panel_keyboard(ub_username, owner.id)
        
        try:
            await safe_callback_answer(call, "", show_alert=True)
            await call.bot.send_message(chat_id=share_user_id, text=text, reply_markup=markup)
            await safe_callback_answer(call, "⏳ Ожидание подтверждения вторым пользователем...", reply_markup=kb.get_back_to_main_panel_keyboard())
        except TelegramForbiddenError:
            await safe_callback_answer(call, "❌ Не удалось отправить приглашение. Пользователь должен сначала начать диалог с ботом.", show_alert=True)
            await safe_callback_answer(call, "❌ Ошибка: пользователь не начал диалог с ботом", reply_markup=kb.get_back_to_main_panel_keyboard())
        except Exception as e:
            logging.error(f"Ошибка при отправке приглашения пользователю {share_user_id}: {e}")
            await safe_callback_answer(call, "❌ Произошла ошибка при отправке приглашения", show_alert=True)
            await safe_callback_answer(call, "❌ Ошибка при отправке приглашения", reply_markup=kb.get_back_to_main_panel_keyboard())
        
        await state.clear()
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("accept_share_panel:"), F.chat.type == "private")
async def cq_accept_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
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

        await safe_callback_answer(call, "✅ Доступ выдан! Теперь вы можете управлять этим юзерботом.", show_alert=True)
        await show_management_panel(call, ub_username, state)
        
        try:
            await safe_callback_answer(call, "", show_alert=True)
            await call.bot.send_message(chat_id=int(owner_id_str), text=f"Пользователь <code>{call.from_user.id}</code> принял доступ к панели <code>{html.quote(ub_username)}</code>.")
        except TelegramForbiddenError:
            logging.warning(f"Не удалось уведомить владельца {owner_id_str} о принятии доступа: пользователь не начал диалог с ботом")
        except Exception as e:
            logging.error(f"Ошибка при уведомлении владельца {owner_id_str}: {e}")
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("accept_share_panel:"))
async def cq_accept_share_panel_fallback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        chat = getattr(call.message, "chat", None)
        if chat and chat.type == "private":
            await cq_accept_share_panel(call, state, bot)
        else:
            await safe_callback_answer(call,
                "⚠️ Функция 'Поделиться панелью' работает только в личных сообщениях с ботом.",
                show_alert=True
            )
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("decline_share_panel:"), F.chat.type == "private")
async def cq_decline_share_panel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        await safe_callback_answer(call, "Вы отклонили приглашение.", show_alert=True)
        await safe_callback_answer(call, "❌ Вы отклонили приглашение к совместному управлению этим юзерботом.", show_alert=True)
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.callback_query(F.data.startswith("decline_share_panel:"), F.chat.type != "private")
async def cq_decline_share_panel_in_chat(call: types.CallbackQuery):
    try:
        await safe_callback_answer(call,
            "⚠️ Функция 'Поделиться панелью' работает только в личных сообщениях с ботом.",
            show_alert=True
        )
    except TelegramBadRequest:
        await safe_callback_answer(call, "Упс... кажется кнопки устарели, вызовите новые через /start", show_alert=True)

@router.message(Command("ping"))
async def cmd_ping(message: types.Message):
    user_id = message.from_user.id
    current_time = time.time()

    if user_id in PING_TIMESTAMPS:
        if current_time - PING_TIMESTAMPS[user_id] < PING_COOLDOWN_SECONDS:
            return

    PING_TIMESTAMPS[user_id] = current_time
    
    start_time = time.perf_counter()
    msg = await message.reply("...")
    end_time = time.perf_counter()
    delay = (end_time - start_time) * 1000
    await msg.edit_text(f"🏓 <b>Понг!</b>\nЗадержка: <code>{delay:.2f} мс</code>")
    
@router.message(Command("review"), F.chat.type == "private")
async def cmd_review(message: types.Message, state: FSMContext):
    text = (
        "✍️ <b>Напишите отзыв о TeaHost</b>\n\n"
        "ℹ️ В отзыве можете рассказать о том, сколько пользуетесь TeaHost, какие отличия заметили от предыдущего хостинга и т.д.\n\n"
        "📅 В ближайшее время отзыв будет опубликован на @TeaHostReviews."
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
    await call.answer("200 OK.", show_alert=True)
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            logging.error(f"ошибочка, вот лог: {e}")

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
            
    await safe_callback_answer(message, "✅ Отправлен на модерацию.", show_alert=True)
    
    if original_bot_message_id:
        try:
            await safe_callback_answer(message, "", show_alert=True)
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
    await safe_callback_answer(call, "", show_alert=True)
    commit_id = call.data.split(":")[1]
    await _display_commit_details(call, commit_id)

@router.callback_query(F.data.startswith("vote_commit:"))
async def cq_vote_commit(call: types.CallbackQuery):
    _, commit_id, vote_type_str = call.data.split(":")
    vote_type = int(vote_type_str)
    
    await db.set_vote(commit_id, call.from_user.id, vote_type)
    
    alert_text = "Ваш 👍 поставлен на коммит!" if vote_type == 1 else "Ваш 👎 поставлен на коммит!"
    await safe_callback_answer(call, alert_text, show_alert=False)
    
    await _display_commit_details(call, commit_id)

@router.callback_query(F.data == "back_to_commits")
async def cq_back_to_commits(call: types.CallbackQuery):
    await safe_callback_answer(call, "", show_alert=True)
    text, markup = await _get_commits_list_message()
    await safe_callback_answer(call, text, show_alert=True)
    await call.message.edit_text(text, reply_markup=markup)

@router.callback_query(F.data == "hide_commits")
async def cq_hide_commits(call: types.CallbackQuery):
    await safe_callback_answer(call, "", show_alert=True)
    await safe_callback_answer(call, "", show_alert=True)
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
        await safe_callback_answer(call, "❌ Этот коммит не найден. Возможно, он был удален.", show_alert=True)
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
        await safe_callback_answer(call, text, show_alert=True)
        await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Ошибка обновления деталей коммита: {e}")
         
@router.inline_query(F.query.startswith("exec"))
async def inline_exec_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    user_bots = await db.get_userbots_by_tg_id(user_id)

    if not user_bots:
        result = InlineQueryResultArticle(
            id=f"exec_no_bot_{user_id}", 
            title="Нет юзербота", 
            description="У вас нет юзербота для выполнения команд.", 
            input_message_content=InputTextMessageContent(message_text="❌ <b>У вас нет юзербота.</b>", parse_mode="HTML")
        )
        await inline_query.answer([result], cache_time=5, is_personal=True)
        return

    the_only_bot = user_bots[0]
    ub_username = the_only_bot['ub_username']
    ub_data = await db.get_userbot_data(ub_username)

    if not ub_data or ub_data.get('status') in ['installing', 'deleting']:
        status_text = "Установка в процессе..." if ub_data.get('status') == 'installing' else "Удаление в процессе..."
        result = InlineQueryResultArticle(
            id=f"exec_status_fail_{user_id}", 
            title="Действие недоступно", 
            description=status_text,
            input_message_content=InputTextMessageContent(message_text=f"⏳ <b>Действие временно недоступно.</b>\n\n{status_text}", parse_mode="HTML")
        )
        await inline_query.answer([result], cache_time=5, is_personal=True)
        return

    command_str = inline_query.query[len("exec"):].strip()

    if not command_str:
        result = InlineQueryResultArticle(
            id=f"exec_help_{user_id}", 
            title="Введите команду", 
            description="Напишите команду.", 
            input_message_content=InputTextMessageContent(message_text="ℹ️ Введите команду после `exec ` для выполнения команды..")
        )
        await inline_query.answer([result], cache_time=5, is_personal=True)
        return
        
    server_ip = the_only_bot['server_ip']
    
    exec_result = await api_manager.exec_in_container(ub_username, command_str, server_ip)

    if not exec_result.get("success"):
        error_text = exec_result.get('error', 'Неизвестная ошибка API')
        response_text = f"❌ <b>Ошибка выполнения:</b>\n<pre>{html.quote(error_text)}</pre>"
    else:
        data = exec_result.get("data", {}).get("exec", {})
        exit_code = data.get("exit_code", "N/A")
        output = data.get("output", "").strip()

        header = (
            f"<b>Команда:</b> <pre>{html.quote(command_str)}</pre>\n"
            f"<b>Код выхода:</b> <code>{exit_code}</code>\n\n"
        )
        
        if output:
            if len(output) > 3800:
                output = output[:3800] + "\n\n[...Вывод обрезан...]"
            response_text = header + f"<b>Вывод:</b>\n<blockquote>{html.quote(output)}</blockquote>"
        else:
            response_text = header + "<i>(Нет вывода)</i>"
        
    result = InlineQueryResultArticle(
        id=f"exec_result_{user_id}_{command_str}", 
        title=f"Выполнить: {command_str[:50]}", 
        description="Показать результат выполнения команды", 
        input_message_content=InputTextMessageContent(message_text=response_text, parse_mode="HTML")
    )

    try:
        await inline_query.answer([result], cache_time=1, is_personal=True)
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            return
        else:
            logging.error(f"Ошибка ответа на inline_query exec: {e}")
            raise

@router.callback_query(F.data.startswith("revoke_shared_access:"))
async def cq_revoke_shared_access(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await state.set_state(UserBotShare.ConfirmingRevoke)
    await state.update_data(ub_username=ub_username)
    text = f"Вы уверены, что хотите отказаться от управления юзерботом <code>{html.quote(ub_username)}</code>?"
    markup = kb.get_confirm_revoke_shared_keyboard(ub_username)
    await safe_callback_answer(call, text, show_alert=True)
    await safe_callback_answer(call, "", show_alert=True)

@router.callback_query(F.data.startswith("confirm_revoke_shared:"), UserBotShare.ConfirmingRevoke)
async def cq_confirm_revoke_shared(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    ub_username = call.data.split(":")[1]
    await db.remove_userbot_shared_access(ub_username, call.from_user.id)
    await state.clear()
    await safe_callback_answer(call, f"✅ Вы больше не управляете юзерботом <code>{html.quote(ub_username)}</code>.", show_alert=True)
    await safe_callback_answer(call, "", show_alert=True)

@router.callback_query(F.data.startswith("cancel_revoke_shared:"), UserBotShare.ConfirmingRevoke)
async def cq_cancel_revoke_shared(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await state.clear()
    await show_management_panel(call, ub_username, state)
    await safe_callback_answer(call, "", show_alert=True)

@router.callback_query(F.data.startswith("owner_revoke_shared:"))
async def cq_owner_revoke_shared(call: types.CallbackQuery, state: FSMContext):
    _, ub_username, shared_id = call.data.split(":")
    shared_id = int(shared_id)
    await db.remove_userbot_shared_access(ub_username, shared_id)
    await safe_callback_answer(call, "Доступ отозван.", show_alert=True)
    await show_management_panel(call, ub_username, state)

def check_panel_owner(call, owner_id: int) -> bool:
    if call.from_user.id != owner_id:
        import asyncio
        coro = safe_callback_answer(call, "Это не ваша панель!", show_alert=True)
        if asyncio.iscoroutine(coro):
            asyncio.create_task(coro)
        return False
    return True

@router.callback_query(F.data.startswith("shared_reject_access:"))
async def cq_shared_reject_access(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    ub_username = call.data.split(":")[1]
    await db.remove_userbot_shared_access(ub_username, call.from_user.id)
    await safe_callback_answer(call, "Вы отказались от доступа к панели.", show_alert=True)
    ub_data = await db.get_userbot_data(ub_username)
    owner_id = ub_data.get('tg_user_id') if ub_data else None
    if owner_id and owner_id != call.from_user.id:
        user = call.from_user
        user_display = f"@{user.username}" if user.username else user.full_name
        try:
            await safe_callback_answer(call, f"ℹ️ Пользователь {user_display} (<code>{user.id}</code>) отказался от доступа к вашей панели <code>{html.quote(ub_username)}</code>.", show_alert=True)
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
    await safe_callback_answer(call, "", show_alert=True)

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

    await safe_callback_answer(call, "✅ Доступ выдан! Теперь вы можете управлять этим юзерботом.", show_alert=True)
    await show_management_panel(call, ub_username, state)
    
    try:
        await safe_callback_answer(call, "", show_alert=True)
        await call.bot.send_message(chat_id=int(owner_id_str), text=f"Пользователь <code>{call.from_user.id}</code> принял доступ к панели <code>{html.quote(ub_username)}</code>.")
    except TelegramForbiddenError:
        logging.warning(f"Не удалось уведомить владельца {owner_id_str} о принятии доступа: пользователь не начал диалог с ботом")
    except Exception as e:
        logging.error(f"Ошибка при уведомлении владельца {owner_id_str}: {e}")

@router.callback_query(F.data.startswith("manage_shared_access:"))
async def cq_manage_shared_access(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    shared_users = await db.get_userbot_shared_users(ub_username)
    if not shared_users:
        await safe_callback_answer(call, "Нет пользователей с доступом.", show_alert=True)
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
    await safe_callback_answer(call, text, show_alert=True)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await safe_callback_answer(call, "", show_alert=True)

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

    await safe_callback_answer(call, "Доступ отозван.", show_alert=True)
    await cq_manage_shared_access(call, state)

@router.callback_query(F.data.startswith("back_to_panel:"))
async def cq_back_to_panel_from_shared(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    await safe_callback_answer(call, "", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    await show_management_panel(call, ub_username, state)
    await safe_callback_answer(call, "", show_alert=True)

@router.callback_query(F.data.startswith("reinstall_ub_start_request:"))
async def cq_reinstall_ub_start_request_fallback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    parts = call.data.split(":")
    if len(parts) < 3:
        await safe_callback_answer(call, "Кнопка устарела, обновите панель.", show_alert=True)
        return
    _, ub_username, owner_id_str = parts
    owner_id = int(owner_id_str)
    if not check_panel_owner(call, owner_id):
        return
    await safe_callback_answer(call, "Функция переустановки временно недоступна.", show_alert=True)

# async def get_userbot_rom_usage(ub_username: str, server_ip: str) -> dict:
#     home_dir = f"/home/{ub_username}"
#     cmd = f"df -m {home_dir} | awk 'NR==2{{print $3, $2}}'"
#     res = await sm.run_command_async(cmd, server_ip)
#     if res.get('success') and res.get('output'):
#         try:
#             used, total = map(int, res['output'].strip().split())
#             percent = int(used / total * 100) if total else 0
#             return {'used': used, 'total': total, 'percent': percent}
#         except Exception:
#             pass
#     return {'used': 0, 'total': 0, 'percent': 0}
    
@router.callback_query(F.data.startswith("health_check_retry:"))
async def cq_health_check_retry(call: types.CallbackQuery, state: FSMContext):
    await safe_callback_answer(call, "Проверяю снова...", show_alert=True)
    await safe_callback_answer(call, "", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())

    ub_username = call.data.split(":")[1]
    ub_data = await db.get_userbot_data(ub_username)
    
    if not ub_data:
        await safe_callback_answer(call, "❌ Юзербот не найден.", show_alert=True)
        await _show_main_panel(call.bot, call.message.chat.id, call.from_user.id, call.from_user.full_name, state, call.message.message_id)
        return

    server_ip = ub_data['server_ip']
    
    # Проверяем статус контейнера через API
    container_status = await api_manager.get_container_status(ub_username, server_ip)
    container_exists = container_status.get("success", False)
    disk_space_ok = True  # Упрощенная проверка

    if not container_exists or not disk_space_ok:
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
                await call.bot.send_message(
                    admin_id,
                    f"⚠️ <b>Сбой юзербота/сервера</b>\n\n"
                    f"chat_id: <code>{call.message.chat.id}</code>\n"
                    f"container_exists: <code>{container_exists}</code>\n"
                    f"disk_space_ok: <code>{disk_space_ok}</code>\n"
                    f"Панель управления уведомила пользователя об ошибке."
                )
        except Exception as e:
            import logging
            logging.error(f"Не удалось отправить уведомление админам: {e}")
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data=f"health_check_retry:{ub_username}")
        builder.button(text="🔙 Назад", callback_data="back_to_main_panel")
        await safe_callback_answer(call, error_text, show_alert=True)
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
    await safe_callback_answer(call,
        "<b>Выберите тип Бекапа:</b>",
        reply_markup=builder.as_markup()
    )
    await safe_callback_answer(call, "", show_alert=True)

@router.callback_query(HerokuBackupType.filter())
async def cq_heroku_backup_type(call: types.CallbackQuery, callback_data: HerokuBackupType, bot: Bot):
    ub_username = callback_data.ub_username
    owner_id = callback_data.owner_id
    backup_type = callback_data.backup_type
    if not check_panel_owner(call, owner_id):
        return
    await safe_callback_answer(call, "Создаю Бекап...", show_alert=False)
    await safe_callback_answer(call,
        "<b>⏳ Создание Бекапа...</b>",
        reply_markup=kb.get_loading_keyboard()
    )
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data or ub_data.get("ub_type") != "heroku":
        await safe_callback_answer(call, "❌ Бекап доступен только для Heroku-юзерботов.", show_alert=True)
        await safe_callback_answer(call,
            reply_markup=kb.get_back_to_main_panel_keyboard()
        )
        return
    server_ip = ub_data["server_ip"]
    # try:
    #     backup_path, backup_name = await sm.make_heroku_backup_ssh(ub_username, server_ip, backup_type)
    await safe_callback_answer(call, "❌ Функция бекапа временно недоступна.", show_alert=True)
    await safe_callback_answer(call,
        reply_markup=kb.get_back_to_main_panel_keyboard()
    )
    return
    #     with open(backup_path, "rb") as f:
    #         await bot.send_document(
    #             chat_id=call.from_user.id,
    #             document=FSInputFile(backup_path, filename=backup_name),
    #             caption=f"<b>Backup ({backup_type})</b>",
    #             parse_mode="HTML"
    #         )
    #     sm.cleanup_heroku_backup_file(backup_path)
    #     await call.message.edit_caption(
    #         caption=f"✅ Бекап отправлен! Файл: <code>{backup_name}</code>",
    #         reply_markup=kb.get_back_to_main_panel_keyboard()
    #     )
    # except Exception as e:
    #     logging.error(f"Ошибка при создании/отправке Бекапа: {e}\n{traceback.format_exc()}")
    #     # Truncate error message to avoid Telegram caption length limit
    #     error_msg = str(e)
    #     if len(error_msg) > 200:
    #         error_msg = error_msg[:197] + "..."
    #     
    #     await call.message.edit_caption(
    #         caption=f"❌ Ошибка при создании или отправке Бекапа: <code>{py_html.escape(error_msg)}</code>",
    #         reply_markup=kb.get_back_to_main_panel_keyboard()
    #     )

@router.callback_query(F.data.startswith("select_server:"), UserBotSetup.ChoosingServer)
async def cq_select_server(call: types.CallbackQuery, state: FSMContext):
    server_ip = call.data.split(":")[1]
    
    # Проверяем, не является ли это сервисным сервером
    if server_ip == "127.0.0.1" or server_ip == sm.LOCAL_IP:  # LOCAL_IP
        await safe_callback_answer(call, "ℹ️ Это сервисный сервер, на котором работает бот.\n\nУстановка юзерботов на него невозможна.", show_alert=True)
        return
    
    await _proceed_to_type_selection(call, state, server_ip)

async def _proceed_to_type_selection(call: types.CallbackQuery, state: FSMContext, server_ip: str):
    from bot import BANNER_FILE_IDS
    await state.update_data(server_ip=server_ip)
    
    text = (
        "⬇️ <b>Установка</b>\n\n"
        "<blockquote>"
        "🌘 <b>Hikka</b> - A multifunctional, and most popular developer-focused userbot based on GeekTG, but it is currently closed and will no longer receive updates.\n\n"
        "🪐 <b>Heroku</b> - The most popular fork of the Hikka userbot, it receives regular updates and has many new features, supports Hikka userbot modules.\n\n"
        "🌙 <b>Legacy</b> - The most popular fork of the Heroku userbot, it has a log of fixed bugs, receives regular updates and supports Hikka userbot modules.\n\n"
        "🦊 <b>FoxUserBot</b> - Telegram userbot with the simplest installation, doesn't have much functionality as other userbots, receives regular updates and uses Kurigram (Pyrogram fork)"
        "</blockquote>\n"
        "👾 <b>Выберите юзербот который хотите установить</b>"
    )
    
    photo = BANNER_FILE_IDS.get("select_userbot") or FSInputFile("banners/select_userbot.png")
    
    data = await state.get_data()
    message_id = data.get("message_id_to_edit", call.message.message_id)

    try:
        await call.answer()
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
    random_part = secrets.token_urlsafe(32)
    new_token = f"{username}:{user.id}:{random_part}"
    await db.set_api_token(user.id, new_token)
    return new_token

@router.callback_query(F.data == "regenerate_api_token", StateFilter(APITokenManagement.TokenHidden, APITokenManagement.TokenShown))
async def cq_regenerate_api_token(call: types.CallbackQuery, state: FSMContext):
    user = call.from_user
    username = user.username or f"user{user.id}"
    random_part = secrets.token_urlsafe(32)
    new_token = f"{username}:{user.id}:{random_part}"
    
    if await db.regenerate_user_token(user.id, new_token):
        await state.update_data(token=new_token)
        await safe_callback_answer(call, "✅ API токен успешно обновлен!", show_alert=True)
        await cq_show_api_panel(call, state)
    else:
        await safe_callback_answer(call, "❌ Ошибка обновления токена", show_alert=True)
    
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
    await safe_callback_answer(call, "", show_alert=True)
    token = await _get_or_create_token(call.from_user)
    
    text = (
        "🔑 <b>Ваш персональный API-токен</b>\n\n"
        "Этот токен используется для доступа к API TeaHost из внешних приложений.\n\n"
        "<b>Никому не передавайте этот токен!</b>\n\n"
        "Ваш токен:\n"
        f"<code>{html.quote(_mask_token(token))}</code>"
    )
    
    markup = kb.get_api_token_keyboard(is_shown=False)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await state.set_state(APITokenManagement.TokenHidden)

@router.callback_query(F.data == "toggle_api_token_visibility", StateFilter(APITokenManagement.TokenHidden, APITokenManagement.TokenShown))
async def cq_toggle_api_token_visibility(call: types.CallbackQuery, state: FSMContext):
    await safe_callback_answer(call, "", show_alert=True)
    current_state = await state.get_state()
    token = await _get_or_create_token(call.from_user)
    
    is_currently_shown = current_state == APITokenManagement.TokenShown
    
    new_text_token = _mask_token(token) if is_currently_shown else token
    new_is_shown = not is_currently_shown
    new_state = APITokenManagement.TokenHidden if is_currently_shown else APITokenManagement.TokenShown

    text = (
        "🔑 <b>Ваш персональный API-токен</b>\n\n"
        "Этот токен используется для доступа к API TeaHost из внешних приложений.\n\n"
        "<b>Никому не передавайте этот токен!</b>\n\n"
        "Ваш токен:\n"
        f"<code>{html.quote(new_text_token)}</code>"
    )
    
    markup = kb.get_api_token_keyboard(is_shown=new_is_shown)
    await call.message.edit_caption(caption=text, reply_markup=markup)
    await state.set_state(new_state)
    
def find_ip_by_code(code: str) -> str | None:
    servers = server_config.get_servers()
    for ip, details in servers.items():
        if details.get("code") and details.get("code").lower() == code.lower():
            return ip
    return None

@router.callback_query(F.data.startswith("migrate_ub_start:"))
async def cq_migrate_ub_start(call: types.CallbackQuery, state: FSMContext):
    from bot import BANNER_FILE_IDS
    await call.answer()

    try:
        _, ub_username, owner_id_str = call.data.split(":")
        owner_id = int(owner_id_str)
        if not check_panel_owner(call, owner_id):
            return

        loading_text = "<b>🔄 Смена сервера</b>\n\nЗагружаю доступные сервера..."
        photo = BANNER_FILE_IDS.get("select_server") or FSInputFile("banners/select_server.png")
        await call.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=loading_text),
            reply_markup=kb.get_loading_keyboard()
        )
        
        ub_data = await db.get_userbot_data(ub_username)
        if not ub_data:
            await call.message.edit_caption(caption="❌ Юзербот не найден.", reply_markup=kb.get_back_to_main_panel_keyboard())
            return

        current_server_ip = ub_data['server_ip']
        user_id = call.from_user.id
        has_premium = await db.check_premium_access(user_id)
        
        all_servers = server_config.get_servers()
        all_userbots = await db.get_all_userbots_full_info()
        installed_bots_map = defaultdict(int)
        for ub in all_userbots:
            installed_bots_map[ub['server_ip']] += 1

        available_servers_filtered = []
        for ip, details in all_servers.items():
            if ip == sm.LOCAL_IP or ip == current_server_ip:
                continue
            
            status = details.get("status")
            if status in ['false', 'test']:
                continue
            
            available_servers_filtered.append((ip, details))
        
        data = await state.get_data()
        server_stats = data.get("server_stats", {})
        if not server_stats:
            stats_tasks = [sm.get_server_stats(ip) for ip, _ in available_servers_filtered]
            stats_results = await asyncio.gather(*stats_tasks)
            server_stats = {ip: res for (ip, _), res in zip(available_servers_filtered, stats_results)}

        markup = kb.get_migration_server_selection_keyboard(
            ub_username=ub_username,
            owner_id=owner_id,
            servers_list=available_servers_filtered,
            installed_bots_map=installed_bots_map,
            server_stats=server_stats,
            has_premium_access=has_premium
        )
        
        final_text = f"<b>🔄 Смена сервера</b>\n\n<b>💻 Выберите новый сервер для переноса</b>"
        
        await call.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=final_text),
            reply_markup=markup
        )
        await state.set_state(UserBotSetup.Migrating)

    except Exception as e:
        logging.error(f"Ошибка в cq_migrate_ub_start: {e}")
        await call.answer("Произошла ошибка при запуске переноса.", show_alert=True)

@router.callback_query(F.data.startswith("migrate_ub_select:"), StateFilter(UserBotSetup.Migrating))
async def cq_migrate_ub_execute(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    try:
        _, ub_username, owner_id_str, new_server_code = call.data.split(":")
        owner_id = int(owner_id_str)
        if not check_panel_owner(call, owner_id):
            return

        await state.clear()
        
        await call.message.edit_media(
            media=InputMediaPhoto(media=FSInputFile("banners/panel_userbot.png"), caption="Переношу на другой сервер контейнер..."),
            reply_markup=kb.get_loading_keyboard()
        )
        await call.answer()

        new_server_ip = find_ip_by_code(new_server_code)
        if not new_server_ip or not await server_config.is_install_allowed(new_server_ip, owner_id):
            await call.answer("❌ Выбранный сервер недоступен для установки.", show_alert=True)
            await show_management_panel(call, ub_username, state)
            return

        ub_data = await db.get_userbot_data(ub_username=ub_username)
        if not ub_data:
            await call.message.edit_caption("❌ Ошибка: Юзербот не найден в базе данных.")
            return
        
        old_server_ip = ub_data.get('server_ip')
        ub_type = ub_data.get('ub_type')
        
        if old_server_ip == new_server_ip:
            await call.message.edit_caption("❌ Старый и новый серверы не могут быть одинаковыми.")
            return

        if not await db.update_userbot_server(ub_username, new_server_ip):
            raise Exception("Не удалось обновить IP в базе данных.")
        await db.delete_password(owner_id)

        backup_result = await api_manager.backup_container(ub_username, old_server_ip)
        if not backup_result.get("success"):
            await db.update_userbot_server(ub_username, old_server_ip)
            raise Exception(f"Ошибка создания резервной копии: {backup_result.get('error', 'Неизвестная ошибка')}")

        restore_result = await api_manager.restore_container(ub_username, ub_type, new_server_ip)
        if not restore_result.get("success"):
            await db.update_userbot_server(ub_username, old_server_ip)
            raise Exception(f"Ошибка восстановления: {restore_result.get('error', 'Неизвестная ошибка')}")

        all_servers = server_config.get_servers()
        old_server_details = all_servers.get(old_server_ip, {})
        old_server_code_for_log = old_server_details.get('code', 'N/A')

        log_data = {
            "user_data": {"id": call.from_user.id, "full_name": call.from_user.full_name},
            "ub_info": {"name": ub_username, "type": ub_type},
            "server_info": {"ip": new_server_ip, "code": new_server_code},
            "old_server_info": {"ip": old_server_ip, "code": old_server_code_for_log}
        }
        await log_event(bot, "userbot_migrated", log_data)

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"refresh_panel:{ub_username}:{owner_id}")
        
        await call.message.edit_caption(
            caption="Перенос успешный (200 OK), спасибо что пользуетесь TH (TeaHost).",
            reply_markup=builder.as_markup()
        )

    except Exception as e:
        logging.error(f"Ошибка при переносе контейнера: {e}")
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data=f"refresh_panel:{ub_username}:{owner_id}")
        await call.message.edit_caption(
            f"❌ <b>Произошла ошибка при переносе!</b>\n\n"
            f"<pre>{html.quote(str(e))}</pre>\n\n"
            "Обратитесь в поддержку.",
            reply_markup=builder.as_markup()
        )
# --- END OF FILE user_handlers.py ---
