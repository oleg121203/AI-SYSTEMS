import json
import logging
import os
from typing import Any, Dict, Optional

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json"
)


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
