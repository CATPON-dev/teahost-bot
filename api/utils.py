import asyncio
import logging
from aiogram import Bot, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
import database as db
import server_config
from config_manager import config
from channel_logger import log_event

logger = logging.getLogger(__name__)


def create_bot_instance():
    return Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )


async def api_create_and_notify(tg_user_id: int, server_ip: str, webui_port: int):
    bot = create_bot_instance()
    try:
        login_url = f"https://ub{tg_user_id}.sharkhost.space"
        builder = InlineKeyboardBuilder()
        builder.button(text="➡️ Войти в WEB-UI", url=login_url)
        text = f"✅ <b>Ваш юзербот, созданный через API, готов!</b>\n\nИспользуйте кнопку ниже для авторизации."
        await bot.send_message(tg_user_id, text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    finally:
        await bot.session.close()


async def api_delete_and_notify(tg_user_id: int, ub_username: str, server_ip: str, request_ip: str):
    bot = create_bot_instance()
    try:
        ub_data = await db.get_userbot_data(ub_username)
        ub_type = ub_data.get(
            'ub_type',
            'Userbot').capitalize() if ub_data else 'Userbot'

        server_details = server_config.get_servers().get(server_ip, {})
        server_code = server_details.get('code', 'Unknown')
        server_flag = server_details.get('flag', '🏳️')

        text = (
            f"🗑️ <b>Ваш юзербот {html.quote(ub_type)} был удален по API запросу.</b>\n\n"
            "<blockquote>"
            f"<b>Сервер:</b> {server_flag} {server_code}\n"
            f"<b>IP-адрес запроса:</b> <code>{request_ip}</code>"
            "</blockquote>")
        await bot.send_message(tg_user_id, text)
    finally:
        await bot.session.close()


async def log_api_action(event_type: str, data: dict):
    bot = None
    try:
        bot = create_bot_instance()
        await log_event(bot, event_type, data)
    except Exception as e:
        logger.error(f"Failed to log API event '{event_type}': {e}")
    finally:
        if bot:
            await bot.session.close()
