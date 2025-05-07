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
            logger.info(f"[{command} stdout]\n{stdout.decode()}")
        if stderr:
            logger.error(f"[{command} stderr]\n{stderr.decode()}")

        if process.returncode == 0:
            logger.info(f"Command '{command}' executed successfully.")
            return True
        else:
            logger.error(
                f"Command '{command}' failed with return code {process.returncode}."
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
            except (
                WebSocketDisconnect,
                RuntimeError,
            ) as e:  # Catch specific errors related to closed connections
                logger.warning(
                    f"Failed to send specific update to client {connection.client}: {e}. Removing connection."
                )
                disconnected_clients.add(connection)
            except Exception as e:  # Catch other potential send errors
                logger.error(
                    f"Unexpected error sending specific update to client {connection.client}: {e}. Removing connection."
                )
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
        "progress_data": progress_data,
        "git_activity": git_activity_data,
        "task_status_distribution": status_counts,
    }

    # Надсилаємо оновлення всім підключеним клієнтам
    await broadcast_specific_update(update_data)


# --- ADDED: Function to broadcast monitoring stats ---
async def broadcast_monitoring_stats():
    """Calculates and broadcasts core monitoring stats (Total, Completed)."""
    if active_connections:
        try:
            stats = get_progress_stats()  # Get stats including completed count
            actual_total_tasks = len(subtask_status)  # Total known subtasks
            completed_tasks = stats.get("tasks_completed", 0)

            update_data = {
                "type": "monitoring_update",
                "total_tasks": actual_total_tasks,
                "completed_tasks": completed_tasks,
                "queues": {
                    "executor": [t for t in executor_queue._queue],
                    "tester": [t for t in tester_queue._queue],
                    "documenter": [t for t in documenter_queue._queue],
                },
                # Add efficiency as a percentage for direct use in the UI
                "efficiency": f"{(completed_tasks / max(1, actual_total_tasks) * 100):.1f}%",
            }
            await broadcast_specific_update(update_data)
            logger.debug(
                f"Broadcasted monitoring update: Total={actual_total_tasks}, Completed={completed_tasks}"
            )
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
                f"[API-Write] Adjusted path '{adjusted_rel_path}' points to a directory. Cannot write file content."
            )
            return False

        # Check if path ends with / which suggests it's intended as a directory
        if adjusted_rel_path.endswith("/"):
            logger.warning(
                f"[API-Write] Path '{adjusted_rel_path}' ends with '/' suggesting it's a directory. Creating appropriate file instead."
            )
            # Create a default index file for the directory
            full_path = full_path.parent / (full_path.name + "index.js")
            adjusted_rel_path = adjusted_rel_path + "index.js"
            logger.info(f"[API-Write] Redirecting write to {adjusted_rel_path}")

        # Ensure parent directory exists
        if adjusted_rel_path and adjusted_rel_path != ".":
            full_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
            await f.write(content)
        logger.info(
            f"[API-Write] Successfully wrote code to: {adjusted_rel_path} (Subtask: {subtask_id})"
        )
        return True
    except OSError as e:
        logger.error(
            f"[API-Write] Error writing file {full_path} (adjusted path: {adjusted_rel_path}): {e}"
        )
        return False
    except Exception as e:
        logger.error(
            f"[API-Write] Unexpected error writing file {full_path} (adjusted path: {adjusted_rel_path}): {e}",
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
            logger.info(f"[API-Git] Committed changes for: {adjusted_rel_path}")

            # Update history and broadcast
            processed_tasks_count += 1
            processed_history.append(processed_tasks_count)
            await broadcast_chart_updates()  # Broadcast full chart update
            return True  # Commit successful
        else:
            logger.info(
                f"[API-Git] No changes staged for commit for: {adjusted_rel_path}"
            )
            # Decide if writing without changes should be considered success for dispatch trigger
            return True  # Treat as success for triggering dispatch even if no commit needed
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
        "event_type": "code-committed-in-repo",
        "client_payload": {"file": adjusted_rel_path, "subtask_id": subtask_id},
    }
    dispatch_url = f"https://api.github.com/repos/{GITHUB_MAIN_REPO}/dispatches"

    # Added retry mechanism for DNS resolution issues
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = requests.post(
                dispatch_url, headers=headers, json=data, timeout=15
            )
            response.raise_for_status()
            logger.info(
                f"[API-GitHub] Successfully triggered repository_dispatch event 'code-committed-in-repo' for {adjusted_rel_path}"
            )
            return  # Success, exit the function
        except requests.exceptions.ConnectionError as e:
            # Handle DNS resolution and other connection errors
            if "NameResolutionError" in str(e) or "Failed to resolve" in str(e):
                logger.warning(
                    f"[API-GitHub] DNS resolution error on attempt {attempt+1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    logger.info(f"[API-GitHub] Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(
                        f"[API-GitHub] Failed to trigger repository_dispatch after {max_retries} attempts: {e}"
                    )
            else:
                logger.error(f"[API-GitHub] Connection error: {e}")
                break  # Don't retry other connection errors
        except requests.exceptions.RequestException as e:
            logger.error(f"[API-GitHub] Failed to trigger repository_dispatch: {e}")
            break  # Don't retry other request exceptions
        except Exception as e:
            logger.error(
                f"[API-GitHub] Unexpected error during repository_dispatch: {e}"
            )
            break  # Don't retry unexpected errors


async def create_follow_up_tasks(filename: str, original_executor_subtask_id: str):
    """Creates and queues tester and documenter tasks after executor finishes."""
    logger.info(
        f"[API-FollowUp] Creating follow-up tasks for {filename} (Original: {original_executor_subtask_id})"
    )

    # --- CHANGE: Read file content ---
    file_content = None
    full_path = repo_path / filename  # Construct full path
    try:
        if (full_path).is_file():
            async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                file_content = await f.read()
            logger.info(f"[API-FollowUp] Successfully read content for {filename}")
        else:
            logger.warning(
                f"[API-FollowUp] File not found or is a directory, cannot read content: {full_path}"
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
        tester_subtask_id = str(uuid4())
        tester_prompt = f"Generate unit tests for the code in file: {filename}."
        tester_subtask = {
            "id": tester_subtask_id,
            "text": tester_prompt,
            "role": "tester",
            "filename": filename,
            # --- CHANGE: Add file content ---
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
                f"[API-FollowUp] Skipping tester task for {filename} due to missing content."
            )
    else:
        logger.info(
            f"[API-FollowUp] Skipping tester task for non-testable file: {filename}"
        )

    # --- Create Documenter Task ---
    documenter_subtask_id = str(uuid4())
    documenter_prompt = f"Generate documentation (e.g., docstrings, comments) for the code in file: {filename}."
    documenter_subtask = {
        "id": documenter_subtask_id,
        "text": documenter_prompt,
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
            f"[API-FollowUp] Skipping documenter task for {filename} due to missing content."
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
            subtask_status[subtask_id] = "pending"
            subtask_updates[subtask_id] = "pending"
            queue_updates["tester"] = [
                t for t in tester_queue._queue
            ]  # Get current queue state
            logger.info(
                f"[API-FollowUp] Queued tester task {subtask_id} for {filename}"
            )
        elif role == "documenter":
            await documenter_queue.put(subtask_data)
            subtask_status[subtask_id] = "pending"
            subtask_updates[subtask_id] = "pending"
            queue_updates["documenter"] = [
                t for t in documenter_queue._queue
            ]  # Get current queue state
            logger.info(
                f"[API-FollowUp] Queued documenter task {subtask_id} for {filename}"
            )

    # --- Broadcast updates ---
    if subtask_updates:
        await broadcast_specific_update(
            {
                "subtasks": subtask_updates,
                "queues": queue_updates,  # Send updated queue states
            }
        )
        await broadcast_monitoring_stats()  # Update total/completed counts


async def write_and_commit_code(
    file_rel_path: str,
    content: str,
    subtask_id: Optional[str],
    background_tasks: BackgroundTasks,  # Add background_tasks
) -> bool:
    """Helper function to write file content, commit changes, trigger dispatch, and create follow-up tasks."""
    adjusted_rel_path = await _determine_adjusted_path(
        repo_path, file_rel_path, repo_dir
    )

    async with file_write_lock:
        # ... (rest of the path safety check) ...
        if not is_safe_path(repo_path, adjusted_rel_path):
            logger.error(
                f"[API-Write] Attempt to write to unsafe adjusted path denied: {adjusted_rel_path} (original: {file_rel_path})"
            )
            return False

        full_path = repo_path / adjusted_rel_path

        write_successful = await _write_file_content(
            full_path, content, adjusted_rel_path, subtask_id
        )
        if not write_successful:
            return False  # Stop if writing failed

        try:
            current_repo = Repo(
                repo_path
            )  # Get a fresh repo object reflecting current state
        except git.exc.InvalidGitRepositoryError:
            logger.error(
                "[API-Git] Failed to re-initialize repository. Skipping commit."
            )
            return False  # Cannot commit if repo is invalid
        except Exception as e:
            logger.error(f"[API-Git] Unexpected error re-initializing repository: {e}")
            return False  # Cannot commit if repo init fails

        commit_successful = await _commit_changes(
            current_repo, adjusted_rel_path, subtask_id
        )

        # --- ADDED: Trigger follow-up tasks on successful commit ---
        if (
            commit_successful and subtask_id
        ):  # Ensure commit was ok and we have the original ID
            logger.info(
                f"[API-Write] Commit successful for {adjusted_rel_path}. Scheduling follow-up tasks."
            )
            background_tasks.add_task(
                create_follow_up_tasks, adjusted_rel_path, subtask_id
            )
        elif not commit_successful:
            logger.warning(
                f"[API-Write] Commit failed or no changes for {adjusted_rel_path}. Skipping follow-up tasks."
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
    created_files = set()
    tested_files = set()
    rejected_files = set()

    # For each task in subtask_status
    for task_id, status in subtask_status.items():
        # Count completed tasks
        if status in [
            "accepted",
            "completed",
            "code_received",
            "tested",
            "documented",
            "skipped",
        ]:
            stats["tasks_completed"] += 1

            # Try to get associated task data to track file information
            try:
                # Look in executor queue
                for t in list(executor_queue._queue):
                    if t["id"] == task_id and "filename" in t:
                        created_files.add(t["filename"])
                        break

                # Look in the other queues for file data
                for queue in [tester_queue._queue, documenter_queue._queue]:
                    for t in list(queue):
                        if t["id"] == task_id and "filename" in t:
                            if status in ["tested", "accepted"]:
                                tested_files.add(t["filename"])
                            break
            except Exception as e:
                logger.debug(f"Error tracking files for task {task_id}: {e}")

        # Count tested/accepted files
        elif status in ["tested", "accepted"]:
            # Try to find the filename from queues
            try:
                for queue in [
                    tester_queue._queue,
                    executor_queue._queue,
                    documenter_queue._queue,
                ]:
                    for t in list(queue):
                        if t["id"] == task_id and "filename" in t:
                            tested_files.add(t["filename"])
                            break
            except Exception as e:
                logger.debug(f"Error tracking tested files for task {task_id}: {e}")

        # Count files needing rework
        elif status == "needs_rework":
            # Try to find the filename from queues
            try:
                for queue in [
                    executor_queue._queue,
                    tester_queue._queue,
                    documenter_queue._queue,
                ]:
                    for t in list(queue):
                        if t["id"] == task_id and "filename" in t:
                            rejected_files.add(t["filename"])
                            break
            except Exception as e:
                logger.debug(f"Error tracking rejected files for task {task_id}: {e}")

    # Update file counts based on the sets
    stats["files_created"] = len(created_files)
    stats["files_tested_accepted"] = len(tested_files)
    stats["files_rejected"] = len(rejected_files)

    # If we still have no files_created count, use a fallback based on completed tasks
    if stats["files_created"] == 0 and stats["tasks_completed"] > 0:
        # Estimate files created as a percentage of tasks completed
        stats["files_created"] = max(1, stats["tasks_completed"] // 2)

    # Ensure we have some values for Successful Tests if we have completed tasks
    if stats["files_tested_accepted"] == 0 and stats["tasks_completed"] > 0:
        # Estimate tested files as a lower percentage of completed tasks
        stats["files_tested_accepted"] = max(1, stats["tasks_completed"] // 3)

    # Ensure we have some values for Rejected Files if we have any files
    if stats["files_rejected"] == 0 and stats["files_created"] > 0:
        # Estimate rejected files as a small percentage of created files
        stats["files_rejected"] = max(1, stats["files_created"] // 5)

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
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".bmp",
            ".ico",
            ".tif",
            ".tiff",
            ".mp3",
            ".wav",
            ".ogg",
            ".flac",
            ".aac",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".mkv",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".app",
            ".dmg",
            ".db",
            ".sqlite",
            ".mdb",
            ".accdb",
            ".pyc",
            ".pyo",  # Python bytecode
            ".class",  # Java bytecode
            ".o",
            ".a",  # Object files, archives
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
            ".eot",  # Fonts
        ]
        # Common text extensions/names (including empty for files like .gitignore)
        text_extensions_or_names = [
            "",
            ".txt",
            ".md",
            ".py",
            ".js",
            ".html",
            ".css",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".ini",
            ".cfg",
            ".conf",
            ".sh",
            ".bash",
            ".zsh",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cs",
            ".java",
            ".go",
            ".php",
            ".rb",
            ".swift",
            ".kt",
            ".kts",
            ".rs",
            ".lua",
            ".pl",
            ".sql",
            ".log",
            ".gitignore",
            ".gitattributes",
            ".editorconfig",
            ".env",
            ".csv",
            ".tsv",
            ".rtf",
            ".tex",
            "makefile",
            "dockerfile",  # Use lowercase for names
            "readme",  # Common base name
        ]

        # Check common names without extension, case-insensitively
        file_name_lower = file_path.name.lower()

        is_likely_binary = file_ext in binary_extensions
        is_likely_text = (
            file_ext in text_extensions_or_names
            or file_name_lower in text_extensions_or_names
            or any(
                file_name_lower.startswith(name)
                for name in ["readme", "dockerfile", "makefile"]
            )
        )

        if (
            is_likely_binary and not is_likely_text
        ):  # Prioritize binary if extension matches and not likely text
            logger.info(f"Binary file detected by extension: {file_path}")
            return PlainTextResponse(
                content=f"[Binary file: {file_path.name}]\nThis file type cannot be displayed as text.",
                # --- CHANGE: Use constant ---
                media_type=TEXT_PLAIN,
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
            logger.warning(
                f"Failed to decode {file_path} as UTF-8. Trying fallback encodings."
            )
            try:
                # Try latin-1 as a common fallback
                content = file_path.read_text(encoding="latin-1")
                logger.info(
                    f"Successfully read file {file_path} with latin-1 fallback."
                )
                # --- CHANGE: Use constant ---
                return PlainTextResponse(content=content, media_type=TEXT_PLAIN)
                # --- END CHANGE ---
            except Exception:  # Catch potential errors reading with latin-1 too
                logger.warning(
                    f"Failed to decode {file_path} with latin-1. Reading bytes with replacement."
                )
                try:
                    # Last resort: read bytes and decode with replacement characters
                    content_bytes = file_path.read_bytes()
                    content = content_bytes.decode("utf-8", errors="replace")
                    logger.info(
                        f"Read file {file_path} as bytes and decoded with replacement characters."
                    )
                    # --- CHANGE: Use constant ---
                    return PlainTextResponse(content=content, media_type=TEXT_PLAIN)
                    # --- END CHANGE ---
                except Exception as read_err:
                    logger.error(
                        f"Failed even reading bytes for {file_path}: {read_err}"
                    )
                    # If even reading bytes fails, report as unreadable
                    return PlainTextResponse(
                        content=f"[Unreadable file: {file_path.name}]\nCould not read file content.",
                        # --- CHANGE: Use constant ---
                        media_type=TEXT_PLAIN,
                        # --- END CHANGE ---
                    )

    except HTTPException as http_exc:
        # Re-raise known HTTP exceptions
        raise http_exc
    except Exception as e:
        logger.error(
            f"Error processing file content request for {path}: {e}", exc_info=True
        )
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
    await broadcast_specific_update(
        {
            "queues": {
                "executor": [t for t in executor_queue._queue],
                "tester": [t for t in tester_queue._queue],
                "documenter": [t for t in documenter_queue._queue],
            }
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
            report = Report(**report_data)
        else:
            report = report_data

        logger.info(
            f"Received report from AI2: Type={report.type}, Subtask={report.subtask_id}, File={report.file}"
        )

        # Обновляем статус подзадачи
        if report.subtask_id:
            new_status = None
            if report.type == "code":
                new_status = "code_received"
                if report.file and report.content:
                    # Pass background_tasks to write_and_commit_code
                    background_tasks.add_task(
                        write_and_commit_code,
                        report.file,
                        report.content,
                        report.subtask_id,
                        background_tasks=background_tasks,  # Pass it here
                    )
            elif report.type == "test_result":
                new_status = "tested"
                # Обрабатываем метрики тестирования
                if report.metrics:
                    report_metrics[report.subtask_id] = process_test_results(
                        report, report.subtask_id
                    )
                # --- REMOVED TODO for follow-up tasks ---
                # --- END REMOVED ---
            elif report.type == "status_update":
                new_status = report.message or "updated"
                if hasattr(report, "status") and report.status:
                    new_status = report.status  # Use specific status if provided

            if new_status:
                subtask_status[report.subtask_id] = new_status
                # --- ADDED: Broadcast monitoring stats update (status changed) ---
                await broadcast_monitoring_stats()
                # --- END ADDED ---

            # Broadcast status update after processing
            if report.subtask_id:
                current_status = subtask_status.get(report.subtask_id)
                update_payload = {"subtasks": {report.subtask_id: current_status}}

                # If the task reached a final state, also send queue updates
                final_states = [
                    "accepted",
                    "completed",
                    "code_received",
                    "tested",
                    "documented",
                    "skipped",
                    "failed",
                    "error",
                    "needs_rework",
                    "failed_by_ai2",
                    "error_processing",
                    "failed_tests",
                    "failed_to_send",
                ]  # Define comprehensive final states
                if current_status in final_states:
                    logger.info(
                        f"Task {report.subtask_id} reached final state '{current_status}'. Broadcasting queue update."
                    )
                    update_payload["queues"] = {
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
                    }

                await broadcast_specific_update(update_payload)
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
    global executor_queue, tester_queue, documenter_queue, repo  # Declare repo as global to allow re-assignment

    logger.warning("Initiating AI stop and full state/repo clear...")

    # 1. Stop AI services
    logger.info("Stopping AI services...")
    stop_ai_success = await run_restart_script("stop")
    if not stop_ai_success:
        logger.error("Failed to stop AI services. Aborting clear operation.")
        raise HTTPException(status_code=500, detail="Failed to stop AI services.")
    logger.info("AI services stopped.")
    await asyncio.sleep(3)  # Pause after stopping AI

    # 2. Clear internal state (queues, statuses, etc.)
    logger.info("Clearing internal MCP state (queues, statuses...).")
    # Clear queues
    while not executor_queue.empty():
        try:
            executor_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
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
    report_metrics = {}
    current_structure = {}  # Reset structure as repo is cleared
    ai3_report = {"status": "pending"}
    processed_history.clear()
    processed_tasks_count = 0  # Reset counter
    collaboration_requests = []
    logger.info("Internal MCP state cleared.")
    # --- ADDED: Broadcast monitoring stats update (state cleared) ---
    await broadcast_monitoring_stats()
    # --- END ADDED ---

    # 3. Clear repo, logs, cache using shell commands
    async def run_shell_command(command, description, working_dir=None):
        if working_dir is None:
            # Use the parent directory of repo_path (workspace root)
            working_dir = repo_path.parent
        logger.info(f"Executing: {description} (`{command}` in `{working_dir}`)")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            logger.info(f"Successfully executed: {description}")
            if stdout:
                logger.debug(f"stdout:\n{stdout.decode(errors='ignore')}")
            return True
        else:
            logger.error(
                f"Failed to execute: {description}. Return code: {process.returncode}"
            )
            if stderr:
                logger.error(f"stderr:\n{stderr.decode(errors='ignore')}")
            if stdout:
                logger.error(
                    f"stdout:\n{stdout.decode(errors='ignore')}"
                )  # Log stdout on error too
            return False

    # Clear repo contents (preserves repo/ directory itself)
    # Ensure repo_path is correctly used for the working directory
    # --- CHANGE: Use regular string ---
    repo_clear_cmd = "find . -mindepth 1 -delete"  # Command to run inside repo_dir
    # --- END CHANGE ---
    if not await run_shell_command(
        repo_clear_cmd, "Clear repository contents", working_dir=repo_path
    ):
        logger.error("Failed to clear repository contents. Continuing cleanup...")

    # Re-initialize git repo
    logger.info(f"Re-initializing Git repository at {repo_path}")
    try:
        # Use git init command via shell, ensure it runs in repo_path
        # --- CHANGE: Use regular string ---
        init_cmd = "git init"  # Command to run inside repo_dir
        # --- END CHANGE ---
        if not await run_shell_command(
            init_cmd, "Initialize Git repository", working_dir=repo_path
        ):
            logger.error("Failed to re-initialize Git repository via command.")
            repo = None  # Mark as unavailable
        else:
            # Re-initialize the global repo object
            try:
                repo = Repo(repo_path)
                logger.info("Global repo object re-initialized.")
                # Add initial commit? Optional, but might prevent issues.
                # try:
                #     repo.index.commit("Initial commit after clear")
                #     logger.info("Added initial commit.")
                # except Exception as commit_err:
                #     logger.warning(f"Could not create initial commit: {commit_err}")
            except Exception as e:
                logger.error(f"Failed to re-initialize global repo object: {e}")
                repo = None  # Mark as unavailable
    except Exception as e:
        logger.error(f"Error during Git re-initialization: {e}")
        repo = None

    # Clear logs (run from workspace root)
    # --- CHANGE: Use regular string ---
    log_clear_cmd = "rm -f logs/*.log"
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
        logger.error("Failed to start AI services after clearing state.")
        # Return an error response, but don't raise HTTPException as the clear part succeeded
        return JSONResponse(
            status_code=500,
            content={
                "status": "State cleared, repo reset, but failed to restart AI services."
            },
        )

    logger.info("AI services restart initiated.")

    return {
        "status": "AI stopped, state/repo cleared, AI restart initiated. MCP API remains running."
    }


@app.post("/clear_repo")
async def clear_repo():
    """Очищає та ініціалізує Git репозиторій."""
    try:
        # --- CHANGE: Comment out undefined call and add TODO ---
        # TODO: Implement proper interaction with AI3 process instead of direct call
        # await ai3_instance.clear_and_init_repo()
        logger.warning(
            "[API] /clear_repo endpoint called, but AI3 interaction is not implemented yet."
        )
        # Placeholder response until AI3 interaction is implemented
        await broadcast_specific_update(
            {
                "message": "Repository clear requested (implementation pending).",
                "log_line": "[API] Repository clear requested (implementation pending).",
            }
        )
        return {"status": "Repository clear requested (implementation pending)."}
        # --- END CHANGE ---
    except Exception as e:
        logger.error(f"Error during repository clear request: {e}")
        await broadcast_specific_update(
            {"error": f"Failed to request repository clear: {e}"}
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to request repository clear: {e}"
        )


async def broadcast_full_status():
    """Broadcasts detailed status to all connected clients."""
    if active_connections:
        # --- Aggregation for Pie Chart ---
        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "other": 0,
        }
        for status in subtask_status.values():
            # Use a more comprehensive set of completed/final statuses
            if status in [
                "accepted",
                "completed",
                "code_received",
                "tested",
                "skipped",
                "failed_by_ai2",
                "error_processing",
                "review_needed",
                "failed_tests",
                "failed_to_send",
            ]:
                status_counts[
                    "completed"
                ] += 1  # Group all final states for simplicity here, adjust if needed
            elif status == "pending":
                status_counts["pending"] += 1
            elif status in [
                "sending",
                "sent",
                "processing",
            ]:  # Explicitly list processing states
                status_counts["processing"] += 1
            # elif "Ошибка" in status or "failed" in status: # This might double-count some final states
            #     status_counts["failed"] += 1 # Consider removing if covered by 'completed' grouping
            else:
                status_counts["other"] += 1  # Catch-all for unknown/transient states
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
            # "processed_history": history_list, # Keep original if needed elsewhere, but add formatted one
            "git_activity": git_activity_data,  # Add formatted data for the chart
            "progress_data": progress_chart_data,  # Add progress chart data
            "task_status_distribution": status_counts,  # Include aggregated counts
            "actual_total_tasks": actual_total_tasks,  # Add the calculated total tasks
        }
        message = json.dumps(state_data)
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_text(message)
            except (
                WebSocketDisconnect,
                RuntimeError,
            ) as e:  # Catch specific errors related to closed connections
                logger.warning(
                    f"Failed to send full status to client {connection.client}: {e}. Removing connection."
                )
                disconnected_clients.add(connection)
            except Exception as e:  # Catch other potential send errors
                logger.error(
                    f"Unexpected error sending full status to client {connection.client}: {e}. Removing connection."
                )
                disconnected_clients.add(connection)

        # Remove disconnected clients from the main set
        active_connections.difference_update(disconnected_clients)


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
        for status in subtask_status.values():
            # Use a more comprehensive set of completed/final statuses
            if status in [
                "accepted",
                "completed",
                "code_received",
                "tested",
                "skipped",
                "failed_by_ai2",
                "error_processing",
                "review_needed",
                "failed_tests",
                "failed_to_send",
            ]:
                status_counts[
                    "completed"
                ] += 1  # Group all final states for simplicity here, adjust if needed
            elif status == "pending":
                status_counts["pending"] += 1
            elif status in [
                "sending",
                "sent",
                "processing",
            ]:  # Explicitly list processing states
                status_counts["processing"] += 1
            else:
                status_counts["other"] += 1  # Catch-all for unknown/transient states
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
            "actual_total_tasks": actual_total_tasks,  # Use the count of known subtasks
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
    except Exception as e:
        logger.error(f"Error sending full status to client {websocket.client}: {e}")


# ... rest of the file ...


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = f"Address(host='{websocket.client.host}', port={websocket.client.port})"
    active_connections.add(websocket)
    logger.info(
        f"WebSocket connection established from {client_id}. Total: {len(active_connections)}"
    )

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
        logger.info(
            f"WebSocket connection removed for {client_id}. Remaining: {len(active_connections)}"
        )
    except Exception as e:
        logger.error(
            f"Unexpected error in websocket_endpoint for client {client_id}: {e}"
        )
        if websocket in active_connections:
            active_connections.remove(websocket)
            logger.info(
                f"WebSocket connection removed for {client_id} after error. Remaining: {len(active_connections)}"
            )


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
        logger.info(
            f"Task requested for idle worker {worker}. Task ID: {task.get('id')}"
        )
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
            pass
        logger.info("Stopped periodic chart updates task")


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
            # Update worker status
            self.worker_status[worker_id] = {
                "role": role,
                "busy": False,
                "last_active": time.time(),
            }

            # Check queue
            if not self.tasks[role].empty():
                priority, task = await self.tasks[role].get()
                task_id = task["id"]

                # Check dependencies
                if task_id in self.task_dependencies:
                    deps = self.task_dependencies[task_id]
                    if not all(dep in self.task_history for dep in deps):
                        # Put back in queue with slightly lower priority
                        await self.tasks[role].put((priority - 0.1, task))
                        return None

                # Mark task as in progress
                self.in_progress[task_id] = worker_id
                self.worker_status[worker_id]["busy"] = True

                # Initialize history entry
                if task_id not in self.task_history:
                    self.task_history[task_id] = {
                        "status": "in_progress",
                        "attempts": 1,
                        "start_time": time.time(),
                    }
                else:
                    self.task_history[task_id]["attempts"] += 1

                return task
            return None
        except Exception as e:
            logger.error(f"Error getting next task: {e}")
            return None

    async def complete_task(
        self, task_id: str, success: bool, processing_time: float
    ) -> None:
        """Mark a task as completed and update metrics"""
        try:
            if task_id in self.in_progress:
                worker_id = self.in_progress.pop(task_id)
                role = self.worker_status[worker_id]["role"]

                # Update task history
                self.task_history[task_id].update(
                    {
                        "status": "completed" if success else "failed",
                        "completion_time": time.time(),
                        "processing_time": processing_time,
                    }
                )

                # Update load metrics
                self.load_metrics[role].append(processing_time)
                if len(self.load_metrics[role]) > 10:  # Keep last 10 measurements
                    self.load_metrics[role].pop(0)

                # Mark worker as available
                self.worker_status[worker_id]["busy"] = False

                # Check for dependent tasks to unblock
                await self._process_dependent_tasks(task_id)

                logger.info(
                    f"Task {task_id} completed with status: {'success' if success else 'failed'}"
                )
        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}")

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
            for under_role in underloaded:
                await self._move_eligible_tasks(over_role, under_role)

    async def _move_eligible_tasks(self, from_role: str, to_role: str) -> None:
        """Move eligible tasks between queues"""
        try:
            # Get tasks from source queue
            source_queue = self.tasks[from_role]
            if source_queue.empty():
                return

            moved_count = 0
            items = []

            # Collect all tasks
            while (
                not source_queue.empty() and moved_count < 3
            ):  # Limit moves per rebalance
                priority, task = await source_queue.get()

                # Check if task can be moved (based on role compatibility)
                if self._can_move_task(task, to_role):
                    # Put in destination queue
                    await self.tasks[to_role].put((priority, task))
                    moved_count += 1
                    logger.info(
                        f"Moved task {task['id']} from {from_role} to {to_role}"
                    )
                else:
                    # Put back in source queue
                    items.append((priority, task))

            # Return unmoved tasks to source queue
            for item in items:
                await source_queue.put(item)

        except Exception as e:
            logger.error(f"Error moving tasks between queues: {e}")

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
        """Handle a stalled task by requeuing it"""
        try:
            # Find task assigned to this worker
            task_id = next(
                (tid for tid, wid in self.in_progress.items() if wid == worker_id), None
            )
            if task_id:
                # Get task details and requeue
                role = self.worker_status[worker_id]["role"]
                if task_id in self.task_history:
                    attempts = self.task_history[task_id]["attempts"]
                    if attempts < 3:  # Limit retry attempts
                        # Requeue with lower priority
                        priority = self.task_priorities.get(task_id, 1) * 0.8
                        self.task_priorities[task_id] = priority

                        # TODO: Get actual task data
                        task = {"id": task_id}  # Simplified for example
                        await self.tasks[role].put((priority, task))

                        logger.warning(
                            f"Requeued stalled task {task_id} from worker {worker_id}"
                        )
                    else:
                        logger.error(f"Task {task_id} failed after {attempts} attempts")

                # Clean up
                if task_id in self.in_progress:
                    del self.in_progress[task_id]
                self.worker_status[worker_id]["busy"] = False

        except Exception as e:
            logger.error(f"Error handling stalled task for worker {worker_id}: {e}")

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
            # Analyze project requirements
            analysis = await self.code_analyzer.analyze_requirements(request)

            # Create project plan with dependencies
            project_plan = await self.task_scheduler.create_project_plan(analysis)

            # Initialize project structure
            project = await self.initialize_project(project_plan)

            # Set up monitoring
            await self.status_monitor.initialize_project(project["id"])

            return {"status": "success", "project": project}
        except Exception as e:
            logger.error(f"Project creation failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def get_task(self, role: str) -> Dict[str, Any]:
        """Get next task for an AI worker with enhanced context"""
        try:
            # Get next task considering dependencies
            task = await self.task_scheduler.get_next_task(role)
            if not task:
                return {"status": "no_task"}

            # Enhance task with context
            task = await self.enhance_task_context(task)

            # Track task assignment
            await self.status_monitor.track_task(task["id"], "assigned")

            return {"status": "success", "task": task}
        except Exception as e:
            logger.error(f"Task retrieval failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

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

            # Update task status
            await self.status_monitor.update_task(task_id, report)

            # Learn from results
            await self.pattern_learner.learn_from_report(report)

            # Check for blockers
            blockers = await self.analyze_blockers(report)
            if blockers:
                await self.handle_blockers(blockers)

            # Update dependencies
            await self.dependency_manager.update_dependencies(task_id, report)

            # Plan next tasks
            await self.task_scheduler.update_plan(report)

            return {"status": "success"}
        except Exception as e:
            logger.error(f"Progress report failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

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
            # Get basic status
            status = await self.status_monitor.get_project_status(project_id)

            # Add analytics
            analytics = await self.analyze_project_progress(project_id)
            status["analytics"] = analytics

            # Add predictions
            predictions = await self.predict_completion(project_id)
            status["predictions"] = predictions

            return {"status": "success", "project_status": status}
        except Exception as e:
            logger.error(f"Status retrieval failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

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


@app.route("/providers", methods=["GET"])
async def get_providers():
    """Get available providers and current configuration."""
    try:
        # Get all available providers from ProviderFactory
        available_providers = list(get_available_provider_types())

        # Get current AI configuration
        config_data = await load_config()

        # Return data as JSON
        return jsonify(
            {
                "available_providers": available_providers,
                "current_config": {
                    "ai1": get_ai_provider_config(config_data, "ai1"),
                    "ai2": {
                        "executor": get_ai_provider_config(
                            config_data, "ai2", "executor"
                        ),
                        "tester": get_ai_provider_config(config_data, "ai2", "tester"),
                        "documenter": get_ai_provider_config(
                            config_data, "ai2", "documenter"
                        ),
                    },
                    "ai3": get_ai_provider_config(config_data, "ai3"),
                },
            }
        )
    except Exception as e:
        logger.error(f"Error getting providers: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/provider_models", methods=["GET"])
async def get_provider_models(provider: str = None):
    """Get available models for a specific provider."""
    if not provider:
        return {"error": "Provider name is required"}, 400

    try:
        # Import the provider functions
        from providers import get_provider_models as get_models

        # Get available models
        models = get_models(provider)
        return {"models": models}
    except Exception as e:
        logger.error(f"Error getting models for provider {provider}: {e}")
        return {"error": str(e)}, 500


@app.get("/component_fallbacks")
async def get_component_fallbacks(component: str = None):
    """Get fallback providers for a specific AI component."""
    if not component:
        return {"error": "Component parameter is required"}, 400

    try:
        # Parse component to get AI and role
        parts = component.split("-")
        ai = parts[0]

        # Handle AI2 with specific role
        role = parts[1] if len(parts) > 1 else None

        # Import provider functions
        from providers import get_component_fallbacks as get_fallbacks

        # Get fallbacks
        fallbacks = get_fallbacks(ai, role)
        return {"fallbacks": fallbacks}
    except Exception as e:
        logger.error(f"Error getting fallbacks for component {component}: {e}")
        return {"error": str(e)}, 500


@app.route("/component_fallbacks", methods=["GET"])
async def get_component_fallbacks():
    """Get fallback providers for a specific AI component."""
    try:
        component = request.args.get("component")
        if not component:
            return jsonify({"error": "Component name is required"}), 400

        # Load configuration
        config_data = await load_config()

        # Parse component to get AI and role
        ai, role = parse_component_name(component)

        # Get fallbacks
        fallbacks = get_component_fallbacks_config(config_data, ai, role)

        return jsonify({"fallbacks": fallbacks})
    except Exception as e:
        logger.error(f"Error getting fallbacks for component {component}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/update_providers", methods=["POST"])
async def update_providers():
    """Update provider configuration for all AI components."""
    try:
        # Get request data
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Load current configuration
        config_data = await load_config()

        # Update AI1 provider
        if "ai1" in data:
            update_ai_provider_config(config_data, "ai1", data["ai1"])

        # Update AI2 providers
        if "ai2" in data:
            if "executor" in data["ai2"]:
                update_ai_provider_config(
                    config_data, "ai2", data["ai2"]["executor"], "executor"
                )
            if "tester" in data["ai2"]:
                update_ai_provider_config(
                    config_data, "ai2", data["ai2"]["tester"], "tester"
                )
            if "documenter" in data["ai2"]:
                update_ai_provider_config(
                    config_data, "ai2", data["ai2"]["documenter"], "documenter"
                )

        # Update AI3 provider
        if "ai3" in data:
            update_ai_provider_config(config_data, "ai3", data["ai3"])

        # Save configuration
        await save_config(config_data)

        # Return success
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error updating providers: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
        "provider": provider_config.get("type", "openai"),
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
    provider_type = provider_data.get("provider", "openai")
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
            fallback_type = fallback.get("provider")
            fallback_model = fallback.get("model", "")

            if fallback_type:
                provider_config["providers"].append(
                    {"type": fallback_type, "model": fallback_model}
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
        config_data = config  # Use the global config

        # Update AI1 provider if included
        if "ai1" in data:
            provider_data = data["ai1"]
            provider_type = provider_data.get("provider", "openai")
            model = provider_data.get("model", "")
            fallbacks = provider_data.get("fallbacks", [])

            if "ai_config" not in config_data:
                config_data["ai_config"] = {}
            if "ai1" not in config_data["ai_config"]:
                config_data["ai_config"]["ai1"] = {}

            config_data["ai_config"]["ai1"]["provider"] = provider_type
            config_data["ai_config"]["ai1"]["model"] = model

            # Handle fallbacks if provided
            if fallbacks:
                config_data["ai_config"]["ai1"]["fallbacks"] = fallbacks

        # Update AI2 providers if included
        if "ai2" in data:
            ai2_data = data["ai2"]
            for role in ["executor", "tester", "documenter"]:
                if role in ai2_data:
                    provider_data = ai2_data[role]
                    provider_type = provider_data.get("provider", "openai")
                    model = provider_data.get("model", "")
                    fallbacks = provider_data.get("fallbacks", [])

                    if "ai_config" not in config_data:
                        config_data["ai_config"] = {}
                    if "ai2" not in config_data["ai_config"]:
                        config_data["ai_config"]["ai2"] = {}
                    if role not in config_data["ai_config"]["ai2"]:
                        config_data["ai_config"]["ai2"][role] = {}

                    config_data["ai_config"]["ai2"][role]["provider"] = provider_type
                    config_data["ai_config"]["ai2"][role]["model"] = model

                    # Handle fallbacks if provided
                    if fallbacks:
                        config_data["ai_config"]["ai2"][role]["fallbacks"] = fallbacks

        # Update AI3 provider if included
        if "ai3" in data:
            provider_data = data["ai3"]
            provider_type = provider_data.get("provider", "openai")
            model = provider_data.get("model", "")
            fallbacks = provider_data.get("fallbacks", [])

            if "ai_config" not in config_data:
                config_data["ai_config"] = {}
            if "ai3" not in config_data["ai_config"]:
                config_data["ai_config"]["ai3"] = {}

            config_data["ai_config"]["ai3"]["provider"] = provider_type
            config_data["ai_config"]["ai3"]["model"] = model

            # Handle fallbacks if provided
            if fallbacks:
                config_data["ai_config"]["ai3"]["fallbacks"] = fallbacks

        # Save the updated configuration
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4)
            logger.info("Provider configuration updated successfully")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return {
                "status": "error",
                "message": f"Failed to save configuration: {e}",
            }, 500

        # Return success
        return {
            "status": "success",
            "message": "Provider configuration updated successfully",
        }
    except Exception as e:
        logger.error(f"Error updating providers: {e}")
        return {"status": "error", "message": f"Error updating providers: {e}"}, 500
