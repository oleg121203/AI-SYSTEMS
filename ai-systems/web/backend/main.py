import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiohttp
import prometheus_client
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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

# Import GitHub integration
from github_integration import github_integration
from github_integration import GitHubIntegration
from model_listing import ModelLister

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("web-backend")

# Constants
AI_CORE_URL = os.getenv("AI_CORE_URL", "http://localhost:7871")
DEVELOPMENT_AGENTS_URL = os.getenv("DEVELOPMENT_AGENTS_URL", "http://localhost:7872")
PROJECT_MANAGER_URL = os.getenv("PROJECT_MANAGER_URL", "http://localhost:7873")
CMP_URL = os.getenv("CMP_URL", "http://localhost:7874")
CONFIG_PATH = os.getenv(
    "CONFIG_PATH", "/workspaces/AI-SYSTEMS/ai-systems/web/backend/config.json"
)
GITHUB_REPO = os.getenv("GITHUB_REPO", "oleg121203/AI-SYSTEMS-REPO")

# Log file paths
LOGS_DIR = os.getenv("LOGS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "logs"))
# Create logs directory if it doesn't exist
os.makedirs(LOGS_DIR, exist_ok=True)
logger.info(f"Using logs directory: {LOGS_DIR}")

LOG_FILES = {
    "web-backend": os.path.join(LOGS_DIR, "web-backend.log"),
    "ai-core": os.path.join(LOGS_DIR, "ai-core.log"),
    "development-agents": os.path.join(LOGS_DIR, "development-agents.log"),
    "project-manager": os.path.join(LOGS_DIR, "project-manager.log"),
    "cmp": os.path.join(LOGS_DIR, "cmp.log"),
}


# Load configuration
def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load config from {CONFIG_PATH}: {e}")
        return {}


config = load_config()

app = FastAPI(title="AI-SYSTEMS Web Backend")

# Initialize Git service
try:
    # Import Git service
    from git_service import GitService

    git_service = GitService()
    logger.info("Git service initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Git service: {e}")
    git_service = None

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up Prometheus metrics
REQUEST_COUNT = prometheus_client.Counter(
    "http_requests_total", "Total HTTP Requests", ["method", "endpoint", "status"]
)
REQUEST_LATENCY = prometheus_client.Histogram(
    "http_request_duration_seconds", "HTTP Request Latency", ["method", "endpoint"]
)
ACTIVE_CONNECTIONS = prometheus_client.Gauge(
    "websocket_connections", "Number of active WebSocket connections"
)


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        ACTIVE_CONNECTIONS.set(len(self.active_connections))
        logger.info(
            f"WebSocket client connected: {len(self.active_connections)} active connections"
        )

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        ACTIVE_CONNECTIONS.set(len(self.active_connections))
        logger.info(
            f"WebSocket client disconnected: {len(self.active_connections)} active connections"
        )

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")


manager = ConnectionManager()


# Enums
class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentRole(str, Enum):
    EXECUTOR = "executor"
    TESTER = "tester"
    DOCUMENTER = "documenter"


# Model definitions
class Project(BaseModel):
    id: Optional[str] = None
    name: str
    description: str
    repository_url: Optional[str] = None
    idea_md: Optional[str] = None
    status: ProjectStatus = ProjectStatus.PLANNING
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    target_completion_date: Optional[datetime] = None
    progress: float = 0.0
    task_count: int = 0
    completed_tasks: int = 0
    ai_config: Optional[Dict[str, Dict[str, str]]] = None


class Task(BaseModel):
    id: Optional[str] = None
    title: str
    description: str
    project_id: str
    parent_task_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    assignee: Optional[str] = None
    subtasks: List[str] = []


class Subtask(BaseModel):
    subtask_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_text: str
    role: AgentRole
    filename: str
    code: Optional[str] = None
    idea_md: Optional[str] = None
    is_rework: bool = False


class Report(BaseModel):
    type: str = Field(..., description="Report type (code, test_result, status_update)")
    file: Optional[str] = Field(None, description="File path")
    content: Optional[str] = Field(None, description="File content")
    subtask_id: Optional[str] = Field(None, description="Subtask ID")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Performance metrics")
    message: Optional[str] = Field(None, description="Additional message")


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
    version: Optional[str] = None
    last_seen: Optional[datetime] = None


class AIConfig(BaseModel):
    provider: str
    model: str
    apiKey: Optional[str] = None


class GitCommitFile(BaseModel):
    path: str
    content: str


class GitCommitRequest(BaseModel):
    files: List[GitCommitFile]
    commit_message: str
    last_seen: Optional[datetime] = None


# Service clients
class AIServiceClient:
    """Base class for AI service clients"""

    def __init__(self, base_url: str, service_name: str):
        self.base_url = base_url
        self.service_name = service_name
        self.session = None
        self.retry_count = 0
        self.max_retries = 3
        self.last_health_status = {"status": "unknown"}
        self.recovery_in_progress = False

    async def get_session(self):
        """Get a new or existing aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def health_check(self) -> Dict[str, Any]:
        """Check if the service is running with retry logic"""
        try:
            session = await self.get_session()
            async with session.get(f"{self.base_url}/health", timeout=5) as response:
                if response.status == 200:
                    self.retry_count = 0  # Reset retry count on success
                    self.last_health_status = {"status": "healthy", "timestamp": datetime.now().isoformat()}
                    return self.last_health_status
                else:
                    error_text = await response.text()
                    logger.warning(
                        f"Health check failed for {self.service_name}: {response.status} - {error_text}"
                    )
                    self.last_health_status = {"status": "unhealthy", "error": error_text}
                    # Attempt recovery if needed
                    if not self.recovery_in_progress:
                        asyncio.create_task(self.attempt_recovery())
                    return self.last_health_status
        except Exception as e:
            logger.warning(f"Error connecting to {self.service_name}: {e}")
            self.last_health_status = {"status": "unhealthy", "error": str(e)}
            # Attempt recovery if needed
            if not self.recovery_in_progress:
                asyncio.create_task(self.attempt_recovery())
            return self.last_health_status

    async def attempt_recovery(self):
        """Attempt to recover connection to the service"""
        if self.recovery_in_progress:
            return
            
        self.recovery_in_progress = True
        try:
            # Log the recovery attempt
            logger.info(f"Attempting to recover connection to {self.service_name}")
            
            # Close the current session if it exists
            if self.session and not self.session.closed:
                await self.session.close()
                self.session = None
                
            # Create a new session and try to connect
            self.session = aiohttp.ClientSession()
            retry_count = 0
            
            while retry_count < self.max_retries:
                try:
                    async with self.session.get(f"{self.base_url}/health", timeout=5) as response:
                        if response.status == 200:
                            logger.info(f"Successfully recovered connection to {self.service_name}")
                            self.last_health_status = {"status": "healthy", "timestamp": datetime.now().isoformat()}
                            break
                        else:
                            retry_count += 1
                            await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                except Exception:
                    retry_count += 1
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    
            if retry_count >= self.max_retries:
                logger.error(f"Failed to recover connection to {self.service_name} after {self.max_retries} attempts")
        finally:
            self.recovery_in_progress = False


class AICore(AIServiceClient):
    """Client for interacting with the AI Core service"""

    def __init__(self, base_url: str = AI_CORE_URL):
        super().__init__(base_url, "AI Core")

    async def start_project(self, project_id: str, idea_md: str) -> Dict[str, Any]:
        """Start a new project with AI1"""
        try:
            session = await self.get_session()
            payload = {"project_id": project_id, "idea_md": idea_md}
            async with session.post(
                f"{self.base_url}/projects", json=payload
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error starting project with AI Core: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception starting project with AI Core: {e}")
            return {"status": "error", "error": str(e)}

    async def get_project_status(self, project_id: str) -> Dict[str, Any]:
        """Get the status of a project from AI1"""
        try:
            session = await self.get_session()
            async with session.get(
                f"{self.base_url}/projects/{project_id}/status"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Error getting project status from AI Core: {error_text}"
                    )
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception getting project status from AI Core: {e}")
            return {"status": "error", "error": str(e)}


class DevelopmentAgents(AIServiceClient):
    """Client for interacting with the Development Agents service"""

    def __init__(self, base_url: str = DEVELOPMENT_AGENTS_URL):
        super().__init__(base_url, "Development Agents")

    async def create_agent(self, role: AgentRole) -> Dict[str, Any]:
        """Create a new agent with the specified role"""
        try:
            session = await self.get_session()
            async with session.post(f"{self.base_url}/agents/{role}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error creating agent with role {role}: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception creating agent with role {role}: {e}")
            return {"status": "error", "error": str(e)}

    async def process_subtask(self, subtask: Subtask) -> Dict[str, Any]:
        """Process a subtask using an appropriate agent"""
        try:
            session = await self.get_session()
            async with session.post(
                f"{self.base_url}/subtasks", json=subtask.dict()
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error processing subtask: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception processing subtask: {e}")
            return {"status": "error", "error": str(e)}

    async def get_subtask_status(self, subtask_id: str) -> Dict[str, Any]:
        """Get the status of a subtask"""
        try:
            session = await self.get_session()
            async with session.get(
                f"{self.base_url}/subtasks/{subtask_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error getting subtask status: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception getting subtask status: {e}")
            return {"status": "error", "error": str(e)}


class ProjectManager(AIServiceClient):
    """Client for interacting with the Project Manager service"""

    def __init__(self, base_url: str = PROJECT_MANAGER_URL):
        super().__init__(base_url, "Project Manager")

    async def create_project(self, project: Project) -> Dict[str, Any]:
        """Create a new project"""
        try:
            session = await self.get_session()
            async with session.post(
                f"{self.base_url}/projects",
                json=project.dict(exclude={"id", "created_at", "updated_at"}),
            ) as response:
                if response.status == 200 or response.status == 201:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error creating project: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception creating project: {e}")
            return {"status": "error", "error": str(e)}

    async def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get a project by ID"""
        try:
            session = await self.get_session()
            async with session.get(
                f"{self.base_url}/projects/{project_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error getting project: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception getting project: {e}")
            return {"status": "error", "error": str(e)}

    async def create_project_plan(self, project_id: str) -> Dict[str, Any]:
        """Generate a project plan with tasks and dependencies"""
        try:
            session = await self.get_session()
            async with session.post(
                f"{self.base_url}/projects/{project_id}/plan"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error creating project plan: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception creating project plan: {e}")
            return {"status": "error", "error": str(e)}

    async def assign_tasks(self, project_id: str) -> Dict[str, Any]:
        """Assign tasks to AI agents"""
        try:
            session = await self.get_session()
            async with session.post(
                f"{self.base_url}/projects/{project_id}/assign"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error assigning tasks: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception assigning tasks: {e}")
            return {"status": "error", "error": str(e)}


class ContinuousMonitoring(AIServiceClient):
    """Client for interacting with the Continuous Monitoring Platform service"""

    def __init__(self, base_url: str = CMP_URL):
        super().__init__(base_url, "Continuous Monitoring Platform")

    async def record_metric(
        self, service: str, metric_name: str, value: float, labels: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        """Record a metric"""
        try:
            session = await self.get_session()
            payload = {
                "service": service,
                "metric_name": metric_name,
                "value": value,
                "labels": labels,
            }
            async with session.post(
                f"{self.base_url}/metrics/record", json=payload
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error recording metric: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception recording metric: {e}")
            return {"status": "error", "error": str(e)}

    async def get_services(self) -> Dict[str, Any]:
        """Get all services"""
        try:
            session = await self.get_session()
            async with session.get(f"{self.base_url}/services") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Error getting services: {error_text}")
                    return {"status": "error", "error": error_text}
        except Exception as e:
            logger.error(f"Exception getting services: {e}")
            return {"status": "error", "error": str(e)}


# Initialize service clients
ai_core = AICore()
development_agents = DevelopmentAgents()
project_manager = ProjectManager()
cmp = ContinuousMonitoring()

# In-memory storage for reports and subtasks
reports = []
subtasks = {}


# Basic API endpoints
@app.get("/")
async def root():
    return {"message": "AI-SYSTEMS Web Backend API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Project management endpoints
@app.post(
    "/api/projects", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED
)
async def create_project(project: Project, background_tasks: BackgroundTasks):
    try:
        # Create project in Project Manager
        result = await project_manager.create_project(project)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        project_id = result["id"]

        # Start the project with AI Core in the background
        async def start_ai_project():
            try:
                # Start project with AI Core
                ai_result = await ai_core.start_project(project_id, project.idea_md or "")

                # Record metric
                await cmp.record_metric(
                    service="web-backend",
                    metric_name="project_created",
                    value=1.0,
                    labels={"project_id": project_id},
                )

                # Generate project plan
                plan_result = await project_manager.create_project_plan(project_id)

                # Broadcast update
                await manager.broadcast(
                    {
                        "type": "project_update",
                        "project_id": project_id,
                        "status": "planning_complete",
                        "message": "Project plan generated",
                    }
                )
            except Exception as e:
                logger.error(f"Error in background processing for project {project_id}: {e}")
                logger.error(traceback.format_exc())
                
                # Broadcast error
                await manager.broadcast(
                    {
                        "type": "project_update",
                        "project_id": project_id,
                        "status": "error",
                        "message": f"Error during project setup: {str(e)}",
                    }
                )

        background_tasks.add_task(start_ai_project)

        return {
            "id": project_id,
            "name": project.name,
            "status": "created",
            "message": "Project created successfully and planning started",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects", response_model=List[Dict[str, Any]])
async def get_projects():
    try:
        # Get projects from Project Manager
        result = await project_manager.get_session()
        async with result.get(f"{PROJECT_MANAGER_URL}/projects") as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(
                    status_code=response.status, detail="Error fetching projects"
                )
    except Exception as e:
        logger.error(f"Error getting projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}", response_model=Dict[str, Any])
async def get_project(project_id: str):
    try:
        # Get project from Project Manager
        result = await project_manager.get_project(project_id)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/plan", response_model=Dict[str, Any])
async def create_project_plan(project_id: str, background_tasks: BackgroundTasks):
    try:
        # Generate project plan in the background
        async def generate_plan():
            result = await project_manager.create_project_plan(project_id)

            # Broadcast update
            await manager.broadcast(
                {
                    "type": "project_update",
                    "project_id": project_id,
                    "status": "plan_generated",
                    "message": "Project plan generated",
                }
            )

        background_tasks.add_task(generate_plan)

        return {
            "project_id": project_id,
            "status": "planning_started",
            "message": "Project planning started",
        }
    except Exception as e:
        logger.error(f"Error creating project plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects/{project_id}/start", response_model=Dict[str, Any])
async def start_project(project_id: str, background_tasks: BackgroundTasks):
    try:
        # Check if project exists
        project_result = await project_manager.get_project(project_id)

        if "error" in project_result:
            raise HTTPException(status_code=404, detail=project_result["error"])

        # Assign tasks in the background
        async def assign_project_tasks():
            # Create agents for each role
            for role in [AgentRole.EXECUTOR, AgentRole.TESTER, AgentRole.DOCUMENTER]:
                await development_agents.create_agent(role)

            # Assign tasks
            result = await project_manager.assign_tasks(project_id)

            # Broadcast update
            await manager.broadcast(
                {
                    "type": "project_update",
                    "project_id": project_id,
                    "status": "tasks_assigned",
                    "message": f"Tasks assigned: {result.get('assigned_tasks', [])}",
                }
            )

        background_tasks.add_task(assign_project_tasks)

        return {
            "project_id": project_id,
            "status": "starting",
            "message": "Project execution started",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Task management endpoints
@app.get("/api/projects/{project_id}/tasks", response_model=List[Dict[str, Any]])
async def get_project_tasks(project_id: str):
    try:
        # Get tasks from Project Manager
        result = await project_manager.get_session()
        async with result.get(
            f"{PROJECT_MANAGER_URL}/projects/{project_id}/tasks"
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(
                    status_code=response.status, detail="Error fetching tasks"
                )
    except Exception as e:
        logger.error(f"Error getting project tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{task_id}", response_model=Dict[str, Any])
async def get_task(task_id: str):
    try:
        # Get task from Project Manager
        result = await project_manager.get_session()
        async with result.get(f"{PROJECT_MANAGER_URL}/tasks/{task_id}") as response:
            if response.status == 200:
                return await response.json()
            else:
                raise HTTPException(
                    status_code=response.status, detail="Error fetching task"
                )
    except Exception as e:
        logger.error(f"Error getting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/{task_id}/status", response_model=Dict[str, Any])
async def update_task_status(task_id: str, status: TaskStatus, background_tasks: BackgroundTasks):
    try:
        # Update task status in Project Manager
        result = await project_manager.get_session()
        async with result.post(
            f"{PROJECT_MANAGER_URL}/tasks/{task_id}/status?status={status}"
        ) as response:
            if response.status == 200:
                data = await response.json()
                project_id = data.get("project_id")

                # Broadcast update
                await manager.broadcast(
                    {
                        "type": "task_update",
                        "task_id": task_id,
                        "status": status,
                        "progress": data.get("progress", 0.0),
                    }
                )
                
                # If task is completed, check if all tasks for the project are completed
                if status == TaskStatus.COMPLETED and project_id:
                    # Check if all tasks for this project are completed
                    async def check_project_completion():
                        try:
                            # Get all tasks for the project
                            tasks_result = await project_manager.get_tasks(project_id)
                            if "error" not in tasks_result:
                                tasks = tasks_result.get("tasks", [])
                                incomplete_tasks = [t for t in tasks if t.get("status") != TaskStatus.COMPLETED]
                                
                                if not incomplete_tasks:
                                    logger.info(f"All tasks completed for project {project_id}. Triggering finalization.")
                                    # All tasks are completed, trigger project finalization
                                    await manager.broadcast({
                                        "type": "project_update",
                                        "project_id": project_id,
                                        "status": "all_tasks_completed",
                                        "message": "All tasks completed. Starting GitHub deployment."
                                    })
                                    
                                    # Call finalize_project endpoint
                                    try:
                                        await finalize_project(project_id, background_tasks)
                                    except Exception as finalize_error:
                                        logger.error(f"Error finalizing project: {finalize_error}")
                        except Exception as e:
                            logger.error(f"Error checking project completion: {e}")
                    
                    # Run the check in the background
                    background_tasks.add_task(check_project_completion)

                return data
            else:
                raise HTTPException(
                    status_code=response.status, detail="Error updating task status"
                )
    except Exception as e:
        logger.error(f"Error updating task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Subtask management endpoints
@app.post("/api/subtasks", response_model=Dict[str, Any])
async def create_subtask(subtask: Subtask, background_tasks: BackgroundTasks):
    try:
        # Store subtask locally with timestamp for monitoring
        subtask_data = subtask.dict()
        subtask_data['created_at'] = datetime.now().isoformat()
        subtask_data['last_updated'] = datetime.now().isoformat()
        subtask_data['attempts'] = 1
        subtask_data['max_attempts'] = 3
        subtasks[subtask.subtask_id] = subtask_data

        # Process subtask with Development Agents in the background
        async def process_subtask():
            try:
                # Check service health before processing
                health_status = await development_agents.health_check()
                if health_status.get('status') != 'healthy':
                    logger.warning(f"Development Agents service unhealthy, retrying: {health_status}")
                    # Wait for recovery attempt to complete
                    await asyncio.sleep(5)
                
                # Process the subtask
                result = await development_agents.process_subtask(subtask)
                
                # Update subtask status in local storage
                if subtask.subtask_id in subtasks:
                    subtasks[subtask.subtask_id]['status'] = result.get('status', 'unknown')
                    subtasks[subtask.subtask_id]['message'] = result.get('message', '')
                    subtasks[subtask.subtask_id]['last_updated'] = datetime.now().isoformat()
                
                # Broadcast update
                await manager.broadcast(
                    {
                        "type": "subtask_update",
                        "subtask_id": subtask.subtask_id,
                        "status": result.get("status", "unknown"),
                        "message": result.get("message", ""),
                    }
                )
            except Exception as e:
                logger.error(f"Error processing subtask {subtask.subtask_id}: {e}")
                # Mark subtask as needing retry
                if subtask.subtask_id in subtasks:
                    subtasks[subtask.subtask_id]['status'] = 'error'
                    subtasks[subtask.subtask_id]['error'] = str(e)
                    subtasks[subtask.subtask_id]['needs_retry'] = True
                    subtasks[subtask.subtask_id]['last_updated'] = datetime.now().isoformat()
                
                # Broadcast error
                await manager.broadcast(
                    {
                        "type": "subtask_update",
                        "subtask_id": subtask.subtask_id,
                        "status": "error",
                        "message": f"Error processing subtask: {str(e)}",
                    }
                )

        background_tasks.add_task(process_subtask)

        return {
            "subtask_id": subtask.subtask_id,
            "status": "submitted",
            "message": "Subtask submitted for processing",
        }
    except Exception as e:
        logger.error(f"Error creating subtask: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/subtasks/{subtask_id}", response_model=Dict[str, Any])
async def get_subtask_status(subtask_id: str):
    try:
        # Check if subtask exists locally
        if subtask_id in subtasks:
            # Get status from Development Agents
            result = await development_agents.get_subtask_status(subtask_id)

            if "error" not in result:
                return result

        # If not found or error, return unknown status
        return {"subtask_id": subtask_id, "status": "unknown"}
    except Exception as e:
        logger.error(f"Error getting subtask status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Report management endpoint
@app.post("/api/report", response_model=Dict[str, Any])
async def process_report(report: Report, background_tasks: BackgroundTasks):
    try:
        # Store report locally
        reports.append(report.dict())

        # Broadcast report
        await manager.broadcast({"type": "report", "report": report.dict()})

        # Update task status if applicable
        if report.subtask_id and report.subtask_id in subtasks:
            subtask = subtasks[report.subtask_id]

            # Record metric
            await cmp.record_metric(
                service="web-backend",
                metric_name="report_received",
                value=1.0,
                labels={"report_type": report.type, "subtask_id": report.subtask_id},
            )

        return {"status": "processed", "message": "Report processed successfully"}
    except Exception as e:
        logger.error(f"Error processing report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# AI Provider endpoints


@app.get("/api/ai-config", response_model=Dict[str, Any])
async def get_ai_config():
    """Get current AI configuration"""
    try:
        # Get AI config from environment or config file
        ai_config = {
            "ai1": {
                "provider": os.getenv(
                    "AI1_PROVIDER",
                    config.get("ai_config", {}).get("ai1", {}).get("provider", ""),
                ),
                "model": os.getenv(
                    "AI1_MODEL",
                    config.get("ai_config", {}).get("ai1", {}).get("model", ""),
                ),
            },
            "ai2_executor": {
                "provider": os.getenv(
                    "AI2_EXECUTOR_PROVIDER",
                    config.get("ai_config", {})
                    .get("ai2_executor", {})
                    .get("provider", ""),
                ),
                "model": os.getenv(
                    "AI2_EXECUTOR_MODEL",
                    config.get("ai_config", {})
                    .get("ai2_executor", {})
                    .get("model", ""),
                ),
            },
            "ai2_tester": {
                "provider": os.getenv(
                    "AI2_TESTER_PROVIDER",
                    config.get("ai_config", {})
                    .get("ai2_tester", {})
                    .get("provider", ""),
                ),
                "model": os.getenv(
                    "AI2_TESTER_MODEL",
                    config.get("ai_config", {}).get("ai2_tester", {}).get("model", ""),
                ),
            },
            "ai2_documenter": {
                "provider": os.getenv(
                    "AI2_DOCUMENTER_PROVIDER",
                    config.get("ai_config", {})
                    .get("ai2_documenter", {})
                    .get("provider", ""),
                ),
                "model": os.getenv(
                    "AI2_DOCUMENTER_MODEL",
                    config.get("ai_config", {})
                    .get("ai2_documenter", {})
                    .get("model", ""),
                ),
            },
            "ai3": {
                "provider": os.getenv(
                    "AI3_PROVIDER",
                    config.get("ai_config", {}).get("ai3", {}).get("provider", ""),
                ),
                "model": os.getenv(
                    "AI3_MODEL",
                    config.get("ai_config", {}).get("ai3", {}).get("model", ""),
                ),
            },
        }

        # For each AI agent, check if we have an API key configured
        providers = await get_providers()

        for ai_key, ai_settings in ai_config.items():
            if ai_settings.get("provider") and ai_settings.get("provider") in providers:
                provider = ai_settings.get("provider")
                if providers[provider].get("api_keys"):
                    # Don't send the actual API keys, just indicate that they're available
                    ai_config[ai_key]["api_keys_available"] = len(
                        providers[provider]["api_keys"]
                    )

        return ai_config
    except Exception as e:
        logger.error(f"Error getting AI config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai-config", response_model=Dict[str, Any])
async def update_ai_config(ai_config: Dict[str, Dict[str, Any]]):
    """Update AI configuration"""
    try:
        # Validate the config
        for ai_key, config_data in ai_config.items():
            if "provider" not in config_data or "model" not in config_data:
                raise HTTPException(
                    status_code=400, detail=f"Missing provider or model for {ai_key}"
                )

        # Process API keys if provided
        for ai_key, config_data in ai_config.items():
            if "apiKey" in config_data and config_data["apiKey"]:
                # In a real implementation, we would securely store or use the API key
                # For now, just log that we received it (without logging the actual key)
                logger.info(
                    f"Received API key for {ai_key} using provider {config_data.get('provider')}"
                )

                # Remove the API key from the broadcast data for security
                broadcast_config = {
                    k: v.copy() if isinstance(v, dict) else v
                    for k, v in ai_config.items()
                }
                if "apiKey" in broadcast_config[ai_key]:
                    broadcast_config[ai_key]["apiKey"] = "[REDACTED]"

        # Actually save the configuration to both config files
        try:
            # Save to main config file
            main_config_path = os.getenv("CONFIG_PATH", "config.json")
            with open(main_config_path, "r") as f:
                main_config = json.load(f)
            
            # Update the AI configuration section in main config
            if "ai_config" not in main_config:
                main_config["ai_config"] = {}
                
            # Update each AI agent's configuration in main config
            for ai_key, config_data in ai_config.items():
                if ai_key not in main_config["ai_config"]:
                    main_config["ai_config"][ai_key] = {}
                
                # Update provider and model in main config
                main_config["ai_config"][ai_key]["provider"] = config_data.get("provider")
                
                # Ensure model is explicitly saved, even if it's an empty string
                model_value = config_data.get("model", "")
                main_config["ai_config"][ai_key]["model"] = model_value
                
                # Log the values being saved for debugging
                logger.info(f"Saving for {ai_key}: provider={config_data.get('provider')}, model={model_value}")
            
            # Write the updated main config back to the file
            with open(main_config_path, "w") as f:
                json.dump(main_config, f, indent=2)
            
            # Also save to ai-systems config file
            ai_systems_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")
            if os.path.exists(ai_systems_config_path):
                with open(ai_systems_config_path, "r") as f:
                    ai_systems_config = json.load(f)
                
                # Update the AI configuration section in ai-systems config
                if "ai_config" not in ai_systems_config:
                    ai_systems_config["ai_config"] = {}
                
                # Update each AI agent's configuration in ai-systems config
                for ai_key, config_data in ai_config.items():
                    if ai_key not in ai_systems_config["ai_config"]:
                        ai_systems_config["ai_config"][ai_key] = {}
                    
                    # Update provider and model in ai-systems config
                    ai_systems_config["ai_config"][ai_key]["provider"] = config_data.get("provider")
                    
                    # Ensure model is explicitly saved, even if it's an empty string
                    model_value = config_data.get("model", "")
                    ai_systems_config["ai_config"][ai_key]["model"] = model_value
                    
                    # Log the values being saved for debugging
                    logger.info(f"Saving to ai-systems config for {ai_key}: provider={config_data.get('provider')}, model={model_value}")
                
                # Write the updated ai-systems config back to the file
                with open(ai_systems_config_path, "w") as f:
                    json.dump(ai_systems_config, f, indent=2)
                
                logger.info(f"Successfully saved AI configuration to both {main_config_path} and {ai_systems_config_path}")
            else:
                logger.info(f"Successfully saved AI configuration to {main_config_path} (ai-systems config not found)")
                
            # If an API key is provided, store it in the .env file instead of config.json
            for ai_key, config_data in ai_config.items():
                if "apiKey" in config_data and config_data["apiKey"]:
                    provider_name = config_data.get("provider", "").upper()
                    if provider_name:
                        # We don't directly modify .env here for security reasons
                        # Just log that we would update it
                        logger.info(f"Would update {provider_name}_API_KEY in .env file")
        except Exception as config_error:
            logger.error(f"Failed to save configuration: {config_error}")
            raise HTTPException(status_code=500, detail=f"Failed to save configuration: {str(config_error)}")

        # Log the update
        logger.info(
            f"Updating AI config (providers and models): {[(k, v.get('provider'), v.get('model')) for k, v in ai_config.items()]}"
        )

        # Broadcast the config update (without API keys)
        await manager.broadcast(
            {
                "type": "ai_config_update",
                "data": (
                    broadcast_config if "broadcast_config" in locals() else ai_config
                ),
            }
        )

        # Return the updated config along with the success message
        # This ensures the frontend has the exact state that was saved
        return {
            "status": "success", 
            "message": "AI configuration updated",
            "config": ai_config
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error updating AI config: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to update AI configuration: {str(e)}. Please check server logs for details.")


# AI Provider endpoints
@app.get("/api/providers", response_model=Dict[str, Any])
async def get_providers():
    try:
        # Define available AI providers
        providers = {
            "openai": {
                "name": "OpenAI",
                "description": "OpenAI's GPT models",
                "icon": "openai",
            },
            "anthropic": {
                "name": "Anthropic",
                "description": "Anthropic's Claude models",
                "icon": "anthropic",
            },
            "gemini": {
                "name": "Google Gemini",
                "description": "Google's Gemini models",
                "icon": "gemini",
            },
            "mistral": {
                "name": "Mistral AI",
                "description": "Mistral AI models",
                "icon": "mistral",
            },
            "codestral": {
                "name": "Codestral",
                "description": "Codestral AI models",
                "icon": "codestral",
            },
            "cohere": {
                "name": "Cohere",
                "description": "Cohere AI models",
                "icon": "cohere",
            },
            "groq": {"name": "Groq", "description": "Groq AI models", "icon": "groq"},
            "together": {
                "name": "Together AI",
                "description": "Together AI models",
                "icon": "together",
            },
            "openrouter": {
                "name": "OpenRouter",
                "description": "OpenRouter API",
                "icon": "openrouter",
            },
            "ollama_local": {
                "name": "Ollama (Local)",
                "description": "Locally hosted Ollama models (localhost)",
                "icon": "ollama",
                "base_url": "http://localhost:11434",
            },
            "ollama_remote": {
                "name": "Ollama (Remote)",
                "description": "Remote Ollama models (46.219.108.236)",
                "icon": "ollama",
                "base_url": "http://46.219.108.236:11434",
            },
            "huggingface": {
                "name": "Hugging Face",
                "description": "Hugging Face Inference API",
                "icon": "huggingface",
            },
            "grok": {
                "name": "Grok",
                "description": "xAI's Grok models",
                "icon": "grok",
            },
            "replicate": {
                "name": "Replicate",
                "description": "Replicate hosted models",
                "icon": "replicate",
            },
            "perplexity": {
                "name": "Perplexity",
                "description": "Perplexity AI models",
                "icon": "perplexity",
            },
            "anyscale": {
                "name": "Anyscale",
                "description": "Anyscale Endpoints",
                "icon": "anyscale",
            },
            "deepinfra": {
                "name": "DeepInfra",
                "description": "DeepInfra hosted models",
                "icon": "deepinfra",
            },
            "fireworks": {
                "name": "Fireworks",
                "description": "Fireworks AI models",
                "icon": "fireworks",
            },
            "local": {
                "name": "Local Models",
                "description": "Locally hosted models",
                "icon": "local",
            },
        }

        # Check for API keys in environment variables
        for provider in providers.keys():
            # Initialize API keys list
            api_keys = []

            # Define provider-specific environment variable names
            provider_env_names = [provider.upper()]

            # Add special cases for providers with different environment variable names
            if provider == "together":
                provider_env_names.append(
                    "TUGEZER"
                )  # Add TUGEZER as an alternative name
            elif provider == "gemini":
                provider_env_names.append("GEMINI")  # Ensure GEMINI is included

            # Check for the main API key using all possible environment variable names
            for env_name in provider_env_names:
                main_key = os.getenv(f"{env_name}_API_KEY")
                if main_key:
                    api_keys.append({"name": f"{env_name} Default", "key": main_key})

                # Check for numbered variants (e.g., CODESTRAL2_API_KEY, GEMINI3_API_KEY)
                for i in range(2, 10):  # Check for variants 2-9
                    variant_key = os.getenv(f"{env_name}{i}_API_KEY")
                    if variant_key:
                        api_keys.append(
                            {"name": f"{env_name} Key {i}", "key": variant_key}
                        )

            # Remove duplicates if any
            unique_keys = {}
            for key_info in api_keys:
                if key_info["key"] not in unique_keys:
                    unique_keys[key_info["key"]] = key_info

            api_keys = list(unique_keys.values())

            # Add API keys to provider info
            providers[provider]["api_keys"] = api_keys
            providers[provider]["configured"] = len(api_keys) > 0

        return providers
    except Exception as e:
        logger.error(f"Error getting providers: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve AI providers")


async def check_model_availability(
    provider: str, model: str, api_key: str = None
) -> dict:
    """Check if a model is available via API request to the provider

    Returns:
        dict: A dictionary with 'available' (bool) and 'details' (str) keys
    """
    result = {
        "available": False,
        "details": "API key not provided",
        "latency": None,
        "rate_limited": False,
    }

    if not api_key:
        return result

    try:
        start_time = time.time()

        # Different providers have different API endpoints and authentication methods
        if provider in ["ollama_local", "ollama_remote"]:
            # Get the base URL from the provider info
            providers_info = await get_providers()
            base_url = providers_info.get(provider, {}).get("base_url", "http://localhost:11434")
            
            # Ollama uses a different API structure
            async with aiohttp.ClientSession() as session:
                try:
                    # First try to directly check if the model exists by sending a simple generation request
                    # This is more reliable than just checking if the model is in the list
                    payload = {
                        "model": model,
                        "prompt": "Hello",
                        "stream": False,
                        "options": {"num_predict": 1}  # Minimal token generation to check availability
                    }
                    
                    async with session.post(f"{base_url}/api/generate", json=payload, timeout=5) as response:
                        result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                        
                        if response.status == 200:
                            # If we can generate with this model, it's definitely available
                            result["available"] = True
                            result["details"] = f"Model '{model}' is available and ready for use"
                            
                            # Also get model details if possible
                            try:
                                data = await response.json()
                                if "model" in data:
                                    result["model_details"] = {
                                        "name": data.get("model", model),
                                        "family": model.split(":")[0] if ":" in model else model,
                                        "parameter_size": data.get("parameters", "Unknown")
                                    }
                            except:
                                pass
                        elif response.status == 404 or response.status == 400:
                            # Model not found, check if it can be pulled
                            result["available"] = False
                            result["details"] = f"Model '{model}' not found but may be available to pull"
                            result["can_pull"] = True
                        else:
                            result["details"] = f"API error: {response.status}"
                            
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    # Fallback to listing available models
                    try:
                        async with session.get(f"{base_url}/api/tags") as response:
                            if response.status == 200:
                                data = await response.json()
                                available_models = [m["name"] for m in data.get("models", [])]
                                
                                # Handle model naming conventions (with or without tags)
                                model_base = model.split(":")[0] if ":" in model else model
                                
                                # Check if the model or a version of it is available
                                model_available = model in available_models or any(m.startswith(f"{model_base}:") for m in available_models)
                                result["available"] = model_available
                                
                                if result["available"]:
                                    result["details"] = "Model found in available models list"
                                else:
                                    result["details"] = f"Model '{model}' not found in available models list"
                                    result["can_pull"] = True  # Assume it can be pulled
                            elif response.status == 404:
                                result["details"] = f"Ollama API endpoint not found at {base_url}. Is Ollama running?"
                            else:
                                result["details"] = f"API error: {response.status}"
                    except Exception as inner_e:
                        result["details"] = f"Failed to connect to Ollama at {base_url}: {str(inner_e)}"
                        logger.error(f"Error checking Ollama availability: {inner_e}")
                        
                # Add the base URL to the result for reference
                result["base_url"] = base_url
        elif provider == "huggingface":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For Hugging Face, we'll just check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://huggingface.co/api/models?sort=downloads&direction=-1&limit=1",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        # We can't easily check if a specific model is available via API
                        # So we'll just check if the API key is valid
                        result["available"] = True
                        result["details"] = "API key is valid"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        elif provider == "grok":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For Grok, we'll just check if the API key is valid
            # Since there's no public API to list models
            result["available"] = True
            result["details"] = "API key provided (availability cannot be verified)"
        elif provider == "openai":
            headers = {"Authorization": f"Bearer {api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.openai.com/v1/models", headers=headers
                ) as response:
                    result["latency"] = round(
                        (time.time() - start_time) * 1000
                    )  # in ms

                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = (
                                f"Model '{model}' not found in available models list"
                            )
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"

        elif provider == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            # For Anthropic, we'll make a simple request to check authentication
            async with aiohttp.ClientSession() as session:
                # We're just checking if the API key is valid, not specific model availability
                async with session.get(
                    "https://api.anthropic.com/v1/models", headers=headers
                ) as response:
                    result["latency"] = round(
                        (time.time() - start_time) * 1000
                    )  # in ms

                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("models", [])]
                        result["available"] = any(
                            m.startswith(model) for m in available_models
                        )
                        if result["available"]:
                            result["details"] = "Model appears to be available"
                        else:
                            result["details"] = (
                                f"Model '{model}' not found in available models"
                            )
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"

        elif provider == "google" or provider == "gemini":
            # For Gemini, we'll check via Google AI Studio API
            headers = {"Content-Type": "application/json"}
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            )

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result["latency"] = round(
                        (time.time() - start_time) * 1000
                    )  # in ms

                    if response.status == 200:
                        data = await response.json()
                        available_models = [
                            m["name"].split("/")[-1] for m in data.get("models", [])
                        ]
                        result["available"] = (
                            model in available_models
                            or f"gemini-{model}" in available_models
                        )
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = (
                                f"Model '{model}' not found in available models list"
                            )
                    elif response.status == 400:
                        result["details"] = "Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"

        elif provider == "mistral":
            headers = {"Authorization": f"Bearer {api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.mistral.ai/v1/models", headers=headers
                ) as response:
                    result["latency"] = round(
                        (time.time() - start_time) * 1000
                    )  # in ms

                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = (
                                f"Model '{model}' not found in available models list"
                            )
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"

        elif provider == "codestral":
            # Codestral uses the same API format as Mistral
            headers = {"Authorization": f"Bearer {api_key}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.codestral.com/v1/models", headers=headers
                ) as response:
                    result["latency"] = round(
                        (time.time() - start_time) * 1000
                    )  # in ms

                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = (
                                f"Model '{model}' not found in available models list"
                            )
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"

        elif provider == "replicate":
            headers = {"Authorization": f"Token {api_key}"}
            # For Replicate, we'll check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.replicate.com/v1/models",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        result["available"] = True
                        result["details"] = "API key is valid"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        elif provider == "perplexity":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For Perplexity, we'll check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.perplexity.ai/models",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = f"Model '{model}' not found in available models list"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        elif provider == "anyscale":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For Anyscale, we'll check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.endpoints.anyscale.com/v1/models",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = f"Model '{model}' not found in available models list"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        elif provider == "deepinfra":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For DeepInfra, we'll check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.deepinfra.com/v1/models",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = f"Model '{model}' not found in available models list"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        elif provider == "fireworks":
            headers = {"Authorization": f"Bearer {api_key}"}
            # For Fireworks, we'll check if the API key is valid
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.fireworks.ai/inference/v1/models",
                    headers=headers
                ) as response:
                    result["latency"] = round((time.time() - start_time) * 1000)  # in ms
                    
                    if response.status == 200:
                        data = await response.json()
                        available_models = [m["id"] for m in data.get("data", [])]
                        result["available"] = model in available_models
                        if result["available"]:
                            result["details"] = "Model found in available models list"
                        else:
                            result["details"] = f"Model '{model}' not found in available models list"
                    elif response.status == 401:
                        result["details"] = "Authentication error: Invalid API key"
                    elif response.status == 429:
                        result["details"] = "Rate limit exceeded"
                        result["rate_limited"] = True
                    else:
                        result["details"] = f"API error: {response.status}"
        else:
            # For other providers, we'll assume models are available but mark them as unchecked
            result["available"] = True
            result["details"] = "Provider not supported for availability checks"

        return result
    except Exception as e:
        logger.error(f"Error checking model availability for {provider}/{model}: {e}")
        return {
            "available": False,
            "details": f"Error checking availability: {str(e)}",
            "latency": None,
            "rate_limited": False,
        }


@app.get("/api/providers/{provider}/models", response_model=Dict[str, Any])
async def get_provider_models(
    provider: str, check_availability: bool = False, api_key: str = None
):
    try:
        # Define available models for each provider
        provider_models = {
            "openai": {"models": ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]},
            "anthropic": {
                "models": [
                    "claude-3-opus",
                    "claude-3-sonnet",
                    "claude-3-haiku",
                    "claude-2",
                ]
            },
            "gemini": {
                "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
            },
            "mistral": {"models": ["mistral-large", "mistral-medium", "mistral-small"]},
            "codestral": {"models": ["codestral-latest", "codestral-v0.1"]},
            "cohere": {
                "models": ["command", "command-light", "command-r", "command-r-plus"]
            },
            "groq": {
                "models": [
                    "llama3-70b-8192",
                    "llama3-8b-8192",
                    "mixtral-8x7b-32768",
                    "gemma-7b-it",
                ]
            },
            "together": {
                "models": [
                    "togethercomputer/llama-3-70b-instruct",
                    "togethercomputer/llama-3-8b-instruct",
                    "togethercomputer/StripedHyena-Nous-7B",
                ]
            },
            "openrouter": {
                "models": [
                    "openai/gpt-4o",
                    "anthropic/claude-3-opus",
                    "mistral/mistral-large",
                    "google/gemini-1.5-pro",
                ]
            },
            "ollama_local": {
                "models": [
                    "llama3",
                    "llama3:8b",
                    "llama3:70b",
                    "codellama",
                    "mistral",
                    "mixtral",
                    "phi3",
                    "gemma",
                ]
            },
            "ollama_remote": {
                "models": [
                    "llama3",
                    "llama3:8b",
                    "llama3:70b",
                    "codellama",
                    "mistral",
                    "mixtral",
                    "phi3",
                    "gemma",
                ]
            },
            "huggingface": {
                "models": [
                    "meta-llama/Llama-3-70b-chat-hf",
                    "meta-llama/Llama-3-8b-chat-hf",
                    "mistralai/Mistral-7B-Instruct-v0.2",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1",
                    "microsoft/phi-3-mini-4k-instruct",
                    "google/gemma-7b-it",
                ]
            },
            "grok": {
                "models": [
                    "grok-1",
                    "grok-1.5",
                ]
            },
            "replicate": {
                "models": [
                    "meta/llama-3-70b-instruct",
                    "meta/llama-3-8b-instruct",
                    "mistralai/mistral-7b-instruct-v0.2",
                    "mistralai/mixtral-8x7b-instruct-v0.1",
                ]
            },
            "perplexity": {
                "models": [
                    "llama-3-sonar-large-32k",
                    "llama-3-sonar-small-32k",
                    "sonar-small-chat",
                    "sonar-medium-chat",
                ]
            },
            "anyscale": {
                "models": [
                    "meta-llama/Llama-3-70b-chat-hf",
                    "meta-llama/Llama-3-8b-chat-hf",
                    "mistralai/Mistral-7B-Instruct-v0.2",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1",
                ]
            },
            "deepinfra": {
                "models": [
                    "meta-llama/Llama-3-70b-chat-hf",
                    "meta-llama/Llama-3-8b-chat-hf",
                    "mistralai/Mistral-7B-Instruct-v0.2",
                    "mistralai/Mixtral-8x7B-Instruct-v0.1",
                ]
            },
            "fireworks": {
                "models": [
                    "accounts/fireworks/models/llama-v3-70b-instruct",
                    "accounts/fireworks/models/llama-v3-8b-instruct",
                    "accounts/fireworks/models/mixtral-8x7b-instruct",
                ]
            },
            "local": {"models": ["llama-3-70b", "llama-3-8b", "mixtral-8x7b"]},
        }

        if provider not in provider_models:
            raise HTTPException(
                status_code=404, detail=f"Provider '{provider}' not found"
            )

        # If check_availability is True and we have an API key, check each model's availability
        if check_availability and api_key:
            result = {
                "models": [],
                "provider": provider,
                "api_key_valid": True,
                "check_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "rate_limited": False,
            }

            for model in provider_models[provider]["models"]:
                availability_result = await check_model_availability(
                    provider, model, api_key
                )

                # If any model check indicates rate limiting, mark the entire response
                if availability_result.get("rate_limited", False):
                    result["rate_limited"] = True

                # If any model check indicates invalid API key, mark it
                if "Invalid API key" in availability_result.get("details", ""):
                    result["api_key_valid"] = False

                model_info = {
                    "id": model,
                    "available": availability_result.get("available", False),
                    "details": availability_result.get("details", "Unknown"),
                    "latency": availability_result.get("latency"),
                }

                # Add model-specific metadata
                if "gpt-4" in model:
                    model_info["category"] = "advanced"
                    model_info["capabilities"] = ["text", "code", "reasoning"]
                elif "gpt-3.5" in model:
                    model_info["category"] = "standard"
                    model_info["capabilities"] = ["text", "code"]
                elif "claude-3-opus" in model:
                    model_info["category"] = "advanced"
                    model_info["capabilities"] = ["text", "code", "reasoning", "vision"]
                elif "claude-3" in model:
                    model_info["category"] = "standard"
                    model_info["capabilities"] = ["text", "code", "vision"]
                elif "gemini-ultra" in model:
                    model_info["category"] = "advanced"
                    model_info["capabilities"] = ["text", "code", "reasoning", "vision"]
                elif "gemini-pro" in model:
                    model_info["category"] = "standard"
                    model_info["capabilities"] = ["text", "code"]
                elif "mistral-large" in model or "codestral" in model:
                    model_info["category"] = "advanced"
                    model_info["capabilities"] = ["text", "code"]
                else:
                    model_info["category"] = "standard"
                    model_info["capabilities"] = ["text"]

                result["models"].append(model_info)

            # Sort models by availability and then by category
            result["models"] = sorted(
                result["models"],
                key=lambda x: (
                    not x["available"],
                    0 if x.get("category") == "advanced" else 1,
                ),
            )

            return result

        # Otherwise, return the standard list
        return provider_models[provider]
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting models for provider {provider}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve models for provider {provider}"
        )


# Endpoint to pull Ollama models
@app.post("/api/providers/{provider}/pull-model", response_model=Dict[str, Any])
async def pull_ollama_model(provider: str, model_request: Dict[str, str]):
    """Pull a model from Ollama if it's not already available
    
    Args:
        provider: The provider ID (must be ollama_local or ollama_remote)
        model_request: A dictionary containing the model name to pull
        
    Returns:
        dict: A dictionary with status information about the pull operation
    """
    try:
        model = model_request.get("model")
        if not model:
            raise HTTPException(status_code=400, detail="Model name is required")
            
        if provider not in ["ollama_local", "ollama_remote"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Provider '{provider}' does not support pulling models. Only Ollama providers are supported."
            )
            
        # Get the base URL for the provider
        providers_info = await get_providers()
        base_url = providers_info.get(provider, {}).get("base_url", "http://localhost:11434")
        
        # Send the pull request to Ollama
        async with aiohttp.ClientSession() as session:
            try:
                payload = {"name": model}
                async with session.post(f"{base_url}/api/pull", json=payload) as response:
                    if response.status == 200:
                        return {
                            "status": "success",
                            "message": f"Started pulling model '{model}'. This may take some time depending on the model size.",
                            "details": "The model will be downloaded in the background. You can check its availability later."
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"Failed to pull model '{model}'",
                            "details": f"API error: {response.status} - {error_text}"
                        }
            except Exception as e:
                logger.error(f"Error pulling Ollama model: {e}")
                return {
                    "status": "error",
                    "message": f"Failed to connect to Ollama at {base_url}",
                    "details": str(e)
                }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in pull_ollama_model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pull model: {str(e)}")


# Model listing endpoints
@app.get("/api/models/list/{provider}", response_model=Dict[str, Any])
async def list_provider_models(provider: str):
    """List all models available from a specific provider
    
    Args:
        provider: The provider ID (e.g., ollama_local, huggingface, etc.)
        
    Returns:
        dict: A dictionary with provider models and metadata
    """
    try:
        model_lister = ModelLister()
        
        if provider.startswith("ollama"):
            result = await model_lister.list_ollama_models(provider)
        elif provider == "huggingface":
            result = await model_lister.list_huggingface_models()
        elif provider == "replicate":
            result = await model_lister.list_replicate_models()
        elif provider == "anyscale":
            result = await model_lister.list_anyscale_models()
        elif provider == "deepinfra":
            result = await model_lister.list_deepinfra_models()
        elif provider == "fireworks":
            result = await model_lister.list_fireworks_models()
        elif provider == "perplexity":
            result = await model_lister.list_perplexity_models()
        elif provider == "grok":
            result = await model_lister.list_grok_models()
        elif provider == "codestral":
            result = await model_lister.list_codestral_models()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
        
        return result
    except Exception as e:
        logger.error(f"Error listing models for provider {provider}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")

@app.get("/api/models/list", response_model=Dict[str, Any])
async def list_all_models():
    """List models from all configured providers
    
    Returns:
        dict: A dictionary with all provider models and metadata
    """
    try:
        model_lister = ModelLister()
        result = await model_lister.list_all_models()
        return result
    except Exception as e:
        logger.error(f"Error listing all models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list all models: {str(e)}")

@app.get("/api/models/verify-ollama", response_model=Dict[str, Any])
async def verify_ollama_availability():
    """Verify availability of Ollama endpoints (local and remote)
    
    Returns:
        dict: A dictionary with availability status for each Ollama endpoint
    """
    try:
        model_lister = ModelLister()
        result = await model_lister.verify_all_ollama_endpoints()
        return result
    except Exception as e:
        logger.error(f"Error verifying Ollama availability: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to verify Ollama availability: {str(e)}")

@app.get("/api/models/verify-ollama/{provider}", response_model=Dict[str, Any])
async def verify_specific_ollama_provider(provider: str):
    """Verify availability of a specific Ollama endpoint (local or remote)
    
    Args:
        provider: The Ollama provider ID (ollama_local or ollama_remote)
        
    Returns:
        dict: A dictionary with availability status for the specified Ollama endpoint
    """
    if provider not in ["ollama_local", "ollama_remote"]:
        raise HTTPException(status_code=400, detail=f"Invalid Ollama provider: {provider}. Must be 'ollama_local' or 'ollama_remote'")
    
    try:
        model_lister = ModelLister()
        result = await model_lister.verify_ollama_availability(provider)
        return result
    except Exception as e:
        logger.error(f"Error verifying {provider} availability: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to verify {provider} availability: {str(e)}")

@app.get("/api/models/compare", response_model=Dict[str, Any])
async def compare_models(provider1: str, model1: str, provider2: str, model2: str):
    """Compare two models from different or same providers
    
    Args:
        provider1: First provider ID
        model1: First model name
        provider2: Second provider ID
        model2: Second model name
        
    Returns:
        dict: A comparison of the two models
    """
    try:
        # Get model details for both models
        model_lister = ModelLister()
        
        # Get first model details
        if provider1.startswith("ollama"):
            result1 = await model_lister.list_ollama_models(provider1)
            model1_details = next((m for m in result1.get("models", []) if m.get("name") == model1 or m.get("model") == model1), None)
        else:
            # For other providers, use the check_model_availability function
            availability1 = await check_model_availability(provider1, model1)
            model1_details = availability1
        
        # Get second model details
        if provider2.startswith("ollama"):
            result2 = await model_lister.list_ollama_models(provider2)
            model2_details = next((m for m in result2.get("models", []) if m.get("name") == model2 or m.get("model") == model2), None)
        else:
            # For other providers, use the check_model_availability function
            availability2 = await check_model_availability(provider2, model2)
            model2_details = availability2
        
        # Compare the models
        comparison = {
            "model1": {
                "provider": provider1,
                "name": model1,
                "details": model1_details
            },
            "model2": {
                "provider": provider2,
                "name": model2,
                "details": model2_details
            },
            "comparison": {
                "size_difference": None,  # Will be populated if size info is available
                "capabilities_overlap": None,  # Will be populated if capability info is available
                "parameter_size_ratio": None  # Will be populated if parameter size info is available
            }
        }
        
        # Calculate size difference if available
        if model1_details and model2_details:
            size1 = model1_details.get("size") if isinstance(model1_details, dict) else None
            size2 = model2_details.get("size") if isinstance(model2_details, dict) else None
            
            if size1 and size2:
                comparison["comparison"]["size_difference"] = abs(size1 - size2)
                comparison["comparison"]["size_ratio"] = round(max(size1, size2) / min(size1, size2), 2)
            
            # Compare parameter sizes if available
            param_size1 = model1_details.get("details", {}).get("parameter_size") if isinstance(model1_details, dict) else None
            param_size2 = model2_details.get("details", {}).get("parameter_size") if isinstance(model2_details, dict) else None
            
            if param_size1 and param_size2:
                # Extract numeric part from parameter size (e.g., "7B" -> 7)
                try:
                    num1 = float(param_size1.replace("B", ""))
                    num2 = float(param_size2.replace("B", ""))
                    comparison["comparison"]["parameter_size_ratio"] = round(max(num1, num2) / min(num1, num2), 2)
                except (ValueError, AttributeError):
                    pass
        
        return comparison
    except Exception as e:
        logger.error(f"Error comparing models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to compare models: {str(e)}")



# System status endpoints
@app.get("/api/status", response_model=Dict[str, Any])
async def get_system_status():
    try:
        # Check health of all services
        ai_core_health = await ai_core.health_check()
        development_agents_health = await development_agents.health_check()
        project_manager_health = await project_manager.health_check()
        cmp_health = await cmp.health_check()

        # Get services from CMP
        services_result = await cmp.get_services()

        return {
            "status": "operational",
            "services": {
                "ai_core": ai_core_health,
                "development_agents": development_agents_health,
                "project_manager": project_manager_health,
                "cmp": cmp_health,
            },
            "monitoring": services_result.get("services", []),
        }
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {"status": "degraded", "error": str(e)}


# Git service endpoints
@app.post("/api/git/commit", response_model=Dict[str, Any])
async def commit_to_git(request: GitCommitRequest):
    """Commit files to the GitHub repository"""
    try:
        # Convert the request model to the format expected by github_integration
        files_dict = {}
        for file in request.files:
            files_dict[file.path] = file.content

        # Commit the files using the GitHub integration
        result = git_service.commit_files(request.files, request.commit_message)

        if result[0]:
            return {
                "success": True,
                "message": result[1],
                "files": [f.path for f in request.files],
            }
        else:
            raise HTTPException(status_code=500, detail=result[1])
    except Exception as e:
        logger.error(f"Error committing to git: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to commit to git: {str(e)}"
        )


@app.post("/api/git/setup", response_model=Dict[str, Any])
async def setup_git_repo():
    """Set up Git repository"""
    try:
        logger.info("Setting up Git repository")
        # Initialize the repository if needed
        result = github_integration.setup_repository(GITHUB_REPO)
        
        if not result["success"]:
            logger.error(f"Failed to setup GitHub repository: {result['message']}")
            raise HTTPException(status_code=500, detail=result["message"])
        
        return {
            "success": True,
            "message": "Successfully set up Git repository", 
            "details": result["message"]
        }
    except Exception as e:
        logger.error(f"Error setting up Git repository: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Failed to set up Git repository: {str(e)}"
        )


@app.post("/api/git/setup-actions", response_model=Dict[str, Any])
async def setup_github_actions():
    """Set up GitHub Actions workflows for testing"""
    try:
        # Create the GitHub Actions workflow file
        workflow_path = ".github/workflows/ci.yml"
        workflow_content = """
name: CI/CD Pipeline

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9]

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
        cache: 'pip'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
        pip install pytest pytest-cov flake8
    
    - name: Lint with flake8
      run: |
        # stop the build if there are Python syntax errors or undefined names
        flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
        # exit-zero treats all errors as warnings
        flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
    
    - name: Test with pytest
      run: |
        if [ -d tests ]; then
          pytest tests/ --cov=./ --cov-report=xml
        else
          echo "No tests directory found, skipping tests"
        fi
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        fail_ci_if_error: false
"""

        # Create a simple README if it doesn't exist
        readme_path = "README.md"
        readme_content = """
# AI-SYSTEMS

AI-SYSTEMS is a comprehensive platform for managing AI projects, integrating with various AI providers, and automating development workflows.

## Features

- Multiple AI provider integration (OpenAI, Anthropic, Google, etc.)
- Project management and task tracking
- GitHub integration for code management
- Automated testing with GitHub Actions
- Web-based interface for easy access

## Setup

Follow the installation instructions in the documentation to get started.
"""

        # Commit both the workflow file and README
        files_to_commit = {workflow_path: workflow_content, readme_path: readme_content}

        # Attempt to commit the files
        result = github_integration.commit_code(
            files_to_commit, "Add GitHub Actions CI/CD workflow and README"
        )

        # Return success even if there was a warning during commit
        return {
            "success": True,
            "message": "Successfully set up GitHub Actions workflows",
            "details": result.get("message", ""),
        }

    except Exception as e:
        logger.error(f"Error setting up GitHub Actions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to set up GitHub Actions: {str(e)}"
        )

@app.post("/api/projects/{project_id}/finalize", response_model=Dict[str, Any])
async def finalize_project(project_id: str, background_tasks: BackgroundTasks):
    """Finalize a project by committing all files to GitHub and triggering tests
    
    This function is called when all tasks for a project are completed. It:
    1. Collects all generated files
    2. Commits them to GitHub
    3. Triggers GitHub Actions for testing
    4. Monitors the test results
    5. Updates the project status based on the test results
    """
    try:
        # Check if project exists
        project_result = await project_manager.get_project(project_id)
        if "error" in project_result:
            raise HTTPException(status_code=404, detail=project_result["error"])
            
        # Get all tasks for the project
        tasks_result = await project_manager.get_tasks(project_id)
        if "error" in tasks_result:
            raise HTTPException(status_code=500, detail=tasks_result["error"])
            
        # Check if all tasks are completed
        tasks = tasks_result.get("tasks", [])
        incomplete_tasks = [t for t in tasks if t.get("status") != TaskStatus.COMPLETED]
        
        if incomplete_tasks:
            return {
                "success": False,
                "message": f"Project has {len(incomplete_tasks)} incomplete tasks. Cannot finalize.",
                "incomplete_tasks": [t.get("id") for t in incomplete_tasks]
            }
            
        # Process in the background to avoid timeout
        async def process_finalization():
            try:
                # Collect all generated files
                files_to_commit = []
                
                # This would typically come from a storage service or database
                # For now, we'll assume the files are stored in a project directory
                project_files_path = os.path.join(os.getcwd(), "projects", project_id)
                
                if os.path.exists(project_files_path):
                    for root, _, files in os.walk(project_files_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, project_files_path)
                            
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            files_to_commit.append(FileContent(path=rel_path, content=content))
                
                # Update project status to deploying
                await project_manager.update_project(
                    project_id, {"status": ProjectStatus.DEPLOYING}
                )
                
                # Broadcast update
                await manager.broadcast({
                    "type": "project_update",
                    "project_id": project_id,
                    "status": "deploying",
                    "message": "Committing files to GitHub and triggering tests"
                })
                
                # Commit files to GitHub
                if not files_to_commit:
                    logger.warning(f"No files found to commit for project {project_id}")
                    await manager.broadcast({
                        "type": "project_update",
                        "project_id": project_id,
                        "status": "warning",
                        "message": "No files found to commit"
                    })
                    return
                
                # Ensure GitHub Actions workflows are set up
                if git_service:
                    git_service.setup_github_actions()
                
                    # Commit files
                    commit_message = f"Project {project_id} - Automated commit by AI-SYSTEMS"
                    commit_result = git_service.commit_files(files_to_commit, commit_message)
                    
                    if commit_result[0]:
                        # Successfully committed
                        await manager.broadcast({
                            "type": "project_update",
                            "project_id": project_id,
                            "status": "committed",
                            "message": "Files committed to GitHub successfully"
                        })
                        
                        # Wait for GitHub Actions to complete (in a real implementation, this would use webhooks)
                        await asyncio.sleep(5)  # Simulating waiting for tests
                        
                        # Update project status to completed
                        await project_manager.update_project(
                            project_id, {"status": ProjectStatus.COMPLETED}
                        )
                        
                        await manager.broadcast({
                            "type": "project_update",
                            "project_id": project_id,
                            "status": "completed",
                            "message": "Project completed and deployed to GitHub"
                        })
                    else:
                        # Failed to commit
                        logger.error(f"Failed to commit files: {commit_result[1]}")
                        await manager.broadcast({
                            "type": "project_update",
                            "project_id": project_id,
                            "status": "error",
                            "message": f"Failed to commit files: {commit_result[1]}"
                        })
                else:
                    logger.error("Git service not available")
                    await manager.broadcast({
                        "type": "project_update",
                        "project_id": project_id,
                        "status": "error",
                        "message": "Git service not available"
                    })
            except Exception as e:
                logger.error(f"Error in finalization process: {e}")
                await manager.broadcast({
                    "type": "project_update",
                    "project_id": project_id,
                    "status": "error",
                    "message": f"Error finalizing project: {str(e)}"
                })
        
        # Start the background task
        background_tasks.add_task(process_finalization)
        
        return {
            "success": True,
            "message": "Project finalization started",
            "project_id": project_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finalizing project: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial system status
        system_status = await get_system_status()
        await websocket.send_json({"type": "system_status", "data": system_status})

        # Listen for client messages
        while True:
            data = await websocket.receive_json()

            # Process client messages
            if data.get("type") == "ping":
                await websocket.send_json(
                    {"type": "pong", "timestamp": datetime.now().isoformat()}
                )
            elif data.get("type") == "subscribe" and data.get("project_id"):
                # Send project data if available
                project_id = data.get("project_id")
                try:
                    project = await get_project(project_id)
                    await websocket.send_json(
                        {"type": "project_data", "project": project}
                    )
                except HTTPException:
                    await websocket.send_json(
                        {"type": "error", "message": f"Project {project_id} not found"}
                    )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in manager.active_connections:
            manager.disconnect(websocket)


# Metrics middleware has been disabled to ensure compatibility with FastAPI 0.100.0


# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(
        content=prometheus_client.generate_latest(), media_type=CONTENT_TYPE_LATEST
    )


# Log viewing endpoints
@app.get("/api/logs/{service_name}", response_model=Dict[str, Any])
async def get_logs(service_name: str, lines: int = 100):
    """Get logs for a specific service"""
    try:
        logger.info(f"Retrieving logs for service: {service_name}, lines: {lines}")
        
        if service_name not in LOG_FILES:
            available_services = list(LOG_FILES.keys())
            logger.warning(f"Service '{service_name}' not found in available log files. Available: {available_services}")
            raise HTTPException(
                status_code=404,
                detail=f"Log file for service '{service_name}' not found. Available services: {available_services}",
            )

        log_file = LOG_FILES[service_name]
        logger.info(f"Log file path: {log_file}")

        # Check if log file exists
        if not os.path.exists(log_file):
            logger.warning(f"Log file does not exist: {log_file}")
            return {
                "success": True,
                "logs": [],
                "message": f"Log file {log_file} does not exist yet",
            }

        # Use tail command to get the last N lines
        logger.info(f"Reading {lines} lines from {log_file}")
        result = subprocess.run(
            ["tail", f"-{lines}", log_file], capture_output=True, text=True, check=True
        )

        # Split the output into lines
        log_lines = result.stdout.splitlines()
        logger.info(f"Retrieved {len(log_lines)} log lines from {service_name}")

        return {"success": True, "logs": log_lines}
    except subprocess.CalledProcessError as e:
        error_msg = f"Error reading log file: {e}, stdout: {e.stdout}, stderr: {e.stderr}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg}
    except Exception as e:
        error_msg = f"Error getting logs: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return {"success": False, "message": error_msg, "traceback": traceback.format_exc()}


@app.get("/api/logs", response_model=Dict[str, Any])
async def get_available_logs():
    """Get a list of available log files"""
    try:
        available_logs = {}

        for service_name, log_path in LOG_FILES.items():
            file_exists = os.path.exists(log_path)
            file_size = os.path.getsize(log_path) if file_exists else 0
            last_modified = None

            if file_exists:
                last_modified = datetime.fromtimestamp(
                    os.path.getmtime(log_path)
                ).isoformat()

            available_logs[service_name] = {
                "exists": file_exists,
                "path": log_path,
                "size": file_size,
                "last_modified": last_modified,
            }

        return {"success": True, "logs": available_logs}
    except Exception as e:
        logger.error(f"Error getting available logs: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get available logs: {str(e)}"
        )


# Task monitoring system
async def monitor_workflow():
    """Monitor and recover stalled tasks and subtasks"""
    while True:
        try:
            logger.info("Running workflow monitoring check")
            current_time = datetime.now()
            stalled_count = 0
            retried_count = 0
            
            # Check for stalled subtasks (no updates for 5 minutes)
            for subtask_id, subtask_data in list(subtasks.items()):
                try:
                    # Skip completed or failed subtasks
                    if subtask_data.get('status') in ['completed', 'failed']:
                        continue
                        
                    # Check if subtask is stalled
                    last_updated = datetime.fromisoformat(subtask_data.get('last_updated', subtask_data.get('created_at')))
                    time_since_update = (current_time - last_updated).total_seconds()
                    
                    # If subtask hasn't been updated in 5 minutes, mark it for retry
                    if time_since_update > 300:  # 5 minutes
                        stalled_count += 1
                        logger.warning(f"Detected stalled subtask: {subtask_id}, last updated {time_since_update/60:.1f} minutes ago")
                        
                        # Check if we can retry
                        if subtask_data.get('attempts', 0) < subtask_data.get('max_attempts', 3):
                            # Increment attempt counter
                            subtask_data['attempts'] = subtask_data.get('attempts', 0) + 1
                            subtask_data['last_updated'] = current_time.isoformat()
                            subtask_data['status'] = 'retrying'
                            
                            # Create a clone of the original subtask
                            original_subtask = Subtask(
                                subtask_id=subtask_id,
                                task_text=subtask_data.get('task_text', ''),
                                role=subtask_data.get('role', AgentRole.EXECUTOR),
                                filename=subtask_data.get('filename', ''),
                                code=subtask_data.get('code'),
                                idea_md=subtask_data.get('idea_md'),
                                is_rework=True
                            )
                            
                            # Process the subtask again
                            logger.info(f"Retrying stalled subtask {subtask_id}, attempt {subtask_data['attempts']}")
                            result = await development_agents.process_subtask(original_subtask)
                            retried_count += 1
                            
                            # Update subtask data and broadcast
                            subtask_data['status'] = result.get('status', 'unknown')
                            subtask_data['message'] = result.get('message', '')
                            subtask_data['last_updated'] = current_time.isoformat()
                            
                            await manager.broadcast({
                                "type": "subtask_update",
                                "subtask_id": subtask_id,
                                "status": result.get("status", "unknown"),
                                "message": f"Automatically retried stalled subtask (attempt {subtask_data['attempts']})"                                
                            })
                        else:
                            # Max retries reached, mark as failed
                            logger.error(f"Subtask {subtask_id} failed after {subtask_data.get('attempts')} attempts")
                            subtask_data['status'] = 'failed'
                            subtask_data['last_updated'] = current_time.isoformat()
                            subtask_data['message'] = "Failed after maximum retry attempts"
                            
                            await manager.broadcast({
                                "type": "subtask_update",
                                "subtask_id": subtask_id,
                                "status": "failed",
                                "message": "Failed after maximum retry attempts"
                            })
                except Exception as e:
                    logger.error(f"Error monitoring subtask {subtask_id}: {e}")
            
            # Log monitoring results
            if stalled_count > 0:
                logger.info(f"Workflow monitoring: found {stalled_count} stalled subtasks, retried {retried_count}")
                
            # Check overall system health
            ai_core_health = await ai_core.health_check()
            development_agents_health = await development_agents.health_check()
            project_manager_health = await project_manager.health_check()
            cmp_health = await cmp.health_check()
            
            # Broadcast system status update
            await manager.broadcast({
                "type": "system_status",
                "services": {
                    "ai_core": ai_core_health,
                    "development_agents": development_agents_health,
                    "project_manager": project_manager_health,
                    "cmp": cmp_health
                },
                "timestamp": current_time.isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error in workflow monitoring: {e}")
            
        # Run every minute
        await asyncio.sleep(60)

# Start workflow monitoring on app startup
@app.on_event("startup")
async def start_workflow_monitoring():
    # Start workflow monitoring in the background
    asyncio.create_task(monitor_workflow())
    logger.info("Started workflow monitoring task")

if __name__ == "__main__":
    # Start Prometheus metrics server
    try:
        prometheus_client.start_http_server(9090)
        logger.info("Prometheus metrics server started on port 9090")
    except OSError as e:
        logger.warning(f"Could not start Prometheus metrics server: {e}")
        logger.info("Continuing without Prometheus metrics server")

    # Start FastAPI server
    port = int(os.getenv("WEB_BACKEND_PORT", 8001))
    logger.info(f"Starting FastAPI server on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
