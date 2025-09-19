import logging
from aiogram import Bot, html
from aiogram.exceptions import TelegramAPIError
from config_manager import config

TOPIC_MAP = {
    "installation_success": 5,
    "installation_via_api": 5,
    "deletion_by_owner": 7,
    "api_event": 23,
    "new_user_registered": 3,
    "server_unreachable": 9,
    "server_recovered": 11,
    "server_settings_changed": 13,
    "installation_failed": 15,
    "deletion_by_admin": 17,
    "session_violation": 19,
    "referral_created": 21,
    "referral_deleted": 21,
    "user_banned": 25,
    "user_unbanned": 25,
    "unauthorized_access_attempt": 25,
    "maintenance_mode_on": 28,
    "maintenance_mode_off": 28,
    "inactive_session_warning": 140,
    "batched_session_warning": 140,
    "userbot_reinstalled": 30,
    "api_container_error": 3206,
    "installation_timeout": 3209,
    "userbot_migrated": 3221,
}

KEYWORD_TO_TOPIC_MAP = {
    "обнаружены недоступные серверы": 9,
    "обнаружено >1 сессии": 19,
}

EVENT_TAGS = {
    "installation_success": "#ЮЗЕРБОТ_СОЗДАН",
    "installation_via_api": "#API_УСТАНОВКА",
    "deletion_by_owner": "#ЮЗЕРБОТ_УДАЛЕН",
    "deletion_by_admin": "#УДАЛЕНО_АДМИНОМ",
    "new_user_registered": "#НОВЫЙ_ПОЛЬЗОВАТЕЛЬ",
    "user_action_manage_ub": "#ДЕЙСТВИЕ_ПОЛЬЗОВАТЕЛЯ",
    "userbot_reinstalled": "#ЮЗЕРБОТ_ПЕРЕУСТАНОВЛЕН",
    "user_banned": "#БАН",
    "user_unbanned": "#РАЗБАН",
    "userbot_transferred": "#ПЕРЕДАЧА_ЮЗЕРБОТА",
    "installation_failed": "#ОШИБКА_УСТАНОВКИ",
    "server_unreachable": "#СЕРВЕР_НЕДОСТУПЕН",
    "server_recovered": "#СЕРВЕР_ВОССТАНОВЛЕН",
    "inactive_session_warning": "#ПРЕДУПРЕЖДЕНИЕ_СЕССИЯ",
    "panel_shared_accepted": "#ДОСТУП_ВЫДАН",
    "panel_share_revoked": "#ДОСТУП_ОТОЗВАН",
    "maintenance_mode_on": "#ТЕХ_РАБОТЫ_ВКЛ",
    "maintenance_mode_off": "#ТЕХ_РАБОТЫ_ВЫКЛ",
    "server_settings_changed": "#НАСТРОЙКИ_СЕРВЕРА",
    "api_event": "#API_ЛОГИ",
    "api_delete_userbot": "#API_ЗАПРОС",
    "referral_created": "#РЕФ_ССЫЛКА_СОЗДАНА",
    "referral_deleted": "#РЕФ_ССЫЛКА_УДАЛЕНА",
    "session_violation": "#НАРУШЕНИЕ_ПРАВИЛ",
    "unauthorized_access_attempt": "#НЕСАНКЦ_ДОСТУП",
    "api_container_error": "#API_CONTAINER_ERROR",
    "installation_timeout": "#INSTALLATION_TIMEOUT",
    "userbot_migrated": "#ЮЗЕРБОТ_ПЕРЕНЕСЕН",
}


def _format_user_link(user_data: dict) -> str:
    if not user_data or not user_data.get("id"):
        return "N/A"
    user_id = user_data["id"]
    full_name = html.quote(user_data.get("full_name", str(user_id)))
    return f'<a href="tg://user?id={user_id}">{full_name}</a> (<code>{user_id}</code>)'


async def log_to_channel(bot: Bot, text: str, topic_id: int = None):
    if not config.LOG_CHAT_ID:
        logging.warning("LOG_CHAT_ID не установлен. Логирование отключено.")
        return

    if topic_id is None:
        lower_text = text.lower()
        for keyword, tid in KEYWORD_TO_TOPIC_MAP.items():
            if keyword in lower_text:
                topic_id = tid
                break

    try:
        await bot.send_message(
            chat_id=config.LOG_CHAT_ID,
            text=text,
            disable_notification=True,
            parse_mode="HTML",
            message_thread_id=topic_id
        )
    except TelegramAPIError as e:
        logging.error(
            f"Не удалось отправить лог в чат {config.LOG_CHAT_ID} (топик: {topic_id}): {e}")


async def log_event(bot: Bot, event_type: str, data: dict):
    if not config.LOG_CHAT_ID:
        return

    is_api_event = event_type.startswith("api_")

    tag_key = event_type
    if is_api_event and tag_key not in EVENT_TAGS:
        tag_key = "api_event"
    tag = EVENT_TAGS.get(tag_key, f"#{event_type.upper()}")

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
    topic_id = TOPIC_MAP.get(event_type)

    if is_api_event and event_type not in [
        "api_container_error",
            "installation_timeout"]:
        if topic_id is None:
            topic_id = TOPIC_MAP.get("api_event")
        message_body = (
            f"<b>Событие:</b> <code>{html.quote(event_type)}</code>\n"
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>\n"
            f"<b>Сервер:</b> {server_code}\n"
            f"<b>Детали:</b> <pre>{details_text or error_text}</pre>"
        )
    elif event_type in ["installation_success", "installation_via_api"]:
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code> ({ub_type.capitalize()})\n<b>Сервер:</b> {server_code}")
    elif event_type == "deletion_by_owner":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code>")
    elif event_type == "new_user_registered":
        message_body = f"<b>Пользователь:</b> {user_link}"
    elif event_type == "server_unreachable":
        message_body = f"<b>Сервер:</b> {server_code} (<code>{server_ip}</code>)\n<b>Статус:</b> Недоступен. Отключен для пользователей."
    elif event_type == "server_recovered":
        message_body = f"<b>Сервер:</b> {server_code} (<code>{server_ip}</code>)\n<b>Статус:</b> Снова в сети. {details_text}"
    elif event_type == "server_settings_changed":
        message_body = (
            f"<b>Сервер:</b> {server_code}\n<b>Администратор:</b> {admin_link}\n<b>Детали:</b> {details_text}")
    elif event_type == "installation_failed":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code>\n<b>Ошибка:</b> <pre>{error_text}</pre>")
    elif event_type == "api_container_error":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>\n"
            f"<b>Сервер:</b> {server_code}\n"
            f"<b>Ошибка:</b> <pre>{error_text}</pre>"
        )
    elif event_type == "installation_timeout":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code> ({ub_type.capitalize()})\n"
            f"<b>Сервер:</b> {server_code}\n"
            f"<b>Статус:</b> Таймаут ожидания ссылки для входа")
    elif event_type == "userbot_migrated":
        old_server_info = data.get('old_server_info', {})
        old_server_code = html.quote(old_server_info.get('code', 'N/A'))
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>\n"
            f"<b>Старый сервер:</b> {old_server_code}\n"
            f"<b>Новый сервер:</b> {server_code}\n"
            f"<b>Статус:</b> Успешно перенесен"
        )
    elif event_type == "deletion_by_admin":
        message_body = (
            f"<b>Администратор:</b> {admin_link}\n<b>Владелец:</b> {user_link}\n<b>Юзербот:</b> <code>{ub_name}</code>\n<b>Причина:</b> {reason}")
    elif event_type == "session_violation":
        message_body = data.get(
            "formatted_text",
            "Ошибка форматирования лога нарушения.")
    elif event_type in ["referral_created", "referral_deleted"]:
        message_body = (
            f"<b>Администратор:</b> {admin_link}\n<b>Действие:</b> {details_text}")
    elif event_type == "user_banned":
        message_body = (
            f"<b>Администратор:</b> {admin_link}\n<b>Забанил пользователя:</b> {user_link}\n<b>Детали:</b> {details_text}")
    elif event_type == "user_unbanned":
        message_body = f"<b>Администратор:</b> {admin_link}\n<b>Разбанил пользователя:</b> {user_link}"
    elif event_type == "unauthorized_access_attempt":
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n<b>Действие:</b> Попытка несанкционированного доступа\n<b>Детали:</b> {details_text}")
    elif event_type in ["maintenance_mode_on", "maintenance_mode_off"]:
        status = "Включен" if event_type == "maintenance_mode_on" else "Выключен"
        message_body = f"<b>Администратор:</b> {admin_link}\n<b>Статус:</b> {status} режим тех. работ"
    elif event_type == "userbot_reinstalled":
        message_body = f"<b>Пользователь:</b> {user_link}\n<b>Переустановил юзербота:</b> <code>{ub_name}</code>"
    elif event_type == "inactive_session_warning":
        file_listing = html.quote(data.get('error', ''))
        message_body = (
            f"<b>Пользователь:</b> {user_link}\n"
            f"<b>Юзербот:</b> <code>{ub_name}</code>\n"
            f"<b>Детали:</b> {details_text}\n"
            f"<b>Статус:</b> ❗️ Отсутствует файл сессии (*.session)\n\n"
            f"<b>Содержимое каталога данных:</b>\n<pre>{file_listing}</pre>"
        )
    elif event_type == "batched_session_warning":
        tag = "#ПРЕДУПРЕЖДЕНИЕ_СЕССИЯ"
        message_body = data.get("formatted_text", "")
    else:
        message_body = f"ℹ️ <b>Событие: {html.quote(event_type)}</b>\n\n<pre>{html.quote(str(data))}</pre>"
        topic_id = None

    if message_body:
        full_text = f"{tag}\n\n{message_body}"
        await log_to_channel(bot, full_text, topic_id=topic_id)
