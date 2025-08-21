# --- START OF FILE session_checker.py ---

import asyncio
import logging
from html import escape
import time

import server_config
import system_manager as sm
import database as db
from api_manager import api_manager

CHECK_SEMAPHORE = asyncio.Semaphore(8)

async def _check_sessions_on_server_docker(ip: str):
    base_path = "/root/api/volumes"
    
    command = f"""
    for D in {base_path}/ub*/; do
        if [ -d "${{D}}data" ]; then
            UB_NAME=$(basename "$D")
            
            SESSION_FILES=$(find "${{D}}data/" -maxdepth 1 -type f \\( -name "heroku*" -o -name "hikka*" -o -name "legacy*" -o -name "account*" -o -name "*.session" \\) -printf "%f\\n")
            
            SESSION_COUNT=$(echo "$SESSION_FILES" | grep -c .)
            CLEAN_FILES=$(echo "$SESSION_FILES" | tr '\\n' ',' | sed 's/,$//')
            
            echo "${{UB_NAME}}:${{SESSION_COUNT}}:${{CLEAN_FILES}}"
        fi
    done
    """
    
    async with CHECK_SEMAPHORE:
        res = await sm.run_command_async(command, ip, check_output=True, timeout=120)
    
    found_users = {}
    
    if res.get("success") and res.get("output"):
        for line in res["output"].strip().splitlines():
            if ":" not in line:
                continue
            
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            
            name, count_str, files_str = parts
            try:
                count = int(count_str)
            except ValueError:
                count = 0
            
            files = files_str.split(',') if files_str else []
            found_users[name] = {'count': count, 'files': files}

    users_with_sessions = {}
    users_with_no_sessions = {}
    
    bots_on_this_server = await db.get_userbots_by_server_ip(ip)
    db_usernames = {bot['ub_username'] for bot in bots_on_this_server}

    for ub_name in db_usernames:
        if ub_name in found_users and found_users[ub_name]['count'] > 0:
            users_with_sessions[ub_name] = found_users[ub_name]
        else:
            users_with_no_sessions[ub_name] = {'count': 0, 'files': []}
            
    users_not_in_db = {
        name: data for name, data in found_users.items()
        if name not in db_usernames and data['count'] > 0
    }

    return users_with_sessions, users_with_no_sessions, users_not_in_db

async def check_all_remote_sessions_docker():
    servers = server_config.get_servers()
    remote_servers_ips = [ip for ip in servers if ip != sm.LOCAL_IP]
    
    if not remote_servers_ips:
        return {}

    tasks = [_check_sessions_on_server_docker(ip) for ip in remote_servers_ips]
    results = await asyncio.gather(*tasks)
    
    server_session_map = dict(zip(remote_servers_ips, results))
    
    return server_session_map

def get_userbot_type_emoji(ub_type: str) -> str:
    type_mapping = {
        "fox": "🦊", "heroku": "🪐", "hikka": "🌘", "legacy": "🌙"
    }
    return type_mapping.get(ub_type.lower() if ub_type else "", "❓")

async def get_all_userbot_statuses_on_server(usernames: list, server_ip: str) -> dict:
    statuses = {}
    tasks = []
    for username in usernames:
        async def get_status_with_semaphore(uname):
            async with CHECK_SEMAPHORE:
                return await api_manager.get_container_status(uname, server_ip)
        tasks.append(get_status_with_semaphore(username))
    
    results = await asyncio.gather(*tasks)
    
    for username, res in zip(usernames, results):
        if res.get("success") and res.get("data", {}).get("status") == "running":
            statuses[username] = "🟢"
        else:
            statuses[username] = "🔴"
            
    return statuses

async def format_session_check_report(server_results: dict, view_mode: str, page: int = 0):
    servers_info = server_config.get_servers()
    report_parts = []
    ITEMS_PER_PAGE = 4
    
    all_servers_content = []

    usernames_to_fetch = set()
    for ip, (with_session, without_session, not_in_db) in server_results.items():
        if view_mode == "has_session":
            usernames_to_fetch.update(with_session.keys())
            usernames_to_fetch.update(not_in_db.keys())
        elif view_mode == "no_session":
            usernames_to_fetch.update(without_session.keys())

    ub_data_tasks = [db.get_userbot_data(username) for username in usernames_to_fetch]
    ub_data_results = await asyncio.gather(*ub_data_tasks)
    ub_data_map = {uname: data for uname, data in zip(usernames_to_fetch, ub_data_results) if data}

    status_tasks = {ip: get_all_userbot_statuses_on_server(list(usernames_to_fetch), ip) for ip in server_results}
    status_results = await asyncio.gather(*status_tasks.values())
    status_map = dict(zip(status_tasks.keys(), status_results))

    if view_mode == "has_session":
        report_parts.append("✅ <b>Пользователи, у которых найдены сессии:</b>")
        data_source = {ip: (res[0], res[2]) for ip, res in server_results.items()}
    else:
        report_parts.append("👻 <b>Пользователи, у которых НЕ найдены сессии:</b>")
        data_source = {ip: (res[1], {}) for ip, res in server_results.items()}

    for ip, (user_sessions, not_in_db) in data_source.items():
        blockquote_parts = []
        server_details = servers_info.get(ip, {})
        server_flag = server_details.get("flag", "🏳️")
        server_code = server_details.get("code", "Unknown")
        
        current_statuses = status_map.get(ip, {})

        all_users_on_server = list(user_sessions.items())
        if view_mode == "has_session":
             all_users_on_server.extend(not_in_db.items())
        
        for username, data in sorted(all_users_on_server):
            ub_data = ub_data_map.get(username)
            status = current_statuses.get(username, "🟡")
            ub_type_emoji = get_userbot_type_emoji(ub_data.get('ub_type')) if ub_data else "⚠️"
            
            session_info = ""
            if data['count'] > 0:
                files_str = ", ".join([f"<code>{escape(f)}</code>" for f in data['files']])
                session_info = f" ({data['count']} сессии: {files_str})"

            blockquote_parts.append(f"  - {ub_type_emoji} <code>{escape(username)}</code> {status}{session_info}")

        if blockquote_parts:
            all_servers_content.append(f"\n{server_flag} <b>{server_code}</b> (<code>{ip}</code>)\n<blockquote>" + "\n".join(blockquote_parts) + "</blockquote>")

    if not all_servers_content:
        if view_mode == "has_session":
            report_parts.append("\n<i>На серверах не найдено пользователей с файлами сессий.</i>")
        else:
            report_parts.append("\n<i>✅ У всех пользователей есть файлы сессий.</i>")
        return "\n".join(report_parts), 1

    total_pages = max(1, (len(all_servers_content) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    report_parts.extend(all_servers_content[start_idx:end_idx])
    
    if total_pages > 1:
        report_parts.append(f"\n📄 Страница {page + 1} из {total_pages}")
    
    return "\n".join(report_parts), total_pages