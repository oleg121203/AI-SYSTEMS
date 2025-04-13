import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("test_websocket")


async def test_websocket_connection():
    """Тестирует WebSocket соединение с MCP API."""
    print("=== Тест WebSocket соединения с MCP API ===")

    # Адрес WebSocket
    ws_url = "ws://localhost:7860/ws"

    try:
        print(f"Подключение к {ws_url}...")
        async with websockets.connect(ws_url, timeout=10) as websocket:
            print("✅ Успешное подключение к WebSocket!")

            # Отправляем запрос на получение полного статуса
            print("Отправка запроса на получение полного статуса...")
            await websocket.send(json.dumps({"action": "get_full_status"}))

            # Ждем ответа
            print("Ожидание ответа от сервера...")
            response = await asyncio.wait_for(websocket.recv(), timeout=10)

            # Анализируем ответ
            try:
                data = json.loads(response)
                print(f"✅ Получен ответ от сервера! Тип данных: {data.get('type')}")

                # Проверяем ключевые компоненты ответа
                if "ai_status" in data:
                    print(f"AI статус: {data['ai_status']}")

                if "queues" in data:
                    print(f"Количество задач в очередях:")
                    for queue_name, queue_tasks in data["queues"].items():
                        print(f"  {queue_name}: {len(queue_tasks)}")

                if "structure" in data:
                    print(f"Структура проекта получена: {bool(data['structure'])}")
                    print(
                        f"Корневые ключи структуры: {list(data['structure'].keys()) if data['structure'] else []}"
                    )

                return True
            except json.JSONDecodeError:
                print(f"❌ Ошибка декодирования JSON ответа: {response[:100]}...")
                return False

    except asyncio.TimeoutError:
        print("❌ Таймаут при подключении или ожидании ответа от WebSocket")
        return False
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"❌ Соединение WebSocket закрыто с ошибкой: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка при работе с WebSocket: {e}")
        return False


async def test_specific_websocket_updates():
    """Тестирует получение обновлений по различным событиям."""
    print("\n=== Тест получения обновлений через WebSocket ===")

    ws_url = "ws://localhost:7860/ws"

    try:
        print(f"Подключение к {ws_url}...")
        async with websockets.connect(ws_url, timeout=10) as websocket:
            print("✅ Успешное подключение к WebSocket!")

            # Получаем первоначальный ответ от сервера (если есть)
            try:
                initial_response = await asyncio.wait_for(websocket.recv(), timeout=2)
                print(f"Получено начальное сообщение: {initial_response[:100]}...")
            except asyncio.TimeoutError:
                print("Начальное сообщение не получено (таймаут)")

            # Отправляем запрос на обновление статуса AI
            print("\nТест 1: Запрашиваем обновление статуса AI...")
            await websocket.send(json.dumps({"action": "get_status"}))

            try:
                status_response = await asyncio.wait_for(websocket.recv(), timeout=5)
                data = json.loads(status_response)
                if "ai_status" in data:
                    print(f"✅ Получен ответ со статусом AI: {data['ai_status']}")
                else:
                    print(f"❌ Ответ не содержит статус AI: {data}")
            except Exception as e:
                print(f"❌ Ошибка при получении статуса AI: {e}")

            # Отправляем запрос на обновление очередей
            print("\nТест 2: Запрашиваем данные очередей...")
            await websocket.send(json.dumps({"action": "get_queues"}))

            try:
                queues_response = await asyncio.wait_for(websocket.recv(), timeout=5)
                data = json.loads(queues_response)
                if "queues" in data:
                    print(
                        f"✅ Получен ответ с очередями: {len(data['queues'])} очередей"
                    )
                    for queue, tasks in data["queues"].items():
                        print(f"  {queue}: {len(tasks)} задач")
                else:
                    print(f"❌ Ответ не содержит данных очередей: {data}")
            except Exception as e:
                print(f"❌ Ошибка при получении данных очередей: {e}")

            # Отправляем запрос на получение структуры проекта
            print("\nТест 3: Запрашиваем структуру проекта...")
            await websocket.send(json.dumps({"action": "get_structure"}))

            try:
                structure_response = await asyncio.wait_for(websocket.recv(), timeout=5)
                data = json.loads(structure_response)
                if "structure" in data:
                    print(f"✅ Получена структура проекта")
                    print(
                        f"  Корневые ключи: {list(data['structure'].keys()) if data['structure'] else []}"
                    )
                else:
                    print(f"❌ Ответ не содержит структуры проекта: {data}")
            except Exception as e:
                print(f"❌ Ошибка при получении структуры проекта: {e}")

            return True

    except Exception as e:
        print(f"❌ Ошибка при работе с WebSocket: {e}")
        return False


async def main():
    """Запускает все тесты WebSocket."""
    print("Начало тестирования WebSocket...\n")

    # Проверяем соединение
    connection_ok = await test_websocket_connection()

    if connection_ok:
        print("\n✅ Соединение WebSocket установлено успешно!")
        # Проверяем получение обновлений
        updates_ok = await test_specific_websocket_updates()

        if updates_ok:
            print("\n✅ Тесты обновлений прошли успешно!")
        else:
            print("\n❌ Тесты обновлений завершились с ошибками.")
    else:
        print("\n❌ Не удалось установить соединение WebSocket.")

    print("\nТестирование WebSocket завершено.")


if __name__ == "__main__":
    asyncio.run(main())
