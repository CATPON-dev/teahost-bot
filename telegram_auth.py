import hashlib
import hmac
import json
from urllib.parse import parse_qs
from typing import Optional

def verify_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    try:
        parsed_data = parse_qs(init_data)
        user = json.loads(parsed_data.get("user", ["{}"])[0])
        hash_value = parsed_data.get("hash", [""])[0]

        data_check_string = "\n".join(f"{k}={v[0]}" for k, v in sorted(parsed_data.items()) if k != "hash")
        
        secret_key = hmac.new("WebAppData".encode(), bot_token.encode(), hashlib.sha256).digest()
        
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash == hash_value:
            return user
            
        simple_secret_key = hashlib.sha256(bot_token.encode()).digest()
        simple_calculated_hash = hmac.new(simple_secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if simple_calculated_hash == hash_value:
            return user

        return None
    except Exception as e:
        print(f"Ошибка верификации initData: {e}")
        return None