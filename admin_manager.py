# admin_manager.py

import json
import os
from config_manager import config

ADMINS_FILE = "admins.json"


def get_admin_ids():
    if not os.path.exists(ADMINS_FILE):
        return []
    try:
        with open(ADMINS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_admin_ids(admin_ids: list):
    with open(ADMINS_FILE, 'w') as f:
        json.dump(admin_ids, f, indent=4)


def get_all_admins():
    super_admins = config.SUPER_ADMIN_IDS
    regular_admins = get_admin_ids()
    return list(set(super_admins + regular_admins))


def add_admin(user_id: int):
    admins = get_admin_ids()
    if user_id not in admins:
        admins.append(user_id)
        save_admin_ids(admins)
        return True
    return False


def remove_admin(user_id: int):
    admins = get_admin_ids()
    if user_id in admins:
        admins.remove(user_id)
        save_admin_ids(admins)
        return True
    return False
