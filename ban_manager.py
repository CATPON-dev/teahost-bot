import logging
import asyncio
from aiogram import Bot, html, types
import database as db
from api_manager import api_manager
from channel_logger import log_event

async def execute_ban(target_user_data: dict, admin_user: types.User, bot: Bot, identifier_used: str, is_in_db: bool):
    target_user_id = target_user_data.get('id')
    if not target_user_id:
        return

    await db.add_or_update_banned_user(
        tg_user_id=target_user_id,
        username=target_user_data.get('username'),
        full_name=target_user_data.get('full_name')
    )

    userbots = await db.get_userbots_by_tg_id(target_user_id)
    if userbots:
        tasks = []
        for ub in userbots:
            await db.block_userbot(ub['ub_username'], True)
            tasks.append(api_manager.stop_container(ub['ub_username'], ub['server_ip']))
        
        if tasks:
            await asyncio.gather(*tasks)

    try:
        db_status = "есть в БД" if is_in_db else "нет в БД"
        log_details = f"Цель: {identifier_used} ({db_status})"
        
        log_data = {
            "admin_data": { "id": admin_user.id, "full_name": admin_user.full_name },
            "user_data": { "id": target_user_id, "full_name": target_user_data.get('full_name', identifier_used) },
            "details": log_details
        }
        await log_event(bot, "user_banned", log_data)
    except Exception as e:
        logging.error(f"Failed to log ban event: {e}")

    try:
        await bot.send_message(target_user_id, "❌ <b>Вы были заблокированы администратором.</b>")
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