import argparse
import asyncio
import git
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Union

import aiohttp

# Используем функцию load_config из config.py
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import apply_request_delay, log_message  # Import apply_request_delay

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levellevelname)s - %(message)s"
)
logger = logging.getLogger("AI2")

# Загружаем конфигурацию один раз
config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class AI2:
    """
    Второй AI модуль, отвечающий за генерацию кода, тестов и документации.
    Использует различных провайдеров для разных задач и поддерживает
    механизм fallback.
    """

    def __init__(self, role: str):
        """
        Инициализация AI2 модуля.

        Args:
            role: Роль этого воркера ('executor', 'tester', 'documenter')
        """
        self.role = role
        global logger
        logger = logging.getLogger(f"AI2-{self.role.upper()}")

        self.config = config
        ai_config_base = self.config.get("ai_config", {})
        self.ai_config = ai_config_base.get("ai2", {})
        if not self.ai_config:
            logger.warning(
                "Секция 'ai_config.ai2' не найдена в конфигурации. Используются значения по умолчанию."
            )
            self.ai_config = {"fallback_providers": ["openai"]}

        self.prompts = self.config.get(
            "ai2_prompts",
            [
                "You are an expert programmer. Create the content for the file {filename} based on the following task description. Respond ONLY with the raw file content. Do NOT use markdown code blocks (```).",
                "You are a testing expert. Generate unit tests for the code in file {filename}. Respond ONLY with the raw test code. Do NOT use markdown code blocks (```).",
                "You are a technical writer. Generate documentation (e.g., docstrings, comments) for the code in file {filename}. Respond ONLY with the raw documentation text. Do NOT use markdown code blocks (```).",
            ],
        )
        if len(self.prompts) < 3:
            logger.error(
                "Конфигурация 'ai2_prompts' отсутствует или неполна. Используются промпты по умолчанию."
            )
            self.prompts = [
                "You are an expert programmer. Create the content for the file {filename} based on the following task description. Respond ONLY with the raw file content. Do NOT use markdown code blocks (```).",
                "You are a testing expert. Generate unit tests for the code in file {filename}. Respond ONLY with the raw test code. Do NOT use markdown code blocks (```).",
                "You are a technical writer. Generate documentation (e.g., docstrings, comments) for the code in file {filename}. Respond ONLY with the raw documentation text. Do NOT use markdown code blocks (```).",
            ]

        # Updated: Use the new provider configuration structure
        self.providers = self.ai_config.get("providers", {}).get(self.role, [])
        if not self.providers:
            logger.warning(
                f"No providers configured for role '{self.role}'. Defaulting to ['openai']"
            )
            self.providers = ["openai"]

        # Initialize fallback_providers
        self.fallback_providers = self.ai_config.get("fallback_providers", ["openai"])
        
        # Initialize providers_config
        self.providers_config = self._setup_providers_config()

        logger.info(f"Configured providers for role '{self.role}': {', '.join(self.providers)}")

        self.api_session = None

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Получает или создает сессию aiohttp."""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session

    async def close_session(self):
        """Закрывает сессию aiohttp."""
        if self.api_session or not self.api_session.closed:
            await self.api_session.close()
            logger.info("API сессия закрыта.")

    def _setup_providers_config(self) -> Dict[str, Dict[str, Any]]:
        """
        Настройка конфигурации провайдеров для каждой роли из общей конфигурации.
        Используется self.role для определения нужного провайдера.

        Returns:
            Dict[str, Dict[str, Any]]: Словарь с конфигурацией для текущей роли
        """
        # Используем первый провайдер из списка настроенных провайдеров
        provider_name = self.providers[0] if self.providers else None

        # Если не смогли найти провайдер для роли, используем fallback
        if not provider_name:
            provider_name = self.fallback_providers[0]
            logger.warning(
                f"Не найден провайдер для роли '{self.role}'. Используем fallback: {provider_name}"
            )

        # Получаем конфигурацию провайдера
        providers_list = self.config.get("providers", {})
        if provider_name in providers_list:
            common_config = providers_list[provider_name]
        else:
            logger.warning(
                f"Провайдер '{provider_name}' не найден в списке провайдеров. Используем пустую конфигурацию."
            )
            common_config = {}

        # Собираем итоговую конфигурацию
        role_config = {
            "name": provider_name,
            **common_config,
            **{
                k: v
                for k, v in self.ai_config.items()
                if k
                not in [
                    "executor",
                    "tester",
                    "documenter",
                    "provider",
                    "fallback_providers",
                ]
            },
        }

        logger.info(f"Провайдер для роли '{self.role}' настроен: {provider_name}")
        return {self.role: role_config}

    async def _get_provider_instance(self) -> BaseProvider:
        """Получает или создает экземпляр провайдера для текущей роли воркера."""
        config = self.providers_config.get(self.role)
        if not config:
            raise ValueError(f"Конфигурация для роли '{self.role}' не найдена.")
        provider_name = config.get("name")
        if not provider_name:
            raise ValueError(
                f"Имя провайдера отсутствует в конфигурации для роли '{self.role}'."
            )

        try:
            provider_instance = ProviderFactory.create_provider(provider_name)
            return provider_instance
        except ValueError as e:
            logger.error(
                f"Не удалось создать провайдер '{provider_name}' для роли '{self.role}': {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Неожиданная ошибка при создании провайдера '{provider_name}' для роли '{self.role}': {e}"
            )
            raise

    async def _generate_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Пытается сгенерировать ответ, используя основной провайдер роли и пробует все доступные провайдеры по кругу."""
        provider_config = self.providers_config.get(self.role, {})
        provider_name = provider_config.get("name", "N/A")
        primary_provider = None
        
        # Собираем полный список провайдеров, начиная с основного и добавляя все фолбек провайдеры
        all_providers = [provider_name]
        # Добавим фолбеки, которых нет в списке
        for fallback in self.fallback_providers:
            if fallback not in all_providers:
                all_providers.append(fallback)
        
        logger.info(f"Попытка генерации с использованием провайдеров (по порядку): {', '.join(all_providers)}")
        
        all_errors = []
        # Перебираем все провайдеры по очереди
        for provider_idx, current_provider_name in enumerate(all_providers):
            current_provider = None
            try:
                logger.info(
                    f"Попытка генерации с провайдером [{provider_idx+1}/{len(all_providers)}] '{current_provider_name}'."
                )
                
                # Получаем конфиг для текущего провайдера
                current_config_base = self.config.get("providers", {}).get(
                    current_provider_name, {}
                )
                current_config = {
                    **current_config_base,
                    **{
                        k: v
                        for k, v in self.ai_config.items()
                        if k
                        not in [
                            "executor",
                            "tester",
                            "documenter",
                            "provider",
                            "fallback_providers",
                        ]
                    },
                }

                # Создаем экземпляр провайдера
                current_provider = ProviderFactory.create_provider(
                    current_provider_name, current_config
                )

                # Добавляем задержку, чтобы не перегружать API (только не для первого основного провайдера)
                if provider_idx > 0:
                    await apply_request_delay("ai2", self.role)

                # Генерируем с текущим провайдером
                result = await current_provider.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    model=model
                    or current_config.get("model")
                    or self.ai_config.get("model"),
                    max_tokens=max_tokens or self.ai_config.get("max_tokens"),
                    temperature=temperature or self.ai_config.get("temperature"),
                )
                
                # Проверяем на ошибку генерации
                if isinstance(result, str) and result.startswith("Ошибка генерации"):
                    raise Exception(
                        f"Provider '{current_provider_name}' failed: {result}"
                    )
                
                # Закрываем сессию после успешного использования
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()
                    
                # Возвращаем результат от успешного провайдера
                logger.info(f"Успешно сгенерировано с провайдером '{current_provider_name}'")
                return result

            except Exception as provider_error:
                # Логируем ошибку провайдера
                logger.error(
                    f"Ошибка генерации с провайдером '{current_provider_name}': {provider_error}"
                )
                all_errors.append(f"Provider '{current_provider_name}' failed: {provider_error}")
                
                # Закрываем сессию провайдера при ошибке
                if (
                    current_provider
                    and hasattr(current_provider, "close_session")
                    and callable(current_provider.close_session)
                ):
                    await current_provider.close_session()
        
        # Если все провайдеры не сработали, возвращаем информацию о всех ошибках
        error_msg = "Не удалось сгенерировать ответ ни одним из доступных провайдеров:\n- " + "\n- ".join(all_errors)
        logger.error(error_msg)
        return error_msg

    async def generate_code(self, task: str, filename: str) -> str:
        """Генерация кода на основе описания задачи."""
        logger.info(f"Генерация кода для файла: {filename}")
        system_prompt = self.prompts[0].format(filename=filename)
        user_prompt = f"Task Description: {task}\n\nPlease generate the content for the file '{filename}' based on this task."
        await apply_request_delay("ai2", self.role)
        return await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    async def generate_tests(self, code: str, filename: str) -> str:
        """Генерация тестов для кода."""
        logger.info(f"Генерация тестов для файла: {filename}")
        system_prompt = self.prompts[1].format(filename=filename)
        user_prompt = f"Code for file '{filename}':\n```\n{code}\n```\n\nPlease generate unit tests for this code."
        await apply_request_delay("ai2", self.role)
        test_content = await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )
        
        # Якщо тести згенеровані успішно, комітимо їх в Git
        if test_content and not test_content.startswith("Ошибка генерации"):
            if await self.commit_tests_to_git(filename, test_content):
                return test_content
            else:
                return f"Ошибка генерации: Не удалось сохранить тесты в Git для {filename}"
        
        return test_content

    async def generate_docs(self, code: str, filename: str) -> str:
        """Генерация документации для кода."""
        logger.info(f"Генерация документации для файла: {filename}")
        system_prompt = self.prompts[2].format(filename=filename)
        user_prompt = f"Code for file '{filename}':\n```\n{code}\n```\n\nPlease generate documentation (e.g., docstrings, comments) for this code."
        await apply_request_delay("ai2", self.role)
        return await self._generate_with_fallback(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    async def commit_tests_to_git(self, filename: str, test_content: str) -> bool:
        """Комітить згенеровані тести в Git репозиторій."""
        try:
            # Конвертуємо шлях файлу в шлях тесту
            test_filename = filename.replace(".py", "_test.py")
            if not test_filename.startswith("tests/"):
                test_filename = f"tests/{test_filename}"
            
            repo_path = os.path.join(os.getcwd(), "repo")
            test_filepath = os.path.join(repo_path, test_filename)
            
            # Створюємо директорію для тестів, якщо її немає
            os.makedirs(os.path.dirname(test_filepath), exist_ok=True)
            
            # Записуємо тести у файл
            with open(test_filepath, "w") as f:
                f.write(test_content)
            
            # Ініціалізуємо Git репозиторій
            repo = git.Repo(repo_path)
            
            # Додаємо файл в Git
            repo.index.add([test_filename])
            
            # Створюємо коміт
            commit_message = f"test: Add tests for {filename}"
            repo.index.commit(commit_message)
            
            logger.info(f"Тести для {filename} успішно додані в Git: {test_filename}")
            return True
            
        except Exception as e:
            logger.error(f"Помилка при коміті тестів для {filename} в Git: {e}")
            return False

    async def process_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обрабатывает одну задачу и возвращает словарь для отправки в /report.
        """
        subtask_id = task_info.get("id")
        role = task_info.get("role")
        filename = task_info.get("filename")
        task_description = task_info.get("text")
        code_content = task_info.get("code")

        if not subtask_id or not role or not filename:
            logger.error(f"Некорректная информация о задаче: {task_info}")
            return {
                "type": "status_update",
                "subtask_id": subtask_id or "unknown",
                "message": "Ошибка: Отсутствует ID, роль или имя файла в задаче.",
                "status": "failed",
            }

        if role != self.role:
            logger.error(
                f"Получена задача для другой роли ({role}), ожидалась роль {self.role}. Пропуск."
            )
            return {
                "type": "status_update",
                "subtask_id": subtask_id,
                "message": f"Ошибка: Воркер {self.role} получил задачу для {role}.",
                "status": "failed",
            }

        report = {
            "subtask_id": subtask_id,
            "file": filename,
        }
        start_time = asyncio.get_event_loop().time()
        generated_content = None
        error_message = None

        try:
            if role == "executor":
                report["type"] = "code"
                if not task_description:
                    error_message = "Отсутствует описание задачи для роли executor"
                    logger.error(f"Отсутствует описание задачи для executor: {task_info}")
                else:
                    generated_content = await self.generate_code(task_description, filename)
                    
            elif role == "tester":
                report["type"] = "test_result"
                if code_content is None:
                    error_message = "Отсутствует код для роли tester"
                    logger.error(f"Отсутствует код для tester: {task_info}")
                else:
                    # Generate and commit tests
                    generated_content = await self.generate_tests(code_content, filename)
                    if generated_content and not generated_content.startswith("Ошибка генерации"):
                        # Успішно згенерували і закомітили тести
                        report["content"] = generated_content
                        report["message"] = f"Тести для {filename} успішно згенеровані і закомічені в Git"
                        report["status"] = "tests_committed"
                    else:
                        error_message = f"Помилка генерації тестів для {filename}: {generated_content}"
                        
            elif role == "documenter":
                report["type"] = "code"
                if code_content is None:
                    error_message = "Отсутствует код для роли documenter"
                    logger.error(f"Отсутствует код для documenter: {task_info}")
                else:
                    generated_content = await self.generate_docs(code_content, filename)
                    
            else:
                error_message = f"Неизвестная роль: {role}"
                logger.error(f"Неизвестная роль: {role}")

            if isinstance(generated_content, str) and generated_content.startswith(
                "Не удалось сгенерировать ответ"
            ):
                error_message = generated_content
                generated_content = None

            if generated_content is not None:
                report["content"] = generated_content

        except Exception as e:
            logger.exception(
                f"Неожиданная ошибка при обработке задачи для {filename} ({role}): {e}"
            )
            error_message = f"Неожиданная ошибка: {e}"

        end_time = asyncio.get_event_loop().time()
        processing_time = end_time - start_time

        if error_message:
            report = {
                "type": "status_update",
                "subtask_id": subtask_id,
                "message": f"Ошибка обработки задачи ({role} для {filename}): {error_message}",
                "status": "failed",
            }
            log_message_data = {
                "message": f"Обработка задачи завершилась с ошибкой для {filename} ({role})",
                "role": role,
                "file": filename,
                "status": "error",
                "processing_time": round(processing_time, 2),
                "error_message": error_message,
            }
        else:
            log_message_data = {
                "message": f"Обработка задачи успешно завершена для {filename} ({role})",
                "role": role,
                "file": filename,
                "status": "success",
                "processing_time": round(processing_time, 2),
                "report_type": report.get("type"),
            }

        log_message(json.dumps(log_message_data))
        return report

    async def fetch_task(self) -> Optional[Dict[str, Any]]:
        """Запрашивает задачу у API для текущей роли."""
        api_url = f"{MCP_API_URL}/task/{self.role}"
        try:
            session = await self._get_api_session()
            logger.debug(f"Запрос задачи с {api_url}")
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and "subtask" in data and data["subtask"]:
                        logger.info(
                            f"Получена задача: ID={data['subtask'].get('id')}, File={data['subtask'].get('filename')}"
                        )
                        return data["subtask"]
                    elif data and "message" in data:
                        logger.debug(f"Нет доступных задач: {data['message']}")
                        return None
                    else:
                        logger.warning(
                            f"Неожиданный ответ от API при запросе задачи: {data}"
                        )
                        return None
                else:
                    logger.error(
                        f"Ошибка при запросе задачи: Статус {response.status}, Ответ: {await response.text()}"
                    )
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут при запросе задачи с {api_url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения при запросе задачи с {api_url}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Неожиданная ошибка при запросе задачи: {e}")
            return None

    async def send_report(self, report_data: Dict[str, Any]):
        """Отправляет отчет о выполненной задаче в API."""
        api_url = f"{MCP_API_URL}/report"
        try:
            session = await self._get_api_session()
            logger.debug(
                f"Отправка отчета на {api_url}: Тип={report_data.get('type')}, ID={report_data.get('subtask_id')}"
            )
            async with session.post(api_url, json=report_data, timeout=60) as response:
                if response.status == 200:
                    logger.info(
                        f"Отчет для задачи {report_data.get('subtask_id')} успешно отправлен."
                    )
                else:
                    logger.error(
                        f"Ошибка при отправке отчета для задачи {report_data.get('subtask_id')}: Статус {response.status}, Ответ: {await response.text()}"
                    )
        except asyncio.TimeoutError:
            logger.error(
                f"Таймаут при отправке отчета для задачи {report_data.get('subtask_id')}"
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"Ошибка соединения при отправке отчета для задачи {report_data.get('subtask_id')}: {e}"
            )
        except Exception as e:
            logger.exception(f"Неожиданная ошибка при отправке отчета: {e}")

    async def run_worker(self):
        """Основной цикл воркера: получение задачи, обработка, отправка отчета."""
        logger.info(f"Воркер AI2 ({self.role}) запущен.")
        while True:
            task = await self.fetch_task()
            if task:
                report = await self.process_task(task)
                if report:
                    await self.send_report(report)
                else:
                    logger.error(
                        f"Process_task вернул пустой отчет для задачи {task.get('id')}"
                    )
                await asyncio.sleep(1)
            else:
                sleep_time = config.get("ai2_idle_sleep", 5)
                logger.debug(f"Нет задач для {self.role}. Ожидание {sleep_time} сек.")
                await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI2 Worker")
    parser.add_argument(
        "--role",
        type=str,
        required=True,
        choices=["executor", "tester", "documenter"],
        help="Роль этого воркера AI2",
    )
    args = parser.parse_args()

    ai2_worker = AI2(role=args.role)

    try:
        asyncio.run(ai2_worker.run_worker())
    except KeyboardInterrupt:
        logger.info(f"Воркер AI2 ({args.role}) остановлен вручную.")
    except Exception as e:
        logger.exception(
            f"Критическая ошибка в главном цикле воркера AI2 ({args.role}): {e}"
        )
    finally:
        asyncio.run(ai2_worker.close_session())
