#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функциональности миграции юзерботов
"""

import asyncio
import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import system_manager as sm
import database as db
import server_config

async def test_migration():
    """Тестирование функции миграции"""
    
    # Инициализируем базу данных
    await db.init_pool()
    await db.init_db()
    
    print("🧪 Тестирование системы миграции юзерботов")
    print("=" * 50)
    
    # Получаем список серверов
    servers = server_config.get_servers()
    print(f"📋 Найдено серверов: {len(servers)}")
    
    for ip, details in servers.items():
        print(f"  - {ip}: {details.get('name', 'Unknown')} ({details.get('status', 'unknown')})")
    
    # Получаем список юзерботов
    userbots = await db.get_all_userbots_full_info()
    print(f"\n🤖 Найдено юзерботов: {len(userbots)}")
    
    if userbots:
        # Берем первый юзербот для тестирования
        test_ub = userbots[0]
        ub_username = test_ub['ub_username']
        current_server = test_ub['server_ip']
        
        print(f"\n🔍 Тестируем юзербот: {ub_username}")
        print(f"📍 Текущий сервер: {current_server}")
        
        # Проверяем доступные серверы для миграции
        available_servers = await sm.get_available_servers_for_migration(ub_username, current_server)
        print(f"📋 Доступных серверов для миграции: {len(available_servers)}")
        
        for server in available_servers:
            print(f"  - {server['ip']}: {server['name']} ({server['country']}, {server['city']})")
        
        if available_servers:
            print(f"\n✅ Система миграции готова к работе!")
            print(f"💡 Для миграции {ub_username} доступно {len(available_servers)} серверов")
        else:
            print(f"\n⚠️ Нет доступных серверов для миграции {ub_username}")
    else:
        print("\n⚠️ Нет юзерботов для тестирования")
    
    print("\n" + "=" * 50)
    print("✅ Тестирование завершено")

async def test_server_availability():
    """Тестирование доступности серверов"""
    
    print("\n🔍 Проверка доступности серверов")
    print("-" * 30)
    
    servers = server_config.get_servers()
    
    for ip, details in servers.items():
        if ip == sm.LOCAL_IP:
            continue
            
        print(f"🌐 Проверяем {ip}...")
        
        # Проверяем свободное место
        has_space = await sm.check_server_disk_space(ip, min_gb=2)
        print(f"  💾 Свободное место: {'✅' if has_space else '❌'}")
        
        # Проверяем статус сервера
        status = details.get('status', 'unknown')
        print(f"  📊 Статус: {status}")
        
        print()

if __name__ == "__main__":
    asyncio.run(test_migration())
    asyncio.run(test_server_availability()) 