import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from typing import Type as TypingType  # Keep for now, though seems unused
from typing import Union

from dotenv import load_dotenv

# Attempt to import SDKs with error handling
# These will be assigned to None if import fails, and logged later
try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import httpx
except ImportError:
    httpx = None

try:
    import openai
except ImportError:
    openai = None

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import cohere
except ImportError:
    cohere = None

try:
    import groq
    from groq import AsyncGroq, GroqError
except ImportError:
    groq = None
    AsyncGroq = None
    GroqError = None

try:
    import ollama
except ImportError:
    ollama = None

Together = None
TogetherError = None  # Custom error for Together
try:
    from together import Together

    class TogetherCustomError(
        Exception
    ):  # Renamed to avoid conflict if 'TogetherError' exists in SDK
        """Custom error class for Together AI API errors"""

        def __init__(self, message, status_code=None):
            self.message = message
            self.status_code = status_code
            super().__init__(self.message)

    TogetherError = TogetherCustomError  # Assign custom error
except ImportError:
    # Together SDK not found, Together remains None
    pass

# Initialize logger (MUST be done after importing logging module)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Corrected typo: levellevelname -> levelname
)
logger = logging.getLogger(__name__)

# Log warnings for missing optional dependencies (NOW that logger is defined)
if aiohttp is None:
    logger.warning(
        "Module 'aiohttp' is not installed. Some providers might not work. Install it with: pip install aiohttp"
    )
if httpx is None:
    logger.warning(
        "Module 'httpx' is not installed. Some providers might not work. Install it with: pip install httpx"
    )
if openai is None:
    logger.warning(
        "Module 'openai' is not installed. OpenAIProvider will not work. Install it with: pip install openai"
    )
if anthropic is None:
    logger.warning(
        "Module 'anthropic' is not installed. AnthropicProvider will not work. Install it with: pip install anthropic"
    )
if genai is None:
    logger.warning(
        "Module 'google-generativeai' is not installed. GeminiProvider will not work. Install it with: pip install google-generativeai"
    )
if cohere is None:
    logger.warning(
        "Module 'cohere' is not installed. CohereProvider will not work. Install it with: pip install cohere"
    )
if groq is None or AsyncGroq is None:  # Check both groq and AsyncGroq
    logger.warning(
        "Module 'groq' is not installed. GroqProvider will not work. Install it with: pip install groq"
    )
if ollama is None:
    logger.warning(
        "Module 'ollama' is not installed. OllamaProvider might fall back to REST or fail. Install it with: pip install ollama"
    )
if Together is None:
    logger.warning(
        "Module 'together' is not installed. TogetherProvider will not work. Install it with: pip install together"
    )


load_dotenv()

# Import project-specific modules after standard/third-party and logging setup
try:
    from config import load_config
except ImportError:
    logger.error(
        "CRITICAL: Failed to import load_config from config.py. ProviderFactory will not work correctly."
    )

    def load_config():  # Fallback stub
        logger.error("CRITICAL: load_config stub called because import failed.")
        return {}


# Cache for storing available providers list
_available_providers_cache = None
_provider_models_cache = {}


def get_available_providers() -> List[str]:
    """Returns a list of available provider types."""
    global _available_providers_cache

    if _available_providers_cache is not None:
        return _available_providers_cache

    # Get all provider types from ProviderFactory
    available_providers = [
        "openai",
        "anthropic",
        "groq",
        "local",
        "ollama",
        "openrouter",
        "cohere",
        "gemini",
        "together",
        "codestral",
        "gemini3",
        "gemini4",
        "tugezer",
        "fallback",
    ]

    _available_providers_cache = available_providers
    return available_providers


async def get_provider_models(provider_name: str) -> List[str]:
    """Returns a list of available models for a provider."""
    global _provider_models_cache

    # Check cache first
    if provider_name in _provider_models_cache:
        return _provider_models_cache[provider_name]

    # Create a provider instance
    try:
        provider = ProviderFactory.create_provider(provider_name)
        models = await provider.get_available_models()

        # Cache the result
        _provider_models_cache[provider_name] = models
        return models
    except Exception as e:
        logger.error(f"Error getting models for provider {provider_name}: {e}")
        return []


async def reload_providers():
    """Reload providers and clear caches."""
    global _available_providers_cache, _provider_models_cache

    _available_providers_cache = None
    _provider_models_cache = {}

    # Force reload of available providers
    get_available_providers()

    logger.info("Provider caches cleared and reloaded")
    return True


class ProviderFactory:
    """Фабрика для создания экземпляров провайдеров AI."""

    @staticmethod
    def create_provider(
        provider_name: str,
        config_arg: Optional[Dict[str, Any]] = None,
        session: Optional[Any] = None,
    ) -> "BaseProvider":
        """
        Создает экземпляр провайдера AI по имени.

        Args:
            provider_name: Имя провайдера из секции "providers" в config.json
                           или прямое название типа провайдера
            config_arg: Дополнительная конфигурация для провайдера (необязательно),
                        будет объединена с конфигурацией из файла.
            session: Optional session object (ignored, for backward compatibility)

        Returns:
            BaseProvider: Экземпляр провайдера

        Raises:
            ValueError: Если тип провайдера не поддерживается или конфигурация некорректна.
        """
        try:
            from config import load_config

            all_config = load_config()
            providers_config = all_config.get("providers", {})
        except Exception as e:
            logger.warning(
                f"Не удалось загрузить общую конфигурацию: {e}. Будут использованы только переданные аргументы."
            )
            providers_config = {}

        effective_config = {}
        provider_type_from_config = None

        # 1. Check if provider_name is a key in the global providers_config
        if provider_name in providers_config:
            candidate_config = providers_config[provider_name]
            if isinstance(candidate_config, dict):
                effective_config = candidate_config.copy()  # Start with this config
                provider_type_from_config = effective_config.get("type")
            elif isinstance(candidate_config, str):
                # This case handles when the config for a provider_name is just a string (the type)
                # e.g., "ai1_fallback": "fallback"
                # We treat this string as the provider type.
                provider_type_from_config = candidate_config
                # effective_config remains empty for now, to be populated by config_arg or defaults
                logger.info(
                    f"Configuration for provider key '{provider_name}' is a string: '{candidate_config}'. "
                    f"Using this as the provider type."
                )
            else:
                logger.warning(
                    f"Configuration for provider key '{provider_name}' in 'providers' section "
                    f"is not a dictionary or string: {candidate_config}. "
                    f"Assuming '{provider_name}' is the type and ignoring this config entry."
                )
                # effective_config remains empty; type will be inferred from provider_name or config_arg

        # 2. Merge with config_arg if it's a dictionary.
        # This allows overriding or providing config directly.
        if isinstance(config_arg, dict):
            effective_config.update(config_arg)
        elif config_arg is not None:
            logger.warning(
                f"Non-dictionary 'config_arg' provided for provider '{provider_name}': {config_arg}. "
                "This argument will be ignored for merging."
            )

        # 3. Determine the provider type.
        # Priority:
        #   a) type from config_arg (if config_arg was a dict and had 'type')
        #   b) type from providers_config (if provider_name was a key and its value was a dict with 'type' or a string)
        #   c) provider_name itself as the type (if no 'type' was found above)
        provider_type = effective_config.get(
            "type", provider_type_from_config or provider_name
        ).lower()

        # Workaround for incorrect types that might be present in configuration
        if provider_type == "codestral2":
            logger.warning(
                "Provider type 'codestral2' was remapped to 'codestral'. "
                "Please ensure the 'type' in your provider configuration is correctly set to 'codestral'."
            )
            provider_type = "codestral"
        elif provider_type == "ollama1":
            logger.warning(
                "Provider type 'ollama1' was remapped to 'ollama'. "
                "Please ensure the 'type' in your provider configuration is correctly set to 'ollama'."
            )
            provider_type = "ollama"
        elif (
            provider_type == "structure_fallback"
        ):  # Handle if this is passed as a type directly
            logger.warning(
                "Provider type 'structure_fallback' was remapped to 'fallback'. "
                "Ensure 'structure_fallback' is a named provider configuration with 'type: fallback'."
            )
            provider_type = "fallback"

        logger.info(
            f"Creating provider instance for '{provider_name}' (resolved type: '{provider_type}') "
            # f"with effective config: {effective_config}" # Config can be verbose
        )

        # 4. Instantiate the provider based on provider_type
        if provider_type == "openai":
            return OpenAIProvider(effective_config)
        elif provider_type == "anthropic":
            return AnthropicProvider(effective_config)
        elif provider_type == "groq":
            return GroqProvider(effective_config)
        elif provider_type == "local":
            return LocalProvider(effective_config)
        elif provider_type == "ollama":
            return OllamaProvider(effective_config)
        elif provider_type == "openrouter":
            return OpenRouterProvider(effective_config)
        elif provider_type == "cohere":
            return CohereProvider(effective_config)
        elif provider_type == "gemini":
            return GeminiProvider(effective_config)
        elif provider_type == "together":
            return TogetherProvider(effective_config)
        elif provider_type == "codestral":
            return CodestralProvider(effective_config)
        elif provider_type == "gemini3":
            return Gemini3Provider(effective_config)
        elif provider_type == "gemini4":
            return Gemini4Provider(effective_config)
        elif provider_type == "tugezer":
            return TugezerProvider(effective_config)
        elif provider_type == "fallback":
            return FallbackProvider(effective_config)
        else:
            # Check for dynamically loaded provider plugins
            plugin_provider_class = get_provider_plugin(provider_type)
            if plugin_provider_class:
                return plugin_provider_class(effective_config)
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
        # self.setup() # Removed: Subclasses should call setup() after their own initialization

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

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Alias for generate method to maintain compatibility with different code bases"""
        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

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
            if (
                hasattr(self, "api_key")
                and self.api_key
                and not is_sdk_provider
                and not isinstance(self, CodestralProvider)
                and "Authorization" not in current_headers
            ):
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

    async def get_available_models(self) -> List[str]:
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
        self.setup()  # Ensure setup is called

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

    async def get_available_models(self) -> List[str]:
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
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        if not anthropic:
            logger.error(
                "Модуль anthropic не установлен. Установите его с помощью 'pip install anthropic'"
            )
            self.anthropic = None
            return

        self.anthropic = anthropic  # Assign the imported module
        self.api_key = self.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
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

    async def get_available_models(self) -> List[str]:
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
            "powerful": [
                "llama3-70b-8192",
                "llama-3.3-70b-versatile",
            ],  # Потужні моделі
        }
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        if not groq or not AsyncGroq:  # Check both groq and AsyncGroq
            logger.error(
                "Модуль groq не установлен. Установите его с помощью 'pip install groq'"
            )
            self.groq = None
            return

        self.groq = groq  # Assign the imported module
        self.api_key = self.config.get("api_key") or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            logger.warning(
                "API ключ Groq не найден ни в конфигурации, ни в GROQ_API_KEY."
            )
        else:
            logger.info("Groq настроен успешно")

    def get_client(self) -> Any:
        if not AsyncGroq or not self.groq:  # Check both
            raise ValueError("Модуль groq не импортирован.")
        if not self.api_key:
            raise ValueError("API ключ Groq не установлен.")
        if self._client is None:
            import httpx  # Import httpx

            # Get proxy from config
            proxy_url = self.config.get("proxy")
            http_client_instance = None  # Initialize http_client_instance to None
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
                        http_client=http_client_instance,  # Pass the created client
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

    def select_optimal_model(
        self, prompt: str, requested_model: Optional[str] = None
    ) -> str:
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
        paragraphs = prompt.split("\n\n")

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
                    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
                    current_sentence_group = ""

                    for sentence in sentences:
                        if (
                            len(current_sentence_group) + len(sentence) + 1
                            <= max_length
                        ):
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
                                sentence_parts = [
                                    sentence[i : i + max_length]
                                    for i in range(0, len(sentence), max_length)
                                ]
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
        if not self.groq or not self.api_key:  # Check self.groq
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
                        part_prompt = (
                            f"This is part {i+1} of {len(parts)} of the request. "
                            + part
                        )
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
        except self.groq.APIError as e:  # Use self.groq
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

    async def get_available_models(self) -> List[str]:
        # Додаємо модель llama-3.3-70b-versatile із прикладу запиту
        known = [
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma-7b-it",
            "llama-3.3-70b-versatile",
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
        self.setup()  # Ensure setup is called

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

        response = None  # Define response outside try block
        response_data = {}  # Define response_data outside try block
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
                    error_message = response_data.get("error", {}).get(
                        "message", e.message
                    )
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
        self.setup()  # Ensure setup is called

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
                self.ollama = None  # Ensure ollama module is not used if client fails
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
        max_tokens: Optional[
            int
        ] = None,  # Ollama doesn't directly use max_tokens in chat
        temperature: Optional[float] = None,
    ) -> str:

        model_to_use = model or self.get_default_model() or "llama3"
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )
        # num_predict corresponds roughly to max_tokens, but behavior might differ
        num_predict = max_tokens or self.config.get(
            "num_predict", -1
        )  # Default -1 (no limit)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        options = {"temperature": temperature_to_use}
        if num_predict > 0:
            options["num_predict"] = num_predict

        response = None  # Define response outside try block
        response_data = {}  # Define response_data outside try block
        try:
            if self.use_sdk and self._client:
                response = await self._client.chat(  # Assign to response
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
                async with session.post(
                    api_url, json=payload
                ) as response:  # Assign to inner response
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
                    pass  # Fallback if response body is not JSON or other error
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
            if (
                self.ollama
                and hasattr(self.ollama, "ResponseError")
                and isinstance(e, self.ollama.ResponseError)
            ):
                return f"Ошибка генерации (Ollama SDK {e.status_code}): {e.error}"
            return f"Ошибка генерации: {str(e)}"
        # Removed finally block: session closing handled by __aexit__

    async def get_available_models(self) -> List[str]:
        hardcoded_models = [
            "qwen2.5:latest",
            "qwen2.5:1.5b",
            "qwen3:1.7b",
            "qwen3:latest",
            "hhao/qwen2.5-coder-tools:14b",
            "deepseek-coder-v2:latest",
            "gemma3:27b",
            "qwen2.5-coder:14b",
            "Llama2:7b",
            "qllama/bge-reranker-v2-m3:latest",
            "qwen2.5-coder:1.5b",
            "mistral:latest",
            "llama3.2:latest",
            "qwen2.5:14b-instruct",
            "gemma2:latest",
            "dolphin-mixtral:latest",
            "Llama2:chat",
            "qwen2.5-coder:32b",
            "llama3.3:70b-instruct-q2_K",
            "tulu3:latest",
            "nomic-embed-text:latest",
            "Llama2:13B",
            "deepseek-r1:32b",
            "deepseek-r1:14b",
        ]

        try:
            if self.use_sdk and self._client:
                models = await self._client.list()
                if models:
                    return [model.name for model in models]
            else:
                # Try REST API
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.endpoint}/api/tags") as response:
                        if response.status == 200:
                            data = await response.json()
                            models = [model["name"] for model in data["models"]]
                            return models
        except Exception as e:
            logger.error(f"Failed to fetch Ollama models: {e}")

        # Return hardcoded models if API calls fail
        return hardcoded_models


class OpenRouterProvider(BaseProvider):
    """Провайдер для OpenRouter (OpenAI-совместимый API)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "openrouter"
        self.setup()  # Ensure setup is called

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
            logger.warning(
                f"Модель для OpenRouter не указана, используется дефолтная: {model_to_use}"
            )
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

        response = None  # Define response outside try block
        response_data = {}  # Define response_data outside try block
        try:
            session = await self.get_client_session()
            # OpenRouter requires API Key in Authorization header
            headers = {"Authorization": f"Bearer {self.api_key}"}
            # Add optional headers from config
            headers["HTTP-Referer"] = self.config.get(
                "referer", "http://localhost"
            )  # Example referer
            headers["X-Title"] = self.config.get("title", "MCP-AI-App")  # Example title

            async with session.post(api_url, json=payload, headers=headers) as response:
                response_data = await response.json()
                if response.status == 200:
                    if response_data.get("choices") and response_data["choices"][0].get(
                        "message"
                    ):
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
                    error_message = response_data.get("error", {}).get(
                        "message", e.message
                    )
                except Exception:
                    pass  # Fallback if response body is not JSON or other error
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
                    return (
                        super().get_available_models()
                    )  # Fallback to configured model
        except Exception as e:
            logger.error(f"Ошибка при получении списка моделей OpenRouter: {e}")
            return super().get_available_models()  # Fallback to configured model


class CohereProvider(BaseProvider):
    """Провайдер для Cohere."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "cohere"
        self._client = None
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        if not cohere:
            logger.error(
                "Модуль cohere не установлен. Установите его с помощью 'pip install cohere'"
            )
            self.cohere = None
            return

        self.cohere = cohere
        self.api_key = self.config.get("api_key") or os.environ.get("COHERE_API_KEY")
        if not self.api_key:
            logger.warning(
                "API ключ Cohere не найден ни в конфигурации, ни в COHERE_API_KEY."
            )
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
        system_prompt: Optional[str] = None,  # Cohere uses 'preamble'
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.cohere or not self.api_key:
            return "Ошибка генерации: провайдер Cohere не настроен."

        model_to_use = (
            model or self.get_default_model() or "command-r"
        )  # Default to command-r
        max_tokens_to_use = max_tokens or self.config.get("max_tokens") or 4096
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        try:
            client = self.get_client()
            # Use chat method for conversational generation
            response = await client.chat(
                message=prompt,
                model=model_to_use,
                preamble=system_prompt,  # Use preamble for system context
                max_tokens=max_tokens_to_use,
                temperature=temperature_to_use,
                # Cohere might have different parameter names or capabilities
            )
            if response and hasattr(response, "text"):
                return response.text
            else:
                logger.warning(
                    f"Ответ от Cohere не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от Cohere API."

        except self.cohere.CohereAPIError as e:  # Catch specific Cohere API errors
            logger.error(f"Cohere API Error ({model_to_use}): {e}")
            # Attempt to get status code if available
            status_code = getattr(e, "http_status", "N/A")
            return f"Ошибка генерации (Cohere API {status_code}): {e}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с помощью Cohere ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    async def get_available_models(self) -> List[str]:
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
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        if not genai:
            logger.error(
                "Модуль google-generativeai не установлен. Установите его: pip install google-generativeai"
            )
            self.genai = None
            return

        self.genai = genai
        self.api_key = (
            self.config.get("api_key")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not self.api_key:
            logger.warning(
                "API ключ Gemini/Google не найден ни в конфигурации, ни в GEMINI_API_KEY/GOOGLE_API_KEY."
            )
        else:
            try:
                self.genai.configure(api_key=self.api_key)
                logger.info("Gemini SDK настроен успешно")
            except Exception as e:
                logger.error(f"Ошибка конфигурации Gemini SDK: {e}")
                self.genai = None  # Mark as unusable if config fails

    def get_model(self, model_name: str) -> Any:
        if not self.genai:
            raise ValueError(
                "Модуль google-generativeai не импортирован или не настроен."
            )

        # Cache the model instance? For now, create new each time.
        # Consider safety config from self.config if needed
        safety_settings = self.config.get(
            "safety_settings"
        )  # Example: {"HARASSMENT": "BLOCK_NONE"}
        generation_config = self.config.get(
            "generation_config"
        )  # Example: {"temperature": 0.7}

        try:
            # Combine generation_config from instance config and method args
            combined_gen_config = self.config.get("generation_config", {}).copy()
            # Method args like temperature/max_tokens override instance config
            # Note: SDK uses different names (e.g., max_output_tokens)

            model_instance = self.genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config,  # Pass base config here
            )
            return model_instance
        except Exception as e:
            logger.error(
                f"Не удалось создать экземпляр модели Gemini '{model_name}': {e}"
            )
            raise ValueError(
                f"Не удалось создать экземпляр модели Gemini '{model_name}': {e}"
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[
            str
        ] = None,  # Gemini uses system_instruction in start_chat or generate_content
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        if not self.genai or not self.api_key:
            return "Ошибка генерации: провайдер Gemini не настроен."

        # Default to gemini-1.5-flash-latest if no model specified
        model_to_use = model or self.get_default_model() or "gemini-1.5-flash"

        try:
            model_instance = self.get_model(model_to_use)

            # Prepare generation config, overriding defaults with method args
            gen_config_overrides = {}
            if temperature is not None:
                gen_config_overrides["temperature"] = temperature
            if max_tokens is not None:
                gen_config_overrides["max_output_tokens"] = max_tokens

            # Set up the generation config if needed
            generation_config = None
            if gen_config_overrides:
                generation_config = self.genai.GenerationConfig(**gen_config_overrides)

            # Prepare messages
            messages = []

            # Add system prompt if provided (as user message with special prefix)
            if system_prompt:
                messages.append(
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"<<SYSTEM>>\n{system_prompt}\n<</SYSTEM>>"}
                        ],
                    }
                )

            # Add user prompt
            messages.append({"role": "user", "parts": [{"text": prompt}]})

            # Generate content
            response = await model_instance.generate_content_async(
                messages, generation_config=generation_config
            )

            # Extract text from response
            if hasattr(response, "text"):
                return response.text

            # Alternative way to extract text
            if hasattr(response, "candidates") and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, "content") and candidate.content:
                        if hasattr(candidate.content, "parts"):
                            return "".join(
                                part.text
                                for part in candidate.content.parts
                                if hasattr(part, "text")
                            )

            # Fallback for structure extraction
            if isinstance(response, dict):
                if "candidates" in response and len(response["candidates"]) > 0:
                    candidate = response["candidates"][0]
                    if "content" in candidate and "parts" in candidate["content"]:
                        return "".join(
                            part.get("text", "")
                            for part in candidate["content"]["parts"]
                        )

            logger.warning(f"Ответ от Gemini не содержит ожидаемого текста: {response}")
            return (
                "Ошибка генерации: Не получен корректный текстовый ответ от Gemini API."
            )

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

    async def get_available_models(self) -> List[str]:
        # List known/common Gemini models
        known = [
            "gemini-1.5-pro-latest",
            "gemini-1.5-flash-latest",
            "gemini-1.0-pro",
            "gemini-pro",  # Alias for 1.0 pro?
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
        self.setup()  # Ensure setup is called

    def setup(self) -> None:  # Corrected: Added self
        if not Together:
            logger.error(
                "Модуль 'together' не установлен. Установите его: pip install together"
            )
            self.together_sdk = None
            return

        self.together_sdk = Together  # Assign the imported class
        self.api_key = self.config.get("api_key") or os.environ.get("TOGETHER_API_KEY")
        if not self.api_key:
            logger.warning(
                "API ключ Together не найден ни в конфигурации, ни в TOGETHER_API_KEY."
            )
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
                    f"Ответ от Together SDK ({model_to_use}) не содержит ожидаемых данных: {response}"
                )
                return "Ошибка генерации: Не получен корректный ответ от Together SDK."

        except TogetherError as e:
            logger.error(f"Together API Error ({model_to_use}): {e}")
            return f"Ошибка генерации (Together API): {e}"
        except Exception as e:
            logger.error(
                f"Ошибка при генерации ответа с Together SDK ({model_to_use}): {e}",
                exc_info=True,
            )
            return f"Ошибка генерации: {str(e)}"

    async def get_available_models(self) -> List[str]:
        if not self._client:
            logger.warning(
                "Невозможно получить список моделей: Together SDK не инициализирован."
            )
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
            self.endpoint = self.config.get("endpoint", "https://api.mistral.ai/v1")
        else:
            # Ensure endpoint from config is used if provided
            self.endpoint = self.config.get("endpoint", self.endpoint)
        self.setup()  # Ensure setup is called

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
        retries: int = 3,  # Add retries parameter with default value
        initial_delay: float = 1.0,  # Add initial delay with default value
    ) -> str:
        if not self.api_key:
            return "Ошибка генерации: API ключ Codestral/Mistral не установлен."
        if not self.endpoint:
            return "Ошибка генерации: Endpoint для Codestral не установлен."

        model_to_use = (
            model or self.get_default_model() or "codestral-latest"
        )  # Default model
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 4096)
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
            "stream": False,  # Assuming non-streaming for now
        }
        # Remove None values from payload
        payload = {k: v for k, v in payload.items() if v is not None}

        api_url = f"{self.endpoint}/chat/completions"

        # Implement retry logic with exponential backoff
        current_retry = 0
        delay = initial_delay
        session = None

        try:
            session = await self.get_client_session()

            while current_retry <= retries:
                try:
                    # Headers are managed by get_client_session
                    async with session.post(api_url, json=payload) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            if response_data.get("choices") and response_data[
                                "choices"
                            ][0].get("message"):
                                return response_data["choices"][0]["message"].get(
                                    "content", ""
                                )
                            else:
                                logger.warning(
                                    f"Ответ от Codestral API ({model_to_use}) не содержит ожидаемых данных: {response_data}"
                                )
                                return "Ошибка генерации: Не получен корректный ответ от Codestral API."
                        elif response.status == 429 and current_retry < retries:
                            # Handle rate limit error with retry
                            error_text = await response.text()
                            import random

                            wait_time = delay * (2**current_retry) + random.uniform(
                                0, 0.5
                            )
                            logger.warning(
                                f"Codestral API рейт-лимит превышен ({response.status}). Повторная попытка через {wait_time:.2f} секунд. Попытка {current_retry + 1}/{retries}. Сообщение: {error_text[:200]}"
                            )
                            # Wait with exponential backoff before retrying
                            await asyncio.sleep(wait_time)
                            current_retry += 1
                            continue
                        else:
                            # Attempt to get error message from response for other errors
                            error_text = await response.text()
                            error_message = error_text
                            try:
                                # Try to parse JSON error if possible
                                error_data = json.loads(error_text)
                                if error_data.get("error"):
                                    error_message = error_data.get("error").get(
                                        "message", error_text
                                    )
                            except:
                                pass

                            logger.error(
                                f"Codestral API HTTP Error ({model_to_use}, {response.status}): {error_message[:200]}"
                            )

                            # For rate limit errors that have exceeded retries
                            if response.status == 429:
                                return f"Ошибка генерации: Превышен лимит запросов к Codestral API (429) после {retries} попыток."

                            response.raise_for_status()  # Raise exception for other bad status

                except aiohttp.ClientResponseError as e:
                    # Error message already logged above if possible
                    error_message = e.message
                    try:
                        # Try to parse JSON error again just in case
                        response_data = await e.response.json()
                        error_message = response_data.get("error", {}).get(
                            "message", e.message
                        )
                    except Exception:
                        pass  # Keep original message if JSON parsing fails

                    if e.status == 429 and current_retry < retries:
                        # Handle rate limit with exponential backoff
                        import random

                        wait_time = delay * (2**current_retry) + random.uniform(0, 0.5)
                        logger.warning(
                            f"Codestral API рейт-лимит превышен ({e.status}). Повторная попытка через {wait_time:.2f} секунд. Попытка {current_retry + 1}/{retries}."
                        )
                        await asyncio.sleep(wait_time)
                        current_retry += 1
                        continue
                    elif e.status == 429:
                        # Rate limit exceeded after retries
                        return f"Ошибка генерации: Превышен лимит запросов к Codestral API (429) после {retries} попыток."
                    else:
                        return f"Ошибка генерации (Codestral API {e.status}): {error_message}"

                except aiohttp.ClientError as e:
                    logger.error(
                        f"Ошибка соединения с Codestral API {self.endpoint}: {e}"
                    )
                    if current_retry < retries:
                        # Also retry connection errors
                        import random

                        wait_time = delay * (2**current_retry) + random.uniform(0, 0.5)
                        logger.warning(
                            f"Ошибка соединения с Codestral API. Повторная попытка через {wait_time:.2f} секунд. Попытка {current_retry + 1}/{retries}."
                        )
                        await asyncio.sleep(wait_time)
                        current_retry += 1
                        continue
                    return f"Ошибка генерации: Не удалось подключиться к Codestral API ({e})"

                except Exception as e:
                    logger.error(
                        f"Неожиданная ошибка при генерации ответа с Codestral ({model_to_use}): {e}",
                        exc_info=True,
                    )
                    return f"Ошибка генерации: {str(e)}"

            # If we exhausted all retries
            return f"Ошибка генерации: Не удалось получить ответ от Codestral API после {retries} попыток."
        finally:
            # Ensure we close the session when we're done
            if session:
                await self.close_session()

    async def get_available_models(self) -> List[str]:
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
        self.api_key = os.environ.get(
            "GEMINI3_API_KEY"
        )  # Використовуємо змінну оточення
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        logger.info("Gemini3Provider налаштований через прямі API запити")
        if not self.api_key:
            logger.error(
                "API ключ для Gemini3 не встановлено в змінній оточення GEMINI3_API_KEY"
            )

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
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        # Формуємо вміст запиту
        content = {"parts": [{"text": prompt}]}

        # Додаємо системний промпт, якщо він є
        if system_prompt:
            payload = {
                "contents": [{"parts": [{"text": system_prompt}]}, content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use,
                },
            }
        else:
            payload = {
                "contents": [content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use,
                },
            }

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:generateContent?key={self.api_key}"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    response_data = await response.json()

                    # Витягуємо текст відповіді
                    if (
                        response_data.get("candidates")
                        and response_data["candidates"][0].get("content")
                        and response_data["candidates"][0]["content"].get("parts")
                    ):

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
                    error_message = error_data.get("error", {}).get(
                        "message", "Невідома помилка"
                    )
                    logger.error(
                        f"Gemini3 API HTTP помилка ({response.status}): {error_message}"
                    )
                    return f"Помилка генерації (Gemini3 API {response.status}): {error_message}"

        except aiohttp.ClientError as e:
            logger.error(f"Помилка з'єднання з Gemini3 API: {e}")
            return f"Помилка генерації: Не вдалося підключитися до Gemini3 API ({e})"
        except Exception as e:
            logger.error(
                f"Несподівана помилка при генерації відповіді з Gemini3: {e}",
                exc_info=True,
            )
            return f"Помилка генерації: {str(e)}"

    async def get_available_models(self) -> List[str]:
        return [
            "gemini-2.0-flash",
            "gemini-2.0-pro",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]


class Gemini4Provider(BaseProvider):
    """Провайдер для Google Gemini4 через прямі API запити, використовується для AI2 документатора."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "gemini4"
        self.api_key = os.environ.get(
            "GEMINI4_API_KEY"
        )  # Використовуємо змінну оточення
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        logger.info(
            "Gemini4Provider налаштований через прямі API запити для документації"
        )
        if not self.api_key:
            logger.error(
                "API ключ для Gemini4 не встановлено в змінній оточення GEMINI4_API_KEY"
            )

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
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        # Формуємо вміст запиту
        content = {"parts": [{"text": prompt}]}

        # Додаємо системний промпт, якщо він є
        if system_prompt:
            payload = {
                "contents": [{"parts": [{"text": system_prompt}]}, content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use,
                },
            }
        else:
            payload = {
                "contents": [content],
                "generationConfig": {
                    "maxOutputTokens": max_tokens_to_use,
                    "temperature": temperature_to_use,
                },
            }

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:generateContent?key={self.api_key}"

        try:
            session = await self.get_client_session()
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    response_data = await response.json()

                    # Витягуємо текст відповіді
                    if (
                        response_data.get("candidates")
                        and response_data["candidates"][0].get("content")
                        and response_data["candidates"][0]["content"].get("parts")
                    ):

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
                    error_message = error_data.get("error", {}).get(
                        "message", "Невідома помилка"
                    )
                    logger.error(
                        f"Gemini4 API HTTP помилка ({response.status}): {error_message}"
                    )
                    return f"Помилка генерації (Gemini4 API {response.status}): {error_message}"

        except aiohttp.ClientError as e:
            logger.error(f"Помилка з'єднання з Gemini4 API: {e}")
            return f"Помилка генерації: Не вдалося підключитися до Gemini4 API ({e})"
        except Exception as e:
            logger.error(
                f"Несподівана помилка при генерації відповіді з Gemini4: {e}",
                exc_info=True,
            )
            return f"Помилка генерації: {str(e)}"

    async def get_available_models(self) -> List[str]:
        return ["gemini-2.0-pro", "gemini-1.5-pro", "gemini-1.5-flash"]


class TugezerProvider(BaseProvider):
    """Provider for Tugezer API (HTTP API-based, not client-based)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "tugezer"
        self.setup()  # Ensure setup is called

    def setup(self) -> None:
        if not self.endpoint:
            self.endpoint = "https://api.tugezer.ai/v1"
            logger.warning(
                f"Endpoint for TugezerProvider not specified, using default: {self.endpoint}"
            )
        else:
            # Ensure endpoint doesn't end with a slash
            self.endpoint = self.endpoint.rstrip("/")
            logger.info(f"Tugezer endpoint configured: {self.endpoint}")

        # Get API key from config or environment
        self.api_key = self.config.get("api_key") or os.environ.get("TUGEZER_API_KEY")
        if not self.api_key:
            logger.error(
                "API key for Tugezer not found in configuration or TUGEZER_API_KEY environment variable."
            )
        else:
            logger.info("API key for Tugezer found.")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        retries: int = 3,
        initial_delay: float = 1.0,
    ) -> str:
        if not self.api_key:
            return "Error: Tugezer API key not set."
        if not self.endpoint:
            return "Error: Tugezer endpoint not set."

        model_to_use = model or self.get_default_model() or "tugezer-latest"
        max_tokens_to_use = max_tokens or self.config.get("max_tokens", 4096)
        temperature_to_use = (
            temperature
            if temperature is not None
            else self.config.get("temperature", 0.7)
        )

        # Create messages array for API format
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Prepare request payload
        payload = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens_to_use,
            "temperature": temperature_to_use,
        }

        # Remove None values from payload
        payload = {k: v for k, v in payload.items() if v is not None}

        api_url = f"{self.endpoint}/chat/completions"

        # Implement retry logic with exponential backoff
        current_retry = 0
        delay = initial_delay

        while current_retry <= retries:
            try:
                # Use session from base provider
                session = await self.get_client_session()
                headers = {"Authorization": f"Bearer {self.api_key}"}

                async with session.post(
                    api_url, json=payload, headers=headers
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if response_data.get("choices") and response_data["choices"][
                            0
                        ].get("message"):
                            return response_data["choices"][0]["message"].get(
                                "content", ""
                            )
                        else:
                            logger.warning(
                                f"Response from Tugezer API ({model_to_use}) does not contain expected data: {response_data}"
                            )
                            return "Error: No valid response received from Tugezer API."
                    elif response.status == 429 and current_retry < retries:
                        # Handle rate limit with retry
                        error_text = await response.text()
                        wait_time = delay * (2**current_retry) + random.uniform(0, 0.5)
                        logger.warning(
                            f"Tugezer API rate limit exceeded ({response.status}). Retrying in {wait_time:.2f} seconds. Attempt {current_retry + 1}/{retries}. Message: {error_text[:200]}"
                        )
                        await asyncio.sleep(wait_time)
                        current_retry += 1
                        continue
                    else:
                        # Handle other errors
                        error_text = await response.text()
                        try:
                            error_data = json.loads(error_text)
                            error_message = error_data.get("error", {}).get(
                                "message", error_text
                            )
                        except:
                            error_message = error_text

                        logger.error(
                            f"Tugezer API HTTP Error ({model_to_use}, {response.status}): {error_message[:200]}"
                        )

                        return f"Error ({response.status}): {error_message}"

            except aiohttp.ClientError as e:
                logger.error(f"Connection error with Tugezer API {self.endpoint}: {e}")
                if current_retry < retries:
                    wait_time = delay * (2**current_retry) + random.uniform(0, 0.5)
                    logger.warning(
                        f"Connection error with Tugezer API. Retrying in {wait_time:.2f} seconds. Attempt {current_retry + 1}/{retries}."
                    )
                    await asyncio.sleep(wait_time)
                    current_retry += 1
                    continue
                return f"Error: Could not connect to Tugezer API ({e})"

            except Exception as e:
                logger.error(
                    f"Unexpected error generating response with Tugezer ({model_to_use}): {e}",
                    exc_info=True,
                )
                return f"Error: {str(e)}"

        # If we exhausted all retries
        return (
            f"Error: Failed to get response from Tugezer API after {retries} attempts."
        )

    async def get_available_models(self) -> List[str]:
        known = ["tugezer-latest", "tugezer-7b", "tugezer-13b"]
        default_model = self.get_default_model()
        if default_model and default_model not in known:
            known.append(default_model)
        return known


class FallbackProvider(BaseProvider):
    """Provider that falls back to other providers if the primary one fails."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.name = "fallback"
        self.providers = []
        self.setup()

    def setup(self) -> None:
        """Initialize the fallback provider chain."""
        if not self.config:
            logger.warning("No configuration provided for FallbackProvider")
            return

        providers_config = self.config.get("providers", [])
        if not providers_config:
            logger.warning("No fallback providers configured")
            return

        # Load providers in the specified order
        for provider_config in providers_config:
            provider_type = provider_config.get("type")
            if not provider_type:
                logger.warning(
                    f"Provider type not specified in config: {provider_config}"
                )
                continue

            try:
                # Use ProviderFactory to create each provider
                provider = ProviderFactory.create_provider(
                    provider_type, provider_config
                )
                self.providers.append(provider)
                logger.info(f"Added fallback provider: {provider.name}")
            except Exception as e:
                logger.error(
                    f"Failed to create fallback provider of type {provider_type}: {e}"
                )

        if not self.providers:
            logger.warning("No fallback providers were successfully created")
        else:
            logger.info(
                f"FallbackProvider initialized with {len(self.providers)} providers"
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Try each provider in order until one succeeds."""
        if not self.providers:
            return "Error: No fallback providers configured"

        errors = []

        # Log the fallback chain
        provider_chain = ", ".join([p.name for p in self.providers])
        logger.info(f"Attempting generation with fallback chain: {provider_chain}")

        # Track which provider succeeded to avoid closing its session prematurely
        successful_provider = None
        result = None

        try:
            for i, provider in enumerate(self.providers):
                try:
                    logger.info(
                        f"Trying provider {i+1}/{len(self.providers)}: {provider.name}"
                    )

                    # Get provider-specific model if needed
                    provider_model = model
                    if not provider_model and ":" in (model or ""):
                        parts = model.split(":", 1)
                        if parts[0] == provider.name:
                            provider_model = parts[1]

                    current_result = await provider.generate(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        model=provider_model or provider.get_default_model(),
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )

                    # Check for specific error patterns that indicate we should try fallback
                    error_patterns = [
                        "Generation error: Codestral API request limit exceeded (429)",
                        "Error (Groq API 429)",
                        "Request timed out",
                        "rate limit",
                        "capacity",
                        "overloaded",
                        "API Error",
                        "Ошибка генерации:",
                        "Error generating",
                        "failed after",
                        "Too Many Requests",
                    ]

                    if any(
                        pattern.lower() in current_result.lower()
                        for pattern in error_patterns
                    ):
                        logger.warning(
                            f"Provider {provider.name} returned error: {current_result}"
                        )
                        errors.append(f"{provider.name}: {current_result}")

                        # Close session immediately for failed providers
                        await provider.close_session()
                        continue

                    # If we get here, the provider returned a valid result
                    logger.info(f"Provider {provider.name} succeeded")
                    successful_provider = provider
                    result = current_result
                    return current_result

                except Exception as e:
                    logger.error(f"Error with provider {provider.name}: {e}")
                    errors.append(f"{provider.name}: {str(e)}")

                    # Close session immediately for providers that raised exceptions
                    await provider.close_session()

            # If we get here, all providers failed
            error_report = "\n".join(errors)
            logger.error(f"All fallback providers failed:\n{error_report}")
            return f"All providers failed. Please check the provider configuration or try again later.\nErrors:\n{error_report}"
        finally:
            # In the finally block, close sessions for all providers except the successful one
            for provider in self.providers:
                if provider != successful_provider:
                    try:
                        await provider.close_session()
                    except Exception as e:
                        logger.error(
                            f"Error closing session for provider {provider.name}: {e}"
                        )

    async def get_available_models(self) -> List[str]:
        """Get a list of available models from all providers."""
        models = []
        for provider in self.providers:
            try:
                provider_models = await provider.get_available_models()
                models.extend([f"{provider.name}:{model}" for model in provider_models])
            except Exception as e:
                logger.error(f"Error getting models from provider {provider.name}: {e}")
        return models

    def get_default_model(self) -> Optional[str]:
        """Get the default model from the first provider."""
        if not self.providers:
            return None
        try:
            provider = self.providers[0]
            model = provider.get_default_model()
            return f"{provider.name}:{model}" if model else None
        except Exception:
            return None

    async def close_session(self):
        """Close sessions for all providers."""
        for provider in self.providers:
            try:
                await provider.close_session()
            except Exception as e:
                logger.error(f"Error closing session for provider {provider.name}: {e}")

    async def __aexit__(self, exc_type, exc, tb):
        """Ensure all provider sessions are closed when using async with."""
        await self.close_session()
        await super().__aexit__(exc_type, exc, tb)


def get_component_fallbacks(ai: str, role: Optional[str] = None) -> List[Dict]:
    """Gets fallback providers for a specific AI component.

    Args:
        ai: The AI component name (ai1, ai2, ai3)
        role: For AI2, the specific role (executor, tester, documenter)

    Returns:
        List of provider configs with their models
    """
    try:
        # Load config
        from config import load_config

        config = load_config()

        # Get AI config
        ai_config = config.get("ai_config", {})

        # Handle AI2 with role
        if ai == "ai2" and role:
            if role in ai_config.get("ai2", {}):
                provider_config = ai_config["ai2"][role]
            else:
                return []
        # Handle AI1/AI3
        elif ai in ai_config:
            provider_config = ai_config[ai]
        else:
            return []

        # Check if using fallback provider
        if provider_config.get("provider") != "fallback":
            return []

        # Get fallback providers
        fallbacks = []
        for provider in provider_config.get("fallback_providers", []):
            if provider and "provider" in provider and "model" in provider:
                fallbacks.append(
                    {"provider": provider["provider"], "model": provider["model"]}
                )

        return fallbacks
    except Exception as e:
        logger.error(
            f"Error getting fallbacks for component {ai}{'-'+role if role else ''}: {e}"
        )
        return []


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


import importlib
import importlib.util
import os
import sys
from typing import Dict, List, Optional, Type

# Dictionary to store dynamically loaded provider classes
_plugin_providers = {}
_plugin_providers_loaded = False


def discover_provider_plugins() -> Dict[str, Type[BaseProvider]]:
    """Discovers and loads provider plugins from the plugins directory.

    Looks for Python files in the 'plugins/providers' directory and attempts to
    load any classes that inherit from BaseProvider.

    Returns:
        Dict mapping provider names to provider classes
    """
    global _plugin_providers, _plugin_providers_loaded

    # If already loaded, return cached result
    if _plugin_providers_loaded:
        return _plugin_providers

    # Define plugin directory
    plugin_dir = os.path.join(os.path.dirname(__file__), "plugins", "providers")

    # Create directory if it doesn't exist
    os.makedirs(plugin_dir, exist_ok=True)

    # Check if __init__.py exists in plugin directory
    init_file = os.path.join(plugin_dir, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            f.write("# Provider plugins directory\n")

    # Add plugin directory to system path if not already there
    if plugin_dir not in sys.path:
        sys.path.append(os.path.dirname(plugin_dir))

    try:
        # Find all Python files in the plugin directory
        for filename in os.listdir(plugin_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = f"plugins.providers.{filename[:-3]}"

                try:
                    # Import the module
                    spec = importlib.util.find_spec(module_name)
                    if spec is None:
                        logger.warning(f"Could not find spec for module {module_name}")
                        continue

                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # Find provider classes (inheriting from BaseProvider)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, BaseProvider)
                            and attr is not BaseProvider
                        ):

                            # Get provider name from class
                            provider_name = getattr(attr, "provider_type", None)
                            if not provider_name:
                                # Default to lowercase class name without 'Provider' suffix
                                class_name = attr.__name__
                                if class_name.endswith("Provider"):
                                    provider_name = class_name[:-8].lower()
                                else:
                                    provider_name = class_name.lower()

                            logger.info(
                                f"Discovered provider plugin: {provider_name} ({attr.__name__})"
                            )
                            _plugin_providers[provider_name] = attr

                except Exception as e:
                    logger.error(f"Error loading provider plugin {filename}: {e}")

        _plugin_providers_loaded = True
        if _plugin_providers:
            logger.info(
                f"Loaded {len(_plugin_providers)} provider plugins: {', '.join(_plugin_providers.keys())}"
            )
        else:
            logger.info("No provider plugins found")

    except Exception as e:
        logger.error(f"Error discovering provider plugins: {e}")

    return _plugin_providers


def get_provider_plugin(provider_type: str) -> Optional[Type[BaseProvider]]:
    """Gets a provider plugin class by type name.

    Args:
        provider_type: The type name of the provider

    Returns:
        The provider class if found, None otherwise
    """
    plugins = discover_provider_plugins()
    return plugins.get(provider_type)
