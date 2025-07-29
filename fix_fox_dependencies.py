#!/usr/bin/env python3
"""
Скрипт для исправления зависимостей Fox UserBot для пользователя ub1288092948
"""

import asyncio
import sys
import os

# Добавляем путь к модулям
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from system_manager import (
    fix_python_permissions_for_existing_user, 
    reinstall_fox_dependencies,
    run_command_async
)

async def main():
    ub_username = "ub1288092948"
    server_ip = "158.160.137.16"
    
    print(f"Исправляю зависимости Fox UserBot для пользователя {ub_username}...")
    
    try:
        # 1. Исправляем права доступа к Python
        print("1. Исправляю права доступа к Python...")
        await fix_python_permissions_for_existing_user(ub_username, server_ip)
        
        # 2. Переустанавливаем зависимости
        print("2. Переустанавливаю зависимости...")
        success = await reinstall_fox_dependencies(ub_username, server_ip)
        
        if success:
            print("✅ Зависимости успешно переустановлены!")
        else:
            print("❌ Ошибка при переустановке зависимостей")
            
        # 3. Проверяем статус сервиса
        print("3. Проверяю статус сервиса...")
        check_cmd = f"sudo systemctl status hikka-{ub_username}.service"
        result = await run_command_async(check_cmd, server_ip, check_output=False)
        
        if result.get("success"):
            print("✅ Сервис работает корректно!")
        else:
            print(f"⚠️ Сервис все еще имеет проблемы: {result.get('error')}")
            
    except Exception as e:
        print(f"❌ Ошибка при исправлении зависимостей: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 