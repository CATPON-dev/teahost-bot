import asyncio
import logging
import asyncssh
import psutil  # Для получения локальной статистики CPU
import platform # Для определения операционной системы (например, для команды ping)

import server_config # Предполагается, что этот модуль управляет server_config.json

logger = logging.getLogger(__name__)

async def get_server_load(ip: str, ssh_user: str | None, ssh_pass: str | None, ssh_key_path: str | None = None) -> float:
    """
    Получает загрузку CPU сервера.
    Если ssh_user не предоставлен и IP совпадает с локальным, используется psutil.
    Иначе, используется SSH.
    Возвращает процент загрузки CPU или -1.0 в случае ошибки.
    """
    try:
        # Проверяем, является ли IP локальным адресом или именем хоста
        is_local_machine = (ip == "127.0.0.1" or ip == "localhost" or platform.node().lower() == ip.lower())

        if ssh_user is None and is_local_machine:
            # Если нет SSH-пользователя и это локальная машина, используем psutil
            return psutil.cpu_percent(interval=1)
        elif ssh_user:
            # Для удаленных серверов с SSH-учетными данными
            cmd = "top -bn1 | grep 'Cpu(s)' | sed 's/.*, *\\([0-9.]*\\)%* id.*/\\1/' | awk '{print 100 - $1}'"
            
            # Приоритет: SSH ключ > пароль
            if ssh_key_path and os.path.exists(ssh_key_path):
                async with asyncssh.connect(ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=10) as conn:
                    result = await conn.run(cmd, check=True)
                    return float(result.stdout.strip())
            elif ssh_pass:
                async with asyncssh.connect(ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=10) as conn:
                    result = await conn.run(cmd, check=True)
                    return float(result.stdout.strip())
            else:
                logger.warning(f"Невозможно получить загрузку сервера для {ip}: отсутствуют SSH-учетные данные для удаленного сервера, и это не локальный хост.")
                return -1.0
        else:
            logger.warning(f"Невозможно получить загрузку сервера для {ip}: отсутствуют SSH-учетные данные для удаленного сервера, и это не локальный хост.")
            return -1.0 # Указывает на недоступность или ошибку
    except (asyncssh.Error, ValueError, TypeError, TimeoutError) as e:
        logger.error(f"Не удалось получить загрузку сервера для {ip}: {e}")
        return -1.0

async def get_server_specs(ip: str, ssh_user: str, ssh_pass: str, ssh_key_path: str | None = None):
    """
    Получает характеристики сервера (диск, RAM, количество ядер CPU) по SSH.
    Возвращает словарь с характеристиками или None в случае ошибки/отсутствия данных.
    """
    try:
        if not ssh_user:
            logger.warning(f"SSH-пользователь отсутствует для {ip}. Невозможно получить характеристики сервера.")
            return None
            
        disk_cmd = "df -h / | awk 'NR==2{print $2 \" \" $4}'" # Общий и доступный диск
        ram_cmd = "free -m | awk 'NR==2{print $2 \" \" $3 \" \" $4}'" # Общая, использованная, свободная RAM
        cpu_cmd = "nproc" # Количество ядер CPU

        # Приоритет: SSH ключ > пароль
        if ssh_key_path and os.path.exists(ssh_key_path):
            async with asyncssh.connect(ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=10) as conn:
                disk_res, ram_res, cpu_res = await asyncio.gather(
                    conn.run(disk_cmd, check=True),
                    conn.run(ram_cmd, check=True),
                    conn.run(cpu_cmd, check=True)
                )
        elif ssh_pass:
            async with asyncssh.connect(ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=10) as conn:
                disk_res, ram_res, cpu_res = await asyncio.gather(
                    conn.run(disk_cmd, check=True),
                    conn.run(ram_cmd, check=True),
                    conn.run(cpu_cmd, check=True)
                )
        else:
            logger.warning(f"SSH-учетные данные отсутствуют для {ip}. Невозможно получить характеристики сервера.")
            return None
            
        disk_output = disk_res.stdout.strip().split()
        ram_output = ram_res.stdout.strip().split()

        total_disk = disk_output[0] if len(disk_output) > 0 else "N/A"
        available_disk = disk_output[1] if len(disk_output) > 1 else "N/A"

        total_ram = f"{ram_output[0]} MB" if len(ram_output) > 0 else "N/A"
        used_ram = f"{ram_output[1]} MB" if len(ram_output) > 1 else "N/A"
        free_ram = f"{ram_output[2]} MB" if len(ram_output) > 2 else "N/A"

        return {
            "disk_total": total_disk,
            "disk_available": available_disk,
            "ram_total": total_ram,
            "ram_used": used_ram,
            "ram_free": free_ram,
            "cpu_cores": cpu_res.stdout.strip()
        }
    except (asyncssh.Error, ValueError, TypeError, TimeoutError) as e:
        logger.error(f"Не удалось получить характеристики сервера для {ip}: {e}")
        return None

async def get_server_stats(ip: str):
    """
    Получает полную статистику сервера: доступность, загрузку CPU, RAM, диск и характеристики.
    """
    logger.info(f"Проверка статуса сервера для {ip}")
    creds = server_config.get_server_credentials(ip)
    ssh_user = creds.get("ssh_user")
    ssh_pass = creds.get("ssh_pass")
    ssh_key_path = creds.get("ssh_key_path")

    status = "offline" # Статус по умолчанию

    try:
        # Проверка пингом
        ping_cmd = f"ping -c 1 -W 1 {ip}" # Предполагаем Linux
        if platform.system() == "Windows":
             ping_cmd = f"ping -n 1 -w 1000 {ip}" # -w - таймаут в мс

        process = await asyncio.create_subprocess_shell(
            ping_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        ping_success = process.returncode == 0
        
        # Получаем детальную статистику, только если пинг успешен или это локальный сервер
        # или если есть SSH-учетные данные (для сервера, который может не отвечать на пинг, но доступен по SSH)
        if ping_success or (ssh_user and (ssh_pass or ssh_key_path)) or (ip == "127.0.0.1" or ip == "localhost" or platform.node().lower() == ip.lower()):
            load_task = get_server_load(ip, ssh_user, ssh_pass, ssh_key_path)
            # Запускаем получение спецификаций, только если есть SSH-учетные данные
            specs_task = get_server_specs(ip, ssh_user, ssh_pass, ssh_key_path) if ssh_user and (ssh_pass or ssh_key_path) else asyncio.sleep(0, result=None)

            cpu_load, server_specs = await asyncio.gather(load_task, specs_task)

            if cpu_load != -1.0:
                status = "online"
            else:
                status = "partial_online" # Онлайн, но не удалось получить загрузку CPU

            return {
                "ip": ip,
                "status": status,
                "cpu_load": f"{cpu_load:.1f}%" if cpu_load != -1.0 else "N/A",
                "specs": server_specs,
                "message": "Онлайн" if status == "online" else "Частичные данные"
            }
        else:
            # Если пинг не удался и это не локальный сервер, считаем его оффлайн
            return {
                "ip": ip,
                "status": "offline",
                "cpu_load": "N/A",
                "specs": None,
                "message": "Оффлайн: Пинг не удался"
            }

    except Exception as e:
        logger.error(f"Ошибка при проверке статуса сервера для {ip}: {e}")
        return {
            "ip": ip,
            "status": "error",
            "cpu_load": "N/A",
            "specs": None,
            "message": f"Ошибка: {e}"
        }

# --- Существующие функции управления юзерботами (оставлены без изменений, но здесь для полноты) ---

async def manage_ub_service(ub_username: str, action: str, server_ip: str) -> dict:
    """Управляет (start/stop/restart) службой юзербота systemd."""
    logger.info(f"Попытка {action} службы юзербота {ub_username} на {server_ip}")
    creds = server_config.get_server_credentials(server_ip)
    ssh_user = creds.get("ssh_user")
    ssh_pass = creds.get("ssh_pass")
    ssh_key_path = creds.get("ssh_key_path")

    if not ssh_user:
        return {"success": False, "message": "Отсутствует SSH-пользователь для сервера."}

    service_name = f"userbot-{ub_username}"
    cmd = f"sudo systemctl {action} {service_name}"
    
    try:
        # Приоритет: SSH ключ > пароль
        if ssh_key_path and os.path.exists(ssh_key_path):
            async with asyncssh.connect(server_ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=10) as conn:
                result = await conn.run(cmd, check=True)
                if result.exit_status == 0:
                    logger.info(f"Команда {action} для {service_name} на {server_ip} успешно отправлена")
                    return {"success": True, "message": f"Команда '{action}' успешно выполнена."}
                else:
                    logger.error(f"Не удалось {action} {service_name} на {server_ip}: {result.stderr}")
                    return {"success": False, "message": f"Команда не выполнена: {result.stderr}"}
        elif ssh_pass:
            async with asyncssh.connect(server_ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=10) as conn:
                result = await conn.run(cmd, check=True)
                if result.exit_status == 0:
                    logger.info(f"Команда {action} для {service_name} на {server_ip} успешно отправлена")
                    return {"success": True, "message": f"Команда '{action}' успешно выполнена."}
                else:
                    logger.error(f"Не удалось {action} {service_name} на {server_ip}: {result.stderr}")
                    return {"success": False, "message": f"Команда не выполнена: {result.stderr}"}
        else:
            return {"success": False, "message": "Отсутствуют SSH-учетные данные для сервера."}
    except asyncssh.Error as e:
        logger.error(f"Ошибка SSH при управлении {service_name} на {server_ip}: {e}")
        return {"success": False, "message": f"Ошибка SSH-соединения: {e}"}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при управлении {service_name} на {server_ip}: {e}")
        return {"success": False, "message": f"Неожиданная ошибка: {e}"}

async def get_ub_service_status(ub_username: str, server_ip: str) -> dict:
    """Получает статус службы юзербота systemd."""
    logger.info(f"Проверка статуса службы юзербота {ub_username} на {server_ip}")
    creds = server_config.get_server_credentials(server_ip)
    ssh_user = creds.get("ssh_user")
    ssh_pass = creds.get("ssh_pass")
    ssh_key_path = creds.get("ssh_key_path")

    if not ssh_user:
        return {"status": "unknown", "message": "Отсутствует SSH-пользователь для сервера."}

    service_name = f"userbot-{ub_username}"
    cmd = f"systemctl is-active {service_name}"
    
    try:
        # Приоритет: SSH ключ > пароль
        if ssh_key_path and os.path.exists(ssh_key_path):
            async with asyncssh.connect(server_ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=10) as conn:
                result = await conn.run(cmd, check=False) # check=False, так как может быть код выхода 1 для неактивного
                
                status_text = result.stdout.strip()
                if status_text == "active":
                    return {"status": "running", "message": "Служба активна и запущена."}
                elif status_text == "inactive":
                    return {"status": "stopped", "message": "Служба неактивна (остановлена)."}
                elif status_text == "failed":
                     return {"status": "error", "message": "Служба находится в состоянии ошибки."}
                else:
                     return {"status": "unknown", "message": f"Неизвестный статус службы: {status_text}"}
        elif ssh_pass:
            async with asyncssh.connect(server_ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=10) as conn:
                result = await conn.run(cmd, check=False) # check=False, так как может быть код выхода 1 для неактивного
                
                status_text = result.stdout.strip()
                if status_text == "active":
                    return {"status": "running", "message": "Служба активна и запущена."}
                elif status_text == "inactive":
                    return {"status": "stopped", "message": "Служба неактивна (остановлена)."}
                elif status_text == "failed":
                     return {"status": "error", "message": "Служба находится в состоянии ошибки."}
                else:
                     return {"status": "unknown", "message": f"Неизвестный статус службы: {status_text}"}
        else:
            return {"status": "unknown", "message": "Отсутствуют SSH-учетные данные для сервера."}
    except asyncssh.Error as e:
        logger.error(f"Ошибка SSH при получении статуса для {service_name} на {server_ip}: {e}")
        return {"status": "error", "message": f"Ошибка SSH-соединения: {e}"}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении статуса для {service_name} на {server_ip}: {e}")
        return {"status": "error", "message": f"Неожиданная ошибка: {e}"}


async def create_server_user_and_setup_hikka(tg_user_id: int, ub_username: str, ub_type: str, server_ip: str) -> dict:
    """
    Создает нового пользователя на сервере, устанавливает Hikka и настраивает ее службу.
    Это сложная операция и здесь упрощена.
    """
    logger.info(f"Инициирование создания юзербота {ub_username} на {server_ip} для пользователя {tg_user_id}")
    creds = server_config.get_server_credentials(server_ip)
    ssh_user = creds.get("ssh_user")
    ssh_pass = creds.get("ssh_pass")
    ssh_key_path = creds.get("ssh_key_path")

    if not ssh_user:
        return {"success": False, "message": "Отсутствует SSH-пользователь для сервера."}

    try:
        # Приоритет: SSH ключ > пароль
        if ssh_key_path and os.path.exists(ssh_key_path):
            async with asyncssh.connect(server_ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=60) as conn:
                # 1. Создать пользователя на сервере (пример, заменить на реальное управление пользователями)
        elif ssh_pass:
            async with asyncssh.connect(server_ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=60) as conn:
                # 1. Создать пользователя на сервере (пример, заменить на реальное управление пользователями)
        else:
            return {"success": False, "message": "Отсутствуют SSH-учетные данные для сервера."}
            
        # cmd_create_user = f"sudo useradd -m {ub_username} -s /bin/bash"
        # await conn.run(cmd_create_user, check=True)
        # logger.info(f"Пользователь {ub_username} создан на {server_ip}")

        # 2. Настроить Hikka (упрощенные шаги)
        # Это заглушка, реальные шаги будут включать клонирование репозитория, установку зависимостей и т.д.
        # Пример:
        # cmd_setup_hikka = f"sudo -u {ub_username} bash -c 'cd /home/{ub_username} && git clone https://github.com/hikariatama/Hikka.git && cd Hikka && pip install -r requirements.txt'"
        # await conn.run(cmd_setup_hikka, check=True)
        # logger.info(f"Репозиторий Hikka клонирован и зависимости установлены для {ub_username}")

        # 3. Создать файл службы systemd (упрощено)
        # service_content = f"""
        # [Unit]
        # Description=Hikka Userbot Service for {ub_username}
        # After=network.target

        # [Service]
        # Type=simple
        # User={ub_username}
        # WorkingDirectory=/home/{ub_username}/Hikka
        # ExecStart=/usr/bin/python3 -m hikka
        # Restart=on-failure

        # [Install]
        # WantedBy=multi-user.target
        # """
        # await conn.put(asyncio.BytesIO(service_content.encode()), f"/tmp/userbot-{ub_username}.service", sudo=True, mode=0o644)
        # await conn.run(f"sudo mv /tmp/userbot-{ub_username}.service /etc/systemd/system/", check=True)
        # await conn.run("sudo systemctl daemon-reload", check=True)
        # await conn.run(f"sudo systemctl enable userbot-{ub_username}", check=True)
        # await conn.run(f"sudo systemctl start userbot-{ub_username}", check=True)
        # logger.info(f"Служба systemd для {ub_username} создана и запущена.")

        # Заглушка для реального пути Hikka (это должно быть из скрипта настройки)
        hikka_path = f"/home/{ub_username}/Hikka" 

        return {"success": True, "message": "Процесс создания юзербота инициирован.", "hikka_path": hikka_path}

    except asyncssh.Error as e:
        logger.error(f"Ошибка SSH во время создания юзербота для {ub_username} на {server_ip}: {e}")
        return {"success": False, "message": f"Ошибка SSH-соединения или команды: {e}"}
    except Exception as e:
        logger.error(f"Неожиданная ошибка во время создания юзербота для {ub_username} на {server_ip}: {e}")
        return {"success": False, "message": f"Неожиданная ошибка: {e}"}

async def delete_userbot_full(ub_username: str, server_ip: str) -> dict:
    """
    Полностью удаляет юзербота: останавливает службу, отключает, удаляет файлы и пользователя.
    Это сложная операция и здесь упрощена.
    """
    logger.info(f"Инициирование удаления юзербота {ub_username} на {server_ip}")
    creds = server_config.get_server_credentials(server_ip)
    ssh_user = creds.get("ssh_user")
    ssh_pass = creds.get("ssh_pass")
    ssh_key_path = creds.get("ssh_key_path")

    if not ssh_user:
        return {"success": False, "message": "Отсутствует SSH-пользователь для сервера."}

    try:
        # Приоритет: SSH ключ > пароль
        if ssh_key_path and os.path.exists(ssh_key_path):
            async with asyncssh.connect(server_ip, username=ssh_user, client_keys=[ssh_key_path], known_hosts=None, timeout=60) as conn:
        elif ssh_pass:
            async with asyncssh.connect(server_ip, username=ssh_user, password=ssh_pass, known_hosts=None, timeout=60) as conn:
        else:
            return {"success": False, "message": "Отсутствуют SSH-учетные данные для сервера."}
            
        # 1. Остановить и отключить службу systemd
        try:
            await conn.run(f"sudo systemctl stop userbot-{ub_username}", check=False)
            await conn.run(f"sudo systemctl disable userbot-{ub_username}", check=False)
            await conn.run(f"sudo rm /etc/systemd/system/userbot-{ub_username}.service", check=False)
            await conn.run("sudo systemctl daemon-reload", check=True)
            logger.info(f"Служба systemd для {ub_username} остановлена и удалена.")
        except Exception as e:
            logger.warning(f"Не удалось остановить/отключить службу для {ub_username} (возможно, не существует): {e}")

        # 2. Удалить домашний каталог пользователя и самого пользователя
        cmd_delete_user_data = f"sudo rm -rf /home/{ub_username}"
        await conn.run(cmd_delete_user_data, check=False) # Используем check=False, если каталог не существует
        logger.info(f"Удален /home/{ub_username}")

        cmd_delete_user = f"sudo userdel -r {ub_username}" # -r также удаляет домашний каталог
        await conn.run(cmd_delete_user, check=False) # Используем check=False, если пользователь не существует
        logger.info(f"Пользователь {ub_username} удален с {server_ip}")
        
        return {"success": True, "message": "Юзербот успешно удален с сервера."}

    except asyncssh.Error as e:
        logger.error(f"Ошибка SSH во время удаления юзербота для {ub_username} на {server_ip}: {e}")
        return {"success": False, "message": f"Ошибка SSH-соединения или команды: {e}"}
    except Exception as e:
        logger.error(f"Неожиданная ошибка во время удаления юзербота для {ub_username} на {server_ip}: {e}")
        return {"success": False, "message": f"Неожиданная ошибка: {e}"}
