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

# ... existing imports ...
from providers import BaseProvider, ProviderFactory # Ensure these are imported

# ... existing code ...

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

# --- NEW: Add call_llm_provider function ---
async def call_llm_provider(
    provider_name: str,
    prompt: str,
    system_prompt: Optional[str],
    config: Dict,
    ai_config: Dict,
    service_name: str,
    max_tokens_override: Optional[int] = None,
    temperature_override: Optional[float] = None,
) -> Optional[str]:
    """Helper function to initialize and call an LLM provider."""
    provider_instance = None # Initialize to None
    try:
        logger.info(f"[{service_name.upper()}] Calling provider {provider_name}...")
        # Pass the global config to the factory
        provider_instance: BaseProvider = ProviderFactory.create_provider(provider_name, config=config)
        await apply_request_delay(service_name) # Apply delay based on service

        # Determine max_tokens and temperature, allowing overrides
        max_tokens = max_tokens_override if max_tokens_override is not None else ai_config.get("max_tokens", 4000)
        temperature = temperature_override if temperature_override is not None else ai_config.get("temperature")

        logger.debug(f"[{service_name.upper()}] Using max_tokens={max_tokens}, temperature={temperature}")

        response = await provider_instance.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=ai_config.get("model"), # Model comes from the specific AI config section
            max_tokens=max_tokens,
            temperature=temperature,
        )
        # Ensure session is closed if the provider has one
        if hasattr(provider_instance, "close_session") and callable(provider_instance.close_session):
            await provider_instance.close_session()
            logger.debug(f"[{service_name.upper()}] Closed session for provider {provider_name}")
        return response
    except Exception as e:
        logger.error(f"[{service_name.upper()}] Error calling provider {provider_name}: {e}", exc_info=True)
        # Attempt to close session even if an error occurred during generation
        if provider_instance and hasattr(provider_instance, "close_session") and callable(provider_instance.close_session):
            try:
                await provider_instance.close_session()
                logger.debug(f"[{service_name.upper()}] Closed session for provider {provider_name} after error.")
            except Exception as close_e:
                logger.error(f"[{service_name.upper()}] Error closing provider session after error: {close_e}")
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

# New automated test execution utilities
import subprocess
import json
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import logging
import re

test_logger = logging.getLogger("test_execution")

@dataclass
class TestResult:
    """Results from a test execution"""
    file_path: str
    success: bool
    failures: List[str]
    output: str
    error_details: Optional[Dict[str, Any]] = None
    coverage: Optional[float] = None

class TestRunner:
    """Executes tests and collects detailed results for AI analysis"""
    
    def __init__(self, repo_dir: str = "repo"):
        self.repo_dir = repo_dir
        self._setup_logger()
    
    def _setup_logger(self):
        handler = logging.FileHandler("logs/test_execution.log")
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
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
                    error_details={"exception": str(e), "type": str(type(e))}
                )
        
        return results
    
    def _run_js_tests(self) -> Dict[str, TestResult]:
        """Run JavaScript tests with Jest"""
        results = {}
        test_files = (
            self._find_files("*.test.js") + 
            self._find_files("*.spec.js") + 
            self._find_files("*.test.jsx") + 
            self._find_files("*.test.tsx")
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
                test_logger.error(f"Error running JavaScript test {test_file}: {str(e)}")
                results[test_file] = TestResult(
                    file_path=test_file,
                    success=False,
                    failures=[f"Exception: {str(e)}"],
                    output=f"Error: {str(e)}",
                    error_details={"exception": str(e), "type": str(type(e))}
                )
        
        return results
    
    def _run_web_tests(self) -> Dict[str, TestResult]:
        """Run web tests for HTML/CSS files"""
        results = {}
        html_test_files = self._find_files("*_test.html") + self._find_files("*.test.html")
        css_test_files = self._find_files("*_test.css") + self._find_files("*.test.css")
        
        test_files = html_test_files + css_test_files
        if not test_files:
            test_logger.info("No web test files found")
            return results
        
        test_logger.info(f"Found {len(test_files)} web test files")
        
        # Web tests are typically part of JavaScript test files
        # We'll look for associated JS test files and run them
        for test_file in test_files:
            js_test_file = test_file.replace('.html', '.test.js').replace('.css', '.test.js')
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
                        error_details={"exception": str(e), "type": str(type(e))}
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
                output="File not found error"
            )
        
        test_logger.info(f"Running Python test: {test_file}")
        orig_dir = os.getcwd()
        os.chdir(self.repo_dir)
        
        try:
            # Run the test with pytest
            process = subprocess.run(
                ["python", "-m", "pytest", test_file, "-v"],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = process.returncode == 0
            
            # Parse failures from output
            failures = []
            if not success:
                failure_pattern = r"FAILED\s+(.*?::.*?)\s+"
                matches = re.findall(failure_pattern, output)
                failures = matches if matches else ["Test failed but couldn't parse specific failure"]
            
            return TestResult(
                file_path=test_file,
                success=success,
                failures=failures,
                output=output,
                coverage=self._extract_python_coverage(output)
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
                output="File not found error"
            )
        
        test_logger.info(f"Running JavaScript test: {test_file}")
        orig_dir = os.getcwd()
        os.chdir(self.repo_dir)
        
        try:
            # Run the test with Jest
            process = subprocess.run(
                ["npx", "jest", test_file, "--no-cache"],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = process.returncode == 0
            
            # Parse failures from output
            failures = []
            if not success:
                # Look for the specific error in the output
                if "FAIL" in output:
                    # Extract the lines following FAIL until the next test or summary
                    fail_sections = re.findall(r"FAIL.*?(?=PASS|FAIL|Summary|$)", output, re.DOTALL)
                    for section in fail_sections:
                        failures.append(section.strip())
                
                if not failures:
                    failures = ["Test failed but couldn't parse specific failure"]
            
            return TestResult(
                file_path=test_file,
                success=success,
                failures=failures,
                output=output,
                coverage=self._extract_js_coverage(output)
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
        js_files = self._find_files("*.js") + self._find_files("*.jsx") + self._find_files("*.tsx")
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
                output="File not found error"
            )
        
        try:
            # Run flake8
            process = subprocess.run(
                ["flake8", full_path],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = process.returncode == 0
            
            # Parse failures from output
            failures = []
            if not success:
                failures = [line.strip() for line in output.splitlines() if line.strip()]
            
            return TestResult(
                file_path=file_path,
                success=success,
                failures=failures,
                output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}"
            )
    
    def _run_js_linter(self, file_path: str) -> TestResult:
        """Run eslint on JavaScript file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error"
            )
        
        try:
            # Run eslint
            # First ensure .eslintrc.json exists
            eslint_config = os.path.join(self.repo_dir, ".eslintrc.json")
            if not os.path.exists(eslint_config):
                with open(eslint_config, "w") as f:
                    f.write('{"extends": ["eslint:recommended"], "parserOptions": {"ecmaVersion": 2020}, "env": {"browser": true, "node": true, "es6": true}}')
            
            process = subprocess.run(
                ["eslint", full_path, "--no-eslintrc", "--config", eslint_config],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = process.returncode == 0
            
            # Parse failures from output
            failures = []
            if not success:
                failures = [line.strip() for line in output.splitlines() if line.strip() and not line.startswith("eslint:")]
            
            return TestResult(
                file_path=file_path,
                success=success,
                failures=failures,
                output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}"
            )
    
    def _run_html_linter(self, file_path: str) -> TestResult:
        """Run htmlhint on HTML file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error"
            )
        
        try:
            # Run htmlhint
            # First ensure .htmlhintrc exists
            htmlhint_config = os.path.join(self.repo_dir, ".htmlhintrc")
            if not os.path.exists(htmlhint_config):
                with open(htmlhint_config, "w") as f:
                    f.write('{"tagname-lowercase": true, "attr-lowercase": true, "attr-value-double-quotes": true, "doctype-first": false, "tag-pair": true, "spec-char-escape": true, "id-unique": true, "src-not-empty": true, "attr-no-duplication": true, "title-require": true}')
            
            process = subprocess.run(
                ["htmlhint", full_path],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = "no error" in output.lower()
            
            # Parse failures from output
            failures = []
            if not success:
                failure_lines = [line.strip() for line in output.splitlines() if line.strip() and "error" in line.lower()]
                failures = failure_lines if failure_lines else ["HTML validation errors found"]
            
            return TestResult(
                file_path=file_path,
                success=success,
                failures=failures,
                output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}"
            )
    
    def _run_css_linter(self, file_path: str) -> TestResult:
        """Run stylelint on CSS file"""
        full_path = os.path.join(self.repo_dir, file_path)
        if not os.path.exists(full_path):
            return TestResult(
                file_path=file_path,
                success=False,
                failures=["File not found"],
                output="File not found error"
            )
        
        try:
            # Run stylelint
            # First ensure .stylelintrc.json exists
            stylelint_config = os.path.join(self.repo_dir, ".stylelintrc.json")
            if not os.path.exists(stylelint_config):
                with open(stylelint_config, "w") as f:
                    if file_path.endswith(".scss"):
                        f.write('{"extends": "stylelint-config-standard", "plugins": ["stylelint-scss"]}')
                    else:
                        f.write('{"extends": "stylelint-config-standard"}')
            
            process = subprocess.run(
                ["stylelint", full_path],
                capture_output=True,
                text=True
            )
            
            output = process.stdout + process.stderr
            success = process.returncode == 0
            
            # Parse failures from output
            failures = []
            if not success:
                failures = [line.strip() for line in output.splitlines() if line.strip() and file_path in line]
            
            return TestResult(
                file_path=file_path,
                success=success,
                failures=failures,
                output=output
            )
        except Exception as e:
            return TestResult(
                file_path=file_path,
                success=False,
                failures=[f"Linter error: {str(e)}"],
                output=f"Error: {str(e)}"
            )
    
    def generate_test_report(self, test_results: Dict[str, TestResult]) -> Dict[str, Any]:
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
                failures_by_type[file_ext].append({
                    "file": file_path,
                    "failures": result.failures
                })
        
        # Generate actionable insights
        insights = self._generate_insights(test_results)
        
        report = {
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": {
                "total_tests": total_tests,
                "successful_tests": successful_tests,
                "failed_tests": failed_tests,
                "success_rate": (successful_tests / total_tests) * 100 if total_tests > 0 else 0
            },
            "failures_by_type": failures_by_type,
            "insights": insights,
            "detailed_results": {
                file_path: {
                    "success": result.success,
                    "failures": result.failures,
                    "coverage": result.coverage
                }
                for file_path, result in test_results.items()
            }
        }
        
        # Save report to a file in JSON format
        os.makedirs("test_reports", exist_ok=True)
        report_path = f"test_reports/test_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
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
                insights.append(f"Common error pattern found: '{error_type}' appears in {count} tests")
        
        # Look for files with no tests
        if self._find_files("*.py") and not self._find_files("*_test.py") and not self._find_files("test_*.py"):
            insights.append("Python application files found but no Python tests exist")
        
        if self._find_files("*.js") and not self._find_files("*.test.js") and not self._find_files("*.spec.js"):
            insights.append("JavaScript files found but no JavaScript tests exist")
        
        # Check test coverage
        low_coverage_files = []
        for file_path, result in test_results.items():
            if result.coverage is not None and result.coverage < 50:
                low_coverage_files.append(file_path)
        
        if low_coverage_files:
            insights.append(f"Low test coverage (<50%) found in {len(low_coverage_files)} files")
        
        # Check for failing tests
        failing_files = [file_path for file_path, result in test_results.items() if not result.success]
        if failing_files:
            insights.append(f"Found {len(failing_files)} failing test files that need fixing")
        
        return insights
    
    def _identify_common_errors(self, test_results: Dict[str, TestResult]) -> Dict[str, int]:
        """Identify common error patterns in test failures"""
        error_patterns = {}
        
        for result in test_results.values():
            if not result.success:
                for failure in result.failures:
                    # Extract key parts of error messages
                    if "import" in failure and "error" in failure.lower():
                        error_patterns["Import Error"] = error_patterns.get("Import Error", 0) + 1
                    elif "undefined" in failure.lower():
                        error_patterns["Undefined Reference"] = error_patterns.get("Undefined Reference", 0) + 1
                    elif "assertionerror" in failure.lower() or "assert" in failure.lower():
                        error_patterns["Assertion Failure"] = error_patterns.get("Assertion Failure", 0) + 1
                    elif "syntax" in failure.lower():
                        error_patterns["Syntax Error"] = error_patterns.get("Syntax Error", 0) + 1
                    elif "type" in failure.lower() and "error" in failure.lower():
                        error_patterns["Type Error"] = error_patterns.get("Type Error", 0) + 1
        
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
            return os.path.join(dir_name.replace("/tests", "").replace("\\tests", ""), original_name)
        else:
            return os.path.join(dir_name, original_name)
    
    # JavaScript test conventions
    elif ".test" in base_name:
        original_name = base_name.replace(".test", "")
        if dir_name.endswith("/tests") or dir_name.endswith("\\tests"):
            return os.path.join(dir_name.replace("/tests", "").replace("\\tests", ""), original_name)
        else:
            return os.path.join(dir_name, original_name)
    
    # Python test suffix
    elif base_name.endswith("_test.py"):
        original_name = base_name[:-8] + ".py"
        if dir_name.endswith("/tests") or dir_name.endswith("\\tests"):
            return os.path.join(dir_name.replace("/tests", "").replace("\\tests", ""), original_name)
        else:
            return os.path.join(dir_name, original_name)
    
    return None
