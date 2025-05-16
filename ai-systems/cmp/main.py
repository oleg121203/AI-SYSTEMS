import argparse
import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import aiofiles
import aiohttp
import psutil
import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)
from pydantic import BaseModel, Field
from starlette.responses import Response

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cmp")

# Constants
CONFIG_FILE = os.getenv("CONFIG_PATH", "./config.json")
LOG_DIR = os.getenv("LOG_DIR", "./logs")
METRICS_RETENTION_DAYS = int(os.getenv("METRICS_RETENTION_DAYS", "7"))

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)


# Load configuration
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load config from {CONFIG_FILE}: {e}")
        return {}


config = load_config()

app = FastAPI(title="Continuous Monitoring Platform")

# Import advanced monitoring endpoints
try:
    from advanced_endpoints import router as advanced_router
    app.include_router(advanced_router)
    logger.info("Advanced monitoring features enabled")
except ImportError:
    logger.warning("Advanced monitoring features not available")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a custom registry to avoid conflicts
custom_registry = CollectorRegistry()

# Define Prometheus metrics with custom registry
request_counter = Counter(
    "api_requests_total", "Total API requests", ["endpoint"], registry=custom_registry
)
active_tasks = Gauge("active_tasks", "Number of active tasks", registry=custom_registry)
service_health = Gauge(
    "service_health",
    "Service health status (1=healthy, 0=unhealthy)",
    ["service"],
    registry=custom_registry,
)
task_duration = Histogram(
    "task_duration_seconds",
    "Task execution duration in seconds",
    ["service", "task_type"],
    registry=custom_registry,
)
api_response_time = Summary(
    "api_response_time_seconds",
    "API response time in seconds",
    ["endpoint"],
    registry=custom_registry,
)
system_cpu_usage = Gauge(
    "system_cpu_usage", "System CPU usage percentage", registry=custom_registry
)
system_memory_usage = Gauge(
    "system_memory_usage_bytes",
    "System memory usage in bytes",
    registry=custom_registry,
)
system_disk_usage = Gauge(
    "system_disk_usage_bytes", "System disk usage in bytes", registry=custom_registry
)

# In-memory storage for recent metrics
metrics_history = {
    "cpu": deque(maxlen=60),  # Last 60 data points
    "memory": deque(maxlen=60),
    "tasks": deque(maxlen=60),
    "api_calls": deque(maxlen=60),
    "errors": deque(maxlen=60),
}


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")


manager = ConnectionManager()


# Model definitions
class MonitoringData(BaseModel):
    service: str
    metric_name: str
    value: float
    labels: dict = {}


class SystemMetrics(BaseModel):
    cpu_percent: float
    memory_used: int
    memory_total: int
    disk_used: int
    disk_total: int
    timestamp: datetime = Field(default_factory=datetime.now)


class ServiceStatus(BaseModel):
    service: str
    status: str
    last_seen: datetime = Field(default_factory=datetime.now)
    version: Optional[str] = None
    metrics: Dict[str, Any] = {}


class TaskMetrics(BaseModel):
    task_id: str
    service: str
    task_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    status: str
    metadata: Dict[str, Any] = {}


class ErrorLog(BaseModel):
    service: str
    error_type: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    trace: Optional[str] = None
    metadata: Dict[str, Any] = {}


class MetricsQuery(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    services: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    limit: int = 100


# Service registry to track active services
service_registry = {}

# Task metrics storage
task_metrics = {}

# Error logs storage
error_logs = []


# System metrics collection background task
async def collect_system_metrics():
    """Collects system metrics periodically"""
    while True:
        try:
            # Collect system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Update Prometheus metrics
            system_cpu_usage.set(cpu_percent)
            system_memory_usage.set(memory.used)
            system_disk_usage.set(disk.used)

            # Store in history
            timestamp = datetime.now().isoformat()
            metrics_history["cpu"].append(
                {"timestamp": timestamp, "value": cpu_percent}
            )
            metrics_history["memory"].append(
                {"timestamp": timestamp, "value": memory.percent}
            )

            # Broadcast to connected clients
            await manager.broadcast(
                {
                    "type": "system_metrics",
                    "data": {
                        "cpu_percent": cpu_percent,
                        "memory_used": memory.used,
                        "memory_total": memory.total,
                        "memory_percent": memory.percent,
                        "disk_used": disk.used,
                        "disk_total": disk.total,
                        "disk_percent": disk.percent,
                        "timestamp": timestamp,
                    },
                }
            )

            # Check service health
            await check_services_health()

            # Save metrics to disk periodically
            await save_metrics_to_disk()

            # Wait before next collection
            await asyncio.sleep(10)  # Collect every 10 seconds
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
            await asyncio.sleep(30)  # Longer delay on error


# Check services health
async def check_services_health():
    """Checks the health of all registered services"""
    current_time = datetime.now()
    for service_id, service_data in list(service_registry.items()):
        # Consider a service unhealthy if not seen in the last 60 seconds
        if (current_time - service_data["last_seen"]).total_seconds() > 60:
            service_health.labels(service=service_data["service"]).set(0)  # Unhealthy
            service_data["status"] = "unhealthy"
        else:
            service_health.labels(service=service_data["service"]).set(1)  # Healthy


# Save metrics to disk
async def save_metrics_to_disk():
    """Saves collected metrics to disk for persistence"""
    try:
        # Save system metrics
        metrics_file = os.path.join(
            LOG_DIR, f"system_metrics_{datetime.now().strftime('%Y-%m-%d')}.json"
        )
        async with aiofiles.open(metrics_file, "w") as f:
            await f.write(
                json.dumps(
                    {
                        "cpu": list(metrics_history["cpu"]),
                        "memory": list(metrics_history["memory"]),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            )

        # Clean up old metrics files
        cleanup_old_metrics_files()
    except Exception as e:
        logger.error(f"Error saving metrics to disk: {e}")


# Clean up old metrics files
def cleanup_old_metrics_files():
    """Removes metrics files older than METRICS_RETENTION_DAYS"""
    try:
        cutoff_date = datetime.now() - timedelta(days=METRICS_RETENTION_DAYS)
        for filename in os.listdir(LOG_DIR):
            if filename.startswith("system_metrics_") and filename.endswith(".json"):
                file_date_str = filename.replace("system_metrics_", "").replace(
                    ".json", ""
                )
                try:
                    file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
                    if file_date < cutoff_date:
                        os.remove(os.path.join(LOG_DIR, filename))
                        logger.info(f"Removed old metrics file: {filename}")
                except ValueError:
                    continue
    except Exception as e:
        logger.error(f"Error cleaning up old metrics files: {e}")


# API Endpoints
@app.get("/")
async def root():
    request_counter.labels(endpoint="/").inc()
    return {"message": "Continuous Monitoring Platform is running"}


@app.get("/health")
async def health_check():
    request_counter.labels(endpoint="/health").inc()
    return {"status": "healthy"}


@app.post("/metrics/record")
async def record_metric(data: MonitoringData):
    request_counter.labels(endpoint="/metrics/record").inc()
    try:
        # Record the metric based on type
        if data.metric_name == "task_count":
            active_tasks.set(data.value)

            # Update task history
            timestamp = datetime.now().isoformat()
            metrics_history["tasks"].append(
                {"timestamp": timestamp, "value": data.value}
            )

        # Record service-specific metrics
        if "service_health" in data.metric_name:
            service_health.labels(service=data.service).set(data.value)

            # Update service registry
            service_id = f"{data.service}-{data.labels.get('instance_id', 'default')}"
            service_registry[service_id] = {
                "service": data.service,
                "status": "healthy" if data.value > 0 else "unhealthy",
                "last_seen": datetime.now(),
                "version": data.labels.get("version"),
                "metrics": data.labels,
            }

        # Broadcast the metric update to connected clients
        await manager.broadcast(
            {
                "type": "metric_update",
                "service": data.service,
                "metric": data.metric_name,
                "value": data.value,
                "labels": data.labels,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return {
            "status": "recorded",
            "service": data.service,
            "metric": data.metric_name,
        }
    except Exception as e:
        logger.error(f"Error recording metric: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/task/start")
async def start_task(task: TaskMetrics):
    request_counter.labels(endpoint="/task/start").inc()
    try:
        # Record task start
        task_id = task.task_id
        task_metrics[task_id] = task.dict()

        # Update active tasks count
        active_tasks.inc()

        # Broadcast task start event
        await manager.broadcast(
            {
                "type": "task_start",
                "task_id": task_id,
                "service": task.service,
                "task_type": task.task_type,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return {"status": "recorded", "task_id": task_id}
    except Exception as e:
        logger.error(f"Error recording task start: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/task/complete")
async def complete_task(task_id: str, status: str, metadata: Dict[str, Any] = {}):
    request_counter.labels(endpoint="/task/complete").inc()
    try:
        # Check if task exists
        if task_id not in task_metrics:
            raise HTTPException(status_code=404, detail="Task not found")

        # Update task metrics
        task = task_metrics[task_id]
        task["end_time"] = datetime.now()
        task["status"] = status
        task["duration"] = (task["end_time"] - task["start_time"]).total_seconds()
        task["metadata"].update(metadata)

        # Record task duration in Prometheus
        task_duration.labels(
            service=task["service"], task_type=task["task_type"]
        ).observe(task["duration"])

        # Update active tasks count
        active_tasks.dec()

        # Broadcast task completion event
        await manager.broadcast(
            {
                "type": "task_complete",
                "task_id": task_id,
                "service": task["service"],
                "task_type": task["task_type"],
                "duration": task["duration"],
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return {"status": "completed", "task_id": task_id, "duration": task["duration"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/error/log")
async def log_error(error: ErrorLog):
    request_counter.labels(endpoint="/error/log").inc()
    try:
        # Add error to log
        error_dict = error.dict()
        error_logs.append(error_dict)

        # Keep only the most recent 1000 errors
        if len(error_logs) > 1000:
            error_logs.pop(0)

        # Update error history
        timestamp = datetime.now().isoformat()
        metrics_history["errors"].append(
            {"timestamp": timestamp, "service": error.service}
        )

        # Broadcast error event
        await manager.broadcast(
            {
                "type": "error",
                "service": error.service,
                "error_type": error.error_type,
                "message": error.message,
                "timestamp": timestamp,
            }
        )

        # Log the error
        logger.error(
            f"Service error: {error.service} - {error.error_type}: {error.message}"
        )

        return {"status": "logged"}
    except Exception as e:
        logger.error(f"Error logging error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def metrics():
    request_counter.labels(endpoint="/metrics").inc()
    return Response(generate_latest(custom_registry), media_type="text/plain")


@app.get("/services")
async def get_services():
    request_counter.labels(endpoint="/services").inc()
    return {
        "services": [
            {
                "service": data["service"],
                "status": data["status"],
                "last_seen": data["last_seen"].isoformat(),
                "version": data["version"],
                "metrics": data["metrics"],
            }
            for data in service_registry.values()
        ]
    }


@app.get("/tasks")
async def get_tasks(limit: int = 100, status: Optional[str] = None):
    request_counter.labels(endpoint="/tasks").inc()
    filtered_tasks = [task for task in task_metrics.values()]

    # Apply status filter if provided
    if status:
        filtered_tasks = [task for task in filtered_tasks if task["status"] == status]

    # Sort by start time (most recent first)
    filtered_tasks.sort(key=lambda x: x["start_time"], reverse=True)

    # Apply limit
    filtered_tasks = filtered_tasks[:limit]

    # Convert datetime objects to ISO format strings
    for task in filtered_tasks:
        task["start_time"] = task["start_time"].isoformat()
        if task["end_time"]:
            task["end_time"] = task["end_time"].isoformat()

    return {"tasks": filtered_tasks}


@app.get("/errors")
async def get_errors(limit: int = 100, service: Optional[str] = None):
    request_counter.labels(endpoint="/errors").inc()
    filtered_errors = error_logs.copy()

    # Apply service filter if provided
    if service:
        filtered_errors = [
            error for error in filtered_errors if error["service"] == service
        ]

    # Sort by timestamp (most recent first)
    filtered_errors.sort(key=lambda x: x["timestamp"], reverse=True)

    # Apply limit
    filtered_errors = filtered_errors[:limit]

    # Convert datetime objects to ISO format strings
    for error in filtered_errors:
        error["timestamp"] = error["timestamp"].isoformat()

    return {"errors": filtered_errors}


# WebSocket endpoints
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial system status
        await websocket.send_json(
            {
                "type": "system_status",
                "status": "connected",
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Send current services status
        await websocket.send_json(
            {
                "type": "services_status",
                "services": [
                    {
                        "service": data["service"],
                        "status": data["status"],
                        "last_seen": data["last_seen"].isoformat(),
                        "version": data["version"],
                    }
                    for data in service_registry.values()
                ],
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Send current system metrics
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        await websocket.send_json(
            {
                "type": "system_metrics",
                "data": {
                    "cpu_percent": cpu_percent,
                    "memory_used": memory.used,
                    "memory_total": memory.total,
                    "memory_percent": memory.percent,
                    "disk_used": disk.used,
                    "disk_total": disk.total,
                    "disk_percent": disk.percent,
                    "timestamp": datetime.now().isoformat(),
                },
            }
        )

        # Listen for client messages
        while True:
            data = await websocket.receive_json()

            # Process client messages
            if data.get("type") == "ping":
                await websocket.send_json(
                    {"type": "pong", "timestamp": datetime.now().isoformat()}
                )
            elif data.get("type") == "get_metrics_history":
                # Send metrics history for the requested metric type
                metric_type = data.get("metric_type", "cpu")
                if metric_type in metrics_history:
                    await websocket.send_json(
                        {
                            "type": "metrics_history",
                            "metric_type": metric_type,
                            "data": list(metrics_history[metric_type]),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
            elif data.get("type") == "get_active_tasks":
                # Send current active tasks
                active_task_list = [
                    task
                    for task_id, task in task_metrics.items()
                    if not task.get("end_time")
                ]

                # Convert datetime objects to ISO format strings
                for task in active_task_list:
                    task["start_time"] = task["start_time"].isoformat()

                await websocket.send_json(
                    {
                        "type": "active_tasks",
                        "tasks": active_task_list,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in manager.active_connections:
            manager.disconnect(websocket)


# Background tasks and monitoring code are now handled directly by the CMP
# MCP API integration has been removed as it's redundant


# Startup event to initialize background tasks
@app.on_event("startup")
async def startup_event():
    """Initialize background tasks on startup"""
    logger.info("CMP service started successfully")
    asyncio.create_task(collect_system_metrics())
    
    # Serve static files
    try:
        app.mount("/dashboard", StaticFiles(directory="static", html=True), name="dashboard")
        logger.info("Dashboard UI mounted at /dashboard")
    except Exception as e:
        logger.warning(f"Could not mount dashboard UI: {e}")


# Shutdown event to clean up resources
@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    logger.info("CMP service shutdown complete")


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Continuous Monitoring Platform Service"
    )
    parser.add_argument(
        "--port", type=int, default=7874, help="Port to run the service on"
    )
    args = parser.parse_args()

    # Run the service
    uvicorn.run(
        "main:app", host="0.0.0.0", port=args.port, reload=True, log_level="info"
    )
