# --- START OF FILE server_config.py ---
import json
import os
from typing import Dict, Any
import datetime

IP_CONFIG_FILE = "ip.json"
SERVER_STATUS_FILE = "server_status.json"
DELETED_SERVERS_FILE = "deleted_servers.json"
DEFAULT_API_PORT = "8000"
DEFAULT_API_TOKEN = "kivWJmOe2ey9u50uCqEwCIcHstCwuZslu7QK4YcEsCTGQcUTx33JC3bZveOzvr8y"

def get_servers() -> Dict[str, Any]:
    if not os.path.exists(IP_CONFIG_FILE):
        return {}
    try:
        with open(IP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _save_servers(servers: dict) -> bool:
    try:
        for ip, server_data in servers.items():
            if 'api_url' not in server_data:
                server_data['api_url'] = f"http://{ip}:{DEFAULT_API_PORT}"
            if 'api_token' not in server_data:
                server_data['api_token'] = DEFAULT_API_TOKEN
            if 'status' not in server_data:
                server_data['status'] = 'true'
            if 'slots' not in server_data:
                server_data['slots'] = 0
        
        backup_file = f"{IP_CONFIG_FILE}.bak"
        if os.path.exists(IP_CONFIG_FILE):
            os.replace(IP_CONFIG_FILE, backup_file)
        
        with open(IP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(servers, f, indent=4, ensure_ascii=False)
            
        if os.path.getsize(IP_CONFIG_FILE) == 0:
            if os.path.exists(backup_file):
                os.replace(backup_file, IP_CONFIG_FILE)
            return False
            
        return True
        
    except Exception as e:
        print(f"Ошибка сохранения серверов: {str(e)}")
        if os.path.exists(backup_file):
            os.replace(backup_file, IP_CONFIG_FILE)
        return False

def _archive_deleted_server(ip: str, server_data: dict):
    try:
        if os.path.exists(DELETED_SERVERS_FILE):
            with open(DELETED_SERVERS_FILE, 'r', encoding='utf-8') as f:
                archive = json.load(f)
        else:
            archive = {}
    except (json.JSONDecodeError, FileNotFoundError):
        archive = {}
    entry = dict(server_data)
    entry['deleted_at'] = datetime.datetime.now().isoformat()
    if ip not in archive:
        archive[ip] = []
    archive[ip].append(entry)
    with open(DELETED_SERVERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(archive, f, indent=4)

def delete_server(ip: str) -> bool:
    servers = get_servers()
    if ip not in servers:
        return False
    _archive_deleted_server(ip, servers[ip])
    del servers[ip]
    return _save_servers(servers)

def update_server_status(ip: str, status: str) -> bool:
    servers = get_servers()
    if ip not in servers: return False
    servers[ip]['status'] = status
    return _save_servers(servers)

def update_server_slots(ip: str, slots: int) -> bool:
    servers = get_servers()
    if ip not in servers: return False
    servers[ip]['slots'] = slots
    return _save_servers(servers)

async def is_install_allowed(ip: str, user_id: int) -> bool:
    from admin_manager import get_all_admins
    import database as db

    servers = get_servers()
    server_info = servers.get(ip)
    if not server_info:
        return False

    status = server_info.get('status')
    
    if status == 'premium':
        is_admin = user_id in get_all_admins()
        has_access = await db.check_premium_access(user_id)
        return is_admin or has_access
        
    if status == 'true':
        return True
        
    if status == 'test' and user_id in get_all_admins():
        return True
        
    return False

def get_server_status_by_ip(ip: str) -> str:
    servers = get_servers()
    server_info = servers.get(ip)
    if not server_info: return "not_found"
    return server_info.get('status', 'false')

def update_server_auth_mode(ip: str, mode: str) -> bool:
    servers = get_servers()
    if ip not in servers:
        return False
    
    if 'auth' not in servers[ip]:
        servers[ip]['auth'] = {}
        
    servers[ip]['auth']['mode'] = mode
    
    if mode == 'auto' and 'port' in servers[ip]['auth']:
        del servers[ip]['auth']['port']
        
    return _save_servers(servers)

def get_server_auth_config(ip: str) -> dict:
    servers = get_servers()
    server_info = servers.get(ip, {})
    return server_info.get('auth', {'mode': 'auto'})

def _read_global_status() -> bool:
    if not os.path.exists(SERVER_STATUS_FILE):
        _save_global_status(True)
        return True
    try:
        with open(SERVER_STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('enabled', True)
    except (json.JSONDecodeError, FileNotFoundError):
        _save_global_status(True)
        return True

def _save_global_status(enabled: bool) -> bool:
    try:
        with open(SERVER_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"enabled": enabled}, f, indent=4)
        return True
    except Exception:
        return False

def is_bot_enabled_for_users() -> bool:
    return _read_global_status()

def set_bot_status_for_users(enabled: bool) -> bool:
    return _save_global_status(enabled)

def get_server_api_token(ip: str) -> str:
    """Получает API токен для сервера"""
    servers = get_servers()
    server_info = servers.get(ip, {})
    return server_info.get('api_token', '')

def set_server_api_token(ip: str, token: str) -> bool:
    """Устанавливает API токен для сервера"""
    servers = get_servers()
    if ip not in servers:
        return False
    
    servers[ip]['api_token'] = token
    return _save_servers(servers)

def get_server_api_url(ip: str) -> str:
    """Получает API URL для сервера"""
    servers = get_servers()
    server_info = servers.get(ip, {})
    return server_info.get('api_url', '')

def set_server_api_url(ip: str, url: str) -> bool:
    """Устанавливает API URL для сервера"""
    servers = get_servers()
    if ip not in servers:
        return False
    
    servers[ip]['api_url'] = url
    return _save_servers(servers)
# --- END OF FILE server_config.py ---