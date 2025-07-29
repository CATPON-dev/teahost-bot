# 🚀 SharkHost API Documentation

## 📋 Обзор

SharkHost API предоставляет RESTful интерфейс для управления пользовательскими ботами (userbots) и мониторинга серверов. API построен на FastAPI и поддерживает асинхронные операции.

**Базовый URL:** `https://api.sharkhost.space/api/v1`

## 🔐 Аутентификация

Все API запросы требуют аутентификации через API токен в заголовке:

```
X-API-Token: your_api_token_here
```

### Получение токена
API токен можно получить через Telegram бота командой `/token` или через эндпоинт `/token/regenerate`.

## 📊 Общие принципы

### Формат ответов
Все ответы API имеют единый формат:

```json
{
  "success": true,
  "data": {
    // данные ответа
  }
}
```

### Обработка ошибок
При ошибках API возвращает соответствующий HTTP статус код и детали ошибки:

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Описание ошибки"
  }
}
```

### Коды ошибок
- `CLIENT_ERROR` - Ошибка клиента (4xx)
- `SERVER_ERROR` - Ошибка сервера (5xx)
- `NOT_FOUND` - Ресурс не найден (404)
- `FORBIDDEN` - Доступ запрещен (403)
- `CONFLICT` - Конфликт данных (409)
- `RATE_LIMIT_EXCEEDED` - Превышен лимит запросов (429)

## 🛡️ Ограничения

### Rate Limiting
- **Лимит:** 20 запросов в минуту
- **Окно времени:** 60 секунд
- **При превышении:** HTTP 429 Too Many Requests

### Поддержка режима обслуживания
API автоматически перенаправляет на страницу технического обслуживания при включенном `MAINTENANCE_MODE`.

---

## 🖥️ Серверы (Servers)

### GET /servers/status
Получение статуса всех серверов или конкретного сервера.

**Параметры:**
- `code` (опционально) - Код сервера для фильтрации

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/servers/status" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "servers": [
      {
        "code": "US1",
        "name": "United States Server",
        "flag": "🇺🇸",
        "location": "United States, New York",
        "status": "online",
        "cpu_usage": "45%",
        "ram_usage": "67%",
        "disk_usage": "23%",
        "uptime": "15 days",
        "userbots_count": 12,
        "slots": "12/20"
      }
    ]
  }
}
```

### GET /servers/available
Получение списка доступных для установки серверов.

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/servers/available" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "available_servers": [
      {
        "code": "US1",
        "name": "United States Server",
        "flag": "🇺🇸",
        "location": "United States, New York",
        "slots_free": 8
      }
    ]
  }
}
```

---

## 👥 Пользователи (Users)

### GET /users/{identifier}
Получение информации о пользователе по username или ID.

**Параметры:**
- `identifier` (path) - Username или ID пользователя

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/users/john_doe" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "owner": {
      "id": 123456789,
      "username": "john_doe",
      "full_name": "John Doe",
      "registered_at": "2024-01-15T10:30:00"
    },
    "userbot": {
      "ub_username": "ub123456789",
      "ub_type": "hikka",
      "status": "running",
      "uptime": "5 days",
      "server_code": "US1",
      "created_at": "2024-01-15T11:00:00"
    }
  }
}
```

### POST /token/regenerate
Регенерация API токена пользователя.

**Пример запроса:**
```bash
curl -X POST "https://api.sharkhost.space/api/v1/token/regenerate" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "new_token": "john_doe:123456789:a1b2c3d4e5f6..."
  }
}
```

---

## 🤖 Пользовательские боты (Userbots)

### GET /userbots
Получение списка пользовательских ботов текущего пользователя.

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/userbots" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "userbots": [
      {
        "ub_username": "ub123456789",
        "ub_type": "hikka",
        "status": "running",
        "uptime": "5 days",
        "created_at": "2024-01-15T11:00:00",
        "server": {
          "code": "US1",
          "flag": "🇺🇸"
        }
      }
    ]
  }
}
```

### GET /userbots/{ub_username}/logs
Получение логов пользовательского бота.

**Параметры:**
- `ub_username` (path) - Имя пользовательского бота
- `lines` (query, опционально) - Количество строк логов (1-500, по умолчанию 50)

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/userbots/ub123456789/logs?lines=100" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "logs": [
      "2024-01-20 10:30:15 INFO: Userbot started",
      "2024-01-20 10:30:16 INFO: Connected to Telegram",
      "2024-01-20 10:30:17 INFO: Ready to receive messages"
    ]
  }
}
```

### POST /userbots/create
Создание нового пользовательского бота.

**Тело запроса:**
```json
{
  "server_code": "US1",
  "ub_type": "hikka"
}
```

**Поддерживаемые типы:**
- `hikka` - Hikka Userbot
- `heroku` - Heroku Userbot  
- `fox` - Fox Userbot

**Пример запроса:**
```bash
curl -X POST "https://api.sharkhost.space/api/v1/userbots/create" \
  -H "X-API-Token: your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "server_code": "US1",
    "ub_type": "hikka"
  }'
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "ub_username": "ub123456789",
    "message": "Userbot installation initiated."
  }
}
```

### DELETE /userbots/{ub_username}
Удаление пользовательского бота.

**Параметры:**
- `ub_username` (path) - Имя пользовательского бота

**Пример запроса:**
```bash
curl -X DELETE "https://api.sharkhost.space/api/v1/userbots/ub123456789" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "message": "Userbot has been successfully deleted."
  }
}
```

### POST /userbots/{ub_username}/manage
Управление состоянием пользовательского бота.

**Параметры:**
- `ub_username` (path) - Имя пользовательского бота

**Тело запроса:**
```json
{
  "action": "start"
}
```

**Поддерживаемые действия:**
- `start` - Запуск бота
- `stop` - Остановка бота
- `restart` - Перезапуск бота

**Пример запроса:**
```bash
curl -X POST "https://api.sharkhost.space/api/v1/userbots/ub123456789/manage" \
  -H "X-API-Token: your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "restart"
  }'
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "new_status": "running"
  }
}
```

### POST /userbots/{ub_username}/transfer
Передача пользовательского бота другому пользователю.

**Параметры:**
- `ub_username` (path) - Имя пользовательского бота

**Тело запроса:**
```json
{
  "new_owner_identifier": "new_owner_username"
}
```

**Пример запроса:**
```bash
curl -X POST "https://api.sharkhost.space/api/v1/userbots/ub123456789/transfer" \
  -H "X-API-Token: your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "new_owner_identifier": "new_owner_username"
  }'
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "message": "Userbot successfully transferred to user new_owner_username."
  }
}
```

### POST /userbots/exec
Выполнение команды в контексте пользовательского бота.

**Тело запроса:**
```json
{
  "ub_username": "ub123456789",
  "command": "ls -la"
}
```

**Пример запроса:**
```bash
curl -X POST "https://api.sharkhost.space/api/v1/userbots/exec" \
  -H "X-API-Token: your_token" \
  -H "Content-Type: application/json" \
  -d '{
    "ub_username": "ub123456789",
    "command": "ls -la"
  }'
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "stdout": "total 8\ndrwxr-xr-x 2 ub123456789 ub123456789 4096 Jan 20 10:30 .",
    "stderr": "",
    "exit_code": 0
  }
}
```

---

## 📊 Статистика (Stats)

### GET /stats
Получение расширенной статистики системы.

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/stats" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": {
    "total_users": 1500,
    "owners_count": 1200,
    "new_users_today": 25,
    "total_ubs": 1200,
    "active_ubs_count": 1150,
    "inactive_ubs_count": 50,
    "bots_by_type": {
      "Hikka": 800,
      "Heroku": 300,
      "Fox": 100
    },
    "bots_by_server": {
      "192.168.1.100": {
        "count": 300,
        "flag": "🇺🇸",
        "name": "US Server 1"
      },
      "192.168.1.101": {
        "count": 200,
        "flag": "🇪🇺",
        "name": "EU Server 1"
      }
    }
  }
}
```

---

## 📝 Коммиты (Commits)

### GET /commits
Получение истории коммитов.

**Параметры:**
- `limit` (query, опционально) - Количество коммитов (по умолчанию 50)
- `offset` (query, опционально) - Смещение для пагинации (по умолчанию 0)

**Пример запроса:**
```bash
curl -X GET "https://api.sharkhost.space/api/v1/commits?limit=10&offset=0" \
  -H "X-API-Token: your_token"
```

**Пример ответа:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "commit_id": "abc123def456",
      "admin_id": 123456789,
      "admin_name": "Admin User",
      "admin_username": "admin",
      "commit_text": "Added new server configuration",
      "created_at": "2024-01-20T10:30:00"
    }
  ]
}
```

---

## 🔧 Модели данных

### UserbotCreateRequest
```json
{
  "server_code": "string (required)",
  "ub_type": "hikka|heroku|fox (required)"
}
```

### UserbotManageRequest
```json
{
  "action": "start|stop|restart (required)"
}
```

### UserbotTransferRequest
```json
{
  "new_owner_identifier": "string (required)"
}
```

### UserbotExecRequest
```json
{
  "ub_username": "string (required)",
  "command": "string (required)"
}
```

---

## 🚨 Ограничения и правила

### Ограничения пользователей
- Максимум 1 активный пользовательский бот на пользователя
- Пользователь должен принять соглашение
- Пользователь не должен быть заблокирован

### Ограничения серверов
- Установка на сервисный сервер запрещена
- Проверка доступности слотов на сервере
- Проверка разрешений на установку

### Безопасность
- Все действия логируются
- Проверка владельца для всех операций
- Автоматические уведомления в Telegram

---

## 📞 Поддержка

При возникновении проблем с API:

1. Проверьте правильность API токена
2. Убедитесь в соблюдении лимитов запросов
3. Проверьте статус серверов
4. Обратитесь к администратору системы

---

## 🔄 Версионирование

Текущая версия API: **v1**

Все эндпоинты доступны по префиксу `/api/v1/`

---

*Документация обновлена: 2024-01-20* 