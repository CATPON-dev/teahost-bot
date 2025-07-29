# Строгое ограничение временных файлов пользователя до 120 MB

Данная инструкция позволяет создать жёсткое ограничение объёма всех временных файлов пользователя до **120 MB**, независимо от количества сеансов, с сохранением привычного `/tmp` для системы и других пользователей.

## Требования

- Ubuntu 22.04 или совместимая система
- Права администратора (sudo)
- Поддержка квот на файловой системе

## 1. Создание loop-файла под `/tmp` пользователя

### 1.1. Создание директории для образов
```
sudo mkdir -p /var/lib/user-tmp
```

### 1.2. Создание файла-образа размером 120 MB
```
sudo fallocate -l 120M /var/lib/user-tmp/USERNAME-tmp.img
```
> ⚠️ **Замените `USERNAME` на имя пользователя**

### 1.3. Форматирование в ext4
```
sudo mkfs.ext4 /var/lib/user-tmp/USERNAME-tmp.img
```

## 2. Монтирование образа и включение квот

### 2.1. Создание точки монтирования
```
sudo mkdir -p /tmp/isolated/USERNAME
sudo chown USERNAME:USERNAME /tmp/isolated/USERNAME
```

### 2.2. Добавление в /etc/fstab
Добавьте следующую строку в `/etc/fstab`:
```
/var/lib/user-tmp/USERNAME-tmp.img  /tmp/isolated/USERNAME  ext4  loop,usrquota,nodev,nosuid,noexec  0 0
```

### 2.3. Монтирование файловой системы
```
sudo mount /tmp/isolated/USERNAME
```

### 2.4. Инициализация и включение квот
```
sudo quotacheck -cum /tmp/isolated/USERNAME
sudo quotaon /tmp/isolated/USERNAME
```

### 2.5. Установка жёсткого лимита в 120 MB
```
sudo setquota -u USERNAME 0 122880 0 0 /tmp/isolated/USERNAME
```
> 📝 **122880 KB = 120 MB**

## 3. Перенаправление приложений на изолированный `/tmp`

### 3.1. Системное перенаправление через PAM
Добавьте в конец файла `/etc/security/pam_env.conf`:
```
USERNAME DEFAULT=TMPDIR OVERRIDE=/tmp/isolated/USERNAME
USERNAME DEFAULT=TMP OVERRIDE=/tmp/isolated/USERNAME
USERNAME DEFAULT=TEMP OVERRIDE=/tmp/isolated/USERNAME
```

### 3.2. Пользовательское перенаправление (опционально)
Добавьте в `~USERNAME/.bashrc`:
```
export TMPDIR=/tmp/isolated/USERNAME
export TMP=$TMPDIR
export TEMP=$TMPDIR
```

## 4. Проверка работы ограничения

### 4.1. Тест превышения лимита
```
sudo -u USERNAME dd if=/dev/zero of=/tmp/isolated/USERNAME/test bs=1M count=200
```
**Ожидаемый результат:** `No space left on device`

### 4.2. Проверка квоты пользователя
```
sudo quota -u USERNAME /tmp/isolated/USERNAME
```

### 4.3. Просмотр использованного места
```
df -h /tmp/isolated/USERNAME
```

## 5. Автоматизация для нескольких пользователей

### Скрипт настройки для пользователя
```
#!/bin/bash
# setup-user-tmp.sh

USERNAME=$1
if [ -z "$USERNAME" ]; then
    echo "Usage: $0 "
    exit 1
fi

# Создать loop-файл для tmp
sudo fallocate -l 120M /var/lib/user-tmp/${USERNAME}-tmp.img
sudo mkfs.ext4 /var/lib/user-tmp/${USERNAME}-tmp.img

# Создать точку монтирования
sudo mkdir -p /tmp/isolated/$USERNAME
sudo chown $USERNAME:$USERNAME /tmp/isolated/$USERNAME

# Добавить в fstab
echo "/var/lib/user-tmp/${USERNAME}-tmp.img /tmp/isolated/$USERNAME ext4 loop,usrquota,nodev,nosuid,noexec 0 0" | sudo tee -a /etc/fstab

# Смонтировать и настроить квоты
sudo mount /tmp/isolated/$USERNAME
sudo quotacheck -cum /tmp/isolated/$USERNAME
sudo quotaon /tmp/isolated/$USERNAME
sudo setquota -u $USERNAME 0 122880 0 0 /tmp/isolated/$USERNAME

# Настроить переменные окружения
echo "$USERNAME DEFAULT=TMPDIR OVERRIDE=/tmp/isolated/$USERNAME" | sudo tee -a /etc/security/pam_env.conf
echo "$USERNAME DEFAULT=TMP OVERRIDE=/tmp/isolated/$USERNAME" | sudo tee -a /etc/security/pam_env.conf
echo "$USERNAME DEFAULT=TEMP OVERRIDE=/tmp/isolated/$USERNAME" | sudo tee -a /etc/security/pam_env.conf

echo "Настроен изолированный tmp для $USERNAME: 120MB"
```

### Использование скрипта
```
chmod +x setup-user-tmp.sh
sudo ./setup-user-tmp.sh username
```

## 6. Мониторинг и обслуживание

### Проверка всех пользовательских квот
```
sudo repquota -a | grep /tmp/isolated
```

### Очистка старых файлов (добавить в crontab)
```
# Очищать файлы старше 24 часов каждый день в 3:00
0 3 * * * find /tmp/isolated/*/  -type f -mtime +1 -delete
```

## Результат

После выполнения всех шагов:

- ✅ Пользователь получает **единую** файловую систему на 120 MB для всех временных файлов
- ✅ Все сеансы и приложения пользователя используют **один общий пул** временного пространства
- ✅ При достижении лимита дальнейшая запись **блокируется** на уровне файловой системы
- ✅ Системный `/tmp` остаётся **нетронутым** и доступным для системных служб
- ✅ Защита от **DoS-атак** через заполнение временных файлов

## Важные замечания

- 🔒 Ограничение действует **независимо** от количества одновременных сеансов пользователя
- 🛡️ Защищает систему от атак типа "заполнение диска через /tmp"
- 📊 Не влияет на работу других пользователей и системных служб
- 🔄 Автоматически применяется при каждом входе пользователя в систему
