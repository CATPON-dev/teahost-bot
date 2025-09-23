import aiohttp
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from config_manager import config
import server_config
import json

logger = logging.getLogger(__name__)


class APIManager:
    def __init__(self):
        self.vpn_base_url = "https://vpn.dev3quest.lol:8000"
        self.vpn_username = "teahost"
        self.vpn_password = "nloveuser_tg"
        self.base_url = "http://m7.sharkhost.space:8000"
        self.token = "kivWJmOe2ey9u50uCqEwCIcHstCwuZslu7QK4YcEsCTGQcUTx33JC3bZve0zvr8y"

    def get_server_api_config(self, server_ip: str) -> tuple[str, str]:
        api_url = server_config.get_server_api_url(server_ip)
        api_token = server_config.get_server_api_token(server_ip)

        if not api_url:
            api_url = self.base_url
        if not api_token:
            api_token = self.token

        return api_url, api_token

    async def get_vpn_token(self) -> Optional[str]:
        token_url = f"{self.vpn_base_url}/api/admin/token"

        token_data = {
            "grant_type": "password",
            "username": self.vpn_username,
            "password": self.vpn_password,
            "scope": "",
            "client_id": "string",
            "client_secret": "string"
        }

        token_headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    token_url,
                    data=token_data,
                    headers=token_headers,
                    ssl=False
                ) as token_response:

                    if token_response.status == 200:
                        token_result = await token_response.json()
                        return token_result.get("access_token")
                    else:
                        error_text = await token_response.text()
                        logger.error(
                            f"Ошибка получения токена VPN: {token_response.status} - {error_text}")
                        return None

        except Exception as e:
            logger.error(
                f"Ошибка при получении токена VPN: {e}",
                exc_info=True)
            return None

    async def create_vpn(self, name: str) -> Dict[str, Any]:
        access_token = await self.get_vpn_token()
        if not access_token:
            return {
                "success": False,
                "error": "Не удалось получить токен доступа VPN"}

        url = f"{self.vpn_base_url}/api/user"

        data = {
            "username": name,
            "proxies": {
                "vless": {}
            },
            "inbounds": {
                "vless": [
                    "VLESS TCP REALITY"
                ]
            },
            "expire": None,
            "data_limit": 0,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": "Created automatically without expiration"
        }

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    ssl=False
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"VPN пользователь {name} успешно создан (без лимита времени)")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка создания VPN пользователя {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}

        except Exception as e:
            logger.error(
                f"Ошибка при создании VPN пользователя {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def delete_vpn(self, username: str) -> Dict[str, Any]:
        access_token = await self.get_vpn_token()
        if not access_token:
            return {
                "success": False,
                "error": "Не удалось получить токен доступа VPN"}

        url = f"{self.vpn_base_url}/api/user/{username}"

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.delete(
                    url,
                    headers=headers,
                    ssl=False
                ) as response:

                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"VPN пользователь {username} успешно удален")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка удаления VPN пользователя {username}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}

        except Exception as e:
            logger.error(
                f"Ошибка при удалении VPN пользователя {username}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def create_container(self, name: str, port: int, userbot: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/create"
        params = {
            "name": name,
            "port": port,
            "userbot": userbot
        }
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"Контейнер {name} успешно создан на порту {port}")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка создания контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при создании контейнеров {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def delete_container(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/remove"
        params = {"name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Контейнер {name} успешно удален")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка удаления контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при удалении контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_container_status(self, name: str, server_ip: str, timeout: float = 8.0) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/status"
        params = {"name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка получения статуса контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при получении статуса контейнера {name}")
            return {"success": False, "error": "Таймаут запроса"}
        except Exception as e:
            logger.error(
                f"Ошибка при получении статуса контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_container_logs(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/logs"
        params = {"name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка получения логов контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при получении логов контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_container_stats(self, name: str, server_ip: str, timeout: float = 10.0) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/cont_stat"
        params = {"name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            logger.info(
                f"Запрашиваем статистику контейнера {name} с URL: {url}")
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    logger.info(
                        f"Получен ответ для статистики контейнера {name}: {response.status}")
                    if response.status == 200:
                        result = await response.json()
                        logger.info(
                            f"Успешно получена статистика для контейнера {name}")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка получения статистики контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при получении статистики контейнера {name}")
            return {"success": False, "error": "Таймаут запроса"}
        except Exception as e:
            logger.error(
                f"Ошибка при получении статистики контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_server_ping(self, server_ip: str) -> Optional[float]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/ping"
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            start_time = asyncio.get_event_loop().time()

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    end_time = asyncio.get_event_loop().time()

                    if response.status == 200:
                        result = await response.json()
                        if result.get("message") == "pong":
                            ping_ms = (end_time - start_time) * 1000
                            return round(ping_ms, 1)

                    return None
        except Exception as e:
            logger.error(
                f"Ошибка при измерении пинга до сервера {server_ip}: {e}")
            return None

    async def start_container(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/action"
        params = {"type": "start", "name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Контейнер {name} успешно запущен")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка запуска контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при запуске контейнера {name}")
            return {"success": False, "error": "Таймаут запроса"}
        except Exception as e:
            logger.error(
                f"Ошибка при запуске контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def stop_container(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/action"
        params = {"type": "stop", "name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Контейнер {name} успешно остановлен")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка остановки контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при остановке контейнера {name}")
            return {"success": False, "error": "Таймаут запроса"}
        except Exception as e:
            logger.error(
                f"Ошибка при остановке контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def restart_container(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/action"
        params = {"type": "restart", "name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=20.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Контейнер {name} успешно перезапущен")
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка перезапуска контейнера {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при перезапуске контейнера {name}")
            return {"success": False, "error": "Таймаут запроса"}
        except Exception as e:
            logger.error(
                f"Ошибка при перезапуске контейнера {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_container_list(self, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/list"
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка получения списка контейнеров с {server_ip}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при получении списка контейнеров с {server_ip}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def exec_in_container(self, name: str, command: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/exec"
        params = {"name": name, "command": command}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=300.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка выполнения команды в контейнере {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при выполнении команды в контейнере {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def exec_all(self, command: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/exec_all"
        params = {"command": command}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=300.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка выполнения команды во всех контейнерах: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при выполнении команды во всех контейнерах: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def check_session(self, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/check_session"
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=300.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка проверки сессии: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(f"Ошибка при проверке сессии: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def reinstall_ub(self, name: str, userbot: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/action"
        params = {"type": "recreate", "name": name, "userbot": userbot}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=300.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка переустановки юзербота {name}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Ошибка при переустановке юзербота {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def backup_container(self, name: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/backup"
        params = {"name": name}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=600.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка создания бэкапа для {name} на {server_ip}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Исключение при создании бэкапа {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}

    async def restore_container(self, name: str, userbot_type: str, server_ip: str) -> Dict[str, Any]:
        api_url, api_token = self.get_server_api_config(server_ip)
        url = f"{api_url}/api/host/restore"
        params = {"name": name, "userbot": userbot_type}
        headers = {
            "accept": "application/json",
            "token": api_token
        }

        try:
            timeout = aiohttp.ClientTimeout(total=600.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {"success": True, "data": result}
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Ошибка восстановления {name} на {server_ip}: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}: {error_text}"}
        except Exception as e:
            logger.error(
                f"Исключение при восстановлении {name}: {e}",
                exc_info=True)
            return {"success": False, "error": str(e)}


api_manager = APIManager()
