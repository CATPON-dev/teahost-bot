import re
import os
import shutil

# Список файлов, которые нужно обработать
FILES_TO_PROCESS = [
    'admin_handlers.py',
    'user_handlers.py',
    'app.py',
    'ban_manager.py',
    'bot.py',
    'middlewares/ban_check.py',
    'middlewares/subscription_check.py',
]

# Регулярное выражение:
# (?<!await\s) - негативный просмотр назад, убеждается, что перед db. нет слова "await "
# (db\.[a-zA-Z_][a-zA-Z0-9_]*\() - захватывает 'db.', имя функции и открывающую скобку
PATTERN = re.compile(r"(?<!await\s)(db\.[a-zA-Z_][a-zA-Z0-9_]*\()")

def process_file(filepath):
    """
    Читает файл, добавляет 'await' ко всем вызовам db.* и сохраняет изменения.
    Создает резервную копию перед изменением.
    """
    if not os.path.exists(filepath):
        print(f"⚠️  Файл не найден, пропускаю: {filepath}")
        return

    # Создаем резервную копию
    backup_path = filepath + ".bak"
    shutil.copy(filepath, backup_path)
    
    print(f"🔄 Обрабатываю файл: {filepath}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Заменяем все найденные совпадения, добавляя 'await ' в начало
    # \g<0> - это ссылка на всю найденную подстроку
    new_content, count = PATTERN.subn(r"await \g<0>", content)

    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"✅ Успешно! Внесено изменений: {count}. Резервная копия сохранена в {backup_path}")
    else:
        print(f"👌 Изменения не требуются. Резервная копия {backup_path} удалена.")
        os.remove(backup_path)


if __name__ == "__main__":
    print("--- Запуск скрипта для добавления await к вызовам db ---")
    for file in FILES_TO_PROCESS:
        process_file(file)
    print("\n--- Скрипт завершил работу ---")
    print("Теперь вы можете запускать вашего бота.")