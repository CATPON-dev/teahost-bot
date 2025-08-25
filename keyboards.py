# --- START OF FILE keyboards.py ---
from aiogram.types import InlineKeyboardButton, WebAppInfo
from aiogram import html
from aiogram.utils.keyboard import InlineKeyboardBuilder
import server_config
import database as db
from admin_manager import get_all_admins
import system_manager as sm
import datetime
from config_manager import config

def get_stats_refresh_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="refresh_stats_panel")
    return builder.as_markup()

def get_session_check_keyboard(view_mode: str, page: int = 0, total_pages: int = 1, expanded_servers: set = None):
    builder = InlineKeyboardBuilder()
    
    if expanded_servers is None:
        expanded_servers = set()
    
    # Первая строка: навигация по страницам
    nav_buttons = []
    
    # Кнопка "В начало"
    if page > 0:
        nav_buttons.append(("⏮️", f"check_page:{view_mode}:0"))
    else:
        nav_buttons.append(("⏮️", "no_action"))
    
    # Кнопка "Назад"
    if page > 0:
        nav_buttons.append(("◀️", f"check_page:{view_mode}:{page-1}"))
    else:
        nav_buttons.append(("◀️", "no_action"))
    
    # Информация о странице
    nav_buttons.append((f"{page+1}/{total_pages}", "no_action"))
    
    # Кнопка "Вперед"
    if page < total_pages - 1:
        nav_buttons.append(("▶️", f"check_page:{view_mode}:{page+1}"))
    else:
        nav_buttons.append(("▶️", "no_action"))
    
    # Кнопка "В конец"
    if page < total_pages - 1:
        nav_buttons.append(("⏭️", f"check_page:{view_mode}:{total_pages-1}"))
    else:
        nav_buttons.append(("⏭️", "no_action"))
    
    # Добавляем кнопки навигации на первую строку
    for text, callback_data in nav_buttons:
        builder.button(text=text, callback_data=callback_data)
    
    # Вторая строка: кнопка переключения режима
    if view_mode == 'has_session':
        builder.button(text="👻 Показать без сессий", callback_data="check_view_toggle:no_session")
    else:
        builder.button(text="✅ Показать с сессиями", callback_data="check_view_toggle:has_session")
    
    # Третья строка: кнопка обновления
    builder.button(text="🔄 Обновить", callback_data="refresh_session_check")
    
    # Настройка расположения кнопок: 5 кнопок на первой строке, 1 на второй, 1 на третьей
    builder.adjust(5, 1, 1)
    
    return builder.as_markup()

def get_cancel_review_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_review")
    return builder.as_markup()

def get_review_approval_keyboard(user_id: int, user_message_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=f"approve_review:{user_id}:{user_message_id}")
    builder.button(text="❌ Нет", callback_data="reject_review")
    return builder.as_markup()

def get_subscribe_keyboard(channel_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подписаться", url=f"https://t.me/{channel_id.lstrip('@')}")
    builder.button(text="🔄 Я подписался", callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()

def get_server_selection_keyboard(user_id: int, installed_bots_map: dict, server_stats: dict, servers_on_page: list, page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    is_admin = user_id in get_all_admins()
    
    for ip, details in servers_on_page:
        status = details.get("status", "false")
        slots = details.get("slots", 0)
        installed = installed_bots_map.get(ip, 0)
        flag = details.get("flag", "🏳️")
        code = details.get("code", "N/A")
        cpu_load = server_stats.get(ip, {}).get('cpu_usage', 'N/A')
        
        if status == "false":
            emoji_status = "🔴"
            callback_data = "server_unavailable"
        elif status == "test":
            emoji_status = "🧪"
            callback_data = f"select_server:{ip}"
        elif status == "noub":
            emoji_status = "🟢"
            callback_data = "server_noub"
        elif slots > 0 and installed >= slots:
            emoji_status = "🈵"
            callback_data = "server_full"
        else:
            emoji_status = "🟢"
            callback_data = f"select_server:{ip}"

        button_text = f"{emoji_status} | [{installed}/{slots}] | {flag} | {code} | 📈 {cpu_load}%"
        builder.button(text=button_text, callback_data=callback_data)

    builder.adjust(1)
    
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="« 1", callback_data=f"select_server_page:1"))
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"select_server_page:{page - 1}"))
        
        nav_buttons.append(InlineKeyboardButton(text=f"· {page}/{total_pages} ·", callback_data="noop"))
        
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"select_server_page:{page + 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text=f"{total_pages} »", callback_data=f"select_server_page:{total_pages}"))
        
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_panel"))
    return builder.as_markup()
    
def get_main_panel_keyboard(has_bots: bool, user_id: int = None, chat_id: int = None, is_chat: bool = False):
    builder = InlineKeyboardBuilder()
    is_admin = user_id in get_all_admins()

    if is_chat:
        if has_bots:
            builder.button(text="⚙️ Панель управления", callback_data="go_to_control_panel")
        else:
            builder.button(text="🚀 Установить юзербот", callback_data="create_userbot_start")
        builder.adjust(1)
        return builder.as_markup()

    if has_bots:
        builder.button(text="⚙️ Панель управления", callback_data="go_to_control_panel")
    else:
        builder.button(text="🚀 Установить юзербот", callback_data="create_userbot_start")
    
    if is_admin:
        builder.button(text="🔑 API", callback_data="api_panel_show")
    
    builder.button(text="🛠️ Статус серверов", url="https://t.me/shark_status")
    builder.button(text="💬 Поддержка", url="t.me/SharkHost_support")
    builder.adjust(1)
    return builder.as_markup()
    
def get_api_token_keyboard(is_shown: bool):
    builder = InlineKeyboardBuilder()
    
    toggle_text = "🙈 Скрыть значение" if is_shown else "🙉 Показать значение"
    builder.button(text=toggle_text, callback_data="toggle_api_token_visibility")
    
    builder.button(text="🔄 Сгенерировать новый", callback_data="regenerate_api_token")
    builder.button(text="🔙 Назад", callback_data="back_to_main_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_back_to_main_panel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В главное меню", callback_data="back_to_main_panel")
    return builder.as_markup()
    
def back_to_panel():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="go_to_control_panel")
    return builder.as_markup()

def get_user_list_paginator(page: int, total_pages: int, view_mode: str):
    builder = InlineKeyboardBuilder()
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_page:{view_mode}:{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"user_page:{view_mode}:{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)

    if view_mode == "visible":
        toggle_text = "👻 Показать скрытых"
        toggle_callback = "user_view_toggle:hidden"
    else:
        toggle_text = "✅ Показать активных"
        toggle_callback = "user_view_toggle:visible"
        
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=toggle_callback))
    
    return builder.as_markup()

def get_confirm_unstable_server_keyboard(server_ip: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, продолжить", callback_data=f"confirm_unstable:{server_ip}")
    builder.button(text="❌ Нет, выбрать другой", callback_data="create_userbot_start")
    builder.adjust(1)
    return builder.as_markup()

def get_select_ub_type_keyboard(server_ip: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🌘 Hikka", callback_data=f"ub_type:hikka:{server_ip}")
    builder.button(text="🪐 Heroku", callback_data=f"ub_type:heroku:{server_ip}")
    builder.button(text="🦊 FoxUserbot", callback_data=f"ub_type:fox:{server_ip}")
    builder.button(text="🌙 Legacy", callback_data=f"ub_type:legacy:{server_ip}") 
    builder.button(text="🔙 Назад к выбору сервера", callback_data="create_userbot_start")
    builder.adjust(1)
    return builder.as_markup()

def get_login_link_success_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В главное меню", callback_data="back_to_main_panel")
    builder.adjust(1)
    return builder.as_markup()
    
def get_management_keyboard(ip: str, port: int, is_running: bool, ub_username: str, ub_type: str, is_server_active: bool, is_inline: bool = False, inline_message_id: str = None, is_owner: bool = True, is_private: bool = True, owner_id: int = None, is_shared: bool = False, is_installing: bool = False, is_deleting: bool = False, is_super_admin: bool = False):
    builder = InlineKeyboardBuilder()

    owner_id_str = str(owner_id) if owner_id is not None else "unknown"

    def create_callback(action):
        if is_inline and inline_message_id:
            return f"inline_btn_manage:{action}:{ub_username}:{owner_id_str}:{inline_message_id}"
        else:
            return f"manage_ub:{action}:{ub_username}:{owner_id_str}"

    if not is_inline:
        builder.button(text="🔄 Обновить", callback_data=f"refresh_panel:{ub_username}:{owner_id_str}")
    
    if not is_server_active:
        builder.button(text="🔴 Управление отключено", callback_data=f"noop:{owner_id_str}")
    elif is_running:
        builder.button(text="🔴 Выключить", callback_data=create_callback("stop"))
        builder.button(text="🌐 Веб панель", web_app=WebAppInfo(url=f"https://{ub_username}.sharkhost.space"))
        builder.button(text="🔑 Данные для авторизации", callback_data=create_callback("auth"))
        builder.button(text="🇩🇪VPN", callback_data=create_callback("vpn"))
        builder.button(text="🔄 Перезагрузить", callback_data=create_callback("restart"))
        builder.button(text="🔀 Переустановка", callback_data=create_callback("recreate"))
    else:
        builder.button(text="🚀 Включить", callback_data=create_callback("start"))
    
    builder.adjust(1, 2)

    if is_owner:
        if is_private and not is_installing and not is_deleting:
            builder.row(
                InlineKeyboardButton(text="🖥️ Терминал", switch_inline_query_current_chat="exec "),
                InlineKeyboardButton(text="⚡️ Inline действие", switch_inline_query_current_chat="action ")
            )
        if not is_inline:
            if is_private:
                builder.row(InlineKeyboardButton(text="📜 Логи", callback_data=f"show_user_logs:docker:{ub_username}:{owner_id_str}:1"))
            # if ub_type == 'heroku' and is_private:
            #     builder.row(InlineKeyboardButton(text="💾 Бекап (experimental)", callback_data=f"heroku_backup:{ub_username}:{owner_id_str}"))
            if is_private:
                builder.row(InlineKeyboardButton(text="👥 Поделиться панелью", callback_data=f"share_panel_start:{ub_username}"))
            if is_super_admin:
                builder.row(InlineKeyboardButton(text="🔄 Сменить сервер", callback_data=f"migrate_ub_start:{ub_username}"))
            builder.row(InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_ub_confirm_request:{ub_username}:{owner_id_str}"))
    else:
        if not is_inline:
            builder.row(InlineKeyboardButton(text="📜 Логи", callback_data=f"show_user_logs:docker:{ub_username}:{owner_id_str}:1"))
        if is_shared:
            builder.row(InlineKeyboardButton(text="🚫 Отказаться от доступа", callback_data=f"shared_reject_access:{ub_username}"))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_panel"))

    if hasattr(builder, 'inline_keyboard'):
        builder.inline_keyboard = [row for row in builder.inline_keyboard if row and any(b for b in row)]
    return builder.as_markup()

def get_confirm_delete_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delete_ub_execute:{ub_username}")
    builder.button(text="❌ Нет, отмена", callback_data=f"delete_ub_cancel:{ub_username}")
    return builder.as_markup()

def get_confirm_reinstall_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, переустановить", callback_data=f"reinstall_ub_execute:{ub_username}")
    builder.button(text="❌ Отмена", callback_data=f"reinstall_ub_cancel:{ub_username}")
    builder.adjust(1)
    return builder.as_markup()

def get_back_to_panel_after_reinstall(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к панели", callback_data=f"refresh_panel:{ub_username}")
    return builder.as_markup()

def get_loading_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🕕 Загрузка...", callback_data="noop_loading")
    return builder.as_markup()

def get_agreement_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Почитать соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-dlya-SharkHost-06-23")
    builder.button(text="✅ Принять и продолжить", callback_data="accept_agreement")
    builder.adjust(1)
    return builder.as_markup()

def get_server_info_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="refresh_server_info")
    return builder.as_markup()
    
def _get_server_buttons(builder: InlineKeyboardBuilder, installed_bots_map: dict, server_stats: dict, servers_on_page: dict):
    for ip, details in servers_on_page.items():
        if ip == "127.0.0.1" or ip == sm.LOCAL_IP:
            continue

        status = details.get("status", "false")
        slots = details.get("slots", 0)
        installed = installed_bots_map.get(ip, 0)
        
        if status == 'false': emoji_status = "🔴"
        elif status == 'test': emoji_status = "🧪"
        elif slots > 0 and installed >= slots: emoji_status = "🈵"
        else: emoji_status = "🟢"

        flag = details.get("flag", "🏳️")
        code = details.get("code", "N/A")
        city = details.get("city", "Unknown")
        cpu_load = server_stats.get(ip, {}).get('cpu_usage', 'N/A')

        button_text = f"[{installed}/{slots}] | {emoji_status} | {flag} | {code} | {city} | 📈 {cpu_load}%"
        builder.button(text=button_text, callback_data="noop")
    
def get_public_status_keyboard(installed_bots_map: dict, server_stats: dict, servers_on_page: dict, page: int = 1, total_pages: int = 1):
    builder = InlineKeyboardBuilder()
    _get_server_buttons(builder, installed_bots_map, server_stats, servers_on_page)
    builder.adjust(1)
    if total_pages > 1:
        nav_buttons = []
        if page > 1: nav_buttons.append(InlineKeyboardButton(text="« 1", callback_data=f"status_page:1"))
        if page > 1: nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"status_page:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"· {page}/{total_pages} ·", callback_data="noop"))
        if page < total_pages: nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"status_page:{page + 1}"))
        if page < total_pages: nav_buttons.append(InlineKeyboardButton(text=f"{total_pages} »", callback_data=f"status_page:{total_pages}"))
        builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_public_status"))
    return builder.as_markup()
    
def get_reinstall_userbot(ub_username: str, owner_id_str: str):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🌘 Hikka", 
        callback_data=f"manage_ub:reinstall:{ub_username}:{owner_id_str}:hikka"
    )
    builder.button(
        text="🪐 Heroku", 
        callback_data=f"manage_ub:reinstall:{ub_username}:{owner_id_str}:heroku"
    )
    builder.button(
        text="🦊 FoxUserbot", 
        callback_data=f"manage_ub:reinstall:{ub_username}:{owner_id_str}:fox"
    )
    builder.button(
        text="🌙 Legacy", 
        callback_data=f"manage_ub:reinstall:{ub_username}:{owner_id_str}:legacy"
    ) 
    builder.button(
        text="🔙 Назад к панели управления", 
        callback_data=f"refresh_panel:{ub_username}"
    )
    builder.adjust(1)
    return builder.as_markup()

def get_ub_info_keyboard(is_running: bool, ub_username: str, is_blocked: bool):
    builder = InlineKeyboardBuilder()
    if is_running:
        builder.button(text="⏹ Остановить", callback_data=f"manage_ub_info:stop:{ub_username}")
        builder.button(text="🔄 Перезапустить", callback_data=f"manage_ub_info:restart:{ub_username}")
    else:
        builder.button(text="▶️ Запустить", callback_data=f"manage_ub_info:start:{ub_username}")
    builder.adjust(2)

    if is_blocked:
        builder.row(InlineKeyboardButton(text="🟢 Разблокировать", callback_data=f"toggle_block_ub:{ub_username}:0"))
    else:
        builder.row(InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"toggle_block_ub:{ub_username}:1"))
    
    builder.row(InlineKeyboardButton(text="📝 Добавить/Изменить заметку", callback_data=f"add_note_start:{ub_username}"))
    builder.row(InlineKeyboardButton(text="📜 Показать логи", callback_data=f"choose_log_type:{ub_username}"))
    return builder.as_markup()

def get_cancel_note_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"cancel_add_note:{ub_username}")
    return builder.as_markup()

def get_back_to_ub_panel_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=f"back_to_ub_info:{ub_username}")
    return builder.as_markup()

def get_log_type_choice_keyboard(ub_username: str, owner_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🐳 Docker", callback_data=f"show_logs:docker:{ub_username}:{owner_id}:1")
    builder.button(text="📄 Log File", callback_data=f"show_logs:logfile:{ub_username}:{owner_id}:1")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад к управлению", callback_data=f"back_to_ub_info:{ub_username}:{owner_id}"))
    return builder.as_markup()

def get_logs_paginator_keyboard(log_type: str, ub_username: str, page: int, total_pages: int, owner_id: int):
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="«", callback_data=f"show_logs:{log_type}:{ub_username}:{owner_id}:1"))
        nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"show_logs:{log_type}:{ub_username}:{owner_id}:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"show_logs:{log_type}:{ub_username}:{owner_id}:{page+1}"))
        nav_buttons.append(InlineKeyboardButton(text="»", callback_data=f"show_logs:{log_type}:{ub_username}:{owner_id}:{total_pages}"))
    builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="🔙 Назад к выбору логов", callback_data=f"choose_log_type:{ub_username}:{owner_id}"))
    return builder.as_markup()

def get_user_logs_paginator_keyboard(log_type: str, ub_username: str, page: int, total_pages: int, owner_id: int):
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="« 1", callback_data=f"show_user_logs:{log_type}:{ub_username}:{owner_id}:1"))
        nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"show_user_logs:{log_type}:{ub_username}:{owner_id}:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"· {page}/{total_pages} ·", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"show_user_logs:{log_type}:{ub_username}:{owner_id}:{page+1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{total_pages} »", callback_data=f"show_user_logs:{log_type}:{ub_username}:{owner_id}:{total_pages}"))

    builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="🔙 Назад к панели", callback_data=f"refresh_panel:{ub_username}:{owner_id}"))
    return builder.as_markup()

def get_cancel_transfer_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"transfer_ub_cancel:{ub_username}")
    return builder.as_markup()

def get_confirm_transfer_keyboard(ub_username: str, new_owner_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=f"transfer_ub_execute:{ub_username}:{new_owner_id}")
    builder.button(text="❌ Нет", callback_data=f"transfer_ub_cancel:{ub_username}")
    builder.adjust(2)
    return builder.as_markup()
    
def get_confirm_reboot_keyboard(ip: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, перезагрузить", callback_data=f"host_reboot_confirm:{ip}")
    builder.button(text="❌ Отмена", callback_data="host_reboot_cancel")
    builder.adjust(2)
    return builder.as_markup()
    
def get_reinstall_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Начать переустановку", callback_data="reinstall_userbot_start")
    return builder.as_markup()
    
def get_user_info_keyboard(user_id: int, has_bots: bool):
    builder = InlineKeyboardBuilder()
    if has_bots:
        builder.button(text="🤖 Юзерботы", callback_data=f"show_user_bots:{user_id}")
    return builder.as_markup()

def get_user_bots_list_keyboard(userbots: list, user_id: int):
    builder = InlineKeyboardBuilder()
    for bot in userbots:
        owner_mark = " (ваш)" if bot['tg_user_id'] == user_id else " (доступ)"
        builder.button(text=f"🔹 {bot['ub_username']}{owner_mark}", callback_data=f"select_ub_panel:{bot['ub_username']}")
    builder.button(text="⬅️ Назад к информации", callback_data=f"back_to_user_info:{user_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_ub_management_keyboard(ub_username: str, user_id: int, is_active: bool):
    builder = InlineKeyboardBuilder()
    
    if is_active:
        # builder.button(text="🔴 Выключить", callback_data=f"admin_manage_ub:stop:{ub_username}")
        # builder.button(text="🔄 Перезагрузить", callback_data=f"admin_manage_ub:restart:{ub_username}")
        builder.button(text="🔴 Выключить", callback_data="admin_noop")
        builder.button(text="🔄 Перезагрузить", callback_data="admin_noop")
    else:
        # builder.button(text="🚀 Включить", callback_data=f"admin_manage_ub:start:{ub_username}")
        builder.button(text="🚀 Включить", callback_data="admin_noop")
    
    builder.button(text="📜 Логи", callback_data=f"admin_show_logs:docker:{ub_username}:1")
    builder.button(text="🤝 Передать", callback_data=f"admin_transfer_start:{ub_username}")
    builder.button(text="🗑️ Удалить", callback_data=f"admin_delete_ub:{ub_username}")
    
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к списку юзерботов", callback_data=f"show_user_bots:{user_id}"))
    
    return builder.as_markup()
    
def get_admin_loading_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🕕 Загрузка...", callback_data="admin_noop")
    return builder.as_markup()
    
def get_admin_logs_paginator_keyboard(log_type: str, ub_username: str, user_id: int, page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(text="« 1", callback_data=f"admin_show_logs:{log_type}:{ub_username}:1"))
        nav_buttons.append(InlineKeyboardButton(text="‹", callback_data=f"admin_show_logs:{log_type}:{ub_username}:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"· {page}/{total_pages} ·", callback_data="noop"))
    
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="›", callback_data=f"admin_show_logs:{log_type}:{ub_username}:{page+1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{total_pages} »", callback_data=f"admin_show_logs:{log_type}:{ub_username}:{total_pages}"))

    builder.row(*nav_buttons)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к управлению", callback_data=f"select_user_bot:{ub_username}:{user_id}"))
    return builder.as_markup()

def get_admin_cancel_transfer_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"admin_transfer_cancel:{ub_username}")
    return builder.as_markup()

def get_admin_confirm_transfer_keyboard(ub_username: str, new_owner_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, передать", callback_data=f"admin_transfer_execute:{ub_username}:{new_owner_id}")
    builder.button(text="❌ Отмена", callback_data=f"admin_transfer_cancel:{ub_username}")
    builder.adjust(2)
    return builder.as_markup()
    
def get_commits_list_keyboard(commits: list):
    builder = InlineKeyboardBuilder()

    try:
        import locale
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except locale.Error:
        pass 

    for commit in commits:
        try:
            commit_date = datetime.datetime.strptime(commit['created_at'], '%Y-%m-%d %H:%M:%S')
            date_str = commit_date.strftime('%d %B').lower()
        except (ValueError, TypeError):
            date_str = "???"

        button_text = f"#{commit['commit_id']} ({date_str})"
        builder.button(text=button_text, callback_data=f"view_commit:{commit['commit_id']}")
    
    builder.adjust(2)
    
    builder.row(InlineKeyboardButton(text="Скрыть", callback_data="hide_commits"))
    return builder.as_markup()

def get_commit_details_keyboard(commit_id: str, likes: int, dislikes: int, is_admin: bool):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data=f"vote_commit:{commit_id}:1")
    builder.button(text=f"👎 {dislikes}", callback_data=f"vote_commit:{commit_id}:-1")

    if is_admin:
        builder.button(text="✍️ Редактировать", callback_data=f"edit_commit_start:{commit_id}")
        builder.button(text="🗑️ Удалить", callback_data=f"delete_commit_start:{commit_id}")
    
    builder.row(InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_commits"))
    
    builder.adjust(2, 2, 1)

    return builder.as_markup() 
   
def get_commit_delete_confirm_keyboard(commit_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delete_commit_confirm:{commit_id}")
    builder.button(text="❌ Нет", callback_data=f"delete_commit_cancel:{commit_id}")
    builder.adjust(2)
    return builder.as_markup()
    
def get_delub_reason_keyboard(ub_username: str, reasons: dict):
    builder = InlineKeyboardBuilder()
    for reason_code, reason_text in reasons.items():
        builder.button(text=reason_text.split('\n')[0], callback_data=f"delub_confirm:{ub_username}:{reason_code}")
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="delub_close_menu"))
    return builder.as_markup()

def get_delub_final_confirm_keyboard(ub_username: str, reason_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"delub_execute:{ub_username}:{reason_code}")
    builder.button(text="❌ Нет, назад", callback_data=f"delub_cancel:{ub_username}")
    builder.adjust(2)
    return builder.as_markup()

def get_confirm_revoke_shared_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отказаться", callback_data=f"confirm_revoke_shared:{ub_username}")
    builder.button(text="❌ Нет", callback_data=f"cancel_revoke_shared:{ub_username}")
    builder.adjust(2)
    return builder.as_markup()

def get_confirm_share_panel_keyboard(ub_username: str, share_user_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, поделиться", callback_data=f"confirm_share_panel:{ub_username}:{share_user_id}")
    builder.button(text="❌ Нет", callback_data=f"cancel_revoke_shared:{ub_username}")
    builder.adjust(2)
    return builder.as_markup()

def get_accept_share_panel_keyboard(ub_username: str, owner_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"accept_share_panel:{ub_username}:{owner_id}")
    builder.button(text="❌ Отклонить", callback_data=f"decline_share_panel:{ub_username}:{owner_id}")
    builder.adjust(2)
    return builder.as_markup()
    
def userbot_panel():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_main_panel")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_revoke_shared_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"refresh_panel:{ub_username}")
    return builder.as_markup()

def get_active_status_refresh_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data="refresh_active_status")
    return builder.as_markup()

def get_retry_login_link_keyboard(ub_username: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Попробовать снова", callback_data=f"retry_login_link:{ub_username}")
    builder.button(text="⬅️ Назад", callback_data="back_to_main_panel")
    return builder.as_markup()

def get_stats_keyboard(current_view: str = "overall"):
    builder = InlineKeyboardBuilder()
    
    views = {
        "overall": "📊 Общая",
        "servers": "🖥️ Серверы",
        "userbots": "🤖 Юзерботы"
    }
    
    buttons = []
    for view, text in views.items():
        button_text = f"✅ {text}" if current_view == view else text
        buttons.append(
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"stats_view:{view}"
            )
        )

    builder.row(*buttons)
    builder.row(InlineKeyboardButton(text="🔄 Обновить", callback_data=f"stats_refresh:{current_view}"))
    return builder.as_markup()
    
def get_container_list_keyboard(page_containers: list, page: int, total_pages: int, expanded_container_name: str | None = None):
    """Создает клавиатуру для пагинации и управления статистикой контейнеров."""
    builder = InlineKeyboardBuilder()
    
    stat_buttons = []
    for container in page_containers:
        name = container['name']
        if name == expanded_container_name:
            stat_buttons.append(InlineKeyboardButton(text=f"🔼 Скрыть {name}", callback_data=f"container_stats:hide:{name}:{page}"))
        else:
            stat_buttons.append(InlineKeyboardButton(text=f"📊 Показать {name}", callback_data=f"container_stats:show:{name}:{page}"))
    
    if stat_buttons:
        builder.row(*stat_buttons, width=2)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"container_page:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"• {page+1}/{total_pages} •", callback_data="noop"))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"container_page:{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
        
    builder.row(InlineKeyboardButton(text="🔄 Обновить всё", callback_data="container_page:refresh"))
        
    return builder.as_markup()

def get_server_info_paginator_keyboard(page: int, total_pages: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 1:
        nav_buttons.append({
            'text': '◀️',
            'callback_data': f'serverinfo_page:{page-1}'
        })
    nav_buttons.append({
        'text': f'{page}/{total_pages}',
        'callback_data': 'noop'
    })
    if page < total_pages:
        nav_buttons.append({
            'text': '▶️',
            'callback_data': f'serverinfo_page:{page+1}'
        })
    for btn in nav_buttons:
        builder.button(text=btn['text'], callback_data=btn['callback_data'])
    builder.button(text='🔄 Обновить', callback_data='refresh_server_info')
    return builder.as_markup()
# --- END OF FILE keyboards.py ---