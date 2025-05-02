import asyncio
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, Type as TypingType

import aiohttp
from dotenv import load_dotenv

# Import SDKs at the top level
try:
    from together import Together, TogetherError
except ImportError:
    Together = None
    TogetherError = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import cohere
except ImportError:
    cohere = None

try:
    from groq import AsyncGroq, GroqError
    import groq # Ensure groq module itself is imported
except ImportError:
    AsyncGroq = None
    GroqError = None
    groq = None # Define groq as None if import fails

try:
    import anthropic
except ImportError:
    anthropic = None


# Initialize logger before using it
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Log warnings for missing optional dependencies
if Together is None:
    logger.warning(
        "Module 'together' is not installed. TogetherProvider will not work. Install it with: pip install together"
    )
if genai is None:
     logger.warning(
        "Module 'google-generativeai' is not installed. GeminiProvider will not work. Install it with: pip install google-generativeai"
    )
if cohere is None:
    logger.warning(
        "Module 'cohere' is not installed. CohereProvider will not work. Install it with: pip install cohere"
    )
if AsyncGroq is None or groq is None:
    logger.warning(
        "Module 'groq' is not installed. GroqProvider will not work. Install it with: pip install groq"
    )
if anthropic is None:
    logger.warning(
        "Module 'anthropic' is not installed. AnthropicProvider will not work. Install it with: pip install anthropic"
    )


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
        elif provider_type == "gemini3":
            return Gemini3Provider(provider_config)
        elif provider_type == "gemini4":
            return Gemini4Provider(provider_config)
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
                ),
            )

            # Add CodestralProvider check separately for Authorization header
            if isinstance(self, CodestralProvider) and self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Add Authorization header for non-SDK providers if API key exists and not already set
            # Check if _session exists and has headers before accessing them
            current_headers = self._session.headers if self._session else {}
            if hasattr(self, "api_key") and self.api_key and not is_sdk_provider and not isinstance(self, CodestralProvider) and "Authorization" not in current_headers:
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
        if not anthropic:
             logger.error(
                "Модуль anthropic не установлен. Установите его с помощью 'pip install anthropic'"
            )
             self.anthropic = None
             return

        self.anthropic = anthropic # Assign the imported module
        self.api_key = self.config.get("api_key") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        if not self.api_key:
            logger.warning(
                "API ключ Anthropic не найден ни в конфигурации, ни в ANTHROPIC_API_KEY."
            )
        else:
            logger.info("Anthropic настроен успешно")

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
        # Додамо словник для оптимізації використання ресурсів
        self._model_tiers = {
            "lightweight": ["llama3-8b-8192", "gemma-7b-it"],  # Легкі моделі
            "balanced": ["mixtral-8x7b-32768"],  # Балансні моделі
            "powerful": ["llama3-70b-8192", "llama-3.3-70b-versatile"]  # Потужні моделі
        }

    def setup(self) -> None:
        if not groq or not AsyncGroq: # Check both groq and AsyncGroq
             logger.error(
                "Модуль groq не установлен. Установите его с помощью 'pip install groq'"
            )
             self.groq = None
             return

        self.groq = groq # Assign the imported module
        self.api_key = self.config.get("api_key") or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            logger.warning(
                "API ключ Groq не найден ни в конфигурации, ни в GROQ_API_KEY."
            )
        else:
            logger.info("Groq настроен успешно")

    def get_client(self) -> Any:
        if not AsyncGroq or not self.groq: # Check both
            raise ValueError("Модуль groq не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Groq не установлен.")
        if self._client is None:
            import httpx  # Import httpx

            # Get proxy from config
            proxy_url = self.config.get("proxy")
            http_client_instance = None # Initialize http_client_instance to None
            if proxy_url:
                proxies = {"http://": proxy_url, "https://": proxy_url}
                logger.info(f"Using proxy {proxy_url} for Groq client.")
                # Create httpx.AsyncClient with proxies
                http_client_instance = httpx.AsyncClient(proxies=proxies)

            try:
                # Pass the custom http_client_instance ONLY if it was created (proxies are set)
                if http_client_instance:
                     self._client = self.groq.AsyncGroq(
                        api_key=self.api_key,
                        http_client=http_client_instance # Pass the created client
                    )
                else:
                    # Initialize without custom http_client if no proxy
                    self._client = self.groq.AsyncGroq(api_key=self.api_key)

                logger.info("Groq AsyncClient initialized successfully.")
            except Exception as e:
                logger.error(f"Error initializing Groq AsyncClient: {e}")
                # REMOVED: Manual closing of http_client_instance. The Groq client should manage this.
                raise ValueError(f"Failed to initialize Groq client: {e}")
        return self._client

    def select_optimal_model(self, prompt: str, requested_model: Optional[str] = None) -> str:
        """Selects the optimal model based on prompt complexity and specified model.

        Args:
            prompt: The input prompt text
            requested_model: The requested model (can be None)

        Returns:
            str: The model name to use
        """
        # If a specific model is requested, use it
        if requested_model:
            return requested_model

        # Get default model from configuration
        default_model = self.get_default_model()
        if default_model:
            return default_model

        # Evaluate prompt complexity based on length
        prompt_length = len(prompt)

        if prompt_length < 500:
            # For short prompts, use a lightweight model
            return self._model_tiers["lightweight"][0]
        elif prompt_length < 2000:
            # For medium prompts, use a balanced model
            return self._model_tiers["balanced"][0]
        else:
            # For complex prompts, use a powerful model
            return self._model_tiers["powerful"][0]

    def split_complex_prompt(self, prompt: str, max_length: int = 2000) -> List[str]:
        """Splits a complex prompt into smaller parts to optimize resource usage.

        Args:
            prompt: The input prompt
            max_length: Maximum length of each part

        Returns:
            List[str]: List of prompt parts
        """
        # If the prompt is short, return it as is
        if len(prompt) <= max_length:
            return [prompt]

        # Try to split by paragraphs
        paragraphs = prompt.split('\n\n')

        # Collect parts without exceeding the maximum length
        parts = []
        current_part = ""

        for paragraph in paragraphs:
            if len(current_part) + len(paragraph) + 2 <= max_length:
                if current_part:
                    current_part += "\n\n" + paragraph
                else:
                    current_part = paragraph
            else:
                if current_part:
                    parts.append(current_part)
                    current_part = paragraph
                else:
                    # If paragraph is longer than max_length, split by sentences
                    sentences = re.split(r'(?<=[.!?])\s+', paragraph)
                    current_sentence_group = ""

                    for sentence in sentences:
                        if len(current_sentence_group) + len(sentence) + 1 <= max_length:
                            if current_sentence_group:
                                current_sentence_group += " " + sentence
                            else:
                                current_sentence_group = sentence
                        else:
                            if current_sentence_group:
                                parts.append(current_sentence_group)
                                current_sentence_group = sentence
                            else:
                                # If sentence is too long, split it into chunks
                                sentence_parts = [sentence[i:i+max_length]
                                                  for i in range(0, len(sentence), max_length)]
                                parts.extend(sentence_parts)

                    if current_sentence_group:
                        parts.append(current_sentence_group)

        # Add the last part if it exists
        if current_part:
            parts.append(current_part)

        return parts

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.groq or not self.api_key: # Check self.groq
            return "Error: Groq provider not configured."

        # Use optimal model selection
        model_to_use = self.select_optimal_model(prompt, model)
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        # Flag for performance optimization
        enable_optimization = self.config.get("enable_optimization", True)

        # If the prompt is too complex and optimization is enabled, split it
        if enable_optimization and len(prompt) > 2000:
            parts = self.split_complex_prompt(prompt)

            # If the prompt was split into parts
            if len(parts) > 1:
                logger.info(f"Prompt split into {len(parts)} parts for optimization")
                responses = []

                # Process each part
                for i, part in enumerate(parts):
                    messages = []

                    # For the first part, add system prompt if it exists
                    if i == 0 and system_prompt:
                        messages.append({"role": "system", "content": system_prompt})

                    # Add context for all parts
                    if i > 0:
                        part_prompt = f"This is part {i+1} of {len(parts)} of the request. " + part
                    else:
                        part_prompt = part

                    messages.append({"role": "user", "content": part_prompt})

                    try:
                        client = self.get_client()
                        response = await client.chat.completions.create(
                            model=model_to_use,
                            messages=messages,
                            max_tokens=max_tokens_to_use,
                            temperature=temperature_to_use,
                        )
                        if response.choices and response.choices[0].message:
                            responses.append(response.choices[0].message.content or "")
                        else:
                            logger.warning(
                                f"Response from Groq for part {i+1} does not contain expected data"
                            )
                            responses.append("")
                    except Exception as e:
                        logger.error(f"Error processing part {i+1}: {e}")
                        responses.append(f"[Error processing part {i+1}]")

                # Combine results
                return "\n\n".join(responses)

        # Standard path - process the prompt without splitting
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
                    f"Response from Groq does not contain expected data: {response}"
                )
                return "Error: No valid response received from API."
        except self.groq.APIError as e: # Use self.groq
            logger.error(
                f"Groq API Error ({model_to_use}): Status={e.status_code}, Message={e.message}"
            )
            return f"Error (Groq API {e.status_code}): {e.message}"
        except Exception as e:
            logger.error(
                f"Error generating response with Groq ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Error: {str(e)}"

    def get_available_models(self) -> List[str]:
        # Додаємо модель llama-3.3-70b-versatile із прикладу запиту
        known = [
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma-7b-it",
            "llama-3.3-70b-versatile"
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

        response = None # Define response outside try block
        response_data = {} # Define response_data outside try block
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
            # Try to get more specific error from response if available
            if response and response.status != 200:
                try:
                    # Ensure response_data is populated if an error occurred after response started
                    if not response_data:
                         response_data = await response.json()
                    error_message = response_data.get("error", {}).get("message", e.message)
                except Exception:
                    # Fallback if response body is not JSON or other error
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
        # Removed finally block: session closing handled by __aexit__

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
        # self._session is managed by BaseProvider

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
                # Use host parameter for AsyncClient
                self._client = self.ollama.AsyncClient(host=self.endpoint)
                # Simple check to see if client is usable (e.g., list models)
                # Note: This makes setup async, which might require changes elsewhere
                # Alternatively, defer the check or make it synchronous if possible
                # For now, assume initialization implies usability
                self.use_sdk = True
                logger.info(
                    f"Ollama SDK настроен успешно для эндпоинта: {self.endpoint}"
                )
            except Exception as client_err:
                logger.warning(
                    f"Не удалось инициализировать Ollama AsyncClient ({client_err}). Попытка использовать REST API."
                )
                self._client = None
                self.ollama = None # Ensure ollama module is not used if client fails
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
        max_tokens: Optional[int] = None, # Ollama doesn't directly use max_tokens in chat
        temperature: Optional[float] = None,
    ) -> str:

        model_to_use = model or self.get_default_model() or "llama3"
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )
        # num_predict corresponds roughly to max_tokens, but behavior might differ
        num_predict = max_tokens or self.config.get("num_predict", -1) # Default -1 (no limit)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        options = {"temperature": temperature_to_use}
        if num_predict > 0:
            options["num_predict"] = num_predict


        response = None # Define response outside try block
        response_data = {} # Define response_data outside try block
        try:
            if self.use_sdk and self._client:
                response = await self._client.chat( # Assign to response
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
                # Use REST API
                session = await self.get_client_session()
                api_url = f"{self.endpoint}/api/chat"
                payload = {
                    "model": model_to_use,
                    "messages": messages,
                    "options": options,
                    "stream": False,
                }
                async with session.post(api_url, json=payload) as response: # Assign to inner response
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
            # Try to get more specific error from response if available (REST API case)
            if response and response.status != 200 and not self.use_sdk:
                 try:
                     # Ensure response_data is populated if an error occurred after response started
                     if not response_data:
                          response_data = await response.json()
                     error_message = response_data.get("error", e.message)
                 except Exception:
                     pass # Fallback if response body is not JSON or other error
            logger.error(
                f"Ollama REST API HTTP Error ({model_to_use}, {e.status}): {error_message}"
            )
            return f"Ошибка генерации ({e.status}): {error_message}"
        except aiohttp.ClientError as e:
             # This applies only to the REST API case
            logger.error(f"Ошибка соединения с Ollama REST API {self.endpoint}: {e}")
            return f"Ошибка генерации: Не удалось подключиться к Ollama REST API ({e})"
        except Exception as e:
            # Catch potential SDK errors or other unexpected errors
            sdk_or_rest = "SDK" if self.use_sdk else "REST API"
            logger.error(
                f"Ошибка при генерации ответа с помощью Ollama ({sdk_or_rest}, {model_to_use}): {e}",
                exc_info=True,
            )
            # Check if it's an Ollama SDK specific error if possible
            if self.ollama and hasattr(self.ollama, 'ResponseError') and isinstance(e, self.ollama.ResponseError):
                 return f"Ошибка генерации (Ollama SDK {e.status_code}): {e.error}"
            return f"Ошибка генерации: {str(e)}"
        # Removed finally block: session closing handled by __aexit__

    async def get_available_models(self) -> List[str]:
        default_models = ["llama3", "mistral"] # Provide some defaults
        try:
            if self.use_sdk and self._client:
                models_info = await self._client.list()
                # Ensure models_info and models_info['models'] exist
                return (
                    [model["name"] for model in models_info.get("models", []) if "name" in model]
                    if models_info and isinstance(models_info.get("models"), list)
                    else default_models
                )
            else:
                # Use REST API
                session = await self.get_client_session()
                api_url = f"{self.endpoint}/api/tags"
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                         # Ensure data['models'] exists and is a list
                        return (
                            [model["name"] for model in data.get("models", []) if "name" in model]
                             if isinstance(data.get("models"), list)
                             else default_models
                        )
                    else:
                        logger.error(
                            f"Ошибка при получении списка моделей Ollama REST API ({response.status}): {await response.text()}"
                        )
                        # Return defaults + configured model if API fails
                        base_models = super().get_available_models()
                        return list(set(default_models + base_models))
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей Ollama: {e}")
             # Return defaults + configured model on any exception
            base_models = super().get_available_models()
            return list(set(default_models + base_models))


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
            # Try a sensible default if none configured
            model_to_use = "openai/gpt-3.5-turbo"
            logger.warning(f"Модель для OpenRouter не указана, используется дефолтная: {model_to_use}")
            # return "Ошибка генерации: Модель для OpenRouter не указана." # Or allow default

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

        response = None # Define response outside try block
        response_data = {} # Define response_data outside try block
        try:
            session = await self.get_client_session()
            # OpenRouter requires API Key in Authorization header
            headers = {"Authorization": f"Bearer {self.api_key}"}
            # Add optional headers from config
            headers["HTTP-Referer"] = self.config.get("referer", "http://localhost") # Example referer
            headers["X-Title"] = self.config.get("title", "MCP-AI-App") # Example title

            async with session.post(api_url, json=payload, headers=headers) as response:
                response_data = await response.json()
                if response.status == 200:
                    if response_data.get("choices") and response_data["choices"][0].get("message"):
                        return response_data["choices"][0]["message"].get("content", "")
                    else:
                        logger.warning(
                            f"Ответ от OpenRouter API ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                        )
                        return "Ошибка генерации: Не получен корректный ответ от OpenRouter API."
                else:
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            error_message = e.message
             # Try to get more specific error from response if available
            if response and response.status != 200:
                try:
                     # Ensure response_data is populated if an error occurred after response started
                     if not response_data:
                          response_data = await response.json()
                     error_message = response_data.get("error", {}).get("message", e.message)
                except Exception:
                     pass # Fallback if response body is not JSON or other error
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
        # Removed finally block: session closing handled by __aexit__

    async def get_available_models(self) -> List[str]:
        # OpenRouter has many models, fetching them dynamically is best
        api_url = f"{self.endpoint}/models"
        try:
            session = await self.get_client_session()
            # OpenRouter requires API Key for listing models too
            headers = {"Authorization": f"Bearer {self.api_key}"}
            async with session.get(api_url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return [
                        model.get("id")
                        for model in data.get("data", [])
                        if model.get("id")
                    ]
                else:
                    logger.error(
                        f"Ошибка при получении списка моделей OpenRouter ({response.status}): {await response.text()}"
                    )
                    return super().get_available_models() # Fallback to configured model
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей OpenRouter: {e}")
            return super().get_available_models() # Fallback to configured model


class CohereProvider(BaseProvider):
    """Провайдер для Cohere."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "cohere"
        self._client = None

    def setup(self) -> None:
        if not cohere:
            logger.error("Модуль cohere не установлен. Установите его с помощью 'pip install cohere'")
            self.cohere = None
            return

        self.cohere = cohere
        self.api_key = self.config.get("api_key") or os.environ.get("COHERE_API_KEY")
        if not self.api_key:
            logger.warning("API ключ Cohere не найден ни в конфигурации, ни в COHERE_API_KEY.")
        else:
            logger.info("Cohere настроен успешно")

    def get_client(self) -> Any:
        if not self.cohere:
            raise ValueError("Модуль cohere не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Cohere не установлен.")
        if self._client is None:
            # Use AsyncClient for asynchronous operations
            self._client = self.cohere.AsyncClient(self.api_key)
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None, # Cohere uses 'preamble'
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.cohere or not self.api_key:
            return "Ошибка генерации: провайдер Cohere не настроен."

        model_to_use = model or self.get_default_model() or "command-r" # Default to command-r
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature if temperature is not None else self.config.get("temperature", 0.7)
        )

        try:
            client = self.get_client()
            # Use chat method for conversational generation
            response = await client.chat(
                message=prompt,
                model=model_to_use,
                preamble=system_prompt, # Use preamble for system context
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
                # Cohere might have different parameter names or capabilities
            )
            if response and hasattr(response, 'text'):
                return response.text
            else:
                 logger.warning(f"Ответ от Cohere не содержит ожидаемых данных: {response}")
                 return "Ошибка генерации: Не получен корректный ответ от Cohere API."

        except self.cohere.CohereAPIError as e: # Catch specific Cohere API errors
            logger.error(f"Cohere API Error ({model_to_use}): {e}")
            # Attempt to get status code if available
            status_code = getattr(e, 'http_status', 'N/A')
            return f"Ошибка генерации (Cohere API {status_code}): {e}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Cohere ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        # List known Cohere models
        known = ["command-r-plus", "command-r", "command", "command-light"]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class GeminiProvider(BaseProvider):
    """Провайдер для Google Gemini (используя SDK)."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "gemini"
        self._model_instance = None

    def setup(self) -> None:
        if not genai:
            logger.error("Модуль google-generativeai не установлен. Установите его: pip install google-generativeai")
            self.genai = None
            return

        self.genai = genai
        self.api_key = self.config.get("api_key") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("API ключ Gemini/Google не найден ни в конфигурации, ни в GEMINI_API_KEY/GOOGLE_API_KEY.")
        else:
            try:
                self.genai.configure(api_key=self.api_key)
                logger.info("Gemini SDK настроен успешно")
            except Exception as e:
                logger.error(f"Ошибка конфигурации Gemini SDK: {e}")
                self.genai = None # Mark as unusable if config fails

    def get_model(self, model_name: str) -> Any:
        if not self.genai:
            raise ValueError("Модуль google-generativeai не импортирован или не настроен.")

        # Cache the model instance? For now, create new each time.
        # Consider safety config from self.config if needed
        safety_settings = self.config.get("safety_settings") # Example: {"HARASSMENT": "BLOCK_NONE"}
        generation_config = self.config.get("generation_config") # Example: {"temperature": 0.7}

        try:
             # Combine generation_config from instance config and method args
             combined_gen_config = self.config.get("generation_config", {}).copy()
             # Method args like temperature/max_tokens override instance config
             # Note: SDK uses different names (e.g., max_output_tokens)

             model_instance = self.genai.GenerativeModel(
                 model_name=model_name,
                 safety_settings=safety_settings,
                 generation_config=generation_config # Pass base config here
             )
             return model_instance
        except Exception as e:
             logger.error(f"Не удалось создать экземпляр модели Gemini '{model_name}': {e}")
             raise ValueError(f"Не удалось создать экземпляр модели Gemini '{model_name}': {e}")


    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None, # Gemini uses system_instruction in start_chat or generate_content
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.genai or not self.api_key:
            return "Ошибка генерации: провайдер Gemini не настроен."

        # Default to gemini-1.5-flash-latest if no model specified
        model_to_use = model or self.get_default_model() or "gemini-1.5-flash-latest"

        try:
            model_instance = self.get_model(model_to_use)

            # Prepare generation config, overriding defaults with method args
            gen_config_overrides = {}
            if temperature is not None:
                gen_config_overrides["temperature"] = temperature
            if max_tokens is not None:
                gen_config_overrides["max_output_tokens"] = max_tokens

            # Combine system prompt and user prompt
            # Gemini SDK can take system instruction directly in generate_content
            contents = [prompt] # User prompt is the main content
            system_instruction_param = self.genai.types.Content(
                 parts=[self.genai.types.Part(text=system_prompt)],
                 role="system" # Role might not be needed if using system_instruction param
            ) if system_prompt else None


            # Use generate_content_async for async operation
            response = await model_instance.generate_content_async(
                contents=contents,
                generation_config=self.genai.types.GenerationConfig(**gen_config_overrides) if gen_config_overrides else None,
                system_instruction=system_instruction_param
            )

            # Extract text, handling potential blocks or errors
            if response and hasattr(response, 'text'):
                return response.text
            elif response and hasattr(response, 'parts'):
                 # If response has parts, concatenate their text
                 return "".join(part.text for part in response.parts if hasattr(part, 'text'))
            elif response and response.prompt_feedback and response.prompt_feedback.block_reason:
                 # Handle blocked prompts
                 reason = response.prompt_feedback.block_reason
                 logger.warning(f"Запрос к Gemini ({model_to_use}) был заблокирован: {reason}")
                 return f"Ошибка генерации: Запрос заблокирован ({reason})."
            else:
                logger.warning(f"Ответ от Gemini ({model_to_use}) не содержит ожидаемого текста: {response}")
                return "Ошибка генерации: Не получен корректный текстовый ответ от Gemini API."

        except Exception as e:
            # Catch potential API errors or other issues
            logger.error(
                f"Ошибка при генерации ответа с помощью Gemini ({model_to_use}): {e}",
                exc_info=True,
            )
            # Try to provide more specific feedback if possible (e.g., API key issues)
            if "API key not valid" in str(e):
                 return "Ошибка генерации: Недействительный API ключ Gemini/Google."
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        # List known/common Gemini models
        known = [
            "gemini-1.5-pro-latest",
            "gemini-1.5-flash-latest",
            "gemini-1.0-pro",
            "gemini-pro", # Alias for 1.0 pro?
        ]
        # Add configured model if not already listed
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)

        # Optionally, try to list models via SDK if configured
        # if self.genai:
        #     try:
        #         # This is synchronous, might block async flow if called often
        #         sdk_models = [m.name for m in self.genai.list_models() if 'generateContent' in m.supported_generation_methods]
        #         known = list(set(known + sdk_models)) # Combine and deduplicate
        #     except Exception as e:
        #         logger.warning(f"Не удалось получить список моделей через Gemini SDK: {e}")

        return known


class TogetherProvider(BaseProvider):
    """Провайдер для Together AI."""
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "together"
        self._client = None

    def setup(self) -> None:
        if not Together:
            logger.error("Модуль 'together' не установлен. Установите его: pip install together")
            self.together_sdk = None
            return

        self.together_sdk = Together # Assign the imported class
        self.api_key = self.config.get("api_key") or os.environ.get("TOGETHER_API_KEY")
        if not self.api_key:
            logger.warning("API ключ Together не найден ни в конфигурации, ни в TOGETHER_API_KEY.")
        else:
            try:
                self._client = self.together_sdk(api_key=self.api_key)
                logger.info("Together SDK настроен успешно")
            except TogetherError as e:
                logger.error(f"Ошибка инициализации Together SDK: {e}")
                self._client = None

    def get_client(self) -> Any:
        if not self._client:
            raise ValueError("Клиент Together SDK не инициализирован.")
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
            return "Ошибка генерации: Together SDK не инициализирован."

        model_to_use = model or self.get_default_model() or "together-gpt-3.5-turbo"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature if temperature is not None else self.config.get("temperature", 0.7)
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
                logger.warning(f"Ответ от Together SDK ({model_to_use}) не содержит ожидаемых данных: {response}")
                return "Ошибка генерации: Не получен корректный ответ от Together SDK."

        except TogetherError as e:
            logger.error(f"Together API Error ({model_to_use}): {e}")
            return f"Ошибка генерации (Together API): {e}"
        except Exception as e:
            logger.error(f"Ошибка при генерации ответа с Together SDK ({model_to_use}): {e}", exc_info=True)
            return f"Ошибка генерации: {str(e)}"

    def get_available_models(self) -> List[str]:
        if not self._client:
            logger.warning("Невозможно получить список моделей: Together SDK не инициализирован.")
            return super().get_available_models()

        try:
            models_list = self._client.models.list()
            return [model.id for model in models_list if hasattr(model, "id")]
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей Together: {e}")
            return super().get_available_models()


class CodestralProvider(BaseProvider):
    """Провайдер для Mistral Codestral (использует HTTP API)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "codestral"
        # Ensure endpoint is set, default if not provided
        if not self.endpoint:
            self.endpoint = "https://codestral.mistral.ai/v1"
            logger.info(f"Codestral endpoint not specified, using default: {self.endpoint}")
        else:
            # Ensure endpoint doesn't end with a slash
            self.endpoint = self.endpoint.rstrip('/')
            logger.info(f"Codestral endpoint configured: {self.endpoint}")

    def setup(self) -> None:
        # Check if this is the codestral2 provider and use its specific API key
        if self.name == "codestral2":
            self.api_key = (
                self.config.get("api_key")
                or os.environ.get("CODESTRAL2_API_KEY")
                or os.environ.get("MISTRAL_API_KEY")
            )
            if self.api_key:
                logger.info("API key for Codestral2 found.")
            else:
                logger.error(
                    "API key for Codestral2 not found in configuration or CODESTRAL2_API_KEY environment variable."
                )
        else:
            # Regular codestral provider
            self.api_key = (
                self.config.get("api_key")
                or os.environ.get("MISTRAL_API_KEY")
                or os.environ.get("CODESTRAL_API_KEY")
            )
            if not self.api_key:
                logger.error(
                    "API key for Codestral/Mistral not found in configuration or MISTRAL_API_KEY/CODESTRAL_API_KEY."
                )
            else:
                logger.info("API key for Codestral/Mistral found.")
                
        # No client initialization needed for HTTP API
        logger.info("CodestralProvider configured to use HTTP API.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.api_key:
            return "Ошибка генерации: API ключ Codestral/Mistral не установлен."
        if not self.endpoint:
            return "Ошибка генерации: Endpoint для Codestral не установлен."

        model_to_use = model or self.get_default_model() or "codestral-latest" # Default model
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 4096)
        temperature_to_use = temperature if temperature is not None else self.config.get("temperature", 0.7)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens_to_use,
            "temperature": temperature_to_use,
            "stream": False, # Assuming non-streaming for now
        }
        # Remove None values from payload
        payload = {k: v for k, v in payload.items() if v is not None}

        api_url = f"{self.endpoint}/chat/completions"

        try:
            session = await self.get_client_session()
            # Headers are now managed by get_client_session
            async with session.post(api_url, json=payload) as response:
                response_data = await response.json()
                if response.status == 200:
                    if response_data.get("choices") and response_data["choices"][0].get(
                        "message"
                    ):
                        return response_data["choices"][0]["message"].get("content", "")
                    else:
                        logger.warning(
                            f"Ответ от Codestral API ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                        )
                        return "Ошибка генерации: Не получен корректный ответ от Codestral API."
                else:
                    # Attempt to get error message from response
                    error_message = response_data.get("message", "Unknown API error")
                    logger.error(
                        f"Codestral API HTTP Error ({model_to_use}, {response.status}): {error_message}"
                    )
                    response.raise_for_status() # Raise exception for bad status

        except aiohttp.ClientResponseError as e:
            # Error message already logged above if possible
            error_message = e.message
            try:
                # Try to parse JSON error again just in case
                response_data = await e.response.json()
                error_message = response_data.get("message", e.message)
            except Exception:
                pass # Keep original message if JSON parsing fails
            return f"Ошибка генерации (Codestral API {e.status}): {error_message}"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с Codestral API {self.endpoint}: {e}")
            return f"Ошибка генерации: Не удалось подключиться к Codestral API ({e})"
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при генерации ответа с Codestral ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации (Codestral): {str(e)}"

    def get_available_models(self) -> List[str]:
        # Return a default list or the configured model, as we can't query the API without SDK easily
        known = ["codestral-latest", "codestral-2405"]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class Gemini3Provider(BaseProvider):
    """Провайдер для Google Gemini3 через прямі API запити."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "gemini3"
        self.api_key = os.environ.get("GEMINI3_API_KEY")  # Використовуємо змінну оточення

    def setup(self) -> None:
        logger.info("Gemini3Provider налаштований через прямі API запити")
        if not self.api_key:
            logger.error("API ключ для Gemini3 не встановлено в змінній оточення GEMINI3_API_KEY")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        model_to_use = model or self.get_default_model() or "gemini-2.0-flash"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 4096)
        temperature_to_use = temperature if temperature is not None else self.config.get("temperature", 0.7)

        # Формуємо вміст запиту
        content = {"parts": [{"text": prompt}]}
        
        # Додаємо системний промпт, якщо він є
        if (system_prompt):
            payload = {
                "contents": [
                    {"parts": [{"text": system_prompt}]},
                    content
                ],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use
                }
            }
        else:
            payload = {
                "contents": [content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use
                }
            }

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:generateContent?key={self.api_key}"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    response_data = await response.json()
                    
                    # Витягуємо текст відповіді
                    if (response_data.get("candidates") and 
                        response_data["candidates"][0].get("content") and 
                        response_data["candidates"][0]["content"].get("parts")):
                        
                        text_parts = []
                        for part in response_data["candidates"][0]["content"]["parts"]:
                            if part.get("text"):
                                text_parts.append(part["text"])
                        
                        return "".join(text_parts)
                    else:
                        logger.warning(
                            f"Відповідь від Gemini3 API не містить очікуваних даних: {response_data}"
                        )
                        return "Помилка генерації: Не отримано коректну відповідь від Gemini3 API."
                else:
                    error_data = await response.json()
                    error_message = error_data.get("error", {}).get("message", "Невідома помилка")
                    logger.error(f"Gemini3 API HTTP помилка ({response.status}): {error_message}")
                    return f"Помилка генерації (Gemini3 API {response.status}): {error_message}"
                    
        except aiohttp.ClientError as e:
            logger.error(f"Помилка з'єднання з Gemini3 API: {e}")
            return f"Помилка генерації: Не вдалося підключитися до Gemini3 API ({e})"
        except Exception as e:
            logger.error(f"Несподівана помилка при генерації відповіді з Gemini3: {e}", exc_info=True)
            return f"Помилка генерації: {str(e)}"

    def get_available_models(self) -> List[str]:
        return ["gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-flash", "gemini-1.5-pro"]


class Gemini4Provider(BaseProvider):
    """Провайдер для Google Gemini4 через прямі API запити, використовується для AI2 документатора."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "gemini4"
        self.api_key = os.environ.get("GEMINI4_API_KEY")  # Використовуємо змінну оточення

    def setup(self) -> None:
        logger.info("Gemini4Provider налаштований через прямі API запити для документації")
        if not self.api_key:
            logger.error("API ключ для Gemini4 не встановлено в змінній оточення GEMINI4_API_KEY")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        model_to_use = model or self.get_default_model() or "gemini-2.0-pro"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 4096)
        temperature_to_use = temperature if temperature is not None else self.config.get("temperature", 0.7)

        # Формуємо вміст запиту
        content = {"parts": [{"text": prompt}]}
        
        # Додаємо системний промпт, якщо він є
        if (system_prompt):
            payload = {
                "contents": [
                    {"parts": [{"text": system_prompt}]},
                    content
                ],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use
                }
            }
        else:
            payload = {
                "contents": [content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use
                }
            }

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:generateContent?key={self.api_key}"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    response_data = await response.json()
                    
                    # Витягуємо текст відповіді
                    if (response_data.get("candidates") and 
                        response_data["candidates"][0].get("content") and 
                        response_data["candidates"][0]["content"].get("parts")):
                        
                        text_parts = []
                        for part in response_data["candidates"][0]["content"]["parts"]:
                            if part.get("text"):
                                text_parts.append(part["text"])
                        
                        return "".join(text_parts)
                    else:
                        logger.warning(
                            f"Відповідь від Gemini4 API не містить очікуваних даних: {response_data}"
                        )
                        return "Помилка генерації: Не отримано коректну відповідь від Gemini4 API."
                else:
                    error_data = await response.json()
                    error_message = error_data.get("error", {}).get("message", "Невідома помилка")
                    logger.error(f"Gemini4 API HTTP помилка ({response.status}): {error_message}")
                    return f"Помилка генерації (Gemini4 API {response.status}): {error_message}"
                    
        except aiohttp.ClientError as e:
            logger.error(f"Помилка з'єднання з Gemini4 API: {e}")
            return f"Помилка генерації: Не вдалося підключитися до Gemini4 API ({e})"
        except Exception as e:
            logger.error(f"Несподівана помилка при генерації відповіді з Gemini4: {e}", exc_info=True)
            return f"Помилка генерації: {str(e)}"

    def get_available_models(self) -> List[str]:
        return ["gemini-2.0-pro", "gemini-1.5-pro", "gemini-1.5-flash"]


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
