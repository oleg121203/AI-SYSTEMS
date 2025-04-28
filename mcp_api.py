import asyncio
import json
import logging
import os
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Union
from uuid import uuid4

import aiofiles
import git
import uvicorn
from dotenv import load_dotenv
from fastapi import (BackgroundTasks, FastAPI, HTTPException, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from providers import ProviderFactory  # Добавьте этот импорт, если его нет

load_dotenv()


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
    with open("config.json", "r", encoding="utf-8") as f:
        config_str = f.read()
    # Replace environment variables
    for key, value in os.environ.items():
        config_str = config_str.replace(f"${{{key}}}", value)
    config = json.loads(config_str)
except FileNotFoundError:
    logging.error("CRITICAL: config.json not found. Exiting.")
    exit(1)
except json.JSONDecodeError as e:
    logging.error(f"CRITICAL: Error decoding config.json: {e}. Exiting.")
    exit(1)
except Exception as e:
    logging.error(f"CRITICAL: Error loading configuration: {e}. Exiting.")
    exit(1)


# --- Logging Setup ---
log_file_path = config.get("log_file", "logs/app.log")
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
    async def emit(self, record):
        log_entry = self.format(record)
        await broadcast_specific_update({"log_line": log_entry})

# Configure the handler (do this after basicConfig)
ws_log_handler = WebSocketLogHandler()
ws_log_handler.setLevel(logging.INFO)  # Set desired level for WebSocket logs
formatter = logging.Formatter('%(asctime)s - %(levellevelname)s - %(message)s')  # Simpler format for UI
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
    repo = git.Repo(repo_path)
    logger.info(f"Initialized existing Git repository at {repo_path}")
except git.exc.InvalidGitRepositoryError:
    repo = git.Repo.init(repo_path)
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
ai_status: Dict[str, bool] = {"ai1": False, "ai2": False, "ai3": False}
ai_processes: Dict[str, Optional[subprocess.Popen]] = {
    "ai1": None,
    "ai2": None,
    "ai3": None,
}

# Set for storing active WebSocket connections
active_connections: Set[WebSocket] = set()

# Добавим блокировку для предотвращения гонок при записи файлов/коммитах
file_write_lock = asyncio.Lock()


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
        message = {"type": "specific_update", **update_data}
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_json(message)
            except WebSocketDisconnect:
                disconnected_clients.add(connection)
            except Exception as e:
                logger.error(f"Error sending specific update to {connection.client}: {e}")
                disconnected_clients.add(connection)
        for client in disconnected_clients:
            active_connections.discard(client)


async def write_and_commit_code(
    file_rel_path: str, content: str, subtask_id: Optional[str]
):
    """Helper function to write file content and commit changes."""
    global processed_tasks_count  # Доступ к глобальному счетчику
    async with file_write_lock:  # Используем блокировку
        if not is_safe_path(repo_path, file_rel_path):
            logger.error(
                f"[API-Write] Attempt to write to unsafe path denied: {file_rel_path}"
            )
            return False

        full_path = repo_path / file_rel_path
        try:
            # Ensure directory exists
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content using aiofiles
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)
            logger.info(
                f"[API-Write] Successfully wrote code to: {file_rel_path} (Subtask: {subtask_id})"
            )

            # Commit changes using gitpython
            if repo:
                try:
                    repo.index.add([str(full_path)])
                    commit_message = f"AI2 code update for {file_rel_path}"
                    if subtask_id:
                        commit_message += f" (Subtask: {subtask_id})"
                    if repo.is_dirty(index=True, working_tree=False):
                        repo.index.commit(commit_message)
                        logger.info(f"[API-Git] Committed changes for: {file_rel_path}")
                        # Обновляем историю после успешного коммита
                        processed_tasks_count += 1
                        processed_history.append(processed_tasks_count)
                        # Отправляем обновление истории коммитов
                        await broadcast_specific_update({"processed_over_time": list(processed_history)})
                    else:
                        logger.info(
                            f"[API-Git] No changes staged for commit for: {file_rel_path}"
                        )

                except git.GitCommandError as e:
                    logger.error(f"[API-Git] Error committing {file_rel_path}: {e}")
                    # Continue even if commit fails, file is written
                except Exception as e:
                    logger.error(
                        f"[API-Git] Unexpected error during commit for {file_rel_path}: {e}"
                    )

            return True
        except OSError as e:
            logger.error(f"[API-Write] Error writing file {full_path}: {e}")
            return False
        except Exception as e:
            logger.error(
                f"[API-Write] Unexpected error writing file {full_path}: {e}",
                exc_info=True,
            )
            return False


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
if os.path.exists(repo_path):
    try:
        current_structure = build_directory_structure(repo_path)
        logger.info(f"Initial file structure built from {repo_path}")
    except Exception as e:
        logger.error(f"Failed to build initial file structure: {e}")
        current_structure = {}  # Empty dict as fallback
else:
    logger.warning(f"Repository path {repo_path} does not exist, structure will be empty")
    current_structure = {}


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
                 media_type="text/plain"
             )

        # Attempt to read as text (UTF-8 first)
        try:
            content = file_path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read file as UTF-8: {file_path}")
            return PlainTextResponse(content=content, media_type="text/plain")
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode {file_path} as UTF-8. Trying fallback encodings.")
            try:
                # Try latin-1 as a common fallback
                content = file_path.read_text(encoding="latin-1")
                logger.info(f"Successfully read file {file_path} with latin-1 fallback.")
                return PlainTextResponse(content=content, media_type="text/plain")
            except Exception: # Catch potential errors reading with latin-1 too
                 logger.warning(f"Failed to decode {file_path} with latin-1. Reading bytes with replacement.")
                 try:
                     # Last resort: read bytes and decode with replacement characters
                     content_bytes = file_path.read_bytes()
                     content = content_bytes.decode("utf-8", errors="replace")
                     logger.info(f"Read file {file_path} as bytes and decoded with replacement characters.")
                     return PlainTextResponse(content=content, media_type="text/plain")
                 except Exception as read_err:
                     logger.error(f"Failed even reading bytes for {file_path}: {read_err}")
                     # If even reading bytes fails, report as unreadable
                     return PlainTextResponse(
                         content=f"[Unreadable file: {file_path.name}]\nCould not read file content.",
                         media_type="text/plain"
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
            elif report.type == "status_update":
                subtask_status[report.subtask_id] = report.message or "updated"
                if hasattr(report, "status") and report.status:
                    subtask_status[report.subtask_id] = report.status
            # Broadcast status update after processing
            if report.subtask_id:
                await broadcast_specific_update({"subtasks": {report.subtask_id: subtask_status.get(report.subtask_id)}})

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
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info(message)
            return {"status": "success", "message": message}
        except Exception as e:
            logger.error(f"Failed to write updated config.json: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to save updated configuration file."
            )
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
    if (
        "ai2_prompts" in data
        and isinstance(data["ai2_prompts"], list)
        and len(data["ai2_prompts"]) == 3
    ):
        if config.get("ai2_prompts") != data["ai2_prompts"]:
            config["ai2_prompts"] = data["ai2_prompts"]
            logger.info("AI2 prompts updated.")
            config_changed = True

    if "ai3_prompt" in data and config.get("ai3_prompt") != data["ai3_prompt"]:
        config["ai3_prompt"] = data["ai3_prompt"]
        logger.info("AI3 prompt updated.")
        config_changed = True

    if config_changed:
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            logger.info("Configuration file updated successfully.")
            return {"status": "config updated"}
        except Exception as e:
            logger.error(f"Failed to write updated config.json: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to save updated configuration file."
            )
    else:
        logger.info("No configuration changes detected in update request.")
        return {"status": "no changes detected"}


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


async def broadcast_full_status():
    """Broadcasts detailed status to all connected clients."""
    if active_connections:
        # --- Aggregation for Pie Chart ---
        status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "other": 0}
        for status in subtask_status.values():
            if status in ["accepted", "completed", "code_received", "tested"]:  # Consider these completed
                status_counts["completed"] += 1
            elif status == "pending":
                status_counts["pending"] += 1
            elif status == "processing":
                status_counts["processing"] += 1
            elif "Ошибка" in status or "failed" in status:  # Check for error strings
                status_counts["failed"] += 1
            else:
                status_counts["other"] += 1
        # --- End Aggregation ---

        state_data = {
            "type": "full_status_update",
            "ai_status": ai_status,
            "queues": {
                "executor": [
                    {
                        "id": t["id"],
                        "filename": t.get("filename", "N/A"),  # Add filename for summary
                        "text": t["text"],
                        "status": subtask_status.get(t["id"], "unknown"),
                    }
                    for t in list(executor_queue._queue)  # Convert deque to list for iteration
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
            "processed_over_time": list(processed_history),
            "task_status_distribution": status_counts  # Add aggregated data
        }
        logger.info(
            f"Broadcasting full status update: {state_data}"
        )  # Log full status for debugging
        for connection in active_connections:
            try:
                await connection.send_json(state_data)
            except WebSocketDisconnect:
                logger.info(
                    f"Client {connection.client} disconnected during broadcast."
                )
                active_connections.discard(
                    connection
                )  # Remove disconnected client immediately
            except Exception as e:
                logger.error(f"Error sending status to {connection.client}: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(
        f"WebSocket connection opened from {websocket.client}. Total: {len(active_connections)}"
    )
    try:
        await broadcast_full_status()  # Send initial full status

        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({"type": "ping"})
            except WebSocketDisconnect:
                logger.info(
                    f"WebSocket ping failed, client {websocket.client} likely disconnected."
                )
                break
            except Exception as e:
                logger.error(
                    f"Error sending ping to {websocket.client}: {e}"
                )  # Log ping errors

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected by client {websocket.client}")
    except Exception as e:
        logger.error(f"WebSocket error for {websocket.client}: {e}", exc_info=True)
    finally:
        active_connections.discard(websocket)
        logger.info(
            f"WebSocket connection closed for {websocket.client}. Total: {len(active_connections)}"
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


# --- Main Execution ---
if __name__ == "__main__":
    web_port = config.get("web_port", 7860)
    logger.info(f"Starting Uvicorn server on 0.0.0.0:{web_port}")
    uvicorn.run(app, host="0.0.0.0", port=web_port)
