# meta developer: @EXPERT_CATPON

import aiohttp
import asyncio
from herokutl.tl.types import Message
from .. import loader, utils
import datetime

def parse_ps_etime_to_human(etime: str) -> str:
    """
    Преобразует в человеческий формат :з 
    """
    etime = etime.strip()
    days = 0
    hours = 0
    minutes = 0
    if '-' in etime:
        days_part, time_part = etime.split('-', 1)
        try:
            days = int(days_part)
        except Exception:
            days = 0
    else:
        time_part = etime
    parts = time_part.split(':')
    if len(parts) == 3:
        hours, minutes, _ = parts
    elif len(parts) == 2:
        hours, minutes = parts
    else:
        hours = 0
        minutes = 0
    try:
        hours = int(hours)
        minutes = int(minutes)
    except Exception:
        hours = 0
        minutes = 0
    result = []
    if days:
        result.append(f"{days}d")
    if hours:
        result.append(f"{hours}h")
    if minutes:
        result.append(f"{minutes}m")
    return ' '.join(result) if result else '~1m'

def format_iso_datetime(dt_str: str) -> str:
    """
    Преобразование даты в красивый вид
    """
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        return dt.strftime('%d.%m.%Y в %H:%M')
    except Exception:
        return dt_str

def days_ago_text(dt_str: str) -> str:
    """
    Форматирование даты создания и регистрации
    """
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
        days = (now.date() - dt.date()).days
        if days < 0:
            days = 0
        if days % 10 == 1 and days % 100 != 11:
            word = 'день'
        elif 2 <= days % 10 <= 4 and (days % 100 < 10 or days % 100 >= 20):
            word = 'дня'
        else:
            word = 'дней'
        return f"{days} {word} назад"
    except Exception:
        return dt_str

@loader.tds
class SharkHostMod(loader.Module):
    """Модуль для управления юзерботом SharkHost."""

    strings = {
        "name": "SharkHost",
        "config_api_url": "URL API SharkHost.",
        "config_api_token": "Ваш API токен. @SharkHostBot.",
        "token_not_set": "🚫 <b>API токен не установлен!</b>",
        "getting_info": "🔄 <b>Узнаю информацию ...</b>",
        "no_ub": "🚫 <b>У вас нет активных юзербота.</b>",
        "no_ub_name": "🚫 <b>Error, UserBot not found name.</b>",
        "started": "✅ Started",
        "stopped": "❌ Stopped",
        "restarted": "🔄 Restarted",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "api_url",
                "http://158.160.35.181:2000",
                lambda: self.strings("config_api_url"),
                validator=loader.validators.Link(),
            ),
            loader.ConfigValue(
                "api_token",
                None,
                lambda: self.strings("config_api_token"),
                validator=loader.validators.Hidden(),
            ),
        )

    async def _request(self, method: str, path: str, **kwargs):
        if not self.config["api_token"]:
            return self.strings("token_not_set")

        headers = {"X-API-Token": self.config["api_token"]}
        url = f"{self.config['api_url'].strip('/')}/api/v1/{path}"

        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.request(method, url, **kwargs) as resp:
                    data = await resp.json()
                    if data.get("success"):
                        return data.get("data")
                    else:
                        error = data.get("error", {})
                        return (f"🚫 <b>API Ошибка:</b> <code>{error.get('code', 'UNKNOWN')}</code>\n"
                                f"<blockquote>🗒️ <b>Сообщение:</b> {utils.escape_html(error.get('message', 'Нет деталей'))}</blockquote>")
            except aiohttp.ClientError as e:
                return f"🚫 <b>Ошибка сети:</b> <blockquote>{e}</blockquote>"

    async def _get_my_userbot(self):
        response = await self._request("GET", "userbots")
        if isinstance(response, str):
            return response
        
        userbots = response.get("userbots", [])
        if not userbots:
            return self.strings("no_ub")
        
        return userbots[0]

    @loader.command(ru_doc="[код] - Show servers status")
    async def sstatuscmd(self, message: Message):
        """[code] - Show servers status"""
        await utils.answer(message, "🔄 <b>Запрашиваю статусы...</b>")
        args = utils.get_args_raw(message)
        params = {"code": args} if args else {}
        
        response = await self._request("GET", "servers/status", params=params)

        if isinstance(response, str):
            await utils.answer(message, response)
            return

        servers = response.get("servers", [])
        if not servers:
            await utils.answer(message, "✅ <b>Серверы не найдены.</b>")
            return

        result = "📡 <b>Статус серверов SharkHost:</b>\n"
        for server in servers:
            result += (
                f"\n<blockquote>"
                f"{server['flag']} <b>{server['name']}</b> (<code>{server['code']}</code>)\n\n"
                f"📍 <b>Локация:</b> <i>{server['location']}</i>\n"
                f"🚦 <b>Статус:</b> <code>{server['status']}</code>\n"
                f"⚙️ <b>CPU:</b> {server['cpu_usage']} | <b>RAM:</b> {server['ram_usage']}\n"
                f"💾 <b>Диск:</b> {server['disk_usage']}\n"
                f"🤖 <b>Юзерботы:</b> {server['slots']}"
                f"</blockquote>"
            )
        
        await utils.answer(message, result)

    @loader.command(ru_doc="<reply/ID/юзернейм> - Show user info")
    async def scheckcmd(self, message: Message):
        """<reply/ID/username> - Show user info"""
        identifier = utils.get_args_raw(message)

        if not identifier:
            if message.is_reply:
                reply = await message.get_reply_message()
                identifier = str(reply.sender_id)
            else:
                await utils.answer(message, "🚫 <b>Укажите ID/юзернейм или ответьте на сообщение пользователя.</b>")
                return

        await utils.answer(message, "🔄 <b>Запрашиваю информацию...</b>")
        response = await self._request("GET", f"users/{identifier}")

        if isinstance(response, str):
            await utils.answer(message, response)
            return
        
        owner = response.get('owner', {})
        userbot = response.get('userbot')
        
        owner_username = owner.get('username') or owner.get('id', 'N/A')
        
        result = (f"👤 <b>Информация о пользователе</b> <a href=\"tg://user?id={owner.get('id')}\">{utils.escape_html(str(owner_username))}</a>:\n\n")
        
        result += "<blockquote>"
        result += f"<b> • ID:</b> <code>{owner.get('id', 'N/A')}</code>\n"
        result += f"<b> • Полное имя:</b> <i>{utils.escape_html(owner.get('full_name') or 'Не указано')}</i>\n"
        reg_date = owner.get('registered_at')
        result += f"<b> • Зарегистрировался:</b> <i>{utils.escape_html(days_ago_text(reg_date)) if reg_date else 'Неизвестно'}</i>"
        result += "</blockquote>\n"
        
        if userbot:
            result += "\n🤖 <b>Информация о юзерботе:</b>\n<blockquote>"
            result += (
                f"<b> • Системное имя:</b> <code>{userbot.get('ub_username')}</code>\n"
                f"<b> • Тип:</b> <code>{userbot.get('ub_type')}</code>\n"
                f"<b> • Статус:</b> <code>{userbot.get('status')}</code>\n"
                f"<b> • Сервер:</b> <code>{userbot.get('server_code')}</code>\n"
                f"<b> • Создал:</b> <i>{utils.escape_html(days_ago_text(userbot.get('created_at'))) if userbot.get('created_at') else 'Неизвестно'}</i>"
            )
            uptime = userbot.get('uptime')
            if uptime:
                result += f"\n<b> • Аптайм:</b> <code>{utils.escape_html(parse_ps_etime_to_human(uptime))}</code>"
            result += "</blockquote>"
        else:
            result += "<blockquote>ℹ️ <i>У этого пользователя нет активного юзербота.</i></blockquote>"

        await utils.answer(message, result)
    
    @loader.command(ru_doc="Open menu action userbot")
    async def smanagecmd(self, message: Message):
        """Open menu action userbot"""
        status_message = await utils.answer(message, self.strings("getting_info"))

        userbot_data = await self._get_my_userbot()

        if isinstance(userbot_data, str):
            await utils.answer(status_message, userbot_data)
            return
        
        ub_username = userbot_data.get("ub_username")
        ub_status = userbot_data.get("status")

        if not ub_username or not ub_status:
            await utils.answer(status_message, self.strings("no_ub_name"))
            return

        await self.inline.form(
            message=status_message,
            **self._get_manage_menu_content(ub_username, ub_status)
        )

    def _get_manage_menu_content(self, ub_username: str, status: str) -> dict:
        text = (f"🕹️ <b>Управление юзерботом</b> <code>{utils.escape_html(ub_username)}</code>\n"
                f"<b>Текущий статус:</b> <code>{status}</code>\n\n"
                f"Выберите действие:")
        
        markup = []
        row = []
        if status == "running":
            row.append({"text": "🛑 Остановить", "callback": self._manage_callback, "args": (ub_username, "stop")})
            row.append({"text": "🔄 Перезапустить", "callback": self._manage_callback, "args": (ub_username, "restart")})
        else: 
            row.append({"text": "🚀 Запустить", "callback": self._manage_callback, "args": (ub_username, "start")})
            row.append({"text": "🔄 Перезапустить", "callback": self._manage_callback, "args": (ub_username, "restart")})
        
        markup.append(row)
        markup.append([{"text": "❌ Закрыть", "action": "close"}])

        return {"text": text, "reply_markup": markup}

    async def _manage_callback(self, call, ub_username: str, action: str):
        feedback = {
            "start": self.strings("started"),
            "stop": self.strings("stopped"),
            "restart": self.strings("restarted")
        }
        await call.edit(feedback.get(action, "✅ Готово!"))
        
        payload = {"action": action}
        await self._request("POST", f"userbots/{ub_username}/manage", json=payload)

        new_info_response = await self._get_my_userbot()
        if isinstance(new_info_response, str) or not new_info_response.get("ub_username"):
            await call.edit(
                "🚫 Не удалось обновить статус меню. Закройте его и вызовите снова.",
                reply_markup=None
            )
            return

        new_status = new_info_response.get("status")
        await call.edit(**self._get_manage_menu_content(ub_username, new_status))
    
    async def _direct_manage_action(self, message: Message, action: str):
        status_message = await utils.answer(message, self.strings("getting_info"))
        
        userbot_data = await self._get_my_userbot()
        if isinstance(userbot_data, str):
            await utils.answer(status_message, userbot_data)
            return

        ub_username = userbot_data.get("ub_username")
        if not ub_username:
            await utils.answer(status_message, self.strings("no_ub_name"))
            return

        feedback = {
            "start": self.strings("started"),
            "stop": self.strings("stopped"),
            "restart": self.strings("restarted")
        }
        await utils.answer(status_message, feedback.get(action, "✅ Готово!"))
        
        payload = {"action": action}
        await self._request("POST", f"userbots/{ub_username}/manage", json=payload)


    @loader.command(ru_doc="Start userbot")
    async def sstartcmd(self, message: Message):
        """Start userbot"""
        await self._direct_manage_action(message, "start")

    @loader.command(ru_doc="Stop userbot")
    async def sstopcmd(self, message: Message):
        """Stop userbot"""
        await self._direct_manage_action(message, "stop")

    @loader.command(ru_doc="Restart userbot")
    async def srestartcmd(self, message: Message):
        """Restart userbot"""
        await self._direct_manage_action(message, "restart")