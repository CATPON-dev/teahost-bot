#!/bin/bash
# Быстрое исправление зависимостей Fox UserBot для пользователя ub1288092948

USERNAME="ub1288092948"
SERVER_IP="158.160.137.16"
UB_PATH="/home/$USERNAME/FoxUserbot"

echo "Исправляю зависимости Fox UserBot для пользователя $USERNAME..."

# 1. Исправляем права доступа к Python
echo "1. Исправляю права доступа к Python..."
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/python3 2>/dev/null || true"
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/python3.* 2>/dev/null || true"
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/python 2>/dev/null || true"
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/pip3 2>/dev/null || true"
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/pip 2>/dev/null || true"
ssh root@$SERVER_IP "setfacl -m u:$USERNAME:rx /usr/bin/uv 2>/dev/null || true"

# 2. Останавливаем сервис
echo "2. Останавливаю сервис..."
ssh root@$SERVER_IP "systemctl stop hikka-$USERNAME.service"

# 3. Переустанавливаем зависимости
echo "3. Переустанавливаю зависимости..."
ssh root@$SERVER_IP "cd $UB_PATH && {
    echo 'Installing uv...';
    python3 -m pip install uv 2>/dev/null || true;
    
    echo 'Installing critical packages...';
    python3 -m pip install pyrogram tgcrypto kurigram telegraph requests wget pystyle wikipedia gTTS lyricsgenius flask;
    
    echo 'Verifying installation...';
    python3 -c 'import pyrogram; print(\"pyrogram OK\")' 2>/dev/null || echo 'pyrogram missing';
    python3 -c 'import kurigram; print(\"kurigram OK\")' 2>/dev/null || echo 'kurigram missing';
    python3 -c 'import tgcrypto; print(\"tgcrypto OK\")' 2>/dev/null || echo 'tgcrypto missing';
}"

# 4. Запускаем сервис обратно
echo "4. Запускаю сервис..."
ssh root@$SERVER_IP "systemctl start hikka-$USERNAME.service"

# 5. Проверяем статус
echo "5. Проверяю статус сервиса..."
ssh root@$SERVER_IP "systemctl status hikka-$USERNAME.service"

echo "Исправление завершено!" 