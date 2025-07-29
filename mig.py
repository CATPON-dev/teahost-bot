import sqlite3
import pymysql
import logging
import json
import sys

# --- НАСТРОЙКИ ---
SQLITE_DB_FILE = "userbots.db"

try:
    with open("config.json", "r") as f:
        config = json.load(f)
    DB_CONFIG = config.get("database")
    if not DB_CONFIG:
        raise ValueError("Секция 'database' не найдена в config.json")
except (FileNotFoundError, ValueError) as e:
    logging.critical(f"Ошибка чтения конфигурации: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TABLES_CREATION_ORDER = [
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS userbots (
        id INT PRIMARY KEY AUTO_INCREMENT,
        tg_user_id BIGINT NOT NULL,
        ub_username VARCHAR(255) NOT NULL UNIQUE,
        server_ip VARCHAR(255) NOT NULL,
        ub_type TEXT,
        hikka_path TEXT,
        status VARCHAR(50) DEFAULT 'stopped',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        blocked BOOLEAN NOT NULL DEFAULT FALSE,
        warning_sent_at DATETIME,
        is_warned BOOLEAN NOT NULL DEFAULT FALSE,
        stopped_at DATETIME,
        started_at DATETIME,
        FOREIGN KEY (tg_user_id) REFERENCES users (tg_user_id) ON DELETE CASCADE,
        INDEX(tg_user_id)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS commit_votes (
        commit_id VARCHAR(255) NOT NULL,
        user_id BIGINT NOT NULL,
        vote_type INT NOT NULL,
        PRIMARY KEY (commit_id, user_id)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """,
    """
    CREATE TABLE IF NOT EXISTS userbot_shared (
        ub_username VARCHAR(255) NOT NULL,
        tg_user_id BIGINT NOT NULL,
        PRIMARY KEY (ub_username, tg_user_id),
        FOREIGN KEY (ub_username) REFERENCES userbots (ub_username) ON DELETE CASCADE,
        FOREIGN KEY (tg_user_id) REFERENCES users (tg_user_id) ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """
]

TABLES_MIGRATION_ORDER = [
    'users',
    'userbots',
    'commits',
    'commit_votes',
    'userbot_shared'
]

def get_mysql_columns(mysql_cursor, table_name):
    mysql_cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
    return {row['Field'] for row in mysql_cursor.fetchall()}

def migrate_table(sqlite_cursor, mysql_cursor, table_name):
    logging.info(f"Начинаю миграцию данных для таблицы: {table_name}...")

    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    if not rows:
        logging.info(f"Таблица {table_name} в SQLite пуста, пропускаю.")
        return

    sqlite_columns = {description[0] for description in sqlite_cursor.description}
    mysql_columns = get_mysql_columns(mysql_cursor, table_name)
    
    common_columns = list(sqlite_columns.intersection(mysql_columns))
    
    if not common_columns:
        logging.warning(f"Нет общих столбцов между SQLite и MySQL для таблицы {table_name}. Пропускаю.")
        return

    cols_str = ", ".join([f"`{col}`" for col in common_columns])
    placeholders = ", ".join(["%s"] * len(common_columns))
    sql_insert = f"INSERT INTO `{table_name}` ({cols_str}) VALUES ({placeholders})"
    
    sqlite_col_indices = {col: i for i, col in enumerate([d[0] for d in sqlite_cursor.description])}
    
    values_to_insert = []
    for row in rows:
        value_tuple = tuple(row[sqlite_col_indices[col]] for col in common_columns)
        values_to_insert.append(value_tuple)

    try:
        mysql_cursor.executemany(sql_insert, values_to_insert)
        logging.info(f"Успешно перенесено {mysql_cursor.rowcount} строк в таблицу {table_name}.")
    except Exception as e:
        logging.error(f"Ошибка при массовой вставке данных в таблицу {table_name}: {e}")
        raise

def main():
    sqlite_conn = None
    mysql_conn = None

    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB_FILE)
        mysql_conn = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['db_name'],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        sqlite_cursor = sqlite_conn.cursor()
        mysql_cursor = mysql_conn.cursor()
        
        logging.info("Подключение к базам данных установлено.")
        
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Оборачиваем всю миграцию в управление FOREIGN_KEY_CHECKS ---
        mysql_cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        logging.info("Проверка внешних ключей в MySQL временно отключена.")

        logging.info("Очистка старой структуры в MySQL...")
        for table in TABLES_MIGRATION_ORDER[::-1]: # Удаляем в обратном порядке
            mysql_cursor.execute(f"DROP TABLE IF EXISTS `{table}`;")
        logging.info("Очистка завершена.")

        logging.info("Создание новой структуры таблиц в MySQL...")
        for query in TABLES_CREATION_ORDER:
            mysql_cursor.execute(query)
        logging.info("Структура таблиц успешно создана.")

        for table in TABLES_MIGRATION_ORDER: # Мигрируем в правильном порядке
            migrate_table(sqlite_cursor, mysql_cursor, table)
        
        mysql_conn.commit()
        logging.info("✅ Миграция всех данных успешно завершена!")

    except FileNotFoundError:
        logging.critical(f"Критическая ошибка: файл базы данных SQLite '{SQLITE_DB_FILE}' не найден.")
    except Exception as e:
        logging.critical(f"Критическая ошибка во время миграции: {e}", exc_info=True)
        if mysql_conn:
            logging.warning("Откатываю изменения в MySQL...")
            mysql_conn.rollback()
    finally:
        if mysql_conn:
            # --- ИЗМЕНЕНИЕ ЗДЕСЬ: Всегда включаем проверку ключей обратно ---
            mysql_cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            logging.info("Проверка внешних ключей в MySQL снова включена.")
            mysql_conn.close()
        if sqlite_conn:
            sqlite_conn.close()
        logging.info("Соединения с базами данных закрыты.")

if __name__ == "__main__":
    main()