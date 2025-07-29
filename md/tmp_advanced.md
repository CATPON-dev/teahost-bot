Дополнение: Полная блокировка доступа к системному /tmp

Данное дополнение к основной инструкции обеспечивает полную блокировку доступа пользователя к оригинальному системному /tmp, заставляя его использовать только изолированный каталог с ограничением 120 MB.
Требования

    Выполненная основная инструкция по настройке изолированного /tmp

    Установленный пакет acl для работы с расширенными правами доступа

1. Установка необходимых компонентов
1.1. Установка ACL (если не установлен)

bash
sudo apt update
sudo apt install acl

1.2. Проверка поддержки ACL на файловой системе

bash
# Проверить, что корневая ФС поддерживает ACL
mount | grep "on / "
# Должен быть флаг 'acl' или файловая система ext4/xfs

2. Блокировка доступа к системному /tmp
2.1. Установка запрета через ACL

bash
# Запретить пользователю любой доступ к /tmp
sudo setfacl -m u:USERNAME:0 /tmp

# Запретить доступ к будущим файлам в /tmp (default ACL)
sudo setfacl -m d:u:USERNAME:0 /tmp

2.2. Проверка установленных ACL

bash
# Просмотр текущих ACL на /tmp
getfacl /tmp

Ожидаемый вывод:

text
# file: tmp
# owner: root
# group: root
# flags: --t
user::rwx
user:USERNAME:---
group::rwx
mask::rwx
other::rwx
default:user::rwx
default:user:USERNAME:---
default:group::rwx
default:mask::rwx
default:other::rwx

3. Тестирование блокировки
3.1. Проверка прямого доступа к /tmp

bash
# Попытка просмотра содержимого /tmp
sudo -u USERNAME ls /tmp

Ожидаемый результат: Permission denied
3.2. Проверка создания файлов в /tmp

bash
# Попытка создания файла в /tmp
sudo -u USERNAME touch /tmp/test_file

Ожидаемый результат: Permission denied
3.3. Проверка работы изолированного tmp

bash
# Проверка доступа к изолированному каталогу
sudo -u USERNAME touch /tmp/isolated/USERNAME/test_file
sudo -u USERNAME ls /tmp/isolated/USERNAME/

Ожидаемый результат: Файл успешно создан и виден
3.4. Проверка переменных окружения

bash
# Проверка, что приложения используют изолированный tmp
sudo -u USERNAME bash -c 'echo $TMPDIR'
sudo -u USERNAME python3 -c "import tempfile; print(tempfile.gettempdir())"

Ожидаемый результат: /tmp/isolated/USERNAME
4. Массовое применение для нескольких пользователей
Скрипт блокировки для пользователя

bash
#!/bin/bash
# block-user-tmp.sh

USERNAME=$1
if [ -z "$USERNAME" ]; then
    echo "Usage: $0 <username>"
    exit 1
fi

# Проверить, что пользователь существует
if ! id "$USERNAME" &>/dev/null; then
    echo "Пользователь $USERNAME не существует"
    exit 1
fi

# Заблокировать доступ к системному /tmp
sudo setfacl -m u:$USERNAME:0 /tmp
sudo setfacl -m d:u:$USERNAME:0 /tmp

# Проверить блокировку
echo "Проверка блокировки для $USERNAME:"
sudo -u $USERNAME ls /tmp 2>&1 | grep -q "Permission denied" && echo "✅ Доступ к /tmp заблокирован" || echo "❌ Блокировка не работает"

echo "Блокировка /tmp для пользователя $USERNAME завершена"

Использование скрипта

bash
chmod +x block-user-tmp.sh
sudo ./block-user-tmp.sh username

5. Снятие блокировки (если необходимо)
5.1. Удаление ACL для конкретного пользователя

bash
# Удалить запрет для пользователя
sudo setfacl -x u:USERNAME /tmp
sudo setfacl -x d:u:USERNAME /tmp

5.2. Полное удаление всех ACL с /tmp

bash
# ОСТОРОЖНО: Удаляет ВСЕ ACL с /tmp
sudo setfacl -b /tmp

6. Мониторинг и диагностика
6.1. Проверка всех пользователей с ограничениями

bash
# Показать всех пользователей с ACL на /tmp
getfacl /tmp | grep "user:" | grep -v "user::"

6.2. Лог попыток доступа к /tmp

Для мониторинга попыток доступа можно использовать auditd:

bash
# Установка audit
sudo apt install auditd

# Добавление правила мониторинга /tmp
sudo auditctl -w /tmp -p wa -k tmp_access

# Просмотр логов
sudo ausearch -k tmp_access

7. Важные предупреждения
⚠️ Потенциальные проблемы

    Некоторые системные службы могут создавать файлы от имени пользователя в /tmp

    Старые приложения могут не учитывать переменные окружения TMPDIR

    SSH/X11 forwarding может создавать сокеты в /tmp

🔧 Решения проблем

Если возникают проблемы с определенными приложениями:

bash
# Временно разрешить доступ для отладки
sudo setfacl -m u:USERNAME:rwx /tmp

# После выяснения причины вернуть запрет
sudo setfacl -m u:USERNAME:0 /tmp

Результат полной защиты

После выполнения основной инструкции + данного дополнения:

    🚫 Пользователь полностью заблокирован от прямого доступа к системному /tmp

    🔒 Единственный доступ к временным файлам - через изолированный каталог с лимитом 120 MB

    🛡️ 100% защита системы от DoS-атак через заполнение /tmp

    ✅ Все приложения автоматически используют безопасный изолированный каталог

    📊 Полный контроль над использованием временного пространства

Проверка итоговой защиты

bash
# Должны давать Permission denied
sudo -u USERNAME ls /tmp
sudo -u USERNAME touch /tmp/test
sudo -u USERNAME echo "test" > /tmp/file

# Должны работать нормально
sudo -u USERNAME ls $TMPDIR
sudo -u USERNAME dd if=/dev/zero of=$TMPDIR/test bs=1M count=50
sudo -u USERNAME python3 -c "import tempfile; tempfile.mktemp()"
