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
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from providers import ProviderFactory

load_dotenv()


# --- Pydantic Models ---
class Report(BaseModel):
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
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
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
        logger.debug(f"Broadcasting specific update: {message}")
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
    await queue.put(subtask)
    subtask_status[subtask_id] = "pending"
    logger.info(f"Received subtask for {role}: ID {subtask_id}, File: {filename}")
    await broadcast_specific_update(
        {
            "queues": {
                "executor": list(executor_queue._queue),
                "tester": list(tester_queue._queue),
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
        raise HTTPException(status_code=400, detail="Invalid role")
    try:
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
        return {"message": f"No tasks available for {role}"}


@app.post("/structure")
async def receive_structure(data: dict):
    global current_structure
    structure_obj = data.get("structure")
    if not isinstance(structure_obj, dict):
        logger.error(f"Invalid structure data: {type(structure_obj)}")
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    current_structure = structure_obj
    logger.info(f"Structure updated by AI3: {list(current_structure.keys())}")
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
        await broadcast_full_status()
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {websocket.client}")
    finally:
        active_connections.discard(websocket)


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


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Простий ендпоінт для перевірки стану сервісу."""
    return {"status": "ok"}


if __name__ == "__main__":
    web_port = config.get("web_port", 7860)
    logger.info(f"Starting Uvicorn server on 0.0.0.0:{web_port}")
    uvicorn.run(app, host="0.0.0.0", port=web_port)
