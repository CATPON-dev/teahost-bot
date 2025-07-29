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
        admin_full_name = html.quote(admin_user.full_name)
        admin_username_str = f"@{admin_user.username}" if admin_user.username else ""
        admin_info = f"{admin_full_name} ({html.quote(admin_username_str)}, <code>{admin_user.id}</code>)"
        
        banned_user_info = f"<code>{target_user_id}</code>"
        try:
            banned_user_chat = await bot.get_chat(target_user_id)
            banned_full_name = html.quote(banned_user_chat.full_name)
            banned_username_str = f"@{banned_user_chat.username}" if banned_user_chat.username else ""
            banned_user_info = f"{banned_full_name} ({html.quote(banned_username_str)}, <code>{target_user_id}</code>)"
        except Exception:
            pass
            
        log_data = {"admin_info": admin_info, "user_info": banned_user_info}
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
        admin_full_name = html.quote(admin_user.full_name)
        admin_username_str = f"@{admin_user.username}" if admin_user.username else ""
        admin_info = f"{admin_full_name} ({html.quote(admin_username_str)}, <code>{admin_user.id}</code>)"

        unbanned_user_info = f"<code>{target_user_id}</code>"
        try:
            unbanned_user_chat = await bot.get_chat(target_user_id)
            unbanned_full_name = html.quote(unbanned_user_chat.full_name)
            unbanned_username_str = f"@{unbanned_user_chat.username}" if unbanned_user_chat.username else ""
            unbanned_user_info = f"{unbanned_full_name} ({html.quote(unbanned_username_str)}, <code>{target_user_id}</code>)"
        except Exception:
            pass
            
        log_data = {"admin_info": admin_info, "user_info": unbanned_user_info}
        await log_event(bot, "user_unbanned", log_data)
    except Exception as e:
        logging.error(f"Failed to log unban event: {e}")

    try:
        await bot.send_message(target_user_id, "✅ Вы были разблокированы администратором.")
    except Exception as e:
        logging.warning(f"Не удалось уведомить пользователя {target_user_id} о разбане: {e}")