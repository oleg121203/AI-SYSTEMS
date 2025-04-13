import asyncio
import json
import logging
import os
import time
import uuid  # Import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp

# Используем функцию load_config из config.py
from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import apply_request_delay, log_message  # Import apply_request_delay

config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class AI1:
    """
    AI1 - Координатор проекта
    Формулирует задачи для AI2 на основе структуры проекта и следит за прогрессом,
    при необходимости дробит задачи и управляет циклами доработки.
    """

    def __init__(self, target: str):
        self.target = target
        ai1_config_base = config.get("ai_config", {})
        ai1_config = ai1_config_base.get("ai1", {})
        if not ai1_config:
            log_message(
                "[AI1] Warning: 'ai_config.ai1' section not found in configuration. Using defaults."
            )
            ai1_config = {"provider": "openai"}

        provider_name = ai1_config.get("provider", "openai")
        log_message(f"[AI1] Initializing with provider: {provider_name}")

        try:
            # Передаем только имя провайдера, фабрика сама найдет конфиг
            self.llm: BaseProvider = ProviderFactory.create_provider(provider_name)
            log_message(f"[AI1] Provider '{provider_name}' created successfully.")
        except ValueError as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Failed to create provider '{provider_name}'. {e}. Exiting."
            )
            raise SystemExit(f"AI1 failed to initialize provider: {e}")
        except Exception as e:
            log_message(
                f"[AI1] CRITICAL ERROR: Unexpected error creating provider '{provider_name}'. {e}. Exiting."
            )
            raise SystemExit(
                f"AI1 failed with unexpected error during provider init: {e}"
            )

        self.status = "initializing"
        self.project_structure: Optional[Dict] = None
        self.structure_fetch_attempted = False
        self.files_to_fill = []
        self.files_to_test = []
        self.files_to_document = []
        # Task statuses: pending, sending, sent, code_received, fetch_failed,
        #                tested, accepted, review_needed, failed_tests,
        #                completed_by_ai2, failed_by_ai2, error_processing, skipped,
        #                pending_refinement, refinement_sent
        self.task_status: Dict[str, Dict[str, Any]] = (
            {}
        )  # Status can now hold more info
        self.active_tasks = set()  # Stores "filename::role::subtask_id"
        self.original_task_text: Dict[str, Dict[str, str]] = (
            {}
        )  # Store original text for refinement
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
        """Основной цикл работы AI1"""
        log_message(f"[AI1] Started with target: {self.target}")
        self.status = "waiting_for_structure"

        try:
            # Получаем структуру проекта
            await self.ensure_structure_received()
            if not self.project_structure:
                log_message("[AI1] Failed to obtain project structure. Exiting.")
                self.status = "error"
                return

            # Строим структуру задач и консультируемся с дозором (AI3)
            log_message("[AI1] Начинаю построение структуры задач...")
            await self.build_task_structure()

            # Инициализируем статусы задач
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
        )
        self.files_to_test = [
            f for f in self.files_to_fill if f.lower().endswith(testable_extensions)
        ]
        self.files_to_document = list(
            self.files_to_fill
        )  # All files need documentation

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
                    # Normalize path separators for consistency
                    files.append(os.path.normpath(new_path).replace(os.sep, "/"))
        return files

    def initialize_task_status(self):
        """Инициализирует словарь статусов задач для всех файлов."""
        self.task_status = {}
        self.original_task_text = {}
        for file_path in self.files_to_fill:
            self.task_status[file_path] = {
                "executor": {
                    "status": "pending",
                    "reason": None,
                    "original_text": None,
                    "failure_count": 0,  # Счетчик неудачных попыток
                },
                "tester": {
                    "status": (
                        "pending" if file_path in self.files_to_test else "skipped"
                    ),
                    "reason": None,
                    "original_text": None,
                    "failure_count": 0,  # Счетчик неудачных попыток
                },
                "documenter": {
                    "status": "pending",
                    "reason": None,
                    "original_text": None,
                    "failure_count": 0,  # Счетчик неудачных попыток
                },
            }
            self.original_task_text[file_path] = {}  # Initialize inner dict
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
        api_url = f"{MCP_API_URL}/all_statuses"
        log_message(f"[AI1] Querying API for all subtask statuses...")
        await apply_request_delay("ai1")  # Add delay before request
        try:
            session = await self._get_api_session()
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    if "statuses" in data:
                        log_message(
                            f"[AI1] Received {len(data['statuses'])} task statuses from API."
                        )
                        return data["statuses"]
                    else:
                        log_message(
                            f"[AI1] API response missing 'statuses' key: {data}"
                        )
                        return {}
                else:
                    log_message(
                        f"[AI1] Failed to get all statuses. Status: {response.status}"
                    )
                    return {}
        except asyncio.TimeoutError:
            log_message(f"[AI1] Timeout getting all statuses.")
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

        tasks_to_remove = set()
        for task_key in list(self.active_tasks):
            try:
                filename, role, subtask_id = task_key.split("::")
                api_status_data = api_statuses.get(
                    subtask_id
                )  # API might return more than just status string

                if api_status_data:
                    # Assuming API returns a dict like {'status': '...', 'details': '...'} or just status string
                    api_status = (
                        api_status_data
                        if isinstance(api_status_data, str)
                        else api_status_data.get("status")
                    )
                    api_details = (
                        None
                        if isinstance(api_status_data, str)
                        else api_status_data.get("details")
                    )

                    if not api_status:
                        log_message(
                            f"[AI1] Warning: No status found in API data for {subtask_id}: {api_status_data}"
                        )
                        continue  # Skip if status is missing

                    local_task_entry = self.task_status.get(filename, {}).get(role)
                    local_status = (
                        local_task_entry.get("status") if local_task_entry else None
                    )

                    # Define final states
                    final_states = [
                        "accepted",
                        "skipped",
                    ]

                    # Ошибки, которые требуют исправления (не считаются "финальными")
                    refinement_needed_states = [
                        "review_needed",
                        "failed_tests",
                        "failed_by_ai2",  # Теперь это не финальная ошибка, а состояние, требующее исправления
                        "error_processing",  # Теперь это не финальная ошибка, а состояние, требующее исправления
                    ]

                    if api_status != local_status:
                        log_message(
                            f"[AI1] Updating status for {filename} ({role}) from '{local_status}' to '{api_status}' (Subtask: {subtask_id})"
                        )
                        if local_task_entry:
                            local_task_entry["status"] = api_status
                            local_task_entry["reason"] = (
                                api_details  # Store reason if provided
                            )
                            updated_count += 1
                        else:
                            log_message(
                                f"[AI1] Warning: Cannot update status for non-existent local task {filename} ({role})"
                            )

                    # Если задача требует доработки, отмечаем её локально для повторного выполнения
                    if api_status in refinement_needed_states and local_task_entry:
                        local_task_entry["status"] = "pending_refinement"
                        log_message(
                            f"[AI1] Marked {filename} ({role}) as pending_refinement due to API status '{api_status}'. Reason: {api_details}"
                        )
                        tasks_to_remove.add(
                            task_key
                        )  # Remove original task from active set

                    # Удаляем из активных задач только если достигнуто финальное состояние
                    elif api_status in final_states:
                        tasks_to_remove.add(task_key)
                else:
                    log_message(
                        f"[AI1] Warning: Active subtask {subtask_id} ({filename}::{role}) not found in API status response."
                    )
                    # Consider removing after a timeout or multiple misses
                    # tasks_to_remove.add(task_key)

            except ValueError:
                log_message(f"[AI1] Error parsing active task key: {task_key}")
                tasks_to_remove.add(task_key)
            except Exception as e:
                log_message(
                    f"[AI1] Error processing active task {task_key} during status update: {e}"
                )

        self.active_tasks -= tasks_to_remove
        log_message(
            f"[AI1] Local task statuses updated ({updated_count} changes). Active tasks remaining: {len(self.active_tasks)}"
        )

    async def manage_tasks(self):
        """Основная логика управления задачами: создание, отслеживание и доработка."""
        log_message("[AI1] Starting task management cycle...")
        await self.update_local_task_statuses()

        tasks_to_send = []
        refinement_tasks_to_send = []

        for file_path, roles_status in self.task_status.items():
            executor_status = roles_status["executor"]["status"]
            tester_status = roles_status["tester"]["status"]
            documenter_status = roles_status["documenter"]["status"]

            # Define conditions for triggering next steps
            executor_done_statuses = [
                "code_received",
                "tested",
                "accepted",
                "completed_by_ai2",
                "skipped",  # Skipped executor means we can proceed
            ]
            # Consider a task done if it's accepted or skipped
            is_executor_done = (
                executor_status in executor_done_statuses
                or executor_status == "accepted"
            )
            is_tester_done = tester_status in ["accepted", "skipped"]
            is_documenter_done = documenter_status in ["accepted", "skipped"]

            # --- Handle Refinement First ---
            for role, status_info in roles_status.items():
                if status_info["status"] == "pending_refinement":
                    log_message(
                        f"[AI1] Preparing refinement task for {file_path} ({role}). Reason: {status_info.get('reason')}"
                    )
                    # Store original text if not already stored
                    if not self.original_task_text.get(file_path, {}).get(role):
                        # Attempt to retrieve original text (might need adjustment based on how it was stored)
                        original_text = status_info.get(
                            "original_text", f"Original task for {file_path} ({role})"
                        )
                        self.original_task_text[file_path][role] = original_text

                    refinement_tasks_to_send.append(
                        {
                            "file_path": file_path,
                            "role": role,
                            "original_text": self.original_task_text[file_path][role],
                            "reason": status_info.get("reason", "Unknown failure"),
                        }
                    )
                    status_info["status"] = (
                        "refinement_sending"  # Mark as being processed
                    )

            # --- Handle Regular Task Progression ---
            # 1. Executor tasks
            if executor_status == "pending":
                task_text = f"Implement the required functionality in file: {file_path} based on the overall project goal: {self.target}"
                self.original_task_text[file_path][
                    "executor"
                ] = task_text  # Store original text
                tasks_to_send.append(
                    {
                        "task_text": task_text,
                        "role": "executor",
                        "filename": file_path,
                        "code": None,
                    }
                )
                roles_status["executor"]["status"] = "sending"

            # 2. Tester tasks (only if executor is done and tester is pending)
            if is_executor_done and tester_status == "pending":
                code_content = await self.get_file_content(file_path)
                if code_content is not None:
                    task_text = f"Generate unit tests for the code in file: {file_path}"
                    self.original_task_text[file_path][
                        "tester"
                    ] = task_text  # Store original text
                    tasks_to_send.append(
                        {
                            "task_text": task_text,
                            "role": "tester",
                            "filename": file_path,
                            "code": code_content,
                        }
                    )
                    roles_status["tester"]["status"] = "sending"
                else:
                    log_message(
                        f"[AI1] Failed to fetch content for {file_path} to create tester task. Will retry."
                    )
                    roles_status["tester"]["status"] = "fetch_failed"

            # 3. Documenter tasks (only if executor is done and documenter is pending)
            if is_executor_done and documenter_status == "pending":
                code_content = await self.get_file_content(file_path)
                if code_content is not None:
                    task_text = f"Generate documentation (e.g., docstrings, comments, README section) for the code in file: {file_path}"
                    self.original_task_text[file_path][
                        "documenter"
                    ] = task_text  # Store original text
                    tasks_to_send.append(
                        {
                            "task_text": task_text,
                            "role": "documenter",
                            "filename": file_path,
                            "code": code_content,
                        }
                    )
                    roles_status["documenter"]["status"] = "sending"
                else:
                    log_message(
                        f"[AI1] Failed to fetch content for {file_path} to create documenter task. Will retry."
                    )
                    roles_status["documenter"]["status"] = "fetch_failed"

            # Handle retrying failed fetches
            elif tester_status == "fetch_failed":
                log_message(f"[AI1] Retrying fetch for tester task: {file_path}")
                roles_status["tester"]["status"] = "pending"
            elif documenter_status == "fetch_failed":
                log_message(f"[AI1] Retrying fetch for documenter task: {file_path}")
                roles_status["documenter"]["status"] = "pending"

        # --- Send Refinement Tasks ---
        if refinement_tasks_to_send:
            log_message(
                f"[AI1] Attempting to send {len(refinement_tasks_to_send)} refinement subtasks..."
            )
            refinement_results = await asyncio.gather(
                *[
                    self.create_refinement_subtask(**task_data)
                    for task_data in refinement_tasks_to_send
                ],
                return_exceptions=True,
            )
            # Process refinement results (similar to regular tasks)
            for i, result in enumerate(refinement_results):
                task_data = refinement_tasks_to_send[i]
                file_path = task_data["file_path"]
                role = task_data["role"]
                subtask_id = result if isinstance(result, str) else None

                if isinstance(result, Exception) or result is False:
                    error_msg = (
                        result
                        if isinstance(result, Exception)
                        else "API returned failure"
                    )
                    log_message(
                        f"[AI1] Failed to send refinement subtask for {file_path} ({role}): {error_msg}"
                    )
                    if (
                        self.task_status[file_path][role]["status"]
                        == "refinement_sending"
                    ):
                        self.task_status[file_path][role][
                            "status"
                        ] = "pending_refinement"  # Reset to retry refinement
                elif subtask_id:
                    task_key = f"{file_path}::{role}::{subtask_id}"
                    self.active_tasks.add(task_key)
                    log_message(
                        f"[AI1] Refinement subtask {subtask_id} sent for {file_path} ({role}). Added to active tasks."
                    )
                    if (
                        self.task_status[file_path][role]["status"]
                        == "refinement_sending"
                    ):
                        self.task_status[file_path][role]["status"] = "refinement_sent"

        # --- Send Regular Tasks ---
        if tasks_to_send:
            log_message(
                f"[AI1] Attempting to send {len(tasks_to_send)} new subtasks..."
            )
            results = await asyncio.gather(
                *[self.create_subtask(**task_data) for task_data in tasks_to_send],
                return_exceptions=True,
            )
            # Process results
            for i, result in enumerate(results):
                task_data = tasks_to_send[i]
                file_path = task_data["filename"]
                role = task_data["role"]
                subtask_id = result if isinstance(result, str) else None

                if isinstance(result, Exception) or result is False:
                    error_msg = (
                        result
                        if isinstance(result, Exception)
                        else "API returned failure"
                    )
                    log_message(
                        f"[AI1] Failed to send subtask for {file_path} ({role}): {error_msg}"
                    )
                    if self.task_status[file_path][role]["status"] == "sending":
                        self.task_status[file_path][role][
                            "status"
                        ] = "pending"  # Reset to retry
                elif subtask_id:
                    task_key = f"{file_path}::{role}::{subtask_id}"
                    self.active_tasks.add(task_key)
                    log_message(
                        f"[AI1] Subtask {subtask_id} sent for {file_path} ({role}). Added to active tasks."
                    )
                    if self.task_status[file_path][role]["status"] == "sending":
                        self.task_status[file_path][role]["status"] = "sent"
        else:
            log_message("[AI1] No new regular tasks to send in this cycle.")

    async def create_refinement_subtask(
        self, file_path: str, role: str, original_text: str, reason: str
    ) -> Union[str, bool, Exception]:
        """Creates a subtask specifically for refining a previous failed attempt."""
        log_message(f"[AI1] Generating refinement task for {file_path} ({role})")

        # Получаем код файла, если он существует
        code_content = await self.get_file_content(file_path)

        # Определяем, нужно ли разбить задачу на более мелкие подзадачи
        should_decompose = False
        failure_count = (
            self.task_status.get(file_path, {}).get(role, {}).get("failure_count", 0)
        )

        # Увеличиваем счетчик неудач
        if file_path in self.task_status and role in self.task_status[file_path]:
            self.task_status[file_path][role]["failure_count"] = failure_count + 1

            # Если было больше 2 неудачных попыток, пробуем разбить задачу
            if failure_count >= 2:
                should_decompose = True
                log_message(
                    f"[AI1] Task for {file_path} ({role}) has failed {failure_count} times. Attempting to decompose into smaller subtasks."
                )

        # Создаем основной или декомпозиционный промпт в зависимости от количества неудач
        if should_decompose:
            # Промпт для разбиения задачи на более мелкие
            if role == "executor":
                refinement_prompt = f"""
                Задача для файла '{file_path}' не прошла тесты несколько раз. 
                Причина: '{reason}'.
                
                Оригинальная задача: '{original_text}'.
                
                Текущий код:
                ```
                {code_content if code_content else 'Файл еще не создан или не доступен'}
                ```
                
                Разбейте эту сложную задачу на несколько меньших шагов:
                1. Опишите основные компоненты, которые нужно реализовать
                2. Исправьте все указанные проблемы
                3. Предоставьте полностью обновленную реализацию, которая учитывает все требования и проходит тесты
                
                Будьте особенно внимательны к:
                - Тестам, которые не проходят
                - Логике, которая может быть неверна
                - Пограничным случаям, которые могли быть не учтены
                """
            elif role == "tester":
                refinement_prompt = f"""
                Тесты для файла '{file_path}' не работают должным образом. 
                Причина: '{reason}'.
                
                Оригинальная задача: '{original_text}'.
                
                Код, который нужно тестировать:
                ```
                {code_content if code_content else 'Файл не доступен'}
                ```
                
                Пожалуйста, создайте более тщательные тесты:
                1. Напишите тесты для каждой отдельной функции/метода
                2. Включите тесты для граничных случаев
                3. Проверьте обработку ошибок
                4. Убедитесь, что тесты соответствуют ожидаемому поведению кода
                """
            elif role == "documenter":
                refinement_prompt = f"""
                Документация для файла '{file_path}' требует улучшения. 
                Причина: '{reason}'.
                
                Оригинальная задача: '{original_text}'.
                
                Код, который нужно документировать:
                ```
                {code_content if code_content else 'Файл не доступен'}
                ```
                
                Пожалуйста, улучшите документацию:
                1. Детально опишите каждую функцию/метод/класс
                2. Уточните параметры и возвращаемые значения
                3. Добавьте примеры использования, где это уместно
                4. Документируйте все возможные исключения/ошибки
                """
            else:
                # Общий случай для других ролей
                refinement_prompt = f"""
                Задача для файла '{file_path}' ({role}) требует улучшения после нескольких неудачных попыток. 
                Причина: '{reason}'.
                
                Оригинальная задача: '{original_text}'.
                
                Разбейте эту задачу на меньшие компоненты и решите каждый по отдельности.
                Обратите особое внимание на указанные проблемы и предоставьте улучшенное решение.
                """
        else:
            # Стандартный промпт исправления
            refinement_prompt = f"""
            Требуется доработка для файла '{file_path}' ({role}).
            Причина: '{reason}'.
            
            Оригинальная задача: '{original_text}'.
            
            Текущее содержимое (если доступно):
            ```
            {code_content if code_content else 'Файл еще не создан или не доступен'}
            ```
            
            Пожалуйста, исправьте указанные проблемы и предоставьте обновленное решение.
            """

        # Используем существующую функцию create_subtask с новым промптом
        return await self.create_subtask(
            task_text=refinement_prompt,
            role=role,
            filename=file_path,
            code=code_content,
        )

    async def create_subtask(
        self, task_text: str, role: str, filename: str, code: Optional[str] = None
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
            }
        }
        if code is not None:
            payload["subtask"]["code"] = code

        log_message(
            f"[AI1] Sending subtask: ID={subtask_id}, Role={role}, Filename={filename}{', Code included' if code is not None else ''}"
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

    def check_completion(self) -> bool:
        """Проверяет, все ли задачи выполнены (статус 'accepted' или 'skipped')."""
        if not self.task_status:
            log_message("[AI1] Task status not initialized, cannot check completion.")
            return False

        final_complete_statuses = ["accepted", "skipped"]
        # Consider tasks needing refinement or failed as NOT complete for the overall project goal
        incomplete_statuses = [
            "pending",
            "sending",
            "sent",
            "code_received",
            "tested",
            "fetch_failed",
            "pending_refinement",
            "refinement_sending",
            "refinement_sent",
            "processing",
            "review_needed",
            "failed_tests",
            "failed_by_ai2",
            "error_processing",
        ]  # Added refinement states

        for file_path, roles_status in self.task_status.items():
            for role, status_info in roles_status.items():
                status = status_info["status"]
                if status not in final_complete_statuses:
                    # Log the first incomplete task found for debugging
                    # log_message(f"[AI1] Completion check: Task {file_path} ({role}) is not complete (Status: {status}).")
                    return False  # Found an incomplete task

        log_message(
            "[AI1] Completion check: All tasks are in a final 'accepted' or 'skipped' state."
        )
        return True

    async def build_task_structure(self):
        """
        Строит первоначальную структуру задач на основе цели проекта и структуры файлов.
        Консультируется с AI3 (дозором) для улучшения структуры задач.
        """
        log_message("[AI1] Начинаю построение структуры задач на основе цели проекта")

        try:
            # 1. Создаем базовую структуру задач на основе имеющихся файлов
            task_structure = {
                "main_tasks": [],  # Основные задачи
                "dependencies": {},  # Зависимости между задачами
                "priority": {},  # Приоритеты задач
            }

            # Сначала сгруппируем файлы по типам/компонентам
            component_groups = self._group_files_by_component()

            # Создаем основные задачи на основе компонентов
            for component, files in component_groups.items():
                main_task = {
                    "id": str(uuid.uuid4()),
                    "name": f"Реализация компонента: {component}",
                    "description": f"Разработка функциональности для компонента {component}",
                    "files": files,
                    "subtasks": [],  # Будет заполнено позже
                }

                task_structure["main_tasks"].append(main_task)

                # Определяем приоритет для основной задачи
                if "backend" in component.lower() or "core" in component.lower():
                    task_structure["priority"][main_task["id"]] = "high"
                elif "frontend" in component.lower() or "ui" in component.lower():
                    task_structure["priority"][main_task["id"]] = "medium"
                else:
                    task_structure["priority"][main_task["id"]] = "normal"

            # 2. Консультируемся с AI3 (дозором) для улучшения структуры
            improved_structure = await self._consult_with_overseer(task_structure)

            # 3. Сохраняем финальную структуру задач
            self.task_structure = improved_structure
            log_message(
                f"[AI1] Структура задач построена: {len(improved_structure['main_tasks'])} основных задач"
            )

            # 4. Разбиваем каждую основную задачу на микрозадачи
            await self._decompose_main_tasks()

            return True
        except Exception as e:
            log_message(f"[AI1] Ошибка при построении структуры задач: {e}")
            return False

    def _group_files_by_component(self) -> Dict[str, List[str]]:
        """
        Группирует файлы по компонентам проекта для создания основных задач.
        """
        component_groups = {}

        # Определяем ключевые директории/компоненты
        components = {
            "Backend": ["backend", "api", "server"],
            "Frontend": ["frontend", "ui", "web"],
            "Database": ["db", "database", "models"],
            "Auth": ["auth", "login", "security"],
            "Utils": ["utils", "helpers", "common"],
            "Tests": ["tests", "spec", "test"],
            "Docs": ["docs", "documentation", "wiki"],
        }

        # Распределяем файлы по компонентам
        for file_path in self.files_to_fill:
            assigned = False
            for component, keywords in components.items():
                if any(keyword in file_path.lower() for keyword in keywords):
                    if component not in component_groups:
                        component_groups[component] = []
                    component_groups[component].append(file_path)
                    assigned = True
                    break

            # Если не удалось определить компонент, добавляем в "Misc" (Разное)
            if not assigned:
                if "Misc" not in component_groups:
                    component_groups["Misc"] = []
                component_groups["Misc"].append(file_path)

        return component_groups

    async def _consult_with_overseer(self, task_structure: Dict) -> Dict:
        """
        Консультируется с AI3 (дозором) для улучшения структуры задач.
        Отправляет запрос AI3 и получает рекомендации.
        """
        log_message("[AI1] Консультируюсь с AI3 (дозором) по структуре задач")

        try:
            api_url = f"{MCP_API_URL}/consult_task_structure"
            session = await self._get_api_session()

            request_data = {"task_structure": task_structure, "target": self.target}

            async with session.post(api_url, json=request_data, timeout=60) as response:
                if response.status == 200):
                    result = await response.json()
                    improved_structure = result.get(
                        "improved_structure", task_structure
                    )
                    recommendations = result.get("recommendations", [])

                    log_message(
                        f"[AI1] Получены рекомендации от AI3: {len(recommendations)} пунктов"
                    )
                    for i, rec in enumerate(recommendations, 1):
                        log_message(f"[AI1] Рекомендация {i}: {rec}")

                    return improved_structure
                else:
                    log_message(
                        f"[AI1] Ошибка при консультации с AI3: {response.status}, {await response.text()}"
                    )
                    return task_structure
        except Exception as e:
            log_message(f"[AI1] Ошибка при консультации с AI3: {e}")
            return task_structure

    async def _decompose_main_tasks(self):
        """
        Разбивает каждую основную задачу на микрозадачи и консультируется с AI3.
        """
        if not hasattr(self, "task_structure") or not self.task_structure.get(
            "main_tasks"
        ):
            log_message("[AI1] Ошибка: структура задач не создана")
            return

        log_message("[AI1] Начинаю разбиение основных задач на микрозадачи")

        for main_task in self.task_structure["main_tasks"]:
            log_message(f"[AI1] Разбиваю задачу: {main_task['name']}")

            # Создаем микрозадачи для файлов в этой основной задаче
            subtasks = []
            for file_path in main_task["files"]:
                subtask = {
                    "id": str(uuid.uuid4()),
                    "name": f"Реализация файла: {file_path}",
                    "description": f"Разработка функциональности для {file_path}",
                    "file_path": file_path,
                    "main_task_id": main_task["id"],
                    "steps": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Разработка базовой структуры",
                            "role": "executor",
                            "status": "pending",
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Написание тестов",
                            "role": "tester",
                            "status": "pending",
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "name": "Создание документации",
                            "role": "documenter",
                            "status": "pending",
                        },
                    ],
                }
                subtasks.append(subtask)

            # Консультируемся с AI3 по микрозадачам
            main_task["subtasks"] = await self._consult_subtasks(
                main_task["id"], subtasks
            )

            log_message(
                f"[AI1] Задача {main_task['name']} разбита на {len(main_task['subtasks'])} микрозадач"
            )

        log_message("[AI1] Завершено разбиение всех основных задач на микрозадачи")

    async def _consult_subtasks(
        self, main_task_id: str, subtasks: List[Dict]
    ) -> List[Dict]:
        """
        Консультируется с AI3 по структуре микрозадач для конкретной основной задачи.
        """
        log_message(
            f"[AI1] Консультируюсь с AI3 по микрозадачам для задачи {main_task_id}"
        )

        try:
            api_url = f"{MCP_API_URL}/consult_subtasks"
            session = await self._get_api_session()

            request_data = {
                "main_task_id": main_task_id,
                "subtasks": subtasks,
                "target": self.target,
            }

            async with session.post(api_url, json=request_data, timeout=60) as response:
                if response.status == 200):
                    result = await response.json()
                    improved_subtasks = result.get("improved_subtasks", subtasks)
                    recommendations = result.get("recommendations", [])

                    log_message(
                        f"[AI1] Получены рекомендации от AI3 по микрозадачам: {len(recommendations)} пунктов"
                    )
                    for i, rec in enumerate(recommendations, 1):
                        log_message(f"[AI1] Рекомендация {i}: {rec}")

                    return improved_subtasks
                else:
                    log_message(
                        f"[AI1] Ошибка при консультации с AI3 по микрозадачам: {response.status}, {await response.text()}"
                    )
                    return subtasks
        except Exception as e:
            log_message(f"[AI1] Ошибка при консультации с AI3 по микрозадачам: {e}")
            return subtasks

    async def handle_test_result(self, test_data):
        """
        Обрабатывает результаты тестов из GitHub Actions и принимает решение
        на основе рекомендаций AI3 (дозор).

        Args:
            test_data: Данные о результатах тестов
        """
        run_id = test_data.get("run_id")
        result = test_data.get("result")
        files = test_data.get("files", [])
        ai3_recommendation = test_data.get("recommendation", "")
        comments = test_data.get("comments", [])

        log_message(
            f"[AI1] Получены результаты тестов от GitHub Actions: run_id={run_id}"
        )
        log_message(f"[AI1] Результат тестов: {result}")
        log_message(f"[AI1] Рекомендация AI3 (дозор): {ai3_recommendation}")

        if not files:
            log_message(
                "[AI1] Предупреждение: в данных о тестах отсутствует информация о файлах"
            )
            return

        # Определяем задачи, связанные с протестированными файлами
        affected_tasks = []
        for file_info in files:
            source_file = file_info.get("source_file")
            test_file = file_info.get("test_file")

            if source_file:
                # Находим задачи, связанные с этим файлом
                tasks = self.find_tasks_by_filename(source_file)
                affected_tasks.extend(tasks)

                # Логируем информацию о файле и результате теста
                log_message(
                    f"[AI1] Файл: {source_file}, тест: {test_file}, результат: {result}"
                )

        # Принимаем решение на основе результата и рекомендации AI3
        decision = self.decide_on_test_results(result, ai3_recommendation, comments)

        # Применяем решение к затронутым задачам
        for task in affected_tasks:
            task_id = task.get("id")

            if decision == "accept":
                # Принимаем задачу
                log_message(
                    f"[AI1] Принимаю задачу {task_id} после успешного тестирования"
                )
                self.mark_task_as_accepted(task_id)
            elif decision == "rework":
                # Отправляем задачу на доработку
                log_message(
                    f"[AI1] Отправляю задачу {task_id} на доработку из-за ошибок в тестах"
                )
                self.mark_task_for_rework(task_id, comments)

        # Обновляем отслеживание прогресса
        self.update_progress_tracking()

    def decide_on_test_results(self, result, ai3_recommendation, comments):
        """
        Принимает решение на основе результатов тестов и рекомендации AI3.

        Args:
            result: Результат запуска тестов (success/failure)
            ai3_recommendation: Рекомендация от AI3 (accept/rework)
            comments: Комментарии от AI3

        Returns:
            Строка с решением ("accept" или "rework")
        """
        # По умолчанию следуем рекомендации AI3
        decision = ai3_recommendation

        # Если тесты успешны, но нет явной рекомендации, принимаем
        if result == "success" and not decision:
            decision = "accept"

        # Если тесты неуспешны, но нет явной рекомендации, требуем доработки
        if result != "success" and not decision:
            decision = "rework"

        # Логируем принятое решение и его основания
        if decision == "accept":
            log_message(
                f"[AI1] Решение: принять задачу. Основание: {result}, рекомендация AI3: {ai3_recommendation}"
            )
        else:
            log_message(
                f"[AI1] Решение: отправить на доработку. Основание: {result}, рекомендация AI3: {ai3_recommendation}"
            )
            if comments:
                log_message(f"[AI1] Комментарии AI3: {', '.join(comments)}")

        return decision

    def find_tasks_by_filename(self, filename):
        """
        Находит задачи, связанные с указанным файлом.

        Args:
            filename: Путь к файлу

        Returns:
            Список задач, связанных с файлом
        """
        matching_tasks = []

        # Ищем во всех задачах
        for task_list in [self.main_tasks, self.subtasks]:
            for task in task_list:
                if task.get("filename") == filename:
                    matching_tasks.append(task)

                # Также проверяем, есть ли этот файл в списке related_files
                related_files = task.get("related_files", [])
                if filename in related_files:
                    matching_tasks.append(task)

        return matching_tasks

    def mark_task_as_accepted(self, task_id):
        """
        Отмечает задачу как принятую после успешного тестирования.

        Args:
            task_id: ID задачи
        """
        # Обновляем статус задачи
        for task in self.subtasks:
            if task.get("id") == task_id:
                task["status"] = "accepted"
                task["completed_at"] = datetime.now().isoformat()
                break

        # Отправляем обновление статуса в API
        asyncio.create_task(self.update_task_status(task_id, "accepted"))

    def mark_task_for_rework(self, task_id, comments=None):
        """
        Отмечает задачу для доработки после неудачного тестирования.

        Args:
            task_id: ID задачи
            comments: Комментарии с описанием проблем
        """
        # Находим задачу
        task_to_rework = None
        for task in self.subtasks:
            if task.get("id") == task_id:
                task_to_rework = task
                task["status"] = "needs_rework"
                task["rework_reason"] = "Неудачное тестирование"
                if comments:
                    task["rework_comments"] = comments
                break

        if not task_to_rework:
            log_message(
                f"[AI1] Предупреждение: задача {task_id} не найдена для отправки на доработку"
            )
            return

        # Создаем новую подзадачу для доработки
        filename = task_to_rework.get("filename")
        if filename:
            rework_task = {
                "id": str(uuid.uuid4()),
                "parent_id": task_to_rework.get("parent_id"),
                "filename": filename,
                "role": "executor",  # Всегда назначаем исполнителю
                "text": self.generate_rework_description(task_to_rework, comments),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "priority": "high",  # Высокий приоритет для доработок
                "original_task_id": task_id,  # Ссылка на исходную задачу
            }

            # Добавляем задачу в список и отправляем в API
            self.subtasks.append(rework_task)
            asyncio.create_task(self.submit_subtask(rework_task))
            log_message(
                f"[AI1] Создана новая задача для доработки: {rework_task['id']} для файла {filename}"
            )

    def generate_rework_description(self, original_task, comments=None):
        """
        Генерирует описание задачи на доработку.

        Args:
            original_task: Исходная задача
            comments: Комментарии от тестов

        Returns:
            Строка с описанием задачи на доработку
        """
        filename = original_task.get("filename", "")
        description = f"ДОРАБОТКА: Исправьте ошибки в файле {filename} после неудачного тестирования."

        if comments:
            description += "\n\nПроблемы, которые нужно исправить:\n"
            for i, comment in enumerate(comments, 1):
                description += f"{i}. {comment}\n"

        return description


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
    except Exception as e:
        print(f"An unexpected error occurred in AI1 main loop: {e}")


if __name__ == "__main__":
    asyncio.run(main())
