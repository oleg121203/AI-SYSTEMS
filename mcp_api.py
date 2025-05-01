import asyncio
import json
import logging
import os
import subprocess
from collections import deque, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Union
from uuid import uuid4

import aiofiles
# --- CHANGE: Import Repo and GitCommandError ---
import git
from git import Repo, GitCommandError
# --- END CHANGE ---
import uvicorn
from dotenv import load_dotenv
from fastapi import (BackgroundTasks, FastAPI, HTTPException, Request,
                     WebSocket, WebSocketDisconnect)
# --- CHANGE: Define constants ---
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
# --- END CHANGE ---
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from json_log_formatter import JSONFormatter # Corrected import
from utils import log_message
import requests # Додано для repository_dispatch
# Assuming TestRecommendation is defined in ai3.py
try:
    from ai3 import TestRecommendation
except ImportError:
    # Fallback or placeholder if ai3.py doesn't define it directly
    # This might need adjustment based on the actual definition location
    class TestRecommendation(BaseModel):
        recommendation: str
        context: dict = {}


load_dotenv()

# --- CHANGE: Define constants ---
CONFIG_FILE = "config.json"
TEXT_PLAIN = "text/plain"
# --- CHANGE: Add constant for default repo placeholder ---
DEFAULT_GITHUB_REPO_PLACEHOLDER = "YOUR_GITHUB_USERNAME/YOUR_REPO_NAME"
# --- END CHANGE ---
# --- END CHANGE ---


# --- Pydantic Models ---
class Report(BaseModel):
    """Модель для отчетов от AI2"""

    type: str = Field(..., description="Тип отчета (code, test_result, status_update)")
    file: Optional[str] = Field(
        None, description="Путь к файлу для обновления (для code)"
    )
    content: Optional[str] = Field(None, description="Содержимое файла (для code)")
    subtask_id: Optional[str] = Field(
        None, description="ID подзадачи, которая выполнялась"
    )
    metrics: Optional[Dict] = Field(
        None, description="Метрики выполнения (для test_result)"
    )
    message: Optional[str] = Field(None, description="Дополнительное сообщение")


# --- Configuration Loading ---
try:
    # --- CHANGE: Use constant ---
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    # --- END CHANGE ---
        config_str = f.read()
    # Replace environment variables
    for key, value in os.environ.items():
        config_str = config_str.replace(f"${{{key}}}", value)
    config = json.loads(config_str)
except FileNotFoundError:
    # --- CHANGE: Use constant ---
    logging.error(f"CRITICAL: {CONFIG_FILE} not found. Exiting.")
    # --- END CHANGE ---
    exit(1)
except json.JSONDecodeError as e:
    # --- CHANGE: Use constant ---
    logging.error(f"CRITICAL: Error decoding {CONFIG_FILE}: {e}. Exiting.")
    # --- END CHANGE ---
    exit(1)
except Exception as e:
    logging.error(f"CRITICAL: Error loading configuration: {e}. Exiting.")
    exit(1)

# --- CHANGE: Define GITHUB_MAIN_REPO and GITHUB_TOKEN ---
# --- CHANGE: Use constant for default value ---
GITHUB_MAIN_REPO = config.get("github_repo", DEFAULT_GITHUB_REPO_PLACEHOLDER)
# --- END CHANGE ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") # Get token from environment variable
# --- END CHANGE ---

# --- Logging Setup ---
log_file_path = config.get("log_file", "logs/mcp.log")
os.makedirs(
    os.path.dirname(log_file_path), exist_ok=True
)  # Ensure log directory exists
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Added logger name
)
logger = logging.getLogger(__name__)  # Use specific logger

# Add a handler to send logs via WebSocket
class WebSocketLogHandler(logging.Handler):
    def emit(self, record):
        # Використовуємо синхронну версію, щоб уникнути RuntimeWarning
        log_entry = self.format(record)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Якщо цикл подій запущений, створюємо завдання
                asyncio.create_task(broadcast_specific_update({"log_line": log_entry}))
            else:
                # Якщо цикл не запущений, просто логуємо без відправки
                pass  # Можна просто мовчки ігнорувати в цьому випадку
        except Exception:
            # Тихо ігноруємо помилки при логуванні
            pass

# Configure the handler (do this after basicConfig)
ws_log_handler = WebSocketLogHandler()
ws_log_handler.setLevel(logging.INFO)  # Set desired level for WebSocket logs
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')  # Simpler format for UI - FIX: levelname instead of levellevel
ws_log_handler.setFormatter(formatter)
logging.getLogger().addHandler(ws_log_handler)  # Add to root logger


# --- FastAPI App Setup ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Repository Setup ---
repo_dir = config.get("repo_dir", "repo")
repo_path = Path(repo_dir).resolve()  # Use absolute path
os.makedirs(repo_path, exist_ok=True)  # Ensure repo directory exists

try:
    # --- CHANGE: Use Repo ---
    repo = Repo(repo_path)
    # --- END CHANGE ---
    logger.info(f"Initialized existing Git repository at {repo_path}")
# --- CHANGE: Use git.exc ---
except git.exc.InvalidGitRepositoryError:
    repo = Repo.init(repo_path)
# --- END CHANGE ---
    logger.info(f"Initialized new Git repository at {repo_path}")
except Exception as e:
    logger.error(f"Error initializing Git repository at {repo_path}: {e}")
    # Decide if this is critical - maybe continue without Git? For now, log error.
    repo = None  # Indicate repo is not available


# --- Global State ---
executor_queue = asyncio.Queue()
tester_queue = asyncio.Queue()
documenter_queue = asyncio.Queue()
subtask_status = {}  # Stores status like "pending", "accepted", "failed"
report_metrics = {}  # Stores metrics for accepted tasks {subtask_id: metrics}
current_structure = {}  # Ensure current_structure is initialized
ai3_report = {"status": "pending"}  # Status from AI3 (e.g., structure completion)
processed_history = deque(
    maxlen=config.get("history_length", 20)
)  # Track processed count over time
collaboration_requests = []  # Store collaboration requests
processed_tasks_count = 0  # Добавим счетчик обработанных задач

# Global dictionary for AI status
# --- CHANGE: Initialize AI status to True by default ---
ai_status: Dict[str, bool] = {"ai1": True, "ai2": True, "ai3": True}
# --- END CHANGE ---
ai_processes: Dict[str, Optional[subprocess.Popen]] = {
    "ai1": None,
    "ai2": None,
    "ai3": None,
}

# Set for storing active WebSocket connections
active_connections: Set[WebSocket] = set()

# Добавим блокировку для предотвращения гонок при записи файлов/коммитах
file_write_lock = asyncio.Lock()

# Глобальний словник для зберігання завдань та їх статусів
tasks = {}


# --- Helper Functions ---
def is_safe_path(basedir, path_str):
    """Check if the path_str is safely within the basedir."""
    try:
        # Resolve both paths to absolute paths
        base_path = Path(basedir).resolve(strict=True)
        target_path = Path(basedir, path_str).resolve(
            strict=False
        )  # Don't require target to exist yet
        # Check if the resolved target path is within the base path
        return target_path.is_relative_to(base_path)
    except Exception as e:
        logger.warning(f"Path safety check failed for '{path_str}' in '{basedir}': {e}")
        return False


def get_file_changes(repo_dir):
    """Gets the list of changed files from git status --porcelain"""
    try:
        # Ensure we are running git commands in the correct directory
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_dir,  # Explicitly set the working directory
        )
        changes = []
        for line in result.stdout.strip().split("\n"):
            if line:
                # Example line: ' M path/to/file.py' or '?? new_file.txt'
                # We only need the path part
                parts = line.strip().split()
                if len(parts) >= 2:
                    changes.append(parts[1])
        return changes
    except subprocess.CalledProcessError as e:
        # Log the error, including stderr for more details
        logging.error(f"Error getting file changes: {e}")
        logging.error(f"Git command stderr: {e.stderr}")  # Log stderr
        # Return empty list or re-raise exception depending on desired behavior
        return []  # Return empty list to avoid crashing the caller loop
    except FileNotFoundError:
        logging.error(
            "Error: 'git' command not found. Make sure Git is installed and in PATH."
        )
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_file_changes: {e}")
        return []


async def broadcast_status():
    """Broadcasts the current AI status to all connected clients."""
    if active_connections:
        message = {"type": "status_update", "ai_status": ai_status}
        print(f"Broadcasting status: {ai_status}")  # Added for debugging
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                print(f"Client {connection.client} disconnected during broadcast.")
                disconnected_clients.add(connection)
            except Exception as e:
                print(f"Error sending status to {connection.client}: {e}")
                disconnected_clients.add(connection)
        for client in disconnected_clients:
            active_connections.discard(client)


async def broadcast_specific_update(update_data: dict):
    """Broadcasts a specific update to all clients."""
    if active_connections:
        message = json.dumps(update_data)
        # Iterate over a copy of the set to allow modification during iteration
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_text(message)
            except (WebSocketDisconnect, RuntimeError) as e: # Catch specific errors related to closed connections
                logger.warning(f"Failed to send specific update to client {connection.client}: {e}. Removing connection.")
                disconnected_clients.add(connection)
            except Exception as e: # Catch other potential send errors
                logger.error(f"Unexpected error sending specific update to client {connection.client}: {e}. Removing connection.")
                disconnected_clients.add(connection)

        # Remove disconnected clients from the main set
        active_connections.difference_update(disconnected_clients)


# Додаємо нову функцію для надсилання оновлень графіків
async def broadcast_chart_updates():
    """Формує та відправляє дані для всіх графіків."""
    if not active_connections:
        return
    
    # Отримуємо дані для графіків
    progress_data = get_progress_chart_data()
    
    # --- CHANGE: Refine status aggregation for Pie Chart --- 
    status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "other": 0}
    for status in subtask_status.values():
        if status == "pending":
            status_counts["pending"] += 1
        elif status == "processing":
            status_counts["processing"] += 1
        # More comprehensive list of completed/successful states
        elif status in ["accepted", "completed", "code_received", "tested", "documented", "skipped"]:
            status_counts["completed"] += 1
        # Group failure/error states
        elif status in ["failed", "error", "needs_rework"] or (isinstance(status, str) and "error" in status.lower()):
            status_counts["failed"] += 1
        else:
            status_counts["other"] += 1 # Catch-all for any other statuses
    # --- END CHANGE ---
    
    # Формуємо дані для графіка git активності
    git_activity_data = {
        "labels": [f"Commit {i+1}" for i in range(len(processed_history))],
        "values": list(processed_history)
    }
    
    # Формуємо повне оновлення для всіх графіків
    update_data = {
        "progress_data": progress_data,
        "git_activity": git_activity_data,
        "task_status_distribution": status_counts
    }
    
    # Надсилаємо оновлення всім підключеним клієнтам
    await broadcast_specific_update(update_data)

# Змінна для збереження завдання періодичного оновлення
chart_update_task = None

async def periodic_chart_updates():
    """Періодично надсилає оновлення для графіків (як fallback)."""
    while True:
        try:
            await broadcast_chart_updates()
            await asyncio.sleep(20)  # Збільшуємо інтервал, бо є тригери на події
        except asyncio.CancelledError:
            # Завдання було скасовано
            break
        except Exception as e:
            logger.error(f"Помилка при періодичному оновленні графіків: {e}")
            await asyncio.sleep(10)  # Продовжуємо спробувати навіть при помилці


async def _determine_adjusted_path(repo_path: Path, file_rel_path: str, repo_dir: str) -> str:
    """Determines the adjusted relative path within the repo, handling the 'project' subdirectory."""
    project_subdir = "project"
    potential_project_root = repo_path / project_subdir
    adjusted_rel_path = file_rel_path

    if potential_project_root.is_dir():
        if not file_rel_path.startswith(project_subdir + "/") and file_rel_path != project_subdir:
            adjusted_rel_path = os.path.join(project_subdir, file_rel_path)
            logger.info(f"[API-Write] Prepending '{project_subdir}/' to path '{file_rel_path}' as '{repo_dir}/{project_subdir}/' exists. New path: '{adjusted_rel_path}'")
    else:
        if file_rel_path.startswith(project_subdir + "/"):
            original_path = file_rel_path
            adjusted_rel_path = file_rel_path[len(project_subdir) + 1:]
            logger.warning(f"[API-Write] '{repo_dir}/{project_subdir}/' does not exist, but path '{original_path}' starts with '{project_subdir}/'. Removing prefix. New path: '{adjusted_rel_path}'")
        elif file_rel_path == project_subdir:
            original_path = file_rel_path
            adjusted_rel_path = "."
            logger.warning(f"[API-Write] '{repo_dir}/{project_subdir}/' does not exist, but path is '{original_path}'. Interpreting as root '{adjusted_rel_path}'.")

    if not adjusted_rel_path and file_rel_path:
        adjusted_rel_path = "."
        logger.warning("[API-Write] Adjusted path became empty, defaulting to '.'")

    return adjusted_rel_path

async def _write_file_content(full_path: Path, content: str, adjusted_rel_path: str, subtask_id: Optional[str]) -> bool:
    """Writes content to the specified file path."""
    try:
        if adjusted_rel_path and adjusted_rel_path != ".":
            full_path.parent.mkdir(parents=True, exist_ok=True)

        if full_path.is_dir():
            logger.warning(f"[API-Write] Adjusted path '{adjusted_rel_path}' points to a directory. Cannot write file content.")
            return False

        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
            await f.write(content)
        logger.info(f"[API-Write] Successfully wrote code to: {adjusted_rel_path} (Subtask: {subtask_id})")
        return True
    except OSError as e:
        logger.error(f"[API-Write] Error writing file {full_path} (adjusted path: {adjusted_rel_path}): {e}")
        return False
    except Exception as e:
        logger.error(f"[API-Write] Unexpected error writing file {full_path} (adjusted path: {adjusted_rel_path}): {e}", exc_info=True)
        return False

async def _commit_changes(repo: Optional[Repo], adjusted_rel_path: str, subtask_id: Optional[str]) -> bool:
    """Commits changes for the specified path using gitpython."""
    global processed_tasks_count, processed_history
    if not repo:
        logger.warning("[API-Git] Git repository not available. Skipping commit.")
        return False # Indicate commit did not happen

    try:
        repo.index.add([adjusted_rel_path])
        commit_message = f"AI2 code update for {adjusted_rel_path}"
        if subtask_id:
            commit_message += f" (Subtask: {subtask_id})"

        if repo.is_dirty(index=True, working_tree=False):
            repo.index.commit(commit_message)
            logger.info(f"[API-Git] Committed changes for: {adjusted_rel_path}")

            # Update history and broadcast
            processed_tasks_count += 1
            processed_history.append(processed_tasks_count)
            await broadcast_chart_updates() # Broadcast full chart update
            return True # Commit successful
        else:
            logger.info(f"[API-Git] No changes staged for commit for: {adjusted_rel_path}")
            # Decide if writing without changes should be considered success for dispatch trigger
            return True # Treat as success for triggering dispatch even if no commit needed
    except GitCommandError as e:
        logger.error(f"[API-Git] Error committing {adjusted_rel_path}: {e}")
        return False # Commit failed
    except Exception as e:
        logger.error(f"[API-Git] Unexpected error during commit for {adjusted_rel_path}: {e}")
        return False # Commit failed

async def _trigger_repository_dispatch(commit_successful: bool, adjusted_rel_path: str, subtask_id: Optional[str]):
    """Triggers a GitHub repository_dispatch event if conditions are met."""
    if not commit_successful:
        logger.debug("[API-GitHub] Skipping repository_dispatch because commit was not successful.")
        return
    if not GITHUB_TOKEN:
        logger.warning("[API-GitHub] GITHUB_TOKEN not set. Skipping repository_dispatch.")
        return
    if GITHUB_MAIN_REPO == DEFAULT_GITHUB_REPO_PLACEHOLDER:
        logger.warning("[API-GitHub] github_repo not configured in config.json. Skipping repository_dispatch.")
        return

    logger.info(f"[API-GitHub] Triggering repository_dispatch for {GITHUB_MAIN_REPO}")
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"event_type": "code-committed-in-repo", "client_payload": {"file": adjusted_rel_path, "subtask_id": subtask_id}}
    dispatch_url = f"https://api.github.com/repos/{GITHUB_MAIN_REPO}/dispatches"
    try:
        response = requests.post(dispatch_url, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        logger.info(f"[API-GitHub] Successfully triggered repository_dispatch event 'code-committed-in-repo' for {adjusted_rel_path}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[API-GitHub] Failed to trigger repository_dispatch: {e}")
    except Exception as e:
        logger.error(f"[API-GitHub] Unexpected error during repository_dispatch: {e}")


async def write_and_commit_code(
    file_rel_path: str, content: str, subtask_id: Optional[str]
) -> bool:
    """Helper function to write file content, commit changes, and trigger dispatch."""
    adjusted_rel_path = await _determine_adjusted_path(repo_path, file_rel_path, repo_dir)

    async with file_write_lock:
        if not is_safe_path(repo_path, adjusted_rel_path):
            logger.error(f"[API-Write] Attempt to write to unsafe adjusted path denied: {adjusted_rel_path} (original: {file_rel_path})")
            return False

        full_path = repo_path / adjusted_rel_path

        write_successful = await _write_file_content(full_path, content, adjusted_rel_path, subtask_id)
        if not write_successful:
            return False # Stop if writing failed

        commit_successful = await _commit_changes(repo, adjusted_rel_path, subtask_id)

        # Trigger dispatch regardless of commit success *if writing succeeded*?
        # Current logic triggers only if commit_successful is True (which includes "no changes staged")
        await _trigger_repository_dispatch(commit_successful, adjusted_rel_path, subtask_id)

        # Return overall success (writing succeeded, commit attempted/succeeded/no-op)
        return write_successful # Or return commit_successful depending on strictness needed


def process_test_results(test_data: Report, subtask_id: str):  # Уточним тип test_data
    """
    Обрабатывает результаты тестирования от AI2.

    Args:
        test_data: Объект отчета типа Report
        subtask_id: ID подзадачи

    Returns:
        dict: Обработанные метрики тестирования
    """
    metrics = (
        test_data.metrics or {}
    )  # Используем доступ через атрибут и проверку на None
    if not metrics:
        logger.warning(f"Получены пустые метрики для задачи {subtask_id}")
        # Возвращаем дефолтные значения, если метрики None или пустой dict
        return {"tests_passed": 0.0, "coverage": 0.0}

    # Проверка на валидные значения
    # ...existing code...


def build_directory_structure(start_path):
    """Build a nested dictionary representing the folder structure at start_path."""
    if not os.path.exists(start_path):
        return {}
    
    structure = {}
    
    try:
        for item in os.listdir(start_path):
            # Skip hidden files and directories
            if item.startswith('.') and item != '.gitignore':
                continue
                
            full_path = os.path.join(start_path, item)
            
            # Check if it's a directory
            if os.path.isdir(full_path):
                # Recursively scan subdirectories
                structure[item] = build_directory_structure(full_path)
            else:
                # For files, use None to indicate it's a file
                structure[item] = None
    except PermissionError:
        logger.warning(f"Permission denied when scanning directory: {start_path}")
    except Exception as e:
        logger.error(f"Error scanning directory {start_path}: {e}")
    
    return structure

# Initialize structure from repo directory on startup
if (repo_path).exists():
    try:
        current_structure = build_directory_structure(repo_path)
        logger.info(f"Initial file structure built from {repo_path}")
    except Exception as e:
        logger.error(f"Failed to build initial file structure: {e}")
        current_structure = {}  # Empty dict as fallback
else:
    logger.warning(f"Repository path {repo_path} does not exist, structure will be empty")
    current_structure = {}


# --- Нова функція для розрахунку статистики ---
def get_progress_stats():
    """Розраховує статистику прогресу проекту на основі глобального словника `subtask_status`.""" # Оновлено docstring
    stats = {
        "tasks_total": 0, # Загальна кількість відомих завдань
        "tasks_completed": 0, # Завдання з УСПІШНИМ кінцевим статусом (для графіка)
        "files_created": 0, # Файли, для яких executor завершив роботу (потрібно уточнити логіку)
        "files_tested_accepted": 0, # Файли, що пройшли тестування (accepted)
        "files_rejected": 0 # Файли, відправлені на доопрацювання (needs_rework)
    }
    # --- CHANGE: Use subtask_status as the source for counts --- 
    # created_files = set()
    # accepted_files = set()
    # rejected_files = set()

    stats["tasks_total"] = len(subtask_status) # Загальна кількість відомих завдань

    # Temporary sets to track files based on subtask_status
    temp_accepted_files = set()
    temp_rejected_files = set()
    # We might need the original `tasks` dict if file info isn't in subtask_status
    # This part needs review based on what `subtask_status` actually contains.
    # For now, focus on counting completed tasks from subtask_status.

    for task_id, status in subtask_status.items():
        # --- CHANGE: Align completed statuses with frontend text statistic --- 
        # Рахуємо завершені завдання (тільки статуси, що використовуються в текстовій статистиці)
        if status in ["accepted", "completed", "code_received"]:
        # --- END CHANGE ---
             stats["tasks_completed"] += 1

        # --- Placeholder logic for file counts based on subtask_status --- 
        # This requires knowing if file info is associated with subtask_status entries
        # or if we need to cross-reference with the `tasks` dictionary.
        # Example (assuming file info IS available or cross-referenced):
        # task_data = tasks.get(task_id) # Get original task data if needed
        # if task_data and task_data.get("file"):
        #     file_path = task_data["file"]
        #     if status == "accepted":
        #         temp_accepted_files.add(file_path)
        #         if file_path in temp_rejected_files:
        #             temp_rejected_files.remove(file_path)
        #     elif status == "needs_rework":
        #         if file_path not in temp_accepted_files:
        #             temp_rejected_files.add(file_path)
        # --- End Placeholder ---

    # --- Update file counts based on placeholder logic (needs refinement) ---
    # stats["files_created"] = len(created_files) # Needs logic based on subtask_status/tasks
    stats["files_tested_accepted"] = len(temp_accepted_files)
    stats["files_rejected"] = len(temp_rejected_files)
    # --- END CHANGE ---

    return stats


def get_progress_chart_data():
    """
    Формує ОДНУ точку даних для графіка прогресу проєкту, що відображає ПОТОЧНИЙ стан.
    """
    # Отримуємо поточну статистику
    stats = get_progress_stats()
    
    # Поточна кількість git дій (останнє значення з історії)
    current_git_actions = processed_history[-1] if processed_history else 0
    
    # Отримуємо значення для графіка
    completed_tasks_count = stats.get("tasks_completed", 0)
    successful_tests_count = stats.get("files_tested_accepted", 0)
    files_created_count = stats.get("files_created", 0)
    total_tasks = stats.get("tasks_total", 0) or 1  # Уникаємо ділення на нуль
    
    # Розраховуємо відсоток прогресу
    weighted_progress = calculate_weighted_progress(
        completed_tasks_count,
        successful_tests_count,
        files_created_count,
        total_tasks
    )
    
    # Формуємо підсумкову точку даних з повною міткою часу
    return {
        "timestamp": datetime.now().strftime("%Y-%м-%d %H:%М:%S"),
        "completed_tasks": completed_tasks_count,
        "successful_tests": successful_tests_count,
        "git_actions": current_git_actions,
        "progress_percentage": weighted_progress
    }

def calculate_weighted_progress(completed_tasks, successful_tests, files_created, total_tasks):
    """
    Розраховує зважений прогрес на основі різних метрик.
    """
    # Встановлюємо вагові коефіцієнти
    task_weight = 0.4
    test_weight = 0.4
    file_weight = 0.2
    
    # Нормалізуємо значення до діапазону 0-100
    task_progress = (completed_tasks / total_tasks) * 100 if total_tasks else 0
    test_progress = (successful_tests / max(1, files_created)) * 100 if files_created > 0 else 0
    file_progress = (files_created / total_tasks) * 100 if total_tasks else 0
    
    # Зважений прогрес
    weighted_progress = (
        task_progress * task_weight +
        test_progress * test_weight +
        file_progress * file_weight
    )
    
    # Обмежуємо значення діапазоном 0-100 і округлюємо до одного знаку
    return min(100, max(0, round(weighted_progress, 1)))


# --- API Endpoints ---


@app.get("/file_content")
async def get_file_content(path: str):
    """Gets the content of a file within the repository."""
    logger.debug(f"Request to get file content for path: {path}")
    if not is_safe_path(repo_path, path):
        logger.warning(f"Access denied for unsafe path: {path}")
        raise HTTPException(status_code=403, detail="Access denied: Unsafe path")

    file_path = repo_path / path
    logger.debug(f"Attempting to read file content for: {file_path}")

    try:
        if not file_path.exists():
            logger.warning(f"File not found at path: {file_path}")
            raise HTTPException(status_code=404, detail="File not found")

        if file_path.is_dir():
            logger.warning(f"Path is a directory, not a file: {file_path}")
            raise HTTPException(status_code=400, detail="Path is a directory")

        file_ext = file_path.suffix.lower()
        # More comprehensive list of common binary extensions
        binary_extensions = [
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.tif', '.tiff',
            '.mp3', '.wav', '.ogg', '.flac', '.aac',
            '.mp4', '.avi', '.mov', '.wmv', '.mkv',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz',
            '.exe', '.dll', '.so', '.dylib', '.app', '.dmg',
            '.db', '.sqlite', '.mdb', '.accdb',
            '.pyc', '.pyo', # Python bytecode
            '.class', # Java bytecode
            '.o', '.a', # Object files, archives
            '.woff', '.woff2', '.ttf', '.otf', '.eot' # Fonts
        ]
        # Common text extensions/names (including empty for files like .gitignore)
        text_extensions_or_names = [
            '', '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.xml',
            '.yaml', '.yml', '.ini', '.cfg', '.conf', '.sh', '.bash', '.zsh',
            '.c', '.h', '.cpp', '.hpp', '.cs', '.java', '.go', '.php', '.rb',
            '.swift', '.kt', '.kts', '.rs', '.lua', '.pl', '.sql', '.log',
            '.gitignore', '.gitattributes', '.editorconfig', '.env',
            '.csv', '.tsv', '.rtf', '.tex', 'makefile', 'dockerfile', # Use lowercase for names
            'readme' # Common base name
        ]

        # Check common names without extension, case-insensitively
        file_name_lower = file_path.name.lower()

        is_likely_binary = file_ext in binary_extensions
        is_likely_text = (file_ext in text_extensions_or_names or
                          file_name_lower in text_extensions_or_names or
                          any(file_name_lower.startswith(name) for name in ['readme', 'dockerfile', 'makefile']))


        if is_likely_binary and not is_likely_text: # Prioritize binary if extension matches and not likely text
             logger.info(f"Binary file detected by extension: {file_path}")
             return PlainTextResponse(
                 content=f"[Binary file: {file_path.name}]\nThis file type cannot be displayed as text.",
                 # --- CHANGE: Use constant ---
                 media_type=TEXT_PLAIN
                 # --- END CHANGE ---
             )

        # Attempt to read as text (UTF-8 first)
        try:
            content = file_path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read file as UTF-8: {file_path}")
            # --- CHANGE: Use constant ---
            return PlainTextResponse(content=content, media_type=TEXT_PLAIN)
            # --- END CHANGE ---
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode {file_path} as UTF-8. Trying fallback encodings.")
            try:
                # Try latin-1 as a common fallback
                content = file_path.read_text(encoding="latin-1")
                logger.info(f"Successfully read file {file_path} with latin-1 fallback.")
                # --- CHANGE: Use constant ---
                return PlainTextResponse(content=content, media_type=TEXT_PLAIN)
                # --- END CHANGE ---
            except Exception: # Catch potential errors reading with latin-1 too
                 logger.warning(f"Failed to decode {file_path} with latin-1. Reading bytes with replacement.")
                 try:
                     # Last resort: read bytes and decode with replacement characters
                     content_bytes = file_path.read_bytes()
                     content = content_bytes.decode("utf-8", errors="replace")
                     logger.info(f"Read file {file_path} as bytes and decoded with replacement characters.")
                     # --- CHANGE: Use constant ---
                     return PlainTextResponse(content=content, media_type=TEXT_PLAIN)
                     # --- END CHANGE ---
                 except Exception as read_err:
                     logger.error(f"Failed even reading bytes for {file_path}: {read_err}")
                     # If even reading bytes fails, report as unreadable
                     return PlainTextResponse(
                         content=f"[Unreadable file: {file_path.name}]\nCould not read file content.",
                         # --- CHANGE: Use constant ---
                         media_type=TEXT_PLAIN
                         # --- END CHANGE ---
                     )

    except HTTPException as http_exc:
        # Re-raise known HTTP exceptions
        raise http_exc
    except Exception as e:
        logger.error(f"Error processing file content request for {path}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error reading file: {e}"
        )


@app.post("/subtask")
async def receive_subtask(data: dict):
    """Receives a subtask from AI1 and adds it to the appropriate queue."""
    subtask = data.get("subtask")
    if not subtask or not isinstance(subtask, dict):
        logger.error(f"Invalid subtask data received: {data}")
        raise HTTPException(status_code=400, detail="Invalid subtask data format")

    subtask_id = subtask.get("id")
    role = subtask.get("role")
    filename = subtask.get("filename")
    text = subtask.get("text")

    if not all([subtask_id, role, filename, text]):
        logger.error(f"Missing required fields in subtask: {subtask}")
        raise HTTPException(
            status_code=400,
            detail="Missing required fields in subtask (id, role, filename, text)",
        )

    # Basic validation
    if role not in ["executor", "tester", "documenter"]:
        logger.error(f"Invalid role received: {role}")
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

    if not is_safe_path(repo_path, filename):
        logger.warning(f"Subtask rejected due to unsafe path: {filename}")
        raise HTTPException(status_code=400, detail="Invalid filename (unsafe path)")

    # Add to the correct queue
    if role == "executor":
        await executor_queue.put(subtask)
    elif role == "tester":
        await tester_queue.put(subtask)
    elif role == "documenter":
        await documenter_queue.put(subtask)
    # No else needed due to validation above

    subtask_status[subtask_id] = "pending"
    logger.info(
        f"Received subtask for {role}: '{text[:50]}...', ID: {subtask_id}, File: {filename}"
    )
    # Broadcast queue update
    await broadcast_specific_update({"queues": {
         "executor": [t for t in executor_queue._queue],
         "tester": [t for t in tester_queue._queue],
         "documenter": [t for t in documenter_queue._queue],
    }})
    return {"status": "subtask received", "id": subtask_id}


@app.get("/task/{role}")
async def get_task_for_role(role: str):
    """Provides a task to an AI2 worker based on its role."""
    queue = None
    if role == "executor":
        queue = executor_queue
    elif role == "tester":
        queue = tester_queue
    elif role == "documenter":
        queue = documenter_queue
    else:
        logger.error(f"Invalid role requested for task: {role}")
        raise HTTPException(status_code=400, detail="Invalid role specified")

    try:
        # Non-blocking get
        subtask = queue.get_nowait()
        logger.info(f"Providing task ID {subtask.get('id')} to {role} worker.")
        subtask_status[subtask.get("id")] = "processing"  # Mark as processing
        # Broadcast status and queue update
        await broadcast_specific_update({
            "subtasks": {subtask.get("id"): "processing"},
            "queues": {
                role: [t for t in queue._queue]  # Отправляем обновленную очередь
            }
        })
        return {"subtask": subtask}
    except asyncio.QueueEmpty:
        logger.debug(f"No tasks available for role: {role}")
        return {"message": f"No tasks available for {role}"}
    except Exception as e:
        logger.error(f"Error getting task for {role}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving task")


@app.post("/structure")
async def receive_structure(data: dict):
    """Receives the project structure (as Python object) from AI3."""
    global current_structure
    structure_obj = data.get("structure")
    if not isinstance(structure_obj, dict):  # Expecting a dictionary
        logger.error(
            f"Invalid structure data received (expected dict): {type(structure_obj)}"
        )
        raise HTTPException(
            status_code=400,
            detail="Invalid structure data format, expected a JSON object.",
        )

    current_structure = structure_obj  # Store the Python object
    logger.info(
        f"Project structure updated by AI3. Root keys: {list(current_structure.keys())}"
    )
    # Broadcast structure update
    await broadcast_specific_update({"structure": current_structure})
    return {"status": "structure received"}


@app.get("/structure")
async def get_structure():
    """Returns the current project structure."""
    # Return the stored Python object
    return {"structure": current_structure} if current_structure else {"structure": {}}


@app.post("/report", status_code=200)
async def receive_report(
    report_data: Union[Report, Dict], background_tasks: BackgroundTasks
):
    """
    Получение отчетов от AI2 с кодом и результатами.
    Handles code writing directly.
    """
    report: Report
    try:
        if isinstance(report_data, dict):
            report = Report(**report_data)
        else:
            report = report_data

        logger.info(
            f"Received report from AI2: Type={report.type}, Subtask={report.subtask_id}, File={report.file}"
        )

        # Обновляем статус подзадачи
        if report.subtask_id:
            if report.type == "code":
                subtask_status[report.subtask_id] = "code_received"
                if report.file and report.content:
                    background_tasks.add_task(
                        write_and_commit_code,
                        report.file,
                        report.content,
                        report.subtask_id,
                    )
            elif report.type == "test_result":
                subtask_status[report.subtask_id] = "tested"
                # Обрабатываем метрики тестирования
                if report.metrics:
                    report_metrics[report.subtask_id] = process_test_results(
                        report, report.subtask_id
                    )
                # --- ADDED: TODO for follow-up tasks ---
                # TODO: Implement create_follow_up_tasks or similar logic here
                # await create_follow_up_tasks(report.subtask_id)
                # --- END TODO ---
            elif report.type == "status_update":
                subtask_status[report.subtask_id] = report.message or "updated"
                if hasattr(report, "status") and report.status:
                    subtask_status[report.subtask_id] = report.status
            # Broadcast status update after processing
            if report.subtask_id:
                await broadcast_specific_update({"subtasks": {report.subtask_id: subtask_status.get(report.subtask_id)}})
                # --- CHANGE: Trigger chart update after status change ---
                background_tasks.add_task(broadcast_chart_updates)
                # --- END CHANGE ---

        return {"status": "report received"}

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Internal server error processing report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Internal server error processing report: {e}"
        )


@app.post("/ai3_report")
async def receive_ai3_report(data: dict):
    """Receives status reports from AI3."""
    global ai3_report
    new_status = data.get("status")
    if new_status:
        ai3_report = data
        logger.info(f"Received AI3 report: Status changed to '{new_status}'")
        # Potentially trigger WebSocket update if AI3 status is important for UI
    else:
        logger.warning(f"Received AI3 report with missing status: {data}")
        raise HTTPException(status_code=400, detail="Missing 'status' in AI3 report")
    return {"status": "received"}


@app.get("/ai3_report")
async def get_ai3_report():
    """Returns the last known report/status from AI3."""
    return ai3_report


@app.post("/ai_collaboration")
async def ai_collaboration(data: dict):
    """Endpoint to handle incoming collaboration requests (e.g., log them)."""
    logger.info(f"AI collaboration request received: {data}")
    collaboration_requests.append(data)  # Store the request
    return {"status": "collaboration request logged"}


@app.get("/ai_collaboration")
async def get_collaboration_requests():
    """Returns the list of stored collaboration requests."""
    return {"collaboration_requests": collaboration_requests}


@app.post("/update_ai_provider")
async def update_ai_provider(data: dict):
    """Updates the AI provider configuration (requires restart to take effect)."""
    ai = data.get("ai")
    role = data.get("role")  # Optional, for AI2
    provider = data.get("provider")

    if not ai or ai not in config["ai_config"]:
        raise HTTPException(
            status_code=400, detail=f"Invalid or missing AI identifier: {ai}"
        )

    if not provider or provider not in config["providers"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or missing provider identifier: {provider}",
        )

    message = ""
    config_changed = False

    # Handle AI2 roles specifically
    if ai == "ai2":
        if not role or role not in ["executor", "tester", "documenter"]:
            raise HTTPException(
                status_code=400,
                detail="Role (executor, tester, documenter) is required for AI2 provider update",
            )

        # Ensure AI2 config structure exists
        if not isinstance(config["ai_config"].get("ai2"), dict):
            config["ai_config"]["ai2"] = {}
        if role not in config["ai_config"]["ai2"]:
            config["ai_config"]["ai2"][role] = {}  # Create role entry if missing

        # Update provider for the specific role
        if config["ai_config"]["ai2"][role].get("provider") != provider:
            config["ai_config"]["ai2"][role]["provider"] = provider
            message = (
                f"Updated provider for {ai}.{role} to {provider}. Restart required."
            )
            config_changed = True
        else:
            message = f"Provider for {ai}.{role} is already {provider}. No change."

    else:  # Handle AI1, AI3, etc.
        if config["ai_config"][ai].get("provider") != provider:
            config["ai_config"][ai]["provider"] = provider
            message = f"Updated provider for {ai} to {provider}. Restart required."
            config_changed = True
        else:
            message = f"Provider for {ai} is already {provider}. No change."

    if config_changed:
        try:
            # --- CHANGE: Use constant ---
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            # --- END CHANGE ---
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info(message)
            return {"status": "success", "message": message}
        except Exception as e:
            logger.error(f"Failed to write updated config.json: {e}")
            # --- CHANGE: Fix status_code usage ---
            raise HTTPException(
                status_code=500, detail="Failed to save updated configuration file."
            )
            # --- END CHANGE ---
    else:
        logger.info(message)
        return {"status": "no_change", "message": message}


@app.get("/providers")
async def get_providers():
    """Returns available providers and current AI configuration."""
    providers_info = {
        "available_providers": list(config.get("providers", {}).keys()),
        "current_config": config.get("ai_config", {}),
        "roles": ["executor", "tester", "documenter"],  # Standard roles for AI2
    }
    return providers_info


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serves the main dashboard HTML page."""
    processed_tasks = len([s for s in subtask_status.values() if s == "accepted"])
    template_data = {
        "request": request,
        "processed_tasks": processed_tasks,
        "executor_queue_size": executor_queue.qsize(),
        "tester_queue_size": tester_queue.qsize(),
        "documenter_queue_size": documenter_queue.qsize(),
        "target": config.get("target", "Target not set in config"),
        "structure": current_structure if current_structure else {},  # Pass the object
        "config": config,  # Pass full config for prompt display etc.
        "providers": config.get("providers", {}),
        "ai_config": config.get("ai_config", {}),
        "roles": ["executor", "tester", "documenter"],
    }
    return templates.TemplateResponse("index.html", template_data)


@app.post("/update_config")
async def update_config(data: dict):
    """Updates specific configuration values (target, prompts) and saves the config file."""
    config_changed = False
    if "target" in data and config.get("target") != data["target"]:
        config["target"] = data["target"]
        logger.info(f"Target updated to: {data['target'][:100]}...")
        config_changed = True
    if "ai1_prompt" in data and config.get("ai1_prompt") != data["ai1_prompt"]:
        config["ai1_prompt"] = data["ai1_prompt"]
        logger.info("AI1 prompt updated.")
        config_changed = True
    # --- CHANGE: Merge nested if ---
    if (
        "ai2_prompts" in data
        and isinstance(data["ai2_prompts"], list)
        and len(data["ai2_prompts"]) == 3
        and config.get("ai2_prompts") != data["ai2_prompts"]
    ):
        config["ai2_prompts"] = data["ai2_prompts"]
        logger.info("AI2 prompts updated.")
        config_changed = True
    # --- END CHANGE ---

    if "ai3_prompt" in data and config.get("ai3_prompt") != data["ai3_prompt"]:
        config["ai3_prompt"] = data["ai3_prompt"]
        logger.info("AI3 prompt updated.")
        config_changed = True

    if config_changed:
        try:
            # --- CHANGE: Use constant ---
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            # --- END CHANGE ---
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info("Configuration file updated successfully.")
            return {"status": "config updated"}
        except Exception as e:
            logger.error(f"Failed to write updated config.json: {e}")
            # --- CHANGE: Fix status_code usage ---
            raise HTTPException(
                status_code=500, detail="Failed to save updated configuration file."
            )
            # --- END CHANGE ---
    else:
        logger.info("No configuration changes detected in update request.")
        return {"status": "no changes detected"}


# Новий ендпоінт для оновлення окремого елемента конфігурації
@app.post("/update_config_item")
async def update_config_item(data: dict):
    """Updates a single configuration item and saves the config file."""
    if not data or len(data) != 1:
        raise HTTPException(status_code=400, detail="Request must contain exactly one key-value pair.")

    key = list(data.keys())[0]
    value = data[key]

    # Перевірка, чи ключ існує (можна додати більш глибоку перевірку)
    # Наприклад, перевірити, чи ключ є в певній секції конфігурації
    # if key not in config: # Проста перевірка наявності ключа верхнього рівня
    #     raise HTTPException(status_code=400, detail=f"Invalid configuration key: {key}")

    # Оновлюємо значення, якщо воно змінилося
    # Використовуємо get для безпечного доступу, якщо ключ може бути вкладеним (потрібна складніша логіка для вкладеності)
    current_value = config.get(key)
    if current_value != value:
        config[key] = value
        logger.info(f"Configuration item '{key}' updated to: {value}")
        try:
            # --- CHANGE: Use constant ---
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            # --- END CHANGE ---
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info(f"Configuration file updated successfully after changing '{key}'.")
            # Повідомлення клієнтам про зміну конфігурації (якщо потрібно)
            # await broadcast_specific_update({"config_update": {key: value}})
            return {"status": f"'{key}' updated successfully"}
        except Exception as e:
            logger.error(f"Failed to write updated config.json after changing '{key}': {e}")
            # Відновлюємо попереднє значення в пам'яті, якщо запис не вдався
            if current_value is not None:
                config[key] = current_value
            else:
                # Якщо ключа раніше не було, видаляємо його
                config.pop(key, None)
            # --- CHANGE: Fix status_code usage ---
            raise HTTPException(
                status_code=500, detail=f"Failed to save updated configuration file for '{key}'."
            )
            # --- END CHANGE ---
    else:
        logger.info(f"Configuration item '{key}' already has the value '{value}'. No change.")
        return {"status": "no change detected"}


@app.post("/start_ai1")
async def start_ai1():
    ai_status["ai1"] = True
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI1 started (placeholder)"}


@app.post("/stop_ai1")
async def stop_ai1():
    ai_status["ai1"] = False
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI1 stopped (placeholder)"}


@app.post("/start_ai2")
async def start_ai2():
    ai_status["ai2"] = True
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI2 started (placeholder)"}


@app.post("/stop_ai2")
async def stop_ai2():
    ai_status["ai2"] = False
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI2 stopped (placeholder)"}


@app.post("/start_ai3")
async def start_ai3():
    ai_status["ai3"] = True
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI3 started (placeholder)"}


@app.post("/stop_ai3")
async def stop_ai3():
    ai_status["ai3"] = False
    await broadcast_full_status()  # Update UI after AI status change
    return {"status": "AI3 stopped (placeholder)"}


@app.post("/start_all")
async def start_all():
    ai_status["ai1"] = True
    ai_status["ai2"] = True
    ai_status["ai3"] = True
    await broadcast_full_status()  # Update UI after AI status change
    return JSONResponse(
        {"status": "All AI systems started (Placeholder)", "ai_status": ai_status}
    )


@app.post("/stop_all")
async def stop_all():
    ai_status["ai1"] = False
    ai_status["ai2"] = False
    ai_status["ai3"] = False
    await broadcast_full_status()  # Update UI after AI status change
    return JSONResponse(
        {"status": "All AI systems stopped (Placeholder)", "ai_status": ai_status}
    )


@app.post("/clear")
async def clear_state():
    """Clears logs, queues, and resets state."""
    global subtask_status, report_metrics, current_structure, ai3_report, processed_history, collaboration_requests
    global executor_queue, tester_queue, documenter_queue

    logger.warning("Clearing application state: logs, queues, status...")

    # Clear queues
    while not executor_queue.empty():
        await executor_queue.get()
    while not tester_queue.empty():
        await tester_queue.get()
    while not documenter_queue.empty():
        await documenter_queue.get()
    logger.info("Cleared task queues.")

    # Reset state variables
    subtask_status = {}
    report_metrics = {}
    ai3_report = {"status": "pending"}
    processed_history.clear()
    collaboration_requests = []
    logger.info("Reset internal state variables.")

    # Clear log file
    try:
        with open(log_file_path, "w") as f:
            f.write("")
        logger.info(f"Cleared log file: {log_file_path}")
    except Exception as e:
        logger.error(f"Failed to clear log file {log_file_path}: {e}")

    return {"status": "state cleared"}


@app.post("/clear_repo")
async def clear_repo():
    """Очищає та ініціалізує Git репозиторій."""
    try:
        # --- CHANGE: Comment out undefined call and add TODO ---
        # TODO: Implement proper interaction with AI3 process instead of direct call
        # await ai3_instance.clear_and_init_repo()
        logger.warning("[API] /clear_repo endpoint called, but AI3 interaction is not implemented yet.")
        # Placeholder response until AI3 interaction is implemented
        await broadcast_specific_update({"message": "Repository clear requested (implementation pending).", "log_line": "[API] Repository clear requested (implementation pending)."})
        return {"status": "Repository clear requested (implementation pending)."}
        # --- END CHANGE ---
    except Exception as e:
        logger.error(f"Error during repository clear request: {e}")
        await broadcast_specific_update({"error": f"Failed to request repository clear: {e}"})
        raise HTTPException(status_code=500, detail=f"Failed to request repository clear: {e}")


async def broadcast_full_status():
    """Broadcasts detailed status to all connected clients."""
    if active_connections:
        # --- Aggregation for Pie Chart ---
        status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "other": 0}
        for status in subtask_status.values():
            # Use a more comprehensive set of completed/final statuses
            if status in ["accepted", "completed", "code_received", "tested", "skipped", "failed_by_ai2", "error_processing", "review_needed", "failed_tests", "failed_to_send"]:
                status_counts["completed"] += 1 # Group all final states for simplicity here, adjust if needed
            elif status == "pending":
                status_counts["pending"] += 1
            elif status in ["sending", "sent", "processing"]: # Explicitly list processing states
                status_counts["processing"] += 1
            # elif "Ошибка" in status or "failed" in status: # This might double-count some final states
            #     status_counts["failed"] += 1 # Consider removing if covered by 'completed' grouping
            else:
                status_counts["other"] += 1 # Catch-all for unknown/transient states
        # --- End Aggregation ---

        # Get progress chart data
        progress_chart_data = get_progress_chart_data()

        # Prepare git activity data
        history_list = list(processed_history)
        git_activity_data = {
            "labels": [f"Commit {i+1}" for i in range(len(history_list))],
            "values": history_list
        }

        state_data = {
            "type": "full_status_update",
            "ai_status": ai_status,
            "queues": {
                "executor": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(executor_queue._queue)
                ],
                "tester": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(tester_queue._queue)
                ],
                "documenter": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(documenter_queue._queue)
                ],
            },
            "subtasks": subtask_status,
            "structure": current_structure,
            "ai3_report": ai3_report,
            # "processed_history": history_list, # Keep original if needed elsewhere, but add formatted one
            "git_activity": git_activity_data, # Add formatted data for the chart
            "progress_data": progress_chart_data, # Add progress chart data
            "collaboration_requests": collaboration_requests,
            "status_counts": status_counts, # Include aggregated counts
            "config": { # Send relevant config parts
                 "ai1_max_concurrent_tasks": config.get("ai1_max_concurrent_tasks"),
                 "ai1_desired_active_buffer": config.get("ai1_desired_active_buffer"),
                 # Add other config values if needed by the UI
            }
        }
        message = json.dumps(state_data)
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_text(message)
            except (WebSocketDisconnect, RuntimeError) as e: # Catch specific errors related to closed connections
                logger.warning(f"Failed to send full status to client {connection.client}: {e}. Removing connection.")
                disconnected_clients.add(connection)
            except Exception as e: # Catch other potential send errors
                logger.error(f"Unexpected error sending full status to client {connection.client}: {e}. Removing connection.")
                disconnected_clients.add(connection)

        # Remove disconnected clients from the main set
        active_connections.difference_update(disconnected_clients)


# Додаємо нову функцію для відправлення повного статусу конкретному клієнту
async def send_full_status_update(websocket: WebSocket):
    """Відправляє повний статус конкретному клієнту WebSocket."""
    try:
        # --- Aggregation for Pie Chart ---
        status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "other": 0}
        for status in subtask_status.values():
            # Use a more comprehensive set of completed/final statuses
            if status in ["accepted", "completed", "code_received", "tested", "skipped", "failed_by_ai2", "error_processing", "review_needed", "failed_tests", "failed_to_send"]:
                status_counts["completed"] += 1 # Group all final states for simplicity here, adjust if needed
            elif status == "pending":
                status_counts["pending"] += 1
            elif status in ["sending", "sent", "processing"]: # Explicitly list processing states
                status_counts["processing"] += 1
            else:
                status_counts["other"] += 1 # Catch-all for unknown/transient states
        # --- End Aggregation ---

        # Get progress chart data
        progress_chart_data = get_progress_chart_data()

        # Prepare git activity data
        history_list = list(processed_history)
        git_activity_data = {
            "labels": [f"Commit {i+1}" for i in range(len(history_list))],
            "values": history_list
        }

        state_data = {
            "type": "full_status_update",
            "ai_status": ai_status,
            "queues": {
                "executor": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(executor_queue._queue)
                ],
                "tester": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(tester_queue._queue)
                ],
                "documenter": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(documenter_queue._queue)
                ],
            },
            "subtasks": subtask_status,
            "structure": current_structure,
            "ai3_report": ai3_report,
            "git_activity": git_activity_data, # Add formatted data for the chart
            "progress_data": progress_chart_data, # Add progress chart data
            "collaboration_requests": collaboration_requests,
            "task_status_distribution": status_counts, # Include aggregated counts
            "config": { # Send relevant config parts
                 "ai1_max_concurrent_tasks": config.get("ai1_max_concurrent_tasks"),
                 "ai1_desired_active_buffer": config.get("ai1_desired_active_buffer"),
                 # Add other config values if needed by the UI
            }
        }
        
        # Відправляємо дані клієнту
        await websocket.send_json(state_data)
        logger.info(f"Sent full status update to client {websocket.client}")
        
    except WebSocketDisconnect:
        logger.warning(f"Client {websocket.client} disconnected during full status update.")
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception as e:
        logger.error(f"Error sending full status to client {websocket.client}: {e}")
        # Не видаляємо з'єднання при помилці відправки - це може спричинити втрату клієнтів через тимчасові помилки


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = f"Address(host='{websocket.client.host}', port={websocket.client.port})"
    active_connections.add(websocket)
    logger.info(f"WebSocket connection established from {client_id}. Total: {len(active_connections)}")
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                logger.debug(f"Received message from client {client_id}: {message}")
                
                # Обробляємо запити від клієнта
                if message.get("action") == "get_full_status":
                    # Надсилаємо повний статус як відповідь на запит
                    await send_full_status_update(websocket)
                elif message.get("action") == "get_chart_updates":
                    # Новий обробник для запиту оновлення графіків
                    await broadcast_chart_updates()
                    logger.info(f"Sent chart updates to client {client_id}")
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from client {client_id}: {data}")
            except Exception as e:
                logger.error(f"Error processing client {client_id} message: {e}")
        
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for {client_id}")
        active_connections.remove(websocket)
        logger.info(f"WebSocket connection removed for {client_id}. Remaining: {len(active_connections)}")
    except Exception as e:
        logger.error(f"Unexpected error in websocket_endpoint for client {client_id}: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)
            logger.info(f"WebSocket connection removed for {client_id} after error. Remaining: {len(active_connections)}")


@app.get("/health")
async def health_check():
    """Простий ендпоінт для перевірки стану API."""
    return {"status": "ok"}


@app.get("/subtask_status/{subtask_id}")
async def get_subtask_status(subtask_id: str):
    """Returns the current status of a specific subtask."""
    status = subtask_status.get(subtask_id)
    if status:
        return {"subtask_id": subtask_id, "status": status}
    else:
        raise HTTPException(status_code=404, detail="Subtask not found")


@app.get("/all_subtask_statuses")
async def get_all_subtask_statuses():
    """Returns the status of all known subtasks."""
    return subtask_status


@app.get("/worker_status")
async def get_worker_status():
    """Повертає поточний статус всіх воркерів AI2."""
    worker_status = {
        "executor": {
            "status": "idle" if executor_queue.empty() else "busy",
            "queue_empty": executor_queue.empty(),
            "queue_size": executor_queue.qsize()
        },
        "tester": {
            "status": "idle" if tester_queue.empty() else "busy",
            "queue_empty": tester_queue.empty(),
            "queue_size": tester_queue.qsize()
        },
        "documenter": {
            "status": "idle" if documenter_queue.empty() else "busy",
            "queue_empty": documenter_queue.empty(),
            "queue_size": documenter_queue.qsize()
        }
    }
    return worker_status


@app.post("/request_task_for_idle_worker")
async def request_task_for_idle_worker(data: dict):
    """Запитує нову задачу для воркера, що простоює."""
    worker = data.get("worker")
    if not worker or worker not in ["executor", "tester", "documenter"]:
        raise HTTPException(status_code=400, detail="Invalid worker specified")
    
    # Перевіряємо, чи є задачі у відповідній черзі
    queue = None
    if worker == "executor":
        queue = executor_queue
    elif worker == "tester":
        queue = tester_queue
    elif worker == "documenter":
        queue = documenter_queue
    
    if queue.empty():
        return {"success": False, "message": f"No tasks available for {worker}"}
    
    try:
        # Спробуємо отримати задачу (не блокуючий виклик)
        task = queue.get_nowait()
        logger.info(f"Task requested for idle worker {worker}. Task ID: {task.get('id')}")
        return {"success": True, "task": task}
    except asyncio.QueueEmpty:
        return {"success": False, "message": f"Queue for {worker} is empty"}
    except Exception as e:
        logger.error(f"Error requesting task for {worker}: {e}")
        return {"success": False, "message": str(e)}


@app.post("/request_error_fix")
async def request_error_fix(data: dict):
    """Обробляє запит на виправлення помилок, виявлених у логах."""
    errors = data.get("errors")
    if not errors:
        raise HTTPException(status_code=400, detail="No errors provided")
    
    # --- CHANGE: Remove misplaced code block and add logging ---
    logger.info(f"Received error fix request with errors: {errors}")
    # TODO: Implement logic to handle error fixing requests, potentially creating new subtasks.
    return {"status": "Error fix request received (implementation pending)"}
    # --- END CHANGE ---


# --- Оновлення ендпоінту рекомендацій тестування ---
@app.post("/test_recommendation")
async def receive_test_recommendation(recommendation: TestRecommendation):
    """Отримує рекомендацію від AI3 щодо результатів тестування."""
    log_message(f"Received test recommendation: {recommendation.recommendation}, Context: {recommendation.context}")

    failed_files = recommendation.context.get("failed_files", [])
    updated_tasks = []

    # Знаходимо завдання, пов'язані з файлами, що не пройшли тест/лінтинг
    for task_id, task_data in tasks.items():
        # Перевіряємо, чи файл завдання є серед тих, що не пройшли перевірку
        # Або якщо рекомендація 'rework' і немає конкретних файлів (загальна помилка workflow)
        if task_data.get("file") in failed_files or (recommendation.recommendation == "rework" and not failed_files):
             if recommendation.recommendation == "rework":
                 # Перевіряємо, чи статус вже не 'needs_rework', щоб уникнути зациклення
                 if task_data["status"] != "needs_rework":
                     task_data["status"] = "needs_rework"
                     task_data["test_context"] = recommendation.context # Зберігаємо контекст помилки
                     updated_tasks.append(task_id)
             # Не оновлюємо статус на 'accepted' тут, це зробить AI1
             # elif recommendation.recommendation == "accept" і task_data["status"] == "tested":
             #     task_data["status"] = "accepted" # Позначаємо як прийняте
             #     updated_tasks.append(task_id)


    if updated_tasks:
        # --- CHANGE: Use broadcast_specific_update ---
        await broadcast_specific_update({"type": "task_update", "message": f"Test recommendation '{recommendation.recommendation}' applied to tasks: {updated_tasks}"})
        # --- END CHANGE ---

    # Пересилаємо рекомендацію AI1 (якщо потрібно) - припускаємо, що AI1 слухає WebSocket або має інший механізм
    # Можна додати логіку відправки HTTP-запиту до AI1, якщо потрібно

    return {"message": "Recommendation received and processed"}


# --- Main Execution ---
if __name__ == "__main__":
    web_port = config.get("web_port", 7860)
    logger.info(f"Starting Uvicorn server on 0.0.0.0:{web_port}")
    uvicorn.run(app, host="0.0.0.0", port=web_port)


@app.on_event("startup")
async def startup_event():
    """Виконується при запуску сервера."""
    global chart_update_task
    # Запускаємо періодичне оновлення графіків у фоновому режимі
    chart_update_task = asyncio.create_task(periodic_chart_updates())
    logger.info("Started periodic chart updates task")


@app.on_event("shutdown")
async def shutdown_event():
    """Виконується при зупинці сервера."""
    global chart_update_task
    # Зупиняємо періодичне оновлення графіків
    if chart_update_task:
        chart_update_task.cancel()
        try:
            await chart_update_task
        except asyncio.CancelledError:
            pass
        logger.info("Stopped periodic chart updates task")
