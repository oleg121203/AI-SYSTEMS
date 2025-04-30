import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, Optional
# Додаємо імпорт для ротації логів
from logging.handlers import RotatingFileHandler

import aiohttp

# Налаштування структурованого логування в JSON
import json_log_formatter
from dotenv import load_dotenv

# Вантажимо змінні середовища
load_dotenv()

formatter = json_log_formatter.JSONFormatter()

# --- Налаштування для ротації логів ---
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True) # Переконуємося, що директорія існує
LOG_FILE_PATH = os.path.join(LOG_DIR, "mcp.log") # Основний лог файл
MAX_LOG_SIZE_MB = 10 # Максимальний розмір одного файлу логів у МБ
BACKUP_COUNT = 5 # Кількість архівних файлів логів

# Використовуємо RotatingFileHandler замість FileHandler
handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024, # Переводимо МБ в байти
    backupCount=BACKUP_COUNT,
    encoding='utf-8' # Додаємо кодування
)
handler.setFormatter(formatter)

# Налаштовуємо кореневий логер
logger = logging.getLogger()
# Перевіряємо, чи вже є обробники, щоб уникнути дублювання
if not logger.hasHandlers():
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    # Додаємо також вивід у консоль для зручності
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
# --- Кінець змін для ротації логів ---

# Функція log_message тепер буде використовувати налаштований logger
def log_message(message: str):
    """Логирование сообщения с использованием настроенного логгера"""
    # Використовуємо стандартний logging замість ручного запису
    timestamp = datetime.now().isoformat()
    log_data = {"message": message, "time": timestamp}
    logger.info(log_data)

# Створюємо окремі логери для кожного AI сервісу з їх власною ротацією
def setup_service_logger(service_name):
    """
    Створює і налаштовує логер для конкретного сервісу з ротацією файлів логів.
    
    Args:
        service_name: Ім'я сервісу (ai1, ai2_executor, ai2_tester і т.д.)
    
    Returns:
        logging.Logger: Налаштований логер
    """
    log_path = os.path.join(LOG_DIR, f"{service_name}.log")
    service_logger = logging.getLogger(service_name)
    
    # Очищаємо існуючі обробники, щоб уникнути дублікатів при перезавантаженні
    if service_logger.handlers:
        for handler in service_logger.handlers:
            service_logger.removeHandler(handler)
    
    # Налаштовуємо рівень логування
    service_logger.setLevel(logging.INFO)
    service_logger.propagate = False  # Запобігаємо дублюванню логів у батьківському логері
    
    # Створюємо RotatingFileHandler для цього сервісу
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    service_logger.addHandler(file_handler)
    
    # Додаємо також консольний вивід
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    service_logger.addHandler(console)
    
    return service_logger

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

    # Покращений регулярний вираз для пошуку JSON: шукаємо як у блоках коду, так і без них
    # 1. Спочатку шукаємо у блоці ```json ... ```
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)

    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # 2. Якщо немає блоку коду, шукаємо JSON об'єкт або масив напряму
        json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Якщо жоден метод не спрацював, логуємо помилку з оригінальною відповіддю
            logging.error(f"JSON не знайдено у відповіді: {response[:200]}...")
            raise ValueError("JSON не найден в ответе")

    try:
        # Додаємо логування для відлагодження
        logging.debug(f"Extracted JSON string: {json_str[:100]}...")
        result = json.loads(json_str)
        return result
    except json.JSONDecodeError as e:
        # Додаємо більше інформації про помилку і оригінальний рядок
        logging.error(f"Помилка парсингу JSON: {e}. JSON рядок: {json_str[:200]}")
        raise ValueError(f"Ошибка парсинга JSON: {e}")


# --- CHANGE: Add format_code_blocks function ---
def format_code_blocks(text: str) -> str:
    """
    Ensures there is a space after the language identifier in markdown code blocks.
    Example: ```python -> ``` python
    Handles blocks with or without language identifiers.
    """
    # Pattern to find ``` followed by non-whitespace characters (language) and then the code block start
    # It captures the language identifier
    # Backslashes are double-escaped for JSON embedding (\\ becomes \\\\)
    pattern = r"(```)(\\S+)(\\s*\\n)"

    # Replacement function
    def replace_func(match):
        # match.group(1) is ```
        # match.group(2) is the language identifier (e.g., python)
        # match.group(3) is the whitespace/newline after the language
        # Ensure there's a space before the language identifier
        return f"{match.group(1)} {match.group(2)}{match.group(3)}"

    # Apply the substitution
    formatted_text = re.sub(pattern, replace_func, text)

    # Handle code blocks without language identifiers (ensure ``` is followed by newline)
    # This might be less common but good to handle edge cases
    # Backslashes are double-escaped for JSON embedding (\\ becomes \\\\)
    formatted_text = re.sub(r"(```)(?!\\s)(\\S)", r"\\1 \\2", formatted_text)

    return formatted_text
# --- END CHANGE ---


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
            elif "type" in node and node["type"] == "directory":
                 # Это директория
                 dir_name = node.get("name", "")
                 # Construct path correctly, handling root case
                 new_path = os.path.join(current_path, dir_name) if current_path else dir_name
                 if "children" in node and isinstance(node["children"], list):
                     for child in node["children"]:
                         extract_from_node(child, new_path) # Recurse into children
            # Handle root node or other dictionary structures if needed
            # This assumes the structure primarily uses 'type': 'file'/'directory'
            # and nests children within directories.
            else: # If not file or directory, assume it's a container or root
                # Iterate through values assuming they might be file/dir nodes or sub-structures
                for key, value in node.items():
                     # Avoid recursing on simple metadata if structure is mixed
                     if isinstance(value, (dict, list)):
                         # Decide if 'key' should be part of the path - depends on structure definition
                         # Assuming keys are not part of path unless node['name'] is used
                         extract_from_node(value, current_path) # Recurse on value

        elif isinstance(node, list):
             # If the node is a list (e.g., root is a list of items)
             for item in node:
                 extract_from_node(item, current_path)

    # Start the extraction from the root structure
    extract_from_node(structure)
    return files


async def wait_for_service(url: str, timeout: int = 60) -> bool:
    """Waits for a service to become available at the given URL."""
    start_time = time.time()
    logger.info({"message": f"Waiting for service at {url}..."})
    while time.time() - start_time < timeout:
        try:
            async with aiohttp.ClientSession() as session:
                # Use a simple GET or HEAD request to check availability
                async with session.get(url, timeout=5) as response:
                    if response.status < 400: # Consider 2xx/3xx as success
                        logger.info({"message": f"Service at {url} is available."})
                        return True
                    else:
                        logger.debug({"message": f"Service at {url} returned status {response.status}"})
        except aiohttp.ClientConnectorError as e:
             logger.debug({"message": f"Connection attempt to {url} failed: {str(e)}"})
        except aiohttp.ClientError as e: # Catch other client errors like timeouts
            logger.warning({"message": f"Error checking service {url}: {str(e)}"})
        except asyncio.TimeoutError: # Specifically catch asyncio timeouts if session.get raises it
             logger.debug({"message": f"Connection attempt to {url} timed out."})
        except Exception as e:
            logger.warning(
                {"message": f"Unexpected error connecting to {url}: {str(e)}"}
            )
        # Wait before retrying
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
