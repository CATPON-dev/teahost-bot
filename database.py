# --- START OF FILE database.py ---
import aiomysql
import logging
import random
from typing import Dict, Any, List, Optional
import datetime
from config_manager import config

logger = logging.getLogger(__name__)

pool = None

async def init_pool():
    global pool
    if pool:
        return
    try:
        pool = await aiomysql.create_pool(
            host=config.DB_CONFIG['host'],
            port=config.DB_CONFIG['port'],
            user=config.DB_CONFIG['user'],
            password=config.DB_CONFIG['password'],
            db=config.DB_CONFIG['db_name'],
            autocommit=True,
            charset='utf8mb4'
        )
        logger.info("Пул соединений с MySQL успешно создан.")
    except Exception as e:
        logger.critical(f"Не удалось создать пул соединений с MySQL: {e}", exc_info=True)
        raise

async def _add_column_if_not_exists(cursor, table_name, column_name, column_definition):
    await cursor.execute(f"""
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = '{table_name}'
        AND COLUMN_NAME = '{column_name}'
    """)
    if (await cursor.fetchone())[0] == 0:
        await cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_definition}")
        logger.info(f"Добавлен столбец '{column_name}' в таблицу '{table_name}'.")

async def init_db():
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Подавляем предупреждения о существующих таблицах
                await cursor.execute("SET sql_notes = 0")
                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS vpn (
                    tg_user_id BIGINT PRIMARY KEY,
                    link TEXT
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)
                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS auth (
                    tg_user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    password TEXT
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)
                
                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    agreement_accepted BOOLEAN NOT NULL DEFAULT FALSE,
                    is_banned BOOLEAN NOT NULL DEFAULT FALSE,
                    note TEXT,
                    api_token TEXT,
                    ub_limit INT DEFAULT 1,
                    INDEX(api_token(255))
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)
                
                await _add_column_if_not_exists(cursor, 'users', 'token_regen_count', 'INT DEFAULT 0')
                await _add_column_if_not_exists(cursor, 'users', 'token_regen_timestamp', 'DATETIME')

                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS userbots (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    tg_user_id BIGINT NOT NULL,
                    ub_username VARCHAR(255) NOT NULL UNIQUE,
                    server_ip VARCHAR(255) NOT NULL,
                    ub_type TEXT,
                    status VARCHAR(50) DEFAULT 'stopped',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    blocked BOOLEAN NOT NULL DEFAULT FALSE,
                    warning_sent_at DATETIME,
                    is_warned BOOLEAN NOT NULL DEFAULT FALSE,
                    stopped_at DATETIME,
                    started_at DATETIME,
                    webui_port INT DEFAULT NULL,
                    FOREIGN KEY (tg_user_id) REFERENCES users (tg_user_id) ON DELETE CASCADE,
                    INDEX(tg_user_id),
                    INDEX(webui_port)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)

                # Добавляем столбцы, если их нет
                await _add_column_if_not_exists(cursor, 'userbots', 'webui_port', 'INT DEFAULT NULL')
                await _add_column_if_not_exists(cursor, 'userbots', 'is_test_mode', 'BOOLEAN NOT NULL DEFAULT FALSE')
                
                # Удаляем старый столбец hikka_path, если он существует
                try:
                    await cursor.execute("ALTER TABLE userbots DROP COLUMN hikka_path")
                    logger.info("Столбец hikka_path удален из таблицы userbots")
                except:
                    pass  # Столбец уже не существует

                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS commits (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    commit_id VARCHAR(255) NOT NULL UNIQUE,
                    admin_id BIGINT NOT NULL,
                    admin_name TEXT NOT NULL,
                    admin_username TEXT,
                    commit_text TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX(created_at)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)

                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS commit_votes (
                    commit_id VARCHAR(255) NOT NULL,
                    user_id BIGINT NOT NULL,
                    vote_type INT NOT NULL,
                    PRIMARY KEY (commit_id, user_id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)

                await cursor.execute("""
                CREATE TABLE IF NOT EXISTS userbot_shared (
                    ub_username VARCHAR(255) NOT NULL,
                    tg_user_id BIGINT NOT NULL,
                    PRIMARY KEY (ub_username, tg_user_id),
                    FOREIGN KEY (ub_username) REFERENCES userbots (ub_username) ON DELETE CASCADE,
                    FOREIGN KEY (tg_user_id) REFERENCES users (tg_user_id) ON DELETE CASCADE
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                """)

        logger.info("Инициализация и проверка схемы базы данных MySQL завершены.")
    except aiomysql.Error as e:
        logger.error(f"Ошибка инициализации БД MySQL: {e}", exc_info=True)
        raise
    finally:
        # Восстанавливаем настройки SQL
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SET sql_notes = 1")
        except:
            pass

async def update_token_regen_info(user_id: int, count: int, timestamp: Optional[datetime.datetime]):
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "UPDATE users SET token_regen_count = %s, token_regen_timestamp = %s WHERE tg_user_id = %s",
                    (count, timestamp, user_id)
                )
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления информации о регенерации токена для {user_id}: {e}")

async def set_api_token(user_id: int, token: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET api_token = %s WHERE tg_user_id = %s", (token, user_id))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка установки API токена для {user_id}: {e}")
        return False

async def get_user_by_api_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM users WHERE api_token = %s", (token,))
                return await cursor.fetchone()
    except aiomysql.Error as e:
        logger.error(f"Ошибка поиска пользователя по API токену: {e}", exc_info=True)
        return None

async def set_user_note(user_id: int, note: Optional[str]) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET note = %s WHERE tg_user_id = %s", (note, user_id))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка установки заметки для {user_id}: {e}")
        return False

async def set_user_ban_status(user_id: int, is_banned: bool) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET is_banned = %s WHERE tg_user_id = %s", (is_banned, user_id))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка установки статуса бана для {user_id}: {e}")
        return False

async def is_user_banned(user_id: int) -> bool:
    user_data = await get_user_data(user_id)
    return bool(user_data and user_data.get("is_banned"))

async def get_user_by_username_or_id(identifier: str) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                clean_identifier = identifier.lstrip('@')
                if clean_identifier.isdigit():
                    await cursor.execute("SELECT * FROM users WHERE tg_user_id = %s", (int(clean_identifier),))
                else:
                    await cursor.execute("SELECT * FROM users WHERE username = %s", (clean_identifier,))
                return await cursor.fetchone()
    except (aiomysql.Error, ValueError) as e:
        logger.error(f"Ошибка поиска пользователя по '{identifier}': {e}", exc_info=True)
        return None

async def register_or_update_user(tg_user_id: int, username: Optional[str], full_name: Optional[str]) -> bool:
    sql_insert = """
        INSERT INTO users (tg_user_id, username, full_name, registered_at, agreement_accepted)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, FALSE) AS new_values
        ON DUPLICATE KEY UPDATE 
            username = new_values.username, 
            full_name = new_values.full_name;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql_insert, (tg_user_id, username, full_name))
        return True
    except aiomysql.Error as e:
        logger.error(f"Ошибка БД при работе с пользователем {tg_user_id}: {e}", exc_info=True)
        return False

async def set_user_agreement_accepted(tg_user_id: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET agreement_accepted = TRUE WHERE tg_user_id = %s", (tg_user_id,))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка при установке согласия для {tg_user_id}: {e}")
        return False

async def has_user_accepted_agreement(tg_user_id: int) -> bool:
    user_data = await get_user_data(tg_user_id)
    return bool(user_data and user_data.get("agreement_accepted"))

async def get_user_data(tg_user_id: int) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM users WHERE tg_user_id = %s", (tg_user_id,))
                return await cursor.fetchone()
    except aiomysql.Error as e:
        logger.error(f"SQL ошибка в get_user_data: {e}", exc_info=True)
        return None

async def generate_random_port() -> int:
    """Генерирует случайный порт, избегая важных системных портов и красивых чисел"""
    # Избегаем важные порты: 1-1023, 3306, 5432, 6379, 8080, 9000, 9090
    # Избегаем красивые числа: 1000, 2000, 3000, 10000, 20000, 30000
    # Избегаем порты с повторяющимися цифрами: 1111, 2222, 3333, 4444, 5555, 6666, 7777, 8888, 9999
    forbidden_ranges = [
        (1, 1023),      # Системные порты
        (3306, 3306),   # MySQL
        (5432, 5432),   # PostgreSQL
        (6379, 6379),   # Redis
        (8080, 8080),   # HTTP альтернативный
        (9000, 9000),   # Jenkins
        (9090, 9090),   # Prometheus
        (1000, 1000),   # Красивые числа
        (2000, 2000),
        (3000, 3000),
        (10000, 10000),
        (20000, 20000),
        (30000, 30000),
        (1111, 1111),   # Повторяющиеся цифры
        (2222, 2222),
        (3333, 3333),
        (4444, 4444),
        (5555, 5555),
        (6666, 6666),
        (7777, 7777),
        (8888, 8888),
        (9999, 9999),
    ]
    
    # Получаем все занятые порты
    occupied_ports = await get_all_occupied_ports()
    
    max_attempts = 100
    for _ in range(max_attempts):
        # Генерируем порт в диапазоне 5000-65000
        port = random.randint(5000, 65000)
        
        # Проверяем, что порт не в запрещенных диапазонах
        is_forbidden = any(start <= port <= end for start, end in forbidden_ranges)
        if is_forbidden:
            continue
            
        # Проверяем, что порт не занят
        if port not in occupied_ports:
            return port
    
    # Если не удалось найти свободный порт, возвращаем None
    return None

async def get_all_occupied_ports() -> List[int]:
    """Получает список всех занятых портов из базы данных"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT webui_port FROM userbots WHERE webui_port IS NOT NULL")
                result = await cursor.fetchall()
                return [row[0] for row in result]
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения занятых портов: {e}", exc_info=True)
        return []

async def add_userbot_record(tg_user_id: int, ub_username: str, ub_type: str, server_ip: str, webui_port: int) -> bool:
    sql = """
        INSERT INTO userbots (tg_user_id, ub_username, ub_type, server_ip, status, blocked, webui_port)
        VALUES (%s, %s, %s, %s, 'installing', FALSE, %s)
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, (tg_user_id, ub_username, ub_type, server_ip, webui_port))
                return True
    except aiomysql.IntegrityError:
        logger.warning(f"Попытка добавить существующего UB: {ub_username}", exc_info=True)
        return False
    except aiomysql.Error as e:
        logger.error(f"Ошибка добавления UB {ub_username}: {e}", exc_info=True)
        return False

async def update_userbot_status(ub_username: str, status: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE userbots SET status = %s WHERE ub_username = %s", (status, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления статуса UB {ub_username}: {e}", exc_info=True)
        return False

async def block_userbot(ub_username: str, blocked_status: bool) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE userbots SET blocked = %s WHERE ub_username = %s", (blocked_status, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка блокировки {ub_username}: {e}")
        return False

async def get_userbot_data(ub_username: str) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots WHERE ub_username = %s", (ub_username,))
                return await cursor.fetchone()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения данных UB: {e}", exc_info=True)
        return None

async def get_userbots_by_tg_id(tg_user_id: int) -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots WHERE tg_user_id = %s", (tg_user_id,))
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения списка UB для {tg_user_id}: {e}", exc_info=True)
        return []

async def get_userbot_by_tg_id_and_username(tg_user_id: int, ub_username: str) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots WHERE tg_user_id = %s AND ub_username = %s", (tg_user_id, ub_username))
                return await cursor.fetchone()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения UB {ub_username} для пользователя {tg_user_id}: {e}", exc_info=True)
        return None

async def get_userbots_by_server_ip(server_ip: str) -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots WHERE server_ip = %s", (server_ip,))
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения списка UB для сервера {server_ip}: {e}", exc_info=True)
        return []

async def get_all_userbots_full_info() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения полной информации о юзерботах: {e}", exc_info=True)
        return []

async def delete_userbot_record(ub_username: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM userbots WHERE ub_username = %s", (ub_username,))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка удаления UB {ub_username}: {e}", exc_info=True)
        return False

async def get_all_bot_users() -> List[int]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT tg_user_id FROM users")
                rows = await cursor.fetchall()
                return [row['tg_user_id'] for row in rows]
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения всех пользователей: {e}", exc_info=True)
        return []

async def get_all_users_with_reg_date() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT tg_user_id, registered_at FROM users")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения всех пользователей с датой регистрации: {e}", exc_info=True)
        return []

async def get_userbot_owners_count() -> int:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT COUNT(DISTINCT tg_user_id) FROM userbots")
                result = await cursor.fetchone()
                return result[0] if result else 0
    except aiomysql.Error:
        return 0

async def get_all_registered_users() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM users WHERE agreement_accepted = TRUE")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения зарегистрированных пользователей: {e}", exc_info=True)
        return []

async def get_all_unregistered_users() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM users WHERE agreement_accepted = FALSE OR agreement_accepted IS NULL")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения незарегистрированных пользователей: {e}", exc_info=True)
        return []

async def transfer_userbot(ub_username: str, new_owner_id: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE userbots SET tg_user_id = %s WHERE ub_username = %s", (new_owner_id, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка переноса юзербота {ub_username} новому владельцу {new_owner_id}: {e}", exc_info=True)
        return False
        
async def add_commit(commit_id: str, admin_id: int, admin_name: str, admin_username: Optional[str], commit_text: str) -> bool:
    sql = "INSERT INTO commits (commit_id, admin_id, admin_name, admin_username, commit_text) VALUES (%s, %s, %s, %s, %s)"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, (commit_id, admin_id, admin_name, admin_username, commit_text))
                return True
    except aiomysql.Error as e:
        logger.error(f"Ошибка добавления коммита {commit_id}: {e}", exc_info=True)
        return False

async def get_all_commits() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM commits ORDER BY created_at DESC")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения всех коммитов: {e}", exc_info=True)
        return []

async def get_commit_by_id(commit_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM commits WHERE commit_id = %s", (commit_id,))
                return await cursor.fetchone()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения коммита {commit_id}: {e}", exc_info=True)
        return None
       
async def set_vote(commit_id: str, user_id: int, vote_type: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT vote_type FROM commit_votes WHERE commit_id = %s AND user_id = %s", (commit_id, user_id))
                current_vote = await cursor.fetchone()

                if current_vote and current_vote['vote_type'] == vote_type:
                    await cursor.execute("DELETE FROM commit_votes WHERE commit_id = %s AND user_id = %s", (commit_id, user_id))
                else:
                    sql_upsert = """
                        INSERT INTO commit_votes (commit_id, user_id, vote_type) VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE vote_type = VALUES(vote_type);
                    """
                    await cursor.execute(sql_upsert, (commit_id, user_id, vote_type))
                return True
    except aiomysql.Error as e:
        logger.error(f"Ошибка установки голоса для коммита {commit_id} от {user_id}: {e}")
        return False

async def get_vote_counts(commit_id: str) -> Dict[str, int]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = """
                    SELECT 
                        SUM(CASE WHEN vote_type = 1 THEN 1 ELSE 0 END) as likes,
                        SUM(CASE WHEN vote_type = -1 THEN 1 ELSE 0 END) as dislikes
                    FROM commit_votes 
                    WHERE commit_id = %s
                """
                await cursor.execute(sql, (commit_id,))
                counts = await cursor.fetchone()
                return {'likes': counts['likes'] or 0, 'dislikes': counts['dislikes'] or 0}
    except aiomysql.Error:
        return {'likes': 0, 'dislikes': 0}
        
async def update_commit_text(commit_id: str, new_text: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE commits SET commit_text = %s WHERE commit_id = %s", (new_text, commit_id))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления текста коммита {commit_id}: {e}")
        return False
        
async def delete_commit_by_id(commit_id: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM commits WHERE commit_id = %s", (commit_id,))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка удаления коммита {commit_id}: {e}")
        return False

async def set_userbot_warning_status(ub_username: str, is_warned: bool, warning_time: Optional[datetime.datetime] = None):
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "UPDATE userbots SET is_warned = %s, warning_sent_at = %s WHERE ub_username = %s",
                    (is_warned, warning_time, ub_username)
                )
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка установки статуса предупреждения для {ub_username}: {e}")
        return False

async def get_warned_userbots() -> List[Dict[str, Any]]:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM userbots WHERE is_warned = TRUE")
                return await cursor.fetchall()
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения списка юзерботов с предупреждением: {e}")
        return []
        
async def regenerate_user_token(user_id: int, new_token: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET api_token = %s WHERE tg_user_id = %s", (new_token, user_id))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка регенерации токена для пользователя {user_id}: {e}")
        return False

async def add_userbot_shared_access(ub_username: str, tg_user_id: int) -> bool:
    sql = "INSERT IGNORE INTO userbot_shared (ub_username, tg_user_id) VALUES (%s, %s)"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, (ub_username, tg_user_id))
                return True
    except aiomysql.Error as e:
        logger.error(f"Ошибка добавления доступа к {ub_username} для {tg_user_id}: {e}")
        return False

async def remove_userbot_shared_access(ub_username: str, tg_user_id: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM userbot_shared WHERE ub_username = %s AND tg_user_id = %s", (ub_username, tg_user_id))
                return True
    except aiomysql.Error as e:
        logger.error(f"Ошибка удаления доступа к {ub_username} для {tg_user_id}: {e}")
        return False

async def has_userbot_shared_access(ub_username: str, tg_user_id: int) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1 FROM userbot_shared WHERE ub_username = %s AND tg_user_id = %s", (ub_username, tg_user_id))
                return await cursor.fetchone() is not None
    except aiomysql.Error as e:
        logger.error(f"Ошибка проверки доступа к {ub_username} для {tg_user_id}: {e}")
        return False

async def get_userbot_shared_users(ub_username: str) -> list:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT tg_user_id FROM userbot_shared WHERE ub_username = %s", (ub_username,))
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения shared пользователей для {ub_username}: {e}")
        return []

async def user_can_manage_ub(user_id: int, ub_username: str) -> bool:
    ub_data = await get_userbot_data(ub_username)
    if not ub_data:
        return False
    if ub_data.get('tg_user_id') == user_id:
        return True
    return await has_userbot_shared_access(ub_username, user_id)

async def update_userbot_status_with_time(ub_username: str, status: str, stopped_time: Optional[datetime.datetime] = None) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                now = stopped_time or datetime.datetime.now()
                if status == 'stopped':
                    await cursor.execute("UPDATE userbots SET status = %s, stopped_at = %s WHERE ub_username = %s", (status, now, ub_username))
                else:
                    await cursor.execute("UPDATE userbots SET status = %s, stopped_at = NULL WHERE ub_username = %s", (status, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления статуса UB {ub_username} (с временем): {e}", exc_info=True)
        return False

async def update_userbot_started_time(ub_username: str, started_time: Optional[datetime.datetime] = None) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                now = started_time or datetime.datetime.now()
                await cursor.execute("UPDATE userbots SET started_at = %s WHERE ub_username = %s", (now, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления started_at для UB {ub_username}: {e}", exc_info=True)
        return False

async def update_userbot_server(ub_username: str, new_server_ip: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE userbots SET server_ip = %s WHERE ub_username = %s", (new_server_ip, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления сервера для UB {ub_username}: {e}", exc_info=True)
        return False
        
async def update_type(ub_username: str, userbot: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE userbots SET ub_type = %s WHERE ub_username = %s", (userbot, ub_username))
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка обновления сервера для UB {ub_username}: {e}", exc_info=True)
        return False
        
async def add_password(tg_id: int, username: str, password: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO auth (tg_user_id, username, password) VALUES (%s, %s, %s)",
                    (tg_id, username, password)
                )
                await conn.commit()
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка добавления пароля для пользователя {username}: {e}", exc_info=True)
        return False

async def get_password(tg_id: int) -> dict:
    """
    Получает данные аутентификации для пользователя
    Возвращает словарь с ключами 'username' и 'password' или пустой словарь
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT username, password FROM auth WHERE tg_user_id = %s",
                    (tg_id,)
                )
                result = await cursor.fetchone()
                return result if result else {}
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения данных аутентификации для пользователя {tg_id}: {e}", exc_info=True)
        return {}

async def delete_password(tg_id: int) -> bool:
    """Удаляет запись с паролем по ID пользователя"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM auth WHERE tg_user_id = %s",
                    (tg_id,)
                )
                await conn.commit()
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка удаления пароля для пользователя {tg_id}: {e}", exc_info=True)
        return False
        
async def add_vpn(tg_id: int, link: str) -> bool:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO vpn (tg_user_id, link) VALUES (%s, %s)",
                    (tg_id, link)
                )
                await conn.commit()
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка добавления VPN для пользователя {tg_id}: {e}", exc_info=True)
        return False

async def get_vpn(tg_id: int) -> str:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT link FROM vpn WHERE tg_user_id = %s",
                    (tg_id,)
                )
                result = await cursor.fetchone()
                return result[0] if result else None
    except aiomysql.Error as e:
        logger.error(f"Ошибка получения VPN для пользователя {tg_id}: {e}", exc_info=True)
        return None

async def delete_vpn(tg_id: int) -> bool:
    """Удаляет запись с VPN по ID пользователя"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM vpn WHERE tg_user_id = %s",
                    (tg_id,)
                )
                await conn.commit()
                return cursor.rowcount > 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка удаления VPN для пользователя {tg_id}: {e}", exc_info=True)
        return False

async def get_user_counts_by_period(days: int) -> int:
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "SELECT COUNT(tg_user_id) FROM users WHERE registered_at >= NOW() - INTERVAL %s DAY"
                await cursor.execute(query, (days,))
                result = await cursor.fetchone()
                return result[0] if result else 0
    except aiomysql.Error as e:
        logger.error(f"Ошибка подсчета пользователей за период {days} дней: {e}")
        return 0
# --- END OF FILE database.py ---