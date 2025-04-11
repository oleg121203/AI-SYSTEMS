import asyncio
import importlib
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from git import GitCommandError, Repo

from config import load_config
from providers import BaseProvider, ProviderFactory
from utils import apply_request_delay  # Import apply_request_delay
from utils import log_message, logger, wait_for_service

logger = logging.getLogger(__name__)  # Use logger correctly

config = load_config()
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")
REPO_DIR = config.get("repo_dir", "repo")
LOG_FILE_PATH = config.get("log_file", "logs/mcp.log")  # Still needed for general logs


def _init_or_open_repo(repo_path: str) -> Repo:
    try:
        Path(repo_path).mkdir(parents=True, exist_ok=True)
        repo = Repo(repo_path)
        log_message(f"[AI3-Git] Opened existing repository at: {repo_path}")
        return repo
    except Exception:
        try:
            repo = Repo.init(repo_path)
            log_message(f"[AI3-Git] Initialized new repository at: {repo_path}")
            gitignore_path = os.path.join(repo_path, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w") as f:
                    f.write("# Ignore OS-specific files\n.DS_Store\n")
                    f.write("# Ignore virtual environment files\nvenv/\n.venv/\n")
                    f.write("# Ignore IDE files\n.idea/\n.vscode/\n")
                    f.write("# Ignore log files\nlogs/\n*.log\n")
                try:
                    repo.index.add([".gitignore"])
                    repo.index.commit("Add .gitignore")
                    log_message("[AI3-Git] Added .gitignore and committed.")
                except GitCommandError as git_e:
                    log_message(
                        f"[AI3-Git] Warning: Failed to commit .gitignore: {git_e}"
                    )
            return repo
        except Exception as init_e:
            log_message(
                f"[AI3-Git] CRITICAL: Failed to initialize or open repository at {repo_path}: {init_e}"
            )
            raise


def _commit_changes(repo: Repo, file_paths: list, message: str):
    if not file_paths:
        return
    try:
        valid_paths = [
            os.path.relpath(p, repo.working_dir)
            for p in file_paths
            if os.path.exists(p)
        ]
        paths_to_add = [
            p
            for p in valid_paths
            if p in repo.untracked_files
            or p in [item.a_path for item in repo.index.diff(None)]
        ]

        if not paths_to_add and not repo.is_dirty(
            untracked_files=True, path=valid_paths
        ):
            log_message(f"[AI3-Git] No changes detected in {valid_paths} to commit.")
            return

        if paths_to_add:
            repo.index.add(paths_to_add)

        if repo.is_dirty():
            repo.index.commit(message)
            log_message(
                f"[AI3-Git] Committed changes for {len(paths_to_add)} file(s): {message}"
            )
        else:
            log_message(f"[AI3-Git] No staged changes to commit for message: {message}")

    except GitCommandError as e:
        log_message(
            f"[AI3-Git] Error committing changes: {message}. Files: {file_paths}. Error: {e}"
        )
    except Exception as e:
        log_message(f"[AI3-Git] Unexpected error during commit: {e}")


async def generate_structure(target: str) -> dict:
    prompt = f"""
Generate a JSON structure for a project with the target: "{target}".
Respond ONLY with the JSON structure itself, enclosed in triple backticks (```json ... ```).
The structure should be a valid JSON object representing directories and files. Use null for files.
Example:
```json
{{
  "src": {{
    "main.py": null,
    "utils.py": null
  }},
  "tests": {{
    "test_main.py": null
  }},
  "README.md": null,
  ".gitignore": null
}}
```
Do not include any explanatory text before or after the JSON block. Ensure the JSON is well-formed.
"""
    ai_config_base = config.get("ai_config", {})
    ai3_config = ai_config_base.get("ai3", {})
    if not ai3_config:
        log_message("[AI3] Warning: 'ai_config.ai3' section not found. Using defaults.")
        ai3_config = {"provider": "openai"}

    provider_name = ai3_config.get("provider", "openai")

    response_text = None
    primary_provider = None
    fallback_provider = None
    try:
        log_message(
            f"[AI3] Attempting structure generation with provider: {provider_name}"
        )
        primary_provider: BaseProvider = ProviderFactory.create_provider(provider_name)
        # Removed finally block with close_session
        await apply_request_delay("ai3")  # Add delay before primary generation
        response_text = await primary_provider.generate(
            prompt=prompt,
            model=ai3_config.get("model"),
            max_tokens=ai3_config.get("max_tokens"),
            temperature=ai3_config.get("temperature"),
        )
        if isinstance(response_text, str) and response_text.startswith(
            "Ошибка генерации"
        ):
            raise Exception(
                f"Primary provider '{provider_name}' failed: {response_text}"
            )

        log_message(
            f"[AI3] Raw response preview from '{provider_name}': {response_text[:200] if response_text else 'None'}"
        )

    except Exception as e:
        primary_provider_name_for_log = (
            primary_provider.name if primary_provider else provider_name
        )
        log_message(
            f"[AI3] Error calling primary provider '{primary_provider_name_for_log}': {e}"
        )
        fallback_provider_name = ai3_config.get("fallback_provider")
        if fallback_provider_name:
            log_message(f"[AI3] Attempting fallback provider: {fallback_provider_name}")
            try:
                fallback_provider: BaseProvider = ProviderFactory.create_provider(
                    fallback_provider_name
                )
                # Removed finally block with close_session
                await apply_request_delay("ai3")  # Add delay before fallback generation
                response_text = await fallback_provider.generate(
                    prompt=prompt,
                    model=ai3_config.get("model"),
                    max_tokens=ai3_config.get("max_tokens"),
                    temperature=ai3_config.get("temperature"),
                )
                if isinstance(response_text, str) and response_text.startswith(
                    "Ошибка генерации"
                ):
                    raise Exception(
                        f"Fallback provider '{fallback_provider_name}' also failed: {response_text}"
                    )

                log_message(
                    f"[AI3] Raw response preview from fallback '{fallback_provider_name}': {response_text[:200] if response_text else 'None'}"
                )

            except Exception as fallback_e:
                log_message(
                    f"[AI3] Fallback provider '{fallback_provider_name}' also failed: {fallback_e}"
                )
                await initiate_collaboration(
                    str(fallback_e),
                    "Both primary and fallback providers failed during structure generation",
                )
                return None
        else:
            log_message("[AI3] No fallback provider configured.")
            await initiate_collaboration(
                str(e),
                "Primary provider failed during structure generation, no fallback configured",
            )
            return None

    if not response_text:
        log_message(
            "[AI3] No response received from AI model for structure generation."
        )
        await initiate_collaboration(
            "No response from model",
            "AI model did not return any response for structure generation",
        )
        return None

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    json_structure_str = None
    if match:
        json_structure_str = match.group(1)
        log_message("[AI3] Found JSON structure within backticks.")
    else:
        potential_json = response_text.strip()
        if potential_json.startswith("{") and potential_json.endswith("}"):
            json_structure_str = potential_json
            log_message(
                "[AI3] Attempting to parse the entire response as JSON (no backticks found)."
            )
        else:
            log_message(
                "[AI3] Could not find JSON structure in model response (checked with/without backticks)."
            )
            await initiate_collaboration(
                "JSON structure not found",
                f"Model response did not contain a valid JSON block. Preview: {response_text[:200]}",
            )
            return None

    try:
        parsed_structure = json.loads(json_structure_str)
        if not isinstance(parsed_structure, dict):
            raise json.JSONDecodeError(
                "Parsed JSON is not an object (dictionary).", json_structure_str, 0
            )
        log_message("[AI3] Successfully extracted and parsed JSON structure.")
        return parsed_structure
    except json.JSONDecodeError as e:
        log_message(
            f"[AI3] Extracted text is not valid JSON: {e}. Text preview: {json_structure_str[:200]}"
        )
        await initiate_collaboration(
            str(e),
            f"Failed to parse extracted JSON structure. Preview: {json_structure_str[:200]}",
        )
        return None
    except Exception as e:
        log_message(f"[AI3] Unexpected error parsing JSON structure: {e}")
        await initiate_collaboration(str(e), "Unexpected error parsing JSON structure")
        return None


# Global session for AI3
ai3_api_session: Optional[aiohttp.ClientSession] = None


async def get_ai3_api_session() -> aiohttp.ClientSession:
    """Gets or creates the shared aiohttp session for AI3."""
    global ai3_api_session
    if (ai3_api_session is None) or ai3_api_session.closed:
        ai3_api_session = aiohttp.ClientSession()
        log_message("[AI3] Created new aiohttp ClientSession.")
    return ai3_api_session


async def close_ai3_api_session():
    """Closes the shared aiohttp session if it exists."""
    global ai3_api_session
    if ai3_api_session and not ai3_api_session.closed:
        await ai3_api_session.close()
        ai3_api_session = None
        log_message("[AI3] Closed aiohttp ClientSession.")


async def send_structure_to_api(structure_obj: dict):
    api_url = f"{MCP_API_URL}/structure"
    log_message(f"[AI3 -> API] Sending structure object to {api_url}")
    client_session = await get_ai3_api_session()  # Use shared session
    try:
        async with client_session.post(
            api_url, json={"structure": structure_obj}, timeout=30
        ) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                log_message(
                    f"[AI3 -> API] Structure successfully sent. Response: {response_text}"
                )
                return True
            else:
                log_message(
                    f"[AI3 -> API] Error sending structure. Status: {resp.status}, Response: {response_text}"
                )
                return False
    except Exception as e:
        log_message(f"[AI3 -> API] Error sending structure: {str(e)}")
        return False


async def send_ai3_report(status: str, details: dict = None):
    api_url = f"{MCP_API_URL}/ai3_report"
    payload = {"status": status}
    if details:
        payload["details"] = details
    log_message(f"[AI3 -> API] Sending report to {api_url}: {payload}")
    session = await get_ai3_api_session()  # Use shared session
    try:
        async with session.post(api_url, json=payload, timeout=15) as resp:
            response_text = await resp.text()
            log_message(
                f"[AI3 -> API] Report sent. Status: {resp.status}, Response: {response_text}"
            )
            return resp.status == 200
    except asyncio.TimeoutError:
        log_message(f"[AI3 -> API] Timeout sending report: {status}")
        return False
    except aiohttp.ClientError as e:
        log_message(f"[AI3 -> API] Connection error sending report: {str(e)}")
        return False
    except Exception as e:
        log_message(f"[AI3 -> API] Unexpected error sending report: {str(e)}")
        return False


async def initiate_collaboration(error: str, context: str):
    api_url = f"{MCP_API_URL}/ai_collaboration"
    collaboration_request = {"error": error, "context": context, "ai": "AI3"}
    log_message(
        f"[AI3 -> API] Initiating collaboration via {api_url}: {collaboration_request}"
    )
    session = await get_ai3_api_session()  # Use shared session
    try:
        async with session.post(
            api_url, json=collaboration_request, timeout=20
        ) as resp:
            response_text = await resp.text()
            log_message(
                f"[AI3 -> API] Collaboration request sent. Status: {resp.status}, Response: {response_text}"
            )
            return resp.status == 200
    except asyncio.TimeoutError:
        log_message(f"[AI3 -> API] Timeout initiating collaboration.")
        return False
    except aiohttp.ClientError as e:
        log_message(f"[AI3 -> API] Connection error initiating collaboration: {str(e)}")
        return False
    except Exception as e:
        log_message(f"[AI3 -> API] Unexpected error initiating collaboration: {str(e)}")
        return False


async def create_files_from_structure(structure_obj: dict, repo: Repo):
    base_path = repo.working_dir
    created_files = []
    created_dirs = []

    async def _create_recursive(struct: dict, current_rel_path: str):
        for key, value in struct.items():
            sanitized_key = re.sub(r'[<>:"/\\|?*]', "_", key).strip()
            if not sanitized_key:
                log_message(
                    f"[AI3] Warning: Skipping empty or invalid name derived from '{key}'"
                )
                continue

            new_rel_path = os.path.join(current_rel_path, sanitized_key)
            full_path = os.path.join(base_path, new_rel_path)

            try:
                if isinstance(value, dict):
                    if not os.path.exists(full_path):
                        os.makedirs(full_path)
                        log_message(f"[AI3] Created directory: {new_rel_path}")
                        created_dirs.append(full_path)
                        if not value:
                            gitkeep_path = os.path.join(full_path, ".gitkeep")
                            with open(gitkeep_path, "w") as f:
                                f.write("")
                            log_message(
                                f"[AI3] Created .gitkeep in empty directory: {new_rel_path}"
                            )
                    await _create_recursive(value, new_rel_path)
                elif value is None or isinstance(value, str):
                    parent_dir = os.path.dirname(full_path)
                    if not os.path.exists(parent_dir):
                        os.makedirs(parent_dir)
                        log_message(
                            f"[AI3] Created parent directory: {os.path.relpath(parent_dir, base_path)}"
                        )

                    if not os.path.exists(full_path):
                        initial_content = (
                            value
                            if isinstance(value, str)
                            else "# Initial empty file created by AI3\n"
                        )
                        with open(full_path, "w", encoding="utf-8") as f:
                            f.write(initial_content)
                        log_message(f"[AI3] Created file: {new_rel_path}")
                        created_files.append(full_path)
                    else:
                        log_message(
                            f"[AI3] File already exists, skipping creation: {new_rel_path}"
                        )
                else:
                    log_message(
                        f"[AI3] Warning: Unknown type in structure for key '{key}', skipping: {type(value)}"
                    )

            except OSError as e:
                log_message(f"[AI3] Error creating file/directory {new_rel_path}: {e}")
            except Exception as e:
                log_message(f"[AI3] Unexpected error processing {new_rel_path}: {e}")

    try:
        log_message("[AI3] Starting file creation from structure...")
        await _create_recursive(structure_obj, "")
        files_to_commit = created_files + [
            os.path.join(d, ".gitkeep")
            for d in created_dirs
            if os.path.exists(os.path.join(d, ".gitkeep"))
        ]
        _commit_changes(
            repo, files_to_commit, "Created initial project structure from AI"
        )
        log_message("[AI3] File creation process completed.")
        await send_ai3_report("structure_creation_completed")
        return True
    except Exception as e:
        log_message(f"[AI3] Error in create_files_from_structure: {e}")
        await initiate_collaboration(str(e), "Failed to create files from structure")
        await send_ai3_report("structure_creation_failed", {"error": str(e)})
        return False


async def simple_log_monitor():
    log_message(f"[AI3] Starting simple log monitoring: {LOG_FILE_PATH}")
    position = 0
    if os.path.exists(LOG_FILE_PATH):
        try:
            position = os.path.getsize(LOG_FILE_PATH)
        except OSError:
            position = 0

    error_pattern = re.compile(r".*(ERROR|CRITICAL).*", re.IGNORECASE)

    while True:
        try:
            current_size = os.path.getsize(LOG_FILE_PATH)
            if current_size < position:
                position = 0

            if current_size > position:
                with open(LOG_FILE_PATH, "r", encoding="utf-8") as file:
                    file.seek(position)
                    new_content = file.read()
                    position = file.tell()

                    for line in new_content.splitlines():
                        if error_pattern.search(line):
                            log_message(
                                f"[AI3-Monitor] Detected potential error: {line}"
                            )
                            pass

        except FileNotFoundError:
            log_message(f"[AI3] Log file not found: {LOG_FILE_PATH}. Retrying...")
            position = 0
        except Exception as e:
            log_message(f"[AI3] Error in simple log monitor: {e}")

        await asyncio.sleep(config.get("ai3_log_monitor_interval", 10))


async def monitor_idle_workers():
    """
    Функция "дозора", которая отслеживает простаивающих работников и
    запрашивает новые задачи для них у API, если они долго не заняты.
    """
    idle_threshold = config.get(
        "idle_threshold_seconds", 60
    )  # Период бездействия, после которого считаем работника простаивающим
    monitoring_interval = config.get(
        "worker_monitoring_interval", 15
    )  # Интервал проверки статуса работников

    log_message("[AI3-Monitor] Начат мониторинг простаивающих работников")

    # Словарь для отслеживания времени последней активности каждого работника
    last_activity = {"executor": None, "tester": None, "documenter": None}
    idle_workers = set()

    # Количество последовательных сообщений о бездействии для каждого работника
    idle_messages_count = {"executor": 0, "tester": 0, "documenter": 0}
    # Максимальное количество сообщений перед запросом на создание новой задачи
    max_idle_messages = 3

    while True:
        try:
            session = await get_ai3_api_session()
            current_time = time.time()

            # Проверяем логи каждого работника
            for role in ["executor", "tester", "documenter"]:
                log_path = f"logs/ai2_{role}.log"
                try:
                    # Проверяем время последнего изменения лог-файла
                    if os.path.exists(log_path):
                        last_modified = os.path.getmtime(log_path)
                        elapsed_time = current_time - last_modified

                        # Проверяем содержимое последних строк логов на наличие сообщений об отсутствии задач
                        has_empty_queue = False
                        with open(log_path, "r", encoding="utf-8") as f:
                            last_lines = deque(f, 10)  # Читаем последние 10 строк
                            for line in last_lines:
                                if "Очередь для роли" in line and "пуста" in line:
                                    has_empty_queue = True
                                    break

                        # Если очередь пуста и прошло достаточно времени
                        if has_empty_queue and elapsed_time > idle_threshold:
                            if role not in idle_workers:
                                idle_workers.add(role)
                                log_message(
                                    f"[AI3-Monitor] Обнаружен простаивающий работник: {role}, бездействует {elapsed_time:.1f} секунд"
                                )

                            idle_messages_count[role] += 1

                            # Если достигнут порог сообщений, запрашиваем новую задачу
                            if idle_messages_count[role] >= max_idle_messages:
                                await request_new_task_for_worker(role)
                                idle_messages_count[role] = 0  # Сбрасываем счетчик
                        else:
                            if role in idle_workers:
                                idle_workers.remove(role)
                                idle_messages_count[role] = 0
                                log_message(
                                    f"[AI3-Monitor] Работник {role} больше не простаивает"
                                )
                except Exception as e:
                    log_message(
                        f"[AI3-Monitor] Ошибка при проверке логов работника {role}: {e}"
                    )

            # Отправляем общий отчет, если есть простаивающие работники
            if idle_workers:
                log_message(
                    f"[AI3-Monitor] Текущие простаивающие работники: {', '.join(idle_workers)}"
                )

            await asyncio.sleep(monitoring_interval)
        except asyncio.CancelledError:
            log_message("[AI3-Monitor] Мониторинг работников остановлен")
            break
        except Exception as e:
            log_message(f"[AI3-Monitor] Ошибка в цикле мониторинга: {e}")
            await asyncio.sleep(monitoring_interval)  # Продолжаем после ошибки


async def request_new_task_for_worker(role):
    """
    Запрашивает новую задачу для простаивающего работника через API.
    """
    log_message(
        f"[AI3-Monitor] Запрос новой задачи для простаивающего работника: {role}"
    )

    try:
        session = await get_ai3_api_session()
        api_url = f"{MCP_API_URL}/request_task_for_idle_worker"

        async with session.post(
            api_url, json={"role": role, "reason": "worker_idle"}, timeout=30
        ) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                log_message(
                    f"[AI3-Monitor] Успешно запрошена новая задача для {role}. Ответ: {response_text}"
                )
                return True
            else:
                log_message(
                    f"[AI3-Monitor] Ошибка запроса новой задачи для {role}. Статус: {resp.status}, Ответ: {response_text}"
                )
                return False
    except Exception as e:
        log_message(f"[AI3-Monitor] Не удалось запросить новую задачу для {role}: {e}")
        return False


async def scan_for_errors_in_logs():
    """
    Сканирует логи на наличие ошибок и запрашивает задачи на исправление.
    """
    scan_interval = config.get("error_scan_interval", 30)  # Интервал сканирования логов
    log_message("[AI3-Monitor] Начато сканирование логов на наличие ошибок")

    # Регулярное выражение для поиска ошибок в логах
    error_pattern = re.compile(
        r".*(ERROR|CRITICAL|Exception|failed test|test failed).*", re.IGNORECASE
    )

    # Словарь для хранения последних позиций чтения файлов
    file_positions = {}

    # Словарь для хранения уже отправленных ошибок, чтобы не дублировать
    reported_errors = {}

    while True:
        try:
            # Проверяем все лог-файлы в директории logs
            log_dir = "logs"
            if os.path.exists(log_dir):
                for filename in os.listdir(log_dir):
                    if filename.endswith(".log"):
                        log_path = os.path.join(log_dir, filename)

                        # Инициализируем позицию чтения, если файл новый
                        if log_path not in file_positions:
                            file_positions[log_path] = 0

                        try:
                            current_size = os.path.getsize(log_path)

                            # Если файл уменьшился, начинаем чтение с начала
                            if current_size < file_positions[log_path]:
                                file_positions[log_path] = 0

                            if current_size > file_positions[log_path]:
                                with open(log_path, "r", encoding="utf-8") as file:
                                    file.seek(file_positions[log_path])
                                    new_content = file.read()
                                    file_positions[log_path] = file.tell()

                                    for line in new_content.splitlines():
                                        if error_pattern.search(line):
                                            # Создаем хеш для этой ошибки, чтобы не дублировать отчеты
                                            error_hash = hash(line)

                                            # Проверяем, не сообщали ли мы уже об этой ошибке
                                            if (
                                                error_hash not in reported_errors
                                                or (
                                                    time.time()
                                                    - reported_errors[error_hash]
                                                )
                                                > 3600
                                            ):  # 1 час между повторными отчетами
                                                log_message(
                                                    f"[AI3-Monitor] Обнаружена ошибка в {filename}: {line}"
                                                )
                                                reported_errors[error_hash] = (
                                                    time.time()
                                                )

                                                # Определяем роль из имени файла
                                                role = None
                                                if "ai2_executor" in filename:
                                                    role = "executor"
                                                elif "ai2_tester" in filename:
                                                    role = "tester"
                                                elif "ai2_documenter" in filename:
                                                    role = "documenter"

                                                # Запрашиваем исправление ошибки
                                                await request_error_fix(
                                                    line, filename, role
                                                )
                        except Exception as e:
                            log_message(
                                f"[AI3-Monitor] Ошибка при чтении лог-файла {log_path}: {e}"
                            )

            await asyncio.sleep(scan_interval)
        except asyncio.CancelledError:
            log_message("[AI3-Monitor] Сканирование ошибок остановлено")
            break
        except Exception as e:
            log_message(f"[AI3-Monitor] Ошибка в цикле сканирования: {e}")
            await asyncio.sleep(scan_interval)


async def request_error_fix(error_line, log_file, role=None):
    """
    Запрашивает задачу на исправление обнаруженной ошибки.
    """
    log_message(
        f"[AI3-Monitor] Запрос исправления ошибки из {log_file}{' для роли '+role if role else ''}"
    )

    try:
        session = await get_ai3_api_session()
        api_url = f"{MCP_API_URL}/request_error_fix"

        payload = {"error_text": error_line, "log_file": log_file, "role": role}

        async with session.post(api_url, json=payload, timeout=30) as resp:
            response_text = await resp.text()
            if resp.status == 200:
                log_message(
                    f"[AI3-Monitor] Успешно запрошено исправление ошибки. Ответ: {response_text}"
                )
                return True
            else:
                log_message(
                    f"[AI3-Monitor] Ошибка запроса исправления. Статус: {resp.status}, Ответ: {response_text}"
                )
                return False
    except Exception as e:
        log_message(f"[AI3-Monitor] Не удалось запросить исправление ошибки: {e}")
        return False


async def monitor_github_actions():
    """
    Функция мониторинга результатов GitHub Actions.
    Отслеживает результаты запуска тестов и предоставляет рекомендации AI1.
    """
    log_message("[AI3-GitHub] Начат мониторинг результатов GitHub Actions")
    check_interval = config.get(
        "github_check_interval", 30
    )  # Интервал проверки в секундах

    github_api_token = config.get("github_token", os.environ.get("GITHUB_TOKEN"))
    repo_owner = config.get("github_repo_owner", "owner")
    repo_name = config.get("github_repo_name", "AI-SYSTEMS")

    # URL для API GitHub Actions
    github_api_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs"
    )

    # Хранение состояния последних проверенных runs
    last_checked_runs = set()

    while True:
        try:
            if not github_api_token:
                log_message(
                    "[AI3-GitHub] Ошибка: отсутствует токен GitHub API. Мониторинг приостановлен."
                )
                await asyncio.sleep(check_interval * 2)
                continue

            headers = {
                "Authorization": f"token {github_api_token}",
                "Accept": "application/vnd.github.v3+json",
            }

            # Получаем последние workflow runs
            session = await get_ai3_api_session()
            async with session.get(github_api_url, headers=headers) as response:
                if response.status != 200:
                    log_message(
                        f"[AI3-GitHub] Ошибка при получении данных GitHub Actions: {response.status}"
                    )
                    await asyncio.sleep(check_interval)
                    continue

                data = await response.json()
                workflow_runs = data.get("workflow_runs", [])

                # Проверяем новые runs
                for run in workflow_runs:
                    run_id = run.get("id")

                    # Пропускаем уже проверенные runs
                    if run_id in last_checked_runs:
                        continue

                    run_status = run.get("status")
                    run_conclusion = run.get("conclusion")

                    # Обрабатываем только завершенные runs
                    if run_status == "completed":
                        last_checked_runs.add(run_id)

                        # Определяем, какие файлы были протестированы
                        commit_sha = run.get("head_sha")
                        test_files = await get_tested_files(
                            session, repo_owner, repo_name, commit_sha, headers
                        )

                        # Создаем отчет для AI1
                        recommendation = await create_test_recommendation(
                            run_id, run_conclusion, test_files, run.get("html_url")
                        )

                        # Отправляем рекомендацию в API
                        await send_test_recommendation(recommendation)

                # Ограничиваем размер множества проверенных runs
                if len(last_checked_runs) > 100:
                    last_checked_runs = set(list(last_checked_runs)[-50:])

            await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            log_message("[AI3-GitHub] Мониторинг GitHub Actions остановлен")
            break
        except Exception as e:
            log_message(f"[AI3-GitHub] Ошибка в цикле мониторинга GitHub Actions: {e}")
            await asyncio.sleep(check_interval)


async def get_tested_files(session, repo_owner, repo_name, commit_sha, headers):
    """
    Определяет, какие файлы были протестированы в конкретном коммите.
    """
    try:
        # Получаем изменения в коммите
        commit_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/{commit_sha}"
        async with session.get(commit_url, headers=headers) as response:
            if response.status != 200:
                return []

            data = await response.json()
            files = data.get("files", [])

            # Фильтруем тестовые файлы
            test_files = []
            for file in files:
                filename = file.get("filename", "")
                if filename.startswith("test_") or filename.endswith("_test.py"):
                    # Проверяем связанные исходные файлы
                    source_file = await find_source_file_for_test(filename)
                    if source_file:
                        test_files.append(
                            {"test_file": filename, "source_file": source_file}
                        )

            return test_files
    except Exception as e:
        log_message(f"[AI3-GitHub] Ошибка при получении протестированных файлов: {e}")
        return []


async def find_source_file_for_test(test_filename):
    """
    Находит исходный файл, который тестируется данным тестом.
    """
    try:
        # Удаляем префикс test_ или суффикс _test.py
        if test_filename.startswith("test_"):
            source_name = test_filename[5:]  # Удаляем "test_"
        elif test_filename.endswith("_test.py"):
            source_name = test_filename[:-8] + ".py"  # Заменяем "_test.py" на ".py"
        else:
            return None

        # Проверяем, существует ли такой файл
        repo_path = os.path.join(REPO_DIR)
        potential_paths = [
            os.path.join(repo_path, source_name),
            os.path.join(repo_path, "src", source_name),
            os.path.join(repo_path, "backend", source_name),
        ]

        for path in potential_paths:
            if os.path.exists(path):
                return os.path.relpath(path, repo_path)

        return None
    except Exception as e:
        log_message(f"[AI3-GitHub] Ошибка при поиске исходного файла: {e}")
        return None


async def create_test_recommendation(run_id, conclusion, test_files, html_url):
    """
    Создает рекомендацию на основе результатов тестов.
    """
    recommendation = {
        "run_id": run_id,
        "result": conclusion,
        "files": test_files,
        "url": html_url,
        "timestamp": datetime.now().isoformat(),
        "recommendation": "accept" if conclusion == "success" else "rework",
    }

    # Добавляем детальные комментарии
    if conclusion == "success":
        recommendation["comments"] = [
            "Все тесты успешно пройдены",
            "Код соответствует требованиям",
        ]
    else:
        recommendation["comments"] = [
            "Тесты завершились с ошибками",
            "Рекомендуется исправить ошибки и отправить код на доработку",
        ]

    return recommendation


async def send_test_recommendation(recommendation):
    """
    Отправляет рекомендацию в API для обработки AI1.
    """
    api_url = f"{MCP_API_URL}/test_recommendation"
    session = await get_ai3_api_session()
    try:
        async with session.post(api_url, json=recommendation, timeout=30) as response:
            if response.status == 200:
                log_message(
                    f"[AI3-GitHub] Рекомендация успешно отправлена. Run ID: {recommendation['run_id']}"
                )
                return True
            else:
                log_message(
                    f"[AI3-GitHub] Ошибка отправки рекомендации. Статус: {response.status}"
                )
                return False
    except Exception as e:
        log_message(f"[AI3-GitHub] Ошибка отправки рекомендации: {e}")
        return False


def install_missing_modules(module_name):
    try:
        importlib.import_module(module_name)
    except ImportError:
        print(f"{module_name} not found. Installing...")
        subprocess.check_call(["pip", "install", module_name])


class AI3:
    async def update_file_and_commit(self, file_path_relative: str, content: str):
        """Оновлює файл у репозиторії та комітить зміни."""
        repo_dir = "repo"
        full_path = os.path.join(repo_dir, file_path_relative)

        try:
            # Переконатися, що директорія існує
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Записати вміст файлу
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Оновлено файл: {full_path}")

            # Додати файл до індексу Git
            add_result = subprocess.run(
                ["git", "add", full_path],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if add_result.returncode != 0:
                logger.error(f"Помилка 'git add' для {full_path}: {add_result.stderr}")
                return  # Не продовжувати, якщо add не вдався

            logger.info(f"Додано до індексу Git: {full_path}")

            # Закомітити зміни
            commit_message = f"AI3: Оновлено {file_path_relative}"
            # Використовує глобально налаштованого користувача Git (з new_repo.sh)
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=repo_dir,
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_result.returncode != 0:
                # Можливо, коміт не вдався, бо не було змін (це нормально)
                if (
                    "nothing to commit, working tree clean" not in commit_result.stdout
                    and "no changes added to commit" not in commit_result.stderr
                ):
                    logger.error(
                        f"Помилка 'git commit' для {file_path_relative}: {commit_result.stderr}"
                    )
                else:
                    logger.info(f"Немає змін для коміту в файлі: {file_path_relative}")

            else:
                logger.info(f"Зроблено коміт для файлу: {file_path_relative}")

        except FileNotFoundError:
            logger.error(
                f"Помилка: команда 'git' не знайдена. Переконайтеся, що Git встановлено та доступний у PATH."
            )
        except Exception as e:
            logger.error(
                f"Не вдалося оновити або закомітити файл {file_path_relative}: {e}"
            )

    async def handle_ai2_output(self, data):
        # ... логіка для вилучення file_path та content ...
        file_path = data.get("filename")  # Або інше поле, що містить шлях
        content = data.get("code")  # Або інше поле, що містить вміст

        if file_path and content is not None:
            # Переконайтеся, що file_path є відносним шляхом всередині 'repo/'
            if file_path.startswith(os.path.abspath("repo")):
                file_path = os.path.relpath(file_path, "repo")

            await self.update_file_and_commit(file_path, content)
        else:
            logger.warning(
                f"Не вдалося вилучити шлях до файлу або вміст зі звіту AI2: {data}"
            )


async def main():
    install_missing_modules("together")
    install_missing_modules("mistralai")
    # Добавим импорт коллекций для deque
    from collections import deque

    target = config.get("target")
    if not target:
        log_message("[AI3] CRITICAL: 'target' not found in config.json. Exiting.")
        return

    log_message(f"[AI3] Started with target: {target}")

    log_message(f"[AI3] Checking connection to MCP API at {MCP_API_URL}")
    if not await wait_for_service(MCP_API_URL, timeout=120):
        log_message(f"[AI3] CRITICAL: MCP API at {MCP_API_URL} not available. Exiting.")
        return

    try:
        repo = _init_or_open_repo(REPO_DIR)
    except Exception as e:
        log_message(
            f"[AI3] CRITICAL: Failed to initialize repository. Exiting. Error: {e}"
        )
        await close_ai3_api_session()  # Ensure session is closed on early exit
        return

    structure_obj = None
    try:
        api_url = f"{MCP_API_URL}/structure"
        session = await get_ai3_api_session()  # Get shared session
        async with session.get(api_url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if (
                    data
                    and isinstance(data.get("structure"), dict)
                    and data["structure"]
                ):
                    structure_obj = data["structure"]
                    log_message("[AI3] Found existing structure from API.")
    except Exception as e:
        log_message(f"[AI3] Could not check for existing structure: {e}")

    if not structure_obj:
        log_message("[AI3] Attempting to generate project structure...")
        structure_obj = await generate_structure(target)

        if structure_obj:
            log_message(
                "[AI3] Structure generated. Sending to API and creating files..."
            )
            if await send_structure_to_api(structure_obj):
                if not await create_files_from_structure(structure_obj, repo):
                    log_message(
                        "[AI3] Failed to create files from structure. Continuing monitor."
                    )
                    await send_ai3_report("structure_creation_failed")
            else:
                log_message(
                    "[AI3] Failed to send structure to API. Cannot create files."
                )
                await send_ai3_report("structure_api_send_failed")
        else:
            log_message("[AI3] Failed to generate structure. Cannot create files.")
            await send_ai3_report("structure_generation_failed")

    # Запускаем все мониторинговые задачи параллельно
    log_message("[AI3] Starting all monitoring tasks...")
    monitoring_tasks = [
        asyncio.create_task(simple_log_monitor()),
        asyncio.create_task(monitor_idle_workers()),
        asyncio.create_task(scan_for_errors_in_logs()),
        asyncio.create_task(
            monitor_github_actions()
        ),  # Добавляем мониторинг GitHub Actions
    ]

    log_message("[AI3] All monitoring tasks started successfully")

    # Ждем завершения любой из задач или исключения
    try:
        await asyncio.gather(*monitoring_tasks)
    except asyncio.CancelledError:
        log_message("[AI3] Main task cancelled, stopping all monitoring tasks...")
        for task in monitoring_tasks:
            if not task.done():
                task.cancel()
        # Ждем завершения отмененных задач
        await asyncio.gather(*monitoring_tasks, return_exceptions=True)
        log_message("[AI3] All monitoring tasks stopped.")
    except Exception as e:
        log_message(f"[AI3] Error in monitoring tasks: {e}")
    finally:
        await close_ai3_api_session()  # Ensure session is closed when monitoring stops or main exits

    log_message("[AI3] Exiting.")


if __name__ == "__main__":
    log_dir = os.path.dirname(LOG_FILE_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_message("[AI3] Received KeyboardInterrupt, shutting down.")
    finally:
        # Ensure session is closed even if asyncio.run exits unexpectedly
        # This might require a more robust shutdown handler in a real application
        # but for now, try closing it here.
        asyncio.run(close_ai3_api_session())


@app.post("/consultation")
async def provide_consultation(request: Request) -> JSONResponse:
    """
    Эндпоинт для AI3 (дозора), который обрабатывает запросы на консультацию от AI1.
    AI3 анализирует задачи или микрозадачи и предлагает рекомендации.
    """
    try:
        data = await request.json()
        consultation_type = data.get("consultation_type", "")
        target = data.get("target", "")
        consultation_data = data.get("data", {})

        if not consultation_type or not consultation_data:
            log_message(
                "[AI3-Консультация] Получен некорректный запрос на консультацию"
            )
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Invalid consultation request"},
            )

        log_message(
            f"[AI3-Консультация] Получен запрос на консультацию типа: {consultation_type}"
        )

        # Используем LLM для анализа задач и генерации рекомендаций
        if consultation_type == "task_structure":
            recommendations = await analyze_task_structure(consultation_data, target)
        elif consultation_type == "subtasks":
            recommendations = await analyze_subtasks(consultation_data, target)
        else:
            log_message(
                f"[AI3-Консультация] Неизвестный тип консультации: {consultation_type}"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Unknown consultation type: {consultation_type}",
                },
            )

        log_message(
            f"[AI3-Консультация] Генерация рекомендаций завершена: {len(recommendations.get('recommendations', []))} пунктов"
        )
        return JSONResponse(content=recommendations)

    except Exception as e:
        log_message(
            f"[AI3-Консультация] Ошибка при обработке запроса на консультацию: {e}"
        )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal error: {str(e)}"},
        )


async def analyze_task_structure(task_structure: Dict, target: str) -> Dict:
    """
    Анализирует структуру задач и генерирует рекомендации по улучшению.

    Args:
        task_structure: Структура задач
        target: Цель проекта

    Returns:
        Dict с рекомендациями и улучшенной структурой
    """
    log_message("[AI3-Консультация] Анализ структуры задач...")

    # Базовая структура ответа
    result = {"recommendations": [], "improved_structure": task_structure.copy()}

    try:
        # Готовим промпт для LLM
        prompt = f"""
        Анализ структуры задач и предложения по улучшению.
        
        Цель проекта: {target}
        
        Текущая структура задач:
        {json.dumps(task_structure, indent=2, ensure_ascii=False)}
        
        Проанализируй структуру задач и предложи улучшения. Рассмотри:
        1. Оптимальна ли группировка задач?
        2. Правильно ли расставлены приоритеты?
        3. Есть ли логические зависимости между задачами, которые не учтены?
        4. Нет ли пропущенных компонентов или задач?
        
        Ответь в формате JSON, который содержит:
        1. "recommendations" - список строк с рекомендациями
        2. "improved_structure" - улучшенная структура задач (опционально)
        """

        # Получаем ответ от LLM
        ai_config = config.get("ai_config", {}).get("ai3", {})
        provider_name = ai_config.get("provider", "openai")
        provider = ProviderFactory.create_provider(provider_name)

        await apply_request_delay("ai3")  # Добавляем задержку перед запросом
        response = await provider.generate(
            prompt=prompt,
            model=ai_config.get("model"),
            max_tokens=ai_config.get("max_tokens", 2000),
            temperature=ai_config.get("temperature", 0.7),
        )

        # Извлекаем JSON из ответа
        try:
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL
            )
            if json_match:
                json_str = json_match.group(1)
            else:
                # Если нет явного JSON блока, пробуем весь текст
                json_str = response.strip()

            llm_result = json.loads(json_str)

            # Проверяем структуру ответа
            if "recommendations" in llm_result:
                result["recommendations"] = llm_result["recommendations"]

            if "improved_structure" in llm_result:
                # Проверяем, что структура валидная
                if (
                    isinstance(llm_result["improved_structure"], dict)
                    and "main_tasks" in llm_result["improved_structure"]
                ):
                    result["improved_structure"] = llm_result["improved_structure"]

            log_message(
                f"[AI3-Консультация] Анализ завершен, получено {len(result['recommendations'])} рекомендаций"
            )

        except json.JSONDecodeError:
            log_message("[AI3-Консультация] Не удалось извлечь JSON из ответа LLM")
            # Извлекаем рекомендации из текста
            recommendations = extract_recommendations_from_text(response)
            result["recommendations"] = recommendations

    except Exception as e:
        log_message(f"[AI3-Консультация] Ошибка при анализе структуры задач: {e}")
        result["recommendations"] = [
            "Рекомендуется начать с ключевых компонентов системы",
            "Уделите особое внимание базовой инфраструктуре",
            "Разделите задачи на фронтенд и бэкенд",
        ]

    return result


async def analyze_subtasks(subtasks_data: Dict, target: str) -> Dict:
    """
    Анализирует микрозадачи и генерирует рекомендации по улучшению.

    Args:
        subtasks_data: Данные о микрозадачах
        target: Цель проекта

    Returns:
        Dict с рекомендациями и улучшенными микрозадачами
    """
    log_message("[AI3-Консультация] Анализ микрозадач...")

    main_task_id = subtasks_data.get("main_task_id", "")
    subtasks = subtasks_data.get("subtasks", [])

    # Базовая структура ответа
    result = {"recommendations": [], "improved_subtasks": subtasks.copy()}

    try:
        # Готовим промпт для LLM
        prompt = f"""
        Анализ микрозадач и предложения по улучшению.
        
        Цель проекта: {target}
        
        Текущие микрозадачи для задачи ID {main_task_id}:
        {json.dumps(subtasks, indent=2, ensure_ascii=False)}
        
        Проанализируй микрозадачи и предложи улучшения. Рассмотри:
        1. Достаточно ли детализированы микрозадачи?
        2. Правильно ли определены шаги для каждой микрозадачи?
        3. Нужны ли дополнительные шаги для какой-либо микрозадачи?
        4. Есть ли зависимости между микрозадачами, которые стоит учесть?
        
        Ответь в формате JSON, который содержит:
        1. "recommendations" - список строк с рекомендациями
        2. "improved_subtasks" - улучшенный список микрозадач (опционально)
        """

        # Получаем ответ от LLM
        ai_config = config.get("ai_config", {}).get("ai3", {})
        provider_name = ai_config.get("provider", "openai")
        provider = ProviderFactory.create_provider(provider_name)

        await apply_request_delay("ai3")  # Добавляем задержку перед запросом
        response = await provider.generate(
            prompt=prompt,
            model=ai_config.get("model"),
            max_tokens=ai_config.get("max_tokens", 2000),
            temperature=ai_config.get("temperature", 0.7),
        )

        # Извлекаем JSON из ответа
        try:
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL
            )
            if json_match:
                json_str = json_match.group(1)
            else:
                # Если нет явного JSON блока, пробуем весь текст
                json_str = response.strip()

            llm_result = json.loads(json_str)

            # Проверяем структуру ответа
            if "recommendations" in llm_result:
                result["recommendations"] = llm_result["recommendations"]

            if "improved_subtasks" in llm_result:
                # Проверяем, что список задач валидный
                if isinstance(llm_result["improved_subtasks"], list):
                    result["improved_subtasks"] = llm_result["improved_subtasks"]

            log_message(
                f"[AI3-Консультация] Анализ микрозадач завершен, получено {len(result['recommendations'])} рекомендаций"
            )

        except json.JSONDecodeError:
            log_message("[AI3-Консультация] Не удалось извлечь JSON из ответа LLM")
            # Извлекаем рекомендации из текста
            recommendations = extract_recommendations_from_text(response)
            result["recommendations"] = recommendations

    except Exception as e:
        log_message(f"[AI3-Консультация] Ошибка при анализе микрозадач: {e}")
        result["recommendations"] = [
            "Разбейте каждую микрозадачу на более мелкие шаги",
            "Добавьте тестирование для каждой микрозадачи",
            "Укажите зависимости между микрозадачами",
        ]

    return result


def extract_recommendations_from_text(text: str) -> List[str]:
    """
    Извлекает рекомендации из текстового ответа LLM.

    Args:
        text: Текст ответа LLM

    Returns:
        Список строк с рекомендациями
    """
    recommendations = []

    # Ищем пронумерованные пункты
    numbered_points = re.findall(r"^\s*\d+\.\s*(.*?)$", text, re.MULTILINE)
    if numbered_points:
        recommendations.extend(numbered_points)

    # Ищем маркированные пункты
    bullet_points = re.findall(r"^\s*[\*\-\•]\s*(.*?)$", text, re.MULTILINE)
    if bullet_points:
        recommendations.extend(bullet_points)

    # Если ничего не нашли, разбиваем текст по строкам
    if not recommendations:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        # Фильтруем строки, которые могут быть рекомендациями
        recommendations = [line for line in lines if len(line) > 20 and len(line) < 200]

    # Ограничиваем количество рекомендаций
    if len(recommendations) > 10:
        recommendations = recommendations[:10]

    return recommendations
