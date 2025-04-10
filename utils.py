import asyncio
import json
import logging
import os
import random  # Added import
import time
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

# Налаштування структурованого логування в JSON
import json_log_formatter
from dotenv import load_dotenv

formatter = json_log_formatter.JSONFormatter()
handler = logging.FileHandler("logs/mcp.log")
handler.setFormatter(formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

load_dotenv()


def log_message(message: str):
    """Логирование сообщения в консоль и файл"""
    timestamp = datetime.now().isoformat()
    log_data = {"message": message, "time": timestamp}
    log_json = json.dumps(log_data)

    # Выводим в консоль
    print(log_json)

    # Записываем в файл лога
    log_file = os.environ.get("LOG_FILE", "logs/mcp.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{log_json}\n")


def load_config(config_file="config.json"):
    """Завантажує конфігурацію з файлу, замінюючи змінні оточення."""
    try:
        with open(config_file, "r") as f:
            config_str = f.read()
        for key, value in os.environ.items():
            config_str = config_str.replace(f"${{{key}}}", value)
        return json.loads(config_str)
    except Exception as e:
        logger.error({"message": "Failed to load config", "error": str(e)})
        raise


def read_config_json(file_path: str = "config.json") -> Dict[str, Any]:
    """Чтение конфигурационного файла JSON"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error reading config file {file_path}: {e}")
        return {}


def save_config_json(config: Dict[str, Any], file_path: str = "config.json"):
    """Сохранение конфигурационного файла JSON"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving config file {file_path}: {e}")


def load_model_config() -> Dict[str, Any]:
    """
    Загрузка конфигурации моделей

    Returns:
        Словарь с конфигурацией моделей
    """
    models = {
        "codestral": {
            "provider": "together",
            "model": "codestral-latest",
            "api_key_env": "TOGETHER_API_KEY",
            "max_tokens": 8192,
            "description": "Модель Codestral для генерации кода",
        },
        "gemini-pro": {
            "provider": "gemini",
            "model": "gemini-pro",
            "api_key_env": "GEMINI_API_KEY",
            "max_tokens": 4096,
            "description": "Gemini Pro модель для обработки текста",
        },
        "gemini-1.5-pro": {
            "provider": "gemini",
            "model": "gemini-1.5-pro",
            "api_key_env": "GEMINI_25_API_KEY",
            "max_tokens": 16384,
            "description": "Gemini 1.5 Pro для сложных задач",
        },
        "cohere-command": {
            "provider": "cohere",
            "model": "command",
            "api_key_env": "COHERE_API_KEY",
            "max_tokens": 4096,
            "description": "Cohere Command для работы с текстом",
        },
        "claude-3-opus": {
            "provider": "openrouter",
            "model": "anthropic/claude-3-opus",
            "api_key_env": "OPENROUTER_API_KEY",
            "max_tokens": 8192,
            "description": "Claude 3 Opus - самая мощная модель Claude",
        },
        "claude-3-sonnet": {
            "provider": "openrouter",
            "model": "anthropic/claude-3-sonnet",
            "api_key_env": "OPENROUTER_API_KEY_2",
            "max_tokens": 4096,
            "description": "Claude 3 Sonnet - баланс между скоростью и качеством",
        },
        "claude-3-haiku": {
            "provider": "openrouter",
            "model": "anthropic/claude-3-haiku",
            "api_key_env": "OPENROUTER_API_KEY_3",
            "max_tokens": 4096,
            "description": "Claude 3 Haiku - быстрая и компактная версия Claude",
        },
        "mixtral-8x7b": {
            "provider": "groq",
            "model": "mixtral-8x7b-32768",
            "api_key_env": "GROQ_API_KEY",
            "max_tokens": 4096,
            "description": "Mixtral 8x7B - мощная модель с длинным контекстом",
        },
        "llama-3-70b": {
            "provider": "groq",
            "model": "llama3-70b-8192",
            "api_key_env": "GROQ_API_KEY",
            "max_tokens": 8192,
            "description": "LLaMA 3 70B - мощная модель с открытым исходным кодом",
        },
    }

    return models


def get_available_models() -> Dict[str, str]:
    """
    Получает список доступных моделей

    Returns:
        Словарь {id_модели: описание}
    """
    config = load_model_config()
    return {model_id: model["description"] for model_id, model in config.items()}


def check_api_keys() -> Dict[str, bool]:
    """
    Проверяет наличие API ключей для всех моделей

    Returns:
        Словарь {id_модели: True/False}
    """
    config = load_model_config()
    result = {}

    for model_id, model in config.items():
        api_key_env = model.get("api_key_env")
        result[model_id] = api_key_env in os.environ and os.environ[api_key_env] != ""

    return result


def setup_logging():
    """
    Настройка логирования в приложении
    """
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("logs/mcp.log")],
    )

    return logging.getLogger(__name__)


def parse_json_from_response(response: str) -> Dict[str, Any]:
    """
    Извлечение JSON из ответа модели

    Args:
        response: Ответ модели

    Returns:
        Словарь с данными из JSON
    """
    import json
    import re

    # Ищем JSON в ответе
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)

    if json_match:
        json_str = json_match.group(1)
    else:
        # Если нет блока кода, пробуем найти JSON без маркеров
        json_match = re.search(r"(\{[\s\S]*\})", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            raise ValueError("JSON не найден в ответе")

    try:
        result = json.loads(json_str)
        return result
    except json.JSONDecodeError as e:
        raise ValueError(f"Ошибка парсинга JSON: {e}")


async def process_file_tasks(structure: Dict[str, Any], mcp_api_url: str):
    """
    Функция для обработки задач по созданию файлов

    Args:
        structure: Структура проекта
        mcp_api_url: URL API для MCP
    """
    import aiohttp
    from llm_provider import LLMProvider

    llm = LLMProvider()
    await llm.initialize()

    # Извлекаем файлы из структуры
    files = extract_files_from_structure(structure)

    # Создаем задачи для каждого файла
    tasks = []
    for file_path, file_info in files.items():
        task = {
            "file_path": file_path,
            "description": file_info.get("description", ""),
            "contents": "",
            "status": "pending",
        }
        tasks.append(task)

    # Отправляем задачи в API
    async with aiohttp.ClientSession() as session:
        for task in tasks:
            async with session.post(
                f"{mcp_api_url}/api/tasks", json={"task": task}
            ) as response:
                if response.status != 200:
                    print(f"Error creating task for {task['file_path']}")

    await llm.close()


def extract_files_from_structure(structure: Dict[str, Any]) -> Dict[str, Any]:
    """
    Рекурсивно извлекает файлы из структуры проекта

    Args:
        structure: Структура проекта

    Returns:
        Словарь с путями к файлам и их свойствами
    """
    files = {}

    def extract_from_node(node, current_path=""):
        if isinstance(node, dict):
            if "type" in node and node["type"] == "file":
                # Это файл
                file_path = current_path + node.get("name", "")
                files[file_path] = {
                    "description": node.get("description", ""),
                    "template": node.get("template", ""),
                    "code": node.get("code", ""),
                }
            else:
                # Это директория или другой объект
                for key, value in node.items():
                    if key == "children" and isinstance(value, list):
                        # Обрабатываем детей
                        for child in value:
                            if "name" in child:
                                new_path = current_path + child["name"] + "/"
                                extract_from_node(child, new_path)
                            else:
                                extract_from_node(child, current_path)
                    elif isinstance(value, (dict, list)):
                        extract_from_node(value, current_path)

    extract_from_node(structure)
    return files


async def wait_for_service(url, timeout=60):
    """Чекає, поки сервіс стане доступним."""
    start_time = asyncio.get_event_loop().time()
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                async with session.get(url, timeout=5) as resp:
                    if resp.status < 400:
                        logger.info({"message": f"Service at {url} is available"})
                        return True
                    else:
                        logger.warning(
                            {
                                "message": f"Service at {url} returned status {resp.status}"
                            }
                        )
            except aiohttp.ClientError as e:
                logger.warning({"message": f"Connection to {url} failed: {str(e)}"})
            except Exception as e:
                logger.warning(
                    {"message": f"Unexpected error connecting to {url}: {str(e)}"}
                )
            await asyncio.sleep(2)

        logger.error({"message": f"Service at {url} not available after {timeout}s"})
        return False


async def apply_request_delay(ai_identifier: str, role: Optional[str] = None):
    """Applies a random delay based on configuration before making an API request."""
    try:
        # Load fresh config inside function to get latest values
        # Assuming load_config is robust enough or default config exists
        from config import load_config

        config = load_config()
        delay_config = config.get("request_delays", {})

        delay_range = None
        if ai_identifier == "ai2" and role:
            delay_range = delay_config.get("ai2", {}).get(role)
        elif ai_identifier in delay_config:
            delay_range = delay_config.get(ai_identifier)

        if (
            delay_range
            and isinstance(delay_range.get("min"), (int, float))
            and isinstance(delay_range.get("max"), (int, float))
        ):
            min_delay = delay_range["min"]
            max_delay = delay_range["max"]
            if min_delay <= max_delay and min_delay >= 0:  # Ensure valid range
                delay = random.uniform(min_delay, max_delay)
                logger.debug(
                    f"Applying delay for {ai_identifier}{f' ({role})' if role else ''}: {delay:.2f}s"
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    f"Invalid delay range for {ai_identifier}{f' ({role})' if role else ''}: min={min_delay}, max={max_delay}. Skipping delay."
                )
        else:
            # Log only if delays are expected but not configured correctly
            if delay_config:  # Only warn if request_delays section exists
                logger.debug(
                    f"No valid delay configured for {ai_identifier}{f' ({role})' if role else ''}. Skipping delay."
                )
    except Exception as e:
        logger.error(
            f"Error applying request delay: {e}"
        )  # Log error but don't block execution
