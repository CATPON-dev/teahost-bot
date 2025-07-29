import logging
from aiogram import Bot, html
from aiogram.exceptions import TelegramAPIError

from config_manager import config

EVENT_TAGS = {
    # Lifecycle
    "installation_success": "#ЮЗЕРБОТ_СОЗДАН",
    "deletion_by_owner": "#ЮЗЕРБОТ_УДАЛЕН",
    "deletion_by_admin": "#УДАЛЕНО_АДМИНОМ",
    "new_user_registered": "#НОВЫЙ_ПОЛЬЗОВАТЕЛЬ",
    
    # User Actions
    "user_action_manage_ub": "#ДЕЙСТВИЕ_ПОЛЬЗОВАТЕЛЯ",
    "userbot_reinstalled": "#ЮЗЕРБОТ_ПЕРЕУСТАНОВЛЕН",
    
    # Admin Actions
    "user_banned": "#БАН",
    "user_unbanned": "#РАЗБАН",
    "userbot_transferred": "#ПЕРЕДАЧА_ЮЗЕРБОТА",
    
    # System & Health
    "installation_failed": "#ОШИБКА_УСТАНОВКИ",
    "server_unreachable": "#СЕРВЕР_НЕДОСТУПЕН",
    "server_recovered": "#СЕРВЕР_ВОССТАНОВЛЕН",
    "inactive_session_warning": "#ПРЕДУПРЕЖДЕНИЕ_СЕССИЯ",
    
    # Access Control
    "panel_shared_accepted": "#ДОСТУП_ВЫДАН",
    "panel_share_revoked": "#ДОСТУП_ОТОЗВАН",
    
    # Maintenance
    "maintenance_mode_on": "#ТЕХ_РАБОТЫ_ВКЛ",
    "maintenance_mode_off": "#ТЕХ_РАБОТЫ_ВЫКЛ",
    "server_settings_changed": "#НАСТРОЙКИ_СЕРВЕРА"
}

def _format_user_link(user_data: dict) -> str:
    if not user_data or not user_data.get("id"):
        return "N/A"
    
    user_id = user_data["id"]
    full_name = html.quote(user_data.get("full_name", str(user_id)))
    
    return f'<a href="tg://user?id={user_id}">{full_name}</a> (<code>{user_id}</code>)'

async def log_to_channel(bot: Bot, text: str):
    if not config.LOG_CHANNEL_ID:
        logging.warning("LOG_CHANNEL_ID не установлен в конфиге. Логирование в канал отключено.")
        return

    try:
        await bot.send_message(
            chat_id=config.LOG_CHANNEL_ID,
            text=text,
            disable_notification=True,
            parse_mode="HTML"
        )
    except TelegramAPIError as e:
        logging.error(f"Не удалось отправить лог в канал {config.LOG_CHANNEL_ID}: {e}")

async def log_event(bot: Bot, event_type: str, data: dict):
    if not config.LOG_CHANNEL_ID:
        return

    tag = EVENT_TAGS.get(event_type, f"#{event_type.upper()}")

    admin_link = _format_user_link(data.get('admin_data'))
    user_link = _format_user_link(data.get('user_data'))
    new_owner_link = _format_user_link(data.get('new_owner_data'))
    sharer_link = _format_user_link(data.get('sharer_data')) 
    
    ub_info = data.get('ub_info', {})
    ub_name = html.quote(ub_info.get('name', 'N/A'))
    ub_type = html.quote(ub_info.get('type', 'N/A'))
    
    server_info = data.get('server_info', {})
    server_ip = html.quote(server_info.get('ip', 'N/A'))
    server_code = html.quote(server_info.get('code', 'N/A'))
    
    reason = html.quote(data.get('reason', ''))
    error_text = html.quote(data.get('error', ''))
    details_text = html.quote(data.get('details', ''))
    action_text = html.quote(data.get('action', ''))

    message_body = ""

    if event_type == "installation_success":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code> ({ub_type.capitalize()})\n"
            f"<b>Сервер:</b> {server_code}"
        )
    elif event_type == "deletion_by_owner":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>"
        )
    elif event_type == "new_user_registered":
        message_body = f"<b>Пользователь:</b> {user_link}"
        
    elif event_type == "user_action_manage_ub":
        action_map = {"start": "🚀 Запустил", "stop": "🔴 Остановил", "restart": "🔄 Перезапустил"}
        action_str = action_map.get(action_text, action_text)
        message_body = f"<b>Пользователь:</b> {user_link}\n<b>Действие:</b> {action_str} юзербота <code>{ub_name}</code>"

    elif event_type == "user_banned":
        message_body = f"<b>Администратор:</b> {admin_link}\n<b>Забанил пользователя:</b> {user_link}"
    
    elif event_type == "user_unbanned":
        message_body = f"<b>Администратор:</b> {admin_link}\n<b>Разбанил пользователя:</b> {user_link}"
    
    elif event_type == "deletion_by_admin":
        message_body = (
            f"<b>Администратор:</b> {admin_link}\n"
            f"<b>Владелец:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>\n"
            f"<b>Причина:</b> {reason}"
        )
    
    elif event_type == "server_unreachable":
        message_body = f"<b>Сервер:</b> {server_code} (<code>{server_ip}</code>)\n<b>Статус:</b> Недоступен. Отключен для пользователей."

    elif event_type == "server_recovered":
        message_body = f"<b>Сервер:</b> {server_code} (<code>{server_ip}</code>)\n<b>Статус:</b> Снова в сети. Включен для пользователей."

    elif event_type == "inactive_session_warning":
        message_body = f"<b>Пользователь:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code>\n<b>Статус:</b> Отправлено предупреждение об отсутствии сессии."
        
    elif event_type == "panel_shared_accepted":
        message_body = (
            f"<b>Владелец:</b> {sharer_link}\n"
            f"<b>Выдал доступ к</b> <code>{ub_name}</code>\n"
            f"<b>Пользователю:</b> {user_link}"
        )
    
    elif event_type == "panel_share_revoked":
        message_body = (
            f"<b>Владелец:</b> {sharer_link}\n"
            f"<b>Отозвал доступ у</b> {user_link}\n"
            f"<b>к юзерботу:</b> <code>{ub_name}</code>"
        )
    
    else:
        if event_type == "installation_failed":
            message_body = (f"<b>Пользователь:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code>\n<b>Ошибка:</b> <pre>{error_text}</pre>")
        elif event_type == "maintenance_mode_on":
            message_body = f"<b>Администратор:</b> {admin_link}\n<b>Статус:</b> Включен режим технических работ"
        elif event_type == "maintenance_mode_off":
            message_body = f"<b>Администратор:</b> {admin_link}\n<b>Статус:</b> Выключен режим технических работ"
        elif event_type == "server_settings_changed":
            message_body = (f"<b>Сервер:</b> {server_code}\n<b>Администратор:</b> {admin_link}\n<b>Детали:</b> {details_text}")
        elif event_type == "userbot_reinstalled":
            message_body = f"<b>Пользователь:</b> {user_link}\n<b>Переустановил юзербота:</b> <code>{ub_name}</code>"
        elif event_type == "userbot_transferred":
            message_body = (f"<b>Старый владелец:</b> {user_link}\n<b>Новый владелец:</b> {new_owner_link}\n<b>Юзербот:</b> <code>{ub_name}</code>")
        else:
            message_body = f"ℹ️ <b>Неизвестное событие: {html.quote(event_type)}</b>\n\n<pre>{html.quote(str(data))}</pre>"

    if message_body:
        full_text = f"{tag}\n\n{message_body}"
        await log_to_channel(bot, full_text)