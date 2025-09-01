import asyncio
import logging
import math
from html import escape
from aiogram import Bot
import server_config
import system_manager as sm
import database as db

CHECK_SEMAPHORE = asyncio.Semaphore(10)

def pluralize_session(count):
    if count % 10 == 1 and count % 100 != 11:
        return "сессия"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        return "сессии"
    else:
        return "сессий"

async def _check_sessions_on_server(ip: str):
    base_path = "/root/api/volumes"
    command = f"""
    for D in {base_path}/ub*/data; do
        if [ -d "$D" ]; then
            SESSION_FILES=$(find "$D" -maxdepth 1 -type f -name "*.session" -printf "%f\\n")
            SESSION_COUNT=$(echo "$SESSION_FILES" | grep -c .)
            UB_NAME=$(basename "$(dirname "$D")")
            CLEAN_FILES=$(echo "$SESSION_FILES" | tr '\\n' ',' | sed 's/,$//')
            echo "${{UB_NAME}}:${{SESSION_COUNT}}:${{CLEAN_FILES}}"
        fi
    done
    """
    
    async with CHECK_SEMAPHORE:
        res = await sm.run_command_async(command, ip, check_output=True, timeout=180)
    
    suspicious = {}
    normal = {}

    if res.get("success") and res.get("output"):
        all_bots_on_server = {bot['ub_username'] for bot in await db.get_userbots_by_server_ip(ip)}
        
        found_on_server = set()
        for line in res["output"].strip().splitlines():
            if ":" not in line: continue
            
            parts = line.split(":", 2)
            if len(parts) != 3: continue
            
            name, count_str, files_str = parts
            found_on_server.add(name)
            try:
                count = int(count_str)
            except ValueError:
                count = 0
            
            files = files_str.split(',') if files_str else []
            user_data = {'count': count, 'files': files}

            if count > 1:
                suspicious[name] = user_data
            else:
                normal[name] = user_data
        
        for bot_name in all_bots_on_server:
            if bot_name not in found_on_server:
                normal[bot_name] = {'count': 0, 'files': []}

    return suspicious, normal

async def check_all_remote_sessions():
    servers = server_config.get_servers()
    remote_servers_ips = [ip for ip in servers if ip != sm.LOCAL_IP]
    
    if not remote_servers_ips:
        return {}

    tasks = [_check_sessions_on_server(ip) for ip in remote_servers_ips]
    results = await asyncio.gather(*tasks)
    
    server_session_map = {}
    for ip, (suspicious, normal) in zip(remote_servers_ips, results):
        server_session_map[ip] = { "suspicious": suspicious, "normal": normal }
    
    return server_session_map

async def format_session_check_report(server_results: dict, view_mode: str, page: int = 0):
    servers_info = server_config.get_servers()
    all_usernames = {uname for ip_data in server_results.values() for view in ip_data.values() for uname in view.keys()}
    ub_data_tasks = [db.get_userbot_data(username) for username in all_usernames]
    ub_data_results = await asyncio.gather(*ub_data_tasks)
    ub_data_map = {uname: data for uname, data in zip(all_usernames, ub_data_results) if data}

    if view_mode == "suspicious":
        header = "⚠️ <b>Пользователи с >1 сессией:</b>\n"
        suspicious_by_server = {}
        for ip, session_data in server_results.items():
            if session_data.get("suspicious"):
                suspicious_by_server[ip] = session_data["suspicious"]
        
        if not suspicious_by_server:
            return "<blockquote>✅ Проверка завершена. Подозрительных пользователей не найдено.</blockquote>", 1

        content_parts = []
        for ip, users in sorted(suspicious_by_server.items(), key=lambda item: servers_info.get(item[0], {}).get('name', item[0])):
            server_details = servers_info.get(ip, {})
            server_flag = server_details.get("flag", "🏳️")
            server_code = server_details.get("code", "N/A")
            user_lines = []
            for username, data in sorted(users.items()):
                ub_data = ub_data_map.get(username)
                owner_id = ub_data.get('tg_user_id') if ub_data else None
                owner_info = ""
                if owner_id:
                    owner_data = await db.get_user_data(owner_id)
                    owner_info = f"<i>({escape(owner_data.get('full_name', ''))}, <code>{owner_id}</code>)</i>" if owner_data else f"<i>(ID: <code>{owner_id}</code>)</i>"
                
                files_str = ", ".join([f"<code>{escape(f)}</code>" for f in data['files']])
                user_lines.append(f"  - <b>{escape(username)}</b> {owner_info}\n    └ 📂 {data['count']} шт.: {files_str}")
            
            content_parts.append(f"<b>{server_flag} {server_code}</b>\n" + "\n".join(user_lines))
        
        full_text = "<blockquote>" + header + "\n" + "\n\n".join(content_parts) + "</blockquote>"
        return full_text, 1
        
    else: # view_mode == "normal"
        header = "✅ <b>Пользователи с 0 или 1 сессией:</b>\n"
        ITEMS_PER_PAGE = 15
        
        all_normal_users = []
        for ip, session_data in server_results.items():
            server_details = servers_info.get(ip, {})
            for username, data in session_data.get("normal", {}).items():
                all_normal_users.append({
                    'username': username, 'count': data['count'], 'server_code': server_details.get('code', 'N/A'),
                    'server_flag': server_details.get('flag', '🏳️')
                })
        
        if not all_normal_users:
            return "<blockquote>ℹ️ В этой категории нет пользователей.</blockquote>", 1
            
        all_normal_users.sort(key=lambda x: (x['server_code'], x['username']))
        
        total_pages = math.ceil(len(all_normal_users) / ITEMS_PER_PAGE)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        
        paginated_users = all_normal_users[start_idx:end_idx]

        user_lines = []
        for user in paginated_users:
            ub_data = ub_data_map.get(user['username'])
            owner_id = ub_data.get('tg_user_id') if ub_data else 'N/A'
            user_lines.append(f"{user['server_flag']} {user['server_code']} - <b>{escape(user['username'])}</b> (<code>{owner_id}</code>) - {user['count']} {pluralize_session(user['count'])}")
            
        content_text = "\n".join(user_lines)
        pagination_info = f"\n📄 Страница {page + 1} из {total_pages}" if total_pages > 1 else ""
        
        full_text = "<blockquote>" + header + "\n" + content_text + pagination_info + "</blockquote>"
            
        return full_text, total_pages
        
SESSION_VIOLATION_CACHE = set()

async def check_and_log_session_violations(bot: Bot, force: bool = False) -> int:
    from channel_logger import log_to_channel

    if not force:
        logging.info("Running scheduled check for session violations...")
    
    server_results = await check_all_remote_sessions()
    if not server_results:
        return 0

    servers_info = server_config.get_servers()
    all_suspicious_users = {}

    for ip, data in server_results.items():
        for username, session_data in data.get("suspicious", {}).items():
            if username not in all_suspicious_users:
                all_suspicious_users[username] = {
                    'ip': ip,
                    'count': session_data['count'],
                    'files': session_data['files']
                }

    if not all_suspicious_users:
        if not force:
            logging.info("No session violations found.")
        return 0

    violations_found_count = 0
    for username, details in all_suspicious_users.items():
        if not force and username in SESSION_VIOLATION_CACHE:
            continue

        violations_found_count += 1
        ub_data = await db.get_userbot_data(username)
        if not ub_data:
            continue

        owner_id = ub_data.get('tg_user_id')
        owner_data = await db.get_user_data(owner_id) if owner_id else None

        user_info = f"<code>{username}</code>"
        if owner_data:
            full_name = escape(owner_data.get('full_name', ''))
            user_link = f"<a href='tg://user?id={owner_id}'>{full_name}</a>"
            user_info = f"{user_link} (<code>{owner_id}</code>)"
        
        server_details = servers_info.get(details['ip'], {})
        server_flag = server_details.get("flag", "🏳️")
        server_code = server_details.get("code", "N/A")
        
        files_str = "\n".join([f"    - <code>{escape(f)}</code>" for f in details['files']])

        log_tag = "#Принудительная_проверка_сессий" if force else "#Нарушение_правил"
        
        log_text = (
            f"<b>{log_tag} (Обнаружено >1 сессии)</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_info}\n"
            f"🤖 <b>Юзербот:</b> <code>{escape(username)}</code>\n"
            f"🖥️ <b>Сервер:</b> {server_flag} {server_code}\n\n"
            f"🔎 <b>Обнаружено сессий:</b> {details['count']} шт.\n"
            f"📂 <b>Файлы сессий:</b>\n{files_str}"
        )

        await log_to_channel(bot, log_text)
        if not force:
            SESSION_VIOLATION_CACHE.add(username)
        await asyncio.sleep(1)

    return violations_found_count