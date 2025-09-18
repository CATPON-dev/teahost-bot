# --- START OF FILE config_manager.py ---
import json
import os

CONFIG_FILE = "config.json"

class _Config:
    def __init__(self):
        self._load()

    def _load(self):
        if not os.path.exists(CONFIG_FILE):
            raise FileNotFoundError(f"{CONFIG_FILE} не найден.")
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        self.BOT_TOKEN = self._get_required("bot_token")
        
        self.CUSTOM_BOT_API_SERVER = self._config.get("custom_bot_api_server")
        
        self.TEST_MODE = self._config.get("test_mode", False)
        
        self.CHANNEL_ID = "@TeaHostChannel"
        
        # В тестовом режиме не используем рабочие каналы
        if self.TEST_MODE:
            self.STATUS_CHANNEL_ID = None
            self.SUPPORT_CHAT_ID = None
            self.SUPPORT_TOPIC_ID = None
            self.LOG_CHANNEL_ID = None
            self.REVIEW_CHANNEL_ID = None
            self.STATS_CHAT_ID = None
            self.STATS_TOPIC_ID = None
        else:
            self.STATUS_CHANNEL_ID = -1002536796447
            self.LOG_CHAT_ID = self._config.get("log_chat_id")
            self.SUPPORT_CHAT_ID = "@TeaHostSupport" 
            self.SUPPORT_TOPIC_ID = 22 
            self.LOG_CHANNEL_ID = self._config.get("log_channel_id")
            self.REVIEW_CHANNEL_ID = self._config.get("review_channel_id")
            self.STATS_CHAT_ID = self._config.get("stats_chat_id")
            self.STATS_TOPIC_ID = self._config.get("stats_topic_id")
        
        admin_ids = self._config.get("admin_user_id")
        if admin_ids is None:
            self.SUPER_ADMIN_IDS = []
        elif isinstance(admin_ids, int):
            self.SUPER_ADMIN_IDS = [admin_ids]
        elif isinstance(admin_ids, list):
            self.SUPER_ADMIN_IDS = [int(i) for i in admin_ids if isinstance(i, int)]
        else:
            self.SUPER_ADMIN_IDS = []

        self.DB_CONFIG = self._get_required("database")

    def _get_required(self, key):
        value = self._config.get(key)
        if value is None: raise ValueError(f"Отсутствует ключ '{key}' в {CONFIG_FILE}")
        return value

    def reload(self):
        self._load()

config = _Config()
        
def _read_raw_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _write_raw_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def add_super_admin(user_id: int) -> bool:
    if user_id in config.SUPER_ADMIN_IDS:
        return False
    raw_config = _read_raw_config()
    if "admin_user_id" not in raw_config or not isinstance(raw_config["admin_user_id"], list):
        raw_config["admin_user_id"] = []
    raw_config["admin_user_id"].append(user_id)
    _write_raw_config(raw_config)
    config.reload()
    return True

def remove_super_admin(user_id: int) -> bool:
    if user_id not in config.SUPER_ADMIN_IDS:
        return False
    raw_config = _read_raw_config()
    if "admin_user_id" in raw_config and isinstance(raw_config["admin_user_id"], list):
        try:
            raw_config["admin_user_id"].remove(user_id)
            _write_raw_config(raw_config)
            config.reload()
            return True
        except ValueError:
            return False
    return False
# --- END OF FILE config_manager.py ---