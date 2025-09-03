import json
import os
import logging

STATE_FILE = "outage_status_backup.json"
logger = logging.getLogger(__name__)

def _read_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _write_state(data):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Не удалось записать состояние недоступности: {e}")

def save_previous_status(ip: str, status: str):
    state = _read_state()
    state[ip] = status
    _write_state(state)
    logger.info(f"Сохранен предыдущий статус '{status}' для недоступного сервера {ip}.")

def restore_previous_status(ip: str) -> str:
    state = _read_state()
    previous_status = state.pop(ip, 'true')
    _write_state(state)
    logger.info(f"Восстановлен статус '{previous_status}' для сервера {ip}.")
    return previous_status