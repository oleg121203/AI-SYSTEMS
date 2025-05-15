import asyncio
import argparse
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union

import aiohttp
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("project-manager")

# Constants
DEFAULT_MCP_API_URL = os.getenv("MCP_API_URL", "http://web-backend:8000")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Load configuration
def load_config():
    config_path = os.getenv("CONFIG_PATH", "/app/config.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load config from {config_path}: {e}")
        return {}

config = load_config()

app = FastAPI(title="Project Manager API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Enums
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

class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

# Models
class Project(BaseModel):
    name: str
    description: str = ""
    repository_url: str = ""
    idea_md: Optional[str] = None
    target_completion_date: Optional[datetime] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    repository_url: Optional[str] = None
    idea_md: Optional[str] = None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    target_completion_date: Optional[datetime] = None
    progress: float = 0.0
    task_count: int = 0
    completed_tasks: int = 0

class Task(BaseModel):
    title: str
    description: str
    project_id: str
    parent_task_id: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    estimated_hours: Optional[float] = None
    assignee: Optional[str] = None

class TaskResponse(BaseModel):
    id: str
    title: str
    description: str
    project_id: str
    parent_task_id: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime
    updated_at: datetime
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    assignee: Optional[str] = None
    subtasks: List[str] = []

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    assignee: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repository_url: Optional[str] = None
    idea_md: Optional[str] = None
    status: Optional[ProjectStatus] = None
    target_completion_date: Optional[datetime] = None

class TaskReport(BaseModel):
    task_id: str
    status: TaskStatus
    progress: float = 0.0
    message: Optional[str] = None
    artifacts: Optional[Dict[str, Any]] = None

class ProjectPlan(BaseModel):
    project_id: str
    tasks: List[Task]
    dependencies: Dict[str, List[str]] = {}
    milestones: Dict[str, datetime] = {}

class ProjectStats(BaseModel):
    project_id: str
    task_count: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    progress: float
    estimated_completion_date: Optional[datetime] = None

# In-memory storage for projects and tasks
# In a production environment, this would be replaced with a database
projects = {}
tasks = {}
# Retry tracking for each task
MAX_RETRIES = 3

# AI3 Project Manager Class
class AI3ProjectManager:
    """AI3 - Project Manager
    Responsible for project planning, task management, and progress tracking
    """
    
    def __init__(self):
        self.api_session = None
        self.mcp_api_url = DEFAULT_MCP_API_URL
        self.github_token = GITHUB_TOKEN
        
        # Initialize LLM provider for project planning
        ai3_config = config.get("ai_config", {}).get("ai3", {})
        provider_name = ai3_config.get("provider", "")
        provider_config = config.get("providers", {}).get(provider_name, {})
        
        # Load prompts
        self.planning_prompt = ai3_config.get("planning_prompt", 
            "You are a project manager. Break down the project into tasks and subtasks.")
        self.estimation_prompt = ai3_config.get("estimation_prompt", 
            "Estimate the time required for each task in hours.")
        
        logger.info("AI3 Project Manager initialized")
    
    async def get_api_session(self):
        """Gets or creates the aiohttp session"""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session
    
    async def close_session(self):
        """Closes the aiohttp session"""
        if self.api_session and not self.api_session.closed:
            await self.api_session.close()
    
    async def generate_project_plan(self, project_id: str) -> Dict[str, Any]:
        """Generate a project plan with tasks and dependencies"""
        if project_id not in projects:
            return {"error": "Project not found"}
        
        project = projects[project_id]
        
        # In a real implementation, this would use an LLM to generate the plan
        # For now, we'll create a mock plan
        
        # Generate mock tasks
        mock_tasks = [
            Task(
                title="Setup project structure",
                description="Create the initial project structure and repository setup",
                project_id=project_id,
                priority=TaskPriority.HIGH,
                estimated_hours=4.0
            ),
            Task(
                title="Define core components",
                description="Define the core components and interfaces for the project",
                project_id=project_id,
                priority=TaskPriority.HIGH,
                estimated_hours=8.0
            ),
            Task(
                title="Implement backend services",
                description="Implement the backend services and APIs",
                project_id=project_id,
                priority=TaskPriority.MEDIUM,
                estimated_hours=16.0
            ),
            Task(
                title="Develop frontend UI",
                description="Develop the user interface components",
                project_id=project_id,
                priority=TaskPriority.MEDIUM,
                estimated_hours=12.0
            ),
            Task(
                title="Integration testing",
                description="Perform integration testing of all components",
                project_id=project_id,
                priority=TaskPriority.LOW,
                estimated_hours=8.0
            ),
            Task(
                title="Deployment and documentation",
                description="Deploy the application and create documentation",
                project_id=project_id,
                priority=TaskPriority.LOW,
                estimated_hours=6.0
            )
        ]
        
        # Create tasks in the system
        task_ids = []
        for task in mock_tasks:
            task_id = f"task-{str(uuid.uuid4())[:8]}"
            tasks[task_id] = {
                "id": task_id,
                "title": task.title,
                "description": task.description,
                "project_id": project_id,
                "parent_task_id": task.parent_task_id,
                "status": TaskStatus.PENDING,
                "priority": task.priority,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "estimated_hours": task.estimated_hours,
                "actual_hours": None,
                "assignee": None,
                "subtasks": []
            }
            task_ids.append(task_id)
        
        # Create mock dependencies
        dependencies = {
            task_ids[2]: [task_ids[0], task_ids[1]],  # Backend depends on setup and core components
            task_ids[3]: [task_ids[1]],  # Frontend depends on core components
            task_ids[4]: [task_ids[2], task_ids[3]],  # Testing depends on backend and frontend
            task_ids[5]: [task_ids[4]]  # Deployment depends on testing
        }
        
        # Update project status
        projects[project_id]["status"] = ProjectStatus.PLANNING
        projects[project_id]["updated_at"] = datetime.now()
        projects[project_id]["task_count"] = len(task_ids)
        
        # Create milestones
        start_date = datetime.now()
        milestones = {
            "Project Start": start_date,
            "Core Components Complete": start_date + timedelta(days=7),
            "Backend Complete": start_date + timedelta(days=14),
            "Frontend Complete": start_date + timedelta(days=21),
            "Testing Complete": start_date + timedelta(days=28),
            "Project Complete": start_date + timedelta(days=30)
        }
        
        return {
            "project_id": project_id,
            "tasks": task_ids,
            "dependencies": dependencies,
            "milestones": milestones
        }
    
    async def update_task_status(self, task_id: str, status: TaskStatus, progress: float = None, message: str = None, retry_count: int = None) -> Dict[str, Any]:
        """Update a task's status and progress, handle retries and escalation"""
        if task_id not in tasks:
            return {"error": "Task not found"}
        
        task = tasks[task_id]
        old_status = task["status"]
        task["status"] = status
        task["updated_at"] = datetime.now()
        
        # Store error message if provided
        if message:
            task["message"] = message
            
        # Track retries for failed tasks
        if "retry_count" not in task:
            task["retry_count"] = 0
            
        if status == TaskStatus.FAILED:
            # Increment retry count for failed tasks
            if retry_count is not None:
                task["retry_count"] = retry_count
            else:
                task["retry_count"] += 1
                
            logger.warning(f"Task {task_id} failed (retry {task['retry_count']}/{MAX_RETRIES}): {message}")
            
            if task["retry_count"] < MAX_RETRIES:
                # Retry the task: set back to pending for reassignment
                logger.info(f"Retrying task {task_id}")
                task["status"] = TaskStatus.PENDING
                
                # Reassign the task
                project_id = task["project_id"]
                await self.assign_tasks_to_agents(project_id)
                
                # Broadcast retry notification
                await manager.broadcast({
                    "event": "task_retry", 
                    "task_id": task_id, 
                    "retry_count": task["retry_count"],
                    "message": f"Retrying task (attempt {task['retry_count']}/{MAX_RETRIES})"
                })
            else:
                # Escalate to AI1Coordinator for redistribution
                logger.error(f"Task {task_id} exceeded max retries. Escalating to AI1.")
                
                # Mark as escalated for tracking
                task["escalated"] = True
                
                # Broadcast escalation notification
                await manager.broadcast({
                    "event": "task_escalated", 
                    "task_id": task_id, 
                    "message": f"Task failed after {MAX_RETRIES} attempts. Escalated to AI1 for redistribution."
                })
                
                # Make API call to AI1 to redistribute the task
                try:
                    # This would be an API call to AI Core service
                    project_id = task["project_id"]
                    ai_core_url = os.getenv("AI_CORE_URL", "http://ai-core:7871")
                    
                    async with aiohttp.ClientSession() as session:
                        payload = {
                            "task_id": task_id,
                            "project_id": project_id,
                            "error_message": message or "Task failed after maximum retries",
                            "retry_count": task["retry_count"]
                        }
                        
                        async with session.post(f"{ai_core_url}/redistribute_task", json=payload) as response:
                            if response.status == 200:
                                logger.info(f"Successfully requested task redistribution from AI1 for task {task_id}")
                            else:
                                error_text = await response.text()
                                logger.error(f"Failed to request task redistribution: {error_text}")
                except Exception as e:
                    logger.error(f"Error requesting task redistribution from AI1: {e}")
        
        if progress is not None:
            task["progress"] = max(0.0, min(1.0, progress))  # Clamp between 0 and 1
        elif status == TaskStatus.COMPLETED:
            task["progress"] = 1.0
            task["retry_count"] = 0  # Reset retry count on completion
        elif status == TaskStatus.IN_PROGRESS and old_status == TaskStatus.PENDING:
            task["progress"] = 0.2
        
        # Update project progress
        project_id = task["project_id"]
        if project_id in projects:
            self.update_project_progress(project_id)
        
        return {
            "task_id": task_id,
            "status": status,
            "progress": task.get("progress", 0.0)
        }
    
    def update_project_progress(self, project_id: str) -> float:
        """Update a project's progress based on task status"""
        if project_id not in projects:
            return 0.0
        
        project_tasks = [t for t in tasks.values() if t["project_id"] == project_id]
        if not project_tasks:
            return 0.0
        
        total_tasks = len(project_tasks)
        completed_tasks = sum(1 for t in project_tasks if t["status"] == TaskStatus.COMPLETED)
        in_progress_tasks = sum(1 for t in project_tasks if t["status"] == TaskStatus.IN_PROGRESS)
        
        # Calculate weighted progress
        progress = (completed_tasks + 0.5 * in_progress_tasks) / total_tasks
        
        # Update project stats
        projects[project_id]["progress"] = progress
        projects[project_id]["task_count"] = total_tasks
        projects[project_id]["completed_tasks"] = completed_tasks
        projects[project_id]["updated_at"] = datetime.now()
        
        # Update project status if all tasks are completed
        if completed_tasks == total_tasks and total_tasks > 0:
            projects[project_id]["status"] = ProjectStatus.COMPLETED
        elif in_progress_tasks > 0:
            projects[project_id]["status"] = ProjectStatus.ACTIVE
        
        return progress
    
    async def assign_tasks_to_agents(self, project_id: str) -> Dict[str, Any]:
        """Assign tasks to AI agents based on priority and dependencies"""
        if project_id not in projects:
            return {"error": "Project not found"}
        
        project_tasks = [t for t in tasks.values() if t["project_id"] == project_id]
        if not project_tasks:
            return {"error": "No tasks found for project"}
        
        # Initialize task dependencies dictionary if it doesn't exist
        dependencies = {}
        for task in project_tasks:
            if task["id"] not in dependencies:
                dependencies[task["id"]] = []
        
        # Find tasks that are ready to be worked on (no pending dependencies)
        ready_tasks = []
        for task in project_tasks:
            if task["status"] == TaskStatus.PENDING:
                # Check if this task has dependencies
                has_pending_deps = False
                for dep_list in [deps for t_id, deps in dependencies.items() if t_id == task["id"]]:
                    for dep_id in dep_list:
                        if tasks[dep_id]["status"] != TaskStatus.COMPLETED:
                            has_pending_deps = True
                            break
                
                if not has_pending_deps:
                    ready_tasks.append(task)
        
        # Sort by priority
        ready_tasks.sort(key=lambda t: {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.MEDIUM: 2,
            TaskPriority.LOW: 3
        }[t["priority"]])
        
        # In a real implementation, we would communicate with the agent services
        # For now, just mark the top 3 tasks as in progress
        assigned_tasks = []
        for task in ready_tasks[:3]:
            task["status"] = TaskStatus.IN_PROGRESS
            task["updated_at"] = datetime.now()
            assigned_tasks.append(task["id"])
        
        # Update project status
        if assigned_tasks and projects[project_id]["status"] == ProjectStatus.PLANNING:
            projects[project_id]["status"] = ProjectStatus.ACTIVE
            projects[project_id]["updated_at"] = datetime.now()
        
        return {
            "project_id": project_id,
            "assigned_tasks": assigned_tasks,
            "remaining_tasks": len(ready_tasks) - len(assigned_tasks)
        }

# Initialize the AI3 Project Manager
project_manager = AI3ProjectManager()

# Basic API endpoints
@app.get("/")
async def root():
    return {"message": "Project Manager API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Project management endpoints
@app.post("/projects", response_model=ProjectResponse)
async def create_project(project: Project):
    try:
        project_id = f"project-{str(uuid.uuid4())[:8]}"
        now = datetime.now()
        
        projects[project_id] = {
            "id": project_id,
            "name": project.name,
            "description": project.description,
            "repository_url": project.repository_url,
            "idea_md": project.idea_md,
            "status": ProjectStatus.PLANNING,
            "created_at": now,
            "updated_at": now,
            "target_completion_date": project.target_completion_date,
            "progress": 0.0,
            "task_count": 0,
            "completed_tasks": 0
        }
        
        return ProjectResponse(**projects[project_id])
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/projects", response_model=List[ProjectResponse])
async def list_projects():
    """List all projects"""
    return [ProjectResponse(**p) for p in projects.values()]

@app.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    """Get a project by ID"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**projects[project_id])

@app.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, project_update: ProjectUpdate):
    """Update a project"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects[project_id]
    update_data = project_update.dict(exclude_unset=True)
    
    for key, value in update_data.items():
        if value is not None:
            project[key] = value
    
    project["updated_at"] = datetime.now()
    return ProjectResponse(**project)

@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Delete all tasks associated with the project
    project_task_ids = [t_id for t_id, t in tasks.items() if t["project_id"] == project_id]
    for task_id in project_task_ids:
        del tasks[task_id]
    
    # Delete the project
    del projects[project_id]
    
    return {"message": f"Project {project_id} deleted successfully"}

@app.post("/projects/{project_id}/plan", response_model=ProjectPlan)
async def create_project_plan(project_id: str, background_tasks: BackgroundTasks):
    """Generate a project plan with tasks and dependencies"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Generate the plan in the background
    async def generate_plan():
        await project_manager.generate_project_plan(project_id)
        # Broadcast an update to connected clients
        await manager.broadcast({
            "type": "project_update",
            "project_id": project_id,
            "message": "Project plan generated"
        })
    
    background_tasks.add_task(generate_plan)
    
    # Return a placeholder response
    return {
        "project_id": project_id,
        "tasks": [],
        "dependencies": {},
        "milestones": {},
        "message": "Project plan generation started"
    }

@app.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: Task):
    """Create a new task for a project"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Validate parent task if specified
    if task.parent_task_id and task.parent_task_id not in tasks:
        raise HTTPException(status_code=400, detail="Parent task not found")
    
    task_id = f"task-{str(uuid.uuid4())[:8]}"
    now = datetime.now()
    
    task_data = {
        "id": task_id,
        "title": task.title,
        "description": task.description,
        "project_id": project_id,
        "parent_task_id": task.parent_task_id,
        "status": TaskStatus.PENDING,
        "priority": task.priority,
        "created_at": now,
        "updated_at": now,
        "estimated_hours": task.estimated_hours,
        "actual_hours": None,
        "assignee": task.assignee,
        "subtasks": []
    }
    
    tasks[task_id] = task_data
    
    # Update parent task if needed
    if task.parent_task_id:
        tasks[task.parent_task_id]["subtasks"].append(task_id)
    
    # Update project stats
    projects[project_id]["task_count"] += 1
    projects[project_id]["updated_at"] = now
    
    return TaskResponse(**task_data)

@app.get("/projects/{project_id}/tasks", response_model=List[TaskResponse])
async def list_project_tasks(project_id: str):
    """List all tasks for a project"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project_tasks = [t for t in tasks.values() if t["project_id"] == project_id]
    return [TaskResponse(**t) for t in project_tasks]

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """Get a task by ID"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**tasks[task_id])

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, task_update: TaskUpdate):
    """Update a task"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]
    update_data = task_update.dict(exclude_unset=True)
    
    old_status = task["status"]
    
    for key, value in update_data.items():
        if value is not None:
            task[key] = value
    
    task["updated_at"] = datetime.now()
    
    # If status changed, update project progress
    if "status" in update_data and update_data["status"] != old_status:
        project_id = task["project_id"]
        if project_id in projects:
            project_manager.update_project_progress(project_id)
    
    return TaskResponse(**task)

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = tasks[task_id]
    project_id = task["project_id"]
    
    # Remove from parent's subtasks if needed
    if task["parent_task_id"] and task["parent_task_id"] in tasks:
        parent = tasks[task["parent_task_id"]]
        if task_id in parent["subtasks"]:
            parent["subtasks"].remove(task_id)
    
    # Delete all subtasks
    for subtask_id in task["subtasks"][:]:  # Create a copy to avoid modifying during iteration
        if subtask_id in tasks:
            del tasks[subtask_id]
    
    # Delete the task
    del tasks[task_id]
    
    # Update project stats
    if project_id in projects:
        projects[project_id]["task_count"] -= 1
        if task["status"] == TaskStatus.COMPLETED:
            projects[project_id]["completed_tasks"] -= 1
        projects[project_id]["updated_at"] = datetime.now()
        project_manager.update_project_progress(project_id)
    
    return {"message": f"Task {task_id} deleted successfully"}

@app.post("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def update_task_status(task_id: str, status: TaskStatus, progress: Optional[float] = None):
    """Update a task's status and progress"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    result = await project_manager.update_task_status(task_id, status, progress)
    
    # Broadcast an update to connected clients
    await manager.broadcast({
        "type": "task_update",
        "task_id": task_id,
        "status": status.value,
        "progress": result.get("progress", 0.0)
    })
    
    return result

@app.post("/projects/{project_id}/assign", response_model=Dict[str, Any])
async def assign_project_tasks(project_id: str, background_tasks: BackgroundTasks):
    """Assign tasks to AI agents based on priority and dependencies"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Assign tasks in the background
    async def assign_tasks():
        result = await project_manager.assign_tasks_to_agents(project_id)
        # Broadcast an update to connected clients
        await manager.broadcast({
            "type": "project_update",
            "project_id": project_id,
            "message": f"Assigned {len(result.get('assigned_tasks', []))} tasks"
        })
    
    background_tasks.add_task(assign_tasks)
    
    return {
        "project_id": project_id,
        "message": "Task assignment started"
    }

@app.get("/projects/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(project_id: str):
    """Get statistics for a project"""
    if project_id not in projects:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects[project_id]
    project_tasks = [t for t in tasks.values() if t["project_id"] == project_id]
    
    total_tasks = len(project_tasks)
    completed_tasks = sum(1 for t in project_tasks if t["status"] == TaskStatus.COMPLETED)
    in_progress_tasks = sum(1 for t in project_tasks if t["status"] == TaskStatus.IN_PROGRESS)
    pending_tasks = sum(1 for t in project_tasks if t["status"] == TaskStatus.PENDING)
    
    # Calculate estimated completion date
    if total_tasks > 0 and completed_tasks < total_tasks:
        # Simple estimation based on progress rate
        progress = project["progress"]
        if progress > 0:
            days_elapsed = (datetime.now() - project["created_at"]).days
            if days_elapsed > 0:
                progress_per_day = progress / days_elapsed
                days_remaining = (1.0 - progress) / progress_per_day if progress_per_day > 0 else 30
                estimated_completion = datetime.now() + timedelta(days=days_remaining)
            else:
                estimated_completion = project["target_completion_date"]
        else:
            estimated_completion = project["target_completion_date"]
    elif completed_tasks == total_tasks:
        # All tasks completed
        estimated_completion = datetime.now()
    else:
        estimated_completion = project["target_completion_date"]
    
    return {
        "project_id": project_id,
        "task_count": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "progress": project["progress"],
        "estimated_completion_date": estimated_completion
    }

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Process received data
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            elif data.get("type") == "subscribe" and data.get("project_id"):
                # Send initial project data
                project_id = data.get("project_id")
                if project_id in projects:
                    await websocket.send_json({
                        "type": "project_data",
                        "project": projects[project_id]
                    })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in manager.active_connections:
            manager.disconnect(websocket)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Project Manager Service')
    parser.add_argument('--port', type=int, default=7873, help='Port to run the service on')
    args = parser.parse_args()
    
    # Run the service
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=args.port,
        reload=True,
        log_level="info"
    )
