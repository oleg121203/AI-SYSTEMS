#!/usr/bin/env python3
"""
AI Communication Module

This module standardizes communication between AI agents in the system.
It provides structured message passing, reliable delivery, and prioritization.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union, Callable

from config import load_config
from utils import log_message

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AI_COMM")

# Load configuration
config = load_config()

# Communication settings
MESSAGE_RETRY_ATTEMPTS = config.get("comm_retry_attempts", 3)
MESSAGE_RETRY_DELAY = config.get("comm_retry_delay", 2)  # seconds
MESSAGE_DELIVERY_TIMEOUT = config.get("comm_delivery_timeout", 30)  # seconds


class Priority(Enum):
    """Priority levels for messages between AI agents"""
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


class MessageType(Enum):
    """Types of messages that can be exchanged between AI agents"""
    STATUS_UPDATE = auto()
    ERROR_REPORT = auto()
    TASK_REQUEST = auto()
    TASK_RESPONSE = auto()
    TEST_RESULT = auto()
    CODE_UPDATE = auto()
    LOG_ANALYSIS = auto()
    SYSTEM_COMMAND = auto()


@dataclass
class Message:
    """Standard message format for inter-AI communication"""
    msg_id: str  # Unique message identifier
    msg_type: MessageType  # Type of message
    sender: str  # Sending AI (ai1, ai2, ai3)
    recipient: str  # Receiving AI (ai1, ai2, ai3, or 'all')
    priority: Priority  # Message priority
    timestamp: float  # Unix timestamp
    content: Dict[str, Any]  # Message content (structured based on msg_type)
    retry_count: int = 0  # Number of delivery attempts
    acknowledged: bool = False  # Whether message was acknowledged


# Message bus for in-memory communication
_message_bus = {
    "ai1": asyncio.Queue(),
    "ai2": asyncio.Queue(),
    "ai3": asyncio.Queue(),
    "all": asyncio.Queue(),  # Broadcast queue
}

# Message history for debugging and recovery
_message_history: List[Message] = []
_message_history_max_size = config.get("message_history_max_size", 100)

# Delivery status tracking
_delivery_status: Dict[str, str] = {}  # msg_id -> status
_callbacks: Dict[str, List[Callable]] = {}  # msg_id -> callbacks list


async def send_message(
    sender: str,
    recipient: str,
    msg_type: MessageType,
    content: Dict[str, Any],
    priority: Priority = Priority.MEDIUM,
) -> str:
    """
    Send a message to another AI agent through the message bus.
    
    Args:
        sender: Sending AI identifier (ai1, ai2, ai3)
        recipient: Receiving AI identifier (ai1, ai2, ai3, or 'all')
        msg_type: Type of message being sent
        content: Dictionary containing the message payload
        priority: Message priority level
        
    Returns:
        str: Message ID if successfully queued, raises exception otherwise
    """
    # Validate parameters
    if sender not in ["ai1", "ai2", "ai3", "mcp"]:
        raise ValueError(f"Invalid sender: {sender}")
    if recipient not in ["ai1", "ai2", "ai3", "all", "mcp"]:
        raise ValueError(f"Invalid recipient: {recipient}")
    if recipient == sender:
        logger.warning(f"Message from {sender} sent to itself, this may cause issues")
    
    # Create message object
    msg_id = f"{int(time.time())}-{sender}-{os.urandom(4).hex()}"
    message = Message(
        msg_id=msg_id,
        msg_type=msg_type,
        sender=sender,
        recipient=recipient,
        priority=priority,
        timestamp=time.time(),
        content=content,
    )
    
    # Add to message history
    _message_history.append(message)
    if len(_message_history) > _message_history_max_size:
        _message_history.pop(0)  # Remove oldest message
    
    # Queue the message
    try:
        if recipient == "all":
            # Broadcast to all AIs except sender
            for ai_id in ["ai1", "ai2", "ai3"]:
                if ai_id != sender:
                    await _message_bus[ai_id].put(message)
            logger.debug(f"Message {msg_id} broadcast from {sender} to all AIs")
        else:
            # Direct message to specific recipient
            await _message_bus[recipient].put(message)
            logger.debug(f"Message {msg_id} queued from {sender} to {recipient}")
        
        _delivery_status[msg_id] = "queued"
        return msg_id
    except Exception as e:
        logger.error(f"Failed to send message from {sender} to {recipient}: {e}")
        raise


async def get_messages(ai_id: str, timeout: float = 0.1) -> List[Message]:
    """
    Get all pending messages for an AI agent.
    
    Args:
        ai_id: AI identifier to get messages for
        timeout: Maximum time to wait for messages
        
    Returns:
        List of Message objects
    """
    if ai_id not in _message_bus:
        raise ValueError(f"Invalid AI ID: {ai_id}")
    
    messages = []
    try:
        # Get all available messages without blocking
        while True:
            try:
                message = _message_bus[ai_id].get_nowait()
                messages.append(message)
                # Mark as received
                _delivery_status[message.msg_id] = "received"
            except asyncio.QueueEmpty:
                # If queue is empty but we have some messages, return them
                if messages:
                    break
                # Otherwise wait for a message with timeout
                try:
                    message = await asyncio.wait_for(_message_bus[ai_id].get(), timeout)
                    messages.append(message)
                    _delivery_status[message.msg_id] = "received"
                    break
                except asyncio.TimeoutError:
                    # Return empty list if no messages arrived within timeout
                    break
    except Exception as e:
        logger.error(f"Error retrieving messages for {ai_id}: {e}")
    
    return messages


async def acknowledge_message(msg_id: str, ai_id: str) -> bool:
    """
    Acknowledge receipt of a message.
    
    Args:
        msg_id: Message ID to acknowledge
        ai_id: AI ID that received the message
        
    Returns:
        bool: True if successful, False otherwise
    """
    if msg_id in _delivery_status:
        _delivery_status[msg_id] = "acknowledged"
        
        # Find message in history and mark as acknowledged
        for msg in _message_history:
            if msg.msg_id == msg_id:
                msg.acknowledged = True
                break
        
        # Process any callbacks
        if msg_id in _callbacks:
            for callback in _callbacks[msg_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(msg_id)
                    else:
                        callback(msg_id)
                except Exception as e:
                    logger.error(f"Error in message callback for {msg_id}: {e}")
            
            # Clear callbacks after processing
            _callbacks.pop(msg_id, None)
        
        logger.debug(f"Message {msg_id} acknowledged by {ai_id}")
        return True
    else:
        logger.warning(f"Attempted to acknowledge unknown message {msg_id}")
        return False


async def register_callback(msg_id: str, callback: Callable) -> bool:
    """
    Register a callback function to be called when a message is acknowledged.
    
    Args:
        msg_id: Message ID to attach callback to
        callback: Function to call when message is acknowledged
        
    Returns:
        bool: True if successful, False otherwise
    """
    if msg_id not in _delivery_status:
        logger.warning(f"Attempted to register callback for unknown message {msg_id}")
        return False
    
    if msg_id not in _callbacks:
        _callbacks[msg_id] = []
    
    _callbacks[msg_id].append(callback)
    logger.debug(f"Callback registered for message {msg_id}")
    return True


# ----- High-level communication functions -----

async def send_error_report(
    sender: str,
    error_type: str,
    message: str,
    file_path: Optional[str] = None,
    stack_trace: Optional[str] = None,
    severity: Priority = Priority.MEDIUM,
) -> str:
    """
    Send an error report to AI1.
    
    Args:
        sender: AI reporting the error (ai2, ai3)
        error_type: Type of error (e.g., "system_error", "logic_error")
        message: Error message
        file_path: Path to file where error occurred (if applicable)
        stack_trace: Stack trace (if available)
        severity: Error severity
        
    Returns:
        str: Message ID
    """
    content = {
        "error_type": error_type,
        "message": message,
        "timestamp": time.time(),
    }
    
    if file_path:
        content["file_path"] = file_path
    if stack_trace:
        content["stack_trace"] = stack_trace
    
    # Errors are always sent to AI1 for centralized handling
    return await send_message(
        sender=sender,
        recipient="ai1",
        msg_type=MessageType.ERROR_REPORT,
        content=content,
        priority=severity,
    )


async def send_test_result(
    sender: str,
    file_path: str,
    passed: bool,
    test_output: str,
    priority: Priority = Priority.MEDIUM,
) -> str:
    """
    Send test results from AI2 to both AI1 and AI3.
    
    Args:
        sender: AI sending test results (typically ai2)
        file_path: Path to file that was tested
        passed: Whether tests passed
        test_output: Output from test run
        priority: Message priority
        
    Returns:
        str: Message ID for broadcast
    """
    content = {
        "file_path": file_path,
        "passed": passed,
        "test_output": test_output,
        "timestamp": time.time(),
    }
    
    # Send test results to both AI1 and AI3
    return await send_message(
        sender=sender,
        recipient="all",  # Broadcast to all AIs
        msg_type=MessageType.TEST_RESULT,
        content=content,
        priority=priority,
    )


async def request_code_fix(
    sender: str,
    file_path: str,
    issues: List[Dict[str, Any]],
    priority: Priority = Priority.MEDIUM,
) -> str:
    """
    Request AI2 to fix code based on issues found by AI3.
    
    Args:
        sender: AI requesting the fix (typically ai3)
        file_path: Path to file needing fixes
        issues: List of issues to fix (each with line, message, severity)
        priority: Message priority
        
    Returns:
        str: Message ID
    """
    content = {
        "file_path": file_path,
        "issues": issues,
        "timestamp": time.time(),
    }
    
    # Code fix requests go to AI2
    return await send_message(
        sender=sender,
        recipient="ai2",
        msg_type=MessageType.TASK_REQUEST,
        content=content,
        priority=priority,
    )


async def send_log_analysis(
    sender: str,
    log_file: str,
    findings: List[Dict[str, Any]],
    recommendation: str,
    priority: Priority = Priority.MEDIUM,
) -> str:
    """
    Send log analysis results from AI3 to AI1.
    
    Args:
        sender: AI sending analysis (typically ai3)
        log_file: Path to log file analyzed
        findings: List of findings from log analysis
        recommendation: Recommended action
        priority: Message priority
        
    Returns:
        str: Message ID
    """
    content = {
        "log_file": log_file,
        "findings": findings,
        "recommendation": recommendation,
        "timestamp": time.time(),
    }
    
    # Log analysis goes to AI1 for decision making
    return await send_message(
        sender=sender,
        recipient="ai1",
        msg_type=MessageType.LOG_ANALYSIS,
        content=content,
        priority=priority,
    )


async def process_incoming_messages(ai_id: str, handler_map: Dict[MessageType, Callable]) -> None:
    """
    Process incoming messages for an AI agent using registered handlers.
    
    Args:
        ai_id: AI identifier to process messages for
        handler_map: Dictionary mapping message types to handler functions
        
    Returns:
        None
    """
    messages = await get_messages(ai_id)
    
    for message in messages:
        if message.msg_type in handler_map:
            handler = handler_map[message.msg_type]
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
                
                # Acknowledge message after successful processing
                await acknowledge_message(message.msg_id, ai_id)
            except Exception as e:
                logger.error(f"Error processing message {message.msg_id} in {ai_id}: {e}")
        else:
            logger.warning(f"No handler for message type {message.msg_type} in {ai_id}")
            # Still acknowledge even if no handler
            await acknowledge_message(message.msg_id, ai_id)


# ----- Monitoring and diagnostics -----

def get_message_history() -> List[Dict[str, Any]]:
    """
    Get message history for diagnostics.
    
    Returns:
        List of message data dictionaries
    """
    history = []
    for msg in _message_history:
        history.append({
            "msg_id": msg.msg_id,
            "msg_type": msg.msg_type.name,
            "sender": msg.sender,
            "recipient": msg.recipient,
            "priority": msg.priority.name,
            "timestamp": msg.timestamp,
            "content_summary": str(msg.content)[:100] + "..." if len(str(msg.content)) > 100 else str(msg.content),
            "acknowledged": msg.acknowledged,
            "delivery_status": _delivery_status.get(msg.msg_id, "unknown"),
        })
    return history


def get_queue_status() -> Dict[str, int]:
    """
    Get status of message queues.
    
    Returns:
        Dictionary with queue sizes
    """
    return {
        ai_id: queue.qsize() for ai_id, queue in _message_bus.items()
    }


# ----- Message handler example -----

# This example shows how to create a handler map for an AI agent
async def example_handler_map():
    handler_map = {
        MessageType.ERROR_REPORT: handle_error_report,
        MessageType.TEST_RESULT: handle_test_result,
        MessageType.TASK_REQUEST: handle_task_request,
        # Add more handlers as needed
    }
    return handler_map


async def handle_error_report(message: Message):
    """Example handler for error reports"""
    error_type = message.content.get("error_type", "unknown")
    error_message = message.content.get("message", "No details")
    log_message(f"[AI Communication] Received error report: {error_type} - {error_message}")


async def handle_test_result(message: Message):
    """Example handler for test results"""
    file_path = message.content.get("file_path", "unknown")
    passed = message.content.get("passed", False)
    log_message(f"[AI Communication] Received test result for {file_path}: {'PASSED' if passed else 'FAILED'}")


async def handle_task_request(message: Message):
    """Example handler for task requests"""
    file_path = message.content.get("file_path", "unknown")
    issues = message.content.get("issues", [])
    log_message(f"[AI Communication] Received task request for {file_path} with {len(issues)} issues")


# ----- Main function for testing -----

async def test_communication():
    """Test function to simulate message exchange"""
    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Send test messages
    msg_id1 = await send_error_report(
        sender="ai3",
        error_type="system_error",
        message="Test error message",
        file_path="test.py",
        stack_trace="Traceback...",
        severity=Priority.HIGH,
    )
    
    msg_id2 = await send_test_result(
        sender="ai2",
        file_path="test.py",
        passed=True,
        test_output="All tests passed!",
    )
    
    # Get messages for each AI
    ai1_messages = await get_messages("ai1")
    ai2_messages = await get_messages("ai2")
    ai3_messages = await get_messages("ai3")
    
    # Print results
    print(f"AI1 has {len(ai1_messages)} messages")
    print(f"AI2 has {len(ai2_messages)} messages")
    print(f"AI3 has {len(ai3_messages)} messages")
    
    # Acknowledge messages
    if ai1_messages:
        await acknowledge_message(ai1_messages[0].msg_id, "ai1")
    
    # Show message history
    print("\nMessage History:")
    for msg in get_message_history():
        print(f"{msg['msg_id']}: {msg['sender']} -> {msg['recipient']} [{msg['msg_type']}] {msg['delivery_status']}")
    
    # Show queue status
    print("\nQueue Status:")
    status = get_queue_status()
    for ai_id, size in status.items():
        print(f"{ai_id}: {size} messages")


if __name__ == "__main__":
    asyncio.run(test_communication())