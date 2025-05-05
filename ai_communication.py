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
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp
import async_timeout

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
MCP_API_URL = config.get("mcp_api", "http://localhost:7860")


class Priority(Enum):
    """Priority levels for messages between AI agents"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MessageType(Enum):
    """Types of messages that can be exchanged between AI agents"""

    ERROR = "error"
    STATUS = "status"
    TASK = "task"
    RESULT = "result"
    INSIGHT = "insight"
    COLLABORATION = "collaboration"
    SYSTEM = "system"


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


class MessageBus:
    """Centralized message bus for AI component communication"""

    def __init__(self):
        self.subscribers = defaultdict(list)
        self.message_history = []
        self.error_patterns = defaultdict(int)
        self.success_patterns = defaultdict(int)
        self.pattern_recognition = PatternLearner()
        self.recovery_strategies = {}
        self.max_history = 1000
        self.lock = asyncio.Lock()

    async def publish(self, topic: str, message: Dict[str, Any]) -> None:
        """Publish a message to all subscribers of a topic"""
        async with self.lock:
            timestamp = datetime.now().isoformat()
            message_id = str(uuid.uuid4())
            enriched_message = {
                "id": message_id,
                "timestamp": timestamp,
                "topic": topic,
                "content": message,
                "sender": message.get("sender", "unknown"),
            }

            # Store in history with timestamp
            self.message_history.append(enriched_message)
            if len(self.message_history) > self.max_history:
                self.message_history.pop(0)

            # Learn from successful messages
            if message.get("status") == "success":
                await self.pattern_recognition.learn_success_pattern(topic, message)

            # Track error patterns for recovery
            if "error" in message:
                await self.handle_error(topic, message)

            # Notify subscribers
            tasks = []
            for callback in self.subscribers[topic]:
                tasks.append(
                    asyncio.create_task(self._safe_notify(callback, enriched_message))
                )

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Trigger recovery if needed
            if "error" in message and topic in self.recovery_strategies:
                await self.trigger_recovery(topic, enriched_message)

    async def _safe_notify(self, callback, message: Dict[str, Any]) -> None:
        """Safely execute subscriber callback with timeout and error handling"""
        try:
            async with async_timeout.timeout(10):  # 10 second timeout
                await callback(message)
        except asyncio.TimeoutError:
            logger.error(f"Timeout notifying subscriber for message {message['id']}")
        except Exception as e:
            logger.error(f"Error notifying subscriber: {e}", exc_info=True)

    async def subscribe(self, topic: str, callback: Callable) -> None:
        """Subscribe to a topic with a callback function"""
        async with self.lock:
            if callback not in self.subscribers[topic]:
                self.subscribers[topic].append(callback)
                logger.info(f"New subscriber added for topic: {topic}")

    async def unsubscribe(self, topic: str, callback: Callable) -> None:
        """Unsubscribe from a topic"""
        async with self.lock:
            if callback in self.subscribers[topic]:
                self.subscribers[topic].remove(callback)
                logger.info(f"Subscriber removed from topic: {topic}")

    async def handle_error(self, topic: str, message: Dict[str, Any]) -> None:
        """Handle error messages and update error patterns"""
        error = message.get("error", "")
        error_type = self._categorize_error(error)
        self.error_patterns[error_type] += 1

        # Update pattern recognition
        await self.pattern_recognition.learn_error_pattern(topic, message)

        # Log error pattern detection
        if self.error_patterns[error_type] >= 3:
            logger.warning(f"Recurring error pattern detected: {error_type}")
            await self.notify_error_pattern(error_type, self.error_patterns[error_type])

    def _categorize_error(self, error: str) -> str:
        """Categorize error messages into types"""
        if "timeout" in error.lower():
            return "timeout"
        elif "permission" in error.lower():
            return "permission"
        elif "not found" in error.lower():
            return "not_found"
        elif "syntax" in error.lower():
            return "syntax"
        elif "validation" in error.lower():
            return "validation"
        return "unknown"

    async def notify_error_pattern(self, error_type: str, count: int) -> None:
        """Notify about recurring error patterns"""
        await self.publish(
            "error_patterns",
            {
                "type": error_type,
                "count": count,
                "timestamp": datetime.now().isoformat(),
            },
        )

    async def register_recovery_strategy(self, topic: str, strategy: Callable) -> None:
        """Register a recovery strategy for a topic"""
        self.recovery_strategies[topic] = strategy
        logger.info(f"Recovery strategy registered for topic: {topic}")

    async def trigger_recovery(self, topic: str, message: Dict[str, Any]) -> None:
        """Trigger recovery strategy for a topic"""
        if topic in self.recovery_strategies:
            try:
                await self.recovery_strategies[topic](message)
            except Exception as e:
                logger.error(
                    f"Error in recovery strategy for {topic}: {e}", exc_info=True
                )

    async def get_topic_status(self, topic: str) -> Dict[str, Any]:
        """Get current status of a topic including error patterns"""
        messages = [m for m in self.message_history if m["topic"] == topic]
        error_count = len([m for m in messages if "error" in m["content"]])
        success_count = len(
            [m for m in messages if m["content"].get("status") == "success"]
        )

        return {
            "total_messages": len(messages),
            "error_count": error_count,
            "success_count": success_count,
            "error_patterns": dict(self.error_patterns),
            "last_message": messages[-1] if messages else None,
        }


class PatternLearner:
    """Learns patterns from message flow for improved error recovery"""

    def __init__(self):
        self.error_patterns = defaultdict(list)
        self.success_patterns = defaultdict(list)
        self.pattern_weights = defaultdict(float)
        self.min_confidence = 0.7

    async def learn_error_pattern(self, topic: str, message: Dict[str, Any]) -> None:
        """Learn from error messages"""
        pattern = self._extract_pattern(message)
        self.error_patterns[topic].append(pattern)

        # Update pattern weights
        if len(self.error_patterns[topic]) > 1:
            self._update_pattern_weights(topic, pattern, is_error=True)

    async def learn_success_pattern(self, topic: str, message: Dict[str, Any]) -> None:
        """Learn from successful messages"""
        pattern = self._extract_pattern(message)
        self.success_patterns[topic].append(pattern)

        # Update pattern weights
        if len(self.success_patterns[topic]) > 1:
            self._update_pattern_weights(topic, pattern, is_error=False)

    def _extract_pattern(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant pattern features from a message"""
        return {
            "structure": self._get_message_structure(message),
            "content_type": self._get_content_type(message),
            "size": self._get_message_size(message),
            "timing": datetime.now().timestamp(),
        }

    def _get_message_structure(self, message: Dict[str, Any]) -> str:
        """Get the structural pattern of a message"""

        def get_structure(obj):
            if isinstance(obj, dict):
                return {k: get_structure(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [get_structure(x) for x in obj]
            else:
                return type(obj).__name__

        return str(get_structure(message))

    def _get_content_type(self, message: Dict[str, Any]) -> str:
        """Determine the content type of a message"""
        content = message.get("content", {})
        if isinstance(content, dict):
            if "code" in content:
                return "code"
            elif "error" in content:
                return "error"
            elif "status" in content:
                return "status"
        return "unknown"

    def _get_message_size(self, message: Dict[str, Any]) -> int:
        """Get the size category of a message"""
        size = len(str(message))
        if size < 1000:
            return "small"
        elif size < 10000:
            return "medium"
        return "large"

    def _update_pattern_weights(
        self, topic: str, pattern: Dict[str, Any], is_error: bool
    ) -> None:
        """Update pattern weights based on new observations"""
        key = f"{topic}:{pattern['structure']}"
        if is_error:
            self.pattern_weights[key] *= 0.9  # Decrease weight for error patterns
        else:
            self.pattern_weights[key] *= 1.1  # Increase weight for success patterns

        # Normalize weights
        max_weight = max(self.pattern_weights.values())
        if max_weight > 0:
            for k in self.pattern_weights:
                self.pattern_weights[k] /= max_weight

    async def get_pattern_prediction(
        self, topic: str, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Predict if a message matches known patterns"""
        pattern = self._extract_pattern(message)
        key = f"{topic}:{pattern['structure']}"

        confidence = self.pattern_weights.get(key, 0.5)
        prediction = {
            "matches_success_pattern": confidence > self.min_confidence,
            "confidence": confidence,
            "similar_patterns": self._find_similar_patterns(topic, pattern),
        }

        return prediction

    def _find_similar_patterns(
        self, topic: str, pattern: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find patterns similar to the given one"""
        similar = []
        for stored_pattern in self.success_patterns[topic]:
            similarity = self._calculate_similarity(pattern, stored_pattern)
            if similarity > 0.8:  # 80% similarity threshold
                similar.append({"pattern": stored_pattern, "similarity": similarity})
        return sorted(similar, key=lambda x: x["similarity"], reverse=True)[:3]

    def _calculate_similarity(
        self, pattern1: Dict[str, Any], pattern2: Dict[str, Any]
    ) -> float:
        """Calculate similarity between two patterns"""
        structure_match = pattern1["structure"] == pattern2["structure"]
        content_match = pattern1["content_type"] == pattern2["content_type"]
        size_match = pattern1["size"] == pattern2["size"]

        weights = {"structure": 0.5, "content": 0.3, "size": 0.2}
        similarity = (
            (structure_match * weights["structure"])
            + (content_match * weights["content"])
            + (size_match * weights["size"])
        )

        return similarity


class ErrorRecoveryManager:
    """Manages error recovery strategies and execution"""

    def __init__(self, message_bus: MessageBus):
        self.message_bus = message_bus
        self.recovery_attempts = defaultdict(int)
        self.max_attempts = 3
        self.cooldown_periods = defaultdict(float)
        self.lock = asyncio.Lock()

    async def register_strategies(self):
        """Register recovery strategies for different error types"""
        await self.message_bus.register_recovery_strategy(
            "code_generation", self.handle_code_generation_error
        )
        await self.message_bus.register_recovery_strategy(
            "test_execution", self.handle_test_error
        )
        await self.message_bus.register_recovery_strategy(
            "documentation", self.handle_documentation_error
        )

    async def handle_code_generation_error(self, message: Dict[str, Any]) -> None:
        """Handle code generation errors"""
        error_type = self.message_bus._categorize_error(
            message["content"].get("error", "")
        )
        message_id = message["id"]

        async with self.lock:
            if self.recovery_attempts[message_id] >= self.max_attempts:
                logger.error(f"Max recovery attempts reached for message {message_id}")
                return

            if time.time() < self.cooldown_periods.get(message_id, 0):
                logger.info(f"In cooldown period for message {message_id}")
                return

            self.recovery_attempts[message_id] += 1

            try:
                if error_type == "timeout":
                    await self._handle_timeout_error(message)
                elif error_type == "validation":
                    await self._handle_validation_error(message)
                else:
                    await self._handle_generic_error(message)

                # Set cooldown period
                self.cooldown_periods[message_id] = time.time() + (
                    30 * self.recovery_attempts[message_id]
                )

            except Exception as e:
                logger.error(f"Error in recovery handler: {e}", exc_info=True)

    async def _handle_timeout_error(self, message: Dict[str, Any]) -> None:
        """Handle timeout-specific errors"""
        # Implement timeout-specific recovery logic
        # For example, retry with increased timeout or split task
        pass

    async def _handle_validation_error(self, message: Dict[str, Any]) -> None:
        """Handle validation-specific errors"""
        # Implement validation-specific recovery logic
        # For example, adjust parameters or try alternative approach
        pass

    async def _handle_generic_error(self, message: Dict[str, Any]) -> None:
        """Handle generic errors"""
        # Implement generic error recovery logic
        # For example, retry with modified parameters
        pass

    async def handle_test_error(self, message: Dict[str, Any]) -> None:
        """Handle test execution errors"""
        # Implement test error recovery logic
        pass

    async def handle_documentation_error(self, message: Dict[str, Any]) -> None:
        """Handle documentation generation errors"""
        # Implement documentation error recovery logic
        pass


# Global message bus instance
_message_bus: Optional[MessageBus] = None


async def get_message_bus() -> MessageBus:
    """Gets or creates the global message bus instance"""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus


async def send_error_report(
    sender: str,
    error_type: str,
    message: str,
    file_path: Optional[str] = None,
    stack_trace: Optional[str] = None,
    severity: Priority = Priority.HIGH,
) -> bool:
    """Convenience function to send error reports"""
    bus = await get_message_bus()
    return await bus.send_error_report(
        sender=sender,
        error_type=error_type,
        message=message,
        file_path=file_path,
        stack_trace=stack_trace,
        severity=severity,
    )


async def send_status_update(
    sender: str,
    status: str,
    details: Optional[Dict] = None,
    priority: Priority = Priority.LOW,
) -> bool:
    """Convenience function to send status updates"""
    bus = await get_message_bus()
    return await bus.send_status_update(
        sender=sender, status=status, details=details, priority=priority
    )


async def send_insight(
    sender: str,
    insight_type: str,
    data: Dict[str, Any],
    priority: Priority = Priority.MEDIUM,
) -> bool:
    """Convenience function to send insights"""
    bus = await get_message_bus()
    return await bus.send_insight(
        sender=sender, insight_type=insight_type, data=data, priority=priority
    )


async def request_collaboration(
    sender: str, issue: str, context: Dict[str, Any], priority: Priority = Priority.HIGH
) -> bool:
    """Convenience function to request collaboration"""
    bus = await get_message_bus()
    return await bus.request_collaboration(
        sender=sender, issue=issue, context=context, priority=priority
    )


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
        msg_type=MessageType.ERROR,
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
        msg_type=MessageType.RESULT,
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
        msg_type=MessageType.TASK,
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
        msg_type=MessageType.INSIGHT,
        content=content,
        priority=priority,
    )


async def process_incoming_messages(
    ai_id: str, handler_map: Dict[MessageType, Callable]
) -> None:
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
                logger.error(
                    f"Error processing message {message.msg_id} in {ai_id}: {e}"
                )
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
        history.append(
            {
                "msg_id": msg.msg_id,
                "msg_type": msg.msg_type.name,
                "sender": msg.sender,
                "recipient": msg.recipient,
                "priority": msg.priority.name,
                "timestamp": msg.timestamp,
                "content_summary": (
                    str(msg.content)[:100] + "..."
                    if len(str(msg.content)) > 100
                    else str(msg.content)
                ),
                "acknowledged": msg.acknowledged,
                "delivery_status": _delivery_status.get(msg.msg_id, "unknown"),
            }
        )
    return history


def get_queue_status() -> Dict[str, int]:
    """
    Get status of message queues.

    Returns:
        Dictionary with queue sizes
    """
    return {ai_id: queue.qsize() for ai_id, queue in _message_bus.items()}


# ----- Message handler example -----


# This example shows how to create a handler map for an AI agent
async def example_handler_map():
    handler_map = {
        MessageType.ERROR: handle_error_report,
        MessageType.RESULT: handle_test_result,
        MessageType.TASK: handle_task_request,
        # Add more handlers as needed
    }
    return handler_map


async def handle_error_report(message: Message):
    """Example handler for error reports"""
    error_type = message.content.get("error_type", "unknown")
    error_message = message.content.get("message", "No details")
    log_message(
        f"[AI Communication] Received error report: {error_type} - {error_message}"
    )


async def handle_test_result(message: Message):
    """Example handler for test results"""
    file_path = message.content.get("file_path", "unknown")
    passed = message.content.get("passed", False)
    log_message(
        f"[AI Communication] Received test result for {file_path}: {'PASSED' if passed else 'FAILED'}"
    )


async def handle_task_request(message: Message):
    """Example handler for task requests"""
    file_path = message.content.get("file_path", "unknown")
    issues = message.content.get("issues", [])
    log_message(
        f"[AI Communication] Received task request for {file_path} with {len(issues)} issues"
    )


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
        print(
            f"{msg['msg_id']}: {msg['sender']} -> {msg['recipient']} [{msg['msg_type']}] {msg['delivery_status']}"
        )

    # Show queue status
    print("\nQueue Status:")
    status = get_queue_status()
    for ai_id, size in status.items():
        print(f"{ai_id}: {size} messages")


if __name__ == "__main__":
    asyncio.run(test_communication())

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiohttp


class AICommunicationManager:
    """Advanced AI component communication and coordination manager"""

    def __init__(self):
        self.message_queue = asyncio.Queue()
        self.response_queues = {}
        self.active_sessions = {}
        self.pattern_cache = {}
        self.error_recovery_strategies = self._init_recovery_strategies()
        self.logger = logging.getLogger(__name__)

    async def send_message(
        self, sender: str, recipient: str, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send message between AI components with enhanced error handling"""
        session_id = f"{sender}-{recipient}-{datetime.now().isoformat()}"
        try:
            # Add context and metadata
            enhanced_message = await self._enhance_message(message, sender, recipient)

            # Queue message
            await self.message_queue.put(
                {
                    "session_id": session_id,
                    "sender": sender,
                    "recipient": recipient,
                    "message": enhanced_message,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Create response queue
            self.response_queues[session_id] = asyncio.Queue()

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(
                    self.response_queues[session_id].get(),
                    timeout=300,  # 5 minute timeout
                )
                return response
            except asyncio.TimeoutError:
                await self._handle_timeout(session_id, sender, recipient)
                return {"status": "error", "message": "Request timed out"}

        except Exception as e:
            self.logger.error(f"Error in send_message: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _enhance_message(
        self, message: Dict[str, Any], sender: str, recipient: str
    ) -> Dict[str, Any]:
        """Enhance message with context and patterns"""
        enhanced = message.copy()

        # Add timestamp and message ID
        enhanced["timestamp"] = datetime.now().isoformat()
        enhanced["message_id"] = f"{sender}-{recipient}-{len(self.pattern_cache)}"

        # Add relevant patterns from cache
        patterns = await self._get_relevant_patterns(message)
        if patterns:
            enhanced["patterns"] = patterns

        # Add execution context
        enhanced["context"] = await self._get_execution_context(sender, recipient)

        return enhanced

    async def _get_relevant_patterns(
        self, message: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get relevant patterns from pattern cache"""
        relevant_patterns = []
        message_type = message.get("type", "")

        if message_type in self.pattern_cache:
            patterns = self.pattern_cache[message_type]
            for pattern in patterns:
                if await self._pattern_matches(pattern, message):
                    relevant_patterns.append(pattern)

        return relevant_patterns

    async def _pattern_matches(
        self, pattern: Dict[str, Any], message: Dict[str, Any]
    ) -> bool:
        """Check if a pattern matches the message"""
        try:
            if "conditions" not in pattern:
                return False

            for condition in pattern["conditions"]:
                if not await self._evaluate_condition(condition, message):
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Error matching pattern: {e}")
            return False

    async def _evaluate_condition(
        self, condition: Dict[str, Any], message: Dict[str, Any]
    ) -> bool:
        """Evaluate a single pattern matching condition"""
        try:
            field = condition["field"]
            operator = condition["operator"]
            value = condition["value"]

            if field not in message:
                return False

            msg_value = message[field]

            if operator == "equals":
                return msg_value == value
            elif operator == "contains":
                return value in msg_value
            elif operator == "regex":
                import re

                return bool(re.match(value, str(msg_value)))
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error evaluating condition: {e}")
            return False

    async def _get_execution_context(
        self, sender: str, recipient: str
    ) -> Dict[str, Any]:
        """Get relevant execution context for the communication"""
        context = {
            "timestamp": datetime.now().isoformat(),
            "sender_state": await self._get_component_state(sender),
            "recipient_state": await self._get_component_state(recipient),
            "active_sessions": len(self.active_sessions),
            "queue_size": self.message_queue.qsize(),
        }
        return context

    async def _get_component_state(self, component: str) -> Dict[str, Any]:
        """Get current state of an AI component"""
        if component in self.active_sessions:
            session = self.active_sessions[component]
            return {
                "status": "active",
                "last_seen": session["last_seen"],
                "message_count": session["message_count"],
            }
        return {"status": "inactive"}

    async def _handle_timeout(self, session_id: str, sender: str, recipient: str):
        """Handle communication timeout with recovery strategies"""
        self.logger.warning(f"Communication timeout for session {session_id}")

        # Try recovery strategies
        for strategy in self.error_recovery_strategies:
            try:
                success = await strategy(session_id, sender, recipient)
                if success:
                    self.logger.info(f"Successfully recovered session {session_id}")
                    return
            except Exception as e:
                self.logger.error(f"Error in recovery strategy: {e}")

        # Clean up if recovery failed
        if session_id in self.response_queues:
            del self.response_queues[session_id]

    def _init_recovery_strategies(self) -> List[callable]:
        """Initialize error recovery strategies"""
        return [
            self._retry_message,
            self._check_component_health,
            self._reset_connection,
        ]

    async def _retry_message(
        self, session_id: str, sender: str, recipient: str
    ) -> bool:
        """Retry sending the message"""
        try:
            if session_id not in self.active_sessions:
                return False

            original_message = self.active_sessions[session_id]["message"]
            # Retry with exponential backoff
            for i in range(3):  # 3 retries
                try:
                    await asyncio.sleep(2**i)  # Exponential backoff
                    await self.send_message(sender, recipient, original_message)
                    return True
                except Exception as e:
                    self.logger.error(f"Retry {i+1} failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error in retry_message: {e}")
            return False

    async def _check_component_health(
        self, session_id: str, sender: str, recipient: str
    ) -> bool:
        """Check health of AI components"""
        try:
            # Check sender health
            sender_healthy = await self._check_health(sender)
            if not sender_healthy:
                self.logger.error(f"Sender {sender} is unhealthy")
                return False

            # Check recipient health
            recipient_healthy = await self._check_health(recipient)
            if not recipient_healthy:
                self.logger.error(f"Recipient {recipient} is unhealthy")
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error checking component health: {e}")
            return False

    async def _check_health(self, component: str) -> bool:
        """Check health of a specific component"""
        try:
            # Send health check message
            health_check = {
                "type": "health_check",
                "timestamp": datetime.now().isoformat(),
            }

            response = await self.send_message("system", component, health_check)
            return response.get("status") == "healthy"
        except Exception:
            return False

    async def _reset_connection(
        self, session_id: str, sender: str, recipient: str
    ) -> bool:
        """Reset connection between components"""
        try:
            # Clear session state
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]

            # Clear response queue
            if session_id in self.response_queues:
                del self.response_queues[session_id]

            # Initialize new session
            self.active_sessions[session_id] = {
                "start_time": datetime.now().isoformat(),
                "message_count": 0,
                "last_seen": datetime.now().isoformat(),
            }

            return True
        except Exception as e:
            self.logger.error(f"Error resetting connection: {e}")
            return False

    async def learn_pattern(self, message_type: str, pattern: Dict[str, Any]):
        """Learn new communication pattern"""
        if message_type not in self.pattern_cache:
            self.pattern_cache[message_type] = []
        self.pattern_cache[message_type].append(pattern)

    async def process_message_queue(self):
        """Process messages in the queue"""
        while True:
            try:
                message_data = await self.message_queue.get()
                session_id = message_data["session_id"]

                # Update session state
                if session_id in self.active_sessions:
                    self.active_sessions[session_id]["message_count"] += 1
                    self.active_sessions[session_id][
                        "last_seen"
                    ] = datetime.now().isoformat()

                # Process message
                try:
                    response = await self._process_single_message(message_data)

                    # Send response
                    if session_id in self.response_queues:
                        await self.response_queues[session_id].put(response)
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
                    # Send error response
                    if session_id in self.response_queues:
                        await self.response_queues[session_id].put(
                            {"status": "error", "message": str(e)}
                        )

            except Exception as e:
                self.logger.error(f"Error in message queue processing: {e}")
                await asyncio.sleep(1)  # Prevent tight loop on error

    async def _process_single_message(
        self, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process a single message"""
        message = message_data["message"]
        message_type = message.get("type", "unknown")

        # Apply relevant patterns
        if message_type in self.pattern_cache:
            for pattern in self.pattern_cache[message_type]:
                message = await self._apply_pattern(message, pattern)

        return {
            "status": "success",
            "processed_message": message,
            "timestamp": datetime.now().isoformat(),
        }

    async def _apply_pattern(
        self, message: Dict[str, Any], pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply a pattern to a message"""
        try:
            if "transformations" in pattern:
                for transform in pattern["transformations"]:
                    message = await self._apply_transformation(message, transform)
            return message
        except Exception as e:
            self.logger.error(f"Error applying pattern: {e}")
            return message

    async def _apply_transformation(
        self, message: Dict[str, Any], transform: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply a single transformation to a message"""
        try:
            transform_type = transform.get("type")
            if transform_type == "add_field":
                message[transform["field"]] = transform["value"]
            elif transform_type == "remove_field":
                message.pop(transform["field"], None)
            elif transform_type == "modify_field":
                if transform["field"] in message:
                    message[transform["field"]] = transform["value"]
            return message
        except Exception as e:
            self.logger.error(f"Error applying transformation: {e}")
            return message
