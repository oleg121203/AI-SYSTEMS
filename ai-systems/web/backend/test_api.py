#!/usr/bin/env python3
"""
Test script for Web Backend API
This script tests the integration of the Web Backend with all AI services
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from typing import Dict, Any

import aiohttp

# Configuration
API_URL = "http://localhost:8000"  # Update this if running in Docker


async def test_health():
    """Test the health endpoint"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/health") as response:
            print(f"Health check status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Health check response: {data}")
                return True
            return False


async def test_system_status():
    """Test the system status endpoint"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/status") as response:
            print(f"System status check: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"System status: {data['status']}")
                print(f"Services:")
                for service_name, service_status in data['services'].items():
                    print(f"  - {service_name}: {service_status.get('status', 'unknown')}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_create_project():
    """Test creating a project"""
    payload = {
        "name": "Test Project",
        "description": "A test project created by the API test script",
        "repository_url": "https://github.com/example/test-project",
        "idea_md": "# Test Project\n\nThis is a test project for the AI-SYSTEMS platform.\n\n## Features\n\n- Feature 1\n- Feature 2\n\n## Technologies\n\n- Python\n- FastAPI\n- React"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/projects", json=payload) as response:
            print(f"Create project status: {response.status}")
            if response.status == 201:
                data = await response.json()
                print(f"Project created: {data}")
                return data.get("id")
            print(f"Error: {await response.text()}")
            return None


async def test_get_projects():
    """Test getting all projects"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/projects") as response:
            print(f"Get projects status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Projects: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return []


async def test_get_project(project_id: str):
    """Test getting a specific project"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/projects/{project_id}") as response:
            print(f"Get project status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Project: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return None


async def test_create_project_plan(project_id: str):
    """Test creating a project plan"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/projects/{project_id}/plan") as response:
            print(f"Create project plan status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Project plan: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return None


async def test_start_project(project_id: str):
    """Test starting a project"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/projects/{project_id}/start") as response:
            print(f"Start project status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Project started: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return None


async def test_get_project_tasks(project_id: str):
    """Test getting project tasks"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/projects/{project_id}/tasks") as response:
            print(f"Get project tasks status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Project tasks: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return []


async def test_create_subtask():
    """Test creating a subtask"""
    subtask_id = str(uuid.uuid4())
    payload = {
        "subtask_id": subtask_id,
        "task_text": "Create a simple function to calculate factorial",
        "role": "executor",
        "filename": "factorial.py",
        "idea_md": "# Factorial Function\n\nImplement a recursive factorial function in Python."
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/subtasks", json=payload) as response:
            print(f"Create subtask status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Subtask created: {json.dumps(data, indent=2)}")
                return subtask_id
            print(f"Error: {await response.text()}")
            return None


async def test_get_subtask_status(subtask_id: str):
    """Test getting subtask status"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/api/subtasks/{subtask_id}") as response:
            print(f"Get subtask status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Subtask status: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return None


async def test_process_report():
    """Test processing a report"""
    payload = {
        "type": "code",
        "file": "factorial.py",
        "content": "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n-1)\n",
        "subtask_id": str(uuid.uuid4()),
        "message": "Generated factorial function"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/api/report", json=payload) as response:
            print(f"Process report status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Report processed: {json.dumps(data, indent=2)}")
                return data
            print(f"Error: {await response.text()}")
            return None


async def test_websocket():
    """Test WebSocket connection"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{API_URL}/ws") as ws:
                print("WebSocket connected")
                
                # Wait for initial system status
                msg = await ws.receive_json()
                print(f"Received: {msg['type']}")
                
                # Send ping
                await ws.send_json({"type": "ping"})
                msg = await ws.receive_json()
                print(f"Received response to ping: {msg['type']}")
                
                # Subscribe to a project (use a fake ID since we're just testing)
                await ws.send_json({"type": "subscribe", "project_id": "project-test"})
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    print(f"Received project data or error: {msg['type']}")
                except asyncio.TimeoutError:
                    print("No project data available")
                
                print("WebSocket test completed")
                return True
    except Exception as e:
        print(f"WebSocket error: {e}")
        return False


async def run_tests():
    """Run all tests"""
    print("Testing Web Backend API...")
    
    # Test health endpoint
    if not await test_health():
        print("Health check failed. Is the server running?")
        return
    
    # Test system status
    await test_system_status()
    
    # Test project lifecycle
    project_id = await test_create_project()
    if project_id:
        await test_get_project(project_id)
        await test_create_project_plan(project_id)
        await test_start_project(project_id)
        await test_get_project_tasks(project_id)
    
    # Test getting all projects
    await test_get_projects()
    
    # Test subtask lifecycle
    subtask_id = await test_create_subtask()
    if subtask_id:
        await test_get_subtask_status(subtask_id)
    
    # Test report processing
    await test_process_report()
    
    # Test WebSocket
    await test_websocket()
    
    print("All tests completed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
