import json
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Moved DEFAULT_CONFIG_PATH definition up and placed logging configuration below it
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json"
)


# Function to get initial logging configuration
def _get_initial_logging_config(config_file_path: str) -> dict:
    """
    Safely loads logging configuration (level and format) from the specified
    config file. Uses defaults if the file is missing, malformed, or if
    specific logging settings are not found.
    This function does not use the module's logger to avoid issues during
    initial setup.
    """
    default_settings = {
        "level": "INFO",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    }
    # Start with a copy of default settings
    log_config = default_settings.copy()

    if os.path.exists(config_file_path):
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                loaded_json = json.load(f)

            # Check if "logging" section exists and is a dictionary
            if "logging" in loaded_json and isinstance(loaded_json["logging"], dict):
                logging_section = loaded_json["logging"]

                # Get level, ensure it's a string, convert to upper, fallback to default
                level_val = logging_section.get("level", default_settings["level"])
                log_config["level"] = (
                    str(level_val).upper()
                    if isinstance(level_val, (str, int))
                    else default_settings["level"]
                )

                # Get format, ensure it's a string, fallback to default
                format_val = logging_section.get("format", default_settings["format"])
                log_config["format"] = (
                    str(format_val)
                    if isinstance(format_val, str)
                    else default_settings["format"]
                )
            # If "logging" key is missing or not a dict, log_config remains as default_settings

        except json.JSONDecodeError:
            # Malformed JSON in config file; use defaults.
            # Consider printing to stderr if this case needs visibility during startup:
            # import sys
            # print(f"Warning: Error decoding JSON from {config_file_path}. Using default logging settings.", file=sys.stderr)
            pass  # Silently use defaults
        except Exception:
            # Other errors (e.g., permission issues) reading file; use defaults.
            pass  # Silently use defaults

    return log_config


# Configure logging using settings from config.json or defaults
_initial_log_params = _get_initial_logging_config(DEFAULT_CONFIG_PATH)

# Ensure level is a string and uppercase before passing to getattr
_log_level_str = str(_initial_log_params.get("level", "INFO")).upper()
_log_format_str = str(
    _initial_log_params.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
)

# Get the actual logging level integer value from the logging module
_actual_log_level = getattr(logging, _log_level_str, logging.INFO)

# Setup root logger
logging.basicConfig(level=_actual_log_level, format=_log_format_str)
logger = logging.getLogger(__name__)


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Загрузка конфигурации из файла.

    Args:
        config_path: Путь к файлу конфигурации. Если None, используется путь по умолчанию.

    Returns:
        Dict[str, Any]: Словарь с конфигурацией
    """
    if not config_path:
        config_path = DEFAULT_CONFIG_PATH

    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            logger.warning(
                f"Файл конфигурации {config_path} не найден. Используем конфигурацию по умолчанию."
            )
            return create_default_config(config_path)
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return create_default_config()


def create_default_config(save_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Создание конфигурации по умолчанию.

    Args:
        save_path: Путь для сохранения конфигурации. Если None, конфигурация не сохраняется.

    Returns:
        Dict[str, Any]: Словарь с конфигурацией по умолчанию
    """
    default_config = {
        "version": "1.0.0",
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "ai_config": {
            "ai1": {
                "provider": "openai",
                "model": "gpt-4",
                "max_tokens": 2000,
                "temperature": 0.7,
            },
            "ai2": {
                "provider": {
                    "executor": "openai",
                    "tester": "openai",
                    "documenter": "openai",
                },
                "fallback_provider": "groq",
                "max_tokens": 2000,
                "temperature": 0.7,
            },
            "ai3": {
                "provider": "openai",
                "model": "gpt-4",
                "max_tokens": 2000,
                "temperature": 0.7,
            },
        },
        "ai1_prompts": [
            "Вы опытный программист, специализирующийся на {language}. Разбейте задачу на подзадачи и создайте план реализации.",
            "Вы инженер по требованиям. Опишите требования к системе на основе следующего задания.",
        ],
        "ai2_prompts": [
            "Вы опытный программист. Создайте файл {filename} согласно заданию.",
            "Вы тестировщик. Напишите тесты для файла {filename} согласно заданию.",
            "Вы технический писатель. Создайте документацию для файла {filename}.",
        ],
        "languages": [
            "python",
            "javascript",
            "typescript",
            "java",
            "c++",
            "go",
            "rust",
            "php",
        ],
        "output_dir": "output",
    }

    if save_path:
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            logger.info(f"Конфигурация по умолчанию сохранена в {save_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении конфигурации: {e}")

    return default_config


def save_config(config: Dict[str, Any], config_path: Optional[str] = None) -> bool:
    """
    Сохранение конфигурации в файл.

    Args:
        config: Словарь с конфигурацией
        config_path: Путь к файлу конфигурации. Если None, используется путь по умолчанию.

    Returns:
        bool: True если конфигурация сохранена успешно, иначе False
    """
    if not config_path:
        config_path = DEFAULT_CONFIG_PATH

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"Конфигурация сохранена в {config_path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфигурации: {e}")
        return False


def update_config(
    updates: Dict[str, Any], config_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Обновление конфигурации.

    Args:
        updates: Словарь с обновлениями для конфигурации
        config_path: Путь к файлу конфигурации. Если None, используется путь по умолчанию.

    Returns:
        Dict[str, Any]: Обновленный словарь с конфигурацией
    """
    config = load_config(config_path)

    def recursive_update(target, source):
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and key in target
                and isinstance(target[key], dict)
            ):
                recursive_update(target[key], value)
            else:
                target[key] = value

    recursive_update(config, updates)
    save_config(config, config_path)

    return config


# Для тестирования
if __name__ == "__main__":
    config = load_config()
    print(json.dumps(config, indent=2, ensure_ascii=False))
