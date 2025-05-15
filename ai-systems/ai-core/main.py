import asyncio
import argparse
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Constants
DEFAULT_MCP_API_URL = os.getenv("MCP_API_URL", "http://web-backend:8000")
DEFAULT_TARGET = os.getenv("TARGET", "Create a modern web application")

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

app = FastAPI(
    title="AI-Core Service",
    description="Central AI coordination service for AI-SYSTEMS",
    version="1.0.0"
)

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

# Models
class ProjectRequest(BaseModel):
    name: str
    description: str
    repository_url: Optional[str] = None
    idea_md: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    status: str
    message: str

class TaskRequest(BaseModel):
    task_id: str
    task_type: str
    content: Dict[str, Any]
    priority: int = 1

class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    
class ProjectStructure(BaseModel):
    structure: Dict[str, Any]
    target: str
    
class SubtaskRequest(BaseModel):
    task_text: str
    role: str
    filename: str
    code: Optional[str] = None
    is_rework: bool = False
    
class TestResult(BaseModel):
    recommendation: str
    context: Dict[str, Any] = {}

# Provider interface for LLM integration
class BaseProvider:
    """Base class for all LLM providers"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.name = "base"
        
    async def generate(self, 
                 prompt: str, 
                 system_prompt: Optional[str] = None,
                 model: Optional[str] = None,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate text from the LLM"""
        raise NotImplementedError("Subclasses must implement this method")
    
    async def get_available_models(self) -> List[str]:
        """Get available models for this provider"""
        return []

# Factory for creating providers
class ProviderFactory:
    @staticmethod
    def create_provider(provider_type: str, config: Dict[str, Any] = None) -> BaseProvider:
        """Create a provider instance based on type"""
        # In a real implementation, this would dynamically load provider classes
        # For now, we'll return a mock provider
        return MockProvider(config)

# Mock provider for development
class MockProvider(BaseProvider):
    """Mock provider for development and testing"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.name = "mock"
        
    async def generate(self, 
                 prompt: str, 
                 system_prompt: Optional[str] = None,
                 model: Optional[str] = None,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate mock response"""
        return f"Mock response for prompt: {prompt[:50]}..."
    
    async def get_available_models(self) -> List[str]:
        """Get available models for this provider"""
        return ["mock-model-1", "mock-model-2"]

# AI1 Coordinator Class
class AI1Coordinator:
    """AI1 - Project Coordinator
    Formulates tasks for AI2 based on project structure and tracks progress
    """
    
    def __init__(self, target: str):
        self.target = target
        self.project_structure = None
        self.files = []
        self.task_status = {}
        self.api_session = None
        self.mcp_api_url = DEFAULT_MCP_API_URL
        self.failed_tasks = {}  # Track failed tasks and retry counts
        self.escalated_tasks = {}  # Track tasks escalated from AI3
        self.MAX_RETRIES = 3
        self.GLOBAL_MAX_RETRIES = 5  # Maximum retries across all AI agents
        
        # Initialize LLM provider
        ai1_config = config.get("ai_config", {}).get("ai1", {})
        provider_name = ai1_config.get("provider", "")
        provider_config = config.get("providers", {}).get(provider_name, {})
        full_config = {**provider_config, **ai1_config}
        
        try:
            self.llm = ProviderFactory.create_provider(provider_name, full_config)
            logger.info(f"Initialized provider '{provider_name}' for AI1")
        except Exception as e:
            logger.error(f"Failed to initialize provider: {e}")
            self.llm = MockProvider()
            
        # System prompt
        self.system_prompt = config.get("ai1_prompt", "You are AI1, the project coordinator.")
        
        # Task management settings
        self.max_concurrent_tasks = config.get("ai1_max_concurrent_tasks", 10)
        self.desired_active_buffer = config.get("ai1_desired_active_buffer", 15)
        
        logger.info(f"AI1 Coordinator initialized with target: {target}")
    
    async def get_api_session(self):
        """Gets or creates the aiohttp session"""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session
    
    async def close_session(self):
        """Closes the aiohttp session"""
        if self.api_session and not self.api_session.closed:
            await self.api_session.close()
    
    async def process_structure(self, structure_data: Dict[str, Any]):
        """Process project structure and identify files for tasks"""
        self.project_structure = structure_data
        self.files = self._extract_files(structure_data.get("structure", {}))
        logger.info(f"Processed structure with {len(self.files)} files")
        return self.files
    
    def _extract_files(self, node: Dict[str, Any], current_path: str = "") -> List[str]:
        """Recursively extracts all files from the JSON structure"""
        files = []
        
        if isinstance(node, dict):
            if "type" in node and node["type"] == "file" and "content" in node:
                # This is a file node
                file_path = current_path
                if file_path.startswith("/"):
                    file_path = file_path[1:]
                files.append(file_path)
            else:
                # This is a directory or another type of node
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        new_path = f"{current_path}/{key}" if current_path else key
                        files.extend(self._extract_files(value, new_path))
        elif isinstance(node, list):
            for item in node:
                files.extend(self._extract_files(item, current_path))
                
        return files
    
    async def initialize_task_status(self):
        """Initialize task statuses for all files"""
        self.task_status = {}
        
        for file_path in self.files:
            # Each file needs executor, tester, and documenter tasks
            self.task_status[f"executor:{file_path}"] = {"status": "pending", "file": file_path}
            self.task_status[f"tester:{file_path}"] = {"status": "pending", "file": file_path}
            self.task_status[f"documenter:{file_path}"] = {"status": "pending", "file": file_path}
        
        # Special case for idea.md which needs refinement first
        if "idea.md" in self.files:
            self.task_status["executor:idea.md"] = {"status": "pending", "file": "idea.md", "priority": "high"}
        
        logger.info(f"Initialized {len(self.task_status)} tasks")
        return self.task_status
    
    async def create_subtask(self, task_text: str, role: str, filename: str, code: Optional[str] = None, is_rework: bool = False):
        """Create a subtask via API"""
        subtask_id = str(uuid.uuid4())
        
        # Prepare the task data
        task_data = {
            "subtask_id": subtask_id,
            "task_text": task_text,
            "role": role,
            "filename": filename,
            "is_rework": is_rework
        }
        
        if code is not None:
            task_data["code"] = code
            
        # Add idea.md context for all tasks if available
        if "idea.md" in self.files and filename != "idea.md":
            try:
                idea_content = await self.get_file_content("idea.md")
                if idea_content:
                    task_data["idea_md"] = idea_content
            except Exception as e:
                logger.error(f"Error fetching idea.md content: {e}")
        
        try:
            session = await self.get_api_session()
            async with session.post(f"{self.mcp_api_url}/api/subtasks", json=task_data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Created subtask {subtask_id} for {filename} ({role})")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Error creating subtask: {error_text}")
                    return {"error": error_text}
        except Exception as e:
            logger.error(f"Exception creating subtask: {e}")
            return {"error": str(e)}
    
    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Get file content from the API"""
        try:
            session = await self.get_api_session()
            async with session.get(f"{self.mcp_api_url}/api/files/{file_path}") as response:
                if response.status == 200:
                    return await response.text()
                else:
                    logger.error(f"Error fetching file {file_path}: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Exception fetching file {file_path}: {e}")
            return None
            
    async def manage_tasks(self):
        """Main task management logic, including retry and escalation"""
        # Update task statuses from API
        await self.update_task_statuses()
        
        # Calculate current task counts
        pending_tasks = []
        active_tasks = []
        completed_tasks = []
        failed_tasks = []
        
        for task_id, task in self.task_status.items():
            status = task.get("status", "")
            if status == "pending":
                pending_tasks.append(task_id)
            elif status in ["sending", "sent", "working"]:
                active_tasks.append(task_id)
            elif status in ["accepted", "skipped", "review"]:
                completed_tasks.append(task_id)
            elif status == "failed":
                failed_tasks.append(task_id)
        
        # Process failed tasks for retry
        for task_id in failed_tasks:
            retry_count = self.failed_tasks.get(task_id, 0)
            if retry_count < self.MAX_RETRIES:
                logger.warning(f"Retrying failed task {task_id} (attempt {retry_count+1}/{self.MAX_RETRIES})")
                await self.create_subtask(
                    task_text=f"Retry task for {self.task_status[task_id]['file']}",
                    role=task_id.split(":")[0],
                    filename=self.task_status[task_id]["file"],
                    is_rework=True
                )
                self.failed_tasks[task_id] = retry_count + 1
                # Update status to pending for next cycle
                self.task_status[task_id]["status"] = "pending"
            else:
                logger.error(f"Task {task_id} permanently failed after {self.MAX_RETRIES} attempts.")
                # Mark as permanently failed
                self.task_status[task_id]["status"] = "permanently_failed"
        
        # Determine how many new tasks to send
        slots_available = max(0, self.desired_active_buffer - len(active_tasks))
        
        if slots_available > 0 and pending_tasks:
            # Prioritize tasks
            prioritized_tasks = self._prioritize_tasks(pending_tasks)
            tasks_to_send = prioritized_tasks[:slots_available]
            
            # Send tasks
            for task_id in tasks_to_send:
                role, filename = task_id.split(":", 1)
                self.task_status[task_id]["status"] = "sending"
                
                # Create task text based on role and filename
                if role == "executor":
                    task_text = f"Implement the file {filename} according to the project requirements."
                elif role == "tester":
                    task_text = f"Write tests for the file {filename}."
                elif role == "documenter":
                    task_text = f"Document the file {filename}."
                else:
                    task_text = f"Process {filename}."
                
                # Send the task
                result = await self.create_subtask(task_text, role, filename)
                
                if "error" not in result:
                    self.task_status[task_id]["status"] = "sent"
                    self.task_status[task_id]["subtask_id"] = result.get("subtask_id")
                else:
                    self.task_status[task_id]["status"] = "pending"  # Reset to try again
        
        # Also check for any escalated tasks that need redistribution
        for task_id, task_info in list(self.escalated_tasks.items()):
            if task_info.get("status") != "redistributed":
                logger.info(f"Processing escalated task {task_id} from AI3")
                await self.redistribute_task(task_id, task_info["project_id"], task_info.get("error_message", ""))
        
        # Check if all tasks are complete
        all_complete = all(task.get("status") in ["accepted", "skipped", "review", "permanently_failed"] 
                         for task in self.task_status.values())
        
        return {
            "pending": len(pending_tasks),
            "active": len(active_tasks),
            "completed": len(completed_tasks),
            "failed": len(failed_tasks),
            "all_complete": all_complete
        }
        
    async def redistribute_task(self, task_id: str, project_id: str, error_message: str = ""):
        """Redistribute a task that was escalated from AI3
        
        This method is called when a task has failed multiple times in AI3 and needs to be
        redistributed by AI1. This completes the cyclic task distribution flow.
        """
        try:
            logger.info(f"Redistributing task {task_id} for project {project_id}")
            
            # Get the task details from the Project Manager
            session = await self.get_api_session()
            project_manager_url = os.getenv("PROJECT_MANAGER_URL", "http://project-manager:7873")
            
            async with session.get(f"{project_manager_url}/tasks/{task_id}") as response:
                if response.status != 200:
                    logger.error(f"Failed to get task details for {task_id}: {response.status}")
                    return
                    
                task_data = await response.json()
                
            # Extract the file path and role from the task
            file_path = task_data.get("file_path")
            role = task_data.get("role", "executor")  # Default to executor if role not specified
            
            if not file_path:
                logger.error(f"Task {task_id} does not have a file path")
                return
                
            # Update escalated task status
            self.escalated_tasks[task_id]["status"] = "redistributing"
            
            # Get existing file content if available
            existing_content = None
            try:
                existing_content = await self.get_file_content(file_path)
            except Exception as e:
                logger.warning(f"Could not get existing content for {file_path}: {e}")
            
            # Create a refined task with more context about the failure
            refined_task_text = f"This task has failed multiple times. Please fix the following issues:\n\n{error_message}\n\nReimplement the file {file_path} addressing these issues."
            
            # Create a new subtask with the refined task description
            subtask_result = await self.create_subtask(
                task_text=refined_task_text,
                role=role,
                filename=file_path,
                code=existing_content,
                is_rework=True
            )
            
            # Update the escalated task tracking
            self.escalated_tasks[task_id]["status"] = "redistributed"
            self.escalated_tasks[task_id]["redistributed_at"] = datetime.now()
            self.escalated_tasks[task_id]["new_subtask_id"] = subtask_result.get("subtask_id") if subtask_result else None
            
            # Track this in failed_tasks for global retry counting
            if task_id not in self.failed_tasks:
                self.failed_tasks[task_id] = 0
            self.failed_tasks[task_id] += 1
            
            logger.info(f"Successfully redistributed task {task_id} with new subtask")
            
            return {
                "status": "success",
                "message": "Task redistributed successfully",
                "task_id": task_id,
                "new_subtask_id": self.escalated_tasks[task_id]["new_subtask_id"]
            }
        except Exception as e:
            logger.error(f"Error redistributing task {task_id}: {e}")
            
            # Mark as failed
            if task_id in self.escalated_tasks:
                self.escalated_tasks[task_id]["status"] = "redistribution_failed"
                self.escalated_tasks[task_id]["error"] = str(e)
            
            return {
                "status": "error",
                "message": f"Failed to redistribute task: {str(e)}",
                "task_id": task_id
            }
    
    def _prioritize_tasks(self, task_ids: List[str]) -> List[str]:
        """Prioritize tasks based on dependencies and importance"""
        # Special case: idea.md should always be first
        prioritized = []
        regular = []
        
        for task_id in task_ids:
            if "idea.md" in task_id:
                prioritized.append(task_id)
            else:
                regular.append(task_id)
        
        # Sort by role: executor first, then tester, then documenter
        executor_tasks = [t for t in regular if t.startswith("executor:")]
        tester_tasks = [t for t in regular if t.startswith("tester:")]
        documenter_tasks = [t for t in regular if t.startswith("documenter:")]
        
        return prioritized + executor_tasks + tester_tasks + documenter_tasks
    
    async def update_task_statuses(self):
        """Update task statuses from the API"""
        try:
            session = await self.get_api_session()
            async with session.get(f"{self.mcp_api_url}/api/subtasks") as response:
                if response.status == 200:
                    api_tasks = await response.json()
                    
                    # Update local task status based on API data
                    for api_task in api_tasks:
                        subtask_id = api_task.get("subtask_id")
                        status = api_task.get("status")
                        role = api_task.get("role")
                        filename = api_task.get("filename")
                        
                        if subtask_id and role and filename:
                            task_id = f"{role}:{filename}"
                            if task_id in self.task_status:
                                self.task_status[task_id]["status"] = status
                                self.task_status[task_id]["subtask_id"] = subtask_id
                else:
                    logger.error(f"Error fetching task statuses: {response.status}")
        except Exception as e:
            logger.error(f"Exception updating task statuses: {e}")

# In-memory storage
tasks: Dict[str, Dict] = {}
ai1_coordinator: Optional[AI1Coordinator] = None

# Basic API endpoints
@app.post("/tasks/", response_model=TaskResponse)
async def create_task(task: TaskRequest):
    """Create a new task in the system."""
    try:
        task_id = task.task_id
        if task_id in tasks:
            raise HTTPException(status_code=400, detail="Task already exists")

        tasks[task_id] = {
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            **task.dict()
        }
        
        return TaskResponse(
            task_id=task_id,
            status="pending",
            message="Task created successfully",
            created_at=tasks[task_id]["created_at"]
        )
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}", response_model=Dict)
async def get_task(task_id: str):
    """Get task status and information."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/projects", response_model=ProjectResponse)
async def create_project(project: ProjectRequest):
    """Create a new project in the system.
    
    This endpoint receives project creation requests from the web backend
    and initializes the AI planning process.
    """
    try:
        # Generate a unique project ID
        project_id = f"project-{uuid.uuid4().hex[:8]}"
        logger.info(f"Received project creation request for: {project.name} (ID: {project_id})")
        
        # In a full implementation, this would initialize project-specific resources
        # For now, just log the project details and return success
        
        # Initialize AI coordinator for this project if needed
        # This would be expanded in a full implementation
        
        return ProjectResponse(
            id=project_id,
            status="created",
            message=f"Project {project.name} created successfully"
        )
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# AI1 Coordinator endpoints
@app.post("/initialize", response_model=Dict[str, Any])
async def initialize_ai1(background_tasks: BackgroundTasks, target: str = DEFAULT_TARGET):
    """Initialize the AI1 coordinator with a target."""
    global ai1_coordinator
    
    try:
        # Create new AI1 coordinator instance
        ai1_coordinator = AI1Coordinator(target)
        logger.info(f"Initialized AI1 coordinator with target: {target}")
        
        # Return success response
        return {
            "status": "success",
            "message": "AI1 coordinator initialized",
            "target": target
        }
    except Exception as e:
        logger.error(f"Error initializing AI1 coordinator: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process-structure", response_model=Dict[str, Any])
async def process_structure(structure: ProjectStructure):
    """Process project structure and initialize tasks."""
    global ai1_coordinator
    
    if not ai1_coordinator:
        # Auto-initialize if not already done
        ai1_coordinator = AI1Coordinator(structure.target)
        logger.info(f"Auto-initialized AI1 coordinator with target: {structure.target}")
    
    try:
        # Process structure and extract files
        files = await ai1_coordinator.process_structure(structure.dict())
        
        # Initialize task statuses
        task_status = await ai1_coordinator.initialize_task_status()
        
        return {
            "status": "success",
            "message": "Project structure processed",
            "files_count": len(files),
            "tasks_count": len(task_status)
        }
    except Exception as e:
        logger.error(f"Error processing structure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/manage-tasks", response_model=Dict[str, Any])
async def manage_tasks():
    """Manage tasks - update statuses and send new tasks."""
    global ai1_coordinator
    
    if not ai1_coordinator:
        raise HTTPException(status_code=400, detail="AI1 coordinator not initialized")
    
    try:
        # Manage tasks
        result = await ai1_coordinator.manage_tasks()
        
        return {
            "status": "success",
            "message": "Tasks managed",
            **result
        }
    except Exception as e:
        logger.error(f"Error managing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/task-status", response_model=Dict[str, Any])
async def get_task_status():
    """Get current task status."""
    global ai1_coordinator
    
    if not ai1_coordinator:
        raise HTTPException(status_code=400, detail="AI1 coordinator not initialized")
    
    try:
        # Update task statuses
        await ai1_coordinator.update_task_statuses()
        
        # Count tasks by status
        status_counts = {}
        for task in ai1_coordinator.task_status.values():
            status = task.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "status": "success",
            "task_count": len(ai1_coordinator.task_status),
            "status_counts": status_counts,
            "tasks": ai1_coordinator.task_status
        }
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/redistribute_task", response_model=Dict[str, Any])
async def redistribute_task(task_data: Dict[str, Any]):
    """Redistribute a failed task that was escalated from AI3
    
    This endpoint is called when a task has failed multiple times in AI3 and needs to be
    redistributed by AI1. This completes the cyclic task distribution flow.
    """
    try:
        if not ai1_coordinator:
            raise HTTPException(status_code=500, detail="AI1 Coordinator not initialized")
            
        task_id = task_data.get("task_id")
        project_id = task_data.get("project_id")
        error_message = task_data.get("error_message")
        retry_count = task_data.get("retry_count", 0)
        
        if not task_id or not project_id:
            raise HTTPException(status_code=400, detail="Missing task_id or project_id")
            
        # Store the escalated task for tracking
        ai1_coordinator.escalated_tasks[task_id] = {
            "project_id": project_id,
            "error_message": error_message,
            "retry_count": retry_count,
            "escalated_at": datetime.now()
        }
        
        logger.info(f"Task {task_id} escalated to AI1 for redistribution")
        
        # Check if we've exceeded the global maximum retries
        global_retries = ai1_coordinator.failed_tasks.get(task_id, 0) + retry_count
        
        if global_retries >= ai1_coordinator.GLOBAL_MAX_RETRIES:
            logger.error(f"Task {task_id} has exceeded global maximum retries ({ai1_coordinator.GLOBAL_MAX_RETRIES})")
            
            # Mark as permanently failed
            return {
                "status": "failed",
                "message": f"Task has exceeded global maximum retries ({ai1_coordinator.GLOBAL_MAX_RETRIES})",
                "task_id": task_id
            }
        
        # Start the redistribution process in the background
        background_tasks = BackgroundTasks()
        background_tasks.add_task(ai1_coordinator.redistribute_task, task_id, project_id, error_message)
        
        return {
            "status": "processing",
            "message": "Task redistribution started",
            "task_id": task_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error redistributing task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test-result", response_model=Dict[str, Any])
async def process_test_result(test_result: TestResult):
    """Process test result from AI3."""
    global ai1_coordinator
    
    if not ai1_coordinator:
        raise HTTPException(status_code=400, detail="AI1 coordinator not initialized")
    
    try:
        # In a full implementation, this would call ai1_coordinator.handle_test_result()
        # For now, just log the recommendation
        logger.info(f"Received test result: {test_result.recommendation}")
        
        return {
            "status": "success",
            "message": "Test result processed"
        }
    except Exception as e:
        logger.error(f"Error processing test result: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            elif data.get("type") == "get_status" and ai1_coordinator:
                # Send current task status
                await ai1_coordinator.update_task_statuses()
                await websocket.send_json({
                    "type": "task_status",
                    "data": {
                        "task_count": len(ai1_coordinator.task_status),
                        "tasks": ai1_coordinator.task_status
                    }
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in manager.active_connections:
            manager.disconnect(websocket)

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='AI Core Service')
    parser.add_argument('--port', type=int, default=7871, help='Port to run the service on')
    args = parser.parse_args()
    
    # Run the service
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=args.port,
        reload=True,
        log_level="info"
    )
