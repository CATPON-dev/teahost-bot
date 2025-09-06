import subprocess
import asyncio
import time
import re
import secrets
import string
import os
import pwd
import sys
import shlex
from html import escape
import datetime
import pytz
import json
import logging
import time
import asyncssh
from urllib.request import urlopen
import tempfile
import uuid
import shutil
from pathlib import Path
import zipfile
import random
import math

import database as db
import server_config

logger_lm = logging.getLogger(__name__)

def get_public_ip():
    try:
        with urlopen("https://api.ipify.org") as response:
            ip = response.read().decode("utf-8")
        logging.info(f"Public IP address detected: {ip}")
        return ip
    except Exception as e:
        logging.critical(f"Could not determine public IP address. Exiting. Error: {e}")
        sys.exit("Critical error: Public IP address could not be determined.")

LOCAL_IP = get_public_ip()
GIT_OVERRIDES_FILE = "git_overrides.json"
STATS_CACHE = {}
CACHE_LIFETIME_SECONDS = 20

def _read_git_overrides():
    if not os.path.exists(GIT_OVERRIDES_FILE):
        return {}
    try:
        with open(GIT_OVERRIDES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _write_git_overrides(overrides: dict):
    with open(GIT_OVERRIDES_FILE, 'w') as f:
        json.dump(overrides, f, indent=4)

def update_git_repository(ub_type: str, url: str):
    overrides = _read_git_overrides()
    overrides[ub_type] = url
    _write_git_overrides(overrides)

def get_current_repo_url(ub_type: str) -> str:
    repo_map = {
        "hikka": {"url": "https://github.com/qqsharki4/Hikka"},
        "heroku": {"url": "https://github.com/qqsharki4/Heroku"},
        "fox": {"url": "https://github.com/FoxUserbot/FoxUserbot"},
        "legacy": {"url": "https://github.com/Crayz310/Legacy"}
    }
    overrides = _read_git_overrides()
    return overrides.get(ub_type, repo_map.get(ub_type, {}).get("url", "URL не найден"))

async def get_ping_ms(target: str, source_ip: str) -> str:
    ping_cmd = f"ping -c 1 -W 2 {shlex.quote(target)}"
    res = await run_command_async(ping_cmd, source_ip, check_output=False, timeout=5)
    
    if res["success"] and res["output"]:
        match = re.search(r"time=([\d\.]+)\s*ms", res["output"])
        if match:
            return f"{float(match.group(1)):.1f} мс"
    return "❌ Ошибка"

async def get_server_ping(server_ip: str) -> float | None:
    try:
        ping_cmd = f"ping -c 1 -W 2 {shlex.quote(server_ip)}"
        
        process = await asyncio.create_subprocess_shell(
            ping_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=3.0)

        if process.returncode == 0:
            match = re.search(r"time=([\d\.]+)\s*ms", stdout.decode('utf-8', 'ignore'))
            if match:
                return float(match.group(1))
    except (asyncio.TimeoutError, Exception):
        pass

    try:
        start_time = time.perf_counter()
        ssh_res = await run_command_async("echo pong", server_ip, timeout=5)
        end_time = time.perf_counter()
        if ssh_res["success"]:
            ssh_rtt_ms = (end_time - start_time) * 1000
            return ssh_rtt_ms
    except Exception as e:
        logger_lm.error(f"SSH ping fallback failed for {server_ip}: {e}")

    return None

async def get_userbot_resource_usage(ub_username: str, server_ip: str) -> dict:
    """
    Заглушка для получения информации об использовании ресурсов Docker-контейнером юзербота.
    Возвращает словарь с ключами: cpu, ram_used, ram_limit, ram_percent
    """
    # Заглушка - возвращаем нулевые значения
    return {
        "cpu": "0.0",
        "ram_used": "0",
        "ram_limit": "500",
        "ram_percent": "0.0"
    }

async def run_command_async(command_str: str, server_ip: str, timeout=300, user=None, check_output=True, capture_output=True, ssh_pass=None):
    stdout_pipe = asyncio.subprocess.PIPE if capture_output else asyncio.subprocess.DEVNULL
    stderr_pipe = asyncio.subprocess.PIPE if capture_output else asyncio.subprocess.DEVNULL
    
    try:
        if server_ip == LOCAL_IP:
            if user:
                final_command = f'sudo -u {shlex.quote(user)} bash -c {shlex.quote("source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; set -o pipefail; " + command_str)}'
            else:
                final_command = f'bash -c {shlex.quote("set -o pipefail; " + command_str)}'
            
            process = await asyncio.create_subprocess_shell(
                final_command, stdout=stdout_pipe, stderr=stderr_pipe
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            
            stdout_str = stdout.decode('utf-8', 'ignore').strip() if stdout else ""
            stderr_str = stderr.decode('utf-8', 'ignore').strip() if stderr else ""

            if check_output and process.returncode != 0:
                err_msg = f"RC={process.returncode}\nSTDERR:\n{stderr_str}\nSTDOUT:\n{stdout_str}"
                return {"success": False, "output": stdout_str, "error": err_msg, "exit_status": process.returncode}

            return {"success": True, "output": stdout_str, "error": stderr_str, "exit_status": process.returncode}

        else:
            servers = server_config.get_servers()
            server_details = servers.get(server_ip)
            if not server_details:
                return {"success": False, "error": f"SSH details not found for server {server_ip}", "exit_status": -1}

            ssh_user = server_details.get("ssh_user")
            ssh_pass_final = ssh_pass or server_details.get("ssh_pass")

            if not ssh_user:
                return {"success": False, "error": f"SSH user not configured for remote server {server_ip}", "exit_status": -1}

            conn = None
            try:
                conn = await asyncio.wait_for(
                    asyncssh.connect(server_ip, username=ssh_user, password=ssh_pass_final, known_hosts=None),
                    timeout=30.0  
                )
                
                if user:
                    safe_user = shlex.quote(user)
                    full_user_command = f"cd /home/{safe_user} && {command_str}"
                    final_command = f"sudo -u {safe_user} bash -c {shlex.quote('source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; set -o pipefail; ' + full_user_command)}"
                else:
                    final_command = f"bash -c {shlex.quote('set -o pipefail; ' + command_str)}"
                
                result = await asyncio.wait_for(conn.run(final_command, check=False), timeout=timeout)
                conn.close()

                stdout_str = result.stdout.strip() if result.stdout else ""
                stderr_str = result.stderr.strip() if result.stderr else ""
                
                if check_output and result.exit_status != 0:
                    err_msg = f"RC={result.exit_status}\nSTDERR:\n{stderr_str}\nSTDOUT:\n{stdout_str}"
                    return {"success": False, "output": stdout_str, "error": err_msg, "exit_status": result.exit_status}

                return {"success": True, "output": stdout_str, "error": stderr_str, "exit_status": result.exit_status}

            except asyncio.TimeoutError:
                if conn: conn.close()
                logger_lm.error(f"HARD TIMEOUT on connection to [{server_ip}].")
                return {"success": False, "error": "Принудительный таймаут SSH-подключения.", "exit_status": -1}
            except (ConnectionResetError, asyncssh.misc.ConnectionLost, OSError, asyncssh.Error) as e:
                if conn: conn.close()
                logger_lm.error(f"SSH Connection Error on [{server_ip}]: {type(e).__name__}")
                return {"success": False, "error": f"Ошибка соединения: {type(e).__name__}", "exit_status": -1}

    except Exception as e:
        logger_lm.error(f"Unhandled EXCEPTION in run_command_async on [{server_ip}]", exc_info=True)
        return {"success": False, "error": str(e), "exit_status": -1}

def generate_password(length=20):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{};:,./<>?"
    return ''.join(secrets.choice(alphabet) for i in range(length))

async def get_server_stats(server_ip: str):
    current_time = time.time()
    if server_ip in STATS_CACHE:
        cached_data, timestamp = STATS_CACHE[server_ip]
        if current_time - timestamp < CACHE_LIFETIME_SECONDS:
            logger_lm.debug(f"Returning cached stats for [{server_ip}]")
            return cached_data

    # Оптимизированная команда для сбора всех данных за один вызов
    combined_cmd = (
        "top -bn1 | awk '/^%Cpu/ {print $2+$4}' && "
        "echo '---' && "
        "free -m | awk 'NR==2{printf \"%d|%d\", $3, $2}' && "
        "echo '---' && "
        "df -h / | awk 'NR==2{printf \"%s|%s|%s\", $5, $3, $2}' && "
        "echo '---' && "
        "uptime -p && "
        "echo '---' && "
        "nproc"
    )

    res = await run_command_async(combined_cmd, server_ip, timeout=15)
    
    defaults = {
        "cpu_usage": "0.0", "cpu_cores": "N/A", "ram_percent": "0.0", "ram_used": "0G", "ram_total": "0G",
        "disk_percent": "0%", "disk_used": "0B", "disk_total": "0B", "uptime": "N/A"
    }

    if not res.get("success") or not res.get("output"):
        STATS_CACHE[server_ip] = (defaults, current_time)
        return defaults

    try:
        parts = res['output'].strip().split('---')
        if len(parts) < 5:
             STATS_CACHE[server_ip] = (defaults, current_time)
             return defaults

        cpu_out, ram_out, disk_out, uptime_out, nproc_out = [p.strip() for p in parts]

        cpu_usage = float(cpu_out) if cpu_out else 0.0
        
        ram_data = ram_out.split('|')
        ram_used_mb, ram_total_mb = int(ram_data[0]), int(ram_data[1])
        ram_percent = (ram_used_mb / ram_total_mb * 100) if ram_total_mb > 0 else 0

        disk_data = disk_out.split('|')
        
        uptime = uptime_out.replace("up ", "")
        
        cpu_cores = nproc_out if nproc_out.isdigit() else "N/A"

        stats_data = {
            "cpu_usage": f"{cpu_usage:.1f}",
            "cpu_cores": cpu_cores,
            "ram_percent": f"{ram_percent:.1f}",
            "ram_used": f"{(ram_used_mb/1024):.1f}G",
            "ram_total": f"{(ram_total_mb/1024):.1f}G",
            "disk_percent": disk_data[0],
            "disk_used": disk_data[1],
            "disk_total": disk_data[2],
            "uptime": uptime
        }
        STATS_CACHE[server_ip] = (stats_data, current_time)
        return stats_data
        
    except (ValueError, IndexError, TypeError) as e:
        logging.error(f"Failed to parse combined stats from {server_ip}. Error: {e}. Output: {res.get('output')}")
        STATS_CACHE[server_ip] = (defaults, current_time)
        return defaults

async def user_exists(username, server_ip):
    res = await run_command_async(f"id -u {shlex.quote(username)}", server_ip, capture_output=False, check_output=False)
    return res["exit_status"] == 0

async def ensure_system_utils(server_ip: str):
    # Проверяем и ждем завершения процесса apt-get если он запущен
    check_apt_cmd = "sudo fuser -v /var/lib/dpkg/lock* /var/lib/apt/lists/lock* 2>/dev/null || echo 'no_locks'"
    apt_check = await run_command_async(check_apt_cmd, server_ip, capture_output=False)
    
    if apt_check.get("success") and "no_locks" not in apt_check.get("output", ""):
        logging.info(f"Waiting for apt processes to complete on {server_ip}...")
        await run_command_async("sudo fuser -k /var/lib/dpkg/lock* /var/lib/apt/lists/lock* 2>/dev/null || true", server_ip, capture_output=False)
        await asyncio.sleep(5)
    
    await run_command_async("sudo apt-get update -qq", server_ip, capture_output=False)
    await run_command_async("sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git ca-certificates procps python3-pip", server_ip, capture_output=False)

async def check_for_session_file(ub_username: str, server_ip: str) -> bool:
    ub_data = await db.get_userbot_data(ub_username=ub_username)
    if not ub_data or not await user_exists(ub_username, server_ip): return False
    ub_type, hikka_path = ub_data.get("ub_type"), ub_data.get("hikka_path")
    if not ub_type or not hikka_path: return False
    
    cmd = f'sudo find {shlex.quote(hikka_path)} -maxdepth 1 \\( -name "*.session" -o -name "heroku*" \\) -print -quit'
    res = await run_command_async(cmd, server_ip, check_output=False)
    return bool(res["success"] and res["output"])
    
async def get_all_userbots_cpu_usage(server_ip: str):
    """
    Заглушка для получения информации об использовании CPU всеми Docker-контейнерами юзерботов.
    """
    # Заглушка - возвращаем пустой словарь
    return {}
    
def generate_strong_password(length=28):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{};:,./<>?"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

async def prepare_server_without_password_change(ip, ssh_user, ssh_pass):
    """
    Подготавливает сервер без смены пароля - только настройка безопасности
    """
    import asyncssh
    import shlex
    import logging

    pubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF8o56JaCLaEta/fNV9I235ngQLcjqmOutIiGkYpdSc8 qqsharki4@gmail.com"
    sshd_config = '''Port 22
AddressFamily any
ListenAddress 0.0.0.0
Protocol 2
HostKey /etc/ssh/ssh_host_rsa_key
HostKey /etc/ssh/ssh_host_ecdsa_key
HostKey /etc/ssh/ssh_host_ed25519_key
LoginGraceTime 60
PermitRootLogin yes
StrictModes yes
MaxAuthTries 3
MaxSessions 5
PubkeyAuthentication yes
PasswordAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
ClientAliveInterval 300
ClientAliveCountMax 2
Compression no
Subsystem sftp /usr/lib/openssh/sftp-server
AllowAgentForwarding no
AllowTcpForwarding yes
GatewayPorts no
PermitTunnel no'''

    try:
        async with asyncssh.connect(ip, username=ssh_user, password=ssh_pass, known_hosts=None) as conn:
            # 1. Удаление всех ключей из /root/.ssh и /home/*/.ssh
            try:
                res = await conn.run('rm -rf /root/.ssh/*', check=False)
                logging.info(f"rm root keys: {res.stdout} {res.stderr}")
                res = await conn.run('for d in /home/*/.ssh; do rm -rf "$d"/*; done', check=False)
                logging.info(f"rm home keys: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при удалении ssh-ключей: {e}")
                raise

            # 2. Запрет SSH для всех кроме root
            try:
                res = await conn.run('for u in $(awk -F: "$1 != \"root\" {print $1}" /etc/passwd); do sudo usermod -s /usr/sbin/nologin $u; done', check=False)
                logging.info(f"usermod: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при usermod: {e}")
                raise

            # 3. Добавление публичного ключа
            try:
                res = await conn.run('mkdir -p /root/.ssh && chmod 700 /root/.ssh', check=True)
                logging.info(f"mkdir .ssh: {res.stdout} {res.stderr}")
                res = await conn.run(f'echo "{pubkey}" > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys', check=True)
                logging.info(f"add pubkey: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при добавлении публичного ключа: {e}")
                raise

            # 4. Запись sshd_config
            try:
                res = await conn.run(f'echo {shlex.quote(sshd_config)} | sudo tee /etc/ssh/sshd_config', check=True)
                logging.info(f"sshd_config: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при записи sshd_config: {e}")
                raise

            # 5. Проверка и рестарт sshd
            try:
                res = await conn.run('sudo sshd -t', check=True)
                logging.info(f"sshd -t: {res.stdout} {res.stderr}")

                # Получаем список ssh-сервисов
                res_units = await conn.run('systemctl list-units --type=service | grep ssh', check=False)
                units = res_units.stdout or ''
                print(f"systemctl list-units --type=service | grep ssh: {units}")
                if 'ssh.service' in units:
                    ssh_service = 'ssh'
                elif 'sshd.service' in units:
                    ssh_service = 'sshd'
                else:
                    ssh_service = 'ssh'  # fallback
                print(f"Выбран сервис для перезапуска: {ssh_service}")

                res = await conn.run(f'sudo systemctl restart {ssh_service}', check=True)
                logging.info(f"restart {ssh_service}: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при перезапуске ssh-сервиса: {e}")
                raise

            # 6. Пароль НЕ меняется - сохраняем оригинальный
            logging.info(f"Пароль для {ip} сохранен без изменений")
    except Exception as e:
        logging.error(f"[prepare_server_without_password_change] Ошибка: {repr(e)}")
        raise
    return ssh_pass  # Возвращаем оригинальный пароль

async def secure_and_prepare_server(ip, old_ssh_user, old_ssh_pass):
    """
    Старая функция для обратной совместимости - меняет пароль
    """
    import asyncssh
    import shlex
    import logging

    new_password = generate_strong_password(28)
    pubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIF8o56JaCLaEta/fNV9I235ngQLcjqmOutIiGkYpdSc8 qqsharki4@gmail.com"
    sshd_config = '''Port 22
AddressFamily any
ListenAddress 0.0.0.0
Protocol 2
HostKey /etc/ssh/ssh_host_rsa_key
HostKey /etc/ssh/ssh_host_ecdsa_key
HostKey /etc/ssh/ssh_host_ed25519_key
LoginGraceTime 60
PermitRootLogin yes
StrictModes yes
MaxAuthTries 3
MaxSessions 5
PubkeyAuthentication yes
PasswordAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
ClientAliveInterval 300
ClientAliveCountMax 2
Compression no
Subsystem sftp /usr/lib/openssh/sftp-server
AllowAgentForwarding no
AllowTcpForwarding yes
GatewayPorts no
PermitTunnel no'''

    try:
        async with asyncssh.connect(ip, username=old_ssh_user, password=old_ssh_pass, known_hosts=None) as conn:
            # 1. Удаление всех ключей из /root/.ssh и /home/*/.ssh
            try:
                res = await conn.run('rm -rf /root/.ssh/*', check=False)
                logging.info(f"rm root keys: {res.stdout} {res.stderr}")
                res = await conn.run('for d in /home/*/.ssh; do rm -rf "$d"/*; done', check=False)
                logging.info(f"rm home keys: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при удалении ssh-ключей: {e}")
                raise

            # 2. Запрет SSH для всех кроме root
            try:
                res = await conn.run('for u in $(awk -F: "$1 != \"root\" {print $1}" /etc/passwd); do sudo usermod -s /usr/sbin/nologin $u; done', check=False)
                logging.info(f"usermod: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при usermod: {e}")
                raise

            # 3. Добавление публичного ключа
            try:
                res = await conn.run('mkdir -p /root/.ssh && chmod 700 /root/.ssh', check=True)
                logging.info(f"mkdir .ssh: {res.stdout} {res.stderr}")
                res = await conn.run(f'echo "{pubkey}" > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys', check=True)
                logging.info(f"add pubkey: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при добавлении публичного ключа: {e}")
                raise

            # 4. Запись sshd_config
            try:
                res = await conn.run(f'echo {shlex.quote(sshd_config)} | sudo tee /etc/ssh/sshd_config', check=True)
                logging.info(f"sshd_config: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при записи sshd_config: {e}")
                raise

            # 5. Проверка и рестарт sshd
            try:
                res = await conn.run('sudo sshd -t', check=True)
                logging.info(f"sshd -t: {res.stdout} {res.stderr}")

                # Получаем список ssh-сервисов
                res_units = await conn.run('systemctl list-units --type=service | grep ssh', check=False)
                units = res_units.stdout or ''
                print(f"systemctl list-units --type=service | grep ssh: {units}")
                if 'ssh.service' in units:
                    ssh_service = 'ssh'
                elif 'sshd.service' in units:
                    ssh_service = 'sshd'
                else:
                    ssh_service = 'ssh'  # fallback
                print(f"Выбран сервис для перезапуска: {ssh_service}")

                res = await conn.run(f'sudo systemctl restart {ssh_service}', check=True)
                logging.info(f"restart {ssh_service}: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при перезапуске ssh-сервиса: {e}")
                raise

            # 6. Смена пароля root (после успешного рестарта sshd)
            try:
                res = await conn.run('sudo chpasswd', input=f'root:{new_password}\n', check=True)
                logging.info(f"chpasswd: {res.stdout} {res.stderr}")
            except Exception as e:
                logging.error(f"Ошибка при смене пароля root: {e}")
                raise
    except Exception as e:
        logging.error(f"[secure_and_prepare_server] Ошибка: {repr(e)}")
        raise
    return new_password

async def add_server_with_security(ip: str, user: str, password: str, details: dict) -> str | None:
    try:
        # Подготавливаем сервер без смены пароля
        await prepare_server_without_password_change(ip, user, password)
    except Exception as e:
        print(f"[add_server_with_security] Ошибка при подготовке сервера: {e}")
        return None

    servers = server_config.get_servers()
    servers[ip] = {
        "ssh_user": user,
        "ssh_pass": password,  # Используем оригинальный пароль
        "name": details.get("name", "serv_new"),
        "country": details.get("country", "Unknown"),
        "city": details.get("city", "Unknown"),
        "regionName": details.get("regionName", "N/A"),
        "flag": details.get("flag", "🏳️"),
        "code": details.get("code", ip.split('.')[-1]),
        "org": details.get("org", "N/A"),
        "timezone": details.get("timezone", "N/A"),
        "hosting": details.get("hosting", False),
        "proxy": details.get("proxy", False),
        "vpn": details.get("vpn", False),
        "status": "test",
        "slots": 0,
        "api_url": f"http://{ip}:8000",
        "api_token": "kivWJmOe2ey9u50uCqEwCIcHstCwuZslu7QK4YcEsCTGQcUTx33JC3bZveOzvr8y"
    }
    if server_config._save_servers(servers):
        return password  # Возвращаем оригинальный пароль
    else:
        return None
        
async def service_and_prepare_server(ip: str, bot=None, chat_id=None, ssh_pass=None) -> bool:
    """
    Выполняет полное обслуживание и подготовку сервера для хостинга Docker-контейнеров.
    Включает обновление системы, установку зависимостей и клонирование/обновление репозиториев.
    """
    logging.info(f"Starting full service and preparation for server {ip}...")

    async def send_status(text):
        if bot and chat_id:
            try:
                await bot.send_message(chat_id, f"<b>[Обслуживание {html.quote(ip)}]</b>\n{html.quote(text)}")
            except Exception as e:
                logging.warning(f"Failed to send status update to {chat_id}: {e}")

    try:
        await send_status("Шаг 1/3: Обновление пакетов и установка утилит...")
        
        # Проверяем и ждем завершения процесса apt-get если он запущен
        check_apt_cmd = "sudo fuser -v /var/lib/dpkg/lock* /var/lib/apt/lists/lock* 2>/dev/null || echo 'no_locks'"
        apt_check = await run_command_async(check_apt_cmd, ip, ssh_pass=ssh_pass, capture_output=False)
        
        if apt_check.get("success") and "no_locks" not in apt_check.get("output", ""):
            await send_status("⏳ Ожидание завершения других процессов apt-get...")
            await run_command_async("sudo fuser -k /var/lib/dpkg/lock* /var/lib/apt/lists/lock* 2>/dev/null || true", ip, ssh_pass=ssh_pass, capture_output=False)
            await asyncio.sleep(5)
        
        install_cmd = "sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3-venv zip acl"
        install_res = await run_command_async(install_cmd, ip, ssh_pass=ssh_pass, timeout=600)
        if not install_res.get("success"):
            error_msg = f"Ошибка установки базовых пакетов: {install_res.get('error')}"
            logging.error(f"Failed to install base packages on {ip}: {install_res.get('error')}")
            await send_status(f"❌ {error_msg}")
            return False

        await send_status("Шаг 2/3: Клонирование/обновление репозиториев юзерботов...")
        repo_map = {
            "hikka": {"dir": "Hikka"},
            "heroku": {"dir": "Heroku"},
            "fox": {"dir": "FoxUserbot"},
            "legacy": {"dir": "Legacy"}
        }
        
        all_repos_ok = True
        for ub_type, info in repo_map.items():
            repo_url = get_current_repo_url(ub_type)
            target_dir = f"/root/{info['dir']}"
            
            # Пробуем клонировать с retry механизмом
            max_retries = 3
            clone_success = False
            
            for attempt in range(max_retries):
                if attempt > 0:
                    await send_status(f"🔄 Повторная попытка клонирования {ub_type.capitalize()} (попытка {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(2)
                
                # Проверяем доступность GitHub перед клонированием
                if attempt == 0:
                    ping_cmd = "ping -c 1 -W 5 github.com"
                    ping_res = await run_command_async(ping_cmd, ip, ssh_pass=ssh_pass, timeout=10)
                    if not ping_res.get("success"):
                        await send_status(f"⚠️ Проблемы с доступом к GitHub на {ip}")
                    
                    # Проверяем DNS
                    nslookup_cmd = "nslookup github.com"
                    nslookup_res = await run_command_async(nslookup_cmd, ip, ssh_pass=ssh_pass, timeout=10)
                    if not nslookup_res.get("success"):
                        await send_status(f"⚠️ Проблемы с DNS на {ip}")
                
                # Пробуем разные методы клонирования
                if attempt == 0:
                    clone_cmd = f"sudo rm -rf {target_dir} && git clone --depth 1 {repo_url} {target_dir}"
                elif attempt == 1:
                    # Пробуем с отключенным SSL
                    clone_cmd = f"sudo rm -rf {target_dir} && git -c http.sslVerify=false clone --depth 1 {repo_url} {target_dir}"
                else:
                    # Пробуем с принудительным IPv4
                    clone_cmd = f"sudo rm -rf {target_dir} && git -c http.sslVerify=false -c url.'https://github.com/'.insteadOf 'https://github.com/' clone --depth 1 {repo_url} {target_dir}"
                
                clone_res = await run_command_async(clone_cmd, ip, ssh_pass=ssh_pass, timeout=300)
                
                if clone_res.get("success"):
                    clone_success = True
                    break
                else:
                    logging.warning(f"Attempt {attempt + 1} failed to clone {repo_url} on {ip}: {clone_res.get('error')}")
            
            if not clone_success:
                logging.error(f"Failed to clone {repo_url} on {ip} after {max_retries} attempts: {clone_res.get('error')}")
                await send_status(f"❌ Ошибка клонирования репозитория для {ub_type.capitalize()}")
                all_repos_ok = False
        
        if not all_repos_ok:
            return False

        await send_status("Шаг 3/3: Настройка сетевых параметров...")
        
        # Проверяем и исправляем сетевые настройки
        await send_status("🔧 Настройка DNS и Git конфигурации...")
        network_fix_cmd = """
        # Проверяем DNS
        echo "nameserver 8.8.8.8" | sudo tee -a /etc/resolv.conf > /dev/null
        echo "nameserver 1.1.1.1" | sudo tee -a /etc/resolv.conf > /dev/null
        
        # Проверяем git конфигурацию
        git config --global --unset-all http.sslVerify 2>/dev/null || true
        git config --global http.sslVerify false
        
        # Очищаем git кэш
        rm -rf ~/.git-cache 2>/dev/null || true
        """
        await run_command_async(network_fix_cmd, ip, ssh_pass=ssh_pass, timeout=60)
        
        logging.info(f"Successfully serviced and prepared server {ip} for Docker containers.")
        await send_status("✅ Сервер готов для работы с Docker-контейнерами!")
        return True

    except Exception as e:
        error_text = f"Критическая ошибка при обслуживании сервера {ip}: {e}"
        logging.error(error_text, exc_info=True)
        await send_status(f"❌ {error_text}")
        return False
        
async def get_all_userbots_ram_usage(server_ip: str) -> dict[str, float]:
    """
    Заглушка для получения информации об использовании RAM всеми Docker-контейнерами юзерботов.
    """
    # Заглушка - возвращаем пустой словарь
    return {}

async def get_journal_logs(ub_username: str, server_ip: str, lines: int = 100) -> str:
    """
    Получает логи systemd службы юзербота через journalctl.
    Возвращает последние N строк логов.
    """
    try:
        # Определяем имя службы на основе типа юзербота
        ub_data = await db.get_userbot_data(ub_username=ub_username)
        if not ub_data:
            return "❌ Юзербот не найден в базе данных"
        
        ub_type = ub_data.get('ub_type', 'hikka')
        service_name = f"{ub_type}-{ub_username}.service"
        
        # Команда для получения логов через journalctl
        log_cmd = f"journalctl -u {shlex.quote(service_name)} --no-pager -n {lines} --output=cat"
        
        result = await run_command_async(log_cmd, server_ip, timeout=30)
        
        if result.get("success"):
            logs = result.get("output", "")
            if logs.strip():
                return logs
            else:
                return f"📜 Логи службы {service_name} пусты или служба не запускалась"
        else:
            error_msg = result.get("error", "Неизвестная ошибка")
            return f"❌ Ошибка получения логов: {error_msg}"
            
    except Exception as e:
        logger_lm.error(f"Exception in get_journal_logs for {ub_username} on {server_ip}: {e}")
        return f"❌ Исключение при получении логов: {str(e)}"

async def get_script_log_file(ub_username: str, ub_type: str, server_ip: str, lines: int = 100) -> str:
    """
    Получает логи из файла скрипта юзербота.
    Возвращает последние N строк логов.
    """
    try:
        # Определяем путь к файлу логов на основе типа юзербота
        log_paths = {
            "hikka": f"/home/{ub_username}/Hikka/logs/hikka.log",
            "heroku": f"/home/{ub_username}/Heroku/logs/heroku.log", 
            "fox": f"/home/{ub_username}/FoxUserbot/logs/fox.log",
            "legacy": f"/home/{ub_username}/Legacy/logs/legacy.log"
        }
        
        log_path = log_paths.get(ub_type)
        if not log_path:
            return f"❌ Неизвестный тип юзербота: {ub_type}"
        
        # Команда для получения последних строк из файла логов
        log_cmd = f"tail -n {lines} {shlex.quote(log_path)} 2>/dev/null || echo 'Файл логов не найден'"
        
        result = await run_command_async(log_cmd, server_ip, timeout=30)
        
        if result.get("success"):
            logs = result.get("output", "")
            if logs.strip() and "Файл логов не найден" not in logs:
                return logs
            else:
                return f"📜 Файл логов {log_path} пуст или не существует"
        else:
            error_msg = result.get("error", "Неизвестная ошибка")
            return f"❌ Ошибка получения логов из файла: {error_msg}"
            
    except Exception as e:
        logger_lm.error(f"Exception in get_script_log_file for {ub_username} ({ub_type}) on {server_ip}: {e}")
        return f"❌ Исключение при получении логов из файла: {str(e)}"

async def get_docker_container_logs(ub_username: str, server_ip: str, lines: int = 100) -> str:
    """
    Получает логи Docker-контейнера юзербота.
    Возвращает последние N строк логов.
    """
    try:
        # Определяем имя контейнера
        container_name = f"userbot-{ub_username}"
        
        # Команда для получения логов Docker-контейнера
        log_cmd = f"docker logs --tail {lines} {shlex.quote(container_name)} 2>&1"
        
        result = await run_command_async(log_cmd, server_ip, timeout=30)
        
        if result.get("success"):
            logs = result.get("output", "")
            if logs.strip():
                return logs
            else:
                return f"📜 Логи контейнера {container_name} пусты"
        else:
            error_msg = result.get("error", "Неизвестная ошибка")
            # Проверяем, существует ли контейнер
            check_cmd = f"docker ps -a --filter name={shlex.quote(container_name)} --format '{{{{.Names}}}}'"
            check_result = await run_command_async(check_cmd, server_ip, timeout=10)
            
            if check_result.get("success") and container_name not in check_result.get("output", ""):
                return f"❌ Контейнер {container_name} не найден"
            else:
                return f"❌ Ошибка получения логов Docker: {error_msg}"
                
    except Exception as e:
        logger_lm.error(f"Exception in get_docker_container_logs for {ub_username} on {server_ip}: {e}")
        return f"❌ Исключение при получении логов Docker: {str(e)}"

async def get_userbot_logs(ub_username: str, server_ip: str, log_type: str = "journal", lines: int = 100) -> str:
    """
    Универсальный метод для получения логов юзербота.
    
    Args:
        ub_username: Имя пользователя юзербота
        server_ip: IP сервера
        log_type: Тип логов ("journal", "file", "docker")
        lines: Количество строк для получения
    
    Returns:
        Строка с логами или сообщение об ошибке
    """
    try:
        if log_type == "journal":
            return await get_journal_logs(ub_username, server_ip, lines)
        elif log_type == "file":
            ub_data = await db.get_userbot_data(ub_username=ub_username)
            if not ub_data:
                return "❌ Юзербот не найден в базе данных"
            ub_type = ub_data.get('ub_type', 'hikka')
            return await get_script_log_file(ub_username, ub_type, server_ip, lines)
        elif log_type == "docker":
            return await get_docker_container_logs(ub_username, server_ip, lines)
        else:
            return f"❌ Неизвестный тип логов: {log_type}"
            
    except Exception as e:
        logger_lm.error(f"Exception in get_userbot_logs for {ub_username} ({log_type}) on {server_ip}: {e}")
        return f"❌ Исключение при получении логов: {str(e)}"
        
async def get_git_info() -> dict:
    info = {
        "status": "N/A",
        "last_commit_hash": "N/A",
        "last_commit_msg": "N/A",
        "branch": "N/A"
    }

    try:
        branch_res = await run_command_async("git rev-parse --abbrev-ref HEAD", LOCAL_IP)
        if branch_res.get("success"):
            info["branch"] = branch_res.get("output", "N/A")

        commit_res = await run_command_async("git log -1 --pretty='%h|%s'", LOCAL_IP)
        if commit_res.get("success") and commit_res.get("output"):
            parts = commit_res.get("output").split('|', 1)
            if len(parts) == 2:
                info["last_commit_hash"] = parts[0].strip()
                info["last_commit_msg"] = parts[1].strip()

        await run_command_async("git remote update", LOCAL_IP, timeout=60)
        status_res = await run_command_async("git status -uno", LOCAL_IP)
        if status_res.get("success"):
            output = status_res.get("output", "")
            if "Your branch is up to date" in output:
                info["status"] = "👌 Up-to-date"
            elif "Your branch is behind" in output:
                info["status"] = "😔 Update required"
            else:
                info["status"] = "🤔 Unknown"
                
    except Exception as e:
        logging.error(f"Ошибка при получении информации из Git: {e}")
        for key in info:
            info[key] = "Error"
            
    return info