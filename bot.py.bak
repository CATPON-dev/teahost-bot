import logging
import asyncio
import os
import json
import sys
import shutil
import time
from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramForbiddenError
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, date, timedelta
import pytz
from collections import defaultdict

from config_manager import config
import database as db
import system_manager as sm
import server_config
import user_handlers
import admin_handlers
import keyboards as kb
import inline_handlers  # дада я ебал
from admin_handlers import auto_backup_task
from middlewares.error_handler import handle_errors
from middlewares.ban_check import BanMiddleware
from middlewares.antispam import AntiSpamMiddleware
from admin_manager import get_all_admins
from constants import RESTART_INFO_FILE, STATUS_IDS_FILE, STATS_MESSAGE_ID_FILE
from channel_logger import log_to_channel, log_event

SSH_SEMAPHORE = asyncio.Semaphore(4)

STATUS_MESSAGE_IDS = {"channel": None, "topic": None}
STATS_MESSAGE_ID = None
BANNER_FILE_IDS = {}
LAST_REFRESH_TIMESTAMP = 0
LAST_STATS_REFRESH_TIMESTAMP = 0
DOWN_SERVERS_NOTIFIED = set()

def _read_status_ids() -> dict:
    if not os.path.exists(STATUS_IDS_FILE):
        return {}
    try:
        with open(STATUS_IDS_FILE, 'r') as f:
            data = json.load(f)
            # Фильтруем некорректные значения
            filtered_data = {}
            for key, value in data.items():
                if isinstance(value, int) and value is not None:
                    filtered_data[key] = value
                else:
                    logging.warning(f"Invalid status ID for key {key}: {value}")
            return filtered_data
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _save_status_ids(ids: dict):
    try:
        os.makedirs(os.path.dirname(STATUS_IDS_FILE), exist_ok=True)
        with open(STATUS_IDS_FILE, 'w') as f:
            json.dump(ids, f)
    except Exception as e:
        logging.error(f"Failed to save status IDs: {e}")

def _read_stats_id() -> int | None:
    if not os.path.exists(STATS_MESSAGE_ID_FILE):
        return None
    try:
        with open(STATS_MESSAGE_ID_FILE, 'r') as f:
            data = json.load(f)
            message_id = data.get("message_id")
            # Проверяем, что message_id является корректным числом
            if isinstance(message_id, int) and message_id is not None:
                return message_id
            else:
                logging.warning(f"Invalid stats message ID: {message_id}")
                return None
    except (json.JSONDecodeError, FileNotFoundError, TypeError):
        return None

def _save_stats_id(message_id: int | None):
    try:
        os.makedirs(os.path.dirname(STATS_MESSAGE_ID_FILE), exist_ok=True)
        with open(STATS_MESSAGE_ID_FILE, 'w') as f:
            json.dump({"message_id": message_id}, f)
    except Exception as e:
        logging.error(f"Failed to save stats message ID: {e}")

async def upload_banners(bot: Bot):
    logging.info("Uploading and caching banner file_ids...")
    if not config.SUPER_ADMIN_IDS:
        logging.warning("No SUPER_ADMIN_IDS found in config. Cannot upload banners.")
        return
    
    # В тестовом режиме пропускаем загрузку баннеров
    if config.TEST_MODE:
        logging.info("Test mode enabled, skipping banner upload")
        return
    
    # Определяем целевой чат для кеширования баннеров
    target_chat_id = None
    chat_type = "unknown"
    
    # Сначала пробуем использовать log_channel_id, если он доступен
    if hasattr(config, 'LOG_CHANNEL_ID') and config.LOG_CHANNEL_ID:
        try:
            test_message = await bot.send_message(chat_id=config.LOG_CHANNEL_ID, text="🔄 Тест кеширования баннеров...")
            await bot.delete_message(chat_id=config.LOG_CHANNEL_ID, message_id=test_message.message_id)
            target_chat_id = config.LOG_CHANNEL_ID
            chat_type = "log_channel"
            logging.info(f"Using log channel {target_chat_id} for banner caching")
        except Exception as e:
            logging.warning(f"Cannot use log channel {config.LOG_CHANNEL_ID}: {e}")
    
    # Если log_channel недоступен, используем личные сообщения первого админа
    if target_chat_id is None:
        target_chat_id = config.SUPER_ADMIN_IDS[0]
        chat_type = "admin_pm"
        
        # Проверяем, что бот может отправлять сообщения админу
        try:
            test_message = await bot.send_message(chat_id=target_chat_id, text="🔄 Инициализация кеша баннеров...")
            await bot.delete_message(chat_id=target_chat_id, message_id=test_message.message_id)
            logging.info(f"Successfully tested communication with admin {target_chat_id}")
        except Exception as e:
            logging.error(f"Cannot send messages to admin {target_chat_id}: {e}")
            logging.warning("Banner caching will be skipped. Banners will be loaded from disk when needed.")
            return
    
    banner_files = {
        "main_panel": "banners/select_action.png",
        "select_server": "banners/select_server.png",
        "select_userbot": "banners/select_userbot.png",
        "panel_userbot": "banners/panel_userbot.png",
    }
    for key, path in banner_files.items():
        try:
            if not os.path.exists(path):
                logging.warning(f"Banner file not found: {path}. Skipping.")
                continue
            photo = FSInputFile(path)
            sent_message = await bot.send_photo(chat_id=target_chat_id, photo=photo)
            BANNER_FILE_IDS[key] = sent_message.photo[-1].file_id
            # Удаляем сообщение после получения file_id
            await bot.delete_message(chat_id=target_chat_id, message_id=sent_message.message_id)
            logging.info(f"Cached banner '{key}' via {chat_type}: {BANNER_FILE_IDS[key]}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Failed to upload and cache banner '{key}' from '{path}': {e}")
            # Продолжаем с другими баннерами, даже если один не удался
            continue
    
    if BANNER_FILE_IDS:
        logging.info(f"Banner caching complete. Successfully cached {len(BANNER_FILE_IDS)} banners.")
    else:
        logging.warning("No banners were cached. Will use disk files.")

async def refresh_public_status_handler(call: CallbackQuery, bot: Bot):
    global LAST_REFRESH_TIMESTAMP
    current_time = time.time()
    cooldown = 5

    if current_time - LAST_REFRESH_TIMESTAMP < cooldown:
        await call.answer(f"Обновлять можно раз в {cooldown} секунд.", show_alert=True)
        return

    LAST_REFRESH_TIMESTAMP = current_time
    await call.answer("Обновляю...", show_alert=False)
    await update_status_message(bot, force_resend=False)

async def refresh_stats_panel_handler(call: CallbackQuery, bot: Bot):
    global LAST_STATS_REFRESH_TIMESTAMP
    current_time = time.time()
    cooldown = 5

    if current_time - LAST_STATS_REFRESH_TIMESTAMP < cooldown:
        await call.answer(f"Обновлять можно раз в {cooldown} секунд.", show_alert=True)
        return

    LAST_STATS_REFRESH_TIMESTAMP = current_time
    await call.answer("Обновляю...", show_alert=False)
    await update_stats_message(bot, force_resend=False)

def _create_progress_bar(percent_str: str, length: int = 10) -> str:
    try:
        percent = float(str(percent_str).replace('%',''))
        filled_length = int(length * percent / 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}]"
    except (ValueError, TypeError):
        return f"[{'?' * length}]"

async def _send_or_edit_status_message(bot: Bot, chat_id: int, message_id: int | None, text: str, markup, **kwargs) -> int | None:
    if chat_id is None:
        logging.warning("chat_id is None, skipping message send/edit")
        return None
        
    if message_id:
        try:
            edit_kwargs = {k: v for k, v in kwargs.items() if k in ['disable_web_page_preview']}
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup, **edit_kwargs)
            return message_id
        except TelegramBadRequest as e:
            if "message to edit not found" in str(e) or "message can't be edited" in str(e):
                logging.warning(f"Status message {message_id} not found in chat {chat_id}. Sending a new one.")
            elif "message is not modified" in str(e).lower():
                return message_id
            else:
                logging.error(f"Failed to edit status message {message_id} in {chat_id}: {e}")
                return message_id
    
    try:
        sent_msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, **kwargs)
        return sent_msg.message_id
    except Exception as e:
        logging.error(f"Failed to send new status message to {chat_id}: {e}")
        return None

def pluralize_userbot(n):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "юзербот"
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return "юзербота"
    else:
        return "юзерботов"

async def update_stats_message(bot: Bot, force_resend: bool = False):
    global STATS_MESSAGE_ID
    if not config.STATS_CHAT_ID or not config.STATS_TOPIC_ID:
        logging.warning("STATS_CHAT_ID или STATS_TOPIC_ID не настроены. Обновление статистики пропущено.")
        return

    if force_resend:
        old_id = _read_stats_id()
        if old_id is not None and isinstance(old_id, int):
            try:
                await bot.delete_message(chat_id=config.STATS_CHAT_ID, message_id=old_id)
            except (TelegramBadRequest, TelegramNotFound):
                pass
        STATS_MESSAGE_ID = None
        _save_stats_id(None)

    try:
        all_ubs_info = await db.get_all_userbots_full_info()
        total_ubs = len(all_ubs_info)
        
        bots_by_type = defaultdict(int)
        for ub in all_ubs_info:
            ub_type = ub.get('ub_type', 'unknown').capitalize()
            bots_by_type[ub_type] += 1

        type_emojis = {
            "Fox": "🦊",
            "Heroku": "🪐",
            "Hikka": "🌘",
            "Legacy": "🌙",
            "Unknown": "❓"
        }

        text_parts = [
            "📊 <b>SharkHost статистика</b>"
        ]

        text_parts.append(f"<blockquote>Всего юзерботов: <code>{total_ubs}</code></blockquote>")
        
        text_parts.append("<b>⚙️ Распределение по типам:</b>")

        type_stats = []
        all_known_types = ["Fox", "Heroku", "Hikka", "Legacy"]
        for ub_type in all_known_types:
            count = bots_by_type.get(ub_type, 0)
            emoji = type_emojis.get(ub_type, "🤖")
            type_stats.append(f"- {emoji} {ub_type}: <code>{count}</code>")
            
        text_parts.append(f"<blockquote>" + "\n".join(type_stats) + "</blockquote>")
        
        update_time_str = datetime.now(pytz.timezone("Europe/Moscow")).strftime('%d.%m.%Y в %H:%M:%S')
        text_parts.append(f"<i>Последнее обновление: {update_time_str} MSK</i>")

        text = "\n\n".join(text_parts)
        
        new_id = await _send_or_edit_status_message(
            bot=bot,
            chat_id=config.STATS_CHAT_ID,
            message_id=STATS_MESSAGE_ID,
            text=text,
            markup=kb.get_stats_refresh_keyboard(),
            message_thread_id=config.STATS_TOPIC_ID,
            disable_web_page_preview=True
        )

        if new_id:
            STATS_MESSAGE_ID = new_id
            _save_stats_id(new_id)

    except Exception as e:
        logging.error(f"Не удалось обновить панель статистики: {e}", exc_info=True)

async def update_status_message(bot: Bot, force_resend: bool = False):
    if config.TEST_MODE:
        return

    global STATUS_MESSAGE_IDS
    logging.info(f"Running status panel update. Force resend: {force_resend}")
    
    current_ids = _read_status_ids()
    if force_resend:
        for key, msg_id in current_ids.items():
            # Проверяем, что msg_id не None и является числом
            if msg_id is None or not isinstance(msg_id, int):
                logging.warning(f"Skipping invalid message_id for key {key}: {msg_id}")
                continue
                
            chat_id = config.STATUS_CHANNEL_ID if key == "channel" else config.SUPPORT_CHAT_ID
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except (TelegramBadRequest, TelegramNotFound):
                pass
        current_ids = {}

    try:
        total_users = len(await db.get_all_bot_users())
        servers = server_config.get_servers()
        active_servers = {ip: s for ip, s in servers.items() if s.get('status') == "true" and ip != "127.0.0.1"}  # sm.LOCAL_IP
        available_servers = len(active_servers)
        
        installed_bots_map = {ip: len(await db.get_userbots_by_server_ip(ip)) for ip in servers.keys()}
        
        free_slots = 0
        for ip, s in active_servers.items():
            slots = s.get('slots', 0)
            used = installed_bots_map.get(ip, 0)
            free_slots += max(0, slots - used)

        async def get_stats_with_semaphore(ip):
            async with SSH_SEMAPHORE:
                try:
                    # Получаем реальные данные через SSH
                    stats = await sm.get_server_stats(ip)
                    return stats
                except Exception as e:
                    logging.error(f"Failed to get stats for {ip}: {e}")
                    return {"cpu_usage": "0", "ram_percent": "0", "disk_percent": "0%", "uptime": "N/A"}
        
        tasks = [get_stats_with_semaphore(ip) for ip in servers.keys()]
        stats_results = await asyncio.gather(*tasks)
        server_stats = dict(zip(servers.keys(), stats_results))
        
        text_parts = [
            "🦈 <b>SharkHost Status</b>",
            "",
            "<b>📊 Общая статистика:</b>",
            f"<blockquote>- {total_users} пользователей\n- {available_servers} серверов доступно\n- {free_slots} {pluralize_userbot(free_slots)} можно установить</blockquote>",
            "",
            "<b>🚀 Статус серверов:</b>",
            ""
        ]
        
        for ip, details in servers.items():
            if ip == "127.0.0.1": continue  # sm.LOCAL_IP
            
            # Исключаем сервер, на котором запущен бот (лондонский сервер)
            if details.get("ssh_user") is None and details.get("ssh_pass") is None:
                continue
            
            flag, location_name, code, status = details.get("flag", "🏳️"), details.get("city", details.get("name", "Unknown")), details.get("code", "N/A"), details.get("status", "false")
            
            if status not in ("true", "noub", "test", "false"): status = "false"
            if status == "test" or status == "false":
                continue
            else:
                server_title = f"{flag} {location_name} ({code})"
                stats = server_stats.get(ip, {})
                cpu_percent, ram_percent, disk_percent, uptime = stats.get('cpu_usage', '0'), stats.get('ram_percent', '0'), stats.get('disk_percent', '0%').replace('%', ''), stats.get('uptime', 'N/A')
                cpu_bar, ram_bar, disk_bar = _create_progress_bar(cpu_percent), _create_progress_bar(ram_percent), _create_progress_bar(disk_percent)
                server_block = (f"<blockquote>🧠 CPU: {cpu_bar} {cpu_percent}%\n"
                                f"💾 RAM: {ram_bar} {ram_percent}%\n"
                                f"💽 Disk: {disk_bar} {disk_percent}%\n"
                                f"⏳ Uptime: {uptime}</blockquote>")
                text_parts.append(server_title)
                text_parts.append(server_block)
        
        text = "\n".join(text_parts)
        markup = kb.get_public_status_keyboard(installed_bots_map, server_stats, servers)

        new_channel_id = None
        new_topic_id = None
        
        if config.STATUS_CHANNEL_ID:
            new_channel_id = await _send_or_edit_status_message(bot, config.STATUS_CHANNEL_ID, current_ids.get("channel"), text, markup, disable_web_page_preview=True)
        
        if config.SUPPORT_CHAT_ID:
            new_topic_id = await _send_or_edit_status_message(bot, config.SUPPORT_CHAT_ID, current_ids.get("topic"), text, markup, message_thread_id=config.SUPPORT_TOPIC_ID, disable_web_page_preview=True)

        STATUS_MESSAGE_IDS = {"channel": new_channel_id, "topic": new_topic_id}
        _save_status_ids(STATUS_MESSAGE_IDS)

    except Exception as e:
        logging.error(f"Failed to update status panel: {e}", exc_info=True)

async def check_servers_on_startup(bot: Bot):
    # В тестовом режиме пропускаем проверку серверов при запуске
    if config.TEST_MODE:
        logging.info("Test mode enabled, skipping server check on startup")
        return
        
    logging.info("Starting comprehensive server check-up...")
    servers = server_config.get_servers()
    if not servers:
        logging.warning("ip.json is empty. No servers to check.")
        return

    default_params = {"ssh_user": "root", "ssh_pass": "password", "name": "Unnamed", "country": "Unknown", "city": "Unknown", "flag": "🏳️", "code": "N/A", "status": "false", "slots": 0, "regionName": "N/A", "org": "N/A", "timezone": "N/A", "hosting": False, "proxy": False, "vpn": False}
    needs_saving = False
    for ip, details in servers.items():
        for key, value in default_params.items():
            if key not in details:
                details[key] = value
                needs_saving = True
        if ip == "127.0.0.1":  # sm.LOCAL_IP
            if details.get('ssh_user') is not None: details['ssh_user'] = None; needs_saving = True
            if details.get('ssh_pass') is not None: details['ssh_pass'] = None; needs_saving = True

    if needs_saving:
        logging.info("Updating ip.json with default parameters and nullifying local SSH creds.")
        server_config._save_servers(servers)

    remote_servers_ips = [ip for ip, d in servers.items() if ip != "127.0.0.1"]  # sm.LOCAL_IP
    if not remote_servers_ips:
        logging.info("No remote servers to check.")
        return

    async def check_conn_with_semaphore(ip):
        async with SSH_SEMAPHORE:
            try:
                return await sm.run_command_async("echo 1", ip, timeout=10)
            except Exception as e:
                logging.error(f"Failed to check connection to {ip}: {e}")
                return {"success": False, "error": str(e)}

    tasks = [check_conn_with_semaphore(ip) for ip in remote_servers_ips]
    logging.info(f"Checking connectivity for {len(tasks)} remote servers concurrently...")
    results = await asyncio.gather(*tasks)

    unreachable_servers = []
    for ip, conn_res in zip(remote_servers_ips, results):
        if not conn_res.get("success"):
            error_details = html.quote(conn_res.get('error', 'Неизвестная ошибка SSH'))
            unreachable_servers.append(f" • <code>{ip}</code> - {error_details}")

    if unreachable_servers:
        text = "<b>‼️ Обнаружены недоступные серверы при запуске:</b>\n\n" + "\n".join(unreachable_servers)
        await log_to_channel(bot, text)
    else:
        logging.info("All remote servers checked. Status: OK.")

async def monitor_servers_health(bot: Bot):
    global DOWN_SERVERS_NOTIFIED
    
    # В тестовом режиме пропускаем мониторинг серверов
    if config.TEST_MODE:
        logging.info("Test mode enabled, skipping server health check")
        return
    
    logging.info("Running scheduled server health check...")
    servers = {ip: d for ip, d in server_config.get_servers().items() if ip != "127.0.0.1"}  # sm.LOCAL_IP

    for ip, details in servers.items():
        async with SSH_SEMAPHORE:
            try:
                conn_res = await sm.run_command_async("echo 1", ip, timeout=10)
            except Exception as e:
                logging.error(f"Failed to check health for {ip}: {e}")
                conn_res = {"success": False, "error": str(e)}
        
        if not conn_res.get("success"):
            if ip not in DOWN_SERVERS_NOTIFIED:
                server_config.update_server_status(ip, 'test')
                DOWN_SERVERS_NOTIFIED.add(ip)
                log_data = {"server_info": {"ip": ip, "code": details.get("code", "N/A")}}
                await log_event(bot, "server_unreachable", log_data)
            continue

        if ip in DOWN_SERVERS_NOTIFIED:
            DOWN_SERVERS_NOTIFIED.remove(ip)
            server_config.update_server_status(ip, 'true')
            log_data = {"server_info": {"ip": ip, "code": details.get("code", "N/A")}}
            await log_event(bot, "server_recovered", log_data)

async def daily_backup_task(bot: Bot):
    # В тестовом режиме пропускаем ежедневный бэкап
    if config.TEST_MODE:
        logging.info("Test mode enabled, skipping daily backup task")
        return
        
    source_directory = "/root/nh"
    if not os.path.exists(source_directory):
        logging.warning(f"Ежедневный бэкап: Директория {source_directory} не найдена. Пропускаю.")
        return
    logging.info("Starting daily backup task...")
    backup_filename_base = f"daily_backup_newhost_{datetime.now().strftime('%Y-%m-%d')}"
    backup_filepath_zip = f"{backup_filename_base}.zip"
    def _blocking_create_backup():
        try:
            shutil.make_archive(backup_filename_base, 'zip', source_directory)
            return True
        except Exception as e:
            logging.error(f"Ошибка при создании ежедневного архива: {e}")
            return False
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, _blocking_create_backup)
    if not success:
        logging.error("Ежедневный бэкап: не удалось создать архив.")
        if os.path.exists(backup_filepath_zip):
            os.remove(backup_filepath_zip)
        return
    logging.info(f"Daily backup archive created: {backup_filepath_zip}")
    try:
        document = FSInputFile(backup_filepath_zip)
        for admin_id in config.SUPER_ADMIN_IDS:
            try:
                await bot.send_document(
                    chat_id=admin_id, document=document,
                    caption=f"🗂️ Ежедневная резервная копия (от {datetime.now().strftime('%Y-%m-%d')})"
                )
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Не удалось отправить бэкап администратору {admin_id}: {e}")
    finally:
        if os.path.exists(backup_filepath_zip):
            os.remove(backup_filepath_zip)
            logging.info(f"Daily backup archive deleted: {backup_filepath_zip}")

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
    return " ".join(parts) if parts else "<1m"

async def daily_log_cleanup():
    # В тестовом режиме пропускаем очистку логов
    if config.TEST_MODE:
        logging.info("Test mode enabled, skipping daily log cleanup")
        return
        
    log_file = "bot.log"
    logging.info(f"Starting daily cleanup of {log_file}...")
    try:
        with open(log_file, "w") as f:
            f.truncate(0)
        logging.info(f"Successfully truncated {log_file}.")
    except Exception as e:
        logging.error(f"Failed to truncate {log_file}: {e}")

async def main():
    try:
        await db.init_pool()
        await db.init_db()
        
        bot = Bot(
            token=config.BOT_TOKEN, 
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        await upload_banners(bot)
        
        dp.update.middleware(BanMiddleware())
        dp.update.middleware(AntiSpamMiddleware())
        dp.errors.register(handle_errors)
        dp.include_router(admin_handlers.router)
        dp.include_router(user_handlers.router)
        dp.callback_query.register(refresh_public_status_handler, F.data == "refresh_public_status")
        dp.callback_query.register(refresh_stats_panel_handler, F.data == "refresh_stats_panel")

        await check_servers_on_startup(bot)
        
        # Удаляем старые сообщения статуса только если каналы настроены
        if config.STATUS_CHANNEL_ID or config.SUPPORT_CHAT_ID:
            old_status_ids = _read_status_ids()
            for key, msg_id in old_status_ids.items():
                # Проверяем, что msg_id не None и является числом
                if msg_id is None or not isinstance(msg_id, int):
                    logging.warning(f"Skipping invalid message_id for key {key}: {msg_id}")
                    continue
                    
                chat_id = config.STATUS_CHANNEL_ID if key == "channel" else config.SUPPORT_CHAT_ID
                if chat_id is None:
                    continue
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except (TelegramBadRequest, TelegramNotFound):
                    pass
            _save_status_ids({})

        # Удаляем старое сообщение статистики только если канал настроен
        if config.STATS_CHAT_ID:
            old_stats_id = _read_stats_id()
            if old_stats_id is not None and isinstance(old_stats_id, int):
                try:
                    await bot.delete_message(chat_id=config.STATS_CHAT_ID, message_id=old_stats_id)
                except (TelegramBadRequest, TelegramNotFound):
                    pass
            _save_stats_id(None)

        if os.path.exists(RESTART_INFO_FILE):
            try:
                with open(RESTART_INFO_FILE, "r") as f:
                    restart_info = json.load(f)
                await bot.edit_message_text(
                    chat_id=restart_info["chat_id"], message_id=restart_info["message_id"], text="✅ Бот успешно перезапущен!"
                )
            except Exception as e:
                logging.error(f"Could not edit restart message: {e}")
            finally:
                os.remove(RESTART_INFO_FILE)

        await bot.delete_webhook(drop_pending_updates=True)

        scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
        scheduler.add_job(monitor_servers_health, 'interval', minutes=10, args=[bot])
        scheduler.add_job(update_status_message, 'interval', minutes=3, args=[bot, False])
        scheduler.add_job(update_stats_message, 'interval', minutes=10, args=[bot, False])
        scheduler.add_job(daily_log_cleanup, 'cron', hour=3, minute=0, id="daily_log_cleanup")
        
        # Автоматическое резервное копирование каждые 30 минут (в :00 и :30)
        scheduler.add_job(auto_backup_task, 'cron', minute='0,30', timezone='Europe/Moscow', args=[bot], id="auto_backup")
        
        scheduler.start()
        
        await update_status_message(bot, force_resend=True)
        await update_stats_message(bot, force_resend=True)

        logging.info("Starting bot polling...")
        try:
            await dp.start_polling(bot)
        finally:
            logging.warning("Bot polling stopped. Shutting down...")
            if scheduler.running:
                scheduler.shutdown()
            await dp.storage.close()
            await bot.session.close()
            logging.info("Bot has been shut down gracefully.")
    except Exception as e:
        logging.critical("!!! A CRITICAL ERROR OCCURRED !!!", exc_info=True)

if __name__ == '__main__':
    logs_dir = 'logs'
    archive_dir = 'Archive'
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)
    log_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    session_log_name = f'bot-{log_time}.log'
    session_log_path = os.path.join(logs_dir, session_log_name)
    if os.path.exists('bot.log') and os.path.getsize('bot.log') > 0:
        archive_name = f'bot-{log_time}-archive.log'
        archive_path = os.path.join(archive_dir, archive_name)
        shutil.move('bot.log', archive_path)
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    file_handler = logging.FileHandler(session_log_path, mode='w', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    logging.getLogger().addHandler(file_handler)
    class StreamToLogger(object):
        def __init__(self, logger, level):
            self.logger = logger
            self.level = level
        def write(self, message):
            message = message.rstrip()
            if message:
                self.logger.log(self.level, message)
        def flush(self):
            pass
    sys.stdout = StreamToLogger(logging.getLogger(), logging.INFO)
    sys.stderr = StreamToLogger(logging.getLogger(), logging.ERROR)
    asyncio.run(main())
