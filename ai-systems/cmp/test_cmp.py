#!/usr/bin/env python3
"""
Test script for Continuous Monitoring Platform API
This script tests the basic functionality of the CMP API
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from typing import Dict, Any

import aiohttp

# Configuration
API_URL = "http://localhost:7864"  # Update this if running in Docker


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


async def test_record_metric():
    """Test recording a metric"""
    payload = {
        "service": "test-service",
        "metric_name": "test-metric",
        "value": 42.0,
        "labels": {
            "instance_id": "test-1",
            "version": "1.0.0"
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/metrics/record", json=payload) as response:
            print(f"Record metric status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Record metric response: {data}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_start_task():
    """Test starting a task"""
    task_id = str(uuid.uuid4())
    payload = {
        "task_id": task_id,
        "service": "test-service",
        "task_type": "test-task",
        "start_time": datetime.now().isoformat(),
        "status": "running",
        "metadata": {
            "test": "data"
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/task/start", json=payload) as response:
            print(f"Start task status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Start task response: {data}")
                return task_id
            print(f"Error: {await response.text()}")
            return None


async def test_complete_task(task_id: str):
    """Test completing a task"""
    payload = {
        "task_id": task_id,
        "status": "completed",
        "metadata": {
            "result": "success"
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/task/complete", params={"task_id": task_id, "status": "completed"}, json=payload) as response:
            print(f"Complete task status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Complete task response: {data}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_log_error():
    """Test logging an error"""
    payload = {
        "service": "test-service",
        "error_type": "test-error",
        "message": "This is a test error",
        "trace": "Traceback (most recent call last):\n  File \"test.py\", line 42, in <module>\n    raise Exception('Test error')\nException: Test error",
        "metadata": {
            "test": "data"
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API_URL}/error/log", json=payload) as response:
            print(f"Log error status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Log error response: {data}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_get_services():
    """Test getting services"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/services") as response:
            print(f"Get services status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Services: {json.dumps(data, indent=2)}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_get_tasks():
    """Test getting tasks"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/tasks") as response:
            print(f"Get tasks status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Tasks: {json.dumps(data, indent=2)}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_get_errors():
    """Test getting errors"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{API_URL}/errors") as response:
            print(f"Get errors status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Errors: {json.dumps(data, indent=2)}")
                return True
            print(f"Error: {await response.text()}")
            return False


async def test_websocket():
    """Test WebSocket connection"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"{API_URL}/ws") as ws:
                print("WebSocket connected")
                
                # Wait for initial messages
                for _ in range(3):
                    msg = await ws.receive_json()
                    print(f"Received: {msg['type']}")
                
                # Send ping
                await ws.send_json({"type": "ping"})
                msg = await ws.receive_json()
                print(f"Received response to ping: {msg['type']}")
                
                # Request metrics history
                await ws.send_json({"type": "get_metrics_history", "metric_type": "cpu"})
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    print(f"Received metrics history: {msg['type']}")
                except asyncio.TimeoutError:
                    print("No metrics history available yet")
                
                # Request active tasks
                await ws.send_json({"type": "get_active_tasks"})
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                    print(f"Received active tasks: {msg['type']}")
                except asyncio.TimeoutError:
                    print("No active tasks available")
                
                print("WebSocket test completed")
                return True
    except Exception as e:
        print(f"WebSocket error: {e}")
        return False


async def run_tests():
    """Run all tests"""
    print("Testing Continuous Monitoring Platform API...")
    
    # Test health endpoint
    if not await test_health():
        print("Health check failed. Is the server running?")
        return
    
    # Test recording a metric
    await test_record_metric()
    
    # Test task lifecycle
    task_id = await test_start_task()
    if task_id:
        await test_complete_task(task_id)
    
    # Test logging an error
    await test_log_error()
    
    # Test getting services, tasks, and errors
    await test_get_services()
    await test_get_tasks()
    await test_get_errors()
    
    # Test WebSocket
    await test_websocket()
    
    print("All tests completed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
