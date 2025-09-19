# --- START OF FILE inline_handlers.py ---
import logging
import asyncio
from aiogram import Router, F, Bot, html
from aiogram.types import InlineQuery, InputTextMessageContent, InlineQueryResultArticle, InlineQueryResultPhoto, WebAppInfo
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hlink
import datetime

import database as db
# import system_manager as sm
import server_config
import keyboards as kb
from filters import IsSuperAdmin
from admin_manager import get_all_admins

router = Router()


def create_progress_bar(percent_str: str, length: int = 10) -> str:
    try:
        percent = float(str(percent_str).replace('%', ''))
        filled_length = int(length * percent / 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}] {percent:.1f}%"
    except (ValueError, TypeError):
        return f"[{'?' * length}] N/A"


async def _get_full_server_info_text(stats_map, servers):
    text_parts = ["🖥️ <b>Статистика по серверам:</b>\n"]
    for ip, details in servers.items():
        stats = stats_map.get(ip, {})
        ub_count = len(await db.get_userbots_by_server_ip(ip))

        cpu_bar = create_progress_bar(stats.get('cpu_usage', '0'))
        ram_bar = create_progress_bar(stats.get('ram_percent', '0'))
        disk_bar = create_progress_bar(stats.get('disk_percent', '0'))

        ram_used = stats.get('ram_used', 'N/A')
        ram_total = stats.get('ram_total', 'N/A')
        disk_used = stats.get('disk_used', 'N/A')
        disk_total = stats.get('disk_total', 'N/A')
        uptime = stats.get('uptime', 'N/A')

        flags = []
        if details.get('hosting'):
            flags.append("☁️ Hosting")
        if details.get('vpn'):
            flags.append("🛡️ VPN")
        if details.get('proxy'):
            flags.append("🌐 Proxy")
        flags_str = " | ".join(flags) if flags else "Нет"

        server_block = (
            f"\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
            f"<b>{details.get('flag', '🏳️')} {details.get('name')}</b> (<code>{ip}</code>)\n"
            f"├ <b>Локация:</b> {details.get('country')}, {details.get('city')}\n"
            f"├ <b>Провайдер:</b> {details.get('org', 'N/A')}\n"
            f"├ <b>CPU:</b>  {cpu_bar}\n"
            f"├ <b>RAM:</b> {ram_bar} ({ram_used}/{ram_total})\n"
            f"├ <b>Disk:</b>  {disk_bar} ({disk_used}/{disk_total})\n"
            f"├ <b>Uptime:</b> {uptime}\n"
            f"├ <b>Особенности:</b> {flags_str}\n"
            f"└ <b>Юзерботы:</b> {ub_count} шт.")
        text_parts.append(server_block)

    return "".join(text_parts)


@router.inline_query(F.query.startswith("info "))
async def inline_user_info_handler(inline_query: InlineQuery):
    identifier = inline_query.query[len("info "):].strip()

    if not identifier:
        result = InlineQueryResultArticle(
            id="info_help",
            title="Информация о пользователе",
            description="Укажите ID или юзернейм пользователя после 'info'",
            input_message_content=InputTextMessageContent(
                message_text="ℹ️ Пожалуйста, укажите ID или юзернейм пользователя."))
        await inline_query.answer([result], is_personal=True, cache_time=5)
        return

    user_data = await db.get_user_by_username_or_id(identifier)

    if not user_data:
        result = InlineQueryResultArticle(
            id=f"info_not_found_{identifier}",
            title="Пользователь не найден",
            description=f"Пользователь '{identifier}' не найден в базе данных бота.",
            input_message_content=InputTextMessageContent(
                message_text=f"❌ Пользователь <code>{html.quote(identifier)}</code> не найден в базе данных бота.",
                parse_mode="HTML"))
        await inline_query.answer([result], is_personal=True, cache_time=5)
        return

    # --- Сбор информации о пользователе ---
    user_id = user_data['tg_user_id']
    full_name = html.quote(user_data.get('full_name', 'Имя не указано'))
    username = user_data.get('username')
    reg_date_obj = user_data.get('registered_at')
    reg_date_str = reg_date_obj.strftime('%d.%m.%Y в %H:%M') if isinstance(
        reg_date_obj, datetime.datetime) else "Неизвестно"

    # Статус пользователя (от себя)
    user_status_icon = "👤"
    if user_id in get_all_admins():
        user_status_icon = "👑"
    if await db.is_user_banned(user_id):
        user_status_icon = "🚫"

    user_info_text = (
        f"{user_status_icon} <b>Информация о пользователе</b>\n\n"
        f"<b>Ник:</b> {hlink(full_name, f'tg://user?id={user_id}')}\n"
        f"<b>Юзернейм:</b> @{html.quote(username)}\n"
        f"<b>ID:</b> <code>{user_id}</code>\n"
        f"<b>Дата регистрации:</b> {reg_date_str}"
    )

    # --- Сбор информации о юзерботе (если есть) ---
    userbot_info_text = ""
    user_bots = await db.get_userbots_by_tg_id(user_id)
    if user_bots:
        ub = user_bots[0]
        ub_username = ub.get('ub_username')
        server_ip = ub.get('server_ip')

        # is_active = await
        # sm.is_service_active(f"hikka-{ub_username}.service", server_ip)
        is_active = False
        status_text = "🟢 Включен" if is_active else "🔴 Выключен"

        uptime_str = "N/A"
        if is_active:
            # uptime_raw = await sm.get_service_process_uptime(f"hikka-{ub_username}.service", server_ip)
            # if uptime_raw:
            #     uptime_str = sm.parse_ps_etime_to_human(uptime_raw)
            uptime_str = "N/A"

        ub_created_obj = ub.get('created_at')
        ub_created_str = ub_created_obj.strftime('%d.%m.%Y в %H:%M') if isinstance(
            ub_created_obj, datetime.datetime) else "Неизвестно"

        # Дополнительная информация (от себя)
        server_details = server_config.get_servers().get(server_ip, {})
        server_display = f"{server_details.get('flag', '🏳️')} {server_details.get('code', 'N/A')}"
        # resources = await sm.get_userbot_resource_usage(ub_username,
        # server_ip)
        resources = {"cpu": "0", "ram_used": "0"}

        userbot_info_text = (
            f"\n\n🤖 <b>Информация о юзерботе</b>\n\n"
            f"<b>Статус:</b> {status_text}\n"
            f"<b>Аптайм:</b> {uptime_str}\n"
            f"<b>Дата создания:</b> {ub_created_str}\n"
            f"<b>Сервер:</b> {server_display}\n"
            f"<b>CPU / RAM:</b> {resources.get('cpu', '0')}% / {resources.get('ram_used', '0')}MB")

    full_text = user_info_text + userbot_info_text

    result = InlineQueryResultArticle(
        id=f"info_{user_id}",
        title=f"Информация о {full_name}",
        description=f"@{username}" if username else f"ID: {user_id}",
        input_message_content=InputTextMessageContent(
            message_text=full_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    )

    await inline_query.answer([result], is_personal=True, cache_time=10)


@router.inline_query(F.query == "servinfo", IsSuperAdmin())
async def inline_servinfo_handler(inline_query: InlineQuery):
    servers = server_config.get_servers()
    # tasks = [sm.get_server_stats(ip) for ip in servers.keys()]
    tasks = [asyncio.create_task(asyncio.sleep(0)) for ip in servers.keys()]
    stats_results = await asyncio.gather(*tasks)
    stats_map = dict(zip(servers.keys(), stats_results))

    info_text = await _get_full_server_info_text(stats_map, servers)

    result = InlineQueryResultArticle(
        id="servinfo_panel",
        title="🖥️ Статистика по серверам",
        description="Показать актуальную информацию о состоянии всех серверов.",
        input_message_content=InputTextMessageContent(
            message_text=info_text,
            parse_mode="HTML"),
        reply_markup=kb.get_server_info_keyboard())
    await inline_query.answer([result], is_personal=True, cache_time=10)


@router.inline_query(F.query.startswith("exec"))
async def inline_exec_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    user_bots = await db.get_userbots_by_tg_id(user_id)

    if not user_bots:
        result = InlineQueryResultArticle(
            id=str(user_id),
            title="Ошибка",
            description="У вас нет юзербота для выполнения команд.",
            input_message_content=InputTextMessageContent(
                message_text="❌ <b>У вас нет юзербота.</b>",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    the_only_bot = user_bots[0]
    ub_username = the_only_bot['ub_username']
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data or ub_data.get('tg_user_id') != user_id:
        result = InlineQueryResultArticle(
            id=str(user_id),
            title="Ошибка",
            description="Только владелец может использовать терминал.",
            input_message_content=InputTextMessageContent(
                message_text="❌ <b>Только владелец может использовать терминал.</b>",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    # Проверка статуса юзербота - терминал недоступен во время установки или
    # удаления
    if ub_data.get('status') == 'installing':
        result = InlineQueryResultArticle(
            id=str(user_id),
            title="⏳ Установка в процессе",
            description="Терминал будет доступен после завершения установки",
            input_message_content=InputTextMessageContent(
                message_text="⏳ <b>Установка юзербота в процессе...</b>\n\nТерминал будет доступен после завершения установки и настройки всех систем безопасности.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    if ub_data.get('status') == 'deleting':
        result = InlineQueryResultArticle(
            id=str(user_id),
            title="🗑️ Удаление в процессе",
            description="Терминал недоступен во время удаления",
            input_message_content=InputTextMessageContent(
                message_text="🗑️ <b>Удаление юзербота в процессе...</b>\n\nТерминал недоступен во время удаления юзербота.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    command_str = inline_query.query[len("exec"):].strip()

    if not command_str:
        result = InlineQueryResultArticle(
            id=str(user_id),
            title="Введите команду",
            description="Напишите команду, которую хотите выполнить на сервере.",
            input_message_content=InputTextMessageContent(
                message_text="ℹ️ Введите команду после `exec ` для выполнения на сервере."))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    server_ip = the_only_bot['server_ip']
    system_user = the_only_bot['ub_username']

    # res = await sm.run_command_async(command_str, server_ip, timeout=60,
    # user=system_user)
    res = {"success": True, "output": "Command executed successfully"}

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

    available_space = TELEGRAM_MSG_LIMIT - \
        len(header) - len(content_prefix) - len(content_suffix)

    if len(full_content) > available_space:
        truncated_content = full_content[:available_space -
                                         15] + "\n[...обрезано]"
    else:
        truncated_content = full_content

    if full_content.strip() and not full_content.startswith("\n<i>"):
        response_text = header + content_prefix + truncated_content + content_suffix
    else:
        response_text = header + truncated_content

    result = InlineQueryResultArticle(
        id=str(user_id),
        title=f"Выполнить: {command_str[:50]}...",
        description="Результат выполнения команды",
        input_message_content=InputTextMessageContent(
            message_text=response_text,
            parse_mode="HTML"))

    try:
        await inline_query.answer([result], cache_time=1, is_personal=True)
    except TelegramBadRequest as e:
        if "query is too old" in str(e) or "query ID is invalid" in str(e):
            # Не логируем, просто игнорируем устаревший запрос
            return
        else:
            raise


@router.inline_query(F.query.startswith("action"))
async def inline_action_handler(inline_query: InlineQuery, bot: Bot):
    user_id = inline_query.from_user.id
    user_bots = await db.get_userbots_by_tg_id(user_id)

    if not user_bots:
        await inline_query.answer([], cache_time=10)
        return

    the_only_bot = user_bots[0]
    ub_username = the_only_bot['ub_username']
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data or ub_data.get('tg_user_id') != user_id:
        await inline_query.answer([], cache_time=1)
        return

    # Проверка статуса юзербота - действия недоступны во время установки или
    # удаления
    if ub_data.get('status') == 'installing':
        result = InlineQueryResultArticle(
            id=f"action_installing",
            title="⏳ Установка в процессе",
            description="Действия будут доступны после завершения установки",
            input_message_content=InputTextMessageContent(
                message_text="⏳ <b>Установка юзербота в процессе...</b>\n\nДействия будут доступны после завершения установки и настройки всех систем безопасности.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    if ub_data.get('status') == 'deleting':
        result = InlineQueryResultArticle(
            id=f"action_deleting",
            title="🗑️ Удаление в процессе",
            description="Действия недоступны во время удаления",
            input_message_content=InputTextMessageContent(
                message_text="🗑️ <b>Удаление юзербота в процессе...</b>\n\nДействия недоступны во время удаления юзербота.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    is_server_active = server_config.get_server_status_by_ip(
        the_only_bot['server_ip']) not in ["false", "not_found"]
    if not is_server_active:
        await inline_query.answer([], cache_time=10)
        return

    is_running = the_only_bot.get('status') == 'running'

    logging.info(
        f"Inline action check for {ub_username}: service is_running = {is_running} (from DB)")

    all_possible_actions = {
        "start": {
            "title": "🚀 Включить", "description": f"Запустить {ub_username}"}, "stop": {
            "title": "🔴 Выключить", "description": f"Остановить {ub_username}"}, "restart": {
                "title": "🔄 Перезагрузить", "description": f"Перезапустить {ub_username}"}}

    available_actions = []
    if is_running:
        available_actions.extend(["stop", "restart"])
    else:
        available_actions.append("start")

    user_arg = inline_query.query[len("action"):].strip().lower()

    actions_to_show = []
    if not user_arg:
        actions_to_show = available_actions
    else:
        for act_name in available_actions:
            if act_name.startswith(user_arg):
                actions_to_show.append(act_name)

    if not actions_to_show:
        await inline_query.answer([], cache_time=1)
        return

        # tasks = {action: sm.manage_ub_service(ub_username, action, the_only_bot['server_ip']) for action in actions_to_show}
        tasks = {
            action: asyncio.create_task(
                asyncio.sleep(0)) for action in actions_to_show}
    task_results = await asyncio.gather(*tasks.values())

    results = []
    for (action, res) in zip(tasks.keys(), task_results):
        item = all_possible_actions[action]

        error_msg = res.get('message', 'Неизвестная ошибка')
        header = f"❌ <b>Ошибка!</b> (<code>{action}</code>)\n"
        content_prefix = "<pre>"
        content_suffix = "</pre>"
        TELEGRAM_MSG_LIMIT = 4096
        available_space = TELEGRAM_MSG_LIMIT - \
            len(header) - len(content_prefix) - len(content_suffix)
        truncated_error = html.quote(error_msg[:available_space])

        if res.get("success"):
            message_text = f"✅ <b>Выполнено!</b> (<code>{action}</code>)"
        else:
            message_text = header + content_prefix + truncated_error + content_suffix

        results.append(
            InlineQueryResultArticle(
                id=f"action_{action}",
                title=item['title'],
                description=item['description'],
                input_message_content=InputTextMessageContent(
                    message_text=message_text,
                    parse_mode="HTML"
                )
            )
        )

    await inline_query.answer(results, is_personal=True, cache_time=1)


@router.inline_query(F.query == "menu")
async def inline_menu_handler(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    user_bots = await db.get_userbots_by_tg_id(user_id)

    if not user_bots:
        await inline_query.answer([], cache_time=10)
        return

    the_only_bot = user_bots[0]
    ub_username = the_only_bot['ub_username']
    server_ip = the_only_bot['server_ip']

    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await inline_query.answer([], cache_time=10)
        return

    # Проверка статуса юзербота - меню недоступно во время установки или
    # удаления
    if ub_data.get('status') == 'installing':
        result = InlineQueryResultArticle(
            id="menu_installing",
            title="⏳ Установка в процессе",
            description="Меню будет доступно после завершения установки",
            input_message_content=InputTextMessageContent(
                message_text="⏳ <b>Установка юзербота в процессе...</b>\n\nМеню управления будет доступно после завершения установки и настройки всех систем безопасности.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    if ub_data.get('status') == 'deleting':
        result = InlineQueryResultArticle(
            id="menu_deleting",
            title="🗑️ Удаление в процессе",
            description="Меню недоступно во время удаления",
            input_message_content=InputTextMessageContent(
                message_text="🗑️ <b>Удаление юзербота в процессе...</b>\n\nМеню управления недоступно во время удаления юзербота.",
                parse_mode="HTML"))
        await inline_query.answer([result], cache_time=1, is_personal=True)
        return

    is_server_active_str = server_config.get_server_status_by_ip(server_ip)
    is_server_active = is_server_active_str not in ["false", "not_found"]

    # is_running = await sm.is_service_active(f"hikka-{ub_username}.service",
    # server_ip) if is_server_active else False
    is_running = False

    server_details = server_config.get_servers().get(server_ip, {})
    flag = server_details.get("flag", "🏳️")
    server_code = server_details.get("code", "N/A")
    server_display = f"{flag} {server_code}"

    # ping_ms = await sm.get_server_ping(server_ip)
    # resources = await sm.get_userbot_resource_usage(ub_username, server_ip)
    ping_ms = 0
    resources = {"cpu": "0", "ram_used": "0"}

    if not is_server_active:
        status_text = "⚪️ Сервер отключен"
    elif is_running:
        status_text = "🟢 Включено"
    else:
        status_text = "🔴 Выключено"

    caption_text = (
        f"<b>🎛 Панель управления</b>\n\n"
        f"<blockquote>"
        f"🆔 ID: {user_id}\n\n"
        f"💻 Статус: {status_text}\n\n"
        f"🤖 Юзербот: {ub_data.get('ub_type', 'N/A').capitalize()}\n\n"
        f"🖥 Сервер: {server_display}\n\n"
        f"⏱ Пинг: {ping_ms}ms\n\n"
        f"💾 CPU: {resources['cpu']}%\n\n"
        f"⚙️ RAM: {resources['ram_used']} MB / {resources['ram_limit']} MB {resources['ram_percent']}%"
        f"</blockquote>")

    markup = kb.get_management_keyboard(
        is_running=is_running,
        ub_username=ub_username,
        ub_type=ub_data.get('ub_type', 'N/A'),
        is_server_active=is_server_active,
        is_inline=True,
        inline_message_id=inline_query.id,
        is_installing=(ub_data.get('status') == 'installing'),
        is_deleting=(ub_data.get('status') == 'deleting')
    )

    result = InlineQueryResultPhoto(
        id="control_panel",
        photo_url="https://envs.sh/FSU.jpg",
        thumbnail_url="https://envs.sh/FSU.jpg",
        title="⚙️ Панель управления",
        description=f"Открыть меню для {ub_username}",
        caption=caption_text,
        parse_mode="HTML",
        reply_markup=markup
    )

    await inline_query.answer([result], is_personal=True, cache_time=1)


@router.inline_query(F.query == "")
async def inline_photo_handler(inline_query: InlineQuery):
    photo_url = "https://i.postimg.cc/1545FdLV/IMG-20250704-171839-255.jpg"
    thumb_url = "https://i.postimg.cc/1545FdLV/IMG-20250704-171839-255.jpg"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="WebApp Panel",
                    url="https://host.ekey.space/"
                )
            ]
        ]
    )

    result = InlineQueryResultPhoto(
        id="1",
        photo_url=photo_url,
        thumbnail_url=thumb_url,
        reply_markup=keyboard
    )

    await inline_query.answer(
        results=[result],
        cache_time=0,
        is_personal=True
    )
# --- END OF FILE inline_handlers.py ---
