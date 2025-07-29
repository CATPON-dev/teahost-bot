# --- START OF FILE middlewares/techwork.py ---
import os
import json
import logging

STATUS_FILE = "maintenance_status.json"
logger = logging.getLogger(__name__)

def is_maintenance_mode() -> bool:
    """Проверяет, включен ли режим технических работ."""
    if not os.path.exists(STATUS_FILE):
        return False
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("maintenance_on", False)
    except (json.JSONDecodeError, FileNotFoundError):
        return False

def set_maintenance_mode(is_on: bool) -> bool:
    """Включает или выключает режим технических работ."""
    try:
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"maintenance_on": is_on}, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Failed to set maintenance mode to {is_on}: {e}")
        return False
# --- END OF FILE middlewares/techwork.py ---