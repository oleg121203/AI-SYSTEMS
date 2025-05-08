import asyncio
import json
import logging
import os
import random
import re  # Added re import
import signal
import sys
import time
from datetime import datetime

# Додаємо імпорт для ротації логів
from logging.handlers import RotatingFileHandler
from typing import Optional  # Consolidated typing imports
from typing import Any, Dict, List, Set, Tuple, Union

import aiohttp

# Налаштування структурованого логування в JSON
import json_log_formatter
from dotenv import load_dotenv

# Вантажимо змінні середовища
load_dotenv()

GITKEEP_FILENAME = ".gitkeep"  # Define GITKEEP_FILENAME here
MCP_API_URL = "http://localhost:7860"  # Define MCP_API_URL here
REPO_DIR = "repo"  # Define REPO_DIR here

formatter = json_log_formatter.JSONFormatter()

# --- Налаштування для ротації логів ---
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)  # Переконуємося, що директорія існує
LOG_FILE_PATH = os.path.join(LOG_DIR, "mcp.log")  # Основний лог файл
MAX_LOG_SIZE_MB = 10  # Максимальний розмір одного файлу логів у МБ
BACKUP_COUNT = 5  # Кількість архівних файлів логів

# Використовуємо RotatingFileHandler замість FileHandler
handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,  # Переводимо МБ в байти
    backupCount=BACKUP_COUNT,
    encoding="utf-8",  # Додаємо кодування
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
    service_logger.propagate = (
        False  # Запобігаємо дублюванню логів у батьківському логері
    )

    # Створюємо RotatingFileHandler для цього сервісу
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_SIZE_MB * 1024 * 1024,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
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
        format="%(asctime)s - %(name)s - %(levellevel)s - %(message)s",
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

from providers import BaseProvider  # Ensure these are imported
from providers import ProviderFactory

# Global dictionary to track the last API request time for each component.
# This is used for monitoring or potential future rate limiting logic,
# but not for calculating the delay in the revised apply_request_delay.
last_api_request = {}

# The global `delay_settings` is no longer the primary source for `apply_request_delay`.
# It might be used by other functions or can be removed if not.
# For now, we'll leave its definition if it exists, but `apply_request_delay` will fetch its own.
delay_settings = {}


# --- CHANGE: Modify apply_request_delay to fetch fresh config and use random.uniform ---
async def apply_request_delay(identifier: str):
    """
    Apply a random delay based on dynamically loaded configuration before
    making an API request.

    Identifier format examples: 'ai1', 'ai3', 'ai2_executor'
    The function normalizes identifiers like 'ai2_executor_task123' to
    'ai2_executor' for settings lookup.

    Args:
        identifier (str): Component identifier making the request
    """
    global last_api_request

    try:
        # Import config here to ensure latest version is used
        from config import load_config

        # Load the latest config - load_config has its own mtime-based cache
        config_data = load_config()
        loaded_request_delays = config_data.get("request_delays", {})

        # Normalize identifier to component_id used in settings
        # e.g., "ai2_executor_task1" becomes "ai2_executor"
        component_id_for_settings = identifier
        if identifier.startswith("ai2_"):
            parts = identifier.split("_", 2)
            if len(parts) >= 2:
                component_id_for_settings = f"ai2_{parts[1]}"

        # Initialize with default minimal delays
        min_delay = 0.05
        max_delay = 0.1

        # Get settings for this component with a fallback
        default_min_max = {"min_delay": 0.05, "max_delay": 0.1}
        settings = loaded_request_delays.get(component_id_for_settings, default_min_max)

        min_d = settings.get("min_delay", default_min_max["min_delay"])
        max_d = settings.get("max_delay", default_min_max["max_delay"])

        # Validate delay values
        min_d = max(0.0, min_d)  # Ensure min_delay is not negative
        max_d = max(min_d, max_d)  # Ensure max_delay is not less than min_delay

        actual_delay_to_apply = 0.0
        if max_d > 0:  # Only sleep if max_d is positive
            actual_delay_to_apply = random.uniform(min_d, max_d)

        if actual_delay_to_apply > 0:
            logger.debug(
                f"[{identifier} -> {component_id_for_settings}] Applying API "
                f"request delay: {actual_delay_to_apply:.3f}s "
                f"(range: {min_d:.3f}-{max_d:.3f})"
            )
            await asyncio.sleep(actual_delay_to_apply)

        # Record request time for the normalized component_id
        last_api_request[component_id_for_settings] = time.time()

    except Exception as e:
        logger.error(
            f"Error applying request delay for {identifier}: {e}", exc_info=True
        )
        # Apply minimal delay (50-100ms) in case of error
        await asyncio.sleep(random.uniform(0.05, 0.1))


# --- END CHANGE ---


# --- NEW: Add call_llm_provider function ---
async def call_llm_provider(
    provider_name: str,
    prompt: str,
    system_prompt: Optional[str],
    config: Dict,
    ai_config: Dict,
    service_name: str,  # e.g., 'ai1', 'ai2_executor'
    max_tokens_override: Optional[int] = None,
    temperature_override: Optional[float] = None,
) -> Optional[str]:
    """Helper function to initialize and call an LLM provider."""
    provider_instance = None  # Initialize to None
    try:
        logger.info(f"[{service_name.upper()}] Calling provider {provider_name}...")
        # Pass the global config to the factory
        provider_instance: BaseProvider = ProviderFactory.create_provider(
            provider_name, config=config
        )
        # --- CHANGE: Pass single identifier to apply_request_delay ---
        await apply_request_delay(
            service_name
        )  # Apply delay based on service identifier
        # --- END CHANGE ---

        # Determine max_tokens and temperature, allowing overrides
        max_tokens = (
            max_tokens_override
            if max_tokens_override is not None
            else ai_config.get("max_tokens", 4000)
        )
        temperature = (
            temperature_override
            if temperature_override is not None
            else ai_config.get("temperature")
        )

        logger.debug(
            f"[{service_name.upper()}] Using max_tokens={max_tokens}, temperature={temperature}"
        )

        response = await provider_instance.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=ai_config.get(
                "model"
            ),  # Model comes from the specific AI config section
            max_tokens=max_tokens,
            temperature=temperature,
        )
        # Ensure session is closed if the provider has one
        if hasattr(provider_instance, "close_session") and callable(
            provider_instance.close_session
        ):
            await provider_instance.close_session()
            logger.debug(
                f"[{service_name.upper()}] Closed session for provider {provider_name}"
            )
        return response
    except Exception as e:
        logger.error(
            f"[{service_name.upper()}] Error calling provider {provider_name}: {e}",
            exc_info=True,
        )
        # Attempt to close session even if an error occurred during generation
        if (
            provider_instance
            and hasattr(provider_instance, "close_session")
            and callable(provider_instance.close_session)
        ):
            try:
                await provider_instance.close_session()
                logger.debug(
                    f"[{service_name.upper()}] Closed session for provider {provider_name} after error."
                )
            except Exception as close_e:
                logger.error(
                    f"[{service_name.upper()}] Error closing provider session after error: {close_e}"
                )
        return None


# --- END NEW ---


async def process_file_tasks(structure: Dict[str, Any], mcp_api_url: str):
    """
    Функция для обработки задач по созданию файлов

    Args:
        structure: Структура проекта
        mcp_api_url: URL API для MCP
    """
    import aiohttp

    # TODO: Refactor this function to use ProviderFactory from providers.py
    # from llm_provider import LLMProvider
    # llm = LLMProvider()
    # await llm.initialize()
    # Извлекаем файлы из структури
    files = extract_files_from_structure(structure)

    # Создаем задачи для каждого файла
    tasks = []
    for file_path, file_info in files.items():
        task = {
            "file_path": file_path,
            "description": file_info.get("description", ""),
            "contents": "",  # Initially empty, to be filled by AI2
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

    # await llm.close() # Corresponding close for the commented out llm


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
                # Це файл
                file_path = current_path + node.get("name", "")
                files[file_path] = {
                    "description": node.get("description", ""),
                    "template": node.get("template", ""),
                    "code": node.get("code", ""),
                }
            elif "type" in node and node["type"] == "directory":
                # Це директорія
                dir_name = node.get("name", "")
                # Construct path correctly, handling root case
                new_path = (
                    os.path.join(current_path, dir_name) if current_path else dir_name
                )
                if "children" in node and isinstance(node["children"], list):
                    for child in node["children"]:
                        extract_from_node(child, new_path)  # Recurse into children
            # Handle root node or other dictionary structures if needed
            # This assumes the structure primarily uses 'type': 'file'/'directory'
            # and nests children within directories.
            else:  # If not file or directory, assume it's a container or root
                # Iterate through values assuming they might be file/dir nodes or sub-structures
                for key, value in node.items():
                    # Avoid recursing on simple metadata if structure is mixed
                    if isinstance(value, (dict, list)):
                        # Decide if 'key' should be part of the path - depends on structure definition
                        extract_from_node(value, current_path)  # Recurse on value

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
                    if response.status < 400:  # Consider 2xx/3xx as success
                        logger.info({"message": f"Service at {url} is available."})
                        return True
                    else:
                        logger.debug(
                            {
                                "message": f"Service at {url} returned status {response.status}"
                            }
                        )
        except aiohttp.ClientConnectorError as e:
            logger.debug({"message": f"Connection attempt to {url} failed: {str(e)}"})
        except aiohttp.ClientError as e:  # Catch other client errors like timeouts
            logger.warning({"message": f"Error checking service {url}: {str(e)}"})
        except (
            asyncio.TimeoutError
        ):  # Specifically catch asyncio timeouts if session.get raises it
            logger.debug({"message": f"Connection attempt to {url} timed out."})
        except Exception as e:
            logger.warning(
                {"message": f"Unexpected error connecting to {url}: {str(e)}"}
            )
        # Wait before retrying
        await asyncio.sleep(2)

    logger.error({"message": f"Service at {url} not available after {timeout}s"})
    return False


# New automated test execution utilities
import subprocess

# import json # already imported
# import os # already imported
# from typing import Dict, List, Optional, Any, Tuple # already imported
from dataclasses import dataclass

# import logging # already imported
# import re # already imported

test_logger = logging.getLogger("test_execution")


@dataclass
class TestResult:  # This TestResult class might conflict with the one defined later
    """Results from a test execution"""

    file_path: str
    success: bool
    failures: List[str]
    output: str
    error_details: Optional[Dict[str, Any]] = None
    coverage: Optional[float] = None


class TestRunner:  # This TestRunner class might conflict with the one defined later
    """Executes tests and collects detailed results for AI analysis"""

    def __init__(self, repo_dir: str = "repo"):
        self.repo_dir = repo_dir
        self._setup_logger()

    def _setup_logger(self):
        handler = logging.FileHandler("logs/test_execution.log")
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

    def run_tests(self) -> Dict[str, TestResult]:
        """Run all tests in the repository and collect results"""
        test_logger.info("Starting test execution")
        results = {}

        # Run Python tests
        python_results = self._run_python_tests()
        results.update(python_results)

        # Run JavaScript tests
        js_results = self._run_js_tests()
        results.update(js_results)

        # Run web tests (HTML/CSS)
        web_results = self._run_web_tests()
        results.update(web_results)

        # Run other language tests based on file types
        test_logger.info(f"Completed test execution. Total test files: {len(results)}")
        return results

    def _run_python_tests(self) -> Dict[str, TestResult]:
        """Run Python tests with pytest"""
        results = {}
        test_files = self._find_files("*_test.py") + self._find_files("test_*.py")

        if not test_files:
            test_logger.info("No Python test files found")
            return results

        test_logger.info(f"Found {len(test_files)} Python test files")
        for test_file in test_files:
            try:
                result = self._execute_python_test(test_file)
                results[test_file] = result
            except Exception as e:
                test_logger.error(f"Error running Python test {test_file}: {str(e)}")
                results[test_file] = TestResult(
                    file_path=test_file,
                    success=False,
                    failures=[f"Exception: {str(e)}"],
                    output=f"Error: {str(e)}",
                    error_details={"exception": str(e), "type": str(type(e))},
                )

        return results

    def _run_js_tests(self) -> Dict[str, TestResult]:
        """Run JavaScript tests with Jest"""
        results = {}
        test_files = (
            self._find_files("*.test.js")
            + self._find_files("*.spec.js")
            + self._find_files("*.test.jsx")
            + self._find_files("*.test.tsx")
        )

        if not test_files:
            test_logger.info("No JavaScript test files found")
            return results

        test_logger.info(f"Found {len(test_files)} JavaScript test files")
        for test_file in test_files:
            try:
                result = self._execute_js_test(test_file)
                results[test_file] = result
            except Exception as e:
                test_logger.error(
                    f"Error running JavaScript test {test_file}: {str(e)}"
                )
                results[test_file] = TestResult(
                    file_path=test_file,
                    success=False,
                    failures=[f"Exception: {str(e)}"],
                    output=f"Error: {str(e)}",
                    error_details={"exception": str(e), "type": str(type(e))},
                )

        return results

    def _run_web_tests(self) -> Dict[str, TestResult]:
        """Run web tests for HTML/CSS files"""
        results = {}
        html_test_files = self._find_files("*_test.html") + self._find_files(
            "*.test.html"
        )
        css_test_files = self._find_files("*_test.css") + self._find_files("*.test.css")

        test_files = html_test_files + css_test_files
        if not test_files:
            test_logger.info("No web test files found")
            return results

        test_logger.info(f"Found {len(test_files)} web test files")

        # Web tests are typically part of JavaScript test files
        # We'll look for associated JS test files and run them
        for test_file in test_files:
            js_test_file = test_file.replace(".html", ".test.js").replace(
                ".css", ".test.js"
            )
            if os.path.exists(os.path.join(self.repo_dir, js_test_file)):
                try:
                    result = self._execute_js_test(js_test_file)
                    results[test_file] = result
                except Exception as e:
                    test_logger.error(f"Error running web test {test_file}: {str(e)}")
                    results[test_file] = TestResult(
                        file_path=test_file,
                        success=False,
                        failures=[f"Exception: {str(e)}"],
                        output=f"Error: {str(e)}",
                        error_details={"exception": str(e), "type": str(type(e))},
                    )

        return results

    def _execute_python_test(self, test_file: str) -> TestResult:
        """Execute a single Python test file with pytest"""
        full_path = os.path.join(self.repo_dir, test_file)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=test_file,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        test_logger.info(f"Running Python test: {test_file}")
        orig_dir = os.getcwd()
        os.chdir(self.repo_dir)

        try:
            # Run the test with pytest
            process = subprocess.run(
                ["python", "-m", "pytest", test_file, "-v"],
                capture_output=True,
                text=True,
            )

            output = process.stdout + process.stderr
            success = process.returncode == 0

            # Parse failures from output
            failures = []
            if not success:
                failure_pattern = r"FAILED\s+(.*?::.*?)\s+"
                matches = re.findall(failure_pattern, output)
                failures = (
                    matches
                    if matches
                    else ["Test failed but couldn't parse specific failure"]
                )

            return TestResult(
                file_path=test_file,
                success=success,
                failures=failures,
                output=output,
                coverage=self._extract_python_coverage(output),
            )

        finally:
            os.chdir(orig_dir)

    def _execute_js_test(self, test_file: str) -> TestResult:
        """Execute a single JavaScript test file with Jest"""
        full_path = os.path.join(self.repo_dir, test_file)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=test_file,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        test_logger.info(f"Running JavaScript test: {test_file}")
        orig_dir = os.getcwd()
        os.chdir(self.repo_dir)

        try:
            # Run the test with Jest
            process = subprocess.run(
                ["npx", "jest", test_file, "--no-cache"], capture_output=True, text=True
            )

            output = process.stdout + process.stderr
            success = process.returncode == 0

            # Parse failures from output
            failures = []
            if not success:
                # Look for the specific error in the output
                if "FAIL" in output:
                    # Extract the lines following FAIL until the next test or summary
                    fail_sections = re.findall(
                        r"FAIL.*?(?=PASS|FAIL|Summary|$)", output, re.DOTALL
                    )
                    for section in fail_sections:
                        failures.append(section.strip())

                if not failures:
                    failures = ["Test failed but couldn't parse specific failure"]

            return TestResult(
                file_path=test_file,
                success=success,
                failures=failures,
                output=output,
                coverage=self._extract_js_coverage(output),
            )

        finally:
            os.chdir(orig_dir)

    def _extract_python_coverage(self, output: str) -> Optional[float]:
        """Extract coverage percentage from pytest output"""
        coverage_pattern = r"TOTAL\s+.*?\s+(\d+)%"
        match = re.search(coverage_pattern, output)
        if match:
            return float(match.group(1))
        return None

    def _extract_js_coverage(self, output: str) -> Optional[float]:
        """Extract coverage percentage from Jest output"""
        coverage_pattern = r"All files.*?\|.*?\|.*?\|.*?\|.*?\|\s+(\d+\.?\d*).*?\|"
        match = re.search(coverage_pattern, output)
        if match:
            return float(match.group(1))
        return None

    def _find_files(self, pattern: str) -> List[str]:
        """Find files matching a pattern in the repo directory"""
        import glob

        orig_dir = os.getcwd()
        os.chdir(self.repo_dir)
        try:
            # Use relative paths within the repo directory
            matches = glob.glob("**/" + pattern, recursive=True)
            return matches
        finally:
            os.chdir(orig_dir)

    def run_linters(self) -> Dict[str, TestResult]:
        """Run linters on all files in the repository"""
        results = {}

        # Run Python linters
        python_files = self._find_files("*.py")
        for file_path in python_files:
            result = self._run_python_linter(file_path)
            results[file_path] = result

        # Run JavaScript linters
        js_files = (
            self._find_files("*.js")
            + self._find_files("*.jsx")
            + self._find_files("*.tsx")
        )
        for file_path in js_files:
            result = self._run_js_linter(file_path)
            results[file_path] = result

        # Run HTML linters
        html_files = self._find_files("*.html") + self._find_files("*.htm")
        for file_path in html_files:
            result = self._run_html_linter(file_path)
            results[file_path] = result

        # Run CSS linters
        css_files = self._find_files("*.css") + self._find_files("*.scss")
        for file_path in css_files:
            result = self._run_css_linter(file_path)
            results[file_path] = result

        return results

    def _run_python_linter(self, file_path: str) -> TestResult:
        """Run flake8 on Python file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        try:
            # Run flake8
            process = subprocess.run(
                ["flake8", full_path], capture_output=True, text=True
            )

            output = process.stdout + process.stderr
            success = process.returncode == 0

            # Parse failures from output
            failures = []
            if not success:
                failures = [
                    line.strip() for line in output.splitlines() if line.strip()
                ]

            return TestResult(
                file_path=file_path, success=success, failures=failures, output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}",
            )

    def _run_js_linter(self, file_path: str) -> TestResult:
        """Run eslint on JavaScript file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        try:
            # Run eslint
            # First ensure .eslintrc.json exists
            eslint_config = os.path.join(self.repo_dir, ".eslintrc.json")
            if not os.path.exists(eslint_config):
                with open(eslint_config, "w") as f:
                    f.write(
                        '{"extends": ["eslint:recommended"], "parserOptions": {"ecmaVersion": 2020}, "env": {"browser": true, "node": true, "es6": true}}'
                    )

            process = subprocess.run(
                ["eslint", full_path, "--no-eslintrc", "--config", eslint_config],
                capture_output=True,
                text=True,
            )

            output = process.stdout + process.stderr
            success = process.returncode == 0

            # Parse failures from output
            failures = []
            if not success:
                failures = [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip() and not line.startswith("eslint:")
                ]

            return TestResult(
                file_path=file_path, success=success, failures=failures, output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}",
            )

    def _run_html_linter(self, file_path: str) -> TestResult:
        """Run htmlhint on HTML file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        try:
            # Run htmlhint
            # First ensure .htmlhintrc exists
            htmlhint_config = os.path.join(self.repo_dir, ".htmlhintrc")
            if not os.path.exists(htmlhint_config):
                with open(htmlhint_config, "w") as f:
                    f.write(
                        '{"tagname-lowercase": true, "attr-lowercase": true, "attr-value-double-quotes": true, "doctype-first": false, "tag-pair": true, "spec-char-escape": true, "id-unique": true, "src-not-empty": true, "attr-no-duplication": true, "title-require": true}'
                    )

            process = subprocess.run(
                ["htmlhint", full_path], capture_output=True, text=True
            )

            output = process.stdout + process.stderr
            success = "no error" in output.lower()

            # Parse failures from output
            failures = []
            if not success:
                failure_lines = [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip() and "error" in line.lower()
                ]
                failures = (
                    failure_lines if failure_lines else ["HTML validation errors found"]
                )

            return TestResult(
                file_path=file_path, success=success, failures=failures, output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}",
            )

    def _run_css_linter(self, file_path: str) -> TestResult:
        """Run stylelint on CSS file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error",
            )

        try:
            # Run stylelint
            # First ensure .stylelintrc.json exists
            stylelint_config = os.path.join(self.repo_dir, ".stylelintrc.json")
            if not os.path.exists(stylelint_config):
                with open(stylelint_config, "w") as f:
                    if file_path.endswith(".scss"):
                        f.write(
                            '{"extends": "stylelint-config-standard", "plugins": ["stylelint-scss"]}'
                        )
                    else:
                        f.write('{"extends": "stylelint-config-standard"}')

            process = subprocess.run(
                ["stylelint", full_path], capture_output=True, text=True
            )

            output = process.stdout + process.stderr
            success = process.returncode == 0

            # Parse failures from output
            failures = []
            if not success:
                failures = [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip() and file_path in line
                ]

            return TestResult(
                file_path=file_path, success=success, failures=failures, output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}",
            )

    def generate_test_report(
        self, test_results: Dict[str, TestResult]
    ) -> Dict[str, Any]:
        """Generate a comprehensive test report for AI consumption"""
        total_tests = len(test_results)
        successful_tests = sum(1 for result in test_results.values() if result.success)
        failed_tests = total_tests - successful_tests

        # Group failures by file type
        failures_by_type = {}
        for file_path, result in test_results.items():
            if not result.success:
                file_ext = os.path.splitext(file_path)[1]
                if file_ext not in failures_by_type:
                    failures_by_type[file_ext] = []
                failures_by_type[file_ext].append(
                    {"file": file_path, "failures": result.failures}
                )

        # Generate actionable insights
        insights = self._generate_insights(test_results)

        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": {
                "total_tests": total_tests,
                "successful_tests": successful_tests,
                "failed_tests": failed_tests,
                "success_rate": (
                    (successful_tests / total_tests) * 100 if total_tests > 0 else 0
                ),
            },
            "failures_by_type": failures_by_type,
            "insights": insights,
            "detailed_results": {
                file_path: {
                    "success": result.success,
                    "failures": result.failures,
                    "coverage": result.coverage,
                }
                for file_path, result in test_results.items()
            },
        }

        # Save report to a file in JSON format
        os.makedirs("test_reports", exist_ok=True)
        report_path = f"test_reports/test_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        test_logger.info(f"Test report generated and saved to {report_path}")
        return report

    def _generate_insights(self, test_results: Dict[str, TestResult]) -> List[str]:
        """Generate actionable insights from test results"""
        insights = []

        # Pattern analysis on failures
        common_errors = self._identify_common_errors(test_results)
        for error_type, count in common_errors.items():
            if count > 1:
                insights.append(
                    f"Common error pattern found: '{error_type}' appears in {count} tests"
                )

        # Look for files with no tests
        if (
            self._find_files("*.py")
            and not self._find_files("*_test.py")
            and not self._find_files("test_*.py")
        ):
            insights.append("Python application files found but no Python tests exist")

        if (
            self._find_files("*.js")
            and not self._find_files("*.test.js")
            and not self._find_files("*.spec.js")
        ):
            insights.append("JavaScript files found but no JavaScript tests exist")

        # Check test coverage
        low_coverage_files = []
        for file_path, result in test_results.items():
            if result.coverage is not None and result.coverage < 50:
                low_coverage_files.append(file_path)

        if low_coverage_files:
            insights.append(
                f"Low test coverage (<50%) found in {len(low_coverage_files)} files"
            )

        # Check for failing tests
        failing_files = [
            file_path
            for file_path, result in test_results.items()
            if not result.success
        ]
        if failing_files:
            insights.append(
                f"Found {len(failing_files)} failing test files that need fixing"
            )

        return insights

    def _identify_common_errors(
        self, test_results: Dict[str, TestResult]
    ) -> Dict[str, int]:
        """Identify common error patterns in test failures"""
        error_patterns = {}

        for result in test_results.values():
            if not result.success:
                for failure in result.failures:
                    # Extract key parts of error messages
                    if "import" in failure and "error" in failure.lower():
                        error_patterns["Import Error"] = (
                            error_patterns.get("Import Error", 0) + 1
                        )
                    elif "undefined" in failure.lower():
                        error_patterns["Undefined Reference"] = (
                            error_patterns.get("Undefined Reference", 0) + 1
                        )
                    elif (
                        "assertionerror" in failure.lower()
                        or "assert" in failure.lower()
                    ):
                        error_patterns["Assertion Failure"] = (
                            error_patterns.get("Assertion Failure", 0) + 1
                        )
                    elif "syntax" in failure.lower():
                        error_patterns["Syntax Error"] = (
                            error_patterns.get("Syntax Error", 0) + 1
                        )
                    elif "type" in failure.lower() and "error" in failure.lower():
                        error_patterns["Type Error"] = (
                            error_patterns.get("Type Error", 0) + 1
                        )

        return error_patterns


def get_original_file_from_test(test_file: str) -> Optional[str]:
    """Determine the original file path based on the test file path"""
    dir_name = os.path.dirname(test_file)
    base_name = os.path.basename(test_file)
    file_ext = os.path.splitext(test_file)[1]

    # Python test conventions
    if base_name.startswith("test_"):
        original_name = base_name[5:]
        if dir_name.endswith("/tests") or dir_name.endswith("\\tests"):
            # Check if this is in a tests directory and adjust path
            return os.path.join(
                dir_name.replace("/tests", "").replace("\\tests", ""), original_name
            )
        else:
            return os.path.join(dir_name, original_name)

    # JavaScript test conventions
    elif ".test" in base_name:
        original_name = base_name.replace(".test", "")
        if dir_name.endswith("/tests") or dir_name.endswith("\\tests"):
            return os.path.join(
                dir_name.replace("/tests", "").replace("\\tests", ""), original_name
            )
        else:
            return os.path.join(dir_name, original_name)

    # Python test suffix
    elif base_name.endswith("_test.py"):
        original_name = base_name[:-8] + ".py"
        if dir_name.endswith("/tests") or dir_name.endswith("\\tests"):
            return os.path.join(
                dir_name.replace("/tests", "").replace("\\tests", ""), original_name
            )
        else:
            return os.path.join(dir_name, original_name)

    return None


import asyncio
import json
import logging
import os
import re
import subprocess
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Налаштування логування
logger = logging.getLogger("utils")


# Додавання класу для аналізу результатів тестування
@dataclass
class TestResult:
    success: bool
    failures: List[str]
    output: str
    file_path: str
    coverage: Optional[float] = None
    execution_time: float = 0.0
    retry_count: int = 0

    def get_failure_summary(self) -> str:
        """Повертає стислий опис помилок"""
        if not self.failures:
            return "No failures"

        return "\n".join(self.failures[:5]) + (
            f"\n... and {len(self.failures) - 5} more issues"
            if len(self.failures) > 5
            else ""
        )

    def to_dict(self) -> dict:
        """Конвертує результат у словник для серіалізації"""
        return {
            "success": self.success,
            "failures": self.failures,
            "output_length": len(self.output),
            "file_path": self.file_path,
            "coverage": self.coverage,
            "execution_time": self.execution_time,
            "retry_count": self.retry_count,
        }


class TestRunner:
    """Клас для автоматичного запуску та аналізу результатів тестування"""

    def __init__(self, repo_dir: str):
        self.repo_dir = repo_dir
        self.test_files_map = {}  # Кеш відповідності між файлами коду та тестами
        self.test_history = {}  # Історія запусків тестів
        self.max_retries = 3  # Максимальна кількість повторних спроб

    def find_test_files(self) -> List[str]:
        """Знаходить всі файли тестів у репозиторії"""
        test_files = []

        for root, _, files in os.walk(self.repo_dir):
            for file in files:
                if self._is_test_file(file):
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_dir)
                    test_files.append(rel_path)

        logger.info(f"[TestRunner] Found {len(test_files)} test files")
        return test_files

    def find_implementation_files(self) -> List[str]:
        """Знаходить всі файли з кодом реалізації у репозиторії"""
        impl_files = []

        excluded_dirs = {"__pycache__", "node_modules", ".git", "venv", "env", ".env"}

        for root, dirs, files in os.walk(self.repo_dir):
            # Пропускаємо виключені директорії
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for file in files:
                if self._is_implementation_file(file) and not self._is_test_file(file):
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_dir)
                    impl_files.append(rel_path)

        logger.info(f"[TestRunner] Found {len(impl_files)} implementation files")
        return impl_files

    def map_tests_to_implementation(self) -> Dict[str, List[str]]:
        """Створює відображення між файлами реалізації та тестами"""
        if self.test_files_map:
            return self.test_files_map

        test_files = self.find_test_files()
        impl_files = self.find_implementation_files()

        result = {}

        for impl_file in impl_files:
            impl_name = os.path.basename(impl_file)
            impl_name_no_ext = os.path.splitext(impl_name)[0]
            impl_dir = os.path.dirname(impl_file)

            matching_tests = []

            # Пошук тестів за різними патернами
            for test_file in test_files:
                test_name = os.path.basename(test_file)
                test_dir = os.path.dirname(test_file)

                # Паттерн 1: test_file.py або file_test.py
                if test_name.startswith(f"test_{impl_name}") or test_name.startswith(
                    f"{impl_name_no_ext}_test"
                ):
                    matching_tests.append(test_file)

                # Паттерн 2: tests/file.py для impl/file.py
                elif test_name == impl_name and (
                    "test" in test_dir.lower() or "spec" in test_dir.lower()
                ):
                    matching_tests.append(test_file)

                # Паттерн 3: tests/prefix/file_test.py для prefix/file.py
                elif test_dir.endswith("tests") and impl_dir not in ["tests", "test"]:
                    if impl_name_no_ext in test_name:
                        matching_tests.append(test_file)

            # Якщо знайдено відповідні тести, додаємо запис
            if matching_tests:
                result[impl_file] = matching_tests

        self.test_files_map = result
        logger.info(
            f"[TestRunner] Created test-to-implementation map with {len(result)} entries"
        )
        return result

    def run_tests(
        self, specific_files: List[str] = None, retry_failed: bool = True
    ) -> Dict[str, TestResult]:
        """Запускає всі або вказані тести і повертає результати"""
        test_files = specific_files if specific_files else self.find_test_files()
        results = {}

        for test_file in test_files:
            # Пропускаємо файли, що не є тестами
            if not self._is_test_file(os.path.basename(test_file)):
                continue

            abs_path = os.path.join(self.repo_dir, test_file)
            if not os.path.exists(abs_path):
                logger.warning(f"[TestRunner] Test file does not exist: {abs_path}")
                continue

            # Запускаємо тест з можливими повторними спробами
            result = self._run_single_test(
                test_file,
                retry_count=0,
                max_retries=self.max_retries if retry_failed else 0,
            )
            results[test_file] = result

            # Зберігаємо в історії
            if test_file not in self.test_history:
                self.test_history[test_file] = []
            self.test_history[test_file].append(
                {"timestamp": datetime.now().isoformat(), "result": result.to_dict()}
            )

        return results

    def _run_single_test(
        self, test_file: str, retry_count: int = 0, max_retries: int = 3
    ) -> TestResult:
        """Запускає один тест з можливими повторними спробами при помилках"""
        start_time = time.time()
        abs_path = os.path.join(self.repo_dir, test_file)
        ext = os.path.splitext(test_file)[1].lower()

        try:
            # Вибір команди залежно від типу файлу
            command = self._get_test_command(test_file)

            # Запуск команди
            logger.info(
                f"[TestRunner] Running test: {test_file} with command: {command}"
            )
            process = subprocess.run(
                command,
                shell=True,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 хвилин максимум
            )

            execution_time = time.time() - start_time
            output = process.stdout + "\n" + process.stderr

            # Аналіз результатів
            success = process.returncode == 0
            failures = []

            # Якщо тест не пройшов, витягаємо інформацію про помилки
            if not success:
                failures = self._extract_failures(output, test_file)
                logger.warning(
                    f"[TestRunner] Test {test_file} failed with {len(failures)} failures"
                )

                # Спроба запустити ще раз, якщо дозволено
                if retry_count < max_retries:
                    logger.info(
                        f"[TestRunner] Retrying test {test_file}, attempt {retry_count + 1}/{max_retries}"
                    )
                    return self._run_single_test(
                        test_file, retry_count + 1, max_retries
                    )

            # Отримання покриття тестами, якщо можливо
            coverage = self._extract_coverage(output)

            return TestResult(
                success=success,
                failures=failures,
                output=output,
                file_path=test_file,
                coverage=coverage,
                execution_time=execution_time,
                retry_count=retry_count,
            )

        except subprocess.TimeoutExpired:
            logger.error(f"[TestRunner] Test {test_file} timed out after 300 seconds")
            return TestResult(
                success=False,
                failures=["Test execution timed out after 300 seconds"],
                output="TIMEOUT",
                file_path=test_file,
                execution_time=300.0,
                retry_count=retry_count,
            )
        except Exception as e:
            logger.error(
                f"[TestRunner] Error running test {test_file}: {e}", exc_info=True
            )
            return TestResult(
                success=False,
                failures=[f"Error executing test: {str(e)}"],
                output=traceback.format_exc(),
                file_path=test_file,
                execution_time=time.time() - start_time,
                retry_count=retry_count,
            )

    def run_linters(self, specific_files: List[str] = None) -> Dict[str, TestResult]:
        """Запускає лінтинг для всіх або вказаних файлів"""
        impl_files = (
            specific_files if specific_files else self.find_implementation_files()
        )
        results = {}

        for file_path in impl_files:
            abs_path = os.path.join(self.repo_dir, file_path)
            if not os.path.exists(abs_path):
                logger.warning(f"[TestRunner] File does not exist: {abs_path}")
                continue

            ext = os.path.splitext(file_path)[1].lower()

            # Вибір лінтера за типом файлу
            lint_command = None
            if ext == ".py":
                lint_command = f"flake8 {abs_path}"
            elif ext in [".js", ".jsx", ".ts", ".tsx"]:
                lint_command = f"npx eslint {abs_path}"
            elif ext in [".go"]:
                lint_command = f"golint {abs_path}"
            elif ext in [".rs"]:
                lint_command = f"cargo clippy --manifest-path={os.path.join(self.repo_dir, 'Cargo.toml')} -- -D warnings"

            if not lint_command:
                logger.info(f"[TestRunner] No linter available for {file_path}")
                continue

            try:
                # Запуск лінтера
                logger.info(f"[TestRunner] Running linter: {lint_command}")
                start_time = time.time()
                process = subprocess.run(
                    lint_command,
                    shell=True,
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                execution_time = time.time() - start_time
                output = process.stdout + "\n" + process.stderr

                # Аналіз результатів
                success = process.returncode == 0
                failures = []

                # Якщо лінтинг знайшов проблеми
                if not success:
                    failures = self._extract_lint_failures(output, file_path)
                    logger.warning(
                        f"[TestRunner] Linting {file_path} found {len(failures)} issues"
                    )

                results[file_path] = TestResult(
                    success=success,
                    failures=failures,
                    output=output,
                    file_path=file_path,
                    execution_time=execution_time,
                )

            except subprocess.TimeoutExpired:
                logger.error(
                    f"[TestRunner] Linting {file_path} timed out after 60 seconds"
                )
                results[file_path] = TestResult(
                    success=False,
                    failures=["Linting timed out after 60 seconds"],
                    output="TIMEOUT",
                    file_path=file_path,
                    execution_time=60.0,
                )
            except Exception as e:
                logger.error(f"[TestRunner] Error running linter for {file_path}: {e}")
                results[file_path] = TestResult(
                    success=False,
                    failures=[f"Error running linter: {str(e)}"],
                    output=traceback.format_exc(),
                    file_path=file_path,
                    execution_time=time.time() - start_time,
                )

        return results

    def generate_test_report(
        self, test_results: Dict[str, TestResult]
    ) -> Dict[str, Any]:
        """Генерує детальний звіт про результати тестування"""
        total_tests = len(test_results)
        passed_tests = sum(1 for result in test_results.values() if result.success)
        failed_tests = total_tests - passed_tests

        total_execution_time = sum(
            result.execution_time for result in test_results.values()
        )
        avg_coverage = 0
        coverage_count = 0

        for result in test_results.values():
            if result.coverage is not None:
                avg_coverage += result.coverage
                coverage_count += 1

        if coverage_count > 0:
            avg_coverage /= coverage_count

        # Збір інсайтів
        insights = []

        # Інсайт: Проблемні модулі (найбільше невдач)
        if failed_tests > 0:
            failed_modules = {}
            for file_path, result in test_results.items():
                if not result.success:
                    module = os.path.dirname(file_path) or "root"
                    failed_modules[module] = failed_modules.get(module, 0) + 1

            most_problematic = sorted(
                failed_modules.items(), key=lambda x: x[1], reverse=True
            )[:3]
            if most_problematic:
                insights.append(
                    f"Most problematic modules: "
                    + ", ".join(
                        [
                            f"{module} ({count} failed tests)"
                            for module, count in most_problematic
                        ]
                    )
                )

        # Інсайт: Низьке покриття коду
        if avg_coverage < 50 and coverage_count > 0:
            insights.append(
                f"Low test coverage detected: {avg_coverage:.2f}%. Consider adding more tests."
            )

        # Інсайт: Повільні тести
        slow_tests = [
            (path, result.execution_time)
            for path, result in test_results.items()
            if result.execution_time > 5.0
        ]
        if slow_tests:
            slow_tests.sort(key=lambda x: x[1], reverse=True)
            insights.append(
                f"Slow tests detected: "
                + ", ".join([f"{path} ({time:.2f}s)" for path, time in slow_tests[:3]])
            )

        # Інсайт: Часті повторні спроби
        tests_with_retries = [
            (path, result.retry_count)
            for path, result in test_results.items()
            if result.retry_count > 0
        ]
        if tests_with_retries:
            insights.append(
                f"Unstable tests (required retries): "
                + ", ".join(
                    [
                        f"{path} ({retries} retries)"
                        for path, retries in tests_with_retries[:3]
                    ]
                )
            )

        # Загальний звіт
        return {
            "summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "failed_tests": failed_tests,
                "pass_rate": (
                    (passed_tests / total_tests * 100) if total_tests > 0 else 0
                ),
                "total_execution_time": total_execution_time,
                "average_coverage": avg_coverage if coverage_count > 0 else None,
            },
            "tests": {path: result.to_dict() for path, result in test_results.items()},
            "insights": insights,
            "timestamp": datetime.now().isoformat(),
        }

    def _is_test_file(self, filename: str) -> bool:
        """Визначає, чи є файл тестовим"""
        filename_lower = filename.lower()
        return (
            filename_lower.startswith("test_")
            or filename_lower.endswith("_test.py")
            or filename_lower.endswith(".test.js")
            or filename_lower.endswith("_test.go")
            or filename_lower.endswith("_test.rs")
            or filename_lower.endswith("test.cpp")
            or filename_lower.endswith("test.java")
            or "test" in filename_lower
            and (
                filename_lower.endswith(".py")
                or filename_lower.endswith(".js")
                or filename_lower.endswith(".jsx")
                or filename_lower.endswith(".ts")
                or filename_lower.endswith(".tsx")
                or filename_lower.endswith(".go")
                or filename_lower.endswith(".rs")
                or filename_lower.endswith(".cpp")
                or filename_lower.endswith(".java")
            )
        )

    def _is_implementation_file(self, filename: str) -> bool:
        filename_lower = filename.lower()  # Define filename_lower
        return (
            filename_lower.endswith(".py")
            or filename_lower.endswith(".js")
            or filename_lower.endswith(".jsx")
            or filename_lower.endswith(".ts")
            or filename_lower.endswith(".tsx")
            or filename_lower.endswith(".go")
            or filename_lower.endswith(".rs")
            or filename_lower.endswith(".cpp")
            or filename_lower.endswith(".hpp")
            or filename_lower.endswith(".c")  # Fixed "або" to "or"
            or filename_lower.endswith(".h")  # Fixed "або" to "or"
            or filename_lower.endswith(
                ".java"
            )  # Fixed "або" to "or" and removed trailing "or"
        )  # Added closing parenthesis

    def _get_test_command(self, test_file: str) -> str:
        """Повертає відповідну команду для запуску тесту"""
        abs_path = os.path.join(self.repo_dir, test_file)
        ext = os.path.splitext(test_file)[1].lower()

        if ext == ".py":
            return f"cd {self.repo_dir} && python -m pytest {test_file} -v"
        elif ext in [".js", ".jsx"]:
            if os.path.exists(os.path.join(self.repo_dir, "package.json")):
                # Спробуємо виявити фреймворк з package.json
                with open(os.path.join(self.repo_dir, "package.json"), "r") as f:
                    try:
                        package_data = json.load(f)
                        deps = {
                            **package_data.get("dependencies", {}),
                            **package_data.get("devDependencies", {}),
                        }

                        if "jest" in deps:
                            return f"cd {self.repo_dir} && npx jest {test_file}"
                        elif "mocha" in deps:
                            return f"cd {self.repo_dir} && npx mocha {test_file}"
                    except json.JSONDecodeError:
                        pass

            # За замовчуванням
            return f"cd {self.repo_dir} && npx jest {test_file}"
        elif ext in [".ts", ".tsx"]:
            return f"cd {self.repo_dir} && npx jest {test_file} --testTimeout=10000"
        elif ext == ".go":
            return f"cd {os.path.dirname(abs_path)} && go test -v"
        elif ext == ".rs":
            return f"cd {self.repo_dir} && cargo test --test {os.path.basename(test_file).split('.')[0]}"

        # Якщо тип файлу не визначено, використовуємо універсальний підхід
        return f"cd {os.path.dirname(abs_path)} && ./{os.path.basename(abs_path)}"

    def _extract_failures(self, output: str, test_file: str) -> List[str]:
        """Вилучає детальну інформацію про помилки з виводу тесту"""
        ext = os.path.splitext(test_file)[1].lower()
        failures = []

        if ext == ".py":
            # Для pytest
            for line in output.split("\n"):
                if "FAILED" in line or "Error" in line:
                    failures.append(line.strip())
                elif "E       " in line:  # Рядки очікуваних/фактичних значень у pytest
                    failures.append(line.strip())

        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            # Для Jest/Mocha
            error_block = False
            for line in output.split("\n"):
                if "● " in line and ("fail" in line.lower() or "error" in line.lower()):
                    error_block = True
                    failures.append(line.strip())
                elif (
                    error_block
                    and line.strip().startswith("Expected")
                    or line.strip().startswith("Received")
                ):
                    failures.append(line.strip())
                elif error_block and line.strip() == "":
                    error_block = False

        elif ext == ".go":
            # Для Go tests
            for line in output.split("\n"):
                if "FAIL:" in line or "panic:" in line:
                    failures.append(line.strip())

        elif ext == ".rs":
            # Для Rust tests
            for line in output.split("\n"):
                if "thread" in line and "panicked" in line:
                    failures.append(line.strip())

        # Якщо жодних специфічних помилок не знайдено, додаємо загальну
        if not failures and "error" in output.lower():
            # Шукаємо рядки з помилками
            for line in output.split("\n"):
                if (
                    "error" in line.lower()
                    or "exception" in line.lower()
                    or "fail" in line.lower()
                ):
                    failures.append(line.strip())
                    if len(failures) >= 10:  # Обмежуємо кількість
                        break

        return failures

    def _extract_lint_failures(self, output: str, file_path: str) -> List[str]:
        """Вилучає детальну інформацію про проблеми лінтингу"""
        ext = os.path.splitext(file_path)[1].lower()
        failures = []

        if ext == ".py":
            # Для flake8
            for line in output.split("\n"):
                if file_path in line and ":" in line:
                    failures.append(line.strip())

        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            # Для ESLint
            for line in output.split("\n"):
                if file_path in line and (
                    "error" in line.lower() or "warning" in line.lower()
                ):
                    failures.append(line.strip())

        elif ext == ".go":
            # Для golint
            for line in output.split("\n"):
                if file_path in line:
                    failures.append(line.strip())

        elif ext == ".rs":
            # Для clippy
            in_file_section = False
            for line in output.split("\n"):
                if file_path in line:
                    in_file_section = True
                    failures.append(line.strip())
                elif in_file_section and (
                    line.strip().startswith("warning:")
                    or line.strip().startswith("error:")
                ):
                    failures.append(line.strip())
                elif in_file_section and line.strip() == "":
                    in_file_section = False

        return failures

    def _extract_coverage(self, output: str) -> Optional[float]:
        """Спроба вилучити інформацію про покриття тестами з виводу"""
        coverage_patterns = [
            r"coverage: (\d+\.\d+)%",  # pytest-cov формат
            r"All files[^\n]+\|[^\n]+\|[^\n]+\|[^\n]+\|[^\n]+\| (\d+\.\d+)",  # jest формат
            r"total:\s+\(statements\)\s+(\d+\.\d+)%",  # інший формат
        ]

        for pattern in coverage_patterns:
            match = re.search(pattern, output)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass

        return None


# Функція для затримки запитів до API
async def apply_request_delay(system_id: str):
    """Applies configured delay between API requests to avoid rate limiting."""
    from config import load_config

    config = load_config()
    delay_key = f"{system_id}_api_request_delay"
    delay = config.get(delay_key, 0)

    if delay > 0:
        await asyncio.sleep(delay)


# Функція для запису в лог
def log_message(msg: str):
    """Logs a message with a timestamp."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    logging.info(msg)


# --- NEW: Add wait_for_service function ---
async def wait_for_service(service_url: str, timeout: int = 60) -> bool:
    """Wait for a service to become available by polling its URL.

    Args:
        service_url: The URL of the service to check
        timeout: Maximum time to wait in seconds

    Returns:
        bool: True if service became available, False if timeout occurred
    """
    import asyncio
    import logging
    import time

    import aiohttp

    logger = logging.getLogger("AI3")
    logger.info(f"[AI3] Waiting for service at {service_url} (timeout: {timeout}s)")
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        while time.time() - start_time < timeout:
            try:
                async with session.get(service_url, timeout=5) as response:
                    if response.status == 200:
                        logger.info(f"[AI3] Service at {service_url} is available")
                        return True
                    else:
                        logger.debug(
                            f"[AI3] Service check: Status {response.status} from {service_url}"
                        )
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ):
                pass  # Expected during startup, don't log each failure
            except Exception as e:
                logger.debug(f"[AI3] Error checking service: {e}")

            # Check every second
            await asyncio.sleep(1)

    logger.warning(
        f"[AI3] Timeout waiting for service at {service_url} after {timeout}s"
    )
    return False


# --- END NEW ---

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levellevel)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mcp.log"),
    ],
)
logger = logging.getLogger("utils")

# Global delay settings and timing tracking
last_api_request = {}
delay_settings = {}


def log_message(message: str):
    """Log a message with timestamp."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}")
    logger.info(message)


async def apply_request_delay(component_id: str):
    """
    Apply a delay before making an API request to prevent overloading services.

    Args:
        component_id: Identifier for the component making the request (e.g., "ai1", "ai2_executor")
    """
    global last_api_request, delay_settings

    # Default delay of 1 second if no settings provided
    min_delay = delay_settings.get(component_id, {}).get("min_delay", 1.0)

    # Check when the last request was made by this component
    last_time = last_api_request.get(component_id, 0)
    current_time = time.time()
    elapsed = current_time - last_time

    # If not enough time has elapsed, wait
    if elapsed < min_delay:
        delay_needed = min_delay - elapsed
        logger.debug(
            f"[{component_id}] Applying API request delay: {delay_needed:.2f}s"
        )
        await asyncio.sleep(delay_needed)

    # Update the last request time
    last_api_request[component_id] = time.time()


def load_delay_settings(config_data: Dict):
    """Load delay settings from config data."""
    global delay_settings

    delay_config = config_data.get("api_delay_settings", {})
    for component, settings in delay_config.items():
        if isinstance(settings, dict) and "min_delay" in settings:
            delay_settings[component] = settings
        elif isinstance(settings, (int, float)):
            # If it's just a number, use it as min_delay
            delay_settings[component] = {"min_delay": float(settings)}

    logger.info(f"Loaded API delay settings for {len(delay_settings)} components")


class SystemMonitor:
    """Monitors system health and manages process recovery"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.process_info = {}
        self.health_checks = {}
        self.recovery_attempts = {}
        self.max_recovery_attempts = self.config.get("monitor", {}).get(
            "max_recovery_attempts", 3
        )
        self.check_interval = self.config.get("monitor", {}).get(
            "check_interval", 60
        )  # seconds
        self.is_running = False
        # Add a flag to track if notification has been sent
        self.notification_sent = {}
        # Add metrics tracking
        self.metrics = {
            "total_recoveries": 0,
            "recovery_by_component": {},
            "last_check_time": 0,
            "uptime_percentage": {},
        }

    def _load_config(self) -> Dict:
        """Load configuration from file"""
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            log_message(f"[SystemMonitor] Error loading config: {e}")
            return {}

    async def start(self):
        """Start the system monitoring loop"""
        self.is_running = True
        log_message("[SystemMonitor] Starting system health monitoring")

        try:
            # Initial process status check
            self._update_process_status()
            self.metrics["last_check_time"] = time.time()

            # Initialize uptime metrics
            for component in self.process_info:
                self.metrics["uptime_percentage"][component] = 100.0
                self.notification_sent[component] = False

            # Main monitoring loop
            while self.is_running:
                await self._check_health()
                current_time = time.time()
                # Update uptime metrics
                time_diff = current_time - self.metrics["last_check_time"]
                self.metrics["last_check_time"] = current_time

                # Update uptime metrics for each component
                for component, info in self.process_info.items():
                    if component not in self.metrics["uptime_percentage"]:
                        self.metrics["uptime_percentage"][component] = 100.0

                    # Adjust uptime percentage based on current status
                    if info["status"] == "running":
                        # Slowly recover uptime if previously down
                        if self.metrics["uptime_percentage"][component] < 100.0:
                            self.metrics["uptime_percentage"][component] = min(
                                100.0,
                                self.metrics["uptime_percentage"][component] + 1.0,
                            )
                    else:
                        # Reduce uptime percentage when down
                        downtime_impact = (
                            time_diff / 3600
                        ) * 5  # 5% per hour of downtime
                        self.metrics["uptime_percentage"][component] = max(
                            0.0,
                            self.metrics["uptime_percentage"][component]
                            - downtime_impact,
                        )

                # Log current status if there are any non-running processes
                if any(
                    info["status"] != "running" for info in self.process_info.values()
                ):
                    self._log_status_report()

                await asyncio.sleep(self.check_interval)

        except Exception as e:
            log_message(f"[SystemMonitor] Monitoring error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """Stop the monitoring loop"""
        self.is_running = False
        log_message("[SystemMonitor] Stopping system health monitoring")

    def _update_process_status(self):
        """Update the status of all managed processes"""
        log_message("[SystemMonitor] Updating process status")

        # Get all active processes
        processes = self._get_active_processes()

        # Update process info dictionary
        for component, pid_info in processes.items():
            if component not in self.process_info:
                self.process_info[component] = {
                    "pid": pid_info["pid"],
                    "start_time": pid_info["start_time"],
                    "status": "running",
                    "last_active": time.time(),
                }
            else:
                # Update only if PID changed
                if self.process_info[component]["pid"] != pid_info["pid"]:
                    self.process_info[component]["pid"] = pid_info["pid"]
                    self.process_info[component]["start_time"] = pid_info["start_time"]
                    self.process_info[component]["status"] = "running"
                    self.process_info[component]["last_active"] = time.time()
                    # Reset notification flag when process is running again
                    self.notification_sent[component] = False

        # Mark processes that are no longer running
        for component in list(self.process_info.keys()):
            if component not in processes:
                if self.process_info[component]["status"] == "running":
                    self.process_info[component]["status"] = "stopped"
                    current_time = time.time()
                    self.process_info[component]["downtime_started"] = current_time
                    log_message(
                        f"[SystemMonitor] Process {component} appears to have stopped"
                    )

                    # Send notification only once per downtime incident
                    if not self.notification_sent.get(component, False):
                        self._send_component_notification(component, "stopped")
                        self.notification_sent[component] = True

    def _get_active_processes(self) -> Dict[str, Dict[str, Any]]:
        """Get all active AI-SYSTEMS processes using pid files"""
        processes = {}

        try:
            # Check all pid files in logs directory
            logs_dir = "logs"
            if not os.path.exists(logs_dir):
                return processes

            for filename in os.listdir(logs_dir):
                if filename.endswith(".pid"):
                    component = filename.replace(".pid", "")
                    pid_path = os.path.join(logs_dir, filename)

                    try:
                        with open(pid_path, "r") as f:
                            pid_data = f.read().strip()

                        # Parse PID and start time
                        if ":" in pid_data:
                            pid_str, start_time_str = pid_data.split(":", 1)
                            pid = int(pid_str)
                            start_time = float(start_time_str)
                        else:
                            pid = int(pid_data)
                            start_time = 0

                        # Check if process is still running
                        if self._is_process_running(pid):
                            processes[component] = {
                                "pid": pid,
                                "start_time": start_time,
                            }
                    except Exception as e:
                        log_message(
                            f"[SystemMonitor] Error reading pid file {filename}: {e}"
                        )

            return processes
        except Exception as e:
            log_message(f"[SystemMonitor] Error getting active processes: {e}")
            return processes

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with the given PID is running"""
        try:
            # On POSIX systems, sending signal 0 checks if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return False

    async def _check_health(self):
        """Check the health of all components and recover if needed"""
        log_message("[SystemMonitor] Performing health check")

        # Update current process status
        self._update_process_status()

        # Check required components
        required_components = self.config.get("monitor", {}).get(
            "required_components",
            ["ai1", "ai2_executor", "ai2_tester", "ai2_documenter", "ai3", "mcp_api"],
        )

        for component in required_components:
            # Skip if component is not being monitored
            if component not in self.process_info:
                continue

            component_status = self.process_info[component]["status"]
            if component_status == "stopped":
                log_message(
                    f"[SystemMonitor] Required component {component} is not running"
                )
                await self._recover_component(component)

        # Also check log file sizes and rotate if needed
        self._check_log_file_sizes()

    async def _recover_component(self, component: str):
        """Attempt to recover a stopped component"""
        # Increment recovery attempt counter
        self.recovery_attempts[component] = self.recovery_attempts.get(component, 0) + 1

        # Update metrics
        self.metrics["total_recoveries"] += 1
        if component not in self.metrics["recovery_by_component"]:
            self.metrics["recovery_by_component"][component] = 0
        self.metrics["recovery_by_component"][component] += 1

        # Check if we've exceeded the maximum recovery attempts
        if self.recovery_attempts[component] > self.max_recovery_attempts:
            log_message(
                f"[SystemMonitor] Maximum recovery attempts ({self.max_recovery_attempts}) reached for {component}"
            )
            self._send_component_notification(
                component, "max_recovery_attempts_reached"
            )
            return

        log_message(
            f"[SystemMonitor] Attempting to recover {component} (attempt {self.recovery_attempts[component]})"
        )

        # Get restart command from configuration
        restart_cmd = (
            self.config.get("monitor", {}).get("restart_commands", {}).get(component)
        )
        if not restart_cmd:
            # Try to build a restart command if none exists in config
            restart_cmd = self._build_restart_command(component)

        if not restart_cmd:
            log_message(
                f"[SystemMonitor] No restart command configured for {component}"
            )
            return

        try:
            # Execute restart command
            log_message(f"[SystemMonitor] Executing restart command: {restart_cmd}")
            process = await asyncio.create_subprocess_shell(
                restart_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for the process to complete with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30
                )
                if process.returncode == 0:
                    log_message(f"[SystemMonitor] Successfully restarted {component}")
                    # Reset recovery attempts on success
                    self.recovery_attempts[component] = 0
                    self._send_component_notification(component, "recovered")
                else:
                    log_message(
                        f"[SystemMonitor] Failed to restart {component}: {stderr.decode().strip()}"
                    )
                    self._send_component_notification(
                        component, "recovery_failed", {"error": stderr.decode().strip()}
                    )
            except asyncio.TimeoutError:
                log_message(
                    f"[SystemMonitor] Restart command for {component} timed out"
                )
                self._send_component_notification(component, "recovery_timeout")

        except Exception as e:
            log_message(
                f"[SystemMonitor] Error executing restart command for {component}: {e}"
            )
            self._send_component_notification(
                component, "recovery_error", {"error": str(e)}
            )

    def _build_restart_command(self, component: str) -> Optional[str]:
        """Try to build a restart command for a component if none is configured"""
        if component == "ai1":
            return "./run_ai1.sh"
        elif (
            component == "ai2_executor"
            or component == "ai2_tester"
            or component == "ai2_documenter"
        ):
            # Extract role from component name
            role = component.split("_")[1]
            return f"./run_ai2.sh {role}"
        elif component == "ai3":
            return "./run_ai3.sh"
        elif component == "mcp_api":
            return "./run_mcp_api.sh"
        elif component == "load_monitor":
            return "./run_load_monitor.sh"
        else:
            return None

    def _send_component_notification(
        self, component: str, status: str, details: Dict = None
    ):
        """Send a notification about component status changes"""
        try:
            # This would ideally interface with the MCP API to broadcast notifications
            # For now, we'll just log the notification
            notification = {
                "component": component,
                "status": status,
                "timestamp": time.time(),
                "details": details or {},
            }
            log_message(
                f"[SystemMonitor] Component notification: {json.dumps(notification)}"
            )

            # TODO: Send notification to MCP API for WebSocket broadcast
            # In a real implementation, this would make an API call
        except Exception as e:
            log_message(f"[SystemMonitor] Error sending notification: {e}")

    def _check_log_file_sizes(self):
        """Check log file sizes and rotate if they get too large"""
        log_dir = "logs"
        max_size_mb = 50  # Maximum log file size in MB

        if not os.path.exists(log_dir):
            return

        for filename in os.listdir(log_dir):
            if filename.endswith(".log"):
                file_path = os.path.join(log_dir, filename)
                try:
                    # Get file size in MB
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)

                    if size_mb > max_size_mb:
                        # Rotate log file
                        log_message(
                            f"[SystemMonitor] Rotating log file {filename} ({size_mb:.2f} MB)"
                        )
                        self._rotate_log_file(file_path)
                except Exception as e:
                    log_message(f"[SystemMonitor] Error checking log file size: {e}")

    def _rotate_log_file(self, file_path: str):
        """Rotate a log file by renaming it with a timestamp and creating a new empty one"""
        try:
            # Get timestamp for rotation
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            base_name, ext = os.path.splitext(file_path)
            rotated_path = f"{base_name}.{timestamp}{ext}"

            # Rename current log file
            os.rename(file_path, rotated_path)

            # Create new empty log file
            with open(file_path, "w") as f:
                f.write(f"Log rotated at {timestamp}\n")

            log_message(
                f"[SystemMonitor] Log file rotated: {file_path} -> {rotated_path}"
            )
        except Exception as e:
            log_message(f"[SystemMonitor] Error rotating log file: {e}")

    def _log_status_report(self):
        """Log a status report of all monitored components"""
        report = ["=== System Component Status Report ==="]
        current_time = time.time()

        for component, info in sorted(self.process_info.items()):
            status = info["status"]
            status_symbol = "✓" if status == "running" else "✗"

            uptime = self.metrics["uptime_percentage"].get(component, 0)
            uptime_color = (
                "green" if uptime > 95 else "yellow" if uptime > 80 else "red"
            )

            if status == "running":
                uptime_duration = (
                    current_time - info["start_time"] if info.get("start_time") else 0
                )
                uptime_str = f"{uptime_duration/3600:.1f} hours"
                report.append(
                    f"{status_symbol} {component}: {status.upper()} for {uptime_str} (uptime: {uptime:.1f}%)"
                )
            else:
                downtime_duration = (
                    current_time - info.get("downtime_started", current_time)
                    if info.get("downtime_started")
                    else 0
                )
                downtime_str = f"{downtime_duration/60:.1f} minutes"
                report.append(
                    f"{status_symbol} {component}: {status.upper()} for {downtime_str} (uptime: {uptime:.1f}%)"
                )

        report.append(f"Recovery attempts: {self.metrics['total_recoveries']} total")
        for component, count in self.metrics["recovery_by_component"].items():
            report.append(f"  - {component}: {count} attempts")
        report.append("=====================================")

        log_message("\n".join(report))


class TestValidator:
    """Validates tests and processes test results"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.test_results = {}

    def _load_config(self) -> Dict:
        """Load configuration from file"""
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            log_message(f"[TestValidator] Error loading config: {e}")
            return {}

    async def validate_test_file(
        self, test_file_path: str, code_file_path: str = None
    ) -> Dict[str, Any]:
        """Validate a test file against coding standards and check syntax"""
        results = {"valid": True, "errors": [], "warnings": []}

        # Check if file exists
        if not os.path.exists(test_file_path):
            results["valid"] = False
            results["errors"].append(f"Test file does not exist: {test_file_path}")
            return results

        # Read test file content
        try:
            with open(test_file_path, "r") as f:
                test_content = f.read()
        except Exception as e:
            results["valid"] = False
            results["errors"].append(f"Error reading test file: {e}")
            return results

        # Get file extension to determine language
        _, ext = os.path.splitext(test_file_path)

        # Apply language-specific validation
        if ext == ".py":
            await self._validate_python_test(test_content, results)
        elif ext in [".js", ".jsx"]:
            await self._validate_js_test(test_content, results)
        elif ext in [".ts", ".tsx"]:
            await self._validate_ts_test(test_content, results)
        elif ext == ".java":
            await self._validate_java_test(test_content, results)
        elif ext in [".go"]:
            await self._validate_go_test(test_content, results)
        elif ext in [".cpp", ".cc", ".cxx"]:
            await self._validate_cpp_test(test_content, results)
        else:
            results["warnings"].append(f"No specific validator for file type {ext}")
            # Generic validation for unknown types
            await self._validate_generic_test(test_content, results)

        # Check for test-code relationship if code file is provided
        if code_file_path and os.path.exists(code_file_path):
            await self._validate_test_coverage(test_content, code_file_path, results)

        return results

    async def _validate_python_test(self, content: str, results: Dict[str, Any]):
        """Validate Python test file"""
        # Check for test imports
        if "import pytest" not in content and "import unittest" not in content:
            results["warnings"].append(
                "Missing test framework import (pytest or unittest)"
            )

        # Check for test methods/functions
        if not re.search(r"def test_\w+", content) and not re.search(
            r"class Test\w+", content
        ):
            results["warnings"].append("No test methods/classes found")

        # Check for assertions
        if "assert" not in content and "self.assert" not in content:
            results["warnings"].append("No assertions found in test")

        # Check for syntax errors (compile test)
        try:
            compile(content, "<string>", "exec")
        except SyntaxError as e:
            results["valid"] = False
            results["errors"].append(f"Python syntax error: {str(e)}")

    async def _validate_js_test(self, content: str, results: Dict[str, Any]):
        """Validate JavaScript test file"""
        # Check for test framework
        if (
            "test(" not in content
            and "it(" not in content
            and "describe(" not in content
        ):
            results["warnings"].append("No test functions found (test, it, describe)")

        # Check for assertions
        if "expect(" not in content and "assert" not in content:
            results["warnings"].append("No assertions found in test")

    async def _validate_ts_test(self, content: str, results: Dict[str, Any]):
        """Validate TypeScript test file"""
        # TypeScript tests have similar structures to JS tests
        await self._validate_js_test(content, results)

        # Check for TypeScript-specific imports
        if "@types/jest" not in content and "@types/mocha" not in content:
            results["warnings"].append(
                "Missing TypeScript type definitions for test framework"
            )

    async def _validate_java_test(self, content: str, results: Dict[str, Any]):
        """Validate Java test file"""
        # Check for JUnit imports
        if "import org.junit" not in content:
            results["warnings"].append("Missing JUnit import")

        # Check for test methods
        if "@Test" not in content:
            results["warnings"].append("No @Test annotations found")

        # Check for assertions
        if "assert" not in content:
            results["warnings"].append("No assertions found in test")

    async def _validate_go_test(self, content: str, results: Dict[str, Any]):
        """Validate Go test file"""
        # Check for test package
        if "package " not in content:
            results["warnings"].append("Missing package declaration")

        # Check for test methods
        if not re.search(r"func Test\w+", content):
            results["warnings"].append(
                "No test functions found (should start with 'Test')"
            )

        # Check for test imports
        if 'import "testing"' not in content:
            results["warnings"].append("Missing 'testing' package import")

    async def _validate_cpp_test(self, content: str, results: Dict[str, Any]):
        """Validate C++ test file"""
        # Check for test framework
        if "TEST(" not in content and "TEST_F(" not in content:
            results["warnings"].append("No GoogleTest TEST macros found")

        # Check for assertions
        if "EXPECT_" not in content and "ASSERT_" not in content:
            results["warnings"].append("No GoogleTest assertions found")

    async def _validate_generic_test(self, content: str, results: Dict[str, Any]):
        """Generic validation for unknown test file types"""
        # Check for common test patterns
        if not re.search(r"test|assert|expect|should", content, re.IGNORECASE):
            results["warnings"].append(
                "No common test patterns found (test, assert, expect, should)"
            )

    async def _validate_test_coverage(
        self, test_content: str, code_file_path: str, results: Dict[str, Any]
    ):
        """Check if test appears to cover the code file"""
        try:
            # Read code file
            with open(code_file_path, "r") as f:
                code_content = f.read()

            # Extract function and class names from code
            function_pattern = r"(?:function|def|func)\s+(\w+)"
            class_pattern = r"(?:class|interface|struct)\s+(\w+)"

            functions = re.findall(function_pattern, code_content)
            classes = re.findall(class_pattern, code_content)

            # Check if functions and classes are mentioned in tests
            missing_coverage = []

            for func in functions:
                # Skip very common or internal function names
                if func in ["main", "init", "setup", "get", "set"]:
                    continue

                # Check if function name is in test content
                if func not in test_content:
                    missing_coverage.append(func)

            for cls in classes:
                if cls not in test_content:
                    missing_coverage.append(cls)

            if missing_coverage:
                results["warnings"].append(
                    f"Potential missing test coverage for: {', '.join(missing_coverage)}"
                )

        except Exception as e:
            results["warnings"].append(f"Error checking test coverage: {e}")

    async def run_tests(self, test_files: List[str]) -> Dict[str, Any]:
        """Run tests and collect results"""
        results = {
            "success": True,
            "total": len(test_files),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        for test_file in test_files:
            test_result = await self._run_test_file(test_file)
            results["details"].append(test_result)

            if test_result["status"] == "passed":
                results["passed"] += 1
            elif test_result["status"] == "failed":
                results["failed"] += 1
                results["success"] = False
            else:  # skipped
                results["skipped"] += 1

        return results

    async def _run_test_file(self, test_file: str) -> Dict[str, Any]:
        """Run a single test file"""
        result = {
            "file": test_file,
            "status": "unknown",
            "output": "",
            "errors": "",
            "duration": 0,
        }

        # Get file extension
        _, ext = os.path.splitext(test_file)

        # Prepare command based on file type
        if ext == ".py":
            cmd = f"python -m pytest {test_file} -v"
        elif ext in [".js", ".jsx", ".ts", ".tsx"]:
            cmd = f"npx jest {test_file}"
        elif ext == ".go":
            cmd = f"go test {test_file}"
        elif ext == ".java":
            # For Java, we need to be more careful with the command
            # This is a simplified version that assumes Maven
            cmd = f"mvn test -Dtest={os.path.basename(test_file).replace('.java', '')}"
        elif ext in [".cpp", ".cc", ".cxx"]:
            # Assumes test is built and in the same directory
            test_exec = os.path.splitext(test_file)[0]
            cmd = f"./{test_exec}"
        else:
            result["status"] = "skipped"
            result["output"] = f"No runner available for file type: {ext}"
            return result

        # Run the test
        start_time = time.time()
        try:
            process = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            end_time = time.time()

            result["duration"] = end_time - start_time
            result["output"] = stdout.decode()
            result["errors"] = stderr.decode()

            if process.returncode == 0:
                result["status"] = "passed"
            else:
                result["status"] = "failed"

        except asyncio.TimeoutError:
            result["status"] = "failed"
            result["errors"] = "Test execution timed out (>60s)"
            result["duration"] = time.time() - start_time
        except Exception as e:
            result["status"] = "failed"
            result["errors"] = f"Error running test: {str(e)}"
            result["duration"] = time.time() - start_time

        return result


# ...existing code...
import json
from typing import Any, Dict, List, Optional, Union

import aiohttp

# ...existing code...


async def call_ollama(
    session: aiohttp.ClientSession,
    prompt: str,
    endpoint: str,
    model: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,  # Corresponds to num_predict in Ollama
    timeout: int = 120,
) -> Optional[str]:
    """
    Calls the Ollama API with the given parameters.

    Args:
        session: The aiohttp client session.
        prompt: The user prompt.
        endpoint: The Ollama API endpoint (e.g., "http://localhost:11434").
        model: The Ollama model to use.
        system_prompt: An optional system prompt.
        temperature: The temperature for generation.
        max_tokens: The maximum number of tokens to generate (num_predict).
        timeout: The request timeout in seconds.

    Returns:
        The Ollama API response content as a string, or None if an error occurs.
    """
    api_url = f"{endpoint.rstrip('/')}/api/chat"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    options = {"temperature": temperature}
    if max_tokens is not None and max_tokens > 0:
        options["num_predict"] = max_tokens

    payload = {
        "model": model,
        "messages": messages,
        "options": options,
        "stream": False,  # Assuming non-streaming for simplicity here
    }

    try:
        async with session.post(api_url, json=payload, timeout=timeout) as response:
            response_data = await response.json()
            if response.status == 200:
                if (
                    response_data
                    and isinstance(response_data, dict)
                    and response_data.get("message")
                    and isinstance(response_data["message"], dict)
                ):
                    return response_data["message"].get("content", "")
                else:
                    logger.warning(
                        f"[OllamaCall] Unexpected response structure from {model}: {response_data}"
                    )
                    return None
            else:
                error_message = response_data.get("error", "Unknown error")
                logger.error(
                    f"[OllamaCall] HTTP Error from {model} ({response.status}): {error_message}"
                )
                return None
    except aiohttp.ClientResponseError as e:
        logger.error(
            f"[OllamaCall] ClientResponseError calling {model} ({e.status}): {e.message}"
        )
        return None
    except aiohttp.ClientConnectionError as e:
        logger.error(f"[OllamaCall] Connection error to {endpoint}: {e}")
        return None
    except asyncio.TimeoutError:
        logger.error(f"[OllamaCall] Timeout calling {model} at {endpoint}")
        return None
    except json.JSONDecodeError:
        logger.error(f"[OllamaCall] Invalid JSON response from {model}")
        return None
    except Exception as e:
        logger.error(
            f"[OllamaCall] Unexpected error calling {model}: {e}", exc_info=True
        )
        return None


import logging
import os
from typing import Any, Dict, Optional

# ...existing code...
import httpx

logger = logging.getLogger(__name__)


# ...existing code...
async def call_ollama(
    prompt: str, model: str = "llama3", base_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Makes a request to the Ollama API and returns the JSON response.

    Args:
        prompt: The prompt to send to the Ollama API.
        model: The Ollama model to use (default is "llama3").
        base_url: The base URL for the Ollama API. If None, uses OLLAMA_BASE_URL from environment or default.

    Returns:
        A dictionary containing the JSON response from the API.
    """
    if base_url is None:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    api_url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,  # Assuming non-streaming for simplicity, adjust if needed
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url, json=payload, timeout=60.0
            )  # Added timeout
            response.raise_for_status()  # Raise an exception for bad status codes
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Ollama API request failed with status {e.response.status_code}: {e.response.text}"
        )
        return {
            "error": f"HTTP error: {e.response.status_code}",
            "details": e.response.text,
        }
    except httpx.RequestError as e:
        logger.error(f"Ollama API request failed: {e}")
        return {"error": "Request error", "details": str(e)}
    except Exception as e:
        logger.error(f"An unexpected error occurred during Ollama API call: {e}")
        return {"error": "Unexpected error", "details": str(e)}


if __name__ == "__main__":
    pass  # Placeholder for any code to run when module is executed directly
