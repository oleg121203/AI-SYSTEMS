import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4

import aiofiles
import aiohttp
import git
import uvicorn
import websockets
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import status as fastapi_status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from providers import ProviderFactory
from shutdown_handler import register_shutdown_handlers

load_dotenv()


# Define log_message function at the beginning of the file
def log_message(message: str):
    """Log a message to console and file"""
    logger.info(message)


def terminate_process(process):
    """Safely terminate a process"""
    if process and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


import aiofiles
import aiohttp
import git
import uvicorn
import websockets
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import status as fastapi_status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from providers import ProviderFactory
from shutdown_handler import register_shutdown_handlers

load_dotenv()


# --- Pydantic Models ---
class Report(BaseModel):
    type: str = Field(..., description="Report type (code, test_result, status_update)")
    file: Optional[str] = Field(
        None, description="Path to the file to update (for code)"
    )
    content: Optional[str] = Field(None, description="File content (for code)")
    subtask_id: Optional[str] = Field(
        None, description="ID of the subtask being executed"
    )
    metrics: Optional[Dict] = Field(
        None, description="Execution metrics (for test_result)"
    )
    message: Optional[str] = Field(None, description="Additional message")


# --- Configuration Loading ---
try:
    with open("config.json", "r", encoding="utf-8") as f:
        config_str = f.read()
    for key, value in os.environ.items():
        config_str = config_str.replace(f"${{{key}}}", value)
    config = json.loads(config_str)
except Exception as e:
    logging.error(f"CRITICAL: Error loading configuration: {e}. Exiting.")
    exit(1)

# --- Logging Setup ---
log_file_path = config.get("log_file", "logs/app.log")
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class WebSocketLogHandler(logging.Handler):
    async def emit(self, record):
        log_entry = self.format(record)
        await broadcast_specific_update({"log_line": log_entry})


ws_log_handler = WebSocketLogHandler()
ws_log_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levellevelname)s - %(message)s")
ws_log_handler.setFormatter(formatter)
logging.getLogger().addHandler(ws_log_handler)

# --- FastAPI App Setup ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Repository Setup ---
repo_dir = config.get("repo_dir", "repo")
repo_path = Path(repo_dir).resolve()
os.makedirs(repo_path, exist_ok=True)
try:
    repo = git.Repo(repo_path)
    logger.info(f"Initialized existing Git repository at {repo_path}")
except git.exc.InvalidGitRepositoryError:
    repo = git.Repo.init(repo_path)
    logger.info(f"Initialized new Git repository at {repo_path}")
except Exception as e:
    logger.error(f"Error initializing Git repository at {repo_path}: {e}")
    repo = None

# --- Global State ---
executor_queue = asyncio.Queue()
tester_queue = asyncio.Queue()
documenter_queue = asyncio.Queue()
subtask_status: Dict[str, str] = {}
report_metrics: Dict[str, Dict] = {}
current_structure: Dict = {}
ai3_report = {"status": "pending"}
processed_history = deque(maxlen=config.get("history_length", 20))
collaboration_requests: List[Dict] = []
processed_tasks_count = 0

ai_status: Dict[str, bool] = {"ai1": False, "ai2": False, "ai3": False}
ai_processes: Dict[str, Optional[subprocess.Popen]] = {
    "ai1": None,
    "ai2": None,
    "ai3": None,
}
active_connections: Set[WebSocket] = set()
file_write_lock = asyncio.Lock()

structure_files = []  # Список файлов из текущей структуры
AI1_API_URL = config.get("ai1_api_url", "http://127.0.0.1:8001")  # URL для API AI1


# --- Helper Functions ---
def is_safe_path(basedir, path_str):
    try:
        base_path = Path(basedir).resolve(strict=True)
        target_path = Path(basedir, path_str).resolve(strict=False)
        return target_path.is_relative_to(base_path)
    except Exception as e:
        logger.warning(f"Path safety check failed for '{path_str}' in '{basedir}': {e}")
        return False


def get_file_changes(repo_dir):
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_dir,
        )
        changes = [
            line.strip().split()[1]
            for line in result.stdout.strip().split("\n")
            if line
        ]
        return changes
    except Exception as e:
        logger.error(f"Error getting file changes: {e}")
        return []


async def broadcast_status():
    if active_connections:
        message = {"type": "status_update", "ai_status": ai_status}
        logger.debug(f"Broadcasting status: {message}")
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending status to {connection.client}: {e}")
                disconnected_clients.add(connection)
        for client in disconnected_clients:
            active_connections.discard(client)


async def broadcast_specific_update(update_data: dict):
    if active_connections:
        message = {"type": "specific_update", **update_data}
        # Avoid logging the full structure if it's too large
        log_message_content = message.copy()
        if "structure" in log_message_content and isinstance(
            log_message_content["structure"], dict
        ):
            log_message_content["structure"] = (
                f"Structure with {len(log_message_content['structure'])} keys"
            )
        if "log_line" in log_message_content:
            # Don't log the log line itself excessively here, it's already logged
            pass
        else:
            logger.debug(
                f"Broadcasting specific update to {len(active_connections)} clients: {log_message_content}"
            )

        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(
                    f"Error sending specific update to {connection.client}: {e}"
                )
                disconnected_clients.add(connection)
        for client in disconnected_clients:
            active_connections.discard(client)


async def write_and_commit_code(
    file_rel_path: str, content: str, subtask_id: Optional[str]
):
    global processed_tasks_count
    async with file_write_lock:
        if not is_safe_path(repo_path, file_rel_path):
            logger.error(f"[API-Write] Unsafe path denied: {file_rel_path}")
            return False

        full_path = repo_path / file_rel_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)
            logger.info(
                f"[API-Write] Wrote code to: {file_rel_path} (Subtask: {subtask_id})"
            )

            if repo:
                try:
                    repo.index.add([str(full_path)])
                    commit_message = f"AI2 code update for {file_rel_path}"
                    if subtask_id:
                        commit_message += f" (Subtask: {subtask_id})"
                    if repo.is_dirty(index=True, working_tree=False):
                        repo.index.commit(commit_message)
                        logger.info(f"[API-Git] Committed changes for: {file_rel_path}")
                        processed_tasks_count += 1
                        processed_history.append(processed_tasks_count)
                        await broadcast_specific_update(
                            {"processed_over_time": list(processed_history)}
                        )
                except Exception as e:
                    logger.error(f"[API-Git] Error committing {file_rel_path}: {e}")
            return True
        except Exception as e:
            logger.error(f"[API-Write] Error writing file {full_path}: {e}")
            return False


def process_test_results(test_data: Report, subtask_id: str):
    metrics = test_data.metrics or {}
    if not metrics:
        logger.warning(f"Empty metrics received for subtask {subtask_id}")
        return {"tests_passed": 0.0, "coverage": 0.0}
    return metrics


def add_task_to_queue(role: str, task: Dict):
    """
    Adds a task to the queue for the specified role.
    """
    queue = {
        "executor": executor_queue,
        "tester": tester_queue,
        "documenter": documenter_queue,
    }.get(role)

    if not queue:
        logger.error(f"Invalid role for task queue: {role}")
        return False

    # Add task to queue
    queue.put_nowait(task)
    subtask_status[task["id"]] = "pending"

    # Update UI via WebSocket
    asyncio.create_task(
        broadcast_specific_update(
            {
                "queues": {
                    "executor": list(executor_queue._queue),
                    "tester": list(tester_queue._queue),
                    "documenter": list(documenter_queue._queue),
                },
                "subtasks": {task["id"]: "pending"},
            }
        )
    )

    logger.info(
        f"Added task {task['id']} to {role} queue for file {task.get('filename')}"
    )
    return True


def get_all_tasks() -> List[Dict]:
    """
    Returns a list of all tasks (active and completed).
    """
    tasks = []
    # Collect tasks from queues
    for role, queue in [
        ("executor", executor_queue),
        ("tester", tester_queue),
        ("documenter", documenter_queue),
    ]:
        for task in list(queue._queue):
            task_copy = task.copy()
            task_copy["status"] = subtask_status.get(task["id"], "unknown")
            task_copy["role"] = role
            tasks.append(task_copy)

    # Add tasks that are not in queues but have status
    for subtask_id, status in subtask_status.items():
        # Check if this task is already in the list
        if not any(t.get("id") == subtask_id for t in tasks):
            # This is a task that is no longer in the queue (completed or extracted)
            tasks.append(
                {
                    "id": subtask_id,
                    "status": status,
                    # Other fields may be unavailable since the task is not in the queue
                }
            )

    return tasks


# --- API Endpoints ---
@app.get("/file_content", response_class=PlainTextResponse)
async def get_file_content(path: str):
    if not is_safe_path(repo_path, path):
        raise HTTPException(status_code=403, detail="Access denied: Unsafe path")
    file_path = repo_path / path
    try:
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        if file_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is a directory")
        return file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")


@app.get("/all_statuses")
async def get_all_statuses():
    """
    Returns statuses of all tasks.
    """
    all_tasks = get_all_tasks()
    return JSONResponse(
        content={"statuses": {task.get("id"): task.get("status") for task in all_tasks}}
    )


@app.post("/subtask")
async def receive_subtask(data: dict):
    subtask = data.get("subtask")
    if not subtask or not isinstance(subtask, dict):
        logger.error(f"Invalid subtask data: {data}")
        raise HTTPException(status_code=400, detail="Invalid subtask data format")

    subtask_id = subtask.get("id")
    role = subtask.get("role")
    filename = subtask.get("filename")
    text = subtask.get("text")

    if not all([subtask_id, role, filename, text]):
        logger.error(f"Missing fields in subtask: {subtask}")
        raise HTTPException(status_code=400, detail="Missing required fields")

    if role not in ["executor", "tester", "documenter"]:
        logger.error(f"Invalid role: {role}")
        raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

    if not is_safe_path(repo_path, filename):
        logger.warning(f"Unsafe path in subtask: {filename}")
        raise HTTPException(status_code=400, detail="Invalid filename")

    queue = {
        "executor": executor_queue,
        "tester": tester_queue,
        "documenter": documenter_queue,
    }[role]

    # Log information about the task being added
    logger.info(f"Adding to {role} queue: ID {subtask_id}, File: {filename}")

    # Check queue contents after adding
    await queue.put(subtask)
    subtask_status[subtask_id] = "pending"

    # Get all queue sizes for logging
    executor_size = executor_queue.qsize()
    tester_size = tester_queue.qsize()
    documenter_size = documenter_queue.qsize()

    logger.info(
        f"Queue status: executor({executor_size}), tester({tester_size}), documenter({documenter_size})"
    )
    logger.info(f"Subtask added to {role} queue: ID {subtask_id}, File: {filename}")

    await broadcast_specific_update(
        {
            "queues": {
                "executor": list(executor_queue._queue),
                "tester": list(tester_queue.__queue),
                "documenter": list(documenter_queue._queue),
            },
            "subtasks": {subtask_id: "pending"},
        }
    )
    return {"status": "subtask received", "id": subtask_id}


@app.get("/task/{role}")
async def get_task_for_role(role: str):
    queue = {
        "executor": executor_queue,
        "tester": tester_queue,
        "documenter": documenter_queue,
    }.get(role)
    if not queue:
        logger.error(f"Invalid role: {role}")
        raise HTTPException(status_code=400, detail="Invalid role")
    try:
        # Check if there are tasks in the queue
        if queue.empty():
            logger.warning(f"Queue for role {role} is empty")
            return {"message": f"No tasks available for {role}", "empty": True}

        subtask = queue.get_nowait()
        subtask_id = subtask.get("id")
        subtask_status[subtask_id] = "processing"
        logger.info(f"Assigned task ID {subtask_id} to {role}")
        await broadcast_specific_update(
            {
                "subtasks": {subtask_id: "processing"},
                "queues": {
                    "executor": list(executor_queue._queue),
                    "tester": list(tester_queue._queue),
                    "documenter": list(documenter_queue._queue),
                },
            }
        )
        return {"subtask": subtask}
    except asyncio.QueueEmpty:
        logger.warning(f"Queue for role {role} is empty (QueueEmpty)")
        return {"message": f"No tasks available for {role}", "empty": True}


@app.post("/structure")
async def receive_structure(data: dict):
    global current_structure
    structure_obj = data.get("structure")
    if not isinstance(structure_obj, dict):
        logger.error(f"Invalid structure data: {type(structure_obj)}")
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    current_structure = structure_obj
    logger.info(f"Structure updated by AI3: {list(current_structure.keys())}")

    # Обновляем список файлов из структуры
    update_structure_files()

    await broadcast_specific_update({"structure": current_structure})
    return {"status": "structure received"}


@app.get("/structure")
async def get_structure():
    return {"structure": current_structure}


@app.post("/report", status_code=200)
async def receive_report(
    report_data: Union[Report, Dict], background_tasks: BackgroundTasks
):
    try:
        report = Report(**report_data) if isinstance(report_data, dict) else report_data
        logger.info(f"Report from AI2: Type={report.type}, Subtask={report.subtask_id}")

        if report.subtask_id:
            if report.type == "code" and report.file and report.content:
                subtask_status[report.subtask_id] = "code_received"
                background_tasks.add_task(
                    write_and_commit_code,
                    report.file,
                    report.content,
                    report.subtask_id,
                )

                # Автоматично створюємо завдання для tester і documenter після отримання коду
                background_tasks.add_task(
                    create_followup_tasks,
                    report.file,
                    report.subtask_id,
                )

            elif report.type == "test_result":
                subtask_status[report.subtask_id] = "tested"
                if report.metrics:
                    report_metrics[report.subtask_id] = process_test_results(
                        report, report.subtask_id
                    )
            elif report.type == "status_update":
                subtask_status[report.subtask_id] = report.message or "updated"
            await broadcast_specific_update(
                {"subtasks": {report.subtask_id: subtask_status.get(report.subtask_id)}}
            )
        return {"status": "report received"}
    except Exception as e:
        logger.error(f"Error processing report: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing report: {e}")


@app.post("/start_all")
async def start_all():
    ai_status.update({"ai1": True, "ai2": True, "ai3": True})
    await broadcast_full_status()
    return {"status": "All AI systems started", "ai_status": ai_status}


@app.post("/stop_all")
async def stop_all():
    ai_status.update({"ai1": False, "ai2": False, "ai3": False})
    await broadcast_full_status()
    return {"status": "All AI systems stopped", "ai_status": ai_status}


@app.post("/clear")
async def clear_state():
    global subtask_status, report_metrics, current_structure, ai3_report, processed_history, collaboration_requests
    global executor_queue, tester_queue, documenter_queue
    logger.warning("Clearing application state")
    executor_queue = asyncio.Queue()
    tester_queue = asyncio.Queue()
    documenter_queue = asyncio.Queue()
    subtask_status.clear()
    report_metrics.clear()
    current_structure = {}
    ai3_report = {"status": "pending"}
    processed_history.clear()
    collaboration_requests.clear()
    try:
        with open(log_file_path, "w") as f:
            f.write("")
        logger.info(f"Cleared log file: {log_file_path}")
    except Exception as e:
        logger.error(f"Failed to clear log file: {e}")
    await broadcast_full_status()
    return {"status": "state cleared"}


async def broadcast_full_status():
    if active_connections:
        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "other": 0,
        }
        for status in subtask_status.values():
            if status in ["accepted", "completed", "code_received", "tested"]:
                status_counts["completed"] += 1
            elif status == "pending":
                status_counts["pending"] += 1
            elif status == "processing":
                status_counts["processing"] += 1
            elif "failed" in status.lower():
                status_counts["failed"] += 1
            else:
                status_counts["other"] += 1

        # Отримуємо актуальну структуру репозиторію за допомогою нової функції
        current_structure = get_repo_structure(str(repo_path))

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
            "progress": {
                "stages": ["Stage 1", "Stage 2", "Stage 3"],
                "values": [30, 60, 10],
            },
            "processed_over_time": list(processed_history),
            "task_status_distribution": status_counts,
        }
        logger.debug(f"Broadcasting full status: {state_data}")
        disconnected_clients = set()
        for connection in list(active_connections):
            try:
                await connection.send_json(state_data)
            except Exception as e:
                logger.error(f"Error sending status to {connection.client}: {e}")
                disconnected_clients.add(connection)
        for client in disconnected_clients:
            active_connections.discard(client)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"WebSocket connected: {websocket.client}")
    try:
        # Send initial full status upon connection
        await broadcast_full_status()

        # Обработка входящих сообщений от клиента
        while True:
            try:
                message = await websocket.receive_json()
                logger.debug(f"Received WebSocket message: {message}")

                action = message.get("action", "")

                if action == "get_full_status":
                    # Отправляем полный статус системы
                    await broadcast_full_status()

                elif action == "get_status":
                    # Отправляем только статус AI
                    await websocket.send_json(
                        {"type": "specific_update", "ai_status": ai_status}
                    )

                elif action == "get_queues":
                    # Отправляем данные о очередях задач
                    await websocket.send_json(
                        {
                            "type": "specific_update",
                            "queues": {
                                "executor": [
                                    {
                                        "id": t["id"],
                                        "filename": t.get("filename", "N/A"),
                                        "text": t["text"],
                                        "status": subtask_status.get(
                                            t["id"], "unknown"
                                        ),
                                    }
                                    for t in list(executor_queue._queue)
                                ],
                                "tester": [
                                    {
                                        "id": t["id"],
                                        "filename": t.get("filename", "N/A"),
                                        "text": t["text"],
                                        "status": subtask_status.get(
                                            t["id"], "unknown"
                                        ),
                                    }
                                    for t in list(tester_queue._queue)
                                ],
                                "documenter": [
                                    {
                                        "id": t["id"],
                                        "filename": t.get("filename", "N/A"),
                                        "text": t["text"],
                                        "status": subtask_status.get(
                                            t["id"], "unknown"
                                        ),
                                    }
                                    for t in list(documenter_queue._queue)
                                ],
                            },
                        }
                    )

                elif action == "get_structure":
                    # Отправляем структуру проекта
                    await websocket.send_json(
                        {"type": "specific_update", "structure": current_structure}
                    )

                elif action == "refresh_data":
                    # Обновляем все данные
                    await broadcast_full_status()

                elif action == "ping":
                    # Просто отвечаем на пинг
                    await websocket.send_json({"type": "pong"})

                else:
                    logger.warning(f"Unknown WebSocket action: {action}")
                    await websocket.send_json(
                        {"type": "error", "message": f"Unknown action: {action}"}
                    )

            except WebSocketDisconnect:
                logger.info(
                    f"WebSocket disconnected during message processing: {websocket.client}"
                )
                break
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from {websocket.client}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}", exc_info=True)

        # Keep connection alive with pings and handle potential disconnects
        while True:
            await asyncio.sleep(30)  # Keepalive interval
            try:
                # Check connection state before sending (updated logic)
                if websocket.application_state == WebSocketState.CONNECTED:
                    await websocket.send_json({"type": "ping"})
                else:
                    logger.warning(
                        f"WebSocket {websocket.client} state is not CONNECTED, skipping ping."
                    )
                    break  # Exit loop if not connected
            except (WebSocketDisconnect, RuntimeError) as e:
                # Catch disconnect or runtime error if send is attempted on closed socket
                logger.warning(
                    f"WebSocket {websocket.client} disconnected or error during ping: {e}"
                )
                break  # Exit the loop to allow cleanup
    except WebSocketDisconnect:
        # This catches disconnects that happen outside the ping loop (e.g., during accept or initial broadcast)
        logger.info(
            f"WebSocket disconnected: {websocket.client} (during main loop or initial phase)"
        )
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(
            f"Unexpected error in WebSocket handler for {websocket.client}: {e}",
            exc_info=True,
        )
    finally:
        # Ensure the connection is removed from the active set on any exit path
        active_connections.discard(websocket)
        logger.info(f"WebSocket connection cleanup for {websocket.client}")


@app.get("/")
async def dashboard(request: Request):
    processed_tasks = len(
        [
            s
            for s in subtask_status.values()
            if s in ["accepted", "completed", "code_received"]
        ]
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "processed_tasks": processed_tasks,
            "executor_queue_size": executor_queue.qsize(),
            "tester_queue_size": tester_queue.qsize(),
            "documenter_queue_size": documenter_queue.qsize(),
            "target": config.get("target", "Target not set"),
            "structure": current_structure,
            "config": config,
        },
    )


@app.get("/health", status_code=fastapi_status.HTTP_200_OK)
async def health_check():
    """Простий ендпоінт для перевірки стану сервісу."""
    return {"status": "ok"}


@app.post("/request_task_for_idle_worker")
async def request_task_for_idle_worker(request: Request) -> JSONResponse:
    """
    Обрабатывает запрос на создание новой задачи для простаивающего работника.
    Этот эндпоинт вызывается AI3, когда он обнаруживает, что работник простаивает.
    """
    try:
        data = await request.json()
        role = data.get("role")
        reason = data.get("reason", "worker_idle")

        if not role:
            logger.warning("Received request for idle worker but no role specified")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Role is required"},
            )

        if role not in ["executor", "tester", "documenter"]:
            logger.warning(f"Received request for invalid role: {role}")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Invalid role: {role}"},
            )

        logger.info(
            f"Received request to create task for idle {role}. Reason: {reason}"
        )

        # Проверяем, есть ли файлы, ожидающие обработки этой ролью
        if role == "executor":
            # Для исполнителя проверяем, есть ли файлы в ожидании
            pending_files = get_pending_files_for_role("executor")
            if pending_files:
                # Берем первый файл из ожидающих
                file_to_process = pending_files[0]
                # Создаем задачу для этого файла
                task_details = create_task_for_file(file_to_process, role)
                return JSONResponse(
                    content={
                        "status": "success",
                        "message": f"Created task for idle {role}",
                        "task": task_details,
                    }
                )
        elif role == "tester":
            # Для тестировщика ищем файлы, готовые для тестирования
            completed_files = get_completed_files_without_tests()
            if completed_files:
                file_to_test = completed_files[0]
                task_details = create_task_for_file(file_to_test, role)
                return JSONResponse(
                    content={
                        "status": "success",
                        "message": f"Created testing task for {file_to_test}",
                        "task": task_details,
                    }
                )
        elif role == "documenter":
            # Для документатора ищем файлы, готовые для документирования
            completed_files = get_completed_files_without_docs()
            if completed_files:
                file_to_document = completed_files[0]
                task_details = create_task_for_file(file_to_document, role)
                return JSONResponse(
                    content={
                        "status": "success",
                        "message": f"Created documentation task for {file_to_document}",
                        "task": task_details,
                    }
                )

        # Если не нашли подходящих задач, возвращаем информацию
        logger.info(f"No pending tasks for idle {role} worker")
        return JSONResponse(
            content={
                "status": "info",
                "message": f"No pending tasks for idle {role} worker",
            }
        )

    except Exception as e:
        logger.error(f"Error handling request for idle worker: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal error: {str(e)}"},
        )


@app.post("/request_error_fix")
async def request_error_fix(request: Request) -> JSONResponse:
    """
    Обрабатывает запрос на исправление ошибки, обнаруженной AI3 в логах.
    """
    try:
        data = await request.json()
        error_text = data.get("error_text")
        log_file = data.get("log_file")
        role = data.get("role")

        if not error_text:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Error text is required"},
            )

        logger.info(
            f"Received request to fix error from {log_file}{' for '+role if role else ''}"
        )

        # Извлекаем подробности об ошибке из текста лога
        error_details = extract_error_details(error_text, log_file)

        # Если смогли определить файл, связанный с ошибкой
        if error_details.get("file"):
            file_to_fix = error_details["file"]
            task_details = create_error_fix_task(file_to_fix, error_text, role)
            # Отправляем запрос в AI1 для создания задачи на исправление
            await notify_ai1_about_error(error_details)
            return JSONResponse(
                content={
                    "status": "success",
                    "message": f"Created error fix task for {file_to_fix}",
                    "task": task_details,
                }
            )
        else:
            logger.warning(
                f"Could not determine file associated with error: {error_text}"
            )
            return JSONResponse(
                content={
                    "status": "warning",
                    "message": "Could not determine file associated with error",
                }
            )

    except Exception as e:
        logger.error(f"Error handling error fix request: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal error: {str(e)}"},
        )


def get_pending_files_for_role(role: str) -> List[str]:
    """
    Возвращает список файлов, ожидающих обработки указанной ролью.
    """
    pending_files = []
    try:
        if role == "executor":
            # Логика пошуку файлів для виконавця
            for file_path in structure_files:
                if file_path not in [
                    task["filename"]
                    for task in get_all_tasks()
                    if task.get("role") == "executor"
                ]:
                    pending_files.append(file_path)
        elif role == "tester":
            # Логика пошуку файлів для тестувальника
            pending_files = get_completed_files_without_tests()
        elif role == "documenter":
            # Логика пошуку файлів для документатора
            pending_files = get_completed_files_without_docs()

        logger.debug(
            f"Found {len(pending_files)} pending files for role {role}: {pending_files[:5]}"
        )
        return pending_files
    except Exception as e:
        logger.error(f"Error getting pending files for {role}: {e}")
        return []


def get_completed_files_without_tests() -> List[str]:
    """
    Возвращает список файлов, для которых код готов, но тесты еще не созданы.
    """
    try:
        all_tasks = get_all_tasks()
        completed_executor_files = [
            task["filename"]
            for task in all_tasks
            if task.get("role") == "executor"
            and task.get("status") in ["completed", "code_received", "accepted"]
        ]

        tested_files = [
            task["filename"]
            for task in all_tasks
            if task.get("role") == "tester"
            and task.get("status") in ["completed", "accepted"]
        ]

        return [file for file in completed_executor_files if file not in tested_files]
    except Exception as e:
        logger.error(f"Error getting files without tests: {e}")
        return []


def get_completed_files_without_docs() -> List[str]:
    """
    Возвращает список файлов, для которых код готов, но документация еще не создана.
    """
    try:
        all_tasks = get_all_tasks()
        completed_executor_files = [
            task["filename"]
            for task in all_tasks
            if task.get("role") == "executor"
            and task.get("status") in ["completed", "code_received", "accepted"]
        ]

        documented_files = [
            task["filename"]
            for task in all_tasks
            if task.get("role") == "documenter"
            and task.get("status") in ["completed", "accepted"]
        ]

        return [
            file for file in completed_executor_files if file not in documented_files
        ]
    except Exception as e:
        logger.error(f"Error getting files without docs: {e}")
        return []


def create_task_for_file(file_path: str, role: str) -> Dict[str, Any]:
    """
    Создает новую задачу для указанного файла и роли.
    """
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "filename": file_path,
        "role": role,
    }

    if role == "executor":
        task["text"] = (
            f"Implement the required functionality in file: {file_path} based on the project goals."
        )
    elif role == "tester":
        task["text"] = f"Generate unit tests for the code in file: {file_path}."
    elif role == "documenter":
        task["text"] = f"Generate documentation for the code in file: {file_path}."

    # Получаем код файла для тестировщика и документатора
    if role in ["tester", "documenter"]:
        file_content = get_file_content(file_path)
        if file_content:
            task["code"] = file_content

    # Добавляем задачу в соответствующую очередь
    add_task_to_queue(role, task)
    logger.info(
        f"Created new task for idle {role} worker: {task_id} for file {file_path}"
    )

    return task


def extract_error_details(error_text: str, log_file: str) -> Dict[str, Any]:
    """
    Извлекает детали об ошибке из текста лога.
    """
    details = {
        "log_file": log_file,
        "error_text": error_text,
        "timestamp": datetime.now().isoformat(),
    }

    # Ищем имя файла в тексте ошибки
    file_pattern = re.compile(r'file[:\s]+[\'"](.*?)[\'"]', re.IGNORECASE)
    file_match = file_pattern.search(error_text)

    if file_match:
        details["file"] = file_match.group(1)
    else:
        # Пробуем другой паттерн
        file_pattern2 = re.compile(
            r'[\'"]([^\'"\s]+\.(py|js|ts|html|css|json))[\'"]', re.IGNORECASE
        )
        file_match2 = file_pattern2.search(error_text)
        if file_match2:
            details["file"] = file_match2.group(1)

    # Определяем тип ошибки
    if "test failed" in error_text.lower() or "failed test" in error_text.lower():
        details["error_type"] = "test_failure"
    elif "error" in error_text.lower():
        details["error_type"] = "runtime_error"
    elif "warning" in error_text.lower():
        details["error_type"] = "warning"
    else:
        details["error_type"] = "unknown"

    return details


def create_error_fix_task(
    file_path: str, error_text: str, role: str = None
) -> Dict[str, Any]:
    """
    Создает задачу на исправление ошибки.
    """
    task_id = str(uuid.uuid4())
    assigned_role = (
        role if role else "executor"
    )  # По умолчанию назначаем ошибку исполнителю

    task = {
        "id": task_id,
        "filename": file_path,
        "role": assigned_role,
        "text": f"Fix error in file {file_path}. Error details: {error_text}",
        "priority": "high",  # Задачам исправления ошибок даем высокий приоритет
        "error_fix": True,
    }

    # Получаем текущий код файла
    file_content = get_file_content(file_path)
    if file_content:
        task["code"] = file_content

    # Добавляем задачу в соответствующую очередь
    add_task_to_queue(assigned_role, task)

    logger.info(
        f"Created error fix task {task_id} for file {file_path}, assigned to {assigned_role}"
    )

    return task


async def notify_ai1_about_error(error_details: Dict[str, Any]):
    """
    Уведомляет AI1 о необходимости создать задачу на исправление ошибки.
    """
    try:
        api_url = (
            f"{AI1_API_URL}/error_notification"
            if AI1_API_URL
            else "http://127.0.0.1:8001/error_notification"
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url, json=error_details, timeout=10
            ) as response:
                if response.status == 200:
                    logger.info(
                        f"Successfully notified AI1 about error in {error_details.get('file')}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Failed to notify AI1 about error. Status: {response.status}"
                    )
                    return False
    except Exception as e:
        logger.error(f"Error notifying AI1 about error: {e}")
        return False


# Добавим функцию для обновления списка файлов из структуры
def update_structure_files():
    """
    Updates the list of files based on the current project structure.
    """
    global structure_files
    structure_files = []

    def extract_files(struct, prefix=""):
        if isinstance(struct, dict):
            for key, value in struct.items():
                path = f"{prefix}/{key}" if prefix else key
                if isinstance(value, dict):
                    # Recursive call to process nested directories
                    extract_files(value, path)
                else:  # This is a file (value may be None or "")
                    structure_files.append(path)

    # Check that the structure contains data
    if current_structure and isinstance(current_structure, dict):
        extract_files(current_structure)
        logger.info(f"Updated file list: found {len(structure_files)} files")
    else:
        logger.warning("Project structure is empty or invalid")

    return structure_files


@app.post("/consult_task_structure")
async def consult_task_structure(request: Request) -> JSONResponse:
    """
    Эндпоинт для консультации AI1 с AI3 (дозором) по структуре задач.
    AI3 рассматривает структуру задач и предлагает улучшения.
    """
    try:
        data = await request.json()
        task_structure = data.get("task_structure", {})
        target = data.get("target", "")

        if not task_structure:
            logger.warning("Received empty task structure for consultation")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Task structure is required"},
            )

        logger.info(
            f"AI1 запрашивает консультацию по структуре задач: {len(task_structure.get('main_tasks', []))} основных задач"
        )

        # Отправляем запрос к AI3 для анализа структуры задач
        recommendations = await request_ai3_consultation(
            task_structure, target, "task_structure"
        )

        # Базовое улучшение структуры
        improved_structure = task_structure.copy()

        # Если AI3 предоставил рекомендации по улучшению структуры, применяем их
        if recommendations.get("improved_structure"):
            improved_structure = recommendations.get("improved_structure")
            logger.info(f"Структура задач улучшена на основе рекомендаций AI3")

        return JSONResponse(
            content={
                "status": "success",
                "improved_structure": improved_structure,
                "recommendations": recommendations.get("recommendations", []),
            }
        )

    except Exception as e:
        logger.error(f"Ошибка при консультации по структуре задач: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal error: {str(e)}"},
        )


@app.post("/consult_subtasks")
async def consult_subtasks(request: Request) -> JSONResponse:
    """
    Эндпоинт для консультации AI1 с AI3 (дозором) по микрозадачам.
    AI3 анализирует микрозадачи и предлагает улучшения.
    """
    try:
        data = await request.json()
        main_task_id = data.get("main_task_id", "")
        subtasks = data.get("subtasks", [])
        target = data.get("target", "")

        if not subtasks:
            logger.warning("Received empty subtasks list for consultation")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Subtasks are required"},
            )

        logger.info(
            f"AI1 запрашивает консультацию по микрозадачам для основной задачи {main_task_id}: {len(subtasks)} микрозадач"
        )

        # Отправляем запрос к AI3 для анализа микрозадач
        recommendations = await request_ai3_consultation(
            {"main_task_id": main_task_id, "subtasks": subtasks}, target, "subtasks"
        )

        # Базовое улучшение (если AI3 не предоставил улучшений)
        improved_subtasks = subtasks

        # Если AI3 предоставил улучшенные микрозадачи, используем их
        if recommendations.get("improved_subtasks"):
            improved_subtasks = recommendations.get("improved_subtasks")
            logger.info(f"Микрозадачи улучшены на основе рекомендаций AI3")

        return JSONResponse(
            content={
                "status": "success",
                "improved_subtasks": improved_subtasks,
                "recommendations": recommendations.get("recommendations", []),
            }
        )

    except Exception as e:
        logger.error(f"Ошибка при консультации по микрозадачам: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal error: {str(e)}"},
        )


async def request_ai3_consultation(
    data: Dict, target: str, consultation_type: str
) -> Dict:
    try:
        logger.info(f"Отправка запроса консультации к AI3: {consultation_type}")

        request_data = {
            "consultation_type": consultation_type,
            "data": data,
            "target": target,
        }

        # Используем локальную функцию для получения рекомендаций
        return generate_basic_recommendations(data, consultation_type)

    except Exception as e:
        logger.error(f"Ошибка при запросе рекомендаций от AI3: {e}")
        # В случае ошибки возвращаем базовые рекомендации
        return generate_basic_recommendations(data, consultation_type)


def generate_basic_recommendations(data: Dict, consultation_type: str) -> Dict:
    """
    Генерирует базовые рекомендации, если AI3 недоступен.

    Args:
        data: Данные для анализа
        consultation_type: Тип консультации

    Returns:
        Dict с базовыми рекомендациями
    """
    result = {"recommendations": []}

    if consultation_type == "task_structure":
        # Базовые рекомендации для структуры задач
        result["recommendations"] = [
            "Рекомендуется начать с разработки основных компонентов системы",
            "Обратите внимание на зависимости между компонентами",
            "Сначала реализуйте базовую инфраструктуру, затем бизнес-логику",
        ]
    elif consultation_type == "subtasks":
        # Базовые рекомендации для микрозадач
        result["recommendations"] = [
            "Разбейте работу над файлом на отдельные логические блоки",
            "Тестируйте каждый блок отдельно перед интеграцией",
            "Документируйте интерфейсы и API для облегчения интеграции",
        ]

    logger.info(
        f"Сгенерированы базовые рекомендации для {consultation_type} из-за недоступности AI3"
    )
    return result


@app.post("/test_recommendation")
async def receive_test_recommendation(request: Request) -> JSONResponse:
    """
    Принимает рекомендации от AI3 по результатам тестов GitHub Actions.
    Перенаправляет рекомендации к AI1 для принятия окончательного решения.
    """
    try:
        data = await request.json()

        run_id = data.get("run_id")
        result = data.get("result")
        files = data.get("files", [])
        recommendation = data.get("recommendation")

        if not run_id or not result:
            logger.error("Получены некорректные данные о результатах тестов")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Некорректные данные о тестах"},
            )

        logger.info(
            f"Получены результаты тестов GitHub Actions: run_id={run_id}, результат={result}"
        )
        logger.info(f"Рекомендация AI3: {recommendation}")

        # Отправляем информацию о тестах к AI1 для принятия решения
        await forward_test_results_to_ai1(data)

        # Обновляем статусы задач на основе результатов тестов
        for file_info in files:
            source_file = file_info.get("source_file")
            test_file = file_info.get("test_file")

            if source_file:
                test_status = "passed" if result == "success" else "failed"
                await update_file_test_status(source_file, test_status, run_id)

        # Отправляем обновление клиентам через WebSocket
        await broadcast_specific_update(
            {
                "test_result": {
                    "run_id": run_id,
                    "result": result,
                    "files": [f["source_file"] for f in files if "source_file" in f],
                    "timestamp": datetime.now().isoformat(),
                }
            }
        )

        return JSONResponse(
            content={"status": "success", "message": "Рекомендация по тестам получена"}
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке рекомендации по тестам: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Внутренняя ошибка: {str(e)}"},
        )


async def update_file_test_status(file_path: str, status: str, run_id: str):
    """
    Обновляет статус теста для файла.
    """
    try:
        # Находим все задачи, связанные с этим файлом
        all_tasks = get_all_tasks()
        for task in all_tasks:
            if task.get("filename") == file_path and task.get("role") == "tester":
                subtask_id = task.get("id")
                if subtask_id:
                    old_status = subtask_status.get(subtask_id, "unknown")

                    # Устанавливаем новый статус на основе результата теста
                    new_status = "completed" if status == "passed" else "failed_tests"

                    logger.info(
                        f"Обновление статуса задачи {subtask_id} для файла {file_path}: {old_status} -> {new_status}"
                    )
                    subtask_status[subtask_id] = new_status

                    # Добавляем информацию о запуске GitHub Actions
                    if not hasattr(task, "test_runs"):
                        task["test_runs"] = []

                    task["test_runs"].append(
                        {
                            "run_id": run_id,
                            "status": status,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

                    # Отправляем обновление клиентам
                    await broadcast_specific_update(
                        {"subtasks": {subtask_id: new_status}}
                    )

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса теста для {file_path}: {e}")


async def forward_test_results_to_ai1(test_data: Dict):
    """
    Отправляет результаты тестов в AI1 для принятия решения.
    """
    try:
        api_url = f"{AI1_API_URL}/test_result"
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=test_data, timeout=30) as response:
                if response.status == 200:
                    logger.info(f"Результаты тестов успешно отправлены в AI1")
                    return True
                else:
                    logger.error(
                        f"Ошибка отправки результатов тестов в AI1. Статус: {response.status}"
                    )
                    return False
    except Exception as e:
        logger.error(f"Ошибка при пересылке результатов тестов в AI1: {e}")
        return False


@app.post("/clear_project")
async def clear_project():
    """
    Повністю очищує проект, включаючи репозиторій, логи, кеш та інші дані
    """
    global repo  # Объявление глобальной переменной перед использованием
    try:
        log_message("[API] Запит на повне очищення проекту отримано")

        # Зупиняємо всі процеси, якщо вони запущені
        if "ai1_process" in globals() and ai1_process and ai1_process.poll() is None:
            log_message("[API] Зупинка AI1 перед очищенням")
            terminate_process(ai1_process)

        if (
            "ai2_executor_process" in globals()
            and ai2_executor_process
            and ai2_executor_process.poll() is None
        ):
            log_message("[API] Зупинка AI2-executor перед очищенням")
            terminate_process(ai2_executor_process)

        if (
            "ai2_tester_process" in globals()
            and ai2_tester_process
            and ai2_tester_process.poll() is None
        ):
            log_message("[API] Зупинка AI2-tester перед очищенням")
            terminate_process(ai2_tester_process)

        if (
            "ai2_documenter_process" in globals()
            and ai2_documenter_process
            and ai2_documenter_process.poll() is None
        ):
            log_message("[API] Зупинка AI2-documenter перед очищенням")
            terminate_process(ai2_documenter_process)

        if "ai3_process" in globals() in ai3_process in ai3_process.poll() is None:
            log_message("[API] Зупинка AI3 перед очищенням")
            terminate_process(ai3_process)

        # Чекаємо, щоб переконатися, що всі процеси зупинилися
        await asyncio.sleep(2)

        # Очищаємо репозиторій - видаляємо та ініціалізуємо заново
        repo_dir = config.get("repo_dir", "repo")
        log_message(f"[API] Очищення репозиторію в: {repo_dir}")

        # Видаляємо репозиторій, якщо він існує
        if os.path.exists(repo_dir):
            try:
                # Переконаємося, що це дійсно директорія repo перед видаленням
                if ос.path.basename(os.path.normpath(repo_dir)) == "repo":
                    # Видаляємо всі файли, включаючи .git
                    for root, dirs, files in os.walk(repo_dir, topdown=False):
                        for name in files:
                            try:
                                file_path = os.path.join(root, name)
                                os.chmod(file_path, 0o777)  # Додаємо всі права на файл
                                os.remove(file_path)
                                log_message(f"[API] Видалено файл: {file_path}")
                            except Exception as e:
                                log_message(
                                    f"[API] Помилка при видаленні файлу {file_path}: {e}"
                                )

                        for name in dirs:
                            try:
                                dir_path = os.path.join(root, name)
                                os.chmod(
                                    dir_path, 0o777
                                )  # Додаємо всі права на директорію
                                shutil.rmtree(dir_path, onerror=handle_readonly_error)
                                log_message(f"[API] Видалено директорію: {dir_path}")
                            except Exception as e:
                                log_message(
                                    f"[API] Помилка при видаленні директорії {dir_path}: {e}"
                                )

                    # Тепер ініціалізуємо Git репозиторій заново
                    try:
                        import git

                        git.Repo.init(repo_dir)
                        log_message(
                            "[API] Git репозиторій успішно ініціалізовано заново"
                        )

                        # Створюємо базовий README.md
                        readme_path = os.path.join(repo_dir, "README.md")
                        with open(readme_path, "w") as f:
                            f.write(
                                "# Проект\n\nЦей репозиторій створено системою AI-SYSTEMS.\n"
                            )

                        # Комітимо базовий README.md
                        repo = git.Repo(repo_dir)
                        repo.git.add(readme_path)
                        repo.git.commit("-m", "Initial commit with README.md")
                        log_message("[API] Створено та закомічено базовий README.md")
                    except Exception as e:
                        log_message(
                            f"[API] Помилка при ініціалізації Git репозиторію: {e}"
                        )
                else:
                    log_message(
                        "[API] Безпека: відмовлено у видаленні директорії, що не є 'repo'"
                    )
            except Exception as e:
                log_message(f"[API] Помилка при видаленні репозиторію: {e}")
        else:
            # Створюємо нову директорію для репозиторію
            os.makedirs(repo_dir, exist_ok=True)
            log_message(f"[API] Створено нову директорію для репозиторію: {repo_dir}")

            # Ініціалізуємо Git репозиторій
            try:
                import git

                git.Repo.init(repo_dir)
                log_message("[API] Git репозиторій успішно ініціалізовано")

                # Створюємо базовий README.md
                readme_path = os.path.join(repo_dir, "README.md")
                with open(readme_path, "w") as f:
                    f.write(
                        "# Проект\n\nЦей репозиторій створено системою AI-SYSTEMS.\n"
                    )

                # Комітимо базовий README.md
                repo = git.Repo(repo_dir)
                repo.git.add(readme_path)
                repo.git.commit("-m", "Initial commit with README.md")
                log_message("[API] Створено та закомічено базовий README.md")
            except Exception as e:
                log_message(f"[API] Помилка при ініціалізації Git репозиторію: {e}")

        # Очищаємо директорію з логами
        logs_dir = "logs"
        log_message(f"[API] Очищення логів в: {logs_dir}")

        # Очищаємо файли логів, але не видаляємо саму директорію
        if ос.path.exists(logs_dir):
            for log_file in ос.listdir(logs_dir):
                log_path = os.path.join(logs_dir, log_file)
                try:
                    # Перевіряємо, чи це файл (не директорія)
                    if ос.path.isfile(log_path):
                        with open(log_path, "w") as f:
                            # Просто відкриваємо файл для запису, щоб очистити
                            pass
                        log_message(f"[API] Очищено лог-файл: {log_file}")
                except Exception as e:
                    log_message(f"[API] Помилка при очищенні лог-файлу {log_file}: {e}")
        else:
            ос.makedirs(logs_dir, exist_ok=True)
            log_message(f"[API] Створено нову директорію для логів: {logs_dir}")

        # Очищаємо кеш та тимчасові файли
        # (Додайте тут очищення інших директорій, якщо необхідно)
        cache_dirs = ["__pycache__", ".pytest_cache", ".cache"]
        for cache_dir in cache_dirs:
            if ос.path.exists(cache_dir):
                try:
                    shutil.rmtree(cache_dir, onerror=handle_readonly_error)
                    log_message(f"[API] Видалено кеш директорію: {cache_dir}")
                except Exception as e:
                    log_message(
                        f"[API] Помилка при видаленні кеш директорії {cache_dir}: {e}"
                    )

        # Очищаємо черги завдань та стан завдань
        global subtask_statuses, task_queues, current_structure
        task_queues = {
            "executor": asyncio.Queue(),
            "tester": asyncio.Queue(),
            "documenter": asyncio.Queue(),
        }
        subtask_statuses = {}
        current_structure = {}
        log_message("[API] Очищено всі черги завдань та статуси")

        # Оновлюємо всіх клієнтів
        await broadcast_specific_update(
            {
                "type": "full_status_update",
                "ai_status": ai_status,
                "queues": {"executor": [], "tester": [], "documenter": []},
                "subtasks": {},
                "structure": {},
            }
        )

        log_message("[API] Проект успішно очищено")
        return {"status": "success", "message": "Проект повністю очищено"}
    except Exception as e:
        log_message(f"[API] Помилка при очищенні проекту: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Помилка очищення: {str(e)}"},
        )


def handle_readonly_error(func, path, exc_info):
    """Функція для обробки помилок доступу при видаленні файлів"""
    import stat

    # Перевіряємо, чи файл "тільки для читання"
    if not os.access(path, os.W_OK):
        # Додаємо права на запис
        os.chmod(path, stat.S_IWUSR)
        # Пробуємо знову
        func(path)
    else:
        # Інакше просто логуємо помилку
        log_message(f"[API] Помилка доступу при видаленні {path}: {exc_info[1]}")


async def create_followup_tasks(file_path: str, executor_subtask_id: str):
    """
    Creates tasks for testing and documentation after successful code receipt.

    Args:
        file_path: Path to the file for which tasks are being created
        executor_subtask_id: ID of the executor subtask that was completed
    """
    try:
        # Get file content
        file_path_obj = repo_path / file_path
        if not file_path_obj.exists():
            logger.error(
                f"[API] Could not find file {file_path} to create follow-up tasks"
            )
            return

        content = None
        try:
            with open(file_path_obj, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"[API] Error reading file {file_path}: {e}")
            return

        # Check file type to determine if tests are needed
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
        needs_tests = file_path.lower().endswith(testable_extensions)

        # Create task for testing
        if needs_tests:
            tester_task = {
                "id": str(uuid4()),
                "filename": file_path,
                "role": "tester",
                "text": f"Generate unit tests for the code in file: {file_path}",
                "code": content,
                "related_task_id": executor_subtask_id,  # Link to original task
            }

            # Add task to queue
            tester_success = add_task_to_queue("tester", tester_task)
            if tester_success:
                logger.info(
                    f"[API] Created testing task {tester_task['id']} for file {file_path}"
                )
            else:
                logger.error(
                    f"[API] Failed to create testing task for file {file_path}"
                )

        # Create task for documentation
        documenter_task = {
            "id": str(uuid4()),
            "filename": file_path,
            "role": "documenter",
            "text": f"Generate documentation for the code in file: {file_path}",
            "code": content,
            "related_task_id": executor_subtask_id,  # Link to original task
        }

        # Add task to queue
        documenter_success = add_task_to_queue("documenter", documenter_task)
        if documenter_success:
            logger.info(
                f"[API] Created documentation task {documenter_task['id']} for file {file_path}"
            )
        else:
            logger.error(
                f"[API] Failed to create documentation task for file {file_path}"
            )

    except Exception as e:
        logger.error(f"[API] Error creating follow-up tasks for {file_path}: {e}")


@app.get("/worker_status")
async def get_worker_status():
    """
    Повертає статус всіх воркерів (executor, tester, documenter).
    Використовується AI3 для моніторингу простоюючих воркерів.
    """
    worker_status = {
        "executor": "idle" if executor_queue.empty() else "busy",
        "tester": "idle" if tester_queue.empty() else "busy",
        "documenter": "idle" if documenter_queue.empty() else "busy",
    }

    # Перевіряємо час останньої активності для кожного воркера
    for role in worker_status.keys():
        log_path = f"logs/ai2_{role}.log"
        if os.path.exists(log_path):
            # Якщо лог-файл не оновлювався більше ніж 60 секунд і черга пуста - воркер простоює
            last_modified = os.path.getmtime(log_path)
            if time.time() - last_modified > 60 and worker_status[role] == "idle":
                worker_status[role] = "idle"
            elif worker_status[role] == "idle":
                # Перевіримо вміст останніх рядків логу
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        last_lines = list(deque(f, 10))  # Читаємо останні 10 рядків
                        has_empty_message = any(
                            "пуста" in line or "empty" in line.lower()
                            for line in last_lines
                        )
                        if has_empty_message:
                            worker_status[role] = "idle"
                        else:
                            # Якщо немає повідомлення про пусту чергу, але черга пуста - воркер в режимі очікування
                            worker_status[role] = "waiting"
                except Exception as e:
                    logger.error(f"Помилка при читанні логу {log_path}: {e}")

    logger.info(f"[API] Запит статусу воркерів: {worker_status}")
    return {"status": worker_status}


def get_repo_structure(repo_path="repo"):
    """
    Recursively scans the repo directory and returns a nested dictionary
    representing the structure of files and directories.
    """
    structure = {}
    if not os.path.exists(repo_path) or not os.path.isdir(repo_path):
        logger.warning(f"Repository directory '{repo_path}' not found.")
        return structure

    try:
        for item in sorted(os.listdir(repo_path)):
            item_path = os.path.join(repo_path, item)
            if os.path.isdir(item_path):
                # Recursive call for subdirectories
                structure[item] = get_repo_structure(item_path)
            else:
                # Files are represented as keys with None value (or other file marker)
                structure[item] = None
    except OSError as e:
        logger.error(f"Error scanning directory '{repo_path}': {e}")
    return structure


async def send_full_status(websocket: WebSocket):
    global current_structure, subtask_status, ai_status, queues
    # ... (отримання інших статусів) ...

    # Отримуємо актуальну структуру репозиторію
    current_structure = get_repo_structure("repo")  # <--- Використовуємо нову функцію

    status_data = {
        "type": "full_status_update",
        "ai_status": ai_status,
        "queues": {role: list(q.queue) for role, q in queues.items()},
        "subtasks": subtask_status,
        "structure": current_structure,  # <--- Надсилаємо коректну структуру
        # ... (інші дані, якщо є) ...
    }
    await manager.broadcast(json.dumps(status_data))
    logger.info("Надіслано повне оновлення статусу всім клієнтам")


@app.post("/task/{role}")
async def add_task_for_role(role: str, task: Dict):
    """
    Adds a task to the queue for the specified role.
    """
    queue = {
        "executor": executor_queue,
        "tester": tester_queue,
        "documenter": documenter_queue,
    }.get(role)

    if not queue:
        logger.error(f"Invalid role for task queue: {role}")
        raise HTTPException(status_code=400, detail="Invalid role")

    # Add task to queue
    queue.put_nowait(task)
    subtask_status[task["id"]] = "pending"

    # Update UI via WebSocket
    asyncio.create_task(
        broadcast_specific_update(
            {
                "queues": {
                    "executor": list(executor_queue._queue),
                    "tester": list(tester_queue._queue),
                    "documenter": list(documenter_queue._queue),
                },
                "subtasks": {task["id"]: "pending"},
            }
        )
    )

    logger.info(
        f"Added task {task['id']} to {role} queue for file {task.get('filename')}"
    )
    return {"status": "task received", "id": task["id"]}


if __name__ == "__main__":
    # Регистрируем обработчики сигналов для корректного завершения
    register_shutdown_handlers()

    web_port = config.get("web_port", 7860)
    logger.info(f"Starting Uvicorn server on 0.0.0.0:{web_port}")
    uvicorn.run(app, host="0.0.0.0", port=web_port)
