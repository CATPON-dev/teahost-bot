# --- START OF FILE admin_handlers.py ---
import aiohttp
import math
import logging
import json
import os
import uuid
import sys
import asyncio
import subprocess
import time
import asyncssh
from datetime import datetime, date, timedelta
from html import escape
import uuid
from io import BytesIO
import shlex
import re
import secrets
import shutil
import pytz

from aiogram import Router, types, Bot, F, html
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, BufferedInputFile, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
import system_manager as sm
import server_config
import keyboards as kb
import ban_manager
import session_checker
from filters import IsAdmin, IsSuperAdmin
from broadcaster import broadcast_message
from admin_manager import get_admin_ids, get_all_admins, add_admin, remove_admin
from config_manager import config
from constants import RESTART_INFO_FILE
from states import AdminTasks, AdminUserBotTransfer
from middlewares.error_handler import handle_error_page_callback
from middlewares import techwork as maintenance_manager
from channel_logger import log_to_channel, log_event


router = Router()

SESSION_CHECK_CACHE = {}
CACHE_TTL = 300
LOG_LINES_PER_PAGE = 25
ACTIVE_STATUS_LAST_REFRESH = 0

@router.message(F.text.regexp(r'^\/.*'), ~IsAdmin())
async def unauthorized_admin_command_attempt(message: types.Message, bot: Bot):
    user_info = f"{message.from_user.full_name} (@{message.from_user.username}, <code>{message.from_user.id}</code>)"
    log_text = (
        f"⚠️ <b>Попытка несанкционированного доступа</b>\n\n"
        f"<b>Пользователь:</b> {user_info}\n"
        f"<b>Команда:</b> <code>{html.quote(message.text)}</code>"
    )
    await log_to_channel(bot, log_text)
    await message.reply("⛔️ У вас нет прав для использования этой команды.")

router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

router.callback_query.register(handle_error_page_callback, F.data.startswith("error_page:"))

TERMINAL_OUTPUT_CACHE = {}
TERMINAL_SESSIONS_ACTIVE = {}
MAX_CACHE_SIZE = 100
ACTIVE_PANEL_UPDATE_TASKS = {}


async def _get_geo_info(ip: str):
    fields = "status,message,country,regionName,city,org,timezone,hosting,query,countryCode,proxy,vpn"
    url = f"http://ip-api.com/json/{ip}?fields={fields}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        return data
                return None
    except Exception:
        return None

def _country_code_to_flag(code: str) -> str:
    if not code or len(code) != 2:
        return "🏳️"
    return "".join(chr(ord(char) + 127397) for char in code.upper())

@router.message(Command("obs"), IsSuperAdmin())
async def cmd_obs_all_servers(message: types.Message, bot: Bot):
    servers_to_service = {ip: details for ip, details in server_config.get_servers().items() if ip != sm.LOCAL_IP}
    
    # Устанавливаем zip на все сервера перед обслуживанием
    install_results = []
    for ip in servers_to_service:
        res = await sm.run_command_async("sudo apt-get update -qq && sudo apt-get install -y zip", ip, check_output=False)
        if res.get("success"):
            install_results.append(f"✅ zip установлен на {ip}")
        else:
            install_results.append(f"❌ Ошибка установки zip на {ip}: {res.get('error','')}")
    if install_results:
        await message.reply("\n".join(install_results))
    
    if not servers_to_service:
        await message.reply("Список удаленных серверов пуст. Нечего обслуживать.")
        return

    ips_to_process = list(servers_to_service.keys())
    msg = await message.reply(f"🚀 <b>Запускаю параллельное обслуживание для {len(ips_to_process)} серверов...</b>\n\nЭто может занять много времени. Вы получите итоговый отчет по завершении.")

    # Исправляем права доступа для существующих пользователей
    ### fix_tasks = [sm.fix_existing_users_tmp_access(ip) for ip in ips_to_process]
    ### await asyncio.gather(*fix_tasks)
    
    tasks = [sm.service_and_prepare_server(ip) for ip in ips_to_process]
    
    results = await asyncio.gather(*tasks)
    
    all_successful = True
    report_lines = []

    for ip, success in zip(ips_to_process, results):
        server_details = servers_to_service.get(ip, {})
        flag = server_details.get("flag", "🏳️")
        name = server_details.get("name", "Unknown")
        
        if success:
            status_icon = "✅"
            status_text = "Успешно"
        else:
            status_icon = "❌"
            status_text = "Ошибка"
            all_successful = False
        
        report_lines.append(f"{status_icon} <b>{flag} {html.quote(name)}</b> (<code>{ip}</code>): {status_text}")

    summary_text = "✅ <b>Обслуживание всех серверов успешно завершено.</b>"
    if not all_successful:
        summary_text = "⚠️ <b>Обслуживание завершено, но на некоторых серверах возникли ошибки.</b>"

    final_report = f"{summary_text}\n\n" + "\n".join(report_lines)
    
    await msg.edit_text(final_report)

def get_terminal_paginator(output_id: str, page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="‹ Назад", callback_data=f"term_page:{output_id}:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ›", callback_data=f"term_page:{output_id}:{page+1}"))
    
    builder.row(*nav_buttons)
    return builder.as_markup()

@router.callback_query(F.data.startswith("term_page:"))
async def terminal_page_callback(call: types.CallbackQuery):
    try:
        _, output_id, page_str = call.data.split(":")
        page = int(page_str)
    except (ValueError, IndexError):
        await call.answer("Ошибка данных пагинации.", show_alert=True)
        return

    cached_data = TERMINAL_OUTPUT_CACHE.get(output_id)
    if not cached_data:
        await call.answer("Данные этого вывода устарели и были удалены из кэша.", show_alert=True)
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n<i>(Данные устарели)</i>", reply_markup=None)
        except TelegramBadRequest:
            pass
        return

    header, raw_chunks = cached_data
    total_pages = len(raw_chunks)

    if not (0 <= page < total_pages):
        await call.answer("Запрошенная страница не существует.", show_alert=True)
        return

    page_content = raw_chunks[page]
    
    new_text = f"{header}\n\n<blockquote>{html.quote(page_content)}</blockquote>"
    markup = get_terminal_paginator(output_id, page, total_pages)
    
    try:
        await call.message.edit_text(
            new_text, 
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Error editing terminal page: {e}")
    finally:
        await call.answer()

def find_ip_by_code(code: str) -> str | None:
    servers = server_config.get_servers()
    for ip, details in servers.items():
        if details.get("code") and details.get("code").lower() == code.lower():
            return ip
    return None

@router.message(Command("terminal"), IsSuperAdmin())
async def cmd_terminal(message: types.Message, command: CommandObject):
    if not command.args:
        servers = server_config.get_servers()
        codes = [details.get("code") for details in servers.values() if details.get("code")]
        codes_str = ", ".join(f"<code>{c}</code>" for c in codes)
        help_text = (
            "<b>🖥️ Терминал — выполнение команд на серверах</b>\n\n"
            "<b>Формат использования:</b>\n\n"
            "🔹 <b>Локально:</b>\n"
            "   <code>/terminal [команда]</code>\n"
            "   <i>(Выполняет команду на сервере, где запущен бот)</i>\n\n"
            "🔹 <b>На одном сервере:</b>\n"
            "   <code>/terminal [код] [команда]</code>\n"
            "   <i>(Пример: <code>/terminal M1 ls -l</code>)</i>\n\n"
            "🔹 <b>На всех серверах:</b>\n"
            "   <code>/terminal all [команда]</code>\n"
            "   <i>(Выполняет команду на всех удаленных хостах)</i>\n\n"
            f"<b>Доступные коды серверов:</b> {codes_str}"
        )
        await message.reply(help_text)
        return

    args = command.args.split(maxsplit=1)
    
    if args[0].lower() == 'all':
        if len(args) < 2:
            await message.reply("<b>Ошибка:</b> Не указана команда для выполнения.\nИспользование: <code>/terminal all [команда]</code>")
            return

        cmd_str = args[1]
        msg = await message.reply(f"⏳ Выполняю <code>{html.quote(cmd_str)}</code> на всех удаленных серверах...")
        
        servers = server_config.get_servers()
        remote_servers = {ip: details for ip, details in servers.items() if ip != sm.LOCAL_IP}

        if not remote_servers:
            await msg.edit_text("❌ Нет настроенных удаленных серверов для выполнения команды.")
            return

        tasks = [sm.run_command_async(cmd_str, ip) for ip in remote_servers.keys()]
        results = await asyncio.gather(*tasks)

        report_lines = [f"<b>🚀 Пакетное выполнение команды:</b>\n<pre><code>{html.quote(cmd_str)}</code></pre>\n"]
        success_count = 0
        fail_count = 0

        for server_details, result in zip(remote_servers.values(), results):
            flag = server_details.get("flag", "🏳️")
            name = server_details.get("name", "Unknown")
            code = server_details.get("code", "N/A")
            
            server_report_part = f"\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n<b>{flag} {name} ({code})</b>"

            if result.get("success"):
                success_count += 1
                server_report_part += "\nСтатус: ✅ Успешно"
                output_message = html.quote(result.get('output', '')).strip()
                if output_message:
                    server_report_part += f"\n<pre><code>{output_message}</code></pre>"
                else:
                    server_report_part += "\n<i>(нет вывода)</i>"
            else:
                fail_count += 1
                exit_code = result.get('exit_status', 'N/A')
                server_report_part += f"\nСтатус: ❌ Ошибка (Код выхода: {exit_code})"
                error_message = html.quote(result.get('error') or "Нет текста ошибки.")
                server_report_part += f"\n<pre><code>{error_message}</code></pre>"
            
            report_lines.append(server_report_part)
        
        summary = f"\n\n<b>Итог: {success_count} ✅ | {fail_count} ❌</b>"
        final_report = "".join(report_lines) + summary
        
        if len(final_report) > 4096:
            report_file = BufferedInputFile(final_report.encode('utf-8'), filename="terminal_all_report.html")
            await msg.delete()
            await message.answer_document(report_file, caption="Отчет о выполнении команды на всех серверах.")
        else:
            await msg.edit_text(final_report)
        return

    target_ip = None
    cmd_str = ""

    potential_code = args[0]
    ip_from_code = find_ip_by_code(potential_code)

    if len(args) == 2 and ip_from_code:
        target_ip = ip_from_code
        cmd_str = args[1]
    else:
        target_ip = sm.LOCAL_IP
        cmd_str = command.args

    msg = await message.reply(f"⏳ Выполняю команду на <code>{target_ip}</code>...")
    res = await sm.run_command_async(cmd_str, target_ip, timeout=600)
    
    output = res.get('output', '')
    error = res.get('error', '')
    exit_code = res.get('exit_status', 'N/A')

    header = (
        f"<b>⌨️ Системная команда <code>{html.quote(cmd_str)}</code></b>\n"
        f"<i>Код выхода: {exit_code}</i>"
    )
    
    content_parts = []
    if output:
        content_parts.append(f"📼 Stdout:\n<blockquote>{html.quote(output)}</blockquote>")
    if error:
        content_parts.append(f"📼 Stderr:\n<blockquote>{html.quote(error)}</blockquote>")
    
    if content_parts:
        full_text = f"{header}\n\n" + "\n\n".join(content_parts)
    else:
        full_text = f"{header}\n\n<i>(Нет вывода)</i>"

    if len(full_text) > 4096:
        await msg.delete()
        output_id = uuid.uuid4().hex
        
        raw_output_content = []
        if output:
            raw_output_content.append(f"📼 Stdout:\n{output}")
        if error:
            raw_output_content.append(f"\n📼 Stderr:\n{error}")
        
        raw_content_to_paginate = "\n".join(raw_output_content)

        available_space = 4096 - len(header) - len("<blockquote></blockquote>") - 20
        
        chunks = [raw_content_to_paginate[i:i + available_space] for i in range(0, len(raw_content_to_paginate), available_space)]
        
        if len(TERMINAL_OUTPUT_CACHE) >= MAX_CACHE_SIZE:
            TERMINAL_OUTPUT_CACHE.pop(next(iter(TERMINAL_OUTPUT_CACHE)))
        
        TERMINAL_OUTPUT_CACHE[output_id] = (header, chunks)
        
        text_to_send = f"{header}\n\n<blockquote>{html.quote(chunks[0])}</blockquote>"
        markup = get_terminal_paginator(output_id, 0, len(chunks))
        
        await message.answer(
            text_to_send, 
            reply_markup=markup,
            disable_web_page_preview=True
        )
    else:
        await msg.edit_text(
            full_text,
            disable_web_page_preview=True
        )

@router.message(Command("serv"), IsSuperAdmin())
async def cmd_serv_manager(message: types.Message, command: CommandObject, bot: Bot):
    if not command.args:
        await message.reply("Недостаточно аргументов. Используйте <code>/serv help</code> для справки.")
        return

    args = command.args.split()
    action = args[0].lower()
    admin_data = {"id": message.from_user.id, "full_name": message.from_user.full_name}
    servers = server_config.get_servers()

    if action == "help":
        help_text = (
            "<b>⚙️ Команды управления серверами:</b>\n\n"
            "<code>/serv list</code>\n"
            "<i>Показывает список всех серверов с их кодами.</i>\n\n"
            "<code>/serv add [IP] [user] [pass]</code>\n"
            "<i>Добавляет новый сервер.</i>\n\n"
            "<code>/serv del [код]</code>\n"
            "<i>Удаляет сервер из конфигурации.</i>\n\n"
            "<b>Команды для конкретного сервера:</b>\n"
            "<code>/serv [код] neofetch</code>\n"
            "<i>Показывает красивую сводку о системе.</i>\n\n"
            "<code>/serv [код] status [статус]</code>\n"
            "<i>Статусы: <code>true</code>, <code>false</code>, <code>noub</code>, <code>test</code>.</i>\n\n"
            "<code>/serv [код] setslot [число]</code>\n"
            "<i>Устанавливает лимит слотов.</i>\n\n"
            "<code>/serv [код] ubs [действие]</code>\n"
            "<i>Массовое управление юзерботами (<code>start</code>, <code>stop</code>, <code>restart</code>).</i>\n\n"
            "<code>/serv [код] reboot</code>\n"
            "<i>Безопасная перезагрузка сервера.</i>"
        )
        await message.reply(help_text)
        return

    if action == "list":
        if not servers:
            await message.reply("Список серверов пуст.")
            return
        
        text_parts = ["<b>📋 Список настроенных серверов:</b>\n"]
        for i, (ip, details) in enumerate(servers.items(), 1):
            country = details.get('country', 'N/A')
            city = details.get('city', 'N/A')
            name = details.get('name', 'N/A')
            code = details.get('code', 'N/A')
            text_parts.append(f"{i}. <code>{ip}</code> (<b>код:</b> <code>{code}</code>) - {name}, {country}, {city}")
        await message.reply("\n".join(text_parts))
        return

    if action == "add":
        if len(args) != 4:
            await message.reply(f"Использование: <code>/serv add [IP] [user] [password]</code>")
            return
        
        _, ip, user, password = args
        if ip in servers:
            await message.reply(f"❌ Сервер <code>{ip}</code> уже существует.")
            return

        msg = await message.reply(f"⏳ Проверяю SSH-соединение с <code>{ip}</code>...")
        
        temp_servers_to_test = servers.copy()
        temp_servers_to_test[ip] = {"ssh_user": user, "ssh_pass": password}
        server_config._save_servers(temp_servers_to_test)
        
        test_res = await sm.run_command_async("echo 'connection_ok'", ip)
        
        server_config._save_servers(servers)

        if not test_res.get("success"):
            await msg.edit_text(f"❌ <b>Ошибка подключения:</b>\n<pre>{html.quote(test_res.get('error', 'Неизвестная ошибка'))}</pre>")
            return
            
        await msg.edit_text(f"✅ Соединение успешно. Получаю информацию о сервере...")

        max_num = sum(1 for s in servers.values() if s.get('name', '').startswith('serv'))
        new_name = f"serv{max_num + 1}"
        geo_info = await _get_geo_info(ip)
        details = { "name": new_name }

        if geo_info:
            details.update({
                "country": geo_info.get("country", "Unknown"), "city": geo_info.get("city", "Unknown"),
                "regionName": geo_info.get("regionName", "N/A"), "flag": _country_code_to_flag(geo_info.get("countryCode", "")),
                "org": geo_info.get("org", "N/A"), "timezone": geo_info.get("timezone", "N/A"),
                "hosting": geo_info.get("hosting", False), "proxy": geo_info.get("proxy", False), "vpn": geo_info.get("vpn", False),
            })
            city_char = details["city"][0].upper() if details["city"] != "Unknown" and details["city"] else "S"
            count = sum(1 for s in servers.values() if s.get('code', '').startswith(city_char))
            details["code"] = f"{city_char}{count + 1}"

        new_password = await sm.add_server_with_security(ip, user, password, details)
        if isinstance(new_password, str) and new_password:
            await msg.edit_text(f"✅ Сервер <b>{new_name}</b> (<code>{ip}</code>) успешно добавлен.\n\n"
                              "⏳ <b>Начинаю автоматическое обслуживание...</b> Это может занять несколько минут.")
            # --- Смена hostname без перезагрузки ---
            await msg.reply("⏳ Меняю hostname на 'sharkhost'...")
            set_hostname_res = await sm.run_command_async("sudo hostnamectl set-hostname sharkhost", ip, ssh_pass=new_password)
            if set_hostname_res.get("success"):
                await msg.reply("✅ Hostname успешно изменён на 'sharkhost'.")
            else:
                await msg.reply(f"⚠️ Не удалось изменить hostname.\n<pre>{set_hostname_res.get('error','')}</pre>")
            asyncio.create_task(sm.service_and_prepare_server(ip, bot, message.chat.id, ssh_pass=new_password))
        else:
            await msg.edit_text(f"❌ Не удалось добавить сервер <code>{ip}</code>.")
        return

    if action == "del":
        if len(args) != 2:
            await message.reply("Использование: <code>/serv del [код]</code>")
            return
        server_code_to_del = args[1]
        ip_to_del = find_ip_by_code(server_code_to_del)
        if not ip_to_del:
            await message.reply(f"❌ Сервер с кодом <code>{html.quote(server_code_to_del)}</code> не найден.")
            return
        if server_config.delete_server(ip_to_del):
            await message.reply(f"✅ Сервер <code>{ip_to_del}</code> (код {server_code_to_del}) удален.")
        else:
            await message.reply(f"❌ Не удалось удалить сервер <code>{ip_to_del}</code> из конфигурации.")
        return
        
    if len(args) < 2 and len(args) != 1:
        await message.reply("Неверный формат команды. Используйте <code>/serv help</code>.")
        return

    server_code = args[0]
    target_ip = find_ip_by_code(server_code)
    
    if not target_ip:
        await message.reply(f"Сервер с кодом <code>{server_code}</code> не найден. Используйте <code>/serv list</code>.")
        return

    sub_action = args[1].lower() if len(args) > 1 else 'neofetch'

    if sub_action == "neofetch":
        msg = await message.reply(f"⏳ Получаю системную сводку с сервера {server_code}...")
        res = await sm.run_command_async("neofetch --stdout", target_ip)
        if res.get("success"):
            await msg.edit_text(f"<b>Системная сводка для {server_code}:</b>\n<pre>{html.quote(res['output'])}</pre>")
        else:
            await msg.edit_text(f"❌ Не удалось выполнить neofetch: <pre>{html.quote(res.get('error', '...'))}</pre>")
        return

    if sub_action == "ubs":
        if len(args) != 3:
            await message.reply("Использование: <code>/serv [код] ubs [start|stop|restart]</code>")
            return
        ub_action = args[2].lower()
        if ub_action not in ["start", "stop", "restart"]:
            await message.reply("Неверное действие. Доступно: start, stop, restart.")
            return
        
        userbots = await db.get_userbots_by_server_ip(target_ip)
        if not userbots:
            await message.reply(f"На сервере <code>{target_ip}</code> нет юзерботов.")
            return

        msg = await message.reply(f"⏳ Выполняю '<b>{ub_action}</b>' для {len(userbots)} юзерботов на сервере <code>{target_ip}</code>...")
        tasks = [sm.manage_ub_service(ub['ub_username'], ub_action, target_ip) for ub in userbots]
        results = await asyncio.gather(*tasks)
        report = [f"<b>Отчет для <code>{target_ip}</code> ({server_code}):</b>"]
        for ub, res in zip(userbots, results):
            status = "✅" if res["success"] else "❌"
            report.append(f" {status} <code>{ub['ub_username']}</code>")
        await msg.edit_text("\n".join(report))

    elif sub_action == "reboot":
        await message.reply(f"⚠️ Вы уверены, что хотите перезагрузить сервер <code>{target_ip}</code> ({server_code})?",
            reply_markup=kb.get_confirm_reboot_keyboard(target_ip))

    elif sub_action == "setslot":
        if len(args) != 3:
            await message.reply(f"Использование: <code>/serv [код] setslot [число]</code>")
            return
        try:
            slots = int(args[2])
            if slots < 0: raise ValueError
            if server_config.update_server_slots(target_ip, slots):
                await message.reply(f"✅ Для сервера <code>{server_code}</code> установлено <b>{slots}</b> слотов.")
                log_data = { "admin_data": admin_data, "server_info": {"ip": target_ip, "code": server_code}, "details": f"установлено новое количество слотов: {slots}" }
                await log_event(bot, "server_settings_changed", log_data)
            else:
                await message.reply("❌ Не удалось обновить количество слотов.")
        except ValueError:
            await message.reply("Количество слотов должно быть целым неотрицательным числом.")
   
    elif sub_action == "auth":
        if len(args) != 3:
            await message.reply("Использование: <code>/serv [код] auth [auto|port]</code>")
            return
        auth_mode = args[2].lower()
        if auth_mode not in ["auto", "port"]:
            await message.reply("Неверный режим. Доступные: <code>auto</code>, <code>port</code>.")
            return

        if server_config.update_server_auth_mode(target_ip, auth_mode):
            mode_description = "поиск ссылки в логах" if auth_mode == "auto" else "статический порт для WebUI"
            await message.reply(f"✅ Режим авторизации для сервера <code>{server_code}</code> изменен на <b>{auth_mode}</b> ({mode_description}).")
            log_data = { "admin_data": admin_data, "server_info": {"ip": target_ip, "code": server_code}, "details": f"режим авторизации изменен на '{auth_mode}'" }
            await log_event(bot, "server_settings_changed", log_data)
        else:
            await message.reply("❌ Не удалось обновить режим авторизации.")
    
    elif sub_action == "status":
        if len(args) != 3:
            await message.reply("Использование: <code>/serv [код] status [true|false|noub|test]</code>")
            return
        status_value = args[2].lower()
        if status_value not in ["true", "false", "noub", "test"]:
            await message.reply("Неверный статус. Доступные: true, false, noub, test.")
            return
        if server_config.update_server_status(target_ip, status_value):
            await message.reply(f"✅ Статус сервера <code>{server_code}</code> изменен на <b>{status_value}</b>.")
            log_data = { "admin_data": admin_data, "server_info": {"ip": target_ip, "code": server_code}, "details": f"статус изменен на '{status_value}'" }
            await log_event(bot, "server_settings_changed", log_data)
            if status_value == "false":
                userbots = await db.get_userbots_by_server_ip(target_ip)
                tasks = [sm.manage_ub_service(ub['ub_username'], 'stop', target_ip) for ub in userbots]
                for task in tasks:
                    asyncio.create_task(task)
        else:
            await message.reply("❌ Не удалось обновить статус сервера.")
    else:
        await message.reply(f"Неизвестное действие '<code>{sub_action}</code>'. Используйте <code>/serv help</code>.")
        
def create_progress_bar(percent_str: str, length: int = 10) -> str:
    try:
        percent = float(str(percent_str).replace('%',''))
        filled_length = int(length * percent / 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}] {percent:.1f}%"
    except (ValueError, TypeError):
        return f"[{'?' * length}] N/A"

async def _get_full_server_info_text(stats_map, servers_to_display: list):
    text_parts = ["🖥️ <b>Статистика по серверам:</b>\n"]

    for ip, details in servers_to_display:
        stats = stats_map.get(ip, {})
        ub_count = len(await db.get_userbots_by_server_ip(ip))

        cpu_usage = stats.get('cpu_usage', '0')
        cpu_cores = stats.get('cpu_cores', '?')
        ram_percent = stats.get('ram_percent', '0')
        ram_used = stats.get('ram_used', 'N/A')
        ram_total = stats.get('ram_total', 'N/A')
        disk_percent = stats.get('disk_percent', '0%')
        disk_used = stats.get('disk_used', 'N/A')
        disk_total = stats.get('disk_total', 'N/A')
        uptime = stats.get('uptime', 'N/A')
        
        cpu_bar = create_progress_bar(cpu_usage)
        ram_bar = create_progress_bar(ram_percent)
        disk_bar = create_progress_bar(disk_percent)

        server_block = (
            f"\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
            f"<blockquote>"
            f"<b>{details.get('flag', '🏳️')} {html.quote(details.get('name', 'Unknown'))}</b> (Код: <code>{details.get('code', 'N/A')}</code>)\n"
            f"├ <b>Локация:</b> {details.get('country', 'N/A')}, {details.get('city', 'N/A')}\n"
            f"├ <b>Провайдер:</b> {details.get('org', 'N/A')}\n"
            f"├ <b>Характеристики:</b>\n"
            f"│  ├─ CPU: {cpu_cores} ядер\n"
            f"│  ├─ RAM: {ram_total}\n"
            f"│  └─ Disk: {disk_total}\n"
            f"├ <b>Текущая нагрузка:</b>\n"
            f"│  ├─ CPU: {cpu_bar} {cpu_usage}%\n"
            f"│  ├─ RAM: {ram_bar} ({ram_used}/{ram_total})\n"
            f"│  └─ Disk: {disk_bar} ({disk_used}/{disk_total})\n"
            f"├ <b>Uptime:</b> {uptime}\n"
            f"└ <b>Юзерботы:</b> {ub_count} шт."
            f"</blockquote>"
        )
        text_parts.append(server_block)
        
    return "".join(text_parts)

async def auto_update_server_info_panel(bot: Bot, chat_id: int, message_id: int):
    while True:
        await asyncio.sleep(180)
        try:
            info_text, _ = await _get_server_info_content()

            await bot.edit_message_text(
                text=info_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=kb.get_server_info_keyboard()
            )
        except TelegramBadRequest as e:
            if "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                logging.warning(f"Message {message_id} in chat {chat_id} for auto-update not found. Stopping task.")
                if chat_id in ACTIVE_PANEL_UPDATE_TASKS:
                    del ACTIVE_PANEL_UPDATE_TASKS[chat_id]
                break 
            elif "message is not modified" not in str(e).lower():
                logging.error(f"Error auto-updating server info panel: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in auto-update task: {e}", exc_info=True)


async def start_or_reset_update_task(bot: Bot, chat_id: int, message_id: int):
    if chat_id in ACTIVE_PANEL_UPDATE_TASKS:
        ACTIVE_PANEL_UPDATE_TASKS[chat_id].cancel()
        logging.info(f"Cancelled previous update task for chat {chat_id}")
    
    task = asyncio.create_task(auto_update_server_info_panel(bot, chat_id, message_id))
    ACTIVE_PANEL_UPDATE_TASKS[chat_id] = task
    logging.info(f"Started new auto-update task for chat {chat_id}, message {message_id}")

async def _get_server_info_content():
    servers = server_config.get_servers()
    
    remote_servers = [(ip, details) for ip, details in servers.items() if ip != sm.LOCAL_IP]
    
    if not remote_servers:
        return "Список удаленных серверов пуст.", None

    stats_tasks = [sm.get_server_stats(ip) for ip, _ in remote_servers]
    all_stats = await asyncio.gather(*stats_tasks)
    stats_map = dict(zip([ip for ip, _ in remote_servers], all_stats))

    info_text = await _get_full_server_info_text(stats_map, remote_servers)
    
    markup = kb.get_server_info_keyboard()
    
    return info_text, markup

@router.message(Command("serverinfo"))
async def cmd_server_info(message: types.Message, bot: Bot):
    msg = await message.reply("⏳ Собираю информацию...")
    
    info_text, markup = await _get_server_info_content()

    if "пуст" in info_text:
        await msg.edit_text(info_text)
        return

    sent_message = await msg.edit_text(
        text=info_text,
        reply_markup=markup
    )
    
    await start_or_reset_update_task(bot, sent_message.chat.id, sent_message.message_id)


@router.callback_query(F.data == "refresh_server_info")
async def refresh_server_info_handler(call: types.CallbackQuery, bot: Bot):
    await call.answer("Обновляю...")
    
    info_text, markup = await _get_server_info_content()

    try:
        await call.message.edit_text(
            text=info_text,
            reply_markup=markup
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
             logging.error(f"Failed to edit message text on refresh: {e}")

    await start_or_reset_update_task(bot, call.message.chat.id, call.message.message_id)

@router.message(Command("restart"), IsSuperAdmin())
async def cmd_restart_bot(message: types.Message):
    try:
        msg = await message.reply("⏳ Перезапускаюсь...")

        restart_info = {"chat_id": msg.chat.id, "message_id": msg.message_id}
        with open(RESTART_INFO_FILE, "w") as f:
            json.dump(restart_info, f)
        
        await asyncio.sleep(1)

        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        logging.error(f"Failed to execute restart: {e}")
        try:
            await msg.edit_text(f"❌ Не удалось перезапустить бота. Ошибка: {e}")
        except:
            pass

@router.message(Command("stop"), IsSuperAdmin())
async def cmd_stop_bot(message: types.Message):
    await message.reply("Останавливаю бота. Для запуска используйте консоль.")
    loop = asyncio.get_running_loop()
    loop.stop()

@router.message(Command("server"))
async def cmd_server_toggle(message: types.Message, command: CommandObject, bot: Bot):
    arg = command.args.lower() if command.args else None
    current_status_is_on = not maintenance_manager.is_maintenance_mode()
    admin_data = {"id": message.from_user.id, "full_name": message.from_user.full_name}

    if arg == "on":
        if not current_status_is_on:
            maintenance_manager.set_maintenance_mode(False)
            await message.reply("✅ Бот включен для пользователей.")
            await log_event(bot, "maintenance_mode_off", {"admin_data": admin_data})
        else:
            await message.reply("✅ Бот уже был включен.")
    elif arg == "off":
        if current_status_is_on:
            maintenance_manager.set_maintenance_mode(True)
            await message.reply("⚙️ Бот переведен в режим тех. работ.")
            await log_event(bot, "maintenance_mode_on", {"admin_data": admin_data})
        else:
            await message.reply("⚙️ Бот уже был в режиме тех. работ.")
    else:
        status = "Включен ✅" if current_status_is_on else "Выключен (тех. работы) ⚙️"
        await message.reply(
            f"<b>Текущий статус для пользователей:</b> {status}\n\n"
            f"Использование: <code>/server [on|off]</code>"
        )

@router.message(Command("remote"))
async def cmd_remote_control(message: types.Message, command: CommandObject):
    if not command.args or len(command.args.split()) != 2:
        await message.reply(f"Использование: <code>/remote [ID|имя_юзербота] [on|off|restart]</code>")
        return
    target, action_str = command.args.split()
    action = action_str.lower()
    action_map = {"on": "start", "off": "stop", "restart": "restart"}
    if action not in action_map:
        await message.reply("Неверное действие. Используйте 'on', 'off' или 'restart'.")
        return
    system_action = action_map[action]
    
    ub_data_list = []
    if target.isdigit():
        user_id = int(target)
        userbots_data = await db.get_userbots_by_tg_id(user_id)
        if not userbots_data:
            await message.reply(f"Не найдено юзерботов для пользователя с ID <code>{user_id}</code>.")
            return
        ub_data_list = userbots_data
    else:
        ub_data = await db.get_userbot_data(ub_username=target)
        if not ub_data:
            await message.reply(f"Юзербот <code>{html.quote(target)}</code> не найден.")
            return
        ub_data_list.append(ub_data)

    await message.reply(f"⏳ Выполняю действие '<b>{action}</b>' для {len(ub_data_list)} юзербота(ов)...")
    
    tasks = [sm.manage_ub_service(ub['ub_username'], system_action, ub['server_ip']) for ub in ub_data_list]
    results = await asyncio.gather(*tasks)

    success_list = [ub_data_list[i]['ub_username'] for i, res in enumerate(results) if res["success"]]
    error_list = [ub_data_list[i]['ub_username'] for i, res in enumerate(results) if not res["success"]]

    response = ""
    if success_list:
        response += f"<b>✅ Успешно для:</b>\n" + "\n".join([f"  - <code>{html.quote(ub)}</code>" for ub in success_list])
    if error_list:
        response += f"\n\n<b>❌ Ошибка для:</b>\n" + "\n".join([f"  - <code>{html.quote(ub)}</code>" for ub in error_list])
    await message.reply(response or "Ничего не было сделано.")

# В файле admin_handlers.py

@router.message(Command("ahelp"))
async def cmd_ahelp(message: types.Message):
    text = (
        "<b>Админ-панель: Справка по командам</b>\n\n"
        
        "<b>Управление ботом и пользователями:</b>\n"
        "<code>/ban [ID|@|имя]</code> - Блокировка пользователя.\n"
        "<code>/unban [ID|@|имя]</code> - Разблокировка пользователя.\n"
        "<code>/users</code> - Постраничный список пользователей.\n"
        "<code>/user [ID|@|имя ub]</code> - Инфо и управление пользователем.\n"
        "<code>/server [on|off]</code> - Вкл/выкл бота для всех.\n"
        "<code>/restart</code> - Перезапуск бота.\n"
        "<code>/stop</code> - Остановка бота.\n\n"

        "<b>Разработка и Обновления:</b>\n"
        "<code>/update [текст]</code> - Опубликовать коммит в канал.\n"
        "<code>/commits</code> - Просмотреть историю коммитов.\n"
        "<code>/git [view|change] fox [URL]</code> - Управление репозиториями.\n"
        "<code>/backup_bot</code> - Создать резервную копию файлов бота.\n\n"

        "<b>Управление серверами (Хостами):</b>\n"
        "<code>/serv help</code> - Справка по командам управления серверами.\n"
        "<code>/serverinfo</code> - Общая статистика по серверам.\n"
        "<code>/obs</code> - Полное обслуживание всех удаленных серверов.\n"
        "<code>/cpu_ub</code> - Нагрузка на CPU по юзерботам.\n"
        "<code>/terminal [код] [команда]</code> - Выполнить команду на сервере.\n\n"
        
        "<b>Управление юзерботами:</b>\n"
        "<code>/ub [имя]</code> - Инфо и управление конкретным юзерботом.\n"
        "<code>/remote [ID|имя] [on|off|restart]</code> - Массовое управление UB.\n"
        "<code>/delub [имя]</code> - Удаление UB с выбором причины.\n"
        "<code>/check</code> - Проверка посторонних сессий на серверах.\n\n"
        
        "<b>Рассылки и связь:</b>\n"
        "<code>/bc [ID|@]</code> - Рассылка (ответом на сообщение).\n"
        "<code>/stats</code> - Расширенная статистика по боту.\n"
    )
    await message.reply(text, disable_web_page_preview=True)

@router.message(Command("check"), IsAdmin())
async def cmd_check_sessions(message: types.Message):
    msg = await message.reply("⏳ Проверяю сессии на всех удалённых серверах...")
    try:
        server_results = await session_checker.check_all_remote_sessions()
        
        # Кешируем данные для быстрого доступа
        cached_data = {
            "data": server_results,
            "timestamp": time.time(),
            "reports": {
                "has_session": {},
                "no_session": {}
            }
        }
        
        # Генерируем отчеты для всех страниц и режимов
        await msg.edit_text("⏳ Генерирую отчеты для всех режимов...")
        
        for view_mode in ["has_session", "no_session"]:
            for page in range(10):  # Максимум 10 страниц
                try:
                    report, total_pages = await session_checker.format_session_check_report(server_results, view_mode, page=page)
                    if total_pages <= page:  # Если страница выходит за пределы
                        break
                    cached_data["reports"][view_mode][page] = {
                        "report": report,
                        "total_pages": total_pages
                    }
                except Exception as e:
                    logging.error(f"Error generating report for {view_mode} page {page}: {e}")
                    break
        
        SESSION_CHECK_CACHE[msg.chat.id] = cached_data
        
        # Отображаем первую страницу
        first_page_data = cached_data["reports"]["has_session"][0]
        markup = kb.get_session_check_keyboard("has_session", page=0, total_pages=first_page_data["total_pages"])
        
        # Отладочная информация
        logging.info(f"Report length: {len(first_page_data['report'])}, Total pages: {first_page_data['total_pages']}")
        
        # Проверяем длину сообщения
        if len(first_page_data["report"]) > 3000:
            # Если сообщение слишком длинное, отправляем как файл
            report_file = BufferedInputFile(first_page_data["report"].encode('utf-8'), filename="session_check_report.txt")
            await msg.delete()
            await message.answer_document(report_file, caption="📊 Отчет о проверке сессий (файл слишком большой для сообщения)")
        else:
            try:
                await msg.edit_text(text=first_page_data["report"], reply_markup=markup)
            except TelegramBadRequest as e:
                if "can't parse entities" in str(e):
                    logging.error(f"HTML parsing error in /check: {e}")
                    # Пробуем отправить без HTML-разметки
                    clean_report = first_page_data["report"].replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '').replace('<blockquote>', '').replace('</blockquote>', '')
                    await msg.edit_text(text=clean_report, reply_markup=markup)
                else:
                    raise e
    except Exception as e:
        logging.error(f"Ошибка во время выполнения /check: {e}", exc_info=True)
        await msg.edit_text(f"❌ Произошла ошибка во время проверки: {e}")

@router.callback_query(F.data.startswith("check_view_toggle:"))
async def check_view_toggle_handler(call: types.CallbackQuery):
    await call.answer()
    cached_data = SESSION_CHECK_CACHE.get(call.message.chat.id)
    if not cached_data or time.time() - cached_data["timestamp"] > CACHE_TTL:
        await call.message.edit_text("Данные для этого отчета устарели. Пожалуйста, выполните команду /check снова.", reply_markup=None)
        return
    
    new_view_mode = call.data.split(":")[1]
    
    # Проверяем, есть ли кешированный отчет
    if "reports" in cached_data and new_view_mode in cached_data["reports"] and 0 in cached_data["reports"][new_view_mode]:
        page_data = cached_data["reports"][new_view_mode][0]
        report = page_data["report"]
        total_pages = page_data["total_pages"]
        markup = kb.get_session_check_keyboard(new_view_mode, page=0, total_pages=total_pages)
        
        # Проверяем длину сообщения
        if len(report) > 3000:
            # Если сообщение слишком длинное, отправляем как файл
            report_file = BufferedInputFile(report.encode('utf-8'), filename="session_check_report.txt")
            await call.message.delete()
            await call.message.answer_document(report_file, caption="📊 Отчет о проверке сессий (файл слишком большой для сообщения)")
        else:
            try:
                await call.message.edit_text(text=report, reply_markup=markup)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    await call.answer("Данные актуальны, изменений нет")
                else:
                    logging.error(f"Ошибка обновления отчета /check: {e}")
                    await call.answer("Произошла ошибка при обновлении", show_alert=True)
    else:
        # Если кеша нет, генерируем заново (fallback)
        server_results = cached_data["data"]
        report, total_pages = await session_checker.format_session_check_report(server_results, new_view_mode, page=0)
        markup = kb.get_session_check_keyboard(new_view_mode, page=0, total_pages=total_pages)
        
        try:
            await call.message.edit_text(text=report, reply_markup=markup)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await call.answer("Данные актуальны, изменений нет")
            else:
                logging.error(f"Ошибка обновления отчета /check: {e}")
                await call.answer("Произошла ошибка при обновлении", show_alert=True)

@router.callback_query(F.data == "no_action")
async def no_action_handler(call: types.CallbackQuery):
    await call.answer()

@router.callback_query(F.data.startswith("check_page:"))
async def check_page_handler(call: types.CallbackQuery):
    await call.answer()
    cached_data = SESSION_CHECK_CACHE.get(call.message.chat.id)
    if not cached_data or time.time() - cached_data["timestamp"] > CACHE_TTL:
        await call.message.edit_text("Данные для этого отчета устарели. Пожалуйста, выполните команду /check снова.", reply_markup=None)
        return
    
    # Парсим данные из callback
    parts = call.data.split(":")
    view_mode = parts[1]
    page = int(parts[2])
    
    logging.info(f"Переход на страницу {page} для режима {view_mode}")
    
    # Проверяем, есть ли кешированный отчет
    if "reports" in cached_data and view_mode in cached_data["reports"] and page in cached_data["reports"][view_mode]:
        page_data = cached_data["reports"][view_mode][page]
        report = page_data["report"]
        total_pages = page_data["total_pages"]
        markup = kb.get_session_check_keyboard(view_mode, page=page, total_pages=total_pages)
        
        logging.info(f"Используем кешированный отчет длиной {len(report)}, всего страниц: {total_pages}")
        
        try:
            await call.message.edit_text(text=report, reply_markup=markup)
            logging.info(f"Сообщение успешно обновлено для страницы {page}")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await call.answer("Данные актуальны, изменений нет")
            else:
                logging.error(f"Ошибка обновления страницы отчета /check: {e}")
                await call.answer("Произошла ошибка при обновлении", show_alert=True)
    else:
        # Если кеша нет, генерируем заново (fallback)
        server_results = cached_data["data"]
        report, total_pages = await session_checker.format_session_check_report(server_results, view_mode, page=page)
        markup = kb.get_session_check_keyboard(view_mode, page=page, total_pages=total_pages)
        
        logging.info(f"Сгенерирован отчет длиной {len(report)}, всего страниц: {total_pages}")
        
        try:
            await call.message.edit_text(text=report, reply_markup=markup)
            logging.info(f"Сообщение успешно обновлено для страницы {page}")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await call.answer("Данные актуальны, изменений нет")
            else:
                logging.error(f"Ошибка обновления страницы отчета /check: {e}")
                await call.answer("Произошла ошибка при обновлении", show_alert=True)

@router.callback_query(F.data == "refresh_session_check")
async def refresh_session_check_handler(call: types.CallbackQuery):
    cached_data = SESSION_CHECK_CACHE.get(call.message.chat.id)
    now = time.time()
    if cached_data and now - cached_data["timestamp"] < 5:
        await call.answer("Обновлять можно не чаще, чем раз в 5 секунд!", show_alert=True)
        return
    # Определяем текущий режим просмотра по кнопкам в сообщении
    current_view_mode = "has_session"  # по умолчанию
    if call.message.reply_markup:
        for row in call.message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data == "check_view_toggle:no_session":
                    current_view_mode = "has_session"
                    break
                elif button.callback_data == "check_view_toggle:has_session":
                    current_view_mode = "no_session"
                    break
    try:
        await call.answer("Обновляю...")
        server_results = await session_checker.check_all_remote_sessions()
        SESSION_CHECK_CACHE[call.message.chat.id] = {
            "data": server_results,
            "timestamp": now
        }
        report, total_pages = await session_checker.format_session_check_report(server_results, current_view_mode, page=0)
        markup = kb.get_session_check_keyboard(current_view_mode, page=0, total_pages=total_pages)
        
        # Проверяем длину сообщения
        if len(report) > 3000:
            # Если сообщение слишком длинное, отправляем как файл
            report_file = BufferedInputFile(report.encode('utf-8'), filename="session_check_report.txt")
            await call.message.delete()
            await call.message.answer_document(report_file, caption="📊 Отчет о проверке сессий (файл слишком большой для сообщения)")
        else:
            await call.message.edit_text(text=report, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await call.answer("Данные актуальны, изменений нет")
        else:
            logging.error(f"Ошибка обновления отчета /check: {e}")
            await call.answer("Произошла ошибка при обновлении", show_alert=True)

@router.message(Command("bc"))
async def cmd_broadcast(message: types.Message, command: CommandObject, bot: Bot):
    replied_message = message.reply_to_message
    if not replied_message:
        await message.reply(
            "<b>⚠️ Неверное использование.</b>\n\n"
            "Ответьте командой <code>/bc</code> на сообщение для рассылки.\n"
            "Для целевой отправки: <code>/bc [ID или @username]</code>.\n"
            "Для рассылки по серверам: <code>/bc [код1] [код2] ...</code> (например: <code>/bc M2 M3</code>)"
        )
        return

    users_to_notify = set()
    is_targeted = False
    target_identifier = "всех пользователей"
    server_codes = set()
    servers = server_config.get_servers()

    if command.args:
        args = command.args.strip().split()
        # Проверяем, есть ли среди аргументов коды серверов
        for arg in args:
            # Если это код сервера (например, M2, A1 и т.д.)
            for ip, details in servers.items():
                if details.get("code", "").lower() == arg.lower():
                    server_codes.add(arg.upper())
                    break
        # Если есть коды серверов - делаем рассылку по ним
        if server_codes:
            is_targeted = True
            target_identifier = ", ".join(server_codes)
            # Получаем IP по коду
            ips = [ip for ip, details in servers.items() if details.get("code", "").upper() in server_codes]
            # Получаем всех юзерботов на этих серверах
            all_owners = set()
            for ip in ips:
                userbots = await db.get_userbots_by_server_ip(ip)
                for ub in userbots:
                    all_owners.add(ub['tg_user_id'])
            users_to_notify = all_owners
            if not users_to_notify:
                await message.reply(f"❌ Нет пользователей с юзерботами на серверах: {target_identifier}")
                return
        else:
            # Если не найдено ни одного кода сервера, пробуем как раньше (ID или username)
            is_targeted = True
            target_identifier = command.args.strip()
            target_user_data = await db.get_user_by_username_or_id(target_identifier)
            if target_user_data:
                users_to_notify.add(target_user_data['tg_user_id'])
            else:
                await message.reply(f"❌ Пользователь <code>{html.quote(target_identifier)}</code> не найден в базе данных.")
                return
    else:
        # Массовая рассылка всем
        users_to_notify = set(await db.get_all_bot_users())

    if not users_to_notify:
        await message.reply("В базе нет пользователей для рассылки.")
        return

    status_text = (
        f"Начинаю целевую отправку для <b>{html.quote(target_identifier)}</b>..."
        if is_targeted else "Начинаю массовую рассылку..."
    )
    msg = await message.reply(text=status_text, reply_markup=kb.get_loading_keyboard())
    
    result = await broadcast_message(
        bot=bot,
        users=list(users_to_notify),
        from_chat_id=replied_message.chat.id,
        message_id=replied_message.message_id
    )
    
    final_status = (
        "✅ Целевая отправка завершена." if is_targeted else "✅ <b>Рассылка завершена.</b>"
    )
    await msg.edit_text(
        f"{final_status}\n\n"
        f"<b>Отправлено:</b> {result['sent']}\n"
        f"<b>Не удалось:</b> {result['failed']}"
    )

async def send_ub_info_panel(bot: Bot, chat_id: int, ub_username: str, message_id: int = None, topic_id: int = None):
    ub_data = await db.get_userbot_data(ub_username=ub_username)
    if not ub_data:
        text = f"❌ Юзербот <code>{html.quote(ub_username)}</code> не найден или был удален."
        if message_id:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=None)
        else:
            await bot.send_message(chat_id=chat_id, text=text, message_thread_id=topic_id)
        return
    
    owner_id = ub_data['tg_user_id']
    owner_data = await db.get_user_data(owner_id)
    server_ip = ub_data['server_ip']
    
    server_details = server_config.get_servers().get(server_ip, {})
    server_code = server_details.get("code", "N/A")
    server_display = f"<code>{server_ip}</code> (<b>{server_code}</b>)"
    
    owner_info = "<i>Неизвестно</i>"
    try:
        owner = await bot.get_chat(chat_id=owner_id)
        owner_info = f"@{owner.username}" if owner.username else owner.full_name
    except (TelegramNotFound, TelegramBadRequest):
        owner_info = f"ID: {owner_id}"
    
    is_active = await sm.is_service_active(f"hikka-{ub_username}.service", server_ip)
    status_text = "🟢 Активен" if is_active else "🔴 Не активен"
    is_blocked = bool(ub_data.get('blocked', 0))
    block_status_text = "🚫 <b>Заблокирован</b>" if is_blocked else "✅ Активен"
    note = owner_data.get('note') if owner_data else None
    
    text = (
        f"🤖 <b>Управление юзерботом:</b> <code>{html.quote(ub_username)}</code>\n"
        f"📍 <b>Сервер:</b> {server_display}\n"
        f"👤 <b>Владелец:</b> {html.quote(owner_info)}\n"
        f"🔧 <b>Статус сервиса:</b> {status_text}\n"
        f"⚖️ <b>Статус доступа:</b> {block_status_text}"
    )
    
    if note:
        text += f"\n📝 <b>Заметка:</b> {html.quote(note)}"

    markup = kb.get_ub_info_keyboard(is_active, ub_username, is_blocked)
    
    if message_id:
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        except TelegramBadRequest:
            pass
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, message_thread_id=topic_id)
        
@router.message(Command("ub"))
async def cmd_ub_info(message: types.Message, command: CommandObject, bot: Bot):
    arg = command.args
    if not arg:
        await message.reply(f"Использование: <code>/ub [имя_юзербота]</code>")
        return
    
    chat_id = message.chat.id
    topic_id = message.message_thread_id
    
    await send_ub_info_panel(bot=bot, chat_id=chat_id, ub_username=arg, topic_id=topic_id)

@router.callback_query(F.data.startswith("add_note_start:"))
async def cq_add_note_start(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    
    ub_data = await db.get_userbot_data(ub_username=ub_username)
    if not ub_data:
        await call.answer("❌ Юзербот не найден!", show_alert=True)
        return

    await state.set_state(AdminTasks.WaitingForNote)
    await state.update_data(ub_username=ub_username, message_id=call.message.message_id, owner_id=ub_data['tg_user_id'])

    await call.message.edit_text(
        "Введите новую заметку для этого пользователя. \nДля удаления заметки отправьте <code>-</code> (минус).",
        reply_markup=kb.get_cancel_note_keyboard(ub_username)
    )
    await call.answer()

@router.callback_query(F.data.startswith("cancel_add_note:"), StateFilter(AdminTasks.WaitingForNote))
async def cq_cancel_add_note(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    
    await state.clear()
    await call.answer("Отменено.")
    await send_ub_info_panel(bot=call.bot, chat_id=call.message.chat.id, ub_username=ub_username, message_id=call.message.message_id)

@router.message(StateFilter(AdminTasks.WaitingForNote))
async def process_note_text(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    message_id = data.get("message_id")
    owner_id = data.get("owner_id")

    await message.delete()

    note_text = message.text
    if note_text == "-":
        await db.set_user_note(owner_id, None)
        status_text = "✅ Заметка удалена."
    else:
        await db.set_user_note(owner_id, note_text)
        status_text = "✅ Заметка сохранена."

    await state.clear()

    await bot.edit_message_text(
        text=status_text,
        chat_id=message.chat.id,
        message_id=message_id,
        reply_markup=kb.get_back_to_ub_panel_keyboard(ub_username)
    )

@router.callback_query(F.data.startswith("toggle_block_ub:"))
async def toggle_block_ub_handler(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    _, ub_username, block_action_str = call.data.split(":")
    block_action = bool(int(block_action_str))
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("Юзербот не найден в БД.", show_alert=True)
        return
    server_ip = ub_data['server_ip']
    
    if await db.block_userbot(ub_username, block_action):
        await call.answer("Статус блокировки обновлен!")
        action = "stop" if block_action else "start"
        await sm.manage_ub_service(ub_username, action, server_ip)
    else:
        await call.answer("❌ Ошибка обновления статуса в БД.", show_alert=True)
    
    await send_ub_info_panel(bot=bot, chat_id=call.message.chat.id, ub_username=ub_username, message_id=call.message.message_id)

@router.callback_query(F.data.startswith("manage_ub_info:"))
async def manage_ub_from_info_panel(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    action, ub_username = call.data.split(":")[1:]
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("Юзербот не найден в БД.", show_alert=True)
        return
    server_ip = ub_data['server_ip']

    res = await sm.manage_ub_service(ub_username, action, server_ip)
    if not res["success"]:
        await call.answer(f"❌ Ошибка: {res.get('message', '...')}", show_alert=True)
    
    await asyncio.sleep(1)
    await send_ub_info_panel(bot=bot, chat_id=call.message.chat.id, ub_username=ub_username, message_id=call.message.message_id)

@router.callback_query(F.data.startswith("choose_log_type:"))
async def choose_log_type_handler(call: types.CallbackQuery):
    ub_username = call.data.split(":")[1]
    ub_data = await db.get_userbot_data(ub_username)
    owner_id = ub_data.get('tg_user_id') if ub_data else None
    text = f"📜 <b>Выберите тип логов для</b> <code>{html.quote(ub_username)}</code>:"
    markup = kb.get_log_type_choice_keyboard(ub_username, owner_id)
    await call.message.edit_text(text=text, reply_markup=markup)

@router.callback_query(F.data.startswith("show_logs:"))
async def show_logs_handler(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    parts = call.data.split(":")
    # Поддержка старого и нового формата (4 или 5+ частей)
    # show_logs:log_type:ub_username:page или show_logs:log_type:ub_username:owner_id:page
    if len(parts) == 4:
        _, log_type, ub_username, page_str = parts
        page = int(page_str)
        # Получаем owner_id из базы
        ub_data = await db.get_userbot_data(ub_username)
        owner_id = ub_data.get('tg_user_id') if ub_data else None
    elif len(parts) >= 5:
        _, log_type, ub_username, owner_id, page_str = parts[:5]
        page = int(page_str)
    else:
        await call.answer("Ошибка: некорректный формат callback_data.", show_alert=True)
        return
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("Юзербот не найден в БД.", show_alert=True)
        return
    server_ip, hikka_path, ub_type = ub_data['server_ip'], ub_data.get('hikka_path'), ub_data.get('ub_type')
    
    log_titles = {"systemd": "Systemd", "logfile": "Log File"}
    log_title = log_titles.get(log_type, "Unknown")
    logs = None

    if log_type == "systemd":
        logs = await sm.get_journal_logs(ub_username, server_ip)
    elif log_type == "logfile":
        if hikka_path and ub_type:
            logs = await sm.get_script_log_file(hikka_path, ub_type, server_ip)
        else:
            await call.answer("❌ Не удалось найти путь или тип юзербота в БД.", show_alert=True)
            return
            
    if not logs:
        await call.answer(f"Логи типа '{log_title}' для этого пользователя пусты или файл не найден.", show_alert=True)
        await choose_log_type_handler(call)
        return

    CHUNK_SIZE = 4000
    escaped_logs = html.quote(logs)
    log_chunks = [escaped_logs[i:i + CHUNK_SIZE] for i in range(0, len(escaped_logs), CHUNK_SIZE)]
    total_pages = len(log_chunks)

    if not (1 <= page <= total_pages):
        await call.answer(f"Страница {page} не существует.", show_alert=True)
        return
        
    page_content = log_chunks[page - 1]

    text = (f"📜 <b>Логи ({log_title}) для <code>{html.quote(ub_username)}</code> (Стр. {page}/{total_pages})</b>\n\n"
            f"<pre>{page_content}</pre>")
    markup = kb.get_logs_paginator_keyboard(log_type, ub_username, page, total_pages, owner_id)
    
    try:
        await call.message.edit_text(text=text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            await call.answer()
        else:
            try:
                from aiogram.types import BufferedInputFile
                log_file = BufferedInputFile(logs.encode('utf-8'), filename=f"{ub_username}_{log_type}.log")
                await call.message.answer_document(log_file, caption=f"Логи для {ub_username} слишком велики для отображения.")
            except Exception as doc_e:
                await call.answer(f"Ошибка при отправке логов как документа: {doc_e}", show_alert=True)

@router.callback_query(F.data.startswith("back_to_ub_info:"))
async def back_to_ub_info_handler(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    ub_username = call.data.split(":")[1]
    await send_ub_info_panel(bot=bot, chat_id=call.message.chat.id, ub_username=ub_username, message_id=call.message.message_id)

REASON_TEMPLATES = {
    "no_reason": "Без указания причины",
    "inactive": "Неактивность (юзербот занимает слот)",
    "abuse": "Злоупотребление сервисом / Систематические нарушения",
    "tos_violation": "Нарушение пользовательского соглашения",
    "multiaccount": "Мультиаккаунт (создание нескольких юзерботов)",
    "cpu_load": "Критическая нагрузка на CPU",
    "ram_load": "Чрезмерное потребление RAM",
    "spam_activity": "Рассылка спама / Жалобы от пользователей",
    "phishing": "Фишинг / Вредоносная активность",
    "owner_request": "По просьбе владельца",
    "forbidden_content": "Распространение запрещенного контента",
    "technical_work": "Технические работы на сервере"
}

@router.message(Command("delub"), IsAdmin())
async def cmd_delub(message: types.Message, command: CommandObject, bot: Bot):
    if not command.args:
        await message.reply("Использование: <code>/delub [имя_юзербота]</code> или <code>/delub [имя_юзербота] -f [ip]</code>")
        return

    args = command.args.split()
    ub_name = args[0]
    force = False
    server_ip = None
    if len(args) >= 3 and args[1] == "-f":
        force = True
        server_ip = args[2]
    elif len(args) == 2 and args[1] == "-f":
        force = True
        await message.reply("❗ Укажите IP сервера: <code>/delub [имя] -f [ip]</code>")
        return

    if force:
        # Принудительное удаление без БД
        await message.reply(f"🗑️ Принудительно удаляю <code>{html.quote(ub_name)}</code> на сервере <code>{html.quote(server_ip)}</code>...")
        res = await sm.delete_userbot_full(ub_name, server_ip)
        if res["success"]:
            await message.reply(f"✅ Юзербот <code>{html.quote(ub_name)}</code> был полностью удален с сервера <code>{html.quote(server_ip)}</code>.")
        else:
            await message.reply(f"❌ Ошибка при удалении <code>{html.quote(ub_name)}</code>: {res.get('message', '...')}")
        return

    if not await db.get_userbot_data(ub_username=ub_name):
        await message.reply(f"❌ Юзербот <code>{html.quote(ub_name)}</code> не найден.")
        return
        
    text = f"Выберите причину удаления для юзербота <code>{html.quote(ub_name)}</code>:"
    markup = kb.get_delub_reason_keyboard(ub_name, REASON_TEMPLATES)
    await message.reply(text, reply_markup=markup)

@router.callback_query(F.data == "delub_close_menu")
async def cq_delub_close_menu(call: types.CallbackQuery):
    await call.message.delete()
    await call.answer()

@router.callback_query(F.data.startswith("delub_confirm:"))
async def cq_delub_reason_selected(call: types.CallbackQuery):
    _, ub_username, reason_code = call.data.split(":")
    reason_text = REASON_TEMPLATES.get(reason_code, "Причина не указана.")

    text = (
        f"<b>⚠️ Подтверждение удаления</b>\n\n"
        f"<b>Юзербот:</b> <code>{html.quote(ub_username)}</code>\n"
        f"<b>Причина:</b> {html.quote(reason_text)}\n\n"
        "Вы уверены, что хотите продолжить?"
    )
    markup = kb.get_delub_final_confirm_keyboard(ub_username, reason_code)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

@router.callback_query(F.data.startswith("delub_cancel:"))
async def cq_delub_cancel(call: types.CallbackQuery):
    ub_username = call.data.split(":")[1]
    text = f"Выберите причину удаления для юзербота <code>{html.quote(ub_username)}</code>:"
    markup = kb.get_delub_reason_keyboard(ub_username, REASON_TEMPLATES)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer("Удаление отменено.")

@router.callback_query(F.data.startswith("delub_execute:"))
async def cq_delub_execute(call: types.CallbackQuery, bot: Bot):
    _, ub_username, reason_code = call.data.split(":")
    reason_text = REASON_TEMPLATES.get(reason_code, "Причина не указана.")
    
    await call.message.edit_text(f"🗑️ Удаляю <code>{html.quote(ub_username)}</code>...", reply_markup=None)
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.message.edit_text("❌ Юзербот уже был удален.")
        return
        
    owner_id = ub_data.get('tg_user_id')
    server_ip = ub_data.get('server_ip')
    
    res = await sm.delete_userbot_full(ub_username, server_ip)
    
    if res["success"]:
        await call.message.edit_text(f"✅ Юзербот <code>{html.quote(ub_username)}</code> был полностью удален.")
        
        admin_data = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        owner_data = {"id": owner_id}
        try:
            owner_chat = await bot.get_chat(owner_id)
            owner_data["full_name"] = owner_chat.full_name
        except Exception:
            pass
            
        server_details = server_config.get_servers().get(server_ip, {})
        
        log_data = {
            "admin_data": admin_data,
            "user_data": owner_data,
            "ub_info": {"name": ub_username},
            "server_info": {"ip": server_ip, "code": server_details.get("code", "N/A")},
            "reason": reason_text
        }
        await log_event(bot, "deletion_by_admin", log_data)

        if owner_id and reason_code != "no_reason":
            try:
                await bot.send_message(
                    chat_id=owner_id,
                    text=f"‼️ <b>Ваш юзербот был удален администратором.</b>\n\n<b>Причина:</b> {html.quote(reason_text)}"
                )
            except Exception as e:
                logging.warning(f"Не удалось уведомить {owner_id} об удалении UB: {e}")
    else:
        await call.message.edit_text(f"❌ Ошибка при удалении <code>{html.quote(ub_username)}</code>: {res.get('message', '...')}")
        
async def _get_sorted_user_list(bot: Bot):
    all_registered_users = await db.get_all_registered_users()
    
    users_with_active_bot = []
    users_with_inactive_bot = []
    users_without_bot = []
    
    all_userbots = await db.get_all_userbots_full_info()

    services_by_ip = {}
    for ub in all_userbots:
        ip = ub.get('server_ip')
        if ip:
            if ip not in services_by_ip:
                services_by_ip[ip] = []
            service_name = f"hikka-{ub['ub_username']}.service"
            services_by_ip[ip].append(service_name)
           
    batch_tasks = [
        sm.get_batch_service_statuses(names, ip)
        for ip, names in services_by_ip.items()
    ]
    batch_results = await asyncio.gather(*batch_tasks)
    
    active_statuses = {}
    for result_dict in batch_results:
        for service_name, is_active in result_dict.items():
            ub_username = service_name.replace("hikka-", "").replace(".service", "")
            active_statuses[ub_username] = is_active
            
    for user in all_registered_users:
        user_bots = [ub for ub in all_userbots if ub.get('tg_user_id') == user.get('tg_user_id')]

        if not user_bots:
            users_without_bot.append(user)
            continue
        
        main_bot = user_bots[0]
        is_active = active_statuses.get(main_bot['ub_username'], False)
        
        user['userbot_info'] = main_bot
        
        if is_active:
            users_with_active_bot.append(user)
        else:
            users_with_inactive_bot.append(user)
            
    return users_with_active_bot + users_with_inactive_bot + users_without_bot

async def build_users_page_text(users_data: list, bot: Bot):
    if not users_data:
        return "В этой категории нет пользователей."
        
    text_parts = []
    servers_info = server_config.get_servers()

    for user_data in users_data:
        user_id = user_data['tg_user_id']
        
        user_display = None
        try:
            user_chat_info = await bot.get_chat(chat_id=user_id)
            user_display = f"@{user_chat_info.username}" if user_chat_info.username else user_chat_info.full_name
        except (TelegramNotFound, TelegramBadRequest):
            if user_data:
                user_display = user_data.get('full_name') or (f"@{user_data['username']}" if user_data.get('username') else None)

        if not user_display:
            user_display = f"ID: {user_id}"

        user_block = [f"👤 <b>{html.quote(user_display)}</b> (<code>{user_id}</code>)"]
        
        ub_info = user_data.get('userbot_info')
        if ub_info:
            ub_username = ub_info['ub_username']
            ub_type = ub_info.get('ub_type', 'N/A').capitalize()
            
            server_details = servers_info.get(ub_info['server_ip'], {})
            server_flag = server_details.get("flag", "🏳️")
            server_name = server_details.get("name", ub_info['server_ip'])
            
            is_active = await sm.is_service_active(f"hikka-{ub_username}.service", ub_info['server_ip'])
            status_emoji = "🟢" if is_active else "🔴"
            
            user_block.append(f"   ├─ 🤖 <code>{html.quote(ub_username)}</code> ({ub_type}) на {server_flag} {html.quote(server_name)} {status_emoji}")
        else:
            user_block.append("   └─ 🤖 Нет юзерботов")

        note = user_data.get('note')
        if note:
            user_block.append(f"   └─ 📝: <i>{html.quote(note)}</i>")

        text_parts.append("\n".join(user_block))
    return "\n\n".join(text_parts)

async def _get_paginated_users_text_and_markup(bot: Bot, view_mode: str, page: int):
    page_size = 5
    header = ""
    
    if view_mode == "visible":
        user_list = await _get_sorted_user_list(bot)
        header = "<b>👥 Список активных пользователей</b>\n\n"
    else:
        user_list = await db.get_all_unregistered_users()
        header = "<b>👻 Список скрытых пользователей (не приняли соглашение)</b>\n\n"
        
    total_pages = max(1, (len(user_list) + page_size - 1) // page_size)
    page = min(page, total_pages)
    
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    users_on_page = user_list[start_index:end_index]
    
    text = await build_users_page_text(users_on_page, bot)
    markup = kb.get_user_list_paginator(page, total_pages, view_mode)
    
    full_text = f"{header}<i>(Страница {page}/{total_pages})</i>\n\n{text}"
    
    return full_text, markup

@router.message(Command("users"))
async def cmd_users_list(message: types.Message, bot: Bot):
    msg = await message.reply("⏳ Готовлю список пользователей...")
    text, markup = await _get_paginated_users_text_and_markup(bot, view_mode="visible", page=1)
    await msg.edit_text(text=text, reply_markup=markup)

@router.callback_query(F.data.startswith("user_page:"))
async def user_list_paginator_handler(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    _, view_mode, page_str = call.data.split(':')
    page = int(page_str)
    text, markup = await _get_paginated_users_text_and_markup(bot, view_mode=view_mode, page=page)
    try:
        await call.message.edit_text(text=text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            raise e
    finally:
        await call.answer()

@router.callback_query(F.data.startswith("user_view_toggle:"))
async def toggle_user_visibility_handler(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_loading_keyboard())
    new_view_mode = call.data.split(':')[1]
    text, markup = await _get_paginated_users_text_and_markup(bot, view_mode=new_view_mode, page=1)
    await call.message.edit_text(text=text, reply_markup=markup)
    await call.answer()

@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    msg = await message.reply("⏳ Собираю расширенную статистику, это может занять до минуты...")

    all_users_data = await db.get_all_users_with_reg_date()
    all_ubs_info = await db.get_all_userbots_full_info()
    servers_info = server_config.get_servers()
    
    total_users = len(all_users_data)
    total_ubs = len(all_ubs_info)
    owners_count = await db.get_userbot_owners_count()
    
    new_users_today = 0
    today_date = date.today() 

    for user in all_users_data:
        registration_datetime = user.get('registered_at')
        if registration_datetime and isinstance(registration_datetime, datetime) and registration_datetime.date() == today_date:
            new_users_today += 1

    active_ubs_count = 0
    bots_by_server = {ip: 0 for ip in servers_info.keys()}
    bots_by_type = {}

    if all_ubs_info:
        services_by_ip = {}
        for ub in all_ubs_info:
            ip = ub.get('server_ip')
            if ip:
                if ip not in services_by_ip:
                    services_by_ip[ip] = []
                service_name = f"hikka-{ub['ub_username']}.service"
                services_by_ip[ip].append(service_name)
        
        batch_tasks = [sm.get_batch_service_statuses(names, ip) for ip, names in services_by_ip.items()]
        batch_results = await asyncio.gather(*batch_tasks)
        
        active_statuses = {}
        for result_dict in batch_results:
            for service_name, is_active in result_dict.items():
                ub_username = service_name.replace("hikka-", "").replace(".service", "")
                active_statuses[ub_username] = is_active

        for ub in all_ubs_info:
            if active_statuses.get(ub['ub_username'], False):
                active_ubs_count += 1
            if ub['server_ip'] in bots_by_server:
                bots_by_server[ub['server_ip']] += 1
            ub_type = ub.get('ub_type', 'unknown').capitalize()
            bots_by_type[ub_type] = bots_by_type.get(ub_type, 0) + 1

    inactive_ubs_count = total_ubs - active_ubs_count

    text = [
        "<b>📊 Расширенная статистика бота</b>\n",
        "👥 <b><u>Пользователи:</u></b>",
        f"  - Всего: <code>{total_users}</code>",
        f"  - Владельцев юзерботов: <code>{owners_count}</code>",
        f"  - Новых за сегодня: <code>{new_users_today}</code>\n",
        "🤖 <b><u>Юзерботы:</u></b>",
        f"  - Всего: <code>{total_ubs}</code>",
        f"  - 🟢 Активных: <code>{active_ubs_count}</code>",
        f"  - 🔴 Неактивных: <code>{inactive_ubs_count}</code>\n"
    ]

    if bots_by_type:
        text.append("⚙️ <b><u>По типам:</u></b>")
        for ub_type, count in sorted(bots_by_type.items()):
            text.append(f"  - {html.quote(ub_type)}: <code>{count}</code>")
        text.append("")

    if bots_by_server:
        text.append("🖥️ <b><u>По серверам:</u></b>")
        for ip, count in sorted(bots_by_server.items(), key=lambda item: servers_info.get(item[0], {}).get('name', item[0])):
            server_details = servers_info.get(ip, {})
            flag = server_details.get("flag", "🏳️")
            name = server_details.get("name", ip)
            text.append(f"  - {flag} {html.quote(name)}: <code>{count}</code>")

    await msg.edit_text("\n".join(text))
    
@router.message(Command("cpu_ub"))
async def cmd_cpu_ub_usage(message: types.Message):
    msg = await message.reply("⏳ Собираю данные о нагрузке CPU... Это может занять до минуты.")
    
    all_servers = server_config.get_servers()
    full_report = ["<b>📊 Нагрузка на CPU по юзерботам:</b>\n"]
    
    has_any_data = False
    
    tasks = [sm.get_all_userbots_cpu_usage(ip) for ip in all_servers.keys()]
    results = await asyncio.gather(*tasks)
    
    for server_ip, cpu_data in zip(all_servers.keys(), results):
        server_details = all_servers.get(server_ip, {})
        server_flag = server_details.get("flag", "🏳️")
        server_name = server_details.get("name", server_ip)

        if not cpu_data:
            continue
            
        has_any_data = True
        
        sorted_bots = sorted(cpu_data.items(), key=lambda item: item[1], reverse=True)
        
        server_report = [f"\n<b>{server_flag} {html.quote(server_name)} (<code>{server_ip}</code>)</b>"]
        for ub_username, cpu_percent in sorted_bots:
            if cpu_percent > 50.0:
                emoji = "🔥"
            elif cpu_percent > 25.0:
                emoji = "⚠️"
            else:
                emoji = "🔹"
                
            server_report.append(f"{emoji} <code>{f'{cpu_percent:.2f}%'.ljust(7)}</code> - {html.quote(ub_username)}")
        
        full_report.extend(server_report)
        
    if not has_any_data:
        await msg.edit_text("Не удалось получить данные о нагрузке ни с одного сервера.")
        return
        
    await msg.edit_text("\n".join(full_report))

@router.callback_query(F.data.startswith("host_reboot_confirm:"))
async def cq_host_reboot_confirm(call: types.CallbackQuery, bot: Bot):
    ip = call.data.split(":")[1]
    await call.message.edit_text(f"⏳ Перезагружаю сервер <code>{ip}</code>... Бот будет ожидать его возвращения в сеть.", reply_markup=None)
    
    asyncio.create_task(sm.run_command_async(f"sudo reboot", ip))
    
    await call.answer("Команда на перезагрузку отправлена.")
    
    asyncio.create_task(monitor_and_restore_server(ip, bot, call.from_user.id))

@router.callback_query(F.data == "host_reboot_cancel")
async def cq_host_reboot_cancel(call: types.CallbackQuery):
    await call.message.edit_text("🚫 Перезагрузка сервера отменена.")
    await call.answer()

async def monitor_and_restore_server(ip: str, bot: Bot, admin_id: int):
    await log_to_channel(bot, f"👀 Начал мониторинг сервера <code>{ip}</code>. Ожидаю, пока он уйдет в оффлайн...")

    for _ in range(10): 
        res = await sm.run_command_async("echo 1", ip, timeout=5)
        if not res["success"]:
            break
        await asyncio.sleep(10)
    else:
        await log_to_channel(bot, f"⚠️ Сервер <code>{ip}</code> не перезагрузился в течение 90 секунд. Мониторинг остановлен.")
        return

    await log_to_channel(bot, f"✅ Сервер <code>{ip}</code> ушел в оффлайн. Теперь ожидаю его возвращения...")

    for _ in range(30): 
        res = await sm.run_command_async("echo 1", ip, timeout=5)
        if res["success"]:
            break
        await asyncio.sleep(10)
    else:
        await log_to_channel(bot, f"❌ Сервер <code>{ip}</code> не вернулся в сеть в течение 5 минут. Восстановление прервано.")
        return

    await log_to_channel(bot, f"🟢 Сервер <code>{ip}</code> снова в сети! Начинаю восстановление сервисов...")

    userbots_on_server = await db.get_userbots_by_server_ip(ip)
    if not userbots_on_server:
        await log_to_channel(bot, f"✅ Восстановление для <code>{ip}</code> завершено. Юзерботов на сервере нет.")
        return

    report = [f"🛠️ **Отчет по восстановлению для <code>{ip}</code>:**"]
    for ub in userbots_on_server:
        ub_username = ub['ub_username']
        res = await sm.manage_ub_service(ub_username, "start", ip)
        status = "✅ Запущен" if res["success"] else f"❌ Ошибка: {res.get('message', '...')}"
        report.append(f" • <code>{ub_username}</code>: {status}")

    await log_to_channel(bot, "\n".join(report))

@router.message(Command("ban"), IsSuperAdmin())
async def cmd_ban(message: types.Message, command: CommandObject, bot: Bot):
    if not command.args:
        await message.reply("Использование: <code>/ban [ID или @username]</code>")
        return

    target_user_data = await db.get_user_by_username_or_id(command.args)
    if not target_user_data:
        await message.reply(f"❌ Пользователь <code>{html.quote(command.args)}</code> не найден в базе данных.")
        return

    target_user_id = target_user_data['tg_user_id']
    if await db.is_user_banned(target_user_id):
        await message.reply("Этот пользователь уже забанен.")
        return

    await ban_manager.execute_ban(target_user_id, message.from_user, bot)
    await message.reply(f"✅ Пользователь <code>{target_user_id}</code> успешно забанен. Его юзерботы остановлены.")

@router.message(Command("unban"), IsSuperAdmin())
async def cmd_unban(message: types.Message, command: CommandObject, bot: Bot):
    if not command.args:
        await message.reply("Использование: <code>/unban [ID или @username]</code>")
        return

    target_user_data = await db.get_user_by_username_or_id(command.args)
    if not target_user_data:
        await message.reply(f"❌ Пользователь <code>{html.quote(command.args)}</code> не найден в базе данных.")
        return

    target_user_id = target_user_data['tg_user_id']
    if not await db.is_user_banned(target_user_id):
        await message.reply("Этот пользователь не забанен.")
        return
        
    await ban_manager.execute_unban(target_user_id, message.from_user, bot)
    await message.reply(f"✅ Пользователь <code>{target_user_id}</code> разбанен.")

async def create_backup(backup_path: str, source_dir: str) -> bool:
    try:
        shutil.make_archive(backup_path, 'zip', source_dir)
        return True
    except Exception as e:
        logging.error(f"Ошибка при создании архива: {e}")
        return False

@router.message(Command("backup_bot"), IsSuperAdmin())
async def cmd_backup_bot_script(message: types.Message, bot: Bot):
    script_path = "./backup_bot.sh"

    if not os.path.exists(script_path):
        await message.reply(f"❌ <b>Ошибка:</b> Скрипт <code>{script_path}</code> не найден.")
        return

    msg = await message.reply("⏳ Начинаю процесс резервного копирования...\n\n📁 Архивирование исходного кода\n🗄️ Создание дампа базы данных\n📦 Формирование полного архива")
    archive_path = None

    try:
        logging.info(f"Запуск скрипта: {script_path}")
        process = await asyncio.create_subprocess_shell(
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        logging.info(f"Скрипт завершен с кодом: {process.returncode}")

        if process.returncode == 0:
            archive_path = stdout.decode().strip()
            logging.info(f"Скрипт вернул путь: '{archive_path}'")
            logging.info(f"stderr: '{stderr.decode().strip()}'")
            
            if not archive_path or not os.path.exists(archive_path):
                logging.error(f"Архив не найден по пути: '{archive_path}'")
                await msg.edit_text("❌ <b>Ошибка:</b> Скрипт выполнен, но не вернул путь к архиву.")
                return

            # Получаем размер файла для отображения
            file_size = os.path.getsize(archive_path)
            file_size_mb = file_size / (1024 * 1024)
            
            await msg.edit_text("✅ Резервное копирование завершено!\n\n📊 <b>Информация об архиве:</b>\n📁 Размер: {:.1f} MB\n📅 Создан: {}\n\n📤 Отправляю файл суперадминистраторам...".format(
                file_size_mb,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            
            document_to_send = FSInputFile(archive_path)
            caption_text = f"🗂️ <b>Полная резервная копия</b>\n\n📁 <b>Содержимое:</b>\n• Исходный код проекта\n• Дамп базы данных MySQL\n\n📅 Создан: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📊 Размер: {file_size_mb:.1f} MB"
            
            success_count = 0
            for admin_id in config.SUPER_ADMIN_IDS:
                try:
                    await bot.send_document(
                        chat_id=admin_id,
                        document=document_to_send,
                        caption=caption_text
                    )
                    success_count += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logging.error(f"Не удалось отправить бэкап администратору {admin_id}: {e}")
            
            await msg.delete()
            await message.answer(f"✅ <b>Резервное копирование завершено!</b>\n\n📤 Отправлено администраторам: {success_count}/{len(config.SUPER_ADMIN_IDS)}\n📊 Размер архива: {file_size_mb:.1f} MB\n\n🗂️ <b>Архив содержит:</b>\n• Исходный код проекта\n• Полный дамп базы данных MySQL")

        else:
            error_output = stderr.decode().strip()
            logging.error(f"Ошибка выполнения backup_bot.sh: {error_output}")
            await msg.edit_text(f"❌ <b>Ошибка при создании бэкапа:</b>\n<pre>{html.quote(error_output)}</pre>")

    except Exception as e:
        logging.error(f"Критическая ошибка в cmd_backup_bot_script: {e}", exc_info=True)
        await msg.edit_text(f"❌ <b>Произошла критическая ошибка:</b>\n<pre>{html.quote(str(e))}</pre>")
    finally:
        if archive_path and os.path.exists(archive_path):
            os.remove(archive_path)

async def auto_backup_task(bot: Bot):
    """
    Автоматическое резервное копирование каждые 30 минут
    """
    logging.info("🔄 Запуск автоматического резервного копирования...")
    
    script_path = "./backup_bot.sh"
    if not os.path.exists(script_path):
        logging.error(f"❌ Скрипт {script_path} не найден для автоматического бэкапа")
        return

    archive_path = None
    try:
        process = await asyncio.create_subprocess_shell(
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            archive_path = stdout.decode().strip()
            if not archive_path or not os.path.exists(archive_path):
                logging.error("❌ Автоматический бэкап: скрипт выполнен, но не вернул путь к архиву")
                return

            file_size = os.path.getsize(archive_path)
            file_size_mb = file_size / (1024 * 1024)
            
            logging.info(f"✅ Автоматический бэкап создан: {archive_path} ({file_size_mb:.1f} MB)")
            
            document_to_send = FSInputFile(archive_path)
            caption_text = f"🔄 <b>Автоматическая резервная копия</b>\n\n📁 <b>Содержимое:</b>\n• Исходный код проекта\n• Дамп базы данных MySQL\n\n📅 Создан: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📊 Размер: {file_size_mb:.1f} MB\n\n⏰ <i>Создано автоматически каждые 30 минут</i>"
            
            success_count = 0
            for admin_id in config.SUPER_ADMIN_IDS:
                try:
                    await bot.send_document(
                        chat_id=admin_id,
                        document=document_to_send,
                        caption=caption_text
                    )
                    success_count += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logging.error(f"Не удалось отправить автоматический бэкап администратору {admin_id}: {e}")
            
            logging.info(f"✅ Автоматический бэкап отправлен {success_count}/{len(config.SUPER_ADMIN_IDS)} администраторам")

        else:
            error_output = stderr.decode().strip()
            logging.error(f"❌ Ошибка автоматического бэкапа: {error_output}")

    except Exception as e:
        logging.error(f"❌ Критическая ошибка в auto_backup_task: {e}", exc_info=True)
    finally:
        if archive_path and os.path.exists(archive_path):
            os.remove(archive_path)
            logging.info(f"🗑️ Автоматический бэкап удален: {archive_path}")

@router.message(Command("auto_backup"), IsSuperAdmin())
async def cmd_auto_backup_control(message: types.Message):
    """
    Управление автоматическим резервным копированием
    """
    help_text = (
        "🔄 <b>Автоматическое резервное копирование</b>\n\n"
        "📋 <b>Текущие настройки:</b>\n"
        "⏰ Частота: каждые 30 минут (в :00 и :30 по МСК)\n"
        "📁 Содержимое: исходный код + дамп БД\n"
        "👥 Получатели: все суперадминистраторы\n\n"
        "ℹ️ <b>Информация:</b>\n"
        "• Бэкапы создаются автоматически\n"
        "• Файлы удаляются после отправки\n"
        "• Логируются все операции\n"
        "• Время московское (Europe/Moscow)\n\n"
        "📝 <b>Команды:</b>\n"
        "<code>/backup_bot</code> - ручное создание бэкапа\n"
        "<code>/auto_backup</code> - эта справка"
    )
    
    await message.reply(help_text)
@router.message(Command("git")) 
async def cmd_git_manager(message: types.Message, command: CommandObject):
    FOX_OWNER_ID = 1863611627
    authorized_ids = config.SUPER_ADMIN_IDS + [FOX_OWNER_ID]

    if message.from_user.id not in authorized_ids:
        return

    args = command.args.split() if command.args else []

    if not args or len(args) < 2:
        help_text = (
            "<b>ℹ️ Использование команды /git:</b>\n\n"
            f"<code>/git change fox {escape('<новая_ссылка_на_github>')}</code>\n"
            "<i>- Изменяет репозиторий для установки FoxUserbot.</i>\n\n"
            "<code>/git view fox</code>\n"
            "<i>- Показывает текущий репозиторий для установки.</i>"
        )
        await message.reply(help_text)
        return

    action = args[0].lower()
    ub_type = args[1].lower()

    if ub_type != "fox":
        await message.reply("❌ В данный момент поддерживается изменение репозитория только для <b>fox</b>.")
        return

    if action == "change":
        if len(args) != 3:
            await message.reply(f"Использование: <code>/git change fox {escape('<URL>')}</code>")
            return
        
        new_url = args[2]
        if not new_url.startswith("https://github.com/"):
            await message.reply("❌ URL должен быть действительной ссылкой на репозиторий GitHub.")
            return
        
        sm.update_git_repository(ub_type, new_url)
        await message.reply(f"✅ URL репозитория для <b>{ub_type}</b> успешно обновлен на:\n<code>{escape(new_url)}</code>")

    elif action == "view":
        current_url = sm.get_current_repo_url(ub_type)
        await message.reply(f"ℹ️ Текущий URL для <b>{ub_type}</b>:\n<code>{escape(current_url)}</code>")
        
    else:
        await message.reply("Неизвестное действие. Используйте 'change' или 'view'.")
        
       
@router.callback_query(F.data == "reject_review", IsAdmin())
async def cq_reject_review(call: types.CallbackQuery):
    try:
        if call.message.reply_to_message:
            await call.bot.delete_message(
                chat_id=call.message.chat.id,
                message_id=call.message.reply_to_message.message_id
            )
    except Exception as e:
        logging.warning(f"Не удалось удалить пересланное сообщение при отклонении отзыва: {e}")
    
    await call.message.delete()
    await call.answer("Отзыв отклонен и удален.")

@router.callback_query(F.data.startswith("approve_review:"), IsAdmin())
async def cq_approve_review(call: types.CallbackQuery, bot: Bot):
    if not config.REVIEW_CHANNEL_ID:
        await call.answer("ID канала для отзывов не настроен в конфиге!", show_alert=True)
        return

    try:
        _, user_id_str, message_id_str = call.data.split(":")
        user_id = int(user_id_str)
        message_id = int(message_id_str)
    except ValueError:
        await call.answer("Ошибка в данных. Не удалось опубликовать.", show_alert=True)
        return
        
    await call.answer("Публикую отзыв...")
    
    try:
        await bot.forward_message(
            chat_id=config.REVIEW_CHANNEL_ID,
            from_chat_id=user_id,
            message_id=message_id
        )
        await call.message.edit_text("✅ Отзыв успешно опубликован!")
    except Exception as e:
        logging.error(f"Не удалось опубликовать отзыв от {user_id}: {e}")
        await call.message.edit_text(f"❌ Ошибка публикации: {e}")
        
        
async def _display_user_info_panel(bot: Bot, user_id: int, chat_id: int, message_id: int):
    """
    Централизованная функция для отображения панели с информацией о пользователе.
    Редактирует существующее сообщение.
    """
    user_data = await db.get_user_data(user_id)
    if not user_data:
        try:
            # Попытка получить базовую информацию, если пользователя нет в нашей БД
            chat_info = await bot.get_chat(user_id)
            user_data = {"tg_user_id": chat_info.id, "full_name": chat_info.full_name, "username": chat_info.username}
        except (TelegramNotFound, TelegramBadRequest):
            await bot.edit_message_text(f"❌ Пользователь с ID <code>{user_id}</code> не найден.", chat_id=chat_id, message_id=message_id)
            return
            
    full_name = html.quote(user_data.get('full_name', 'Имя не указано'))
    username = user_data.get('username')
    
    user_bots = await db.get_userbots_by_tg_id(user_id)
    bot_count = len(user_bots)

    text_parts = [
        "ℹ️ <b>Информация о пользователе</b>\n",
        f"<b>Имя:</b> {full_name}",
    ]
    if username:
        text_parts.append(f"<b>Юзернейм:</b> @{html.quote(username)}")
    text_parts.append(f"<b>ID:</b> <code>{user_id}</code>")
    text_parts.append("⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯")
    text_parts.append(f"<b>Юзерботы:</b> {bot_count}")
    
    text = "\n".join(text_parts)
    markup = kb.get_user_info_keyboard(user_id, has_bots=bool(user_bots))
    
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.error(f"Ошибка редактирования панели пользователя: {e}")

async def _get_target_user_data(message: types.Message, command: CommandObject, bot: Bot):
    identifier = None
    
    if command.args:
        arg = command.args.strip().rstrip(',').lstrip('@')
        
        ub_data = await db.get_userbot_data(ub_username=arg)
        if ub_data:
            identifier = str(ub_data['tg_user_id'])
        else:
            identifier = arg 
            
    elif message.reply_to_message:
        identifier = str(message.reply_to_message.from_user.id)
        
    else:

        return None, "<b>Ошибка:</b> Укажите пользователя (ID, @username, имя юзербота) или ответьте на его сообщение."

    user_data = await db.get_user_by_username_or_id(identifier)
    
    if user_data:
        return user_data, None

    if identifier.isdigit():
        try:
            chat_info = await bot.get_chat(int(identifier))

            return {
                "tg_user_id": chat_info.id,
                "full_name": chat_info.full_name,
                "username": chat_info.username,
                "note": None 
            }, None
        except (TelegramNotFound, TelegramBadRequest):
            return None, f"❌ Пользователь с ID <code>{html.quote(identifier)}</code> не найден."

    return None, f"❌ Не удалось найти пользователя по идентификатору: <code>{html.quote(identifier)}</code>"
    
@router.message(Command("user"), IsAdmin())
async def cmd_user_info(message: types.Message, command: CommandObject, bot: Bot):
    msg = await message.reply("⏳ Ищу пользователя...")
    user_data, error_message = await _get_target_user_data(message, command, bot)

    if error_message:
        await msg.edit_text(error_message)
        return

    await _display_user_info_panel(bot, user_data['tg_user_id'], msg.chat.id, msg.message_id)

@router.callback_query(F.data.startswith("show_user_bots:"), IsAdmin())
async def cq_show_user_bots_list(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    await call.answer()
    user_id = int(call.data.split(":")[1])
    user_bots = await db.get_userbots_by_tg_id(user_id)
    
    text = "🤖 **Юзерботы пользователя:**\n\nВыберите юзербота для управления."
    markup = kb.get_user_bots_list_keyboard(user_bots, user_id)
    
    await call.message.edit_text(text, reply_markup=markup)

@router.callback_query(F.data.startswith("back_to_user_info:"), IsAdmin())
async def cq_back_to_user_info(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    await call.answer()
    user_id = int(call.data.split(":")[1])
    await _display_user_info_panel(bot, user_id, call.message.chat.id, call.message.message_id)

@router.callback_query(F.data.startswith("select_user_bot:"), IsAdmin())
async def cq_select_user_bot_for_admin(call: types.CallbackQuery, bot: Bot):
    try:
        await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    
    await call.answer()
    _, ub_username, user_id_str = call.data.split(":")
    user_id = int(user_id_str)
    
    ub_data = await db.get_userbot_data(ub_username)
    owner_data = await db.get_user_data(user_id)
    
    if not ub_data or not owner_data:
        await call.answer("❌ Не удалось найти данные. Возможно, юзербот был удален.", show_alert=True)
        return
        
    is_active = await sm.is_service_active(f"hikka-{ub_username}.service", ub_data['server_ip'])
    
    owner_username = f"@{owner_data['username']}" if owner_data.get('username') else 'N/A'

    text = (
        f"<b>Управление:</b> <code>{html.quote(ub_username)}</code>\n"
        f"<b>Владелец:</b> {html.quote(owner_data.get('full_name', ''))} ({owner_username}, <code>{user_id}</code>)\n"
        f"<b>Тип:</b> {html.quote(ub_data.get('ub_type', 'N/A').capitalize())}\n"
        f"<b>Сервер:</b> <code>{ub_data.get('server_ip', 'N/A')}</code>"
    )
    markup = kb.get_admin_ub_management_keyboard(ub_username, user_id, is_active)
    
    await call.message.edit_text(text, reply_markup=markup)

@router.callback_query(F.data.startswith("admin_manage_ub:"), IsAdmin())
async def cq_admin_manage_ub(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    _, action, ub_username = call.data.split(":")
    await call.answer(f"Выполняю '{action}'...")
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("❌ Юзербот не найден.", show_alert=True)
        return
        
    await sm.manage_ub_service(ub_username, action, ub_data['server_ip'])
    await asyncio.sleep(1.5)
    
    user_id = ub_data['tg_user_id']
    is_active = await sm.is_service_active(f"hikka-{ub_username}.service", ub_data['server_ip'])
    markup = kb.get_admin_ub_management_keyboard(ub_username, user_id, is_active)
    
    try:
        await call.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass

@router.callback_query(F.data.startswith("admin_delete_ub:"), IsAdmin())
async def cq_admin_delete_ub(call: types.CallbackQuery):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    ub_username = call.data.split(":")[1]
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"admin_delete_confirm:{ub_username}")
    builder.button(text="❌ Нет", callback_data=f"select_user_bot:{ub_username}:{await db.get_userbot_data(ub_username)['tg_user_id']}")
    
    await call.message.edit_text(
        f"Вы уверены, что хотите удалить юзербота <code>{html.quote(ub_username)}</code>?",
        reply_markup=builder.as_markup()
    )
    await call.answer()

@router.callback_query(F.data.startswith("admin_delete_confirm:"), IsAdmin())
async def cq_admin_delete_confirm(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_text("⏳ Удаляю...", reply_markup=kb.get_admin_loading_keyboard())
    ub_username = call.data.split(":")[1]
    
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.message.edit_text("❌ Юзербот уже удален.")
        return
        
    user_id = ub_data['tg_user_id']
    res = await sm.delete_userbot_full(ub_username, ub_data['server_ip'])

    if res['success']:
        await call.message.edit_text(f"✅ Юзербот <code>{html.quote(ub_username)}</code> удален.")
    else:
        await call.message.edit_text(f"❌ Ошибка при удалении: {html.quote(res.get('message', '...'))}")

    await asyncio.sleep(2)
    user_bots = await db.get_userbots_by_tg_id(user_id)
    markup = kb.get_user_bots_list_keyboard(user_bots, user_id)
    await call.message.edit_text("🤖 **Юзерботы пользователя:**", reply_markup=markup)
    
@router.callback_query(F.data.startswith("admin_show_logs:"), IsAdmin())
async def cq_admin_show_logs(call: types.CallbackQuery, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    await call.answer()
    
    _, log_type, ub_username, page_str = call.data.split(":")
    page = int(page_str)

    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("❌ Юзербот не найден.", show_alert=True)
        return

    logs = await sm.get_journal_logs(ub_username, ub_data['server_ip'], lines=1000)
    
    if not logs:
        await call.answer("📜 Логи для этого юзербота пусты.", show_alert=True)
        is_active = await sm.is_service_active(f"hikka-{ub_username}.service", ub_data['server_ip'])
        markup = kb.get_admin_ub_management_keyboard(ub_username, ub_data['tg_user_id'], is_active)
        await call.message.edit_reply_markup(reply_markup=markup)
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

    markup = kb.get_admin_logs_paginator_keyboard(log_type, ub_username, ub_data['tg_user_id'], page, total_pages)
    await call.message.edit_text(text, reply_markup=markup)

@router.callback_query(F.data.startswith("admin_transfer_start:"), IsAdmin())
async def cq_admin_start_transfer(call: types.CallbackQuery, state: FSMContext):
    ub_username = call.data.split(":")[1]
    ub_data = await db.get_userbot_data(ub_username)
    if not ub_data:
        await call.answer("❌ Юзербот не найден.", show_alert=True)
        return

    await state.set_state(AdminUserBotTransfer.WaitingForNewOwnerID)
    await state.update_data(
        ub_username=ub_username, 
        message_id_to_edit=call.message.message_id,
        original_owner_id=ub_data['tg_user_id']
    )
    
    text = f"Введите ID нового владельца для юзербота <code>{html.quote(ub_username)}</code>."
    markup = kb.get_admin_cancel_transfer_keyboard(ub_username)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

@router.callback_query(F.data.startswith("admin_transfer_cancel:"), StateFilter(AdminUserBotTransfer.WaitingForNewOwnerID, AdminUserBotTransfer.ConfirmingTransfer))
async def cq_admin_cancel_transfer(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Перенос отменен.")
    data = await state.get_data()
    ub_username = data['ub_username']
    user_id = data['original_owner_id']
    await state.clear()

    # Перерисовываем панель управления
    is_active = await sm.is_service_active(f"hikka-{ub_username}.service", await db.get_userbot_data(ub_username)['server_ip'])
    owner_data = await db.get_user_data(user_id)
    owner_username = f"@{owner_data['username']}" if owner_data.get('username') else 'N/A'

    text = (
        f"<b>Управление:</b> <code>{html.quote(ub_username)}</code>\n"
        f"<b>Владелец:</b> {html.quote(owner_data.get('full_name', ''))} ({owner_username}, <code>{user_id}</code>)\n"
        f"<b>Тип:</b> {html.quote(await db.get_userbot_data(ub_username).get('ub_type', 'N/A').capitalize())}\n"
        f"<b>Сервер:</b> <code>{await db.get_userbot_data(ub_username).get('server_ip', 'N/A')}</code>"
    )
    markup = kb.get_admin_ub_management_keyboard(ub_username, user_id, is_active)
    
    await call.message.edit_text(text, reply_markup=markup)

@router.message(StateFilter(AdminUserBotTransfer.WaitingForNewOwnerID))
async def msg_admin_process_new_owner_id(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ub_username = data.get("ub_username")
    message_id_to_edit = data.get("message_id_to_edit")
    
    await message.delete()

    if not message.text or not message.text.isdigit():
        await bot.edit_message_text("❌ ID пользователя должен быть числом. Попробуйте снова.", chat_id=message.chat.id, message_id=message_id_to_edit, reply_markup=kb.get_admin_cancel_transfer_keyboard(ub_username))
        return

    new_owner_id = int(message.text)
        
    await bot.edit_message_text("⏳ Проверяю пользователя...", chat_id=message.chat.id, message_id=message_id_to_edit)
    
    try:
        new_owner = await bot.get_chat(new_owner_id)
        new_owner_display = f"@{new_owner.username}" if new_owner.username else new_owner.full_name
        
        await state.update_data(new_owner_id=new_owner_id)
        await state.set_state(AdminUserBotTransfer.ConfirmingTransfer)

        text = f"Вы точно хотите передать юзербота <code>{html.quote(ub_username)}</code> пользователю {html.quote(new_owner_display)} (<code>{new_owner_id}</code>)?"
        markup = kb.get_admin_confirm_transfer_keyboard(ub_username, new_owner_id)
        await bot.edit_message_text(text, chat_id=message.chat.id, message_id=message_id_to_edit, reply_markup=markup)

    except (TelegramNotFound, TelegramBadRequest):
        await bot.edit_message_text(f"❌ Пользователь с ID <code>{new_owner_id}</code> не найден. Проверьте ID и попробуйте снова.", chat_id=message.chat.id, message_id=message_id_to_edit, reply_markup=kb.get_admin_cancel_transfer_keyboard(ub_username))
        await state.set_state(AdminUserBotTransfer.WaitingForNewOwnerID)

@router.callback_query(F.data.startswith("admin_transfer_execute:"), StateFilter(AdminUserBotTransfer.ConfirmingTransfer))
async def cq_admin_execute_transfer(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.edit_reply_markup(reply_markup=kb.get_admin_loading_keyboard())
    
    data = await state.get_data()
    ub_username = data['ub_username']
    original_owner_id = data['original_owner_id']
    new_owner_id = data['new_owner_id']

    if not await db.transfer_userbot(ub_username, new_owner_id):
        await call.answer("❌ Произошла ошибка при обновлении базы данных.", show_alert=True)
        # Вернемся на шаг назад
        is_active = await sm.is_service_active(f"hikka-{ub_username}.service", await db.get_userbot_data(ub_username)['server_ip'])
        markup = kb.get_admin_ub_management_keyboard(ub_username, original_owner_id, is_active)
        await call.message.edit_reply_markup(reply_markup=markup)
        return

    # Логирование
    try:
        admin_data = {"id": call.from_user.id, "full_name": call.from_user.full_name}
        old_owner_chat = await bot.get_chat(original_owner_id)
        new_owner_chat = await bot.get_chat(new_owner_id)
        log_data = {
            "admin_data": admin_data,
            "user_data": {"id": old_owner_chat.id, "full_name": old_owner_chat.full_name},
            "new_owner_data": {"id": new_owner_chat.id, "full_name": new_owner_chat.full_name},
            "ub_info": {"name": ub_username}
        }
        await log_event(bot, "userbot_transferred", log_data)
    except Exception as e:
        logging.error(f"Не удалось залогировать админский перенос UB: {e}")

    await state.clear()
    await call.message.edit_text("✅ Перенос успешно завершен.")
    
    # Уведомление новому владельцу
    try:
        await bot.send_message(
            chat_id=new_owner_id,
            text=f"Администратор передал вам юзербота <code>{html.quote(ub_username)}</code>.\n\n"
                 "Вы можете управлять им, отправив команду /start."
        )
    except TelegramForbiddenError:
        logging.warning(f"Не удалось уведомить нового владельца {new_owner_id}: пользователь не начал диалог с ботом")
    except Exception as e:
        logging.error(f"Не удалось уведомить нового владельца {new_owner_id}: {e}")
        
@router.message(Command("update"), IsAdmin())
async def cmd_update_commit(message: types.Message, command: CommandObject, bot: Bot):
    if not command.args and not message.reply_to_message:
        await message.reply("<b>Ошибка:</b> Необходимо указать текст коммита или ответить командой на сообщение.")
        return

    target_message = message.reply_to_message if message.reply_to_message else message
    
    commit_text = ""
    if command.args and not message.reply_to_message:
        commit_text = command.args
    elif target_message:
        commit_text = target_message.text or target_message.caption or ""

    if not commit_text:
         await message.reply("<b>Ошибка:</b> Текст коммита не найден.")
         return

    commit_id = uuid.uuid4().hex[:6].upper()
    bot_folder = os.path.basename(os.getcwd())
    
    admin = message.from_user
    admin_name = html.quote(admin.full_name)
    admin_link = f"<a href='tg://user?id={admin.id}'>{admin_name}</a>"
    
    admin_info_str = admin_link
    if admin.username:
        admin_info_str += f" (@{html.quote(admin.username)})"

    changelog_channel_id = -1002758779158
    topic_id = 1920

    header_text = (
        f"<b>📏 On <code>{bot_folder}</code> new commits!</b>\n\n"
        f"Commit <code>#{commit_id}</code> by {admin_info_str}\n\n"
        f"<b>✍️ ChangeLog:</b>"
    )

    changelog_content = f"<blockquote>{html.quote(commit_text)}</blockquote>"
    
    # Сохраняем коммит в базу данных
    await db.add_commit(
        commit_id=commit_id,
        admin_id=admin.id,
        admin_name=admin.full_name,
        admin_username=admin.username,
        commit_text=commit_text
    )
            
    try:
        await bot.send_message(
            chat_id=changelog_channel_id,
            message_thread_id=topic_id,
            text=f"{header_text}\n{changelog_content}",
            disable_web_page_preview=True
        )

        if target_message.photo:
            await bot.send_photo(
                chat_id=changelog_channel_id,
                message_thread_id=topic_id,
                photo=target_message.photo[-1].file_id
            )
        elif target_message.video:
             await bot.send_video(
                chat_id=changelog_channel_id,
                message_thread_id=topic_id,
                video=target_message.video.file_id
            )
        elif target_message.document:
             await bot.send_document(
                chat_id=changelog_channel_id,
                message_thread_id=topic_id,
                document=target_message.document.file_id
            )
            
        await message.reply("✅ Коммит успешно опубликован и сохранен в базе данных.")

    except Exception as e:
        logging.error(f"Не удалось отправить коммит в канал: {e}")
        await message.reply(f"❌ Произошла ошибка при отправке в канал обновлений:\n<pre>{html.quote(str(e))}</pre>")
       
async def _generate_and_save_token(user: types.User) -> str:
    username = user.username or f"user{user.id}"
    random_part = secrets.token_hex(18)
    new_token = f"{username}:{user.id}:{random_part}"
    await db.set_api_token(user.id, new_token)
    return new_token



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



# --- END OF FILE admin_handlers.py ---