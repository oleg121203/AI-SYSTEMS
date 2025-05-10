import asyncio
import heapq  # Add import for heapq
import json
import logging
import os
import subprocess
import time  # Add import for time
import uuid  # Add import for uuid
from collections import deque  # Remove Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union  # Add Any here
from uuid import uuid4

import aiofiles

# --- CHANGE: Import Repo and GitCommandError ---
import git
import requests  # Додано для repository_dispatch

# --- END CHANGE ---
import uvicorn
from dotenv import load_dotenv
from fastapi import Query  # Add Query import
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

# --- CHANGE: Define constants ---
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

# --- END CHANGE ---
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from git import GitCommandError, Repo
from pydantic import BaseModel, Field  # Remove ValidationError

import config as config_module  # Added import for config module
from utils import log_message

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
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Get token from environment variable
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
        # Use the newer asyncio approach to avoid deprecation warning
        log_entry = self.format(record)
        try:
            # Use proper error handling with asyncio.create_task
            asyncio.create_task(self._send_log(log_entry))
        except Exception as e:
            # Log the error but continue
            logging.error(f"Error creating log broadcast task: {e}")

    async def _send_log(self, log_entry):
        """Helper method to safely await the broadcast call"""
        try:
            await broadcast_specific_update({"log_line": log_entry})
        except Exception as e:
            # Silently ignore errors during logging
            pass


# Configure the handler (do this after basicConfig)
ws_log_handler = WebSocketLogHandler()
ws_log_handler.setLevel(logging.INFO)  # Set desired level for WebSocket logs
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)  # Simpler format for UI - FIX: levelname instead of levellevel
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

# Ensure repo is treated as global if re-assigned
repo: Optional[Repo] = None
try:
    repo = Repo(repo_path)
    logger.info(f"Initialized existing Git repository at {repo_path}")
except git.exc.InvalidGitRepositoryError:
    try:
        repo = Repo.init(repo_path)
        logger.info(f"Initialized new Git repository at {repo_path}")
    except Exception as e:
        logger.error(f"Error initializing Git repository at {repo_path}: {e}")
        repo = None  # Indicate repo is not available
except Exception as e:
    logger.error(f"Error accessing Git repository at {repo_path}: {e}")
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

# Removed count_files_in_structure function as it's no longer the basis for actual_total_tasks


async def run_restart_script(action: str):
    """Runs the new_restart.sh script with the specified action."""
    command = f"bash ./new_restart.sh {action}"
    logger.info(f"Executing command: {command}")
    try:
        process = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if stdout:
            logger.info(f"Script stdout: {stdout.decode()}")
        if stderr:
            logger.error(f"Script stderr: {stderr.decode()}")

        if process.returncode == 0:
            logger.info(f"Script '{action}' completed successfully.")
            return True
        else:
            logger.error(
                f"Script '{action}' failed with return code {process.returncode}."
            )
            return False
    except Exception as e:
        logger.error(f"Failed to execute command '{command}': {e}")
        return False


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
    except (
        Exception
    ) as e:  # Catching generic Exception is broad, consider specific ones
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
    if ws_manager.active_connections:
        message = {"type": "status_update", "ai_status": ai_status}
        await ws_manager.broadcast(message)


async def broadcast_specific_update(update_data: dict):
    """Broadcasts a specific update to all clients."""
    if ws_manager.active_connections:
        await ws_manager.broadcast(update_data)


# Додаємо нову функцію для надсилання оновлень графіків
async def broadcast_chart_updates():
    """Формує та відправляє дані для всіх графіків."""
    if not ws_manager.active_connections:
        return

    # Отримуємо дані для графіків
    progress_data = get_progress_chart_data()

    # --- CHANGE: Refine status aggregation for Pie Chart ---
    status_counts = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "other": 0,
    }
    for status in subtask_status.values():
        if status == "pending":
            status_counts["pending"] += 1
        elif status == "processing":
            status_counts["processing"] += 1
        # More comprehensive list of completed/successful states
        elif status in [
            "accepted",
            "completed",
            "code_received",
            "tested",
            "documented",
            "skipped",
        ]:
            status_counts["completed"] += 1
        # Group failure/error states
        elif status in ["failed", "error", "needs_rework"] or (
            isinstance(status, str) and "error" in status.lower()
        ):
            status_counts["failed"] += 1
        else:
            status_counts["other"] += 1  # Catch-all for any other statuses
    # --- END CHANGE ---

    # Формуємо дані для графіка git активності
    git_activity_data = {
        "labels": [f"Commit {i+1}" for i in range(len(processed_history))],
        "values": list(processed_history),
    }

    # Формуємо повне оновлення для всіх графіків
    update_data = {
        "type": "chart_update",
        "progress_data": progress_data,
        "git_activity": git_activity_data,
        "task_status_distribution": status_counts,
        "timestamp": datetime.now().isoformat(),
    }

    # Надсилаємо оновлення всім підключеним клієнтам
    await ws_manager.broadcast(update_data)


# --- ADDED: Function to broadcast monitoring stats ---
async def broadcast_monitoring_stats():
    """Calculates and broadcasts core monitoring stats (Total, Completed)."""
    if ws_manager.active_connections:
        try:
            stats = get_progress_stats()  # Re-calculate stats
            monitoring_update = {
                "type": "monitoring_update",
                "total_tasks": stats.get("tasks_total", 0),
                "completed_tasks": stats.get("tasks_completed", 0),
                "timestamp": datetime.now().isoformat(),
            }
            await ws_manager.broadcast(monitoring_update)
        except Exception as e:
            logger.error(f"Error broadcasting monitoring stats: {e}", exc_info=True)


# --- END ADDED ---

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


async def _determine_adjusted_path(
    repo_path: Path, file_rel_path: str, _repo_dir: str  # Mark repo_dir as unused
) -> str:
    """Determines the adjusted relative path within the repo.
       Currently, this function assumes the input file_rel_path is correct
       relative to the repo_path and performs no adjustments.
       It primarily serves as a placeholder for potential future adjustments
       and logging.

    Args:
        repo_path: Повний шлях до репозиторію (/repo)
        file_rel_path: Відносний шлях файлу, який потрібно створити/оновити
        _repo_dir: Ім'я директорії репозиторію (зазвичай "repo") - Marked unused

    Returns:
        The input file_rel_path without modification.
    """
    logger.info(f"[API-Write] Using provided path relative to repo: '{file_rel_path}'")
    # Placeholder for potential future logic if adjustments are needed based on AI1 behavior.
    adjusted_rel_path = file_rel_path
    return adjusted_rel_path


async def _write_file_content(
    full_path: Path, content: str, adjusted_rel_path: str, subtask_id: Optional[str]
) -> bool:
    """Writes content to the specified file path."""
    try:
        # Check if path is a directory before attempting to write
        if full_path.is_dir():
            logger.warning(
                f"[API-Write] Attempted to write to a directory: {full_path}. "
                f"File not written. Subtask: {subtask_id}"
            )
            return False

        # Check if path ends with / which suggests it's intended as a directory
        if adjusted_rel_path.endswith("/"):
            logger.warning(
                f"[API-Write] Path ends with '/', suggesting a directory: "
                f"{adjusted_rel_path}. File not written. Subtask: {subtask_id}"
            )
            # Optionally, try to append a default filename, e.g., index.html or main.py
            # For now, just reject it.
            # Example: if adjusted_rel_path.endswith("/"):
            # adjusted_rel_path = adjusted_rel_path + "index.js"
            return False

        # Ensure parent directory exists
        if adjusted_rel_path and adjusted_rel_path != ".":
            parent_dir = full_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
            await f.write(content)
        logger.info(
            f"[API-Write] Successfully wrote code to: {adjusted_rel_path} "
            f"(Subtask: {subtask_id})"
        )
        return True
    except OSError as e:
        logger.error(
            f"[API-Write] Error writing file {full_path} "
            f"(adjusted path: {adjusted_rel_path}): {e}"
        )
        return False
    except Exception as e:
        logger.error(
            f"[API-Write] Unexpected error writing file {full_path} "
            f"(adjusted path: {adjusted_rel_path}): {e}",
            exc_info=True,
        )
        return False


async def _commit_changes(
    repo: Repo, adjusted_rel_path: str, subtask_id: Optional[str]
) -> bool:
    """Commits changes for the specified path using gitpython."""
    global processed_tasks_count, processed_history

    try:
        repo.index.add([adjusted_rel_path])
        commit_message = f"AI2 code update for {adjusted_rel_path}"
        if subtask_id:
            commit_message += f" (Subtask: {subtask_id})"

        if repo.is_dirty(index=True, working_tree=False):
            repo.index.commit(commit_message)
            logger.info(
                f"[API-Git] Committed changes for {adjusted_rel_path} "
                f"(Subtask: {subtask_id})"
            )
            processed_tasks_count += 1
            processed_history.append(processed_tasks_count)
            return True  # Commit was successful
        else:
            logger.info(
                f"[API-Git] No changes to commit for {adjusted_rel_path} "
                f"after add. (Subtask: {subtask_id})"
            )
            # Decide if writing without changes should be considered success for dispatch trigger
            return True  # No changes, but operation considered "successful" in context
    except GitCommandError as e:
        logger.error(f"[API-Git] GitCommandError committing {adjusted_rel_path}: {e}")
        logger.error(f"[API-Git] Stderr: {e.stderr}")
        return False  # Commit failed
    except Exception as e:
        logger.error(
            f"[API-Git] Unexpected error during commit for {adjusted_rel_path}: {e}"
        )
        return False  # Commit failed


async def _trigger_repository_dispatch(
    commit_successful: bool, adjusted_rel_path: str, subtask_id: Optional[str]
):
    """Triggers a GitHub repository_dispatch event if conditions are met."""
    if not commit_successful:
        logger.debug(
            "[API-GitHub] Skipping repository_dispatch because commit was not successful."
        )
        return
    if not GITHUB_TOKEN:
        logger.warning(
            "[API-GitHub] GITHUB_TOKEN not set. Skipping repository_dispatch."
        )
        return
    if GITHUB_MAIN_REPO == DEFAULT_GITHUB_REPO_PLACEHOLDER:
        logger.warning(
            "[API-GitHub] github_repo not configured in config.json. Skipping repository_dispatch."
        )
        return

    logger.info(f"[API-GitHub] Triggering repository_dispatch for {GITHUB_MAIN_REPO}")
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "event_type": "code-committed-in-repo",  # Standardized event type
        "client_payload": {"file": adjusted_rel_path, "subtask_id": subtask_id},
    }
    dispatch_url = f"https://api.github.com/repos/{GITHUB_MAIN_REPO}/dispatches"

    # Added retry mechanism for DNS resolution issues
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = requests.post(
                dispatch_url, headers=headers, json=data, timeout=10
            )
            response.raise_for_status()  # Raise an exception for bad status codes
            logger.info(
                f"[API-GitHub] Repository dispatch triggered successfully for "
                f"{adjusted_rel_path}. Status: {response.status_code}"
            )
            return  # Success, exit loop
        except requests.exceptions.ConnectionError as e_conn:
            # Handle DNS resolution and other connection errors
            logger.warning(
                f"[API-GitHub] Connection error on attempt {attempt + 1}/{max_retries} "
                f"for dispatch: {e_conn}"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.error(
                    f"[API-GitHub] Failed to trigger repository dispatch after "
                    f"{max_retries} attempts due to connection error."
                )
        except requests.exceptions.RequestException as e_req:
            logger.error(f"[API-GitHub] Error triggering repository dispatch: {e_req}")
            if hasattr(e_req, "response") and e_req.response is not None:
                logger.error(f"[API-GitHub] Response content: {e_req.response.text}")
            return  # Don't retry on other request exceptions for now
        except Exception as e_gen:
            logger.error(
                f"[API-GitHub] Unexpected error triggering repository dispatch: {e_gen}",
                exc_info=True,
            )
            return  # Don't retry on other general exceptions


async def create_follow_up_tasks(filename: str, original_executor_subtask_id: str):
    """Creates and queues tester and documenter tasks after executor finishes."""
    logger.info(
        f"[API-FollowUp] Creating follow-up tasks for {filename} "
        f"(Original: {original_executor_subtask_id})"
    )

    # --- CHANGE: Read file content ---
    file_content = None
    full_path = repo_path / filename  # Construct full path
    try:
        if (full_path).is_file():
            async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                file_content = await f.read()
            logger.debug(f"[API-FollowUp] Read content for {filename}")
        else:
            logger.warning(
                f"[API-FollowUp] File {filename} not found for reading content."
            )
    except Exception as e:
        logger.error(f"[API-FollowUp] Error reading file content for {filename}: {e}")
    # --- END CHANGE ---

    # Determine if testing is applicable (simple check based on common extensions)
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
        ".vue",
    )
    needs_testing = filename.lower().endswith(testable_extensions)

    tasks_to_add = []

    # --- Create Tester Task (if applicable) ---
    if needs_testing:
        tester_subtask_id = str(uuid4())  # Unique ID for this subtask
        tester_prompt = f"Generate unit tests for the code in file: {filename}."
        # --- CHANGE: Add file content ---
        tester_subtask = {
            "id": tester_subtask_id,
            "text": tester_prompt,
            "role": "tester",
            "filename": filename,
            "code": file_content,  # Add the read content
            # --- END CHANGE ---
            "is_rework": False,  # Assuming initial test generation is not rework
            "originating_subtask_id": original_executor_subtask_id,  # Link to original task
        }
        # Only add if content was read successfully
        if file_content is not None:
            tasks_to_add.append(("tester", tester_subtask_id, tester_subtask))
        else:
            logger.warning(
                f"[API-FollowUp] Skipping tester task for {filename} "
                f"due to missing content."
            )
    else:
        logger.info(
            f"[API-FollowUp] Skipping tester task for non-testable file: {filename}"
        )

    # --- Create Documenter Task ---
    documenter_subtask_id = str(uuid4())  # Unique ID for this subtask
    documenter_prompt = (
        f"Generate documentation (e.g., docstrings, comments) for the code in file: "
        f"{filename}."
    )
    documenter_subtask = {
        "id": documenter_subtask_id,
        "text": documenter_prompt,
        "role": "documenter",
        "filename": filename,
        # --- CHANGE: Add file content ---
        "code": file_content,  # Add the read content
        # --- END CHANGE ---
        "is_rework": False,
        "originating_subtask_id": original_executor_subtask_id,  # Link to original task
    }
    # Only add if content was read successfully
    if file_content is not None:
        tasks_to_add.append(("documenter", documenter_subtask_id, documenter_subtask))
    else:
        logger.warning(
            f"[API-FollowUp] Skipping documenter task for {filename} "
            f"due to missing content."
        )

    # --- Add tasks to queues and update status ---
    subtask_updates = {}
    queue_updates = {
        "executor": [],
        "tester": [],
        "documenter": [],
    }  # Initialize structure

    for role, subtask_id, subtask_data in tasks_to_add:
        if role == "tester":
            await tester_queue.put(subtask_data)
            subtask_status[subtask_id] = "pending_test"
            subtask_updates[subtask_id] = "pending_test"
            queue_updates["tester"].append(subtask_data)
            logger.info(f"[API-FollowUp] Queued tester task for {filename}")
        elif role == "documenter":
            await documenter_queue.put(subtask_data)
            subtask_status[subtask_id] = "pending_documentation"
            subtask_updates[subtask_id] = "pending_documentation"
            queue_updates["documenter"].append(subtask_data)
            logger.info(f"[API-FollowUp] Queued documenter task for {filename}")

    # --- Broadcast updates ---
    if subtask_updates:
        await broadcast_specific_update(
            {
                "type": "subtask_update",  # Specific type for this update
                "subtasks": subtask_updates,
                "queues": queue_updates,  # Send updated queue contents
            }
        )
        await broadcast_monitoring_stats()  # Update total/completed counts


async def write_and_commit_code(
    file_rel_path: str,
    content: str,
    subtask_id: Optional[str],
    background_tasks: BackgroundTasks,  # Add background_tasks
    role_from_report: Optional[str] = None,  # Added to determine if follow-up is needed
) -> bool:
    """Helper function to write file content, commit changes, trigger dispatch, and create follow-up tasks."""
    adjusted_rel_path = await _determine_adjusted_path(
        repo_path, file_rel_path, repo_dir
    )

    async with file_write_lock:
        # ... (rest of the path safety check) ...
        if not is_safe_path(repo_path, adjusted_rel_path):
            logger.error(
                f"[API-Write] Path traversal attempt or unsafe path: "
                f"{adjusted_rel_path}. Subtask: {subtask_id}"
            )
            return False

        full_path = repo_path / adjusted_rel_path

        write_successful = await _write_file_content(
            full_path, content, adjusted_rel_path, subtask_id
        )
        if not write_successful:
            return False  # Error already logged in _write_file_content

        current_repo = None
        try:
            current_repo = Repo(repo_path)
        except git.exc.InvalidGitRepositoryError:
            logger.error(f"[API-Git] Invalid Git repository at {repo_path}")
            return False  # Cannot commit without a valid repo
        except Exception as e:
            logger.error(f"[API-Git] Error accessing Git repository: {e}")
            return False

        commit_successful = await _commit_changes(
            current_repo, adjusted_rel_path, subtask_id
        )

        # --- ADDED: Trigger follow-up tasks on successful commit ---
        if (
            commit_successful
            and subtask_id
            and role_from_report
            == "executor"  # Only create follow-up for executor tasks
        ):
            logger.info(
                f"[API-FollowUp] Commit successful for executor task {subtask_id}, "
                f"triggering follow-up tasks for {adjusted_rel_path}."
            )
            background_tasks.add_task(
                create_follow_up_tasks, adjusted_rel_path, subtask_id
            )
        elif not commit_successful:
            logger.warning(
                f"[API-FollowUp] Commit not successful for {subtask_id}, "
                f"skipping follow-up tasks for {adjusted_rel_path}."
            )
        # --- END ADDED ---

        # Trigger dispatch regardless of commit success *if writing succeeded*?
        # Current logic triggers only if commit_successful is True (which includes "no changes staged")
        await _trigger_repository_dispatch(
            commit_successful, adjusted_rel_path, subtask_id
        )

        # Return overall success (writing succeeded, commit attempted/succeeded/no-op)
        return write_successful  # Or return commit_successful depending on strictness needed


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
            if item.startswith(".") and item != ".gitignore":
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
    logger.warning(
        f"Repository path {repo_path} does not exist, structure will be empty"
    )
    current_structure = {}


# --- Нова функція для розрахунку статистики ---
def get_progress_stats():
    """Розраховує статистику прогресу проекту на основі глобального словника `subtask_status`."""
    stats = {
        "tasks_total": 0,  # Загальна кількість відомих завдань
        "tasks_completed": 0,  # Завдання з УСПІШНИМ кінцевим статусом (для графіка)
        "files_created": 0,  # Файли, для яких executor завершив роботу (потрібно уточнити логіку)
        "files_tested_accepted": 0,  # Файли, що пройшли тестування (accepted)
        "files_rejected": 0,  # Файли, відправлені на доопрацювання (needs_rework)
    }

    stats["tasks_total"] = len(subtask_status)  # Загальна кількість відомих завдань

    # Track unique filenames for files created and tested
    created_files_executor = set()  # Files from executor tasks
    created_files_documenter = set()  # Files from documenter tasks (e.g. README.md)
    tested_files_successful = set()  # Files with successful tests
    rejected_files_testing = set()  # Files rejected after testing

    # For each task in subtask_status
    for task_id, status_val in subtask_status.items():
        task_info = tasks.get(task_id, {})  # Get task details if available
        filename = task_info.get("filename")
        role = task_info.get("role")

        # Count completed tasks (generic completion)
        if status_val in [
            "accepted",
            "completed",
            "code_received",  # Executor finished
            "tested",  # Tester finished (passed)
            "documented",  # Documenter finished
            "skipped",  # Task was skipped
        ]:
            stats["tasks_completed"] += 1

        # Files created by executor
        if role == "executor" and status_val == "code_received" and filename:
            created_files_executor.add(filename)

        # Files created/modified by documenter (e.g., README, or adding docstrings)
        if role == "documenter" and status_val == "documented" and filename:
            created_files_documenter.add(filename)

        # Files successfully tested
        if role == "tester" and status_val == "tested" and filename:
            # Assuming 'filename' in tester task refers to the code file tested
            tested_files_successful.add(filename)

        # Files rejected after testing (needs rework)
        if role == "tester" and status_val == "needs_rework" and filename:
            rejected_files_testing.add(filename)

    # Update stats based on sets
    stats["files_created"] = len(created_files_executor.union(created_files_documenter))
    stats["files_tested_accepted"] = len(tested_files_successful)
    stats["files_rejected"] = len(rejected_files_testing)

    # Fallbacks (simplified, consider removing if direct counts are reliable)
    if stats["files_created"] == 0 and stats["tasks_completed"] > 0:
        stats["files_created"] = max(0, stats["tasks_completed"] // 3)  # Rough estimate

    if stats["files_tested_accepted"] == 0 and stats["files_created"] > 0:
        # Estimate based on created files, assuming some pass testing
        stats["files_tested_accepted"] = max(0, stats["files_created"] // 2)

    logger.debug(f"Progress stats calculated: {stats}")
    return stats


def get_progress_chart_data():
    """
    Формує ОДНУ точку даних для графіка прогресу проєкту, що відображає ПОТОЧНИЙ стан.
    """
    # Отримуємо поточну статистику
    stats = get_progress_stats()

    # Поточна кількість git дій (останнє значення з історії)
    # --- FIX: Handle empty processed_history ---
    current_git_actions = processed_history[-1] if processed_history else 0
    # --- END FIX ---

    # Отримуємо значення для графіка
    completed_tasks_count = stats.get("tasks_completed", 0)
    successful_tests_count = stats.get("files_tested_accepted", 0)
    files_created_count = stats.get("files_created", 0)
    # --- ADDED: Get rejected files count ---
    rejected_files_count = stats.get("files_rejected", 0)
    # --- END ADDED ---
    total_tasks = stats.get("tasks_total", 0) or 1  # Уникаємо ділення на нуль

    # Розраховуємо відсоток прогресу
    weighted_progress = calculate_weighted_progress(
        completed_tasks_count, successful_tests_count, files_created_count, total_tasks
    )

    # Формуємо підсумкову точку даних з повною міткою часу
    return {
        "timestamp": datetime.now().strftime("%Y-%м-%d %H:%М:%С"),
        "completed_tasks": completed_tasks_count,
        "successful_tests": successful_tests_count,
        "git_actions": current_git_actions,
        "progress_percentage": weighted_progress,
        # --- ADDED: Include rejected files count ---
        "rejected_files": rejected_files_count,
        # --- END ADDED ---
    }


def calculate_weighted_progress(
    completed_tasks, successful_tests, files_created, total_tasks
):
    """
    Розраховує зважений прогрес на основі різних метрик.
    """
    # Встановлюємо вагові коефіцієнти
    task_weight = 0.4
    test_weight = 0.4
    file_weight = 0.2

    # Нормалізуємо значення до діапазону 0-100
    task_progress = (completed_tasks / total_tasks) * 100 if total_tasks else 0
    test_progress = (
        (successful_tests / max(1, files_created)) * 100 if files_created > 0 else 0
    )
    file_progress = (files_created / total_tasks) * 100 if total_tasks else 0

    # Зважений прогрес
    weighted_progress = (
        task_progress * task_weight
        + test_progress * test_weight
        + file_progress * file_weight
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
        raise HTTPException(status_code=403, detail="Access denied for path")

    file_path = repo_path / path
    logger.debug(f"Attempting to read file content for: {file_path}")

    try:
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        if file_path.is_dir():
            logger.warning(f"Path is a directory, not a file: {file_path}")
            raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
        # Return as plain text, or JSON if you expect specific content types
        return PlainTextResponse(
            content,
            media_type="text/plain; charset=utf-8",  # Ensure UTF-8 for various chars
        )

    except HTTPException as http_exc:
        raise http_exc  # Re-raise known HTTP exceptions
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error reading file: {path}")


@app.post("/subtask")
async def receive_subtask(data: dict):
    """Receives a subtask from AI1 and adds it to the appropriate queue."""
    subtask = data.get("subtask")
    if not subtask or not isinstance(subtask, dict):
        logger.error(f"Invalid subtask data received: {data}")
        raise HTTPException(status_code=400, detail="Invalid subtask data")

    subtask_id = subtask.get("id")
    role = subtask.get("role")
    filename = subtask.get("filename")
    text = subtask.get("text")

    if not all([subtask_id, role, filename, text]):
        logger.error(f"Missing required fields in subtask: {subtask}")
        raise HTTPException(
            status_code=400, detail="Missing required fields in subtask"
        )

    # Basic validation
    if role not in ["executor", "tester", "documenter"]:
        logger.error(f"Invalid role specified: {role}")
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

    if not is_safe_path(repo_path, filename):
        logger.warning(f"Subtask rejected due to unsafe path: {filename}")
        raise HTTPException(
            status_code=400, detail=f"Unsafe path specified: {filename}"
        )

    # Store the full subtask data in the global `tasks` dictionary
    tasks[subtask_id] = subtask  # Store the complete subtask details

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
        f"Received subtask for {role}: '{text[:50]}...', ID: {subtask_id}, "
        f"File: {filename}"
    )
    # Broadcast queue update
    await broadcast_specific_update(
        {
            "type": "queue_update",  # Specific type for this update
            "queues": {
                "executor": [t for t in executor_queue._queue],
                "tester": [t for t in tester_queue._queue],
                "documenter": [t for t in documenter_queue._queue],
            },
        }
    )
    # --- ADDED: Broadcast monitoring stats update ---
    await broadcast_monitoring_stats()
    # --- END ADDED ---
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
        await broadcast_specific_update(
            {
                "subtasks": {subtask.get("id"): "processing"},
                "queues": {
                    role: [t for t in queue._queue]  # Отправляем обновленную очередь
                },
            }
        )
        # --- ADDED: Broadcast monitoring stats update (status changed) ---
        await broadcast_monitoring_stats()
        # --- END ADDED ---
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
    # Broadcast structure update AND full status to ensure actual_total_tasks is updated
    await broadcast_specific_update({"structure": current_structure})
    await broadcast_full_status()  # <<< ADDED CALL
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
            # Attempt to parse if it's a dictionary (e.g., from direct curl)
            report = Report(**report_data)
        elif isinstance(report_data, Report):
            report = report_data
        else:
            logger.error(f"Invalid report data type: {type(report_data)}")
            raise HTTPException(status_code=400, detail="Invalid report data format")

        logger.info(
            f"Received report: Type: {report.type}, Subtask ID: {report.subtask_id}"
        )

        if not report.subtask_id:
            logger.error("Report received without subtask_id")
            raise HTTPException(status_code=400, detail="Missing subtask_id")

        # Update subtask status based on report type
        new_status = None
        original_task_details = tasks.get(report.subtask_id, {})
        role_from_task = original_task_details.get("role")

        if report.type == "code":
            if report.file and report.content is not None:
                logger.info(
                    f"Processing code report for {report.file} (Subtask: {report.subtask_id})"
                )
                # --- CHANGE: Pass role_from_task to write_and_commit_code ---
                write_success = await write_and_commit_code(
                    report.file,
                    report.content,
                    report.subtask_id,
                    background_tasks,
                    role_from_task,  # Pass the role here
                )
                # --- END CHANGE ---
                if write_success:
                    new_status = "code_received"  # Indicates code written and committed
                    logger.info(
                        f"Code for {report.file} (Subtask: {report.subtask_id}) "
                        f"written and committed."
                    )
                else:
                    new_status = "write_failed"
                    logger.error(
                        f"Failed to write/commit code for {report.file} "
                        f"(Subtask: {report.subtask_id})"
                    )
            else:
                logger.error(
                    f"Code report missing file or content (Subtask: {report.subtask_id})"
                )
                new_status = "invalid_code_report"

        elif report.type == "test_result":
            logger.info(f"Processing test result for subtask: {report.subtask_id}")
            processed_metrics = process_test_results(report, report.subtask_id)
            report_metrics[report.subtask_id] = processed_metrics
            # Determine status based on metrics (example logic)
            if processed_metrics.get("tests_passed", 0) > 0.9:
                new_status = "tested"  # Tests passed
            else:
                new_status = "needs_rework"  # Tests failed or low coverage
            logger.info(
                f"Test result for {report.subtask_id}: {new_status}, "
                f"Metrics: {processed_metrics}"
            )

        elif report.type == "status_update":
            new_status = report.message or "processing"
            logger.info(f"Status update for {report.subtask_id}: {new_status}")

        elif report.type == "documentation_result":  # New report type for documenter
            if report.file and report.content is not None:
                logger.info(
                    f"Processing documentation report for {report.file} (Subtask: {report.subtask_id})"
                )
                # Similar to code, write and commit documentation changes
                write_success = await write_and_commit_code(
                    report.file,
                    report.content,
                    report.subtask_id,
                    background_tasks,
                    role_from_task,  # Pass role, though documenter won't spawn new tasks
                )
                if write_success:
                    new_status = "documented"
                    logger.info(
                        f"Documentation for {report.file} (Subtask: {report.subtask_id}) "
                        f"written and committed."
                    )
                else:
                    new_status = "doc_write_failed"
                    logger.error(
                        f"Failed to write/commit documentation for {report.file} "
                        f"(Subtask: {report.subtask_id})"
                    )
            else:
                logger.error(
                    f"Documentation report missing file or content (Subtask: {report.subtask_id})"
                )
                new_status = "invalid_doc_report"

        else:
            logger.warning(f"Unknown report type: {report.type}")
            new_status = "unknown_report_type"

        # Update and broadcast status if changed
        if new_status:
            current_status = subtask_status.get(report.subtask_id)
            if current_status != new_status:
                subtask_status[report.subtask_id] = new_status
                logger.info(
                    f"Subtask {report.subtask_id} status updated to: {new_status} "
                    f"(from: {current_status})"
                )
                await broadcast_specific_update(
                    {
                        "type": "subtask_status_change",  # Specific type
                        "subtask_id": report.subtask_id,
                        "new_status": new_status,
                        "old_status": current_status,
                        "metrics": report_metrics.get(report.subtask_id),
                    }
                )
                await broadcast_monitoring_stats()  # Update total/completed counts
            else:
                logger.info(
                    f"Subtask {report.subtask_id} status ({new_status}) unchanged."
                )

        return {"status": "report received", "subtask_id": report.subtask_id}

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Error processing report: {e}", exc_info=True)
        subtask_id_from_data = (
            report_data.get("subtask_id")
            if isinstance(report_data, dict)
            else getattr(report_data, "subtask_id", None)
        )
        if subtask_id_from_data:
            subtask_status[subtask_id_from_data] = "report_error"
            await broadcast_specific_update(
                {
                    "type": "subtask_status_change",
                    "subtask_id": subtask_id_from_data,
                    "new_status": "report_error",
                    "error_message": str(e),
                }
            )
        raise HTTPException(
            status_code=500, detail=f"Error processing report: {str(e)}"
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

    if not ai or ai not in config.get("ai_config", {}):
        logger.error(f"Invalid AI component specified: {ai}")
        raise HTTPException(status_code=400, detail=f"Invalid AI component: {ai}")

    available_providers = get_available_provider_types()  # Get list of known providers
    if not provider or provider not in available_providers:
        logger.error(f"Invalid provider specified: {provider}")
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    message = ""
    config_changed = False
    current_config = config_module.load_config()  # Load current full config

    # Handle AI2 roles specifically
    if ai == "ai2":
        if not role or role not in ["executor", "tester", "documenter"]:
            logger.error(f"Invalid role for AI2: {role}")
            raise HTTPException(status_code=400, detail=f"Invalid role for AI2: {role}")
        # Ensure ai_config and ai2 structure exists
        if "ai_config" not in current_config:
            current_config["ai_config"] = {}
        if "ai2" not in current_config["ai_config"]:
            current_config["ai_config"]["ai2"] = {}
        if "provider" not in current_config["ai_config"]["ai2"]:
            current_config["ai_config"]["ai2"]["provider"] = {}

        if current_config["ai_config"]["ai2"]["provider"].get(role) != provider:
            current_config["ai_config"]["ai2"]["provider"][role] = provider
            message = (
                f"AI2 ({role}) provider updated to {provider}. "
                f"Restart AI services for changes to take effect."
            )
            config_changed = True
        else:
            message = f"AI2 ({role}) provider is already {provider}. " f"No change."

    else:  # For AI1 and AI3
        if "ai_config" not in current_config:
            current_config["ai_config"] = {}
        if ai not in current_config["ai_config"]:
            current_config["ai_config"][ai] = {}

        if current_config["ai_config"].get(ai, {}).get("provider") != provider:
            current_config["ai_config"].setdefault(ai, {})["provider"] = provider
            message = (
                f"{ai.upper()} provider updated to {provider}. "
                f"Restart AI services for changes to take effect."
            )
            config_changed = True
        else:
            message = f"{ai.upper()} provider is already {provider}. No change."

    if config_changed:
        config_module.save_config(current_config)  # Save the modified config
        logger.info(message)
        await broadcast_specific_update(
            {"type": "config_change_notice", "message": message}
        )
        return {"status": "updated", "message": message}
    else:
        logger.info(message)
        return {"status": "no_change", "message": message}


@app.get("/providers")
async def get_providers():
    """Get available providers and current configuration."""
    try:
        available_providers = get_available_provider_types()
        current_full_config = config_module.load_config()
        ai_configs_from_file = current_full_config.get("ai_config", {})

        response_current_config = {}

        # AI1
        ai1_cfg = ai_configs_from_file.get("ai1", {})
        response_current_config["ai1"] = {
            "provider": ai1_cfg.get("provider"),
            "model": ai1_cfg.get("model"),
            "fallback_provider": ai1_cfg.get("fallback_provider"),
            "fallback_model": ai1_cfg.get("fallback_model"),
        }

        # AI3
        ai3_cfg = ai_configs_from_file.get("ai3", {})
        response_current_config["ai3"] = {
            "provider": ai3_cfg.get("provider"),
            "model": ai3_cfg.get("model"),
            "fallback_provider": ai3_cfg.get("fallback_provider"),
            "fallback_model": ai3_cfg.get("fallback_model"),
        }

        # AI2
        ai2_cfg = ai_configs_from_file.get("ai2", {})
        ai2_provider_cfg = ai2_cfg.get("provider", {})
        ai2_fallback_cfg = ai2_cfg.get("fallback_config", {})

        for role in ["executor", "tester", "documenter"]:
            role_main_provider = ai2_provider_cfg.get(role)
            role_main_model = ai2_provider_cfg.get(f"{role}_model")

            role_fallback_provider_config = ai2_fallback_cfg.get(role, {})
            role_fb_provider = role_fallback_provider_config.get("provider")
            role_fb_model = role_fallback_provider_config.get("model")

            response_current_config[f"ai2-{role}"] = {
                "provider": role_main_provider,
                "model": role_main_model,
                "fallback_provider": role_fb_provider,
                "fallback_model": role_fb_model,
            }

        return JSONResponse(
            content={
                "available_providers": available_providers,
                "current_config": response_current_config,
            }
        )
    except Exception as e:
        logger.error(f"Error getting providers: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serves the main dashboard HTML page."""
    processed_tasks_count_val = len(
        [s for s in subtask_status.values() if s == "accepted"]
    )
    template_data = {
        "request": request,
        "processed_tasks": processed_tasks_count_val,
        "executor_queue_size": executor_queue.qsize(),
        "tester_queue_size": tester_queue.qsize(),
        "documenter_queue_size": documenter_queue.qsize(),
        "target": config.get("target", "Target not set in config"),
        "structure": current_structure if current_structure else {},  # Pass the object
        "config": config_module.load_config(),  # Pass full config for prompt display etc.
        "providers": get_available_provider_types(),  # Use the helper function
        "ai_config": config_module.load_config().get("ai_config", {}),
        "roles": ["executor", "tester", "documenter"],
    }

    # Add provider lists to ai_config if they don't exist (for template compatibility)
    if "ai_config" in template_data and template_data["ai_config"]:
        ai_config = template_data["ai_config"]
        provider_list = template_data["providers"]

        # Add providers to AI1 if needed
        if "ai1" in ai_config and not ai_config["ai1"].get("providers"):
            ai_config["ai1"]["providers"] = provider_list

        # Add providers to AI2 if needed
        if "ai2" in ai_config:
            if not ai_config["ai2"].get("providers"):
                ai_config["ai2"]["providers"] = {
                    "executor": provider_list,
                    "tester": provider_list,
                    "documenter": provider_list,
                }

        # Add providers to AI3 if needed
        if "ai3" in ai_config:
            if not ai_config["ai3"].get("providers"):
                ai_config["ai3"]["providers"] = provider_list
            if not ai_config["ai3"].get("structure_providers"):
                ai_config["ai3"]["structure_providers"] = provider_list

    return templates.TemplateResponse("index.html", template_data)


@app.post("/update_config")
async def update_config(data: dict):
    """Updates specific configuration values (target, prompts) and saves the config file."""
    current_full_config = config_module.load_config()
    config_changed = False

    if "target" in data and current_full_config.get("target") != data["target"]:
        current_full_config["target"] = data["target"]
        config_changed = True
        logger.info(f"Target updated to: {data['target'][:100]}...")

    # AI1 Prompts (assuming it's a list, check if it's 'ai1_prompts')
    if (
        "ai1_prompts" in data
        and isinstance(data["ai1_prompts"], list)
        and current_full_config.get("ai1_prompts") != data["ai1_prompts"]
    ):
        current_full_config["ai1_prompts"] = data["ai1_prompts"]
        config_changed = True
        logger.info("AI1 prompts updated.")

    # AI2 Prompts
    if (
        "ai2_prompts" in data
        and isinstance(data["ai2_prompts"], list)
        and len(data["ai2_prompts"])
        == 3  # Expecting 3 prompts for executor, tester, documenter
        and current_full_config.get("ai2_prompts") != data["ai2_prompts"]
    ):
        current_full_config["ai2_prompts"] = data["ai2_prompts"]
        config_changed = True
        logger.info("AI2 prompts updated.")

    # AI3 Prompts (assuming it's a list, check if it's 'ai3_prompts')
    if (
        "ai3_prompts" in data
        and isinstance(data["ai3_prompts"], list)
        and current_full_config.get("ai3_prompts") != data["ai3_prompts"]
    ):
        current_full_config["ai3_prompts"] = data["ai3_prompts"]
        config_changed = True
        logger.info("AI3 prompts updated.")

    if config_changed:
        config_module.save_config(current_full_config)
        await broadcast_specific_update(
            {
                "type": "config_updated_main",
                "message": "Main configuration (target/prompts) updated.",
                "updated_config": {
                    "target": current_full_config.get("target"),
                    "ai1_prompts": current_full_config.get("ai1_prompts"),
                    "ai2_prompts": current_full_config.get("ai2_prompts"),
                    "ai3_prompts": current_full_config.get("ai3_prompts"),
                },
            }
        )
        return {"status": "updated", "message": "Configuration updated successfully."}
    else:
        return {"status": "no_change", "message": "No configuration changes detected."}


# Новий ендпоінт для оновлення окремого елемента конфігурації
@app.post("/update_config_item")
async def update_config_item(data: dict):
    """Updates a single configuration item and saves the config file."""
    if not data or len(data) != 1:
        raise HTTPException(
            status_code=400, detail="Request must contain exactly one key-value pair."
        )

    key = list(data.keys())[0]
    value = data[key]

    # Перевірка, чи ключ існує (можна додати більш глибоку перевірку)
    # Наприклад, перевірити, чи ключ є в певній секції конфігурації
    # if key not in config: # Проста перевірка наявності ключа верхнього рівня
    #     raise HTTPException(status_code=400, detail=f"Invalid configuration key: {key}")

    # Оновлюємо значення, якщо воно змінилося
    current_value = config.get(key)
    if current_value != value:
        config[key] = value
        logger.info(f"Configuration item '{key}' updated to: {value}")
        try:
            # Save config file
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info(f"Configuration saved to {CONFIG_FILE}")

            # For ai1_desired_active_buffer, log additional info about load level
            if key == "ai1_desired_active_buffer":
                level_descriptions = {
                    5: "Minimal Load (5)",
                    10: "Low Load (10)",
                    15: "Medium Load (15)",
                    20: "High Load (20)",
                    25: "Maximum Load (25)",
                }
                level_name = level_descriptions.get(value, f"Custom Load ({value})")
                logger.info(f"System Load Level changed to: {level_name}")
                # Add WebSocket broadcast to update all clients
                await broadcast_specific_update(
                    {
                        "type": "specific_update",
                        "message": f"System Load Level changed to: {level_name}",
                        "config_update": {key: value},
                    }
                )

            return {"status": "success", "key": key, "value": value}
        except Exception as e:
            logger.error(f"Failed to save configuration for {key}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to save configuration: {e}"
            )
    else:
        logger.info(
            f"Configuration item '{key}' already has the value '{value}'. No change."
        )
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
async def start_all(background_tasks: BackgroundTasks):
    # Update status optimistically first
    ai_status["ai1"] = True
    ai_status["ai2"] = True
    ai_status["ai3"] = True
    await broadcast_full_status()  # Update UI immediately

    # --- CHANGE: Call 'start_ai' action ---
    # Run the start_ai script in the background
    background_tasks.add_task(run_restart_script, "start_ai")
    # --- END CHANGE ---

    return JSONResponse(
        # --- CHANGE: Update status message ---
        {"status": "Start AI process initiated.", "ai_status": ai_status}
        # --- END CHANGE ---
    )


@app.post("/stop_all")
async def stop_all(background_tasks: BackgroundTasks):
    # Update status optimistically first
    ai_status["ai1"] = False
    ai_status["ai2"] = False
    ai_status["ai3"] = False
    await broadcast_full_status()  # Update UI immediately

    # --- CHANGE: Call 'stop' action ---
    # Run the stop script in the background
    background_tasks.add_task(run_restart_script, "stop")
    # --- END CHANGE ---

    return JSONResponse(
        # --- CHANGE: Update status message ---
        {"status": "Stop AI process initiated.", "ai_status": ai_status}
        # --- END CHANGE ---
    )


@app.post("/clear")
async def clear_state():  # Removed background_tasks as we await commands now
    """Stops AI, clears state, repo, logs, cache, then restarts AI (keeps MCP API running)."""
    global subtask_status, report_metrics, current_structure, ai3_report, processed_history, collaboration_requests, processed_tasks_count
    # Declare repo as global to allow re-assignment
    global executor_queue, tester_queue, documenter_queue, repo

    logger.warning("Initiating AI stop and full state/repo clear...")

    # 1. Stop AI services
    logger.info("Stopping AI services...")
    stop_ai_success = await run_restart_script("stop")
    if not stop_ai_success:
        # Log and potentially raise an error or return a failure response
        logger.error("Failed to stop AI services. Aborting clear operation.")
        # Consider how to inform the user, perhaps via WebSocket or HTTP response
        # For now, just log and return, but a more robust solution might be needed.
        return {
            "status": "error",
            "message": "Failed to stop AI services. Clear operation aborted.",
        }
    logger.info("AI services stopped.")
    await asyncio.sleep(3)  # Pause after stopping AI

    # 2. Clear internal state (queues, statuses, etc.)
    logger.info("Clearing internal MCP state (queues, statuses...).")
    # Clear queues
    while not executor_queue.empty():
        try:
            executor_queue.get_nowait()
        except asyncio.QueueEmpty:
            break  # Should not happen if not empty, but good practice
    while not tester_queue.empty():
        try:
            tester_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    while not documenter_queue.empty():
        try:
            documenter_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    # Reset state variables
    subtask_status = {}
    report_metrics = {}  # Clear metrics as well
    current_structure = {}  # Reset structure as repo is cleared
    ai3_report = {"status": "pending"}  # Reset AI3 report
    processed_history.clear()
    processed_tasks_count = 0  # Reset counter
    collaboration_requests = []
    tasks.clear()  # Clear the global tasks dictionary
    logger.info("Internal MCP state cleared.")
    # --- ADDED: Broadcast monitoring stats update (state cleared) ---
    await broadcast_monitoring_stats()
    # --- END ADDED ---

    # 3. Clear repo, logs, cache using shell commands
    async def run_shell_command(command, description, working_dir=None):
        logger.info(f"Executing: {description} ('{command}')")
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,  # Specify working directory if needed
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                logger.info(f"{description} successful.")
                if stdout:
                    logger.debug(f"{description} stdout: {stdout.decode().strip()}")
                return True
            else:
                logger.error(f"{description} failed. Return code: {process.returncode}")
                if stderr:
                    logger.error(f"{description} stderr: {stderr.decode().strip()}")
                return False
        except Exception as e_shell:
            logger.error(f"Error executing '{command}' for {description}: {e_shell}")
            return False

    # Clear repo contents (preserves repo/ directory itself)
    # Ensure repo_path is correctly used for the working directory
    # --- CHANGE: Use regular string ---
    repo_clear_cmd = "find . -mindepth 1 -delete"  # Command to run inside repo_dir
    # --- END CHANGE ---
    if not await run_shell_command(
        repo_clear_cmd, "Clear repository contents", working_dir=str(repo_path)
    ):
        # If clearing repo fails, it's a significant issue. Decide how to handle.
        # For now, log and continue, but this might need to abort the operation.
        logger.error("Failed to clear repository contents. Continuing with caution.")

    # Re-initialize git repo
    logger.info(f"Re-initializing Git repository at {repo_path}")
    try:
        # --- CHANGE: Use regular string for command and specify cwd ---
        init_cmd = "git init"  # Command to run inside repo_dir
        # --- END CHANGE ---
        if await run_shell_command(
            init_cmd, "Initialize Git repository", working_dir=str(repo_path)
        ):
            repo = Repo(repo_path)  # Re-assign global repo object
            logger.info("Global repo object re-initialized.")
        else:
            logger.error("Failed to re-initialize Git repository via shell command.")
            repo = None  # Mark as unavailable
    except Exception as e_git_init:
        logger.error(f"Error re-initializing Git repository: {e_git_init}")
        repo = None  # Mark as unavailable

    # Clear logs (run from workspace root)
    # --- CHANGE: Use regular string ---
    log_clear_cmd = "rm -f logs/*.log logs/*.pid logs/*.out logs/*.json"
    # --- END CHANGE ---
    await run_shell_command(log_clear_cmd, "Clear log files")  # Don't abort if fails

    # Clear Python cache (run from workspace root)
    cache_clear_cmd_1 = "find . -type d -name '__pycache__' -exec rm -rf {} +"
    cache_clear_cmd_2 = "find . -name '*.pyc' -delete"
    await run_shell_command(cache_clear_cmd_1, "Clear __pycache__ directories")
    await run_shell_command(cache_clear_cmd_2, "Clear .pyc files")

    logger.info("Cleanup of repo, logs, and cache finished.")
    await asyncio.sleep(3)  # Pause after cleanup

    # 4. Broadcast cleared state to UI
    logger.info("Broadcasting cleared state to UI.")
    await broadcast_full_status()  # Send the now empty state

    # 5. Start AI services
    logger.info("Starting AI services...")
    start_ai_success = await run_restart_script("start_ai")
    if not start_ai_success:
        logger.error("Failed to restart AI services after clear operation.")
        # Inform user, but the clear itself was mostly successful
        return {
            "status": "warning",
            "message": "Clear operation completed, but AI services failed to restart.",
        }

    logger.info("AI services restart initiated.")

    return {
        "status": "success",
        "message": "AI stopped, state/repo cleared, AI restart initiated. MCP API remains running.",
    }


@app.post("/clear_repo")
async def clear_repo():
    """Очищає та ініціалізує Git репозиторій."""
    try:
        # This should ideally use the same robust logic as in /clear endpoint
        # For now, a simplified version. Consider refactoring to a shared utility.
        logger.info(f"Clearing and re-initializing repository at: {repo_path}")
        # Stop AIs first to avoid conflicts with repo operations
        await run_restart_script("stop")
        await asyncio.sleep(2)

        # Clear repo contents
        clear_command = f"cd {repo_path} && find . -mindepth 1 -delete"
        process_clear = await asyncio.create_subprocess_shell(clear_command)
        await process_clear.wait()

        # Re-initialize Git repo
        init_command = f"cd {repo_path} && git init"
        process_init = await asyncio.create_subprocess_shell(init_command)
        await process_init.wait()

        global repo
        repo = Repo(repo_path)  # Re-initialize global repo object

        logger.info(f"Repository at {repo_path} cleared and re-initialized.")
        # Restart AIs
        await run_restart_script("start_ai")
        return {"status": "Repository cleared and re-initialized successfully."}
    except Exception as e_clear_repo:
        logger.error(f"Error clearing repository: {e_clear_repo}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error clearing repository: {str(e_clear_repo)}"
        )


async def broadcast_full_status():
    """Broadcasts detailed status to all connected clients."""
    if ws_manager.active_connections:
        # Aggregation for Pie Chart
        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "other": 0,
        }
        for status_val in subtask_status.values():  # Iterate through values
            if status_val == "pending":
                status_counts["pending"] += 1
            elif status_val == "processing":
                status_counts["processing"] += 1
            elif status_val in [
                "accepted",
                "completed",
                "code_received",
                "tested",
                "documented",
                "skipped",
            ]:
                status_counts["completed"] += 1
            elif status_val in ["failed", "error", "needs_rework"] or (
                isinstance(status_val, str) and "error" in status_val.lower()
            ):
                status_counts["failed"] += 1
            else:
                status_counts["other"] += 1

        # Get progress chart data
        progress_chart_data = get_progress_chart_data()

        # Prepare git activity data
        history_list = list(processed_history)
        git_activity_data = {
            "labels": [f"Commit {i+1}" for i in range(len(history_list))],
            "values": history_list,
        }

        # Calculate actual total tasks as the number of known subtasks
        actual_total_tasks = len(subtask_status)
        logger.debug(
            f"[Broadcast] Calculated actual_total_tasks (known subtasks): {actual_total_tasks}"
        )

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
            "git_activity": git_activity_data,
            "progress_data": progress_chart_data,
            "task_status_distribution": status_counts,
            "actual_total_tasks": actual_total_tasks,
            "timestamp": datetime.now().isoformat(),
        }

        await ws_manager.broadcast(state_data)


# Додаємо нову функцію для відправлення повного статусу конкретному клієнту
async def send_full_status_update(websocket: WebSocket):
    """Відправляє повний статус конкретному клієнту WebSocket."""
    try:
        # --- Aggregation for Pie Chart ---
        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "other": 0,
        }
        for status_val in subtask_status.values():
            if status_val == "pending":
                status_counts["pending"] += 1
            elif status_val == "processing":
                status_counts["processing"] += 1
            elif status_val in [
                "accepted",
                "completed",
                "code_received",
                "tested",
                "documented",
                "skipped",
            ]:
                status_counts["completed"] += 1
            elif status_val in ["failed", "error", "needs_rework"] or (
                isinstance(status_val, str) and "error" in status_val.lower()
            ):
                status_counts["failed"] += 1
            else:
                status_counts["other"] += 1
        # --- End Aggregation ---

        # Get progress chart data
        progress_chart_data = get_progress_chart_data()

        # Prepare git activity data
        history_list = list(processed_history)
        git_activity_data = {
            "labels": [f"Commit {i+1}" for i in range(len(history_list))],
            "values": history_list,
        }

        # Calculate actual total tasks as the number of known subtasks
        actual_total_tasks = len(subtask_status)
        logger.debug(
            f"[Send] Calculated actual_total_tasks (known subtasks): {actual_total_tasks}"
        )

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
            "git_activity": git_activity_data,
            "progress_data": progress_chart_data,
            "task_status_distribution": status_counts,
            "actual_total_tasks": actual_total_tasks,  # Already calculated
            "timestamp": datetime.now().isoformat(),  # Add timestamp
        }

        # Відправляємо дані клієнту
        await websocket.send_json(state_data)
        logger.info(f"Sent full status update to client {websocket.client}")

    # ... (exception handling remains the same) ...
    except WebSocketDisconnect:
        logger.warning(
            f"Client {websocket.client} disconnected during full status update."
        )
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception as e_send_full:
        logger.error(
            f"Error sending full status to client {websocket.client}: {e_send_full}",
            exc_info=True,
        )


# ... rest of the file ...


class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages to clients"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.connection_info = {}  # Maps WebSocket to client info
        self.message_history = deque(
            maxlen=100
        )  # Store recent messages for new connections
        self.stats = {
            "total_connections": 0,
            "messages_sent": 0,
            "connection_errors": 0,
            "last_broadcast_time": datetime.now().isoformat(),
        }
        self.broadcast_lock = asyncio.Lock()  # Lock for thread-safe broadcasting

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and initialize client data"""
        await websocket.accept()
        self.active_connections.add(websocket)

        # Store connection info
        client_host_info = {
            "ip": websocket.client.host,
            "port": websocket.client.port,
            "connect_time": datetime.now().isoformat(),
            "messages_received": 0,
            "messages_sent": 0,
            "last_activity": datetime.now().isoformat(),
        }
        self.connection_info[websocket] = client_host_info  # Use the new variable name
        self.stats["total_connections"] += 1

        logger.info(
            f"WebSocket connection established from {websocket.client.host}:"
            f"{websocket.client.port}. Active connections: {len(self.active_connections)}"
        )

        # Send initial state to the new client
        await self.send_initial_state(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Handle client disconnection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            client_info_val = self.connection_info.pop(websocket, None)
            if client_info_val:
                logger.info(
                    f"WebSocket connection closed for {client_info_val['ip']}:"
                    f"{client_info_val['port']}. "
                    f"Active connections: {len(self.active_connections)}"
                )
            else:
                logger.info(
                    f"WebSocket connection closed (info not found). "
                    f"Active connections: {len(self.active_connections)}"
                )

    async def send_initial_state(self, websocket: WebSocket):
        """Send initial application state to a newly connected client"""
        try:
            # Send full status first
            await send_full_status_update(websocket)

            # Then send recent message history
            history_to_send = list(self.message_history)
            if history_to_send:
                await websocket.send_json(
                    {
                        "type": "message_history",
                        "history": history_to_send,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            logger.info(
                f"Sent initial state to client {websocket.client.host}:"
                f"{websocket.client.port}"
            )
        except WebSocketDisconnect:
            logger.warning(
                f"Client {websocket.client} disconnected during initial state send."
            )
            # No need to remove here, disconnect will handle it
            self.stats["connection_errors"] += 1
        except Exception as e_init_state:
            logger.error(
                f"Error sending initial state to client: {e_init_state}", exc_info=True
            )
            self.stats["connection_errors"] += 1

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients with rate limiting"""
        if not self.active_connections:
            return

        async with self.broadcast_lock:  # Ensure only one broadcast at a time
            # Add to message history (if it's not a massive status update)
            if message.get("type") != "full_status_update":
                self.message_history.append(message)

            disconnected_clients = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                    self.stats["messages_sent"] += 1
                    if connection in self.connection_info:
                        self.connection_info[connection]["messages_sent"] = (
                            self.connection_info[connection].get("messages_sent", 0) + 1
                        )
                        self.connection_info[connection][
                            "last_activity"
                        ] = datetime.now().isoformat()
                except WebSocketDisconnect:
                    disconnected_clients.append(connection)
                    self.stats["connection_errors"] += 1
                    logger.warning(
                        f"Client {connection.client} disconnected during broadcast."
                    )
                except Exception as e_broadcast_conn:
                    self.stats["connection_errors"] += 1
                    logger.error(
                        f"Error sending message to client {connection.client}: {e_broadcast_conn}",
                        exc_info=True,  # Add exc_info for more details
                    )

            for client in disconnected_clients:
                await self.disconnect(client)  # Properly handle disconnection

            self.stats["last_broadcast_time"] = datetime.now().isoformat()

    async def broadcast_specific(self, message: Dict[str, Any], filter_func=None):
        """Broadcast a message to specific clients based on a filter function"""
        if not self.active_connections:
            return

        async with self.broadcast_lock:  # Use lock here as well for consistency
            disconnected_clients = []
            for connection in self.active_connections:
                if filter_func is None or filter_func(connection):
                    try:
                        await connection.send_json(message)
                        self.stats["messages_sent"] += 1
                        if connection in self.connection_info:
                            self.connection_info[connection]["messages_sent"] = (
                                self.connection_info[connection].get("messages_sent", 0)
                                + 1
                            )
                            self.connection_info[connection][
                                "last_activity"
                            ] = datetime.now().isoformat()
                    except WebSocketDisconnect:
                        disconnected_clients.append(connection)
                        self.stats["connection_errors"] += 1
                        logger.warning(
                            f"Client {connection.client} disconnected during specific broadcast."
                        )
                    except Exception as e_broadcast_spec:
                        self.stats["connection_errors"] += 1
                        logger.error(
                            f"Error sending specific message to client {connection.client}: {e_broadcast_spec}",
                            exc_info=True,
                        )

            for client in disconnected_clients:
                await self.disconnect(client)

    async def handle_client_message(
        self, websocket: WebSocket, message_str: str  # Changed to message_str
    ):
        """Process a message from a client"""
        try:
            # Attempt to parse the message as JSON
            message_data = json.loads(message_str)
            logger.info(f"Received message from {websocket.client}: {message_data}")

            if websocket in self.connection_info:
                self.connection_info[websocket]["messages_received"] += 1
                self.connection_info[websocket][
                    "last_activity"
                ] = datetime.now().isoformat()

            # Example: Handle a ping message
            if isinstance(message_data, dict) and message_data.get("type") == "ping":
                await websocket.send_json(
                    {"type": "pong", "timestamp": datetime.now().isoformat()}
                )

            # Example: Request full status update
            elif (
                isinstance(message_data, dict)
                and message_data.get("type") == "request_full_status"
            ):
                await send_full_status_update(websocket)

            # Example: Request chart update
            elif (
                isinstance(message_data, dict)
                and message_data.get("type") == "request_chart_update"
            ):
                await broadcast_chart_updates()  # Broadcast to all, or send specifically

            # Add more client message handling logic here

        except json.JSONDecodeError:
            logger.warning(
                f"Received non-JSON message from {websocket.client}: {message_str}"
            )
            # Optionally send an error back to the client
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Invalid JSON format.",
                        "received_payload": message_str[
                            :200
                        ],  # Echo back part of the message
                    }
                )
            except WebSocketDisconnect:
                pass  # Client already disconnected
            except Exception:
                logger.error(
                    f"Error sending JSON error to client {websocket.client}",
                    exc_info=True,
                )

        except Exception as e_handle_msg:
            logger.error(
                f"Error handling message from client {websocket.client}: {e_handle_msg}",
                exc_info=True,
            )
            # Optionally send a generic error back to the client
            try:
                await websocket.send_json(
                    {"type": "error", "message": "Error processing your request."}
                )
            except WebSocketDisconnect:
                pass  # Client already disconnected
            except Exception:
                logger.error(
                    f"Error sending generic error to client {websocket.client}",
                    exc_info=True,
                )

    def get_stats(self):
        """Get WebSocket connection statistics"""
        return {
            **self.stats,
            "active_connections": len(self.active_connections),
            "clients": [
                {
                    "ip": info["ip"],
                    "port": info["port"],
                    "connect_time": info["connect_time"],
                    "last_activity": info.get("last_activity", info["connect_time"]),
                    "messages_received": info["messages_received"],
                    "messages_sent": info.get("messages_sent", 0),
                    "duration": self._calculate_duration(info["connect_time"]),
                }
                for info in self.connection_info.values()
            ],
        }

    def _calculate_duration(self, connect_time_str):
        """Calculate connection duration in seconds"""
        try:
            connect_time = datetime.fromisoformat(connect_time_str)
            return (datetime.now() - connect_time).total_seconds()
        except Exception:  # Changed from bare except to explicit Exception
            return 0

    async def cleanup_inactive_connections(
        self, max_idle_time=1800
    ):  # 30 minutes default
        """Remove connections that have been inactive for too long"""
        disconnected = 0
        now = datetime.now()

        for websocket, info in list(self.connection_info.items()):
            try:
                last_activity = datetime.fromisoformat(
                    info.get("last_activity", info["connect_time"])
                )
                idle_time = (now - last_activity).total_seconds()

                if idle_time > max_idle_time:
                    logger.info(
                        f"Disconnecting inactive client {websocket.client} (idle for {idle_time:.1f}s)"
                    )
                    await self.disconnect(websocket)
                    disconnected += 1
            except Exception as e:
                logger.error(f"Error checking client activity: {e}")

        return disconnected


# Initialize the WebSocket manager
ws_manager = WebSocketManager()


# Replace the previous websocket endpoint with the improved version
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)

    try:
        while True:
            message_text = await websocket.receive_text()
            # Pass the raw text message to the handler
            await ws_manager.handle_client_message(websocket, message_text)

    except WebSocketDisconnect:
        logger.info(f"Client {websocket.client} disconnected.")
        # ws_manager.disconnect will be called by the handler if not already
    except Exception as e_ws_endpoint:
        logger.error(
            f"WebSocket error for client {websocket.client}: {e_ws_endpoint}",
            exc_info=True,
        )
        # Ensure disconnect is called on error too
    finally:
        # This ensures disconnect is called even if handle_client_message raises an unhandled error
        # or if the loop breaks unexpectedly.
        await ws_manager.disconnect(websocket)


# Update the broadcast functions to use the WebSocket manager
async def broadcast_status():  # This function is now a re-definition, ensure it's the one to keep or remove duplicates
    """Broadcasts the current AI status to all connected clients."""
    if ws_manager.active_connections:
        message = {"type": "status_update", "ai_status": ai_status}
        await ws_manager.broadcast(message)


async def broadcast_specific_update(update_data: dict):  # Re-definition
    """Broadcasts a specific update to all clients."""
    if ws_manager.active_connections:
        await ws_manager.broadcast(update_data)


async def broadcast_chart_updates():  # Re-definition
    """Formulates and sends data for all charts."""
    if not ws_manager.active_connections:
        return

    # Get data for charts
    progress_data = get_progress_chart_data()

    # Refine status aggregation for Pie Chart
    status_counts = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "other": 0,
    }
    for status_val in subtask_status.values():
        if status_val == "pending":
            status_counts["pending"] += 1
        elif status_val == "processing":
            status_counts["processing"] += 1
        elif status_val in [
            "accepted",
            "completed",
            "code_received",
            "tested",
            "documented",
            "skipped",
        ]:
            status_counts["completed"] += 1
        elif status_val in ["failed", "error", "needs_rework"] or (
            isinstance(status_val, str) and "error" in status_val.lower()
        ):  # Group failure/error states
            status_counts["failed"] += 1
        else:
            status_counts["other"] += 1

    # Format data for git activity chart
    git_activity_data = {
        "labels": [f"Commit {i+1}" for i in range(len(processed_history))],
        "values": list(processed_history),
    }

    # Format complete update for all charts
    update_data = {
        "type": "chart_update",
        "progress_data": progress_data,
        "git_activity": git_activity_data,
        "task_status_distribution": status_counts,
        "timestamp": datetime.now().isoformat(),
    }

    # Send update to all connected clients
    await ws_manager.broadcast(update_data)


async def broadcast_monitoring_stats():  # Re-definition
    """Calculates and broadcasts core monitoring stats (Total, Completed)."""
    if ws_manager.active_connections:
        try:
            stats = get_progress_stats()
            monitoring_update = {
                "type": "monitoring_update",
                "total_tasks": stats.get("tasks_total", 0),
                "completed_tasks": stats.get("tasks_completed", 0),
                "timestamp": datetime.now().isoformat(),
            }
            await ws_manager.broadcast(monitoring_update)
        except Exception as e_mon_stats:
            logger.error(
                f"Error broadcasting monitoring stats: {e_mon_stats}", exc_info=True
            )


async def broadcast_full_status():  # Re-definition
    """Broadcasts detailed status to all connected clients."""
    if ws_manager.active_connections:
        # Aggregation for Pie Chart
        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "other": 0,
        }
        for status_val in subtask_status.values():  # Iterate through values
            if status_val == "pending":
                status_counts["pending"] += 1
            elif status_val == "processing":
                status_counts["processing"] += 1
            elif status_val in [
                "accepted",
                "completed",
                "code_received",
                "tested",
                "documented",
                "skipped",
            ]:
                status_counts["completed"] += 1
            elif status_val in ["failed", "error", "needs_rework"] or (
                isinstance(status_val, str) and "error" in status_val.lower()
            ):
                status_counts["failed"] += 1
            else:
                status_counts["other"] += 1

        # Get progress chart data
        progress_chart_data = get_progress_chart_data()

        # Prepare git activity data
        history_list = list(processed_history)
        git_activity_data = {
            "labels": [f"Commit {i+1}" for i in range(len(history_list))],
            "values": history_list,
        }

        # Calculate actual total tasks as the number of known subtasks
        actual_total_tasks = len(subtask_status)
        logger.debug(
            f"[Broadcast] Calculated actual_total_tasks (known subtasks): {actual_total_tasks}"
        )

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
            "git_activity": git_activity_data,
            "progress_data": progress_chart_data,
            "task_status_distribution": status_counts,
            "actual_total_tasks": actual_total_tasks,
            "timestamp": datetime.now().isoformat(),
        }

        await ws_manager.broadcast(state_data)


# Add new API endpoint to get WebSocket stats
@app.get("/ws/stats")
async def get_websocket_stats():
    """Returns statistics about WebSocket connections"""
    return ws_manager.get_stats()


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
            "queue_size": executor_queue.qsize(),
        },
        "tester": {
            "status": "idle" if tester_queue.empty() else "busy",
            "queue_empty": tester_queue.empty(),
            "queue_size": tester_queue.qsize(),
        },
        "documenter": {
            "status": "idle" if documenter_queue.empty() else "busy",
            "queue_empty": documenter_queue.empty(),
            "queue_size": documenter_queue.qsize(),
        },
    }
    return worker_status


@app.post("/request_task_for_idle_worker")
async def request_task_for_idle_worker(data: dict):
    """Запитує нову задачу для воркера, що простоює."""
    worker = data.get("worker")
    if not worker or worker not in ["executor", "tester", "documenter"]:
        logger.error(f"Invalid worker specified for task request: {worker}")
        raise HTTPException(status_code=400, detail=f"Invalid worker: {worker}")

    # Перевіряємо, чи є задачі у відповідній черзі
    queue = None
    if worker == "executor":
        queue = executor_queue
    elif worker == "tester":
        queue = tester_queue
    elif worker == "documenter":
        queue = documenter_queue

    if queue.empty():
        logger.info(f"No tasks available for idle worker: {worker}")
        return {"success": False, "message": f"No tasks available for {worker}"}

    try:
        task = await queue.get()
        subtask_status[task["id"]] = "processing"  # Update status
        logger.info(f"Task {task['id']} assigned to idle worker: {worker}")
        await broadcast_specific_update(
            {
                "type": "task_assigned",
                "task_id": task["id"],
                "worker": worker,
                "status": "processing",
            }
        )
        return {"success": True, "task": task}
    except asyncio.QueueEmpty:  # Should be caught by earlier check, but good for safety
        logger.info(f"Queue for {worker} became empty before task retrieval.")
        return {"success": False, "message": f"No tasks available for {worker}"}
    except Exception as e_req_task:
        logger.error(
            f"Error requesting task for idle worker {worker}: {e_req_task}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Error retrieving task")


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
    log_message(
        f"Received test recommendation: {recommendation.recommendation}, Context: {recommendation.context}"
    )

    failed_files = recommendation.context.get("failed_files", [])
    updated_tasks = []

    # Знаходимо завдання, пов'язані з файлами, що не пройшли тест/лінтинг
    for task_id, task_data in tasks.items():
        # Перевіряємо, чи файл завдання є серед тих, що не пройшли перевірку
        # Або якщо рекомендація 'rework' і немає конкретних файлів (загальна помилка workflow)
        if task_data.get("file") in failed_files or (
            recommendation.recommendation == "rework" and not failed_files
        ):
            if recommendation.recommendation == "rework":
                # Перевіряємо, чи статус вже не 'needs_rework', щоб уникнути зациклення
                if task_data["status"] != "needs_rework":
                    task_data["status"] = "needs_rework"
                    task_data["test_context"] = (
                        recommendation.context
                    )  # Зберігаємо контекст помилки
                    updated_tasks.append(task_id)
            # Не оновлюємо статус на 'accepted' тут, це зробить AI1
            # elif recommendation.recommendation == "accept" і task_data["status"] == "tested":
            #     task_data["status"] = "accepted" # Позначаємо як прийняте
            #     updated_tasks.append(task_id)

    if updated_tasks:
        # --- CHANGE: Use broadcast_specific_update ---
        await broadcast_specific_update(
            {
                "type": "task_update",
                "message": f"Test recommendation '{recommendation.recommendation}' applied to tasks: {updated_tasks}",
            }
        )
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
            logger.info("Periodic chart updates task cancelled successfully.")
        except Exception as e_shutdown:
            logger.error(
                f"Error during shutdown of chart update task: {e_shutdown}",
                exc_info=True,
            )


class TaskScheduler:
    """Intelligent task scheduler with dynamic load balancing and parallel processing"""

    def __init__(self):
        self.tasks = {
            "executor": asyncio.Queue(),
            "tester": asyncio.Queue(),
            "documenter": asyncio.Queue(),
        }
        self.in_progress = {}  # task_id -> worker_id
        self.worker_status = (
            {}
        )  # worker_id -> {"role": str, "busy": bool, "last_active": float}
        self.task_dependencies = {}  # task_id -> List[task_id]
        self.task_priorities = {}  # task_id -> priority_score
        self.task_history = (
            {}
        )  # task_id -> {"status": str, "completion_time": float, "attempts": int}
        self.load_metrics = {
            role: [] for role in self.tasks.keys()
        }  # Track processing times

    async def add_task(
        self,
        task: Dict[str, Any],
        role: str,
        dependencies: List[str] = None,
        priority: int = 1,
    ) -> str:
        """Add a task to the appropriate queue with dependencies and priority"""
        task_id = str(uuid.uuid4())
        task["id"] = task_id

        # Store dependency information
        if dependencies:
            self.task_dependencies[task_id] = dependencies
            # Calculate priority based on dependencies
            priority += sum(self.task_priorities.get(dep, 0) for dep in dependencies)

        self.task_priorities[task_id] = priority

        # Only add to queue if no unmet dependencies
        if not dependencies or all(dep in self.task_history for dep in dependencies):
            await self.tasks[role].put((priority, task))
            logger.info(
                f"Task {task_id} added to {role} queue with priority {priority}"
            )
        else:
            logger.info(f"Task {task_id} waiting for dependencies: {dependencies}")

        return task_id

    async def get_next_task(
        self, role: str, worker_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get the next highest priority task for a worker, considering dependencies"""
        try:
            # Check for tasks that were in progress by this worker (if any)
            # This logic might be complex if workers can pick up others' tasks
            # For now, assume a worker continues its own task or gets a new one.

            # Get tasks from the role-specific queue, ordered by priority
            # (heapq implements a min-heap, so store negative priority)
            # This requires tasks in queue to be (priority, task_data) tuples
            # For simplicity, let's assume asyncio.Queue is used directly for now
            # and priority is handled during task addition or a separate mechanism.

            if not self.tasks[role].empty():
                task = await self.tasks[role].get()
                task_id = task["id"]
                self.in_progress[task_id] = worker_id
                self.worker_status[worker_id] = {
                    "role": role,
                    "busy": True,
                    "last_active": time.time(),
                    "current_task": task_id,
                }
                logger.info(
                    f"Task {task_id} assigned to worker {worker_id} for role {role}"
                )
                return task
            else:
                logger.info(f"No tasks available in queue for role {role}")
                return None
        except KeyError:  # If role is invalid
            logger.error(f"Invalid role specified for get_next_task: {role}")
            return None
        except Exception as e_get_task:
            logger.error(f"Error getting next task: {e_get_task}", exc_info=True)
            return None

    async def complete_task(
        self, task_id: str, success: bool, processing_time: float
    ) -> None:
        """Mark a task as completed and update metrics"""
        try:
            if task_id in self.in_progress:
                worker_id = self.in_progress.pop(task_id)
                role = self.worker_status[worker_id]["role"]
                self.worker_status[worker_id]["busy"] = False
                self.worker_status[worker_id]["last_active"] = time.time()
                self.worker_status[worker_id].pop("current_task", None)

                status = "completed" if success else "failed"
                self.task_history[task_id] = {
                    "status": status,
                    "completion_time": processing_time,
                    "attempts": self.task_history.get(task_id, {}).get("attempts", 0)
                    + 1,
                    "timestamp": time.time(),
                }
                self.load_metrics[role].append(processing_time)
                logger.info(f"Task {task_id} marked as {status} by worker {worker_id}")

                # Process dependent tasks if successful
                if success:
                    await self._process_dependent_tasks(task_id)
            else:
                logger.warning(f"Task {task_id} not found in progress to complete.")
        except Exception as e_complete_task:
            logger.error(
                f"Error completing task {task_id}: {e_complete_task}", exc_info=True
            )

    async def _process_dependent_tasks(self, completed_task_id: str) -> None:
        """Process tasks that were waiting on the completed task"""
        for task_id, deps in self.task_dependencies.items():
            if completed_task_id in deps:
                # Check if all dependencies are now met
                if all(dep in self.task_history for dep in deps):
                    # Find the role for this task
                    for role, queue in self.tasks.items():
                        async with queue._queue.mutex:  # Access internal queue items
                            for priority, task in queue._queue:
                                if task["id"] == task_id:
                                    logger.info(f"Unblocking dependent task {task_id}")
                                    return

    def get_queue_status(self) -> Dict[str, Dict[str, Any]]:
        """Get current status of all queues and workers"""
        status = {}
        for role in self.tasks:
            status[role] = {
                "queue_size": self.tasks[role].qsize(),
                "active_workers": sum(
                    1
                    for w in self.worker_status.values()
                    if w["role"] == role and w["busy"]
                ),
                "avg_processing_time": (
                    sum(self.load_metrics[role]) / len(self.load_metrics[role])
                    if self.load_metrics[role]
                    else 0
                ),
            }
        return status

    async def rebalance_queues(self) -> None:
        """Rebalance tasks between queues based on load metrics"""
        status = self.get_queue_status()

        # Calculate load factors
        total_load = sum(
            s["avg_processing_time"] * s["queue_size"] for s in status.values()
        )
        if total_load == 0:
            return

        load_factors = {
            role: (s["avg_processing_time"] * s["queue_size"]) / total_load
            for role, s in status.items()
        }

        # Find overloaded and underloaded queues
        avg_load = sum(load_factors.values()) / len(load_factors)
        threshold = 0.2  # 20% deviation threshold

        overloaded = {
            r: lf for r, lf in load_factors.items() if lf > avg_load * (1 + threshold)
        }
        underloaded = {
            r: lf for r, lf in load_factors.items() if lf < avg_load * (1 - threshold)
        }

        if not overloaded or not underloaded:
            return

        # Attempt to move tasks from overloaded to underloaded queues
        for over_role in overloaded:
            # Find the most underloaded queue to move tasks to
            under_role = min(underloaded, key=underloaded.get)
            await self._move_eligible_tasks(over_role, under_role)

    async def _move_eligible_tasks(self, from_role: str, to_role: str) -> None:
        """Move eligible tasks between queues"""
        try:
            # This is a simplified example. Real implementation needs care.
            # Ensure tasks are not currently being processed.
            # Consider task compatibility with the new role.
            temp_holder = []
            while not self.tasks[from_role].empty():
                try:
                    task = self.tasks[from_role].get_nowait()
                    if self._can_move_task(task, to_role):
                        await self.tasks[to_role].put(task)
                        logger.info(
                            f"Moved task {task['id']} from {from_role} to {to_role}"
                        )
                    else:
                        temp_holder.append(task)  # Put back if not moved
                except asyncio.QueueEmpty:
                    break

            # Put back tasks that were not moved
            for task_item in temp_holder:
                await self.tasks[from_role].put(task_item)

        except Exception as e_move_tasks:
            logger.error(
                f"Error moving tasks from {from_role} to {to_role}: {e_move_tasks}",
                exc_info=True,
            )

    def _can_move_task(self, task: Dict[str, Any], target_role: str) -> bool:
        """Check if a task can be moved to the target role"""
        # Add logic here to determine if a task can be handled by different roles
        # For now, return False to prevent arbitrary moves
        return False

    async def monitor_worker_health(self) -> None:
        """Monitor worker health and handle stalled tasks"""
        while True:
            try:
                current_time = time.time()
                for worker_id, status in self.worker_status.items():
                    if status["busy"]:
                        # Check for stalled tasks (no activity for 5 minutes)
                        if current_time - status["last_active"] > 300:
                            await self._handle_stalled_task(worker_id)

                # Clean up old history entries
                self._cleanup_history()

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error in worker health monitoring: {e}")
                await asyncio.sleep(60)

    async def _handle_stalled_task(self, worker_id: str) -> None:
        """Handle a stalled task by requeueing it"""
        try:
            if worker_id in self.worker_status and self.worker_status[worker_id].get(
                "busy"
            ):
                task_id = self.worker_status[worker_id].get("current_task")
                role = self.worker_status[worker_id]["role"]
                if task_id and task_id in self.in_progress:
                    # Requeue the task (potentially with increased priority or to a different queue)
                    # For simplicity, just put it back to its original role's queue
                    task_data = None  # TODO: Get actual task data
                    # This requires storing the task data itself or retrieving it.
                    # For now, we can't directly requeue without the task object.
                    # This part needs refinement: how to get task_data if only ID is known here?
                    # One way: self.in_progress stores task_id -> task_object

                    # Assuming self.in_progress[task_id] stores the task object:
                    # task_data = self.in_progress.pop(task_id) # Get and remove
                    # if task_data:
                    #    await self.tasks[role].put(task_data)
                    #    logger.warning(f"Requeued stalled task {task_id} from worker {worker_id} to {role} queue.")
                    # else:
                    #    logger.error(f"Could not retrieve task data for stalled task {task_id}")

                    # Simplified: Just log and mark worker as not busy
                    logger.warning(
                        f"Worker {worker_id} detected as stalled on task {task_id}. "
                        f"Marking worker as not busy. Task needs manual re-queue or handling."
                    )
                    self.worker_status[worker_id]["busy"] = False
                    self.worker_status[worker_id].pop("current_task", None)
                    if task_id in self.in_progress:  # Clean up in_progress too
                        del self.in_progress[task_id]

                    # Increment attempt count if we had task_data
                    # if task_data and task_id in self.task_history:
                    #    self.task_history[task_id]["attempts"] = self.task_history[task_id].get("attempts", 0) + 1
                else:
                    logger.info(
                        f"Worker {worker_id} was busy but no current task ID found."
                    )
                    self.worker_status[worker_id]["busy"] = False  # Reset busy status
            else:
                logger.debug(
                    f"Worker {worker_id} not busy or not found, no action for stall."
                )
        except Exception as e_stall_handle:
            logger.error(
                f"Error handling stalled task for worker {worker_id}: {e_stall_handle}",
                exc_info=True,
            )

    def _cleanup_history(self) -> None:
        """Clean up old history entries"""
        try:
            current_time = time.time()
            # Keep entries from last 24 hours
            cutoff_time = current_time - 86400

            self.task_history = {
                tid: data
                for tid, data in self.task_history.items()
                if data.get("completion_time", current_time) > cutoff_time
            }
        except Exception as e:
            logger.error(f"Error cleaning up task history: {e}")


# Initialize scheduler
scheduler = TaskScheduler()


@app.post("/task/{role}")
async def get_task(role: str):
    """Get next task for a worker"""
    worker_id = str(uuid.uuid4())  # Generate unique worker ID
    task = await scheduler.get_next_task(role, worker_id)
    return {"task": task, "worker_id": worker_id} if task else {"task": None}


class MCPApi:
    """Advanced Model Context Protocol (MCP) API implementation"""

    def __init__(self):
        self.task_queue = TaskQueue()
        self.task_scheduler = TaskScheduler()
        self.dependency_manager = DependencyManager()
        self.code_analyzer = CodeAnalyzer()
        self.pattern_learner = PatternLearner()
        self.status_monitor = StatusMonitor()

    async def create_project(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a new software project with enhanced planning and analysis"""
        try:
            project_id = str(uuid.uuid4())
            # 1. Analyze requirements (placeholder)
            analysis = await self.code_analyzer.analyze_requirements(request)
            # 2. Create project plan
            plan = await self.task_scheduler.create_project_plan(analysis)
            # 3. Store project plan and initialize status
            self.project_plans[project_id] = plan
            await self.status_monitor.initialize_project_status(project_id, plan)

            logger.info(
                f"Project {project_id} created with {len(plan['tasks'])} tasks."
            )
            return {"project_id": project_id, "plan": plan}
        except Exception as e_create_proj:
            logger.error(f"Error creating project: {e_create_proj}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error creating project")

    async def get_task(self, role: str) -> Dict[str, Any]:
        """Get next task for an AI worker with enhanced context"""
        try:
            task = await self.task_scheduler.get_next_task(
                role, worker_id=f"mcp_api_worker_{role}"
            )  # Example worker_id
            if task:
                task = await self.enhance_task_context(task)
                await self.status_monitor.update_task_status(task["id"], "assigned")
                logger.info(f"Task {task['id']} assigned to role {role}")
                return task
            logger.info(f"No tasks available for role {role}")
            return {"task": None}
        except Exception as e_get_task_mcp:
            logger.error(
                f"Error getting task for role {role}: {e_get_task_mcp}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=f"Error getting task for role {role}"
            )

    async def enhance_task_context(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance task with relevant context and patterns"""
        # Add project context
        project_context = await self.get_project_context(task["project_id"])
        task["context"] = project_context

        # Add learned patterns
        patterns = await self.pattern_learner.get_relevant_patterns(task)
        task["patterns"] = patterns

        # Add dependencies
        dependencies = await self.dependency_manager.get_task_dependencies(task["id"])
        task["dependencies"] = dependencies

        return task

    async def report_progress(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Process task progress report with enhanced analysis"""
        try:
            task_id = report["task_id"]
            await self.status_monitor.update_task(task_id, report)

            # Analyze for blockers
            blockers = await self.analyze_blockers(report)
            if blockers:
                await self.handle_blockers(blockers)
                logger.warning(f"Blockers identified for task {task_id}: {blockers}")
                return {"status": "processed_with_blockers", "blockers": blockers}

            # Learn patterns from successful tasks (example)
            if report.get("status") == "completed" and report.get("code_analysis"):
                await self.pattern_learner.learn_from_task(report)

            logger.info(f"Progress report processed for task {task_id}")
            return {"status": "processed"}
        except Exception as e_report_prog:
            logger.error(
                f"Error processing progress report: {e_report_prog}", exc_info=True
            )
            raise HTTPException(status_code=500, detail="Error processing report")

    async def analyze_blockers(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze task report for potential blockers"""
        blockers = []

        # Check for errors
        if report.get("status") == "error":
            blocker = {
                "type": "error",
                "task_id": report["task_id"],
                "description": report.get("error_message", "Unknown error"),
                "severity": self._assess_severity(report),
            }
            blockers.append(blocker)

        # Check for missing dependencies
        missing_deps = await self.dependency_manager.check_missing_dependencies(report)
        if missing_deps:
            blocker = {
                "type": "missing_dependency",
                "task_id": report["task_id"],
                "dependencies": missing_deps,
            }
            blockers.append(blocker)

        return blockers

    def _assess_severity(self, report: Dict[str, Any]) -> str:
        """Assess the severity of reported issues"""
        if "error" in report.get("error_message", "").lower():
            return "high"
        elif "warning" in report.get("error_message", "").lower():
            return "medium"
        return "low"

    async def handle_blockers(self, blockers: List[Dict[str, Any]]):
        """Handle identified blockers"""
        for blocker in blockers:
            if blocker["type"] == "error":
                await self._handle_error_blocker(blocker)
            elif blocker["type"] == "missing_dependency":
                await self._handle_dependency_blocker(blocker)

    async def _handle_error_blocker(self, blocker: Dict[str, Any]):
        """Handle error-type blockers"""
        # Retry strategy based on severity
        if blocker["severity"] == "high":
            await self.task_scheduler.reschedule_task(
                blocker["task_id"], priority="high"
            )
        else:
            await self.task_scheduler.retry_task(blocker["task_id"])

    async def _handle_dependency_blocker(self, blocker: Dict[str, Any]):
        """Handle dependency-related blockers"""
        # Schedule missing dependencies
        for dep in blocker["dependencies"]:
            await self.task_scheduler.schedule_dependency(dep)

    async def get_project_status(self, project_id: str) -> Dict[str, Any]:
        """Get detailed project status with analytics"""
        try:
            status = await self.status_monitor.get_project_status(project_id)
            if not status:
                raise HTTPException(status_code=404, detail="Project not found")

            # Add analytics
            status["progress_analysis"] = await self.analyze_project_progress(
                project_id
            )
            status["completion_prediction"] = await self.predict_completion(project_id)

            logger.info(f"Retrieved status for project {project_id}")
            return status
        except HTTPException as http_e:
            raise http_e  # Re-raise HTTPException
        except Exception as e_get_proj_status:
            logger.error(
                f"Error getting project status for {project_id}: {e_get_proj_status}",
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Error getting project status")

    async def analyze_project_progress(self, project_id: str) -> Dict[str, Any]:
        """Analyze project progress with metrics"""
        return {
            "completion_rate": await self._calculate_completion_rate(project_id),
            "error_rate": await self._calculate_error_rate(project_id),
            "bottlenecks": await self._identify_bottlenecks(project_id),
            "quality_metrics": await self._calculate_quality_metrics(project_id),
        }

    async def predict_completion(self, project_id: str) -> Dict[str, Any]:
        """Predict project completion metrics"""
        return {
            "estimated_completion_time": await self._estimate_completion_time(
                project_id
            ),
            "risk_factors": await self._identify_risk_factors(project_id),
            "resource_requirements": await self._estimate_resource_requirements(
                project_id
            ),
        }


class TaskQueue:
    """Enhanced task queue with priority and dependency management"""

    def __init__(self):
        self.tasks = []
        self.processing = {}
        self.completed = {}
        self.lock = asyncio.Lock()

    async def add_task(self, task: Dict[str, Any], priority: int = 1):
        """Add task to queue with priority"""
        async with self.lock:
            heapq.heappush(self.tasks, (priority, task))

    async def get_next_task(self, role: str) -> Optional[Dict[str, Any]]:
        """Get next task considering dependencies"""
        async with self.lock:
            while self.tasks:
                priority, task = heapq.heappop(self.tasks)
                if task["role"] == role and await self._can_process(task):
                    self.processing[task["id"]] = task
                    return task
                else:
                    heapq.heappush(self.tasks, (priority, task))
        return None

    async def _can_process(self, task: Dict[str, Any]) -> bool:
        """Check if task can be processed"""
        deps = task.get("dependencies", [])
        return all(dep in self.completed for dep in deps)


class TaskScheduler:
    """Advanced task scheduler with dependency resolution"""

    def __init__(self):
        self.task_queue = TaskQueue()
        self.project_plans = {}
        self.lock = asyncio.Lock()

    async def create_project_plan(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Create project execution plan"""
        tasks = []
        dependencies = []

        # Create tasks from analysis
        for component in analysis["components"]:
            task = await self._create_component_tasks(component)
            tasks.extend(task)

        # Identify dependencies
        for task in tasks:
            deps = await self._identify_dependencies(task)
            dependencies.extend(deps)

        return {
            "tasks": tasks,
            "dependencies": dependencies,
            "estimated_duration": await self._estimate_duration(tasks),
        }


class DependencyManager:
    """Manages task dependencies and relationships"""

    def __init__(self):
        self.dependencies = {}
        self.lock = asyncio.Lock()

    async def add_dependency(self, task_id: str, dependency: str):
        """Add task dependency"""
        async with self.lock:
            if task_id not in self.dependencies:
                self.dependencies[task_id] = set()
            self.dependencies[task_id].add(dependency)

    async def check_dependencies(self, task_id: str) -> bool:
        """Check if all dependencies are met"""
        if task_id not in self.dependencies:
            return True
        return all(self._is_completed(dep) for dep in self.dependencies[task_id])


class CodeAnalyzer:
    """Analyzes code and project requirements"""

    def __init__(self):
        self.pattern_matcher = PatternMatcher()
        self.requirement_analyzer = RequirementAnalyzer()

    async def analyze_requirements(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze project requirements"""
        components = await self.requirement_analyzer.extract_components(request)
        patterns = await self.pattern_matcher.find_patterns(components)

        return {
            "components": components,
            "patterns": patterns,
            "complexity": await self._estimate_complexity(components),
        }


class StatusMonitor:
    """Monitors project and task status"""

    def __init__(self):
        self.project_status = {}
        self.task_status = {}
        self.metrics = {}
        self.lock = asyncio.Lock()

    async def track_task(self, task_id: str, status: str):
        """Track task status changes"""
        async with self.lock:
            self.task_status[task_id] = {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "updates": [],
            }

    async def update_task(self, task_id: str, report: Dict[str, Any]):
        """Update task status with report"""
        async with self.lock:
            if task_id in self.task_status:
                self.task_status[task_id]["updates"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "status": report.get("status"),
                        "progress": report.get("progress"),
                        "message": report.get("message"),
                    }
                )


@app.post("/ai3/repo_cleared")
async def receive_repo_cleared_report():
    """Receives a report from AI3 that the repository has been cleared."""
    logger.info("Received report from AI3: Repository cleared")
    global ai3_report
    ai3_report = {"status": "repo_cleared", "timestamp": datetime.now().isoformat()}
    await broadcast_specific_update({"ai3_report": ai3_report})
    return {"status": "received"}


@app.post("/ai3/structure_creation_completed")
async def receive_structure_creation_report():
    """Receives a report from AI3 that the structure creation phase has completed."""
    logger.info("Received report from AI3: Structure creation completed")
    global ai3_report
    ai3_report = {
        "status": "structure_creation_completed",
        "timestamp": datetime.now().isoformat(),
    }
    await broadcast_specific_update({"ai3_report": ai3_report})
    return {"status": "received"}


@app.post("/ai3/structure_setup_completed")
async def receive_structure_setup_report():
    """Receives a report from AI3 that the structure setup phase has completed."""
    logger.info("Received report from AI3: Structure setup completed")
    global ai3_report
    ai3_report = {
        "status": "structure_setup_completed",
        "timestamp": datetime.now().isoformat(),
    }
    await broadcast_specific_update({"ai3_report": ai3_report})
    return {"status": "received"}


# Helper functions for provider configuration (These seem to be duplicated or misplaced, ensure they are defined once correctly if needed)
# The following @app.route for /providers and /provider_models, /component_fallbacks might conflict
# with earlier @app.get definitions if 'app' is a FastAPI instance and 'route' is an alias.
# It's better to use @app.get, @app.post consistently for FastAPI.

# Removed conflicting/Flask-style /update_providers endpoint previously here (around lines 3301-3326)

# ...existing code...
# @app.route("/providers", methods=["GET"]) # This might be a problematic duplicate or old code
# async def get_providers_alt_version(): # Renamed to avoid direct conflict for now, but should be reviewed
#     """Get available providers and current configuration."""
#     try:
#         # Get all available providers from ProviderFactory
#         available_providers = list(get_available_provider_types())
#
#         # Get current AI configuration
#         config_data = await load_config()
#
#         # Return data as JSON
#         return jsonify(
#             {
#                 "available_providers": available_providers,
#                 "current_config": {
#                     "ai1": get_ai_provider_config(config_data, "ai1"),
#                     "ai2": {
#                         "executor": get_ai_provider_config(
#                             config_data, "ai2", "executor"
#                         ),
#                         "tester": get_ai_provider_config(config_data, "ai2", "tester"),
#                         "documenter": get_ai_provider_config(
#                             config_data, "ai2", "documenter"
#                         ),
#                     },
#                     "ai3": get_ai_provider_config(config_data, "ai3"),
#                 },
#             }
#         )
#     except Exception as e:
#         logger.error(f"Error getting providers: {e}")
#         return jsonify({"error": str(e)}), 500


# @app.route("/provider_models", methods=["GET"])
# async def get_provider_models(provider: str = None):
#     """Get available models for a specific provider."""
#     if not provider:
#         return JSONResponse(
#             content={"error": "Provider name is required"}, status_code=400
#         )
#
#     try:
#         # Import the provider functions
#         from providers import get_provider_models as get_models
#
#         # Get available models
#         models = get_models(provider)
#         return JSONResponse(content={"models": models})
#     except Exception as e:
#         logger.error(f"Error getting models for provider {provider}: {e}")
#         return JSONResponse(content={"error": str(e)}, status_code=500)


# @app.get("/component_fallbacks") # This uses jsonify, prefer the other FastAPI version
# async def get_component_fallbacks_old(component: str = None): # Renamed to avoid conflict
#     """Get fallback providers for a specific AI component."""
#     if not component:
#         return {"error": "Component parameter is required"}, 400
#
#     try:
#         # Parse component to get AI and role
#         parts = component.split("-")
#         ai = parts[0]
#
#         # Handle AI2 with specific role
#         role = parts[1] if len(parts) > 1 else None
#
#         # Import provider functions
#         from providers import get_component_fallbacks as get_fallbacks
#
#         # Get fallbacks
#         fallbacks = get_fallbacks(ai, role)
#         return {"fallbacks": fallbacks} # This implicitly becomes JSONResponse in FastAPI
#     except Exception as e:
#         logger.error(f"Error getting fallbacks for component {component}: {e}")
#         return {"error": str(e)}, 500 # This implicitly becomes JSONResponse


# @app.route("/component_fallbacks", methods=["GET"])
# async def get_component_fallbacks():
#     """Get fallback providers for a specific AI component."""
#     try:
#         component = request.args.get("component")
#         if not component:
#             return jsonify({"error": "Component name is required"}), 400
#
#         # Load configuration
#         config_data = await load_config() # Ensure load_config is available and async
#
#         # Parse component to get AI and role
#         ai, role = parse_component_name(component)
#
#         # Get fallbacks
#         fallbacks = get_component_fallbacks_config(config_data, ai, role)
#
#         return jsonify({"fallbacks": fallbacks})
#     except Exception as e:
#         logger.error(f"Error getting fallbacks for component {component}: {e}")
#         return jsonify({"error": str(e)}), 500


# @app.route("/update_providers", methods=["POST"])
# async def update_providers_old_flask_style(): # Renamed to avoid conflict
#     """Update provider configuration for all AI components."""
#     try:
#         # Get request data
#         data = request.json # Problematic: uses Flask's request
#         if not data:
#             return jsonify({"error": "No data provided"}), 400 # Problematic: uses Flask's jsonify
#
#         # Load current configuration
#         config_data = await load_config() # Problematic: load_config not defined here
#
#         # Update AI1 provider
#         if "ai1" in data:
#             update_ai_provider_config(config_data, "ai1", data["ai1"]) # update_ai_provider_config might be an issue
#
#         # Update AI2 providers
#         if "ai2" in data:
#             if "executor" in data["ai2"]:
#                 update_ai_provider_config(
#                     config_data, "ai2", data["ai2"]["executor"], "executor"
#                 )
#             if "tester" in data["ai2"]:
#                 update_ai_provider_config(
#                     config_data, "ai2", data["ai2"]["tester"], "tester"
#                 )
#             if "documenter" in data["ai2"]:
#                 update_ai_provider_config(
#                     config_data, "ai2", data["ai2"]["documenter"], "documenter"
#                 )
#
#         # Update AI3 provider
#         if "ai3" in data:
#             update_ai_provider_config(config_data, "ai3", data["ai3"])
#
#         # Save configuration
#         await save_config(config_data) # Problematic: save_config not defined here
#
#         # Return success
#         return jsonify({"status": "success"}) # Problematic: uses Flask's jsonify
#     except Exception as e:
#         logger.error(f"Error updating providers: {e}")
#         return jsonify({"status": "error", "message": str(e)}), 500 # Problematic: uses Flask's jsonify


# ...existing code...


# Helper functions for provider configuration


def get_available_provider_types():
    """Get all available provider types."""
    # List of all provider types supported by our system
    return [
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


def parse_component_name(component):
    """Parse component name into AI and role."""
    if component == "ai1":
        return "ai1", None
    elif component == "ai3":
        return "ai3", None
    elif component.startswith("ai2-"):
        role = component.split("-")[1]
        return "ai2", role
    else:
        raise ValueError(f"Invalid component name: {component}")


def get_ai_provider_config(config, ai, role=None):
    """Get provider configuration for an AI component."""
    if ai == "ai1":
        provider_config = config.get("ai1_provider", {})
    elif ai == "ai2" and role:
        providers = config.get("ai2_providers", {})
        provider_config = providers.get(role, {})
    elif ai == "ai3":
        provider_config = config.get("ai3_provider", {})
    else:
        provider_config = {}

    return {
        "provider": provider_config.get("type", ""),
        "model": provider_config.get("model", ""),
        "fallbacks": get_component_fallbacks_config(config, ai, role),
    }


def get_component_fallbacks_config(config, ai, role=None):
    """Get fallback providers for an AI component."""
    if ai == "ai1":
        provider_config = config.get("ai1_provider", {})
    elif ai == "ai2" and role:
        providers = config.get("ai2_providers", {})
        provider_config = providers.get(role, {})
    elif ai == "ai3":
        provider_config = config.get("ai3_provider", {})
    else:
        provider_config = {}

    fallbacks = []
    if provider_config.get("type") == "fallback":
        fallback_providers = provider_config.get("providers", [])
        for p in fallback_providers:
            fallbacks.append(
                {"provider": p.get("type", ""), "model": p.get("model", "")}
            )

    return fallbacks


def update_ai_provider_config(config, ai, provider_data, role=None):
    """Update provider configuration for an AI component."""
    provider_type = provider_data.get("provider", "")
    model = provider_data.get("model", "")
    fallbacks = provider_data.get("fallbacks", [])

    # Create provider config
    if fallbacks and len(fallbacks) > 0:
        # Use fallback provider with the specified providers
        provider_config = {"type": "fallback", "providers": []}

        # Add first provider
        provider_config["providers"].append({"type": provider_type, "model": model})

        # Add fallback providers
        for fallback in fallbacks:
            fallback_provider = fallback.get("provider")
            fallback_model = fallback.get("model")
            if fallback_provider and fallback_model:
                provider_config["providers"].append(
                    {"type": fallback_provider, "model": fallback_model}
                )
    else:
        # Use a single provider
        provider_config = {"type": provider_type, "model": model}

    # Update config
    if ai == "ai1":
        config["ai1_provider"] = provider_config
    elif ai == "ai2" and role:
        if "ai2_providers" not in config:
            config["ai2_providers"] = {}
        config["ai2_providers"][role] = provider_config
    elif ai == "ai3":
        config["ai3_provider"] = provider_config


@app.post("/update_providers")
async def update_providers(data: dict):
    """Update provider configuration for all AI components."""
    try:
        if not data:
            return {"status": "error", "message": "No data provided"}, 400

        # Load current configuration
        current_full_config = config_module.load_config()

        # Update AI1 provider if included
        if "ai1" in data:
            provider_data = data["ai1"]
            provider_type = provider_data.get("provider", "")
            model = provider_data.get("model", "")
            fallbacks = provider_data.get("fallbacks", [])

            if "ai_config" not in current_full_config:
                current_full_config["ai_config"] = {}
            if "ai1" not in current_full_config["ai_config"]:
                current_full_config["ai_config"]["ai1"] = {}

            current_full_config["ai_config"]["ai1"]["provider"] = provider_type
            current_full_config["ai_config"]["ai1"]["model"] = model

            # Handle fallbacks if provided
            if fallbacks:
                current_full_config["ai_config"]["ai1"]["fallbacks"] = fallbacks
            elif "fallbacks" in current_full_config["ai_config"]["ai1"]:
                # Clear fallbacks if empty array was sent
                current_full_config["ai_config"]["ai1"]["fallbacks"] = []

        # Update AI2 providers if included
        if "ai2" in data:
            ai2_data = data["ai2"]
            for role in ["executor", "tester", "documenter"]:
                if role in ai2_data:
                    provider_data = ai2_data[role]
                    provider_type = provider_data.get("provider", "")
                    model = provider_data.get("model", "")
                    fallbacks = provider_data.get("fallbacks", [])

                    if "ai_config" not in current_full_config:
                        current_full_config["ai_config"] = {}
                    if "ai2" not in current_full_config["ai_config"]:
                        current_full_config["ai_config"]["ai2"] = {}
                    if role not in current_full_config["ai_config"]["ai2"]:
                        current_full_config["ai_config"]["ai2"][role] = {}

                    current_full_config["ai_config"]["ai2"][role][
                        "provider"
                    ] = provider_type
                    current_full_config["ai_config"]["ai2"][role]["model"] = model

                    # Handle fallbacks if provided
                    if fallbacks:
                        current_full_config["ai_config"]["ai2"][role][
                            "fallbacks"
                        ] = fallbacks
                    elif "fallbacks" in current_full_config["ai_config"]["ai2"][role]:
                        # Clear fallbacks if empty array was sent
                        current_full_config["ai_config"]["ai2"][role]["fallbacks"] = []

        # Update AI3 provider if included
        if "ai3" in data:
            provider_data = data["ai3"]
            provider_type = provider_data.get("provider", "")
            model = provider_data.get("model", "")
            fallbacks = provider_data.get("fallbacks", [])

            # Handle structure provider settings
            structure_provider = provider_data.get("structure_provider")
            structure_model = provider_data.get("structure_model")
            structure_fallbacks = provider_data.get("structure_fallbacks", [])

            if "ai_config" not in current_full_config:
                current_full_config["ai_config"] = {}
            if "ai3" not in current_full_config["ai_config"]:
                current_full_config["ai_config"]["ai3"] = {}

            current_full_config["ai_config"]["ai3"]["provider"] = provider_type
            current_full_config["ai_config"]["ai3"]["model"] = model

            # Handle main fallbacks if provided
            if fallbacks:
                current_full_config["ai_config"]["ai3"]["fallbacks"] = fallbacks
            elif "fallbacks" in current_full_config["ai_config"]["ai3"]:
                # Clear fallbacks if empty array was sent
                current_full_config["ai_config"]["ai3"]["fallbacks"] = []

            # Handle structure provider settings if provided
            if structure_provider:
                current_full_config["ai_config"]["ai3"][
                    "structure_provider"
                ] = structure_provider
            if structure_model:
                current_full_config["ai_config"]["ai3"][
                    "structure_model"
                ] = structure_model
            if structure_fallbacks:
                current_full_config["ai_config"]["ai3"][
                    "structure_fallbacks"
                ] = structure_fallbacks
            elif "structure_fallbacks" in current_full_config["ai_config"]["ai3"]:
                # Clear structure fallbacks if empty array was sent
                current_full_config["ai_config"]["ai3"]["structure_fallbacks"] = []

        # Save the updated configuration using the config module
        if config_module.save_config(current_full_config):
            logger.info("Provider configuration updated and saved successfully")

            # Update global config
            global config
            config = current_full_config

            # Return success
            return {
                "status": "success",
                "message": "Provider configuration updated successfully",
            }
        else:
            logger.error("Failed to save configuration")
            return {
                "status": "error",
                "message": "Failed to save configuration",
            }, 500

    except Exception as e:
        logger.error(f"Error updating providers: {e}", exc_info=True)
        return {"status": "error", "message": f"Error updating providers: {e}"}, 500


# Add a proper endpoint to get provider models
@app.get("/provider_models")
async def get_provider_models_endpoint(
    provider: str = Query(..., description="The name of the provider")
):
    """
    Retrieves the available models for a specified provider.
    Ensures that the provider name is correctly passed as a string.
    """
    try:
        from providers import (
            get_provider_models as get_models,
        )  # Assuming this function exists in providers.py

        # Assuming get_models is an async function or a synchronous one that is safe to await indirectly
        # If get_models is purely synchronous and potentially blocking,
        # it should be run in a thread pool:
        # models = await asyncio.get_event_loop().run_in_executor(None, get_models, provider)
        models = await get_models(provider)  # If get_models is async

        return JSONResponse(content={"models": models})
    except ImportError:
        logger.error(
            "Failed to import 'get_provider_models' from providers.py for /provider_models endpoint"
        )
        return JSONResponse(
            content={
                "status": "error",
                "message": "Model fetching mechanism not found on server.",
            },
            status_code=500,
        )
    except Exception as e:
        logger.error(
            f"Error getting models for provider '{provider}': {e}", exc_info=True
        )
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Error getting models for provider {provider}: {str(e)}",
            },
            status_code=500,
        )


# ...existing code...
@app.get("/component_fallbacks")
async def get_component_fallbacks(
    component: str = Query(None, description="Component ID like ai1, ai2-executor")
):
    """Get fallback providers for a specific AI component from config."""
    if not component:
        return JSONResponse(
            content={"error": "Component parameter is required"}, status_code=400
        )

    try:
        current_full_config = config_module.load_config()
        ai_config = current_full_config.get("ai_config", {})
        fallbacks = []

        # Handle special case for ai3-structure
        if component == "ai3-structure":
            ai3_cfg = ai_config.get("ai3", {})
            # Use new array-based structure_fallbacks
            structure_fallbacks = ai3_cfg.get("structure_fallbacks", [])
            return JSONResponse(content={"fallbacks": structure_fallbacks})

        # Parse component name for regular components
        ai_name, role = parse_component_name(component)

        if ai_name == "ai1":
            ai1_cfg = ai_config.get("ai1", {})
            # Check for new array-based fallbacks first
            array_fallbacks = ai1_cfg.get("fallbacks", [])
            if array_fallbacks:
                fallbacks = array_fallbacks
            else:
                # Fall back to old style fallback provider/model if present
                fallback_provider = ai1_cfg.get("fallback_provider")
                fallback_model = ai1_cfg.get("fallback_model")
                if fallback_provider and fallback_model:
                    fallbacks = [
                        {"provider": fallback_provider, "model": fallback_model}
                    ]

        elif ai_name == "ai3":
            ai3_cfg = ai_config.get("ai3", {})
            # Check for new array-based fallbacks first
            array_fallbacks = ai3_cfg.get("fallbacks", [])
            if array_fallbacks:
                fallbacks = array_fallbacks
            else:
                # Fall back to old style fallback provider/model if present
                fallback_provider = ai3_cfg.get("fallback_provider")
                fallback_model = ai3_cfg.get("fallback_model")
                if fallback_provider and fallback_model:
                    fallbacks = [
                        {"provider": fallback_provider, "model": fallback_model}
                    ]

        elif ai_name == "ai2" and role:
            ai2_component = ai_config.get("ai2", {}).get(role, {})
            # Check for new array-based fallbacks first
            array_fallbacks = ai2_component.get("fallbacks", [])
            if array_fallbacks:
                fallbacks = array_fallbacks
            else:
                # Fall back to old style fallback provider/model if present
                fallback_provider = ai2_component.get("fallback_provider")
                fallback_model = ai2_component.get("fallback_model")
                if fallback_provider and fallback_model:
                    fallbacks = [
                        {"provider": fallback_provider, "model": fallback_model}
                    ]
                else:
                    # Also check the legacy fallback_config format if needed
                    ai2_fb_cfg = ai_config.get("ai2", {}).get("fallback_config", {})
                    role_fb = ai2_fb_cfg.get(role, {})
                    fb_provider = role_fb.get("provider")
                    fb_model = role_fb.get("model")
                    if fb_provider and fb_model:
                        fallbacks = [{"provider": fb_provider, "model": fb_model}]
        else:
            logger.warning(f"Unknown component for fallbacks: {component}")
            return JSONResponse(
                content={"error": f"Unknown component: {component}"}, status_code=400
            )

        return JSONResponse(content={"fallbacks": fallbacks})

    except Exception as e_get_fb:
        logger.error(
            f"Error getting fallbacks for component {component}: {e_get_fb}",
            exc_info=True,
        )
        return JSONResponse(
            content={"error": f"Error getting fallbacks: {str(e_get_fb)}"},
            status_code=500,
        )


# Remove duplicated @app.route("/component_fallbacks", methods=["GET"]) as it's covered above
# async def get_component_fallbacks():
# ... (old code was here)


# Removed conflicting/Flask-style /update_providers endpoint previously here (around lines 3630-3655)
# @app.route("/update_providers", methods=["POST"])
# async def update_providers():
#     """Updates provider configuration (OpenAI, Anthropic, etc.)."""
#     try:
#         data = request.json
#         if not data:
#             return jsonify({"error": "No data provided"}), 400
#
#         # Load current config
#         config_data = await load_config() # Ensure load_config is async or handle appropriately
#
#         # Update AI1
#         if "ai1" in data:
#             update_ai_provider_config(config_data, "ai1", data["ai1"])
#
#         # Update AI2 (executor, tester, documenter)
#         if "ai2" in data:
#             for role in ["executor", "tester", "documenter"]:
#                 if role in data["ai2"]:
#                     update_ai_provider_config(config_data, "ai2", data["ai2"][role], role)
#
#         # Update AI3
#         if "ai3" in data:
#             update_ai_provider_config(config_data, "ai3", data["ai3"])
#
#         # Save updated config
#         await save_config(config_data) # Ensure save_config is async or handle appropriately
#
#         return jsonify({"status": "success"})
#     except Exception as e:
#         logger.error(f"Error updating providers: {e}")
#         return jsonify({"status": "error", "message": str(e)}), 500


# Helper functions for provider configuration
@app.websocket_route("/monitor_ws")
async def monitor_websocket(websocket: WebSocket):
    """WebSocket endpoint for monitoring data, separate from the main websocket for clients"""
    await websocket.accept()
    logger.info(f"Monitoring WebSocket connection established from {websocket.client}")

    try:
        # Send initial system status
        await websocket.send_json(
            {
                "type": "monitor_status",
                "message": "Monitoring WebSocket connected",
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Listen for monitoring updates
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "monitor_update":
                # Forward to all clients connected to the main WebSocket
                await ws_manager.broadcast(
                    {
                        "type": "system_metrics",
                        "data": data.get("data", {}),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                logger.debug("Forwarded monitoring update to clients")
    except WebSocketDisconnect:
        logger.info(f"Monitoring WebSocket disconnected: {websocket.client}")
    except Exception as e:
        logger.error(f"Error in monitoring WebSocket: {e}", exc_info=True)


# Add an HTTP endpoint to get latest monitoring data
@app.get("/monitoring/status")
async def get_monitoring_status():
    """Returns the latest monitoring status data"""
    try:
        status_path = os.path.join("logs", "load_status.json")
        if not os.path.exists(status_path):
            return JSONResponse(
                content={"error": "Monitoring data not available"}, status_code=404
            )

        with open(status_path, "r") as f:
            status_data = json.load(f)

        return status_data
    except Exception as e:
        logger.error(f"Error reading monitoring status: {e}")
        return JSONResponse(
            content={"error": f"Error reading monitoring data: {str(e)}"},
            status_code=500,
        )


# Define placeholder classes for services
class PatternLearner:
    """Placeholder for the PatternLearner service."""

    def __init__(self):
        pass


class PatternMatcher:
    """Placeholder for the PatternMatcher service."""

    def __init__(self):
        pass


class RequirementAnalyzer:
    """Placeholder for the RequirementAnalyzer service."""

    def __init__(self):
        pass


# ... rest of existing code ...
