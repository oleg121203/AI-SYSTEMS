import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from dotenv import load_dotenv

# Определяем логгер *перед* его использованием
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Попытка импорта специфичных для провайдеров библиотек
try:
    from together import Together, TogetherError
except ImportError:
    logger.warning(
        "Модуль 'together' не установлен. TogetherProvider не будет работать. Установите его: pip install together"
    )
    Together = None
    TogetherError = None

try:
    import google.generativeai as genai
except ImportError:
    logger.warning(
        "Модуль 'google-generativeai' не установлен. GeminiProvider не будет работать. Установите его: pip install google-generativeai"
    )
    genai = None

try:
    import cohere
except ImportError:
    logger.warning(
        "Модуль 'cohere' не установлен. CohereProvider не будет работать. Установите его: pip install cohere"
    )
    cohere = None

try:
    from groq import AsyncGroq, GroqError
except ImportError:
    logger.warning(
        "Модуль 'groq' не установлен. GroqProvider не будет работать. Установите его: pip install groq"
    )
    AsyncGroq = None
    GroqError = None

try:
    from mistralai.async_client import MistralAsyncClient
    from mistralai.models.chat_completion import ChatMessage
except ImportError:
    logger.warning(
        "Модуль 'mistralai' не установлен. CodestralProvider не будет работать. Установите его: pip install mistralai"
    )
    MistralAsyncClient = None
    ChatMessage = None

load_dotenv()


class ProviderFactory:
    """Фабрика для создания экземпляров провайдеров AI."""

    @staticmethod
    def create_provider(
        provider_name: str, config: Optional[Dict[str, Any]] = None
    ) -> "BaseProvider":
        """
        Создает экземпляр провайдера AI по имени.

        Args:
            provider_name: Имя провайдера из секции "providers" в config.json
                           или прямое название типа провайдера
            config: Дополнительная конфигурация для провайдера (необязательно)

        Returns:
            BaseProvider: Экземпляр провайдера

        Raises:
            ValueError: Если тип провайдера не поддерживается или конфигурация отсутствует
        """
        # Загружаем общую конфигурацию
        try:
            from config import load_config

            all_config = load_config()
            providers_config = all_config.get("providers", {})
        except Exception as e:
            logger.warning(
                f"Не удалось загрузить конфигурацию: {e}. Используем переданную конфигурацию."
            )
            providers_config = {}

        # Пытаемся найти конфигурацию провайдера
        provider_config = None

        # Сначала ищем напрямую в секции "providers"
        if provider_name in providers_config:
            provider_config = providers_config[provider_name]
        else:
            # Если не нашли, ищем провайдер по типу
            for name, cfg in providers_config.items():
                if cfg.get("type") == provider_name:
                    provider_config = cfg
                    break

        # Если конфигурация всё еще не найдена, используем переданную
        if not provider_config:
            provider_config = config or {}

        # Если передана дополнительная конфигурация, применяем её
        if config:
            provider_config = {**provider_config, **config}

        # Убеждаемся, что есть тип провайдера
        provider_type = provider_config.get("type", provider_name).lower()

        logger.info(
            f"Creating provider instance for '{provider_name}' with type '{provider_type}'"
        )

        # Создаем экземпляр провайдера в зависимости от типа
        if provider_type == "openai":
            return OpenAIProvider(provider_config)
        elif provider_type == "anthropic":
            return AnthropicProvider(provider_config)
        elif provider_type == "groq":
            return GroqProvider(provider_config)
        elif provider_type == "local":
            return LocalProvider(provider_config)
        elif provider_type == "ollama":
            return OllamaProvider(provider_config)
        elif provider_type == "openrouter":
            return OpenRouterProvider(provider_config)
        elif provider_type == "cohere":
            return CohereProvider(provider_config)
        elif provider_type == "gemini":
            return GeminiProvider(provider_config)
        elif provider_type == "together":
            return TogetherProvider(provider_config)
        elif provider_type == "codestral":
            return CodestralProvider(provider_config)
        else:
            raise ValueError(f"Неподдерживаемый тип провайдера: {provider_type}")


class BaseProvider(ABC):
    """Базовый класс для всех провайдеров AI."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Инициализация провайдера.

        Args:
            config: Параметры конфигурации провайдера (из config.json["providers"][provider_name])
        """
        self.config = config or {}
        self.name = self.config.get("type", "base")
        self.model = self.config.get("model")
        self.api_key = self.config.get("api_key")
        self.endpoint = self.config.get("endpoint")
        self._session: Optional[aiohttp.ClientSession] = None
        self.setup()

    @abstractmethod
    def setup(self) -> None:
        """Настройка и проверка доступности провайдера."""
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Генерация ответа на запрос."""
        pass

    async def get_client_session(self) -> aiohttp.ClientSession:
        """Gets or creates an aiohttp client session."""
        if self._session is None or self._session.closed:
            headers = {}
            is_sdk_provider = isinstance(
                self,
                (
                    OpenAIProvider,
                    AnthropicProvider,
                    GroqProvider,
                    GeminiProvider,
                    CohereProvider,
                    TogetherProvider,
                    CodestralProvider,
                ),
            )

            if hasattr(self, "api_key") and self.api_key and not is_sdk_provider:
                current_headers = self._session.headers if self._session else {}
                if "Authorization" not in current_headers:
                    headers["Authorization"] = f"Bearer {self.api_key}"

            if isinstance(self, OpenRouterProvider):
                headers["HTTP-Referer"] = self.config.get("referer", "http://localhost")
                headers["X-Title"] = self.config.get("title", "MCP-AI-App")

            self._session = aiohttp.ClientSession(headers=headers)
            logger.debug(f"Created aiohttp session for {self.name}")
        return self._session

    async def close_session(self):
        """Closes the aiohttp client session if it exists."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info(f"Closed aiohttp session for {self.name}")
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_session()

    def get_available_models(self) -> List[str]:
        """Получение списка доступных моделей."""
        return [self.model] if self.model else []

    def get_default_model(self) -> Optional[str]:
        """Получение модели по умолчанию из конфигурации экземпляра."""
        return self.model


class OpenAIProvider(BaseProvider):
    """Провайдер для OpenAI."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "openai"
        self._client = None

    def setup(self) -> None:
        try:
            import openai

            self.openai = openai
            self.api_key = self.config.get("api_key") or os.environ.get(
                "OPENAI_API_KEY"
            )
            if not self.api_key:
                logger.warning(
                    "API ключ OpenAI не найден ни в конфигурации, ни в OPENAI_API_KEY."
                )
            else:
                logger.info("OpenAI настроен успешно (ключ найден)")
        except ImportError:
            logger.error(
                "Модуль openai не установлен. Установите его с помощью 'pip install openai'"
            )
            self.openai = None

    def get_client(self) -> Any:
        if not self.openai:
            raise ValueError("Модуль openai не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ OpenAI не установлен.")
        if self._client is None:
            self._client = self.openai.AsyncClient(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.openai:
            return "Ошибка генерации: модуль openai не импортирован."
        if not self.api_key:
            return "Ошибка генерации: API ключ OpenAI не установлен."

        model_to_use = model or self.get_default_model() or "gpt-4"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 2000
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            client = self.get_client()
            response = await client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            else:
                logger.warning(
                    f"Ответ от OpenAI не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от API."
        except self.openai.APIError as e:
            logger.error(
                f"OpenAI API Error ({model_to_use}): Status={e.status_code}, Message={e.message}"
            )
            return f"Ошибка генерации (OpenAI API {e.status_code}): {e.message}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью OpenAI ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        default_model = self.get_default_model()
        known_models = ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
        if default_model and default_model not in known_models:
            known_models.append(default_model)
        return known_models


class AnthropicProvider(BaseProvider):
    """Провайдер для Anthropic."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "anthropic"
        self._client = None

    def setup(self) -> None:
        try:
            import anthropic

            self.anthropic = anthropic
            self.api_key = self.config.get("api_key") or os.environ.get(
                "ANTHROPIC_API_KEY"
            )
            if not self.api_key:
                logger.warning(
                    "API ключ Anthropic не найден ни в конфигурации, ни в ANTHROPIC_API_KEY."
                )
            else:
                logger.info("Anthropic настроен успешно")
        except ImportError:
            logger.error(
                "Модуль anthropic не установлен. Установите его с помощью 'pip install anthropic'"
            )
            self.anthropic = None

    def get_client(self) -> Any:
        if not self.anthropic:
            raise ValueError("Модуль anthropic не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Anthropic не установлен.")
        if self._client is None:
            self._client = self.anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.anthropic or not self.api_key:
            return "Ошибка генерации: провайдер Anthropic не настроен."

        model_to_use = model or self.get_default_model() or "claude-3-sonnet-20240229"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = [{"role": "user", "content": prompt}]
        system_param = {"system": system_prompt} if system_prompt else {}

        try:
            client = self.get_client()
            response = await client.messages.create(
                model=model_to_use,
                messages=messages,
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
                **system_param,
            )
            if (
                response.content
                and isinstance(response.content, list)
                and len(response.content) > 0
            ):
                text_block = next(
                    (
                        block.text
                        for block in response.content
                        if hasattr(block, "text")
                    ),
                    None,
                )
                return text_block or ""
            else:
                logger.warning(
                    f"Ответ от Anthropic не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от API."
        except self.anthropic.APIError as e:
            logger.error(
                f"Anthropic API Error ({model_to_use}): Status={e.status_code}, Message={e.message}"
            )
            return f"Ошибка генерации (Anthropic API {e.status_code}): {e.message}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Anthropic ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        known = [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class GroqProvider(BaseProvider):
    """Провайдер для Groq."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "groq"
        self._client = None

    def setup(self) -> None:
        try:
            import groq

            self.groq = groq
            self.api_key = self.config.get("api_key") or os.environ.get("GROQ_API_KEY")
            if not self.api_key:
                logger.warning(
                    "API ключ Groq не найден ни в конфигурации, ни в GROQ_API_KEY."
                )
            else:
                logger.info("Groq настроен успешно")
        except ImportError:
            logger.error(
                "Модуль groq не установлен. Установите его с помощью 'pip install groq'"
            )
            self.groq = None

    def get_client(self) -> Any:
        if not self.groq:
            raise ValueError("Модуль groq не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Groq не установлен.")
        if self._client is None:
            self._client = self.groq.AsyncGroq(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.groq or not self.api_key:
            return "Ошибка генерации: провайдер Groq не настроен."

        model_to_use = model or self.get_default_model() or "llama3-70b-8192"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 8192
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            client = self.get_client()
            response = await client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            else:
                logger.warning(
                    f"Ответ от Groq не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от API."
        except self.groq.APIError as e:
            logger.error(
                f"Groq API Error ({model_to_use}): Status={e.status_code}, Message={e.message}"
            )
            return f"Ошибка генерации (Groq API {e.status_code}): {e.message}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Groq ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        known = [
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma-7b-it",
        ]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class LocalProvider(BaseProvider):
    """Провайдер для локальных моделей (OpenAI-совместимый API)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "local"

    def setup(self) -> None:
        if not self.endpoint:
            self.endpoint = "http://localhost:8000/v1"
            logger.warning(
                f"Endpoint для LocalProvider не указан, используется дефолтный: {self.endpoint}"
            )
        else:
            logger.info(f"Локальный провайдер настроен на эндпоинт: {self.endpoint}")
        if self.api_key:
            logger.warning(
                "API ключ указан для LocalProvider, но обычно не используется."
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:

        model_to_use = model or self.get_default_model() or "local-model"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 2000
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens_to_use,
            "temperature": temperature_to_use,
            "stream": False,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        api_url = f"{self.endpoint}/chat/completions"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                response_data = await response.json()
                if response.status == 200:
                    if response_data.get("choices") and response_data["choices"][0].get(
                        "message"
                    ):
                        return response_data["choices"][0]["message"].get("content", "")
                    else:
                        logger.warning(
                            f"Ответ от локального API ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                        )
                        return "Ошибка генерации: Не получен корректный ответ от локального API."
                else:
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            error_message = e.message
            try:
                response_data = await e.response.json()
                error_message = response_data.get("error", {}).get("message", e.message)
            except Exception:
                pass
            logger.error(
                f"Local API HTTP Error ({model_to_use}, {e.status}): {error_message}"
            )
            return f"Ошибка генерации ({e.status}): {error_message}"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с локальным API {self.endpoint}: {e}")
            return f"Ошибка генерации: Не удалось подключиться к локальному API ({e})"
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при генерации ответа с локальной моделью ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    async def get_available_models(self) -> List[str]:
        api_url = f"{self.endpoint}/models"
        try:
            session = await self.get_client_session()
            async with session.get(api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return [
                        model.get("id")
                        for model in data.get("data", [])
                        if model.get("id")
                    ]
                else:
                    logger.error(
                        f"Ошибка при получении списка локальных моделей ({response.status}): {await response.text()}"
                    )
                    return super().get_available_models()
        except Exception as e:
            logger.error(f"Ошибка при получении списка локальных моделей: {e}")
            return super().get_available_models()


class OllamaProvider(BaseProvider):
    """Провайдер для Ollama."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "ollama"
        self._client = None
        self._session = None

    def setup(self) -> None:
        if not self.endpoint:
            self.endpoint = "http://localhost:11434"
            logger.warning(
                f"Endpoint для OllamaProvider не указан, используется дефолтный: {self.endpoint}"
            )
        else:
            self.endpoint = (
                self.endpoint.replace("/api/generate", "")
                .replace("/api/chat", "")
                .rstrip("/")
            )
            logger.info(f"Ollama провайдер настроен на эндпоинт: {self.endpoint}")

        self.use_sdk = False
        try:
            import ollama

            self.ollama = ollama
            try:
                self._client = self.ollama.AsyncClient(host=self.endpoint)
                self.use_sdk = True
                logger.info(
                    f"Ollama SDK настроен успешно для эндпоинта: {self.endpoint}"
                )
            except Exception as client_err:
                logger.warning(
                    f"Не удалось инициализировать Ollama AsyncClient ({client_err}). Попытка использовать REST API."
                )
                self._client = None
        except ImportError:
            logger.warning(
                "Модуль ollama не установлен. Будет использоваться REST API."
            )
            self.ollama = None

        if not self.use_sdk:
            logger.info(f"Ollama настроен на использование REST API: {self.endpoint}")

    def get_client(self) -> Any:
        if self.use_sdk and self._client:
            return self._client
        elif self.use_sdk and not self._client:
            raise ValueError("Клиент Ollama SDK не был успешно инициализирован.")
        else:
            raise NotImplementedError(
                "Метод get_client не применим при использовании Ollama через REST API. Используйте get_client_session."
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:

        model_to_use = model or self.get_default_model() or "llama3"
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        options = {"temperature": temperature_to_use}

        try:
            if self.use_sdk and self._client:
                response = await self._client.chat(
                    model=model_to_use, messages=messages, options=options
                )
                if response and isinstance(response, dict) and response.get("message"):
                    return response["message"].get("content", "")
                else:
                    logger.warning(
                        f"Ответ от Ollama SDK ({model_to_use}) не содержит ожидаемых данных: {response}"
                    )
                    return (
                        "Ошибка генерации: Не получен корректный ответ от Ollama SDK."
                    )
            else:
                session = await self.get_client_session()
                api_url = f"{self.endpoint}/api/chat"
                payload = {
                    "model": model_to_use,
                    "messages": messages,
                    "options": options,
                    "stream": False,
                }
                async with session.post(api_url, json=payload) as response:
                    response_data = await response.json()
                    if response.status == 200:
                        if (
                            response_data
                            and isinstance(response_data, dict)
                            and response_data.get("message")
                        ):
                            return response_data["message"].get("content", "")
                        else:
                            logger.warning(
                                f"Ответ от Ollama REST API ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                            )
                            return "Ошибка генерации: Не получен корректный ответ от Ollama REST API."
                    else:
                        response.raise_for_status()

        except aiohttp.ClientResponseError as e:
            error_message = e.message
            try:
                response_data = await e.response.json()
                error_message = response_data.get("error", e.message)
            except Exception:
                pass
            logger.error(
                f"Ollama REST API HTTP Error ({model_to_use}, {e.status}): {error_message}"
            )
            return f"Ошибка генерации ({e.status}): {error_message}"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с Ollama REST API {self.endpoint}: {e}")
            return f"Ошибка генерации: Не удалось подключиться к Ollama REST API ({e})"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Ollama ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    async def get_available_models(self) -> List[str]:
        default_models = ["llama3", "mistral"]
        try:
            if self.use_sdk and self._client:
                models_info = await self._client.list()
                return (
                    [model["name"] for model in models_info.get("models", [])]
                    if models_info
                    else default_models
                )
            else:
                session = await self.get_client_session()
                api_url = f"{self.endpoint}/api/tags"
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [model["name"] for model in data.get("models", [])]
                    else:
                        logger.error(
                            f"Ошибка при получении списка моделей Ollama REST API ({response.status}): {await response.text()}"
                        )
                        return default_models + super().get_available_models()
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей Ollama: {e}")
            return default_models + super().get_available_models()


class OpenRouterProvider(BaseProvider):
    """Провайдер для OpenRouter (OpenAI-совместимый API)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "openrouter"

    def setup(self) -> None:
        if not self.endpoint:
            self.endpoint = "https://openrouter.ai/api/v1"
            logger.warning(
                f"Endpoint для OpenRouterProvider не указан, используется дефолтный: {self.endpoint}"
            )
        else:
            logger.info(f"OpenRouter провайдер настроен на эндпоинт: {self.endpoint}")

        if not self.api_key:
            self.api_key = os.environ.get("OPENROUTER_API_KEY")
            if not self.api_key:
                logger.error(
                    "API ключ для OpenRouter не найден ни в конфигурации, ни в OPENROUTER_API_KEY."
                )
            else:
                logger.info("API ключ для OpenRouter найден в переменной окружения.")
        else:
            logger.info("API ключ для OpenRouter найден в конфигурации.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.api_key:
            return "Ошибка генерации: API ключ OpenRouter не установлен."

        model_to_use = model or self.get_default_model()
        if not model_to_use:
            return "Ошибка генерации: Модель для OpenRouter не указана."

        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens_to_use,
            "temperature": temperature_to_use,
            "stream": False,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        api_url = f"{self.endpoint}/chat/completions"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                response_data = await response.json()
                if response.status == 200:
                    if response_data.get("choices") and response_data["choices"][0].get(
                        "message"
                    ):
                        return response_data["choices"][0]["message"].get("content", "")
                    else:
                        logger.warning(
                            f"Ответ от OpenRouter ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                        )
                        return "Ошибка генерации: Не получен корректный ответ от OpenRouter API."
                else:
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            error_message = e.message
            try:
                response_data = await e.response.json()
                error_message = response_data.get("error", {}).get("message", e.message)
            except Exception:
                pass
            logger.error(
                f"OpenRouter API HTTP Error ({model_to_use}, {e.status}): {error_message}"
            )
            return f"Ошибка генерации ({e.status}): {error_message}"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с OpenRouter API {self.endpoint}: {e}")
            return f"Ошибка генерации: Не удалось подключиться к OpenRouter API ({e})"
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при генерации ответа с OpenRouter ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"


class CohereProvider(BaseProvider):
    """Провайдер для Cohere."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "cohere"
        self._client = None

    def setup(self) -> None:
        try:
            import cohere

            self.cohere = cohere
            self.api_key = self.config.get("api_key") or os.environ.get(
                "COHERE_API_KEY"
            )
            if not self.api_key:
                logger.error(
                    "API ключ Cohere не найден ни в конфигурации, ни в COHERE_API_KEY."
                )
            else:
                logger.info("Cohere настроен успешно")
        except ImportError:
            logger.error(
                "Модуль cohere не установлен. Установите его с помощью 'pip install cohere'"
            )
            self.cohere = None

    def get_client(self) -> Any:
        if not self.cohere:
            raise ValueError("Модуль cohere не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Cohere не установлен.")
        if self._client is None:
            self._client = self.cohere.AsyncClient(api_key=self.api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.cohere or not self.api_key:
            return "Ошибка генерации: провайдер Cohere не настроен."

        model_to_use = model or self.get_default_model() or "command-r"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.3)
        )

        try:
            client = self.get_client()
            response = await client.chat(
                model=model_to_use,
                message=prompt,
                preamble=system_prompt,
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
            )
            if response and hasattr(response, "text"):
                return response.text
            else:
                logger.warning(
                    f"Ответ от Cohere ({model_to_use}) не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от Cohere API."
        except self.cohere.CohereAPIError as e:
            logger.error(
                f"Cohere API Error ({model_to_use}): Status={e.http_status}, Message={e.message}"
            )
            return f"Ошибка генерации (Cohere API {e.http_status}): {e.message}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Cohere ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        known = ["command-r", "command-r-plus", "command", "command-light"]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class GeminiProvider(BaseProvider):
    """Провайдер для Google Gemini."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "gemini"
        self._model_client = None

    def setup(self) -> None:
        try:
            import google.generativeai as genai

            self.genai = genai
            self.api_key = self.config.get("api_key") or os.environ.get(
                "GEMINI_API_KEY"
            )
            if not self.api_key:
                logger.error(
                    "API ключ Gemini не найден ни в конфигурации, ни в GEMINI_API_KEY."
                )
            else:
                try:
                    self.genai.configure(api_key=self.api_key)
                    logger.info("Gemini настроен успешно")
                except Exception as config_e:
                    logger.error(f"Ошибка конфигурации Gemini SDK: {config_e}")
                    self.genai = None
        except ImportError:
            logger.error(
                "Модуль google-generativeai не установлен. Установите его с помощью 'pip install google-generativeai'"
            )
            self.genai = None

    def get_client(self, model_name: str) -> Any:
        if not self.genai:
            raise ValueError(
                "Модуль google.generativeai не импортирован или не настроен."
            )
        try:
            model_client = self.genai.GenerativeModel(model_name)
            return model_client
        except Exception as e:
            logger.error(
                f"Не удалось создать Gemini GenerativeModel для '{model_name}': {e}"
            )
            raise ValueError(f"Не удалось создать Gemini GenerativeModel: {e}")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.genai:
            return "Ошибка генерации: провайдер Gemini не настроен."

        model_to_use = model or self.get_default_model() or "gemini-1.5-flash"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens")
        temperature_to_use = (
            temperature if temperature is not None else self.config.get("temperature")
        )

        generation_config = {}
        if max_tokens_to_use is not None:
            generation_config["max_output_tokens"] = max_tokens_to_use
        if temperature_to_use is not None:
            generation_config["temperature"] = temperature_to_use

        contents = []
        if system_prompt:
            contents.append(system_prompt)
        contents.append(prompt)

        try:
            model_client = self.get_client(model_to_use)
            response = await model_client.generate_content_async(
                contents=contents,
                generation_config=(
                    self.genai.types.GenerationConfig(**generation_config)
                    if generation_config
                    else None
                ),
            )

            if response and hasattr(response, "text"):
                return response.text
            elif (
                response
                and response.candidates
                and response.candidates[0].content.parts
            ):
                return "".join(
                    part.text
                    for part in response.candidates[0].content.parts
                    if hasattr(part, "text")
                )
            else:
                block_reason = ""
                if (
                    response
                    and response.prompt_feedback
                    and hasattr(response.prompt_feedback, "block_reason")
                ):
                    block_reason = (
                        f" Block Reason: {response.prompt_feedback.block_reason}"
                    )
                logger.warning(
                    f"Ответ от Gemini ({model_to_use}) не содержит текст.{block_reason} Response: {response}"
                )
                return (
                    f"Ошибка генерации: Не получен текст от Gemini API.{block_reason}"
                )
        except self.genai.types.generation_types.StopCandidateException as e:
            logger.error(f"Gemini Generation Stopped ({model_to_use}): {e}")
            return f"Ошибка генерации (Gemini Stop): {e}"
        except TypeError as e:
            logger.error(
                f"TypeError при вызове Gemini API ({model_to_use}): {e}", exc_info=True
            )
            return f"Ошибка генерации (TypeError): {e}"
        except Exception as e:
            error_detail = str(e)
            if hasattr(e, "message"):
                error_detail = e.message
            logger.error(
                f"Ошибка при генерации ответа с помощью Gemini ({model_to_use}): {error_detail}",
                exc_info=True,
            )
            return f"Ошибка генерации: {error_detail}"

    def get_available_models(self) -> List[str]:
        known = ["gemini-1.5-pro-latest", "gemini-1.5-flash-latest", "gemini-pro"]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class TogetherProvider(BaseProvider):
    """Провайдер для Together AI (использует официальный SDK)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "together"
        self._client = None

    def setup(self) -> None:
        if not Together:
            logger.error(
                "Библиотека 'together' не установлена. TogetherProvider не может быть настроен."
            )
            return

        self.api_key = self.config.get("api_key") or os.environ.get("TOGETHER_API_KEY")
        if not self.api_key:
            logger.error(
                "API ключ для Together AI не найден ни в конфигурации, ни в TOGETHER_API_KEY."
            )
        else:
            logger.info("API ключ для Together AI найден.")
            try:
                self._client = Together(api_key=self.api_key)
                logger.info("Together AI SDK настроен успешно.")
            except Exception as e:
                logger.error(f"Ошибка инициализации клиента Together AI SDK: {e}")
                self._client = None

    def get_client(self) -> Any:
        if not self._client:
            raise ValueError(
                "Клиент Together AI SDK не инициализирован (проверьте API ключ и установку библиотеки)."
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self._client:
            return "Ошибка генерации: Клиент Together AI SDK не инициализирован."

        model_to_use = model or self.get_default_model()
        if not model_to_use:
            return "Ошибка генерации: Модель для Together AI не указана."

        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            client = self.get_client()
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model_to_use,
                    messages=messages,
                    max_tokens=max_tokens_to_use,
                    temperature=temperature_to_use,
                ),
            )

            if response and response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            else:
                logger.warning(
                    f"Ответ от Together AI SDK ({model_to_use}) не содержит ожидаемых данных: {response}"
                )
                return (
                    "Ошибка генерации: Не получен корректный ответ от Together AI SDK."
                )

        except TogetherError as e:
            logger.error(f"Ошибка API Together AI ({model_to_use}): {e}")
            return f"Ошибка генерации (Together API): {e}"
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при генерации ответа с Together AI SDK ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        if not self._client:
            logger.warning(
                "Невозможно получить список моделей: клиент Together AI не инициализирован."
            )
            return super().get_available_models()

        try:
            models_list = self._client.models.list()
            return [model.id for model in models_list if hasattr(model, "id")]
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей Together AI: {e}")
            return super().get_available_models()


class CodestralProvider(BaseProvider):
    """Провайдер для Mistral Codestral (использует mistralai SDK)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "codestral"
        self._client: Optional[MistralAsyncClient] = None

    def setup(self) -> None:
        if not MistralAsyncClient or not ChatMessage:
            logger.error(
                "Компоненты 'mistralai' (MistralAsyncClient, ChatMessage) не установлены или не импортированы. CodestralProvider не может быть настроен."
            )
            return

        self.api_key = (
            self.config.get("api_key")
            or os.environ.get("MISTRAL_API_KEY")
            or os.environ.get("CODESTRAL_API_KEY")
        )
        if not self.api_key:
            logger.error(
                "API ключ для Codestral/Mistral не найден ни в конфигурации, ни в MISTRAL_API_KEY/CODESTRAL_API_KEY."
            )
        else:
            logger.info("API ключ для Codestral/Mistral найден.")
            try:
                self._client = MistralAsyncClient(api_key=self.api_key)
                logger.info("Mistral AI AsyncClient настроен успешно.")
            except Exception as e:
                logger.error(f"Ошибка инициализации Mistral AI AsyncClient: {e}")
                self._client = None

    def get_client(self) -> MistralAsyncClient:
        if not self._client:
            raise ValueError(
                "Клиент Mistral AI AsyncClient не инициализирован (проверьте API ключ и установку библиотеки)."
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self._client or not ChatMessage:
            return "Ошибка генерации: Клиент Mistral AI SDK не инициализирован или компоненты не импортированы."

        model_to_use = model or self.get_default_model() or "codestral-latest"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        messages = []
        if system_prompt:
            messages.append(
                ChatMessage(
                    role="user",
                    content=f"System Instructions: {system_prompt}\n\nUser Request: {prompt}",
                )
            )
        else:
            messages.append(ChatMessage(role="user", content=prompt))

        try:
            client = self.get_client()
            response = await client.chat(
                model=model_to_use,
                messages=messages,
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
            )

            if response and response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            else:
                logger.warning(
                    f"Ответ от Mistral AI SDK ({model_to_use}) не содержит ожидаемых данных: {response}"
                )
                return (
                    "Ошибка генерации: Не получен корректный ответ от Mistral AI SDK."
                )

        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с Mistral AI SDK ({model_to_use}): {e}",
                exc_info=True,
            )
            error_message = str(e)
            if hasattr(e, "message"):
                error_message = e.message
            return f"Ошибка генерации (Mistral API): {error_message}"


try:
    from config import load_config
except ImportError:
    logger.warning(
        "Не удалось импортировать load_config из config.py. ProviderFactory может не работать без явной передачи config."
    )

    def load_config():
        logger.error("Функция load_config не импортирована.")
        return {}


class Report:
    def __init__(
        self,
        task_id,
        file_path,
        role,
        message,
        processing_time=None,
        content=None,
        error_message=None,
    ):
        self.task_id = task_id
        self.file_path = file_path
        self.role = role
        self.message = message
        self.processing_time = processing_time
        self.content = content
        self.error_message = error_message
        # Добавить статус на основе наличия ошибки
        self.status = "error" if error_message else "completed"
