import asyncio
import json
import logging
import os
import time
import uuid  # Import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp

# Use load_config function from config.py
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import apply_request_delay, log_message  # Import apply_request_delay

config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class AI1:
    """
    AI1 - Project Coordinator
    Formulates tasks for AI2 based on project structure and tracks progress
    """

    def __init__(self, target: str):
        self.target = target
        # Restore LLM initialization
        ai1_config_base = config.get("ai_config", {})
        ai1_config = ai1_config_base.get("ai1", {})
        if not ai1_config:
            log_message(
                "[AI1] Warning: 'ai_config.ai1' section not found in configuration. Using defaults."
            )
            ai1_config = {"providers": ["openai"]} # Default provider list

        # Read the list of providers
        provider_names = ai1_config.get("providers", ["openai"])
        if not provider_names:
             log_message("[AI1] Warning: No providers specified for AI1 in config. Defaulting to ['openai']")
             provider_names = ["openai"]
        provider_name = provider_names[0] # Use the first provider from the list for AI1
        log_message(f"[AI1] Attempting to initialize provider: {provider_name}")

        # Load system prompt for LLM from configuration
        self.system_prompt = config.get("ai1_prompt", "You are AI1, the project coordinator.") # Default prompt
        log_message(f"[AI1] Loaded system prompt: {self.system_prompt[:100]}...")

        # System instructions that will be added to the base prompt
        self.system_instructions = " Use only Latin characters in your responses. Format your output as requested in specific prompts. Provide JSON when asked. Be precise and direct in your decisions."
        
        # Create LLM instance
        try:
            # Pass provider name and configuration for it
            provider_config = config.get("providers", {}).get(provider_name, {})
            full_ai1_config = {**provider_config, **ai1_config} # Merge general and specific configuration
            self.llm: BaseProvider = ProviderFactory.create_provider(provider_name, full_ai1_config)
            log_message(f"[AI1] Provider '{provider_name}' created successfully.")
        except ValueError as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Failed to create provider '{provider_name}'. {e}. LLM features disabled."
            )
            self.llm = None # Disable LLM if initialization failed
        except Exception as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Unexpected error creating provider '{provider_name}'. {e}. LLM features disabled."
            )
            self.llm = None # Disable LLM

        # Save LLM configuration for future use
        self.ai1_llm_config = ai1_config

        self.status = "initializing"
        self.project_structure: Optional[Dict] = None
        self.structure_fetch_attempted = False
        self.files_to_fill = []  # All files to be filled (complete list)
        self.pending_files_to_fill = []  # Files waiting to be tasked
        self.files_to_test = []  # All files to be tested (complete list)
        self.pending_files_to_test = []  # Files waiting to be tested
        self.files_to_document = []  # All files to be documented (complete list)
        self.pending_files_to_document = []  # Files waiting to be documented

        # Maximum number of concurrent tasks from configuration (default 10)
        self.max_concurrent_tasks = config.get("ai1_max_concurrent_tasks", 10)
        log_message(f"[AI1] Maximum concurrent tasks set to: {self.max_concurrent_tasks}")

        # Task statuses: pending, sending, sent, code_received, fetch_failed,
        #                tested, accepted, review_needed, failed_tests,
        #                completed_by_ai2, failed_by_ai2, error_processing, skipped
        self.task_status: Dict[str, Dict[str, str]] = {}
        self.active_tasks = set()  # Stores "filename::role::subtask_id"
        self.api_session = None  # Initialize session

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Gets or creates the aiohttp session."""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session

    async def close_session(self):
        """Closes the aiohttp session."""
        if self.api_session and not self.api_session.closed:
            await self.api_session.close()
            log_message("[AI1] API session closed.")

    async def run(self):
        """Main work cycle of AI1"""
        log_message(f"[AI1] Started with target: {self.target}")
        self.status = "waiting_for_structure"

        try:
            await self.ensure_structure_received()
            if not self.project_structure:
                log_message("[AI1] Failed to obtain project structure. Exiting.")
                self.status = "error"
                return

            self.initialize_task_status()
            self.status = "processing_tasks"

            while self.status == "processing_tasks":
                await self.manage_tasks()
                if self.check_completion():
                    self.status = "completed"
                    log_message("[AI1] All tasks completed. Project finished.")
                    break
                # Adjust sleep time as needed
                await asyncio.sleep(config.get("ai1_sleep_interval", 15))

        except Exception as e:
            log_message(f"[AI1] Unhandled exception in run loop: {e}")
            self.status = "error"
        finally:
            await self.close_session()  # Ensure session is closed on exit

    async def ensure_structure_received(self, timeout=300):
        """Пытается получить структуру проекта от API с повторными попытками."""
        if self.project_structure:
            return True

        log_message("[AI1] Attempting to fetch project structure...")
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                api_url = f"{MCP_API_URL}/structure"
                session = await self._get_api_session()
                async with session.get(api_url, timeout=30) as response:
                    if response.status == 200:
                        structure_data = await response.json()
                        if (
                            structure_data
                            and isinstance(structure_data.get("structure"), dict)
                            and structure_data["structure"]
                        ):  # Check if structure is not empty
                            self.project_structure = structure_data["structure"]
                            log_message("[AI1] Structure received successfully.")
                            self.process_structure(self.project_structure)
                            return True
                        else:
                            log_message(
                                f"[AI1] Received invalid or empty structure data: {structure_data}. Retrying..."
                            )
                    elif response.status == 404:
                        log_message(
                            "[AI1] Structure not yet available from API (404). Retrying..."
                        )
                    else:
                        log_message(
                            f"[AI1] Failed to fetch structure. Status: {response.status}, Body: {await response.text()}. Retrying..."
                        )

            except asyncio.TimeoutError:
                log_message("[AI1] Timeout while fetching structure. Retrying...")
            except aiohttp.ClientError as e:
                log_message(f"[AI1] Error fetching structure: {str(e)}. Retrying...")
            except Exception as e:
                log_message(
                    f"[AI1] Unexpected error fetching structure: {str(e)}. Retrying..."
                )

            await asyncio.sleep(5)  # Wait before retrying

        log_message(
            f"[AI1] Failed to obtain project structure after {timeout} seconds."
        )
        return False

    def process_structure(self, structure_data):
        """Обработать структуру проекта и определить файлы для задач."""
        self.files_to_fill = self._extract_files(structure_data)
        # Determine which files need testing based on extension
        testable_extensions = (
            ".py",
            ".js",
            ".ts",
            ".java",
            ".cpp",
            ".go",
            ".rs",
            ".php",
            ".html",
            ".css",
            ".scss",
            ".jsx",
            ".tsx",
            ".vue"
        )
        self.files_to_test = [
            f for f in self.files_to_fill if f.lower().endswith(testable_extensions)
        ]
        self.files_to_document = list(
            self.files_to_fill
        )  # All files need documentation
        
        # Ініціалізація черг файлів, що очікують на обробку
        self.pending_files_to_fill = list(self.files_to_fill)
        self.pending_files_to_test = list(self.files_to_test)
        self.pending_files_to_document = list(self.files_to_document)

        log_message(
            f"[AI1] Structure processed. Files to implement: {len(self.files_to_fill)}, Files to test: {len(self.files_to_test)}, Files to document: {len(self.files_to_document)}"
        )

    def _extract_files(self, node, current_path="") -> List[str]:
        """Рекурсивно извлекает все файлы из JSON-структуры."""
        files = []
        if isinstance(node, dict):
            for key, value in node.items():
                # Sanitize key to prevent path traversal issues, though API should also validate
                sanitized_key = key.replace("..", "_").strip()
                if not sanitized_key:
                    continue  # Skip empty keys

                new_path = (
                    os.path.join(current_path, sanitized_key)
                    if current_path
                    else sanitized_key
                )
                if isinstance(value, dict):
                    files.extend(self._extract_files(value, new_path))
                elif value is None or isinstance(
                    value, str
                ):  # Treat null or string value as a file placeholder
                    # Нормалізуємо шлях і зберігаємо форвард-слеші для узгодженості з ai3.py
                    normalized_path = os.path.normpath(new_path).replace(os.sep, "/")
                    
                    # ВАЖЛИВО: Переконуємося, що не додаємо ім'я проекту на початку шляху
                    # Це ключовий фікс, що забезпечує узгодженість з ai3.py
                    if self.target and normalized_path.startswith(self.target + "/"):
                        normalized_path = normalized_path[len(self.target) + 1:]
                        log_message(f"[AI1] Видалено ім'я проекту з шляху: {new_path} -> {normalized_path}")
                    
                    files.append(normalized_path)
        return files

    def initialize_task_status(self):
        """Инициализирует словарь статусов задач для всех файлов."""
        self.task_status = {}
        for file_path in self.files_to_fill:
            self.task_status[file_path] = {
                "executor": "pending",
                # Mark as pending only if the file is in the test list
                "tester": "pending" if file_path in self.files_to_test else "skipped",
                "documenter": "pending",  # All files need documentation
            }
        log_message(f"[AI1] Task status initialized for {len(self.task_status)} files.")

    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Получает содержимое файла из API."""
        api_url = f"{MCP_API_URL}/file_content"
        params = {"path": file_path}
        log_message(f"[AI1] Attempting to fetch content for: {file_path}")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, params=params, timeout=45) as response:
                if response.status == 200:
                    content = await response.text()
                    log_message(
                        f"[AI1] Successfully fetched content for: {file_path} (Length: {len(content)})"
                    )
                    return content
                elif response.status == 404:
                    log_message(f"[AI1] File not found via API for: {file_path}")
                    return None
                else:
                    error_text = await response.text()
                    log_message(
                        f"[AI1] Failed to fetch content for {file_path}. Status: {response.status}, Response: {error_text}"
                    )
                    return None
        except asyncio.TimeoutError:
            log_message(f"[AI1] Timeout fetching content for: {file_path}")
            return None
        except aiohttp.ClientError as e:
            log_message(
                f"[AI1] Connection error fetching content for {file_path}: {str(e)}"
            )
            return None
        except Exception as e:
            log_message(
                f"[AI1] Unexpected error fetching content for {file_path}: {str(e)}"
            )
            return None

    async def get_task_status_from_api(self, subtask_id: str) -> Optional[str]:
        """Fetches the status of a specific subtask from the API."""
        api_url = f"{MCP_API_URL}/subtask_status/{subtask_id}"
        log_message(f"[AI1] Querying API for status of subtask: {subtask_id}")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    status = data.get("status")
                    log_message(f"[AI1] API status for {subtask_id}: {status}")
                    return status
                elif response.status == 404:
                    log_message(
                        f"[AI1] Subtask {subtask_id} not found in API status check."
                    )
                    return None  # Or maybe 'unknown'
                else:
                    log_message(
                        f"[AI1] Failed to get status for {subtask_id}. Status: {response.status}"
                    )
                    return None
        except asyncio.TimeoutError:
            log_message(f"[AI1] Timeout getting status for {subtask_id}")
            return None
        except aiohttp.ClientError as e:
            log_message(f"[AI1] Connection error getting status for {subtask_id}: {e}")
            return None
        except Exception as e:
            log_message(f"[AI1] Unexpected error getting status for {subtask_id}: {e}")
            return None

    async def get_all_task_statuses_from_api(self) -> Dict[str, str]:
        """Fetches all task statuses from the API."""
        api_url = f"{MCP_API_URL}/all_subtask_statuses"
        log_message("[AI1] Querying API for all subtask statuses...")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    log_message(f"[AI1] Received {len(data)} task statuses from API.")
                    return data
                else:
                    log_message(
                        f"[AI1] Failed to get all statuses. Status: {response.status}"
                    )
                    return {}
        except asyncio.TimeoutError:
            log_message("[AI1] Timeout getting all statuses.")
            return {}
        except aiohttp.ClientError as e:
            log_message(f"[AI1] Connection error getting all statuses: {e}")
            return {}
        except Exception as e:
            log_message(f"[AI1] Unexpected error getting all statuses: {e}")
            return {}

    async def update_local_task_statuses(self):
        """Updates the local task status dictionary based on API data."""
        api_statuses = await self.get_all_task_statuses_from_api()
        updated_count = 0
        if not api_statuses:
            log_message("[AI1] No statuses received from API to update local state.")
            return

        # Iterate through active tasks (filename::role::subtask_id)
        tasks_to_remove = set()
        for task_key in list(self.active_tasks):  # Iterate over a copy
            try:
                filename, role, subtask_id = task_key.split("::")
                api_status = api_statuses.get(subtask_id)

                if api_status:
                    local_status = self.task_status.get(filename, {}).get(role)
                    # Define final states
                    final_states = [
                        "accepted",
                        "skipped",
                        "failed_by_ai2",
                        "error_processing",
                        "review_needed",
                    ]
                    if api_status != local_status:
                        log_message(
                            f"[AI1] Updating status for {filename} ({role}) from '{local_status}' to '{api_status}' (Subtask: {subtask_id})"
                        )
                        if (
                            filename in self.task_status
                            and role in self.task_status[filename]
                        ):
                            self.task_status[filename][role] = api_status
                            updated_count += 1
                        else:
                            log_message(
                                f"[AI1] Warning: Cannot update status for non-existent local task {filename} ({role})"
                            )

                    # Remove from active tasks if it reached a final state
                    if api_status in final_states:
                        tasks_to_remove.add(task_key)
                else:
                    # Subtask ID from active_tasks not found in API response - might be an issue
                    log_message(
                        f"[AI1] Warning: Active subtask {subtask_id} ({filename}::{role}) not found in API status response."
                    )
                    # Decide whether to remove it or keep checking
                    # tasks_to_remove.add(task_key) # Option: remove if not found after a while

            except ValueError:
                log_message(f"[AI1] Error parsing active task key: {task_key}")
                tasks_to_remove.add(task_key)  # Remove malformed key
            except Exception as e:
                log_message(
                    f"[AI1] Error processing active task {task_key} during status update: {e}"
                )

        self.active_tasks -= tasks_to_remove
        log_message(
            f"[AI1] Local task statuses updated ({updated_count} changes). Active tasks remaining: {len(self.active_tasks)}"
        )

    async def manage_tasks(self):
        """Основна логіка управління задачами: підтримує буфер активних завдань."""
        log_message("[AI1] Starting task management cycle...")

        # Оновлюємо локальні статуси з API
        await self.update_local_task_statuses()

        # 1. Розраховуємо кількість завершених завдань
        tasks_done_count = 0
        # Статуси, що вважаються завершеними (успішно чи ні)
        final_statuses = [
            "accepted",
            "skipped",
            "failed_by_ai2",
            "error_processing",
            "review_needed", # Можливо, вважати завершеним для цього розрахунку
            "failed_tests", # Якщо не передбачено rework
            "failed_to_send", # Якщо не вдалося надіслати
            # Додайте інші статуси, якщо потрібно
        ]
        for file_path, statuses in self.task_status.items():
            for role, status in statuses.items():
                if status in final_statuses:
                    tasks_done_count += 1
        log_message(f"[AI1] Calculated completed/final tasks: {tasks_done_count}")

        # 2. Розраховуємо кількість поточних активних завдань (надіслані, обробляються)
        active_task_count = 0
        # Статуси, які вважаються активними (займають слот обробки)
        active_statuses = ["sending", "sent", "processing", "code_received", "tested"] # Додайте/видаліть за потребою
        current_active_tasks_details = []
        for file_path, roles_statuses in self.task_status.items():
            for role, status in roles_statuses.items():
                if status in active_statuses:
                    active_task_count += 1
                    current_active_tasks_details.append(f"{file_path} ({role}): {status}")

        log_message(f"[AI1] Calculated active (in-progress) tasks: {active_task_count}")
        if current_active_tasks_details:
             log_message(f"[AI1] Active tasks list: {'; '.join(current_active_tasks_details)}")

        # 3. Визначаємо динамічний ліміт для нових завдань
        # Читаємо бажаний буфер з конфігурації, з значенням за замовчуванням 10
        desired_active_buffer = config.get("ai1_desired_active_buffer", 10)
        # Переконуємося, що значення є цілим числом
        try:
            desired_active_buffer = int(desired_active_buffer)
            if desired_active_buffer < 0:
                log_message(f"[AI1] Warning: Invalid negative ai1_desired_active_buffer ({desired_active_buffer}) found in config. Using default 10.")
                desired_active_buffer = 10
        except (ValueError, TypeError):
            log_message(f"[AI1] Warning: Invalid non-integer ai1_desired_active_buffer ('{desired_active_buffer}') found in config. Using default 10.")
            desired_active_buffer = 10

        dynamic_max_concurrent = min(tasks_done_count + desired_active_buffer, self.max_concurrent_tasks)
        log_message(f"[AI1] Target concurrent tasks: {dynamic_max_concurrent} (Completed: {tasks_done_count} + Buffer: {desired_active_buffer}, Capped by Max: {self.max_concurrent_tasks})")

        tasks_to_send = []
        slots_filled_this_cycle = 0

        # --- Застосування LLM для пріоритезації файлів ---
        if self.llm and (self.pending_files_to_fill or self.pending_files_to_test or self.pending_files_to_document):
            log_message("[AI1] Запит до LLM для пріоритезації файлів...")
            try:
                # Формуємо контекст для LLM
                pending_summary = {
                    "executor": len(self.pending_files_to_fill),
                    "tester": len(self.pending_files_to_test),
                    "documenter": len(self.pending_files_to_document),
                }
                
                # Додаємо приклади файлів для кожної ролі (максимум по 5)
                role_example_files = {
                    "executor": self.pending_files_to_fill[:5] if self.pending_files_to_fill else [],
                    "tester": self.pending_files_to_test[:5] if self.pending_files_to_test else [],
                    "documenter": self.pending_files_to_document[:5] if self.pending_files_to_document else [],
                }
                
                # Створюємо загальний аналіз стану
                status_summary = {}
                for file_path, statuses in self.task_status.items():
                    for role, status in statuses.items():
                        if status not in status_summary:
                            status_summary[status] = 0
                        status_summary[status] += 1
                
                # Формуємо промпт для LLM
                llm_prompt = f"""{{
    "system_prompt": "{self.system_prompt}{self.system_instructions}",
    "context": {{
        "project_target": "{self.target}",
        "pending_files": {json.dumps(pending_summary)},
        "example_files": {json.dumps(role_example_files)},
        "project_status": {json.dumps(status_summary)},
        "active_tasks": {len(self.active_tasks)}
    }},
    "request": "Given the current project state, provide guidance on which type of tasks (executor, tester, documenter) should be prioritized in this cycle. Consider dependencies (executor -> tester -> documenter), critical files, and balanced progress. Respond with a JSON structure like: {{\\"priorities\\": [\\"executor\\", \\"tester\\", \\"documenter\\"]}} listing roles in recommended priority order."
}}"""

                # Додаємо затримку перед запитом
                await apply_request_delay("ai1")

                # Викликаємо LLM
                llm_response = await self.llm.generate(
                    prompt=llm_prompt,
                    temperature=self.ai1_llm_config.get("temperature", 0.3),
                    max_tokens=self.ai1_llm_config.get("max_tokens", 150)
                )

                # Обробляємо відповідь LLM
                if llm_response:
                    try:
                        # Шукаємо JSON у відповіді
                        import re
                        json_match = re.search(r'({.*})', llm_response)
                        if json_match:
                            llm_json = json.loads(json_match.group(1))
                            prioritized_roles = llm_json.get("priorities", [])
                            
                            if prioritized_roles:
                                log_message(f"[AI1] LLM рекомендує пріоритезацію: {prioritized_roles}")
                                
                                # Застосовуємо пріоритезацію, сортуючи файли за пріоритетом ролі
                                if "executor" in prioritized_roles and self.pending_files_to_fill:
                                    # Можна також пріоритезувати самі файли для executor
                                    # Наприклад, за розширенням, розміром або шляхом
                                    pass
                                
                                # Відсортуємо ролі для обробки відповідно до рекомендацій LLM
                                roles_to_process = []
                                for role in prioritized_roles:
                                    if role == "executor" and self.pending_files_to_fill:
                                        roles_to_process.append("executor")
                                    elif role == "tester" and self.pending_files_to_test:
                                        roles_to_process.append("tester")
                                    elif role == "documenter" and self.pending_files_to_document:
                                        roles_to_process.append("documenter")
                                
                                log_message(f"[AI1] Ролі для обробки після пріоритезації: {roles_to_process}")
                            else:
                                log_message("[AI1] LLM не надав рекомендацій щодо пріоритетів. Використовуємо стандартну послідовність.")
                        else:
                            log_message(f"[AI1] Не вдалося знайти JSON у відповіді LLM: {llm_response}")
                    except json.JSONDecodeError as e:
                        log_message(f"[AI1] Помилка розбору JSON з відповіді LLM: {e}")
                    except Exception as e:
                        log_message(f"[AI1] Помилка при обробці відповіді LLM для пріоритезації: {e}")
            except Exception as e:
                log_message(f"[AI1] Помилка при використанні LLM для пріоритезації: {e}")

        # --- Логіка додавання завдань (executor, tester, documenter) ---
        # Тепер використовуємо dynamic_max_concurrent замість self.max_concurrent_tasks

        # Приклад для executor:
        processed_executor_files = []
        # Використовуємо копію списку для безпечного видалення під час ітерації
        for file_path in list(self.pending_files_to_fill):
            # Перевіряємо динамічний ліміт ПЕРЕД додаванням
            if active_task_count + slots_filled_this_cycle < dynamic_max_concurrent:
                if "executor" in self.task_status.get(file_path, {}) and self.task_status[file_path]["executor"] == "pending":
                    tasks_to_send.append({
                        "task_text": f"Implement the required functionality in file: {file_path} based on the overall project goal: {self.target}",
                        "role": "executor",
                        "filename": file_path,
                        "code": None,
                    })
                    # Статус зміниться на 'sending' перед надсиланням
                    slots_filled_this_cycle += 1
                    processed_executor_files.append(file_path) # Позначити для видалення з pending
                    log_message(f"[AI1] Queued executor task for {file_path}. Current cycle queue size: {len(tasks_to_send)}. Aiming for total active: {active_task_count + slots_filled_this_cycle}")
            else:
                log_message(f"[AI1] Executor task for {file_path} skipped: dynamic concurrent task limit ({dynamic_max_concurrent}) reached or would be exceeded.")
                break # Зупиняємо додавання executor завдань, якщо ліміт досягнуто

        # Видаляємо оброблені файли з черги executor
        for file_path in processed_executor_files:
             if file_path in self.pending_files_to_fill:
                 self.pending_files_to_fill.remove(file_path)


        # Приклад для tester:
        executor_done_statuses = [
            "code_received", "tested", "accepted", "completed_by_ai2", "review_needed", "failed_tests" # Статуси, після яких можна тестувати
        ]
        processed_test_files = []
        for file_path in list(self.pending_files_to_test):
             # Перевіряємо динамічний ліміт
            if active_task_count + slots_filled_this_cycle < dynamic_max_concurrent:
                if (file_path in self.task_status and
                    "executor" in self.task_status[file_path] and
                    self.task_status[file_path]["executor"] in executor_done_statuses):

                    if "tester" in self.task_status[file_path] and self.task_status[file_path]["tester"] == "pending":
                        code_content = await self.get_file_content(file_path)
                        if code_content is not None:
                            tasks_to_send.append({
                                "task_text": f"Generate unit tests for the code in file: {file_path}",
                                "role": "tester",
                                "filename": file_path,
                                "code": code_content,
                            })
                            slots_filled_this_cycle += 1
                            processed_test_files.append(file_path)
                            log_message(f"[AI1] Queued tester task for {file_path}. Current cycle queue size: {len(tasks_to_send)}. Aiming for total active: {active_task_count + slots_filled_this_cycle}")
                        else:
                            log_message(f"[AI1] Failed to fetch content for {file_path} to create tester task. Setting status to fetch_failed.")
                            self.task_status[file_path]["tester"] = "fetch_failed"
                            processed_test_files.append(file_path) # Видалити з pending, бо є проблема
                # else: Немає завершеного executor або статус tester не pending
            else:
                log_message(f"[AI1] Tester task for {file_path} skipped: dynamic concurrent task limit ({dynamic_max_concurrent}) reached or would be exceeded.")
                break # Зупиняємо додавання tester завдань

        # Видаляємо оброблені файли з черги тестування
        for file_path in processed_test_files:
            if file_path in self.pending_files_to_test:
                self.pending_files_to_test.remove(file_path)


        # Приклад для documenter:
        processed_doc_files = []
        for file_path in list(self.pending_files_to_document):
             # Перевіряємо динамічний ліміт
            if active_task_count + slots_filled_this_cycle < dynamic_max_concurrent:
                if (file_path in self.task_status and
                    "executor" in self.task_status[file_path] and
                    self.task_status[file_path]["executor"] in executor_done_statuses): # Можливо, інша умова для documenter?

                    if "documenter" in self.task_status[file_path] and self.task_status[file_path]["documenter"] == "pending":
                        code_content = await self.get_file_content(file_path)
                        if code_content is not None:
                            tasks_to_send.append({
                                "task_text": f"Generate documentation (e.g., docstrings, comments, README section) for the code in file: {file_path}",
                                "role": "documenter",
                                "filename": file_path,
                                "code": code_content,
                            })
                            slots_filled_this_cycle += 1
                            processed_doc_files.append(file_path)
                            log_message(f"[AI1] Queued documenter task for {file_path}. Current cycle queue size: {len(tasks_to_send)}. Aiming for total active: {active_task_count + slots_filled_this_cycle}")
                        else:
                            log_message(f"[AI1] Failed to fetch content for {file_path} to create documenter task. Setting status to fetch_failed.")
                            self.task_status[file_path]["documenter"] = "fetch_failed"
                            processed_doc_files.append(file_path) # Видалити з pending
                # else: Немає завершеного executor або статус documenter не pending
            else:
                log_message(f"[AI1] Documenter task for {file_path} skipped: dynamic concurrent task limit ({dynamic_max_concurrent}) reached or would be exceeded.")
                break # Зупиняємо додавання documenter завдань

        # Видаляємо оброблені файли з черги документування
        for file_path in processed_doc_files:
            if file_path in self.pending_files_to_document:
                self.pending_files_to_document.remove(file_path)

        # --- Надсилання завдань та обробка результатів ---
        if tasks_to_send:
            log_message(f"[AI1] Attempting to send {len(tasks_to_send)} new subtasks...")
            # Тимчасово оновлюємо статус на 'sending' для тих, що надсилаємо
            tasks_being_sent_keys = []
            for task_data in tasks_to_send:
                file_path = task_data["filename"]
                role = task_data["role"]
                # Переконуємося, що статус все ще 'pending' перед зміною на 'sending'
                if self.task_status.get(file_path, {}).get(role) == "pending":
                    self.task_status[file_path][role] = "sending"
                    tasks_being_sent_keys.append((file_path, role))
                else:
                    log_message(f"[AI1] Warning: Task {file_path} ({role}) status changed from 'pending' before sending. Skipping status update to 'sending'.")


            results = await asyncio.gather(
                *[self.create_subtask(**task_data) for task_data in tasks_to_send],
                return_exceptions=True,
            )

            # Обробляємо результати (оновлюємо статус на основі відповіді API)
            for i, result in enumerate(results):
                task_data = tasks_to_send[i]
                file_path = task_data["filename"]
                role = task_data["role"]
                # Знаходимо відповідний ключ, якщо він був доданий
                original_key = next(((fp, r) for fp, r in tasks_being_sent_keys if fp == file_path and r == role), None)

                subtask_id = result if isinstance(result, str) else None

                if isinstance(result, Exception) or result is False:
                    error_msg = result if isinstance(result, Exception) else "API returned failure"
                    log_message(f"[AI1] Failed to send subtask for {file_path} ({role}): {error_msg}")
                    # Перевіряємо, чи ми змінювали статус на 'sending'
                    if original_key and self.task_status.get(file_path, {}).get(role) == "sending":
                        self.task_status[file_path][role] = "failed_to_send" # Або повернути в 'pending'?
                        # Повертаємо файл у відповідну чергу pending, якщо потрібно
                        if role == "executor" and file_path not in self.pending_files_to_fill:
                             self.pending_files_to_fill.append(file_path)
                        elif role == "tester" and file_path not in self.pending_files_to_test:
                             self.pending_files_to_test.append(file_path)
                        elif role == "documenter" and file_path not in self.pending_files_to_document:
                             self.pending_files_to_document.append(file_path)
                    # Видаляємо з active_tasks, якщо він там був (хоча не мав би бути для failed_to_send)
                    if original_key:
                        task_key_to_remove = f"{file_path}::{role}::{subtask_id if subtask_id else 'unknown'}" # subtask_id може бути None тут
                        self.active_tasks.discard(task_key_to_remove)

                elif subtask_id:
                    log_message(f"[AI1] Subtask {subtask_id} sent successfully for {file_path} ({role}).")
                    # Перевіряємо, чи ми змінювали статус на 'sending'
                    if original_key and self.task_status.get(file_path, {}).get(role) == "sending":
                        self.task_status[file_path][role] = "sent"
                        # Додаємо до активних завдань
                        task_key = f"{file_path}::{role}::{subtask_id}"
                        self.active_tasks.add(task_key)
                    else:
                         log_message(f"[AI1] Warning: Subtask {subtask_id} sent, but local status for {file_path} ({role}) was not 'sending'. Current status: {self.task_status.get(file_path, {}).get(role)}")

                else:
                     # Незрозумілий результат (не Exception, не False, не subtask_id)
                     log_message(f"[AI1] Unexpected result after sending subtask for {file_path} ({role}): {result}")
                     if original_key and self.task_status.get(file_path, {}).get(role) == "sending":
                         self.task_status[file_path][role] = "error_processing" # Або інший статус помилки
                     # Видаляємо з active_tasks, якщо він там був
                     if original_key:
                         task_key_to_remove = f"{file_path}::{role}::{subtask_id if subtask_id else 'unknown'}"
                         self.active_tasks.discard(task_key_to_remove)

        else:
            log_message("[AI1] No new tasks to queue or send in this cycle.")

        # Обробляємо "fetch_failed" статуси (переносимо їх назад в pending для повторної спроби)
        for file_path, statuses in self.task_status.items():
             if "tester" in statuses and statuses["tester"] == "fetch_failed":
                 log_message(f"[AI1] Retrying fetch for tester task: {file_path}")
                 statuses["tester"] = "pending"
                 if file_path not in self.pending_files_to_test and file_path in self.files_to_test:
                     self.pending_files_to_test.append(file_path)

             if "documenter" in statuses and statuses["documenter"] == "fetch_failed":
                 log_message(f"[AI1] Retrying fetch for documenter task: {file_path}")
                 statuses["documenter"] = "pending"
                 if file_path not in self.pending_files_to_document:
                     self.pending_files_to_document.append(file_path)


        # Перевіряємо прогрес (використовуємо tasks_done_count, розрахований раніше)
        total_expected_tasks = sum(len(statuses) for statuses in self.task_status.values()) # Загальна кількість статусів
        if total_expected_tasks > 0:
             progress_percent = (tasks_done_count / total_expected_tasks) * 100
             log_message(f"[AI1] Progress: {progress_percent:.2f}% ({tasks_done_count}/{total_expected_tasks} tasks in final state)")
        else:
             log_message("[AI1] Progress: No tasks initialized yet.")


        # Оптимізуємо величину затримки між циклами
        # Використовуємо active_task_count, розрахований на початку функції
        if active_task_count > 0:
            await asyncio.sleep(config.get("ai1_active_sleep_interval", 5)) # Менша затримка, якщо є активні завдання
        else:
            # Якщо немає активних завдань, перевіряємо, чи є завдання в очікуванні
            has_pending = any(
                status == "pending"
                for roles_statuses in self.task_status.values()
                for status in roles_statuses.values()
            )
            if has_pending:
                 await asyncio.sleep(config.get("ai1_pending_sleep_interval", 10)) # Середня затримка, якщо є що надсилати
            else:
                 # Якщо немає ні активних, ні очікуючих (можливо, все завершено або чекаємо на зовнішні події)
                 await asyncio.sleep(config.get("ai1_idle_sleep_interval", 15)) # Більша затримка

    async def create_subtask(
        self, task_text: str, role: str, filename: str, code: Optional[str] = None, is_rework: bool = False
    ) -> Union[
        str, bool, Exception
    ]:  # Return subtask_id on success, False or Exception on failure
        """Создать подзадачу через API. Возвращает subtask_id при успехе."""
        api_url = f"{MCP_API_URL}/subtask"
        subtask_id = str(uuid.uuid4())
        payload = {
            "subtask": {
                "id": subtask_id,
                "text": task_text,
                "role": role,
                "filename": filename,
                "is_rework": is_rework,  # Додаємо новий параметр
            }
        }
        if code is not None:
            payload["subtask"]["code"] = code

        log_message(
            f"[AI1] Sending subtask: ID={subtask_id}, Role={role}, Filename={filename}, Is_rework={is_rework}{', Code included' if code is not None else ''}"
        )
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.post(api_url, json=payload, timeout=60) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if (
                        response_data.get("status") == "subtask received"
                        and response_data.get("id") == subtask_id
                    ):
                        log_message(
                            f"[AI1] Subtask {subtask_id} creation acknowledged by API for {filename} ({role})"
                        )
                        return subtask_id  # Return ID on success
                    else:
                        log_message(
                            f"[AI1] API acknowledged subtask for {filename} ({role}) but returned unexpected data: {response_data}"
                        )
                        return False
                else:
                    response_text = await response.text()
                    log_message(
                        f"[AI1] Failed to create subtask for {filename} ({role}). Status: {response.status}, Response: {response_text}"
                    )
                    return False
        except asyncio.TimeoutError as e:
            log_message(
                f"[AI1] Timeout error creating subtask {subtask_id} for {filename} ({role})."
            )
            return e  # Return exception
        except aiohttp.ClientError as e:
            log_message(
                f"[AI1] Connection error creating subtask {subtask_id} for {filename} ({role}): {str(e)}"
            )
            return e  # Return exception
        except Exception as e:
            log_message(
                f"[AI1] Unexpected error creating subtask {subtask_id} for {filename} ({role}): {str(e)}"
            )
            return e  # Return exception

    async def handle_test_result(self, test_recommendation: dict):
        """Обробляє рекомендації щодо результатів тестування від AI3."""
        recommendation = test_recommendation.get("recommendation")
        context = test_recommendation.get("context", {})
        
        if not recommendation:
            log_message("[AI1] Отримано порожню рекомендацію від AI3. Ігнорую.")
            return False
        
        log_message(f"[AI1] Отримано рекомендацію від AI3: {recommendation}")
        
        decision = await self.decide_on_test_results(recommendation, context)
        log_message(f"[AI1] Прийнято рішення щодо результатів тестів: {decision}")
        
        if decision == "accept":
            # Позначаємо відповідні файли як прийняті
            if "failed_files" in context:
                for file in context["failed_files"]:
                    # Знаходимо оригінальний файл на основі тестового
                    original_file = self._get_original_file_from_test(file)
                    if original_file and original_file in self.task_status:
                        self.task_status[original_file]["tester"] = "accepted"
                        log_message(f"[AI1] Файл {original_file} позначено як прийнятий (тестування пройдено)")
            else:
                # Якщо немає failed_files, то всі тести пройдені успішно
                # Можемо оновити статус для всіх файлів, які були в статусі "tested"
                for file_path, statuses in self.task_status.items():
                    if statuses.get("tester") == "tested":
                        statuses["tester"] = "accepted"
                        log_message(f"[AI1] Файл {file_path} позначено як прийнятий (тестування пройдено)")
            
            return True
            
        elif decision == "rework":
            # Створюємо нові завдання для файлів, які не пройшли тести
            failed_files = context.get("failed_files", [])
            run_url = context.get("run_url", "")
            
            if not failed_files:
                log_message("[AI1] Рекомендація на доопрацювання, але не вказано файли для виправлення.")
                return False
            
            for test_file in failed_files:
                original_file = self._get_original_file_from_test(test_file)
                if not original_file:
                    log_message(f"[AI1] Не вдалося визначити оригінальний файл для тесту {test_file}")
                    continue
                    
                if original_file in self.task_status:
                    # Позначаємо файл як такий, що потребує доопрацювання
                    self.task_status[original_file]["tester"] = "failed_tests"
                    
                    # Отримуємо вміст тестового файлу, щоб дізнатися про помилки
                    test_content = await self.get_file_content(test_file)
                    original_content = await self.get_file_content(original_file)
                    
                    if not test_content or not original_content:
                        log_message(f"[AI1] Не вдалося отримати вміст файлів для створення завдання на доопрацювання: {original_file}")
                        continue
                    
                    # Створюємо завдання на доопрацювання для executor
                    task_text = (
                        f"Код у файлі {original_file} не пройшов тести. "
                        f"Необхідно виправити код згідно з вимогами у тестах.\n\n"
                        f"Помилки з тесту {test_file}:\n{test_content}\n\n"
                        f"Посилання на GitHub Actions: {run_url}\n"
                        f"Будь ласка, виправте код для проходження тестів."
                    )
                    
                    # Додаємо файл назад до pending_files_to_fill для повторної обробки
                    if original_file not in self.pending_files_to_fill:
                        self.pending_files_to_fill.append(original_file)
                    
                    # Змінюємо статус executor на "needs_rework" та створюємо нову підзадачу
                    self.task_status[original_file]["executor"] = "needs_rework"
                    
                    # Створюємо нову підзадачу для виправлення помилок
                    subtask_result = await self.create_subtask(
                        task_text=task_text,
                        role="executor",
                        filename=original_file,
                        code=original_content,
                        is_rework=True
                    )
                    
                    if subtask_result:
                        log_message(f"[AI1] Створено завдання на доопрацювання для {original_file}: {subtask_result}")
                    else:
                        log_message(f"[AI1] Не вдалося створити завдання на доопрацювання для {original_file}")
            
            return True
        
        else:
            log_message(f"[AI1] Невідоме рішення для рекомендації щодо тестів: {decision}")
            return False

    async def decide_on_test_results(self, recommendation: str, context: dict) -> str:
        """Приймає остаточне рішення щодо результатів тестування."""
        # За замовчуванням довіряємо рекомендації AI3
        decision = recommendation
        
        # Якщо потрібна більш складна логіка прийняття рішення, вона може бути тут
        # Наприклад, можемо аналізувати типи помилок у тестах, історію попередніх рішень тощо
        
        log_message(f"[AI1] Аналіз рекомендації '{recommendation}' та контексту: {context}")
        
        # Приклад додаткової логіки:
        if recommendation == "rework" and context.get("failed_files"):
            # Перевіряємо, чи не є це повторним доопрацюванням тих самих файлів
            failed_files = [self._get_original_file_from_test(f) for f in context.get("failed_files", [])]
            
            # Фільтруємо None значення
            failed_files = [f for f in failed_files if f]
            
            # Перевіряємо, чи не перевищено ліміт спроб доопрацювання
            exceed_max_rework = False
            for file in failed_files:
                if file in self.task_status:
                    # Відстежуємо кількість раз, коли файл був на доопрацюванні
                    if "rework_attempts" not in self.task_status[file]:
                        self.task_status[file]["rework_attempts"] = 1
                    else:
                        self.task_status[file]["rework_attempts"] += 1
                    
                    max_rework_attempts = config.get("ai1_max_rework_attempts", 3)
                    if self.task_status[file].get("rework_attempts", 0) > max_rework_attempts:
                        log_message(f"[AI1] Файл {file} перевищив максимальну кількість спроб доопрацювання ({max_rework_attempts})")
                        exceed_max_rework = True
                        # Можна позначити як "потрібна ручна перевірка"
                        self.task_status[file]["tester"] = "review_needed"
                        # Також позначимо executor, щоб він не намагався знову працювати над цим файлом
                        if "executor" in self.task_status[file]:
                            self.task_status[file]["executor"] = "review_needed"
                        log_message(f"[AI1] Файл {file} позначено для ручної перевірки (перевищено ліміт доопрацювань).")
                        # Видаляємо файл з черг, якщо він там є
                        if file in self.pending_files_to_fill:
                            self.pending_files_to_fill.remove(file)
                        if file in self.pending_files_to_test:
                            self.pending_files_to_test.remove(file)
                        if file in self.pending_files_to_document:
                            self.pending_files_to_document.remove(file)

            if exceed_max_rework:
                # Якщо хоча б один файл перевищив ліміт, змінюємо рішення на manual_review
                # Це запобігає нескінченним циклам доопрацювання
                decision = "manual_review"
                log_message(f"[AI1] Змінено рішення на 'manual_review' через перевищення ліміту доопрацювань.")

        # --- Інтеграція LLM для прийняття рішення ---
        if self.llm:
            log_message("[AI1] Запит до LLM для остаточного рішення щодо результатів тестів...")
            try:
                # Формуємо промпт для LLM
                failed_files_str = ', '.join(context.get("failed_files", []))
                run_url = context.get("run_url", "N/A")
                # Визначаємо оригінальні файли для історії доопрацювань
                original_failed_files = [self._get_original_file_from_test(f) for f in context.get("failed_files", [])]
                original_failed_files = [f for f in original_failed_files if f] # Фільтруємо None

                rework_attempts_info = "".join([f"  - {f}: {self.task_status[f].get('rework_attempts', 0)} attempts\n" for f in original_failed_files if f in self.task_status])

                llm_prompt = f"""{{
        "system_prompt": "{self.system_prompt}",
        "context": {{
            "project_target": "{self.target}",
            "ai3_recommendation": "{recommendation}",
            "failed_test_files": "{failed_files_str}",
            "original_code_files_to_rework": "{', '.join(original_failed_files)}",
            "github_actions_url": "{run_url}",
            "rework_history": "{rework_attempts_info}"
            # Можна додати уривки логів або коду, якщо потрібно
        }},
        "request": "You are AI1, the project coordinator. Given the test results, decide whether to 'accept' the code despite test failures, 'rework' (ask for fixes), or 'manual_review' (if multiple rework attempts failed). Return ONLY 'accept', 'rework', or 'manual_review' as a single word."
    }}"""

                # Додаємо затримку перед запитом
                await apply_request_delay("ai1")

                # Викликаємо LLM
                llm_response = await self.llm.generate(
                    prompt=llm_prompt,
                    temperature=self.ai1_llm_config.get("temperature", 0.2),
                    max_tokens=self.ai1_llm_config.get("max_tokens", 10)
                )

                # Обробляємо відповідь LLM
                if llm_response:
                    # Нормалізуємо відповідь: видаляємо зайві символи, лишаємо тільки текст рішення
                    llm_decision = llm_response.strip().lower()
                    
                    # Шукаємо одне з очікуваних слів у відповіді
                    for expected_decision in ["accept", "rework", "manual_review"]:
                        if expected_decision in llm_decision:
                            llm_decision = expected_decision
                            break
                    else:
                        # Якщо жодне з очікуваних слів не знайдено, використовуємо логіку за замовчуванням
                        log_message(f"[AI1] LLM повернув непідтримуване рішення: '{llm_decision}'. Використовуємо алгоритмічне рішення: '{decision}'")
                        llm_decision = decision
                    
                    # Повертаємо рішення від LLM, якщо воно відрізняється від алгоритмічного
                    if llm_decision != decision:
                        log_message(f"[AI1] LLM змінив рішення з '{decision}' на '{llm_decision}'")
                        decision = llm_decision
                    else:
                        log_message(f"[AI1] LLM підтвердив алгоритмічне рішення: '{decision}'")
                    
            except Exception as e:
                log_message(f"[AI1] Помилка при використанні LLM для прийняття рішення: {e}. Використовуємо алгоритмічне рішення.")
        
        return decision

    def _get_original_file_from_test(self, test_file: str) -> str:
        """Визначає оригінальний файл на основі тестового файлу."""
        # Простий алгоритм: видаляємо 'test_' з назви файлу або замінюємо '_test' на ''
        base_name = os.path.basename(test_file)
        
        if base_name.startswith("test_"):
            original_name = base_name[5:]  # Видаляємо "test_"
        elif "_test." in base_name:
            original_name = base_name.replace("_test.", ".")
        elif base_name.endswith("_test.py") or base_name.endswith("_test.js"):
            original_name = base_name[:-8] + base_name[-3:]  # Видаляємо "_test" перед розширенням
        else:
            log_message(f"[AI1] Не вдалося визначити оригінальний файл для тесту {test_file}")
            return None
        
        # Підбираємо шлях до оригінального файлу
        for file_path in self.files_to_fill:
            if file_path.endswith(original_name) or os.path.basename(file_path) == original_name:
                return file_path
        
        # Якщо оригінальний файл не знайдено, повертаємо None
        return None

    def check_completion(self) -> bool:
        """Проверяет, все ли задачи выполнены (статус 'accepted' или 'skipped')."""
        if not self.task_status:
            log_message("[AI1] Task status not initialized, cannot check completion.")
            return False

        final_complete_statuses = ["accepted", "skipped"]
        final_failed_statuses = [
            "failed_by_ai2",
            "error_processing",
            "review_needed",
        ]  # Consider these 'done' but not successful

        for file_path, statuses in self.task_status.items():
            for role, status in statuses.items():
                if (
                    status not in final_complete_statuses
                    and status not in final_failed_statuses
                ):
                    return False
        log_message("[AI1] Completion check: All tasks are in a final state.")
        return True


async def main():
    target = config.get("target")
    if not target:
        print("CRITICAL: 'target' not found in config.json. Exiting.")
        return

    ai1 = AI1(target)
    try:
        await ai1.run()
    except SystemExit as e:
        print(f"AI1 exited prematurely: {e}")
        raise  # Reraise SystemExit to ensure the program exits
    except Exception as e:
        print(f"An unexpected error occurred in AI1 main loop: {e}")


if __name__ == "__main__":
    asyncio.run(main())
