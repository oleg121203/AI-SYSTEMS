#!/usr/bin/env python3
"""
Test script for Development Agents API
This script tests the basic functionality of the Development Agents API
"""

import asyncio
import json
import sys
import uuid
from typing import Dict, Any

import aiohttp

# Configuration
API_URL = "http://localhost:7862"  # Update this if running in Docker


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


async def test_create_agent(role: str) -> str:
    """Test creating an agent with a specific role"""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/agents/{role}") as response:
            print(f"Create agent status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Created agent: {data}")
                return data.get("agent_id", "")
            print(f"Error: {await response.text()}")
            return ""


async def test_list_agents():
    """Test listing all agents"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/agents") as response:
            print(f"List agents status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Agents: {data}")
                return data
            return {}


async def test_process_subtask(role: str, filename: str, task_text: str) -> str:
    """Test processing a subtask"""
    subtask_id = str(uuid.uuid4())
    payload = {
        "subtask_id": subtask_id,
        "task_text": task_text,
        "role": role,
        "filename": filename,
        "is_rework": False
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/subtasks", json=payload) as response:
            print(f"Process subtask status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Subtask response: {data}")
                return subtask_id
            print(f"Error: {await response.text()}")
            return ""


async def test_get_subtask_status(subtask_id: str):
    """Test getting the status of a subtask"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/subtasks/{subtask_id}") as response:
            print(f"Get subtask status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Subtask status: {data}")
                return data
            return {}


async def test_legacy_execute(task: str, context: Dict[str, Any] = None):
    """Test the legacy execute endpoint"""
    if context is None:
        context = {}
    
    payload = {
        "task": task,
        "context": context
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/execute", json=payload) as response:
            print(f"Legacy execute status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Legacy execute response: {data}")
                return data
            print(f"Error: {await response.text()}")
            return {}


async def run_tests():
    """Run all tests"""
    print("Testing Development Agents API...")
    
    # Test health endpoint
    if not await test_health():
        print("Health check failed. Is the server running?")
        return
    
    # Test creating agents for each role
    executor_id = await test_create_agent("executor")
    tester_id = await test_create_agent("tester")
    documenter_id = await test_create_agent("documenter")
    
    # Test listing agents
    await test_list_agents()
    
    # Test processing subtasks
    code_task = "Create a simple function that calculates the factorial of a number"
    test_task = "Write tests for the factorial function"
    doc_task = "Document the factorial function"
    
    code_subtask_id = await test_process_subtask("executor", "factorial.py", code_task)
    
    # Wait a bit for the task to be processed
    print("Waiting for task processing...")
    await asyncio.sleep(2)
    
    # Check subtask status
    if code_subtask_id:
        await test_get_subtask_status(code_subtask_id)
    
    # Test legacy execute endpoint
    await test_legacy_execute("Create a utility function", {"filename": "utils.py"})
    
    print("All tests completed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
