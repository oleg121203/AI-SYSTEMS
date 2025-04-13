import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import aiohttp
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_ai_integration")

# Загрузка переменных окружения
load_dotenv()


def load_config():
    """Загружает конфигурацию из файла."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_str = f.read()
        for key, value in os.environ.items():
            config_str = config_str.replace(f"${{{key}}}", value)
        return json.loads(config_str)
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        return {}


async def test_ai_status_endpoint():
    """Проверяет возможность запуска и остановки AI через API."""
    print("\nТест 1: Проверка управления статусом AI...")

    config = load_config()
    mcp_api_url = config.get("mcp_api", "http://localhost:7860")

    start_url = f"{mcp_api_url}/start_all"
    stop_url = f"{mcp_api_url}/stop_all"

    try:
        async with aiohttp.ClientSession() as session:
            # Проверка запуска AI
            print("Отправляю запрос на запуск всех AI (start_all)...")
            async with session.post(start_url) as response:
                if response.status == 200:
                    start_data = await response.json()
                    print(f"✅ Запрос на запуск успешен: {start_data}")
                    # Ждем немного, чтобы система успела отреагировать
                    await asyncio.sleep(2)
                else:
                    print(f"❌ Ошибка при запуске AI. Статус: {response.status}")
                    return False

            # Проверка остановки AI
            print("\nОтправляю запрос на остановку всех AI (stop_all)...")
            async with session.post(stop_url) as response:
                if response.status == 200:
                    stop_data = await response.json()
                    print(f"✅ Запрос на остановку успешен: {stop_data}")
                    # Ждем немного, чтобы система успела отреагировать
                    await asyncio.sleep(2)
                    return True
                else:
                    print(f"❌ Ошибка при остановке AI. Статус: {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Ошибка при тестировании статуса AI: {e}")
        return False


async def test_ai3_structure_integration():
    """Проверяет интеграцию между AI3 и MCP API через структуру проекта."""
    print("\nТест 2: Проверка интеграции AI3 со структурой проекта...")

    config = load_config()
    mcp_api_url = config.get("mcp_api", "http://localhost:7860")
    structure_url = f"{mcp_api_url}/structure"

    # Пример минимальной структуры для тестирования
    test_structure = {"test_folder": {"test_file.txt": None}}

    try:
        async with aiohttp.ClientSession() as session:
            # Получаем текущую структуру
            async with session.get(structure_url) as response:
                if response.status == 200:
                    current_structure = await response.json()
                    print(f"✅ Получена текущая структура проекта")
                else:
                    print(
                        f"❌ Ошибка при получении структуры. Статус: {response.status}"
                    )
                    return False

            # Отправляем тестовую структуру
            print("Отправляю тестовую структуру в API...")
            async with session.post(
                structure_url, json={"structure": test_structure}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Структура успешно отправлена: {result}")

                    # Проверяем, что структура обновилась
                    await asyncio.sleep(1)
                    async with session.get(structure_url) as get_response:
                        if get_response.status == 200:
                            updated_structure = await get_response.json()
                            if updated_structure.get("structure") == test_structure:
                                print("✅ Структура успешно обновлена в API")
                                return True
                            else:
                                print("❌ Структура не обновилась в API")
                                return False
                else:
                    print(
                        f"❌ Ошибка при отправке структуры. Статус: {response.status}"
                    )
                    return False
    except Exception as e:
        print(f"❌ Ошибка при тестировании интеграции AI3: {e}")
        return False


async def test_ai2_queue_integration():
    """Проверяет интеграцию AI2 с очередями задач."""
    print("\nТест 3: Проверка интеграции AI2 с очередями задач...")

    config = load_config()
    mcp_api_url = config.get("mcp_api", "http://localhost:7860")

    # Создаем тестовую подзадачу для очереди executor
    test_subtask = {
        "subtask": {
            "id": f"test_{int(time.time())}",
            "role": "executor",
            "filename": "test_file.js",
            "text": "Implement test function",
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Отправляем тестовую подзадачу в очередь
            print("Отправляю тестовую подзадачу в очередь executor...")
            async with session.post(
                f"{mcp_api_url}/subtask", json=test_subtask
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Подзадача успешно отправлена: {result}")
                    subtask_id = result.get("id") or test_subtask["subtask"]["id"]

                    # Проверяем очередь задач
                    print("Запрашиваю задачу из очереди executor...")
                    await asyncio.sleep(1)
                    async with session.get(
                        f"{mcp_api_url}/task/executor"
                    ) as get_response:
                        if get_response.status == 200:
                            queue_data = await get_response.json()
                            if (
                                "subtask" in queue_data
                                and queue_data["subtask"]["id"] == subtask_id
                            ):
                                print("✅ Задача успешно получена из очереди")
                                return True
                            elif "empty" in queue_data and queue_data.get(
                                "empty", False
                            ):
                                print(
                                    "ℹ️ Очередь пуста - задача уже могла быть обработана"
                                )
                                return True
                            else:
                                print(
                                    f"❓ Получены данные из очереди, но не та задача: {queue_data}"
                                )
                                return False
                        else:
                            print(
                                f"❌ Ошибка при получении задачи из очереди. Статус: {get_response.status}"
                            )
                            return False
                else:
                    print(
                        f"❌ Ошибка при отправке подзадачи. Статус: {response.status}"
                    )
                    return False
    except Exception as e:
        print(f"❌ Ошибка при тестировании интеграции AI2: {e}")
        return False


async def test_ai1_consultation_integration():
    """Проверяет интеграцию с механизмом консультаций AI1."""
    print("\nТест 4: Проверка интеграции с механизмом консультаций AI1...")

    config = load_config()
    mcp_api_url = config.get("mcp_api", "http://localhost:7860")

    # Тестовая структура задач для консультации
    test_consultation_data = {
        "task_structure": {
            "main_tasks": [
                {
                    "id": "test_task_1",
                    "title": "Test Task 1",
                    "description": "This is a test task",
                }
            ]
        },
        "target": config.get("target", "Test target"),
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Отправляем запрос на консультацию
            print("Отправляю запрос на консультацию по структуре задач...")
            async with session.post(
                f"{mcp_api_url}/consult_task_structure", json=test_consultation_data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if "improved_structure" in result and "recommendations" in result:
                        print(f"✅ Консультация успешно получена")
                        print(
                            f"   Рекомендации: {result.get('recommendations', [])[:1]}..."
                        )
                        return True
                    else:
                        print(f"❌ Некорректный формат ответа консультации: {result}")
                        return False
                else:
                    print(
                        f"❌ Ошибка при запросе консультации. Статус: {response.status}"
                    )
                    response_text = await response.text()
                    print(f"   Ответ: {response_text[:100]}...")
                    return False
    except Exception as e:
        print(f"❌ Ошибка при тестировании консультаций AI1: {e}")
        return False


async def run_tests():
    """Запускает все тесты интеграции AI компонентов."""
    print("=== Начало тестирования интеграции AI компонентов ===")

    # Запуск всех тестов
    status_ok = await test_ai_status_endpoint()
    ai3_ok = await test_ai3_structure_integration()
    ai2_ok = await test_ai2_queue_integration()
    ai1_ok = await test_ai1_consultation_integration()

    # Общий результат
    all_passed = all([status_ok, ai3_ok, ai2_ok, ai1_ok])

    print("\n=== Результаты тестирования интеграции ===")
    print(f"Управление статусом AI: {'✅' if status_ok else '❌'}")
    print(f"Интеграция AI3 (структура): {'✅' if ai3_ok else '❌'}")
    print(f"Интеграция AI2 (очереди): {'✅' if ai2_ok else '❌'}")
    print(f"Интеграция AI1 (консультации): {'✅' if ai1_ok else '❌'}")
    print(f"\nОбщий результат: {'✅ УСПЕШНО' if all_passed else '❌ ОШИБКА'}")

    return all_passed


if __name__ == "__main__":
    asyncio.run(run_tests())
