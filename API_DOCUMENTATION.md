# API Documentation - SharkHost Container Management

## 🔐 Аутентификация

API использует токен-аутентификацию через заголовок HTTP.

**Заголовок:** `token: YOUR_TOKEN_HERE`

**Статус коды:**
- `200 OK` - успешный запрос
- `403 Forbidden` - ошибка аутентификации

## 📋 Эндпоинты

### 1. Проверка доступности

#### `GET /api/host/ping`

Проверяет доступность API сервера.

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "message": "pong"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/ping"
```

---

### 2. Системные ресурсы

#### `GET /api/host/resources`

Получает информацию о системных ресурсах сервера.

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "resources": {
    "cpu_load_percent": 0.3,
    "cpu_total": 4,
    "ram_load": 724.7,
    "ram_load_percent": 9.1,
    "ram_total": 7937.3
  }
}
```

**Поля ответа:**
- `cpu_load_percent` - загрузка CPU в процентах
- `cpu_total` - общее количество ядер CPU
- `ram_load` - используемая RAM в МБ
- `ram_load_percent` - использование RAM в процентах
- `ram_total` - общий объем RAM в МБ

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/resources"
```

---

### 3. Управление контейнерами

#### `GET /api/host/number`

Получает количество контейнеров.

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "number": 1
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/number"
```

---

#### `GET /api/host/list`

Получает список контейнеров.

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "list": [
    {
      "name": "nametest",
      "status": "running"
    }
  ]
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/list"
```

---

### 4. Управление контейнерами

#### `GET /api/host/create`

Создает новый контейнер.

**Параметры:**
- `port` (обязательный) - порт для привязки
- `name` (обязательный) - имя контейнера
- `userbot` (опциональный) - тип юзербота (hikka, heroku, fox)

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "message": "created"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/create?port=123&name=nametest&userbot=heroku"
```

---

#### `GET /api/host/status`

Получает статус контейнера.

**Параметры:**
- `name` (обязательный) - имя контейнера

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "status": "running"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/status?name=nametest"
```

---

#### `GET /api/host/stats`

Получает детальную статистику контейнера.

**Параметры:**
- `name` (обязательный) - имя контейнера

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "stats": {
    "name": "/nametest",
    "id": "c7f17346fc5f52efe2a82524bac98ee36085f8235062eaace516617cec74654a",
    "status": "running",
    "cpu_stats": {
      "cpu_usage": {
        "total_usage": 9175662000,
        "usage_in_kernelmode": 626070000,
        "usage_in_usermode": 8549592000
      },
      "system_cpu_usage": 1548390630000000,
      "online_cpus": 4
    },
    "memory_stats": {
      "usage": 128770048,
      "limit": 536870912
    },
    "networks": {
      "eth0": {
        "rx_bytes": 388417,
        "tx_bytes": 9609
      }
    }
  }
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/stats?name=nametest"
```

---

#### `GET /api/host/logs`

Получает логи контейнера.

**Параметры:**
- `name` (обязательный) - имя контейнера

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "logs": "🔄 Detected changes in requirements.txt, updating dependencies...\r\n⚠️ WARNING: Running pip as the 'root' user can result in broken permissions...\r\n🔄 Restarting...\r\nHeroku Userbot Web Interface running on 8080\r\n2025-08-03 10:12:44 [INFO] root: 🔮 Web mode ready for configuration\r\n2025-08-03 10:12:45 [INFO] root: 🔗 Please visit http://172.20.15.10:8080\r\n"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/logs?name=nametest"
```

---

#### `GET /api/host/exec`

Выполняет команду в контейнере.

**Параметры:**
- `name` (обязательный) - имя контейнера
- `command` (обязательный) - команда для выполнения

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "exec": {
    "exit_code": 0,
    "output": "root\n"
  }
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/exec?name=nametest&command=whoami"
```

---

#### `GET /api/host/action`

Выполняет действие с контейнером.

**Параметры:**
- `type` (обязательный) - тип действия (start, stop, restart)
- `name` (обязательный) - имя контейнера

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "message": "action completed"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/action?type=start&name=nametest"
```

---

#### `GET /api/host/remove`

Удаляет контейнер.

**Параметры:**
- `name` (обязательный) - имя контейнера

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "remove": null
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/remove?name=nametest"
```

---

#### `GET /api/host/update-image`

Обновляет Docker образ.

**Параметры:**
- `userbot` (обязательный) - тип юзербота для обновления

**Заголовки:**
```
token: YOUR_TOKEN_HERE
```

**Ответ:**
```json
{
  "message": "Image sharkhost/sharkhost:heroku updated",
  "output": "heroku: Pulling from sharkhost/sharkhost\nDigest: sha256:70ef436429084d7253110d2ea04460bdf3f8a0108e404cf9ccd5909115792f45\nStatus: Image is up to date for sharkhost/sharkhost:heroku\ndocker.io/sharkhost/sharkhost:heroku"
}
```

**Пример запроса:**
```bash
curl -H "token: YOUR_TOKEN_HERE" "http://m7.sharkhost.space:8000/api/host/update-image?userbot=heroku"
```

---

## ⚠️ Примечания

1. **Токен работает для всех операций** - один токен для всех эндпоинтов
2. **Контейнеры создаются с Docker** - используется Docker Compose
3. **Web интерфейс доступен** - юзерботы запускаются с веб-интерфейсом
4. **Порты привязываются** - контейнеры доступны по указанным портам

## ✅ Полный список эндпоинтов

Все эндпоинты протестированы и работают:

### 🔍 **Мониторинг:**
- `GET /api/host/ping` - проверка доступности
- `GET /api/host/resources` - системные ресурсы
- `GET /api/host/number` - количество контейнеров
- `GET /api/host/list` - список контейнеров

### 🐳 **Управление контейнерами:**
- `GET /api/host/create` - создание контейнера
- `GET /api/host/status` - статус контейнера
- `GET /api/host/stats` - статистика контейнера
- `GET /api/host/logs` - логи контейнера
- `GET /api/host/exec` - выполнение команды
- `GET /api/host/action` - действия с контейнером
- `GET /api/host/remove` - удаление контейнера
- `GET /api/host/update-image` - обновление образа

---

*Документация создана на основе тестирования API* 