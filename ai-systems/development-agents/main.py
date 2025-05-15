import argparse
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("development-agents")

# Constants
DEFAULT_MCP_API_URL = os.getenv("MCP_API_URL", "http://web-backend:8000")
SUPPORTED_ROLES = ["executor", "tester", "documenter"]

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

app = FastAPI(title="Development Agents API")

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
class AgentRequest(BaseModel):
    task: str
    context: Dict[str, Any] = {}

class AgentResponse(BaseModel):
    result: str
    status: str
    
class SubtaskRequest(BaseModel):
    subtask_id: str
    task_text: str
    role: str
    filename: str
    code: Optional[str] = None
    idea_md: Optional[str] = None
    is_rework: bool = False
    retry_count: int = 0  # Track how many times this subtask has been retried

class SubtaskResponse(BaseModel):
    subtask_id: str
    status: str
    result: Optional[str] = None
    message: Optional[str] = None

class TaskReport(BaseModel):
    type: str = Field(..., description="Report type (code, test_result, status_update)")
    file: Optional[str] = Field(None, description="File path")
    content: Optional[str] = Field(None, description="File content")
    subtask_id: Optional[str] = Field(None, description="Subtask ID")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Performance metrics")
    message: Optional[str] = Field(None, description="Additional message")

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
        # Generate different responses based on the prompt content
        if "code" in prompt.lower() or "implement" in prompt.lower():
            return "```python\ndef example_function():\n    \"\"\"This is a mock function\"\"\"\n    return 'Hello, World!'\n```"
        elif "test" in prompt.lower():
            return "```python\nimport unittest\n\nclass TestExample(unittest.TestCase):\n    def test_example(self):\n        self.assertEqual(example_function(), 'Hello, World!')\n```"
        elif "document" in prompt.lower() or "documentation" in prompt.lower():
            return "# Example Documentation\n\nThis is a mock documentation for the example function.\n\n## Usage\n\n```python\nresult = example_function()\nprint(result)  # Outputs: Hello, World!\n```"
        else:
            return f"Mock response for prompt: {prompt[:50]}..."
    
    async def get_available_models(self) -> List[str]:
        """Get available models for this provider"""
        return ["mock-model-1", "mock-model-2"]

# AI2 Agent Class
class AI2Agent:
    """AI2 - Development Agent
    Responsible for generating code, tests, and documentation based on assigned role
    """
    
    def __init__(self, role: str):
        if role not in SUPPORTED_ROLES:
            raise ValueError(f"Unsupported role: {role}. Must be one of {SUPPORTED_ROLES}")
            
        self.role = role
        self.api_session = None
        self.mcp_api_url = DEFAULT_MCP_API_URL
        
        # Initialize LLM provider
        ai2_config = config.get("ai_config", {}).get("ai2", {})
        role_config = ai2_config.get(role, {})
        provider_name = role_config.get("provider", "")
        provider_config = config.get("providers", {}).get(provider_name, {})
        full_config = {**provider_config, **role_config}
        
        try:
            self.llm = ProviderFactory.create_provider(provider_name, full_config)
            logger.info(f"Initialized provider '{provider_name}' for AI2 {role}")
        except Exception as e:
            logger.error(f"Failed to initialize provider: {e}")
            self.llm = MockProvider()
            
        # Load base prompts
        self.base_prompts = config.get("ai2_prompts", [
            "You are an expert programmer. Create the content for the file {filename} based on the following task description.",
            "You are a testing expert. Generate unit tests for the code in file {filename}.",
            "You are a technical writer. Generate documentation (e.g., docstrings, comments) for the code in file {filename}."
        ])
        
        # Set the appropriate prompt based on role
        if self.role == "executor":
            self.base_prompt = self.base_prompts[0]
        elif self.role == "tester":
            self.base_prompt = self.base_prompts[1]
        elif self.role == "documenter":
            self.base_prompt = self.base_prompts[2]
        else:
            self.base_prompt = "You are an AI assistant helping with software development."
        
        # System instructions
        self.system_instructions = " Respond ONLY with the raw file content. Do NOT use markdown code blocks (```) unless the target file is a markdown file (e.g., .md). Use only Latin characters in your response."
        
        logger.info(f"AI2 {role} agent initialized")
    
    async def get_api_session(self):
        """Gets or creates the aiohttp session"""
        if self.api_session is None or self.api_session.closed:
            self.api_session = aiohttp.ClientSession()
        return self.api_session
    
    async def close_session(self):
        """Closes the aiohttp session"""
        if self.api_session and not self.api_session.closed:
            await self.api_session.close()
    
    async def generate_with_fallback(self, system_prompt: str, user_prompt: str, max_retries: int = 3):
        """Generate content with fallback mechanism"""
        for attempt in range(max_retries):
            try:
                result = await self.llm.generate(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=0.7
                )
                return result
            except Exception as e:
                logger.error(f"Generation attempt {attempt+1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    async def process_subtask(self, subtask: SubtaskRequest) -> Dict[str, Any]:
        """Process a subtask based on the agent's role"""
        logger.info(f"Processing subtask {subtask.subtask_id} for file {subtask.filename} as {self.role}")
        
        try:
            # Prepare the system prompt
            system_prompt = self.base_prompt.format(filename=subtask.filename) + self.system_instructions
            
            # Prepare the user prompt with task description and context
            user_prompt = f"Task: {subtask.task_text}\n\nFilename: {subtask.filename}"
            
            # Add idea.md content if available
            if subtask.idea_md:
                user_prompt += f"\n\nProject Description (from idea.md):\n{subtask.idea_md}"
            
            # Add existing code if available (important for tester and documenter roles)
            if subtask.code and self.role in ["tester", "documenter"]:
                user_prompt += f"\n\nExisting Code:\n{subtask.code}"
            
            # Generate content based on role
            generated_content = await self.generate_with_fallback(system_prompt, user_prompt)
            
            # Prepare the report
            if self.role == "executor":
                report_type = "code"
            elif self.role == "tester":
                report_type = "test"
            else:  # documenter
                report_type = "docs"
            report = {
                "type": report_type,
                "file": subtask.filename,
                "content": generated_content,
                "subtask_id": subtask.subtask_id,
                "message": f"Generated {report_type} for {subtask.filename}"
            }
            
            return {
                "status": "success",
                "result": generated_content,
                "report": report
            }
            
        except Exception as e:
            logger.error(f"Error processing subtask {subtask.subtask_id}: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def send_report(self, report: Dict[str, Any]):
        """Send a report to the MCP API"""
        try:
            # Ensure the report has a type
            if "type" not in report:
                if "error" in report or "message" in report and "failed" in report.get("message", "").lower():
                    report["type"] = "failure"
                else:
                    report["type"] = "status_update"
            
            # Ensure retry_count is included for failure reports
            if report["type"] == "failure" and "retry_count" not in report:
                report["retry_count"] = getattr(self, "retry_count", 0)
                
            # Log the report being sent
            logger.info(f"Sending {report['type']} report for {report.get('file', 'unknown file')}")
            
            session = await self.get_api_session()
            async with session.post(f"{self.mcp_api_url}/api/report", json=report) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Report sent successfully for subtask {report.get('subtask_id')}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Error sending report: {response.status} - {error_text}")
                    
                    # If this is already a failure report, don't try to send another one
                    if report["type"] == "failure":
                        return {"error": error_text}
                    
                    # Try to send a failure report
                    failure_report = {
                        "type": "failure",
                        "file": report.get("file"),
                        "subtask_id": report.get("subtask_id"),
                        "retry_count": getattr(self, "retry_count", 0),
                        "message": f"Failed to send report: {error_text}"
                    }
                    
                    try:
                        # Try to send the failure report
                        async with session.post(f"{self.mcp_api_url}/api/report", json=failure_report) as failure_response:
                            if failure_response.status == 200:
                                logger.info("Failure report sent successfully")
                            else:
                                logger.error(f"Failed to send failure report: {failure_response.status}")
                    except Exception as send_error:
                        logger.error(f"Exception sending failure report: {send_error}")
                    
                    return {"error": error_text}
        except Exception as e:
            logger.error(f"Exception sending report: {e}")
            
            # Try to send a failure report
            try:
                failure_report = {
                    "type": "failure",
                    "file": report.get("file"),
                    "subtask_id": report.get("subtask_id"),
                    "retry_count": getattr(self, "retry_count", 0),
                    "message": f"Exception sending report: {str(e)}"
                }
                
                session = await self.get_api_session()
                async with session.post(f"{self.mcp_api_url}/api/report", json=failure_report) as response:
                    if response.status == 200:
                        logger.info("Failure report sent successfully")
                    else:
                        logger.error(f"Failed to send failure report: {response.status}")
            except Exception as send_error:
                logger.error(f"Exception sending failure report: {send_error}")
                
            return {"error": str(e)}

# In-memory storage for agents and tasks
agents = {}
active_tasks = {}

# Basic API endpoints
@app.get("/")
async def root():
    return {"message": "Development Agents API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Agent management endpoints
@app.post("/agents/{role}", response_model=Dict[str, Any])
async def create_agent(role: str):
    """Create a new agent for the specified role"""
    if role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {role}. Must be one of {SUPPORTED_ROLES}")
    
    try:
        agent_id = f"{role}-{str(uuid.uuid4())[:8]}"
        agents[agent_id] = AI2Agent(role)
        return {
            "agent_id": agent_id,
            "role": role,
            "status": "created"
        }
    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agents", response_model=Dict[str, Any])
async def list_agents():
    """List all active agents"""
    return {
        "agents": [
            {"agent_id": agent_id, "role": agent.role}
            for agent_id, agent in agents.items()
        ]
    }

# Task processing endpoints
@app.post("/subtasks", response_model=SubtaskResponse)
async def process_subtask(subtask: SubtaskRequest, background_tasks: BackgroundTasks):
    """Process a subtask using an appropriate agent"""
    # Find or create an agent for the role
    agent = None
    for agent_id, existing_agent in agents.items():
        if existing_agent.role == subtask.role and agent_id not in active_tasks:
            agent = existing_agent
            break
    
    if not agent:
        # Create a new agent for this role
        agent_id = f"{subtask.role}-{str(uuid.uuid4())[:8]}"
        try:
            agent = AI2Agent(subtask.role)
            agents[agent_id] = agent
        except Exception as e:
            logger.error(f"Error creating agent: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Find the agent_id for the selected agent
        agent_id = next(id for id, a in agents.items() if a == agent)
    
    # Mark the agent as busy
    active_tasks[agent_id] = subtask.subtask_id
    
    # Process the subtask in the background
    async def process_and_report():
        try:
            result = await agent.process_subtask(subtask)
            if result.get("status") == "success" and "report" in result:
                await agent.send_report(result["report"])
            else:
                # If failed, send a failure report with retry count
                failure_report = {
                    "type": "failure",
                    "file": subtask.filename,
                    "subtask_id": subtask.subtask_id,
                    "retry_count": getattr(subtask, 'retry_count', 0),
                    "message": result.get("message", "Unknown error"),
                }
                await agent.send_report(failure_report)
        except Exception as e:
            logger.error(f"Error in background task: {e}")
            # Always send a failure report up the chain
            failure_report = {
                "type": "failure",
                "file": subtask.filename,
                "subtask_id": subtask.subtask_id,
                "retry_count": getattr(subtask, 'retry_count', 0),
                "message": str(e),
            }
            try:
                await agent.send_report(failure_report)
            except Exception as send_e:
                logger.error(f"Error sending failure report: {send_e}")
        finally:
            # Mark the agent as available again
            if agent_id in active_tasks:
                del active_tasks[agent_id]
    
    background_tasks.add_task(process_and_report)
    
    return SubtaskResponse(
        subtask_id=subtask.subtask_id,
        status="processing",
        message=f"Subtask assigned to agent {agent_id}"
    )

@app.get("/subtasks/{subtask_id}", response_model=Dict[str, Any])
async def get_subtask_status(subtask_id: str):
    """Get the status of a subtask"""
    # Find which agent is processing this subtask
    for agent_id, task_id in active_tasks.items():
        if task_id == subtask_id:
            return {
                "subtask_id": subtask_id,
                "status": "processing",
                "agent_id": agent_id,
                "agent_role": agents[agent_id].role
            }
    
    # If not found in active tasks, it's either completed or unknown
    return {
        "subtask_id": subtask_id,
        "status": "unknown"
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
            elif data.get("type") == "get_agents":
                # Send current agents status
                await websocket.send_json({
                    "type": "agents_status",
                    "data": {
                        "agents": [
                            {
                                "agent_id": agent_id,
                                "role": agent.role,
                                "busy": agent_id in active_tasks,
                                "current_task": active_tasks.get(agent_id)
                            }
                            for agent_id, agent in agents.items()
                        ]
                    }
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if websocket in manager.active_connections:
            manager.disconnect(websocket)

# Legacy endpoint for compatibility with old code
@app.post("/execute", response_model=AgentResponse)
async def execute_task(request: AgentRequest, background_tasks: BackgroundTasks):
    """Legacy endpoint for executing tasks"""
    try:
        # Create a subtask from the request
        subtask_id = str(uuid.uuid4())
        subtask = SubtaskRequest(
            subtask_id=subtask_id,
            task_text=request.task,
            role="executor",  # Default to executor role
            filename=request.context.get("filename", "output.txt"),
            code=request.context.get("code"),
            idea_md=request.context.get("idea_md")
        )
        
        # Process the subtask
        await process_subtask(subtask, background_tasks)
        
        return AgentResponse(
            result=f"Task submitted with ID: {subtask_id}",
            status="processing"
        )
    except Exception as e:
        logger.error(f"Error executing task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Development Agents Service')
    parser.add_argument('--port', type=int, default=7872, help='Port to run the service on')
    args = parser.parse_args()
    
    # Run the service
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=args.port,
        reload=True,
        log_level="info"
    )
