import asyncio
import json
import os

import aiohttp
from dotenv import load_dotenv


async def test_openrouter():
    # Загрузка переменных окружения
    load_dotenv()

    # Получение API ключа из переменных окружения
    api_key = os.environ.get("OPENROUTER_API_KEY_3", "")
    if not api_key:
        print("Error: API key not found in environment variables")
        return

    # Настройка запроса
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    model = "qwen/qwen2.5-vl-32b-instruct"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    data = {
        "model": model,
        "messages": [{"role": "user", "content": "Hello, give me a short response."}],
        "max_tokens": 100,  # Ограничиваем количество токенов
        "temperature": 0.7,
    }

    print(f"API Key (first 5 chars): {api_key[:5]}...")
    print(f"Model: {model}")
    print(f"Endpoint: {endpoint}")

    try:
        # Выполнение запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=data, headers=headers) as resp:
                print(f"Status code: {resp.status}")

                response_text = await resp.text()
                print(f"Raw response: {response_text[:200]}...")

                if resp.status == 200:
                    response = json.loads(response_text)
                    content = (
                        response.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    print(f"Response content: {content}")
                else:
                    print(f"Error: {response_text}")
    except Exception as e:
        print(f"Exception: {e}")


if __name__ == "__main__":
    asyncio.run(test_openrouter())
