import logging
from aiogram import Bot, html, types
import database as db
import system_manager as sm
from channel_logger import log_event

async def execute_ban(target_user_id: int, admin_user: types.User, bot: Bot):
    await db.set_user_ban_status(target_user_id, True)

    userbots = await db.get_userbots_by_tg_id(target_user_id)
    if userbots:
        for ub in userbots:
            await db.block_userbot(ub['ub_username'], True)
            await sm.manage_ub_service(ub['ub_username'], "stop", ub['server_ip'])

    try:
        try:
            banned_user_chat = await bot.get_chat(target_user_id)
            banned_user_data = {
                "id": banned_user_chat.id,
                "full_name": banned_user_chat.full_name
            }
        except Exception:
            banned_user_data = {
                "id": target_user_id,
                "full_name": str(target_user_id)
            }

        log_data = {
            "admin_data": {
                "id": admin_user.id,
                "full_name": admin_user.full_name
            },
            "user_data": banned_user_data
        }
        await log_event(bot, "user_banned", log_data)
    except Exception as e:
        logging.error(f"Failed to log ban event: {e}")

    try:
        ban_message = (
            "❌ <b>Вы забанены.</b>\n\n"
            "Доступ к боту для вас ограничен."
        )
        await bot.send_message(target_user_id, ban_message)
    except Exception as e:
        logging.warning(f"Не удалось уведомить пользователя {target_user_id} о бане: {e}")

async def execute_unban(target_user_id: int, admin_user: types.User, bot: Bot):
    await db.set_user_ban_status(target_user_id, False)

    userbots = await db.get_userbots_by_tg_id(target_user_id)
    if userbots:
        for ub in userbots:
            await db.block_userbot(ub['ub_username'], False)

    try:
        try:
            unbanned_user_chat = await bot.get_chat(target_user_id)
            unbanned_user_data = {
                "id": unbanned_user_chat.id,
                "full_name": unbanned_user_chat.full_name
            }
        except Exception:
            unbanned_user_data = {
                "id": target_user_id,
                "full_name": str(target_user_id)
            }

        log_data = {
            "admin_data": {
                "id": admin_user.id,
                "full_name": admin_user.full_name
            },
            "user_data": unbanned_user_data
        }
        await log_event(bot, "user_unbanned", log_data)
    except Exception as e:
        logging.error(f"Failed to log unban event: {e}")

    try:
        await bot.send_message(target_user_id, "✅ Вы были разблокированы администратором.")
    except Exception as e:
        logging.warning(f"Не удалось уведомить пользователя {target_user_id} о разбане: {e}")