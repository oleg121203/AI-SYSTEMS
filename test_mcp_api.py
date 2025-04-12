import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

import aiohttp
from dotenv import load_dotenv

from utils import wait_for_service

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_mcp_api")

# Загрузка переменных окружения
load_dotenv()


async def test_mcp_api_availability():
    """Проверяет доступность MCP API."""
    print("Тест 1: Проверка доступности MCP API...")

    # Загрузка конфигурации
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_str = f.read()
        for key, value in os.environ.items():
            config_str = config_str.replace(f"${{{key}}}", value)
        config = json.loads(config_str)
    except Exception as e:
        print(f"Ошибка загрузки конфигурации: {e}")
        return False

    mcp_api_url = config.get("mcp_api", "http://localhost:7860")

    # Проверка доступности сервиса
    print(f"Проверка доступности MCP API по адресу: {mcp_api_url}")
    is_available = await wait_for_service(mcp_api_url, timeout=10)

    if is_available:
        print("✅ MCP API доступен!")
    else:
        print("❌ MCP API недоступен!")

    return is_available


async def test_mcp_api_health():
    """Проверяет endpoint /health MCP API."""
    print("\nТест 2: Проверка health endpoint...")

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.loads(f.read())

    mcp_api_url = config.get("mcp_api", "http://localhost:7860")
    health_url = f"{mcp_api_url}/health"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(health_url, timeout=5) as response:
                if response.status == 200:
                    health_data = await response.json()
                    print(f"✅ Health endpoint работает: {health_data}")
                    return True
                else:
                    print(f"❌ Health endpoint недоступен. Статус: {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Ошибка при проверке health endpoint: {e}")
        return False


async def test_mcp_api_structure():
    """Проверяет endpoint /structure MCP API."""
    print("\nТест 3: Проверка structure endpoint...")

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.loads(f.read())

    mcp_api_url = config.get("mcp_api", "http://localhost:7860")
    structure_url = f"{mcp_api_url}/structure"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(structure_url, timeout=5) as response:
                if response.status == 200:
                    structure_data = await response.json()
                    if "structure" in structure_data:
                        print(f"✅ Structure endpoint работает")
                        print(
                            f"   Количество ключей в структуре: {len(structure_data['structure'].keys()) if structure_data['structure'] else 0}"
                        )
                        return True
                    else:
                        print("❌ Structure endpoint не вернул ожидаемые данные")
                        return False
                else:
                    print(
                        f"❌ Structure endpoint недоступен. Статус: {response.status}"
                    )
                    return False
    except Exception as e:
        print(f"❌ Ошибка при проверке structure endpoint: {e}")
        return False


async def test_ai_status():
    """Проверяет статус AI компонентов через WebSocket."""
    print("\nТест 4: Проверка статуса AI компонентов...")

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.loads(f.read())

    mcp_api_url = config.get("mcp_api", "http://localhost:7860")
    ws_url = f"{mcp_api_url.replace('http://', 'ws://')}/ws"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, timeout=5) as ws:
                print("✅ Успешное подключение к WebSocket!")

                # Ожидаем первое сообщение со статусом
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    if "ai_status" in msg:
                        print(f"✅ Получен статус AI компонентов: {msg['ai_status']}")
                        return True
                    else:
                        print(f"❓ Получено сообщение, но без статуса AI: {msg}")
                        return False
                except asyncio.TimeoutError:
                    print("❌ Таймаут при ожидании сообщения от WebSocket")
                    return False
    except Exception as e:
        print(f"❌ Ошибка при подключении к WebSocket: {e}")
        return False


async def run_tests():
    """Запускает все тесты MCP API."""
    print("=== Начало тестирования MCP API ===")

    # Запуск всех тестов
    api_available = await test_mcp_api_availability()

    if not api_available:
        print("❌ MCP API недоступен, остальные тесты пропускаются.")
        return False

    health_ok = await test_mcp_api_health()
    structure_ok = await test_mcp_api_structure()
    ai_status_ok = await test_ai_status()

    # Общий результат
    all_passed = all([api_available, health_ok, structure_ok, ai_status_ok])

    print("\n=== Результаты тестирования ===")
    print(f"API доступен: {'✅' if api_available else '❌'}")
    print(f"Health endpoint: {'✅' if health_ok else '❌'}")
    print(f"Structure endpoint: {'✅' if structure_ok else '❌'}")
    print(f"WebSocket статус AI: {'✅' if ai_status_ok else '❌'}")
    print(f"\nОбщий результат: {'✅ УСПЕШНО' if all_passed else '❌ ОШИБКА'}")

    return all_passed


if __name__ == "__main__":
    asyncio.run(run_tests())
