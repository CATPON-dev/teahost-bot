import asyncio
import logging
from html import escape
import time

import server_config
import system_manager as sm
import database as db

async def get_userbot_status(username: str, server_ip: str) -> str:
    """Получает статус юзербота"""
    try:
        # Проверяем, запущен ли сервис юзербота
        service_name = f"hikka-{username}.service"
        is_active = await sm.is_service_active(service_name, server_ip)
        return "🟢" if is_active else "🔴"
    except Exception as e:
        logging.error(f"Error getting status for {username}: {e}")
        return "🟡"

def get_userbot_type_emoji(ub_type: str) -> str:
    """Получает эмодзи типа юзербота"""
    type_mapping = {
        "fox": "🦊",
        "heroku": "🪐", 
        "hikka": "🌘",
        "legacy": "🌙"
    }
    return type_mapping.get(ub_type.lower(), "🦊")

async def get_all_userbot_statuses_on_server(usernames: list, server_ip: str) -> dict:
    """Получает статусы всех юзерботов на сервере через одно SSH-соединение"""
    try:
        # Создаем команду для проверки всех сервисов сразу
        service_names = [f"hikka-{username}.service" for username in usernames]
        service_list = " ".join(service_names)
        
        # Команда для проверки статуса всех сервисов (более надежная)
        cmd = f"systemctl list-units --full --all --plain --no-legend {service_list}"
        
        logging.info(f"Executing command on {server_ip}: {cmd}")
        result = await sm.run_command_async(cmd, server_ip, check_output=True, timeout=30)
        
        if result.get("success") and result.get("output"):
            statuses = {}
            logging.info(f"Raw output from server {server_ip}: {result['output']}")
            for line in result["output"].strip().split('\n'):
                parts = line.split()
                if len(parts) >= 4:
                    service_name = parts[0]
                    active_state = parts[2]
                    username = service_name.replace('hikka-', '').replace('.service', '')
                    status_emoji = "🟢" if active_state == "active" else "🔴"
                    statuses[username] = status_emoji
                    # Отладочная информация
                    logging.info(f"Service {service_name}: status='{active_state}', emoji='{status_emoji}'")
            
            # Добавляем недостающие юзерботы как неактивные
            for username in usernames:
                if username not in statuses:
                    statuses[username] = "🔴"
            
            return statuses
        else:
            logging.error(f"Failed to get statuses for server {server_ip}: {result.get('error', 'Unknown error')}")
            # Если команда не выполнилась, возвращаем все как неактивные
            return {username: "🔴" for username in usernames}
            
    except Exception as e:
        logging.error(f"Error getting statuses for server {server_ip}: {e}")
        return {username: "🔴" for username in usernames}



async def _check_sessions_on_server(ip: str):
    # Запускаем одну команду на сервере, чтобы получить количество .session-файлов для каждого юзербота
    command = (
        "for d in /home/ub*; do "
        "cnt=$(find \"$d\" -type f -name '*.session' 2>/dev/null | wc -l); "
        "name=$(basename \"$d\"); "
        "echo \"$name:$cnt\"; "
        "done"
    )
    res = await sm.run_command_async(command, ip, check_output=True, timeout=60)
    users_with_sessions = {}
    users_with_no_sessions = {}
    users_not_in_db = {}

    if res.get("success") and res.get("output"):
        for line in res["output"].splitlines():
            if ":" not in line:
                continue
            name, cnt = line.split(":", 1)
            try:
                cnt = int(cnt)
            except ValueError:
                continue
            
            # Исключаем системного пользователя ubuntu
            if name == "ubuntu":
                continue
                
            # Проверяем, есть ли такой юзербот в базе
            ub_data = await db.get_userbot_data(name)
            if ub_data is None:
                users_not_in_db[name] = cnt
            elif cnt > 0:
                users_with_sessions[name] = cnt
            else:
                users_with_no_sessions[name] = 0
    else:
        # Если команда не выполнилась, считаем, что ни у кого нет сессий
        logging.error(f"Session check command failed on {ip}: {res.get('error')}")
        # Можно получить список юзерботов для отчёта
        bots_on_this_server = await db.get_userbots_by_server_ip(ip)
        for bot in bots_on_this_server:
            ub_username = bot.get('ub_username')
            if ub_username and ub_username != "ubuntu":  # Исключаем ubuntu и здесь
                users_with_no_sessions[ub_username] = 0

    return users_with_sessions, users_with_no_sessions, users_not_in_db

async def check_all_remote_sessions():
    servers = server_config.get_servers()
    remote_servers_ips = [ip for ip in servers if ip != sm.LOCAL_IP]
    
    if not remote_servers_ips:
        return {}

    tasks = [_check_sessions_on_server(ip) for ip in remote_servers_ips]
    results = await asyncio.gather(*tasks)
    
    server_session_map = dict(zip(remote_servers_ips, results))
    
    return server_session_map

async def format_session_check_report(server_results: dict, view_mode: str, page: int = 0):
    servers_info = server_config.get_servers()
    report_parts = []
    found_any = False
    MAX_LEN = 3000
    ITEMS_PER_PAGE = 4  # Количество серверов на страницу
    
    # Собираем все серверы с данными
    all_servers = []
    
    # Собираем все юзерботы для каждого сервера заранее
    all_usernames_by_server = {}
    all_usernames_flat = []
    
    if view_mode == "has_session":
        report_parts.append("✅ <b>Пользователи, у которых найдены сессии:</b>")
        for ip, (user_sessions, _, not_in_db) in server_results.items():
            usernames = list(user_sessions.keys()) + [username for username, count in not_in_db.items() if count > 0]
            all_usernames_by_server[ip] = usernames
            all_usernames_flat.extend(usernames)
            
    elif view_mode == "no_session":
        report_parts.append("👻 <b>Пользователи, у которых НЕ найдены сессии:</b>")
        for ip, (_, no_user_sessions, not_in_db) in server_results.items():
            usernames = list(no_user_sessions.keys()) + [username for username, count in not_in_db.items() if count == 0]
            all_usernames_by_server[ip] = usernames
            all_usernames_flat.extend(usernames)
    
    # Получаем данные из БД для всех юзерботов сразу
    ub_data_tasks = [db.get_userbot_data(username) for username in all_usernames_flat]
    ub_data_results = await asyncio.gather(*ub_data_tasks, return_exceptions=True)
    ub_data_map = dict(zip(all_usernames_flat, ub_data_results))
    
    # Отладочная информация о данных из БД
    for username, ub_data in ub_data_map.items():
        if isinstance(ub_data, Exception):
            logging.error(f"Error getting data for {username}: {ub_data}")
        elif ub_data is None:
            logging.warning(f"No data in DB for {username}")
        else:
            logging.info(f"DB data for {username}: {ub_data}")
    
    # Получаем статусы всех юзерботов на всех серверах параллельно
    status_tasks = [get_all_userbot_statuses_on_server(usernames, ip) for ip, usernames in all_usernames_by_server.items()]
    status_results = await asyncio.gather(*status_tasks)
    status_map = dict(zip(all_usernames_by_server.keys(), status_results))
    
    if view_mode == "has_session":
        for ip, (user_sessions, _, not_in_db) in server_results.items():
            blockquote_parts = []
            server_details = servers_info.get(ip, {})
            server_flag = server_details.get("flag", "🏳️")
            server_code = server_details.get("code", "Unknown")
            
            statuses = status_map.get(ip, {})
            
            # Обрабатываем обычные юзерботы
            for i, (username, count) in enumerate(sorted(user_sessions.items())):
                ub_data = ub_data_map.get(username)
                status = statuses.get(username, "🟡")
                
                if isinstance(ub_data, Exception) or ub_data is None:
                    ub_type = "⚠️"
                else:
                    raw_ub_type = ub_data.get("ub_type", "fox")
                    ub_type = get_userbot_type_emoji(raw_ub_type)
                    # Отладочная информация
                    logging.info(f"Userbot {username}: raw_type='{raw_ub_type}', emoji='{ub_type}'")
                
                blockquote_parts.append(f"  - {ub_type} <code>{escape(username)}</code> {status}")
            
            # Обрабатываем юзерботы, которых нет в БД, но есть папка
            for username, count in sorted(not_in_db.items()):
                if count > 0:
                    status = statuses.get(username, "🟡")
                    blockquote_parts.append(f"  - ⚠️ <code>{escape(username)}</code> {status}")
            
            if blockquote_parts:
                all_servers.append({
                    'ip': ip,
                    'flag': server_flag,
                    'code': server_code,
                    'content': f"\n{server_flag} <b>{server_code}</b> (<code>{ip}</code>)\n<blockquote>{chr(10).join(blockquote_parts)}</blockquote>"
                })
        
        if not all_servers:
            return "На серверах не найдено пользователей с файлами сессий из числа тех, кто должен там быть.", 1
            
    elif view_mode == "no_session":
        for ip, (_, no_user_sessions, not_in_db) in server_results.items():
            blockquote_parts = []
            server_details = servers_info.get(ip, {})
            server_flag = server_details.get("flag", "🏳️")
            server_code = server_details.get("code", "Unknown")
            
            statuses = status_map.get(ip, {})
            
            # Обрабатываем обычные юзерботы
            for username in sorted(no_user_sessions.keys()):
                ub_data = ub_data_map.get(username)
                status = statuses.get(username, "🟡")
                
                if isinstance(ub_data, Exception) or ub_data is None:
                    ub_type = "⚠️"
                else:
                    raw_ub_type = ub_data.get("ub_type", "fox")
                    ub_type = get_userbot_type_emoji(raw_ub_type)
                    # Отладочная информация
                    logging.info(f"Userbot {username}: raw_type='{raw_ub_type}', emoji='{ub_type}'")
                
                blockquote_parts.append(f"  - {ub_type} <code>{escape(username)}</code> {status}")
            
            # Обрабатываем юзерботы, которых нет в БД, но есть папка
            for username, count in sorted(not_in_db.items()):
                if count == 0:
                    status = statuses.get(username, "🟡")
                    blockquote_parts.append(f"  - ⚠️ <code>{escape(username)}</code> {status}")
            
            if blockquote_parts:
                all_servers.append({
                    'ip': ip,
                    'flag': server_flag,
                    'code': server_code,
                    'content': f"\n{server_flag} <b>{server_code}</b> (<code>{ip}</code>)\n<blockquote>{chr(10).join(blockquote_parts)}</blockquote>"
                })
        
        if not all_servers:
            return "✅ У всех пользователей, которые должны быть на серверах, есть файлы сессий.", 1
    
    # Пагинация
    total_pages = max(1, (len(all_servers) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    logging.info(f"Пагинация: страница {page}, всего серверов {len(all_servers)}, элементов на страницу {ITEMS_PER_PAGE}")
    logging.info(f"Индексы: {start_idx} - {end_idx}, всего страниц: {total_pages}")
    
    # Добавляем серверы для текущей страницы
    for server in all_servers[start_idx:end_idx]:
        report_parts.append(server['content'])
    
    # Добавляем информацию о пагинации
    if total_pages > 1:
        report_parts.append(f"\n📄 Страница {page + 1} из {total_pages}")
    
    result = "\n".join(report_parts)
    
    # Проверяем баланс HTML-тегов
    open_b = result.count('<b>')
    close_b = result.count('</b>')
    open_i = result.count('<i>')
    close_i = result.count('</i>')
    open_code = result.count('<code>')
    close_code = result.count('</code>')
    
    total_open = open_b + open_i + open_code
    total_close = close_b + close_i + close_code
    
    if total_open != total_close:
        logging.warning(f"HTML tag mismatch in session check report: {total_open} open, {total_close} close")
        logging.warning(f"Details: <b>: {open_b}/{close_b}, <i>: {open_i}/{close_i}, <code>: {open_code}/{close_code}")
        # Если есть проблемы с тегами, убираем HTML-разметку
        result = result.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '').replace('<code>', '').replace('</code>', '')
    
    # Отладочная информация
    logging.info(f"Generated report length: {len(result)}, Total pages: {total_pages}")
    
    # Дополнительная проверка на правильность HTML
    if '<b>' in result and '</b>' not in result:
        logging.error("Found <b> without closing tag")
        result = result.replace('<b>', '')
    if '</b>' in result and '<b>' not in result:
        logging.error("Found </b> without opening tag")
        result = result.replace('</b>', '')
    
    return result, total_pages