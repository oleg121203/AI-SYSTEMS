#!/usr/bin/env python3
"""
Скрипт для тестирования функций мониторинга GitHub Actions.
Запускается отдельно от pytest для диагностики проблем.
"""
import asyncio
import os
from datetime import datetime

import os
token = os.environ.get("GITHUB_TOKEN")

async def test_github_token():
    """Проверяет доступность токена GitHub и выводит информацию о нем."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        print(f"[УСПЕХ] Токен GitHub найден: {token[:5]}...{token[-5:]}")
        print(f"Длина токена: {len(token)}")
        if token.startswith("github_pat_"):
            print("[УСПЕХ] Токен имеет правильный формат")
        else:
            print("[ОШИБКА] Токен имеет неправильный формат")
    else:
        print("[ОШИБКА] Токен GitHub не найден в переменных окружения")

        # Проверяем .env файл
        if os.path.exists(".env"):
            print("Найден файл .env, пробуем загрузить токен из него")
            with open(".env", "r") as env_file:
                for line in env_file:
                    if line.strip() and not line.startswith("#"):
                        try:
                            key, value = line.strip().split("=", 1)
                            if key == "GITHUB_TOKEN":
                                os.environ["GITHUB_TOKEN"] = value
                                print(
                                    f"[УСПЕХ] Загружен токен из .env: {value[:5]}...{value[-5:]}"
                                )
                                break
                        except ValueError:
                            pass


async def simple_api_test():
    """Базовый тест API GitHub."""
    import aiohttp

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[ОШИБКА] Токен GitHub не найден, тест API пропущен")
        return

    try:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Примерно будет выглядеть так:
        headers = {"Authorization": f"token {os.environ.get('GITHUB_TOKEN')}"}

        async with aiohttp.ClientSession() as session:
            url = "https://api.github.com/user"
            print(f"Выполняем запрос к {url}")

            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    print(
                        f"[УСПЕХ] API GitHub ответил: пользователь {data.get('login')}"
                    )
                else:
                    print(f"[ОШИБКА] Статус ответа: {response.status}")
                    print(await response.text())

    except Exception as e:
        print(f"[ИСКЛЮЧЕНИЕ] При запросе к GitHub API: {type(e).__name__}: {e}")


async def main():
    """Основная функция для запуска тестов."""
    print(f"=== Начало тестирования мониторинга GitHub: {datetime.now()} ===")

    print("\n1. Проверка токена GitHub:")
    await test_github_token()

    print("\n2. Базовый тест API GitHub:")
    await simple_api_test()

    print(f"\n=== Завершение тестирования: {datetime.now()} ===")


if __name__ == "__main__":
    # Явно устанавливаем токен для тестов
    if "GITHUB_TOKEN" not in os.environ:
        os.environ["GITHUB_TOKEN"] = (
            "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"
        )

    asyncio.run(main())
