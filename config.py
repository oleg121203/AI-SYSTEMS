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

# Global cache for config to avoid repeated disk reads
_config_cache = None
_config_file_path = "config.json"
_config_last_mtime = 0

# System load level constants
LOAD_LEVEL_MINIMAL = 1
LOAD_LEVEL_LOW = 2
LOAD_LEVEL_MEDIUM = 3
LOAD_LEVEL_HIGH = 4
LOAD_LEVEL_MAXIMUM = 5

# Default delay values by load level (in seconds)
# INCREASED DELAYS: Min delays +0.5s, Max delays +1.0s
DELAY_BY_LOAD_LEVEL = {
    LOAD_LEVEL_MINIMAL: {
        "ai1": {"min": 1.5, "max": 3.0},  # Was 1.0, 2.0
        "ai2_executor": {"min": 2.5, "max": 5.0},  # Was 2.0, 4.0
        "ai2_tester": {"min": 2.5, "max": 5.0},  # Was 2.0, 4.0
        "ai2_documenter": {"min": 2.5, "max": 5.0},  # Was 2.0, 4.0
        "ai3": {"min": 2.5, "max": 5.0},  # Was 2.0, 4.0
    },
    LOAD_LEVEL_LOW: {
        "ai1": {"min": 1.0, "max": 2.0},  # Was 0.5, 1.0
        "ai2_executor": {"min": 1.5, "max": 3.0},  # Was 1.0, 2.0
        "ai2_tester": {"min": 1.5, "max": 3.0},  # Was 1.0, 2.0
        "ai2_documenter": {"min": 1.5, "max": 3.0},  # Was 1.0, 2.0
        "ai3": {"min": 1.5, "max": 3.0},  # Was 1.0, 2.0
    },
    LOAD_LEVEL_MEDIUM: {
        "ai1": {"min": 0.8, "max": 1.7},  # Was 0.3, 0.7
        "ai2_executor": {"min": 1.2, "max": 2.5},  # Was 0.7, 1.5
        "ai2_tester": {"min": 1.2, "max": 2.5},  # Was 0.7, 1.5
        "ai2_documenter": {"min": 1.2, "max": 2.5},  # Was 0.7, 1.5
        "ai3": {"min": 1.2, "max": 2.5},  # Was 0.7, 1.5
    },
    LOAD_LEVEL_HIGH: {
        "ai1": {"min": 0.7, "max": 1.5},  # Was 0.2, 0.5
        "ai2_executor": {"min": 1.0, "max": 2.0},  # Was 0.5, 1.0
        "ai2_tester": {"min": 1.0, "max": 2.0},  # Was 0.5, 1.0
        "ai2_documenter": {"min": 1.0, "max": 2.0},  # Was 0.5, 1.0
        "ai3": {"min": 1.0, "max": 2.0},  # Was 0.5, 1.0
    },
    LOAD_LEVEL_MAXIMUM: {
        "ai1": {"min": 0.6, "max": 1.3},  # Was 0.1, 0.3
        "ai2_executor": {"min": 0.8, "max": 1.7},  # Was 0.3, 0.7
        "ai2_tester": {"min": 0.8, "max": 1.7},  # Was 0.3, 0.7
        "ai2_documenter": {"min": 0.8, "max": 1.7},  # Was 0.3, 0.7
        "ai3": {"min": 0.8, "max": 1.7},  # Was 0.3, 0.7
    },
}


def detect_load_level(config: Dict[str, Any]) -> int:
    """
    Detects the current system load level based on buffer settings.

    Args:
        config: The loaded configuration dictionary

    Returns:
        int: Load level value (1-5)
    """
    buffer_size = config.get("ai1_desired_active_buffer", 10)

    # Map buffer size to load level
    if buffer_size <= 5:
        return LOAD_LEVEL_MINIMAL
    elif buffer_size <= 10:
        return LOAD_LEVEL_LOW
    elif buffer_size <= 15:
        return LOAD_LEVEL_MEDIUM
    elif buffer_size <= 20:
        return LOAD_LEVEL_HIGH
    else:
        return LOAD_LEVEL_MAXIMUM


def adjust_delays_for_load_level(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adjusts the request delay settings based on the detected load level.

    Args:
        config: The loaded configuration dictionary

    Returns:
        Dict: Updated configuration with adjusted delay settings
    """
    load_level = detect_load_level(config)

    # Get delay settings for detected load level
    delay_settings = DELAY_BY_LOAD_LEVEL.get(
        load_level, DELAY_BY_LOAD_LEVEL[LOAD_LEVEL_MEDIUM]
    )

    # If config doesn't have request_delays section, add it
    if "request_delays" not in config:
        config["request_delays"] = {}

    # Override basic settings but preserve any custom settings
    for component, delays in delay_settings.items():
        if component == "ai1":
            if "ai1" not in config["request_delays"]:
                config["request_delays"]["ai1"] = {}
            config["request_delays"]["ai1"]["min"] = delays["min"]
            config["request_delays"]["ai1"]["max"] = delays["max"]
        elif component == "ai3":
            if "ai3" not in config["request_delays"]:
                config["request_delays"]["ai3"] = {}
            config["request_delays"]["ai3"]["min"] = delays["min"]
            config["request_delays"]["ai3"]["max"] = delays["max"]
        elif component.startswith("ai2_"):
            role = component.split("_")[
                1
            ]  # Extract 'executor', 'tester', or 'documenter'
            if "ai2" not in config["request_delays"]:
                config["request_delays"]["ai2"] = {}
            if role not in config["request_delays"]["ai2"]:
                config["request_delays"]["ai2"][role] = {}
            config["request_delays"]["ai2"][role]["min"] = delays["min"]
            config["request_delays"]["ai2"][role]["max"] = delays["max"]

    # Set the detected load level
    config["system_load_level"] = load_level

    logger.info(
        f"System configured for load level {load_level} ({_get_load_level_name(load_level)})"
    )
    return config


def _get_load_level_name(level: int) -> str:
    """
    Returns the name of the load level.

    Args:
        level: Load level (1-5)

    Returns:
        str: Name of the load level
    """
    level_names = {
        LOAD_LEVEL_MINIMAL: "Minimal",
        LOAD_LEVEL_LOW: "Low",
        LOAD_LEVEL_MEDIUM: "Medium",
        LOAD_LEVEL_HIGH: "High",
        LOAD_LEVEL_MAXIMUM: "Maximum",
    }
    return level_names.get(level, "Unknown")


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Loads the configuration from the specified path or the default path.
    Handles environment variable substitution and caches results for performance.

    Args:
        config_path: Optional path to the config file

    Returns:
        Dict: The loaded and processed configuration
    """
    global _config_cache, _config_file_path, _config_last_mtime

    file_path = config_path or _config_file_path

    try:
        # Check if file has been modified since last read
        current_mtime = os.path.getmtime(file_path)

        # Use cached config if the file hasn't changed
        if _config_cache is not None and current_mtime <= _config_last_mtime:
            return _config_cache

        # Read and parse the config file
        with open(file_path, "r", encoding="utf-8") as f:
            config_str = f.read()

        # Replace environment variables
        for key, value in os.environ.items():
            config_str = config_str.replace(f"${{{key}}}", value)

        # Parse JSON
        config = json.loads(config_str)

        # Add load level detection and dynamic delay adjustment
        config = adjust_delays_for_load_level(config)

        # Update cache
        _config_cache = config
        _config_last_mtime = current_mtime

        return config
    except Exception as e:
        logger.error(f"Failed to load config from {file_path}: {e}")
        # Return empty dict or a minimal default config
        return {"web_port": 7860}


def save_config(config: Dict[str, Any], config_path: Optional[str] = None) -> bool:
    """
    Saves the configuration to the specified path or the default path.

    Args:
        config: The configuration to save
        config_path: Optional path to the config file

    Returns:
        bool: True if the config was saved successfully, False otherwise
    """
    global _config_cache, _config_file_path, _config_last_mtime

    file_path = config_path or _config_file_path

    try:
        # Make a backup of the current config file
        if os.path.exists(file_path):
            backup_path = f"{file_path}.bak"
            with open(file_path, "r", encoding="utf-8") as src:
                with open(backup_path, "w", encoding="utf-8") as dst:
                    dst.write(src.read())

        # Write the updated config
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        # Update cache
        _config_cache = config
        _config_last_mtime = os.path.getmtime(file_path)

        logger.info(f"Config saved to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config to {file_path}: {e}")
        return False


def update_config_item(key: str, value: Any, config_path: Optional[str] = None) -> bool:
    """
    Updates a single item in the configuration and saves it.

    Args:
        key: The key to update
        value: The new value
        config_path: Optional path to the config file

    Returns:
        bool: True if the config was updated successfully, False otherwise
    """
    config = load_config(config_path)
    config[key] = value

    # If changing load-affecting settings, adjust delays
    if key in ["ai1_desired_active_buffer", "desired_active_buffer"]:
        config = adjust_delays_for_load_level(config)

    return save_config(config, config_path)


def get_config_item(
    key: str, default: Any = None, config_path: Optional[str] = None
) -> Any:
    """
    Gets a single item from the configuration.

    Args:
        key: The key to get
        default: The default value to return if the key is not found
        config_path: Optional path to the config file

    Returns:
        Any: The value of the key or the default value
    """
    config = load_config(config_path)
    return config.get(key, default)


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
