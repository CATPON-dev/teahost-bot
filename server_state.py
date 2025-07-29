import json
import os

STATUS_FILE = "server_status.json"

def is_server_enabled():
    if not os.path.exists(STATUS_FILE):
        return True
    try:
        with open(STATUS_FILE, 'r') as f:
            data = json.load(f)
            return data.get("enabled", True)
    except (json.JSONDecodeError, FileNotFoundError):
        return True

def set_server_status(enabled: bool):
    with open(STATUS_FILE, 'w') as f:
        json.dump({"enabled": enabled}, f)