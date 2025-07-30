#!/bin/bash

set -e

SOURCE_DIR_PATH="/root/nh"
BACKUP_DIR="/tmp"

if [ ! -d "$SOURCE_DIR_PATH" ]; then
  echo "Ошибка: Директория для бэкапа '$SOURCE_DIR_PATH' не найдена." >&2
  exit 1
fi

# Проверяем и устанавливаем необходимые зависимости
echo "Проверка зависимостей..." >&2
if ! command -v mysqldump &> /dev/null; then
    echo "Установка MySQL клиента..." >&2
    apt-get update -qq && apt-get install -y default-mysql-client
fi

if ! command -v zip &> /dev/null; then
    echo "Установка zip..." >&2
    apt-get update -qq && apt-get install -y zip
fi

# Читаем конфигурацию базы данных из config.json
if [ ! -f "$SOURCE_DIR_PATH/config.json" ]; then
  echo "Ошибка: Файл config.json не найден." >&2
  exit 1
fi

# Извлекаем параметры БД из config.json
DB_HOST=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR_PATH/config.json'))['database']['host'])")
DB_PORT=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR_PATH/config.json'))['database']['port'])")
DB_USER=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR_PATH/config.json'))['database']['user'])")
DB_PASS=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR_PATH/config.json'))['database']['password'])")
DB_NAME=$(python3 -c "import json; print(json.load(open('$SOURCE_DIR_PATH/config.json'))['database']['db_name'])")

BASE_DIR=$(dirname "$SOURCE_DIR_PATH")
TARGET_DIR_NAME=$(basename "$SOURCE_DIR_PATH")

# Создаем дамп базы данных
DB_DUMP_NAME="nh-db-$(date +%d-%m).sql"
DB_DUMP_PATH="$BACKUP_DIR/$DB_DUMP_NAME"

echo "Проверка подключения к базе данных..." >&2
if ! mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "SELECT 1;" > /dev/null 2>&1; then
  echo "Ошибка: Не удалось подключиться к базе данных." >&2
  exit 1
fi

echo "Создание дампа базы данных..." >&2
mysqldump -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" --single-transaction --routines --triggers --skip-lock-tables 2>/dev/null > "$DB_DUMP_PATH"

if [ $? -ne 0 ]; then
  echo "Ошибка: Не удалось создать дамп базы данных." >&2
  exit 1
fi

# Архивируем исходный код
ARCHIVE_NAME="nh-$(date +%d-%m).zip"
ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"

echo "Архивирование исходного кода..." >&2
(cd "$BASE_DIR" && zip -r -q "$ARCHIVE_PATH" "$TARGET_DIR_NAME")

# Создаем общий архив с кодом и дампом БД
FULL_BACKUP_NAME="nh-full-backup-$(date +%d-%m).zip"
FULL_BACKUP_PATH="$BACKUP_DIR/$FULL_BACKUP_NAME"

echo "Создание полного архива..." >&2
(cd "$BACKUP_DIR" && zip -q "$FULL_BACKUP_NAME" "$(basename "$ARCHIVE_PATH")" "$(basename "$DB_DUMP_PATH")")

# Удаляем временные файлы
rm -f "$ARCHIVE_PATH" "$DB_DUMP_PATH"

# Проверяем, что финальный архив создался
if [ ! -f "$FULL_BACKUP_PATH" ]; then
  echo "Ошибка: Финальный архив не был создан." >&2
  exit 1
fi

echo "$FULL_BACKUP_PATH"