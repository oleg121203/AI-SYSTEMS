#!/usr/bin/env python3
"""
System Load Monitor - Tracks and manages API rate limiting and system load
"""

import asyncio
import json
import logging
import os
import platform
import signal
import sys
import time
from collections import deque
from datetime import datetime
from threading import Thread
from typing import Dict, Optional

import aiohttp
import psutil

import config

# Constants for monitoring thresholds
CPU_WARNING_THRESHOLD = 80.0  # 80% CPU usage warning
MEMORY_WARNING_THRESHOLD = 85.0  # 85% memory usage warning
API_RATE_WARNING_THRESHOLD = 80.0  # 80% of maximum rate
MAX_HISTORY_POINTS = 60  # Store up to an hour of data at 1-minute intervals

# Add performance monitoring trackers
performance_metrics = {
    "ai1": {
        "request_times": deque(maxlen=100),  # Last 100 request times
        "success_rate": deque(maxlen=100),  # Last 100 success rates (0 or 1)
        "task_completion_times": deque(maxlen=50),  # Time to complete tasks
    },
    "ai2_executor": {
        "request_times": deque(maxlen=100),
        "success_rate": deque(maxlen=100),
        "task_completion_times": deque(maxlen=50),
    },
    "ai2_tester": {
        "request_times": deque(maxlen=100),
        "success_rate": deque(maxlen=100),
        "task_completion_times": deque(maxlen=50),
    },
    "ai2_documenter": {
        "request_times": deque(maxlen=100),
        "success_rate": deque(maxlen=100),
        "task_completion_times": deque(maxlen=50),
    },
    "ai3": {
        "request_times": deque(maxlen=100),
        "success_rate": deque(maxlen=100),
        "task_completion_times": deque(maxlen=50),
    },
}

# History of metrics for time-series charts
metrics_history = {
    "timestamps": deque(maxlen=MAX_HISTORY_POINTS),
    "cpu_usage": deque(maxlen=MAX_HISTORY_POINTS),
    "memory_usage": deque(maxlen=MAX_HISTORY_POINTS),
    "api_calls": {},  # Component -> deque of call counts
    "response_times": {},  # Component -> deque of response times
    "success_rates": {},  # Component -> deque of success rates
    "alert_count": deque(maxlen=MAX_HISTORY_POINTS),
}

# Initialize history for each component
for component in performance_metrics.keys():
    metrics_history["api_calls"][component] = deque(maxlen=MAX_HISTORY_POINTS)
    metrics_history["response_times"][component] = deque(maxlen=MAX_HISTORY_POINTS)
    metrics_history["success_rates"][component] = deque(maxlen=MAX_HISTORY_POINTS)

# Alert storage
active_alerts = []  # List of active alerts
alert_history = deque(maxlen=100)  # History of recent alerts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join("logs", "load_monitor.log")),
    ],
)
logger = logging.getLogger("load_monitor")

# Global state
api_calls = {}  # Tracks API calls by component and timestamp
active_processes = {}  # Tracks active processes (PID and start time)
load_level = 0  # Current system load level (1-5)
buffer_size = 0  # Current buffer size
running = True  # Flag to control the main loop


def get_active_processes() -> Dict[str, Dict]:
    """Get active AI-SYSTEMS processes using PID files"""
    processes = {}
    logs_dir = "logs"

    if not os.path.exists(logs_dir):
        return processes

    for filename in os.listdir(logs_dir):
        if filename.endswith(".pid"):
            component = filename.replace(".pid", "")
            pid_path = os.path.join(logs_dir, filename)

            try:
                with open(pid_path, "r") as f:
                    pid_data = f.read().strip()

                # Parse PID and start time
                if ":" in pid_data:
                    pid_str, start_time_str = pid_data.split(":", 1)
                    pid = int(pid_str)
                    start_time = float(start_time_str)
                else:
                    pid = int(pid_data)
                    # Use current time if not available
                    start_time = time.time()

                # Check if process is still running
                if is_process_running(pid):
                    processes[component] = {
                        "pid": pid,
                        "start_time": start_time,
                    }
            except Exception as e:
                logger.error(f"Error reading PID file {filename}: {e}")

    return processes


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running"""
    try:
        os.kill(pid, 0)  # Send signal 0 to check process existence
        return True
    except OSError:
        return False
    except Exception:
        return False


def update_load_level():
    """Update the current load level from config and save if changed."""
    global load_level, buffer_size  # load_level and buffer_size are module globals

    try:
        # This cfg has request_delays adjusted by load_config()
        cfg = config.load_config()
        # Get the buffer that load_config used
        current_buffer_size = cfg.get("ai1_desired_active_buffer", 5)
        # Detect level based on this buffer
        new_load_level = config.detect_load_level(cfg)

        # If the detected load level is different from our stored one,
        # or if the buffer size that determined the load level has changed.
        if new_load_level != load_level or current_buffer_size != buffer_size:
            logger.info(
                f"Load level or buffer changed. Old level: {load_level}, "
                f"New level: {new_load_level}. Old buffer: {buffer_size}, "
                f"New buffer: {current_buffer_size}"
            )
            load_level = new_load_level
            # Update module global buffer_size
            buffer_size = current_buffer_size

            # cfg already contains the correctly adjusted request_delays because
            # config.load_config() calls config.adjust_delays_for_load_level()
            # internally. We save this version of cfg back to config.json so that
            # other modules (like utils.py) will pick up these specific delay
            # values when they next load the config.
            config.save_config(cfg)
            logger.info(
                f"Config saved with updated request delays for load level "
                f"{load_level} (buffer: {buffer_size})."
            )
        # Uncomment for debug logging if needed
        # else:
        #     logger.debug(
        #         f"Load level ({new_load_level}) and buffer "
        #         f"({current_buffer_size}) unchanged."
        #     )

    except Exception as e:
        logger.error(f"Error updating load level or saving config: {e}", exc_info=True)


async def record_api_call(component: str, timestamp: Optional[float] = None):
    """Record an API call for a component"""
    if not timestamp:
        timestamp = time.time()

    if component not in api_calls:
        api_calls[component] = []

    # Add the new call
    api_calls[component].append(timestamp)

    # Remove calls older than 5 minutes
    cutoff = time.time() - 300  # 5 minutes in seconds
    api_calls[component] = [t for t in api_calls[component] if t >= cutoff]


def get_call_rate(component: str, window_seconds: int = 60) -> float:
    """Calculate the API call rate for a component (calls per minute)"""
    if component not in api_calls:
        return 0.0

    # Count calls within the specified window
    cutoff = time.time() - window_seconds
    recent_calls = [t for t in api_calls[component] if t >= cutoff]

    # Calculate calls per minute
    return len(recent_calls) * (60 / window_seconds)


def analyze_call_rates() -> Dict[str, Dict]:
    """Analyze API call rates for all components"""
    results = {}

    for component, timestamps in api_calls.items():
        if not timestamps:
            continue

        # Calculate rates over different time windows
        rate_1min = get_call_rate(component, 60)  # 1 minute
        rate_5min = get_call_rate(component, 300)  # 5 minutes

        # Get the delay settings for the component based on current load level
        delay_settings = get_delay_settings(component)
        min_delay = delay_settings.get("min", 0.5)
        max_delay = delay_settings.get("max", 1.0)

        # Calculate theoretical maximum rate based on minimum delay
        max_possible_rate = 60 / min_delay if min_delay > 0 else float("inf")

        # Calculate utilization percentage
        utilization = (
            (rate_1min / max_possible_rate) * 100 if max_possible_rate > 0 else 0
        )

        results[component] = {
            "rate_1min": rate_1min,
            "rate_5min": rate_5min,
            "min_delay": min_delay,
            "max_delay": max_delay,
            "max_possible_rate": max_possible_rate,
            "utilization": utilization,
        }

    return results


def get_delay_settings(component: str) -> Dict:
    """Get delay settings for a component based on current load level"""
    try:
        if not load_level:
            update_load_level()

        delay_level = config.DELAY_BY_LOAD_LEVEL.get(
            load_level, config.DELAY_BY_LOAD_LEVEL[config.LOAD_LEVEL_MEDIUM]
        )

        # Normalize AI2 component name (e.g., ai2_executor -> ai2_executor)
        if component.startswith("ai2_") or component in ["ai1", "ai3"]:
            return delay_level.get(component, {"min": 0.5, "max": 1.0})

        # For other components, use a default moderate delay
        return {"min": 0.5, "max": 1.0}
    except Exception as e:
        logger.error(f"Error getting delay settings for {component}: {e}")
        return {"min": 0.5, "max": 1.0}


async def check_system_resources():
    """Check system resources (CPU, memory, etc.)"""
    try:
        # Get CPU usage
        cpu_usage = await get_cpu_usage()

        # Get memory usage
        memory_usage = await get_memory_usage()

        return {
            "cpu": cpu_usage,
            "memory": memory_usage,
        }
    except Exception as e:
        logger.error(f"Error checking system resources: {e}")
        return {"cpu": 0, "memory": 0}


async def get_cpu_usage() -> float:
    """Get current CPU usage percentage"""
    try:
        if sys.platform == "linux":
            # Use ps command to get CPU usage for our processes
            command = (
                "ps -p $(pgrep -f 'python.*ai[123].py') -o %cpu "
                "--no-headers | awk '{s+=$1} END {print s}'"
            )
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            try:
                return float(stdout.decode().strip())
            except ValueError:
                return 0.0
        else:
            # Simplified fallback for other platforms
            return 0.0
    except Exception as e:
        logger.error(f"Error getting CPU usage: {e}")
        return 0.0


async def get_memory_usage() -> float:
    """Get current memory usage percentage"""
    try:
        if sys.platform == "linux":
            # Use ps command to get memory usage for our processes
            command = (
                "ps -p $(pgrep -f 'python.*ai[123].py') -o %mem "
                "--no-headers | awk '{s+=$1} END {print s}'"
            )
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            try:
                return float(stdout.decode().strip())
            except ValueError:
                return 0.0
        else:
            # Simplified fallback for other platforms
            return 0.0
    except Exception as e:
        logger.error(f"Error getting memory usage: {e}")
        return 0.0


async def monitor_api_logs():
    """Monitor API logs to detect API calls"""
    logs_dir = "logs"

    if not os.path.exists(logs_dir):
        logger.error(f"Logs directory not found: {logs_dir}")
        return

    # List of log files to monitor
    log_files = [
        os.path.join(logs_dir, "ai1.log"),
        os.path.join(logs_dir, "ai2_executor.log"),
        os.path.join(logs_dir, "ai2_tester.log"),
        os.path.join(logs_dir, "ai2_documenter.log"),
        os.path.join(logs_dir, "ai3.log"),
        os.path.join(logs_dir, "mcp_api.log"),
    ]

    # File positions (to continue from where we left off)
    file_positions = {file_path: 0 for file_path in log_files}

    # Map log files to component names
    file_to_component = {
        os.path.join(logs_dir, "ai1.log"): "ai1",
        os.path.join(logs_dir, "ai2_executor.log"): "ai2_executor",
        os.path.join(logs_dir, "ai2_tester.log"): "ai2_tester",
        os.path.join(logs_dir, "ai2_documenter.log"): "ai2_documenter",
        os.path.join(logs_dir, "ai3.log"): "ai3",
        os.path.join(logs_dir, "mcp_api.log"): "mcp_api",
    }

    # Look for patterns that indicate API calls
    api_call_patterns = [
        "API request",
        "Calling provider",
        "generate",
        "API call",
        "API response",
    ]

    while running:
        for file_path in log_files:
            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path, "r") as f:
                    # Seek to the last position
                    f.seek(file_positions[file_path])

                    # Read new lines
                    new_lines = f.readlines()

                    # Update position
                    file_positions[file_path] = f.tell()

                    # Process new lines
                    for line in new_lines:
                        if any(pattern in line for pattern in api_call_patterns):
                            component = file_to_component.get(file_path, "unknown")
                            timestamp = time.time()

                            # Extract timestamp from log line if possible
                            try:
                                # Look for ISO format timestamp
                                iso_match = line.split(" - ")[0]
                                log_timestamp = datetime.fromisoformat(
                                    iso_match
                                ).timestamp()
                                timestamp = log_timestamp
                            except (ValueError, IndexError):
                                pass

                            await record_api_call(component, timestamp)
            except Exception as e:
                logger.error(f"Error reading log file {file_path}: {e}")

        # Wait before checking again
        await asyncio.sleep(1)


async def report_status():
    """Report current system status"""
    if not api_calls:
        logger.info("No API calls recorded yet")
        return

    # Analyze call rates
    rates = analyze_call_rates()

    # Get system resources
    resources = await check_system_resources()

    # Get active processes
    processes = get_active_processes()

    # Build status message
    status = [
        "=== System Load Monitor Report ===",
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Load Level: {load_level} ({config._get_load_level_name(load_level)})",
        f"Buffer Size: {buffer_size}",
        f"CPU Usage: {resources['cpu']:.1f}%",
        f"Memory Usage: {resources['memory']:.1f}%",
        f"Active Processes: {len(processes)}",
        "",
        "API Call Rates (calls/min):",
    ]

    # Add call rate information
    for component, rate_info in sorted(rates.items()):
        utilization = rate_info["utilization"]
        status.append(
            f"  {component}: {rate_info['rate_1min']:.1f} calls/min "
            f"({utilization:.1f}% of max {rate_info['max_possible_rate']:.1f})"
        )

    logger.info("\n".join(status))

    # Save to status file
    try:
        status_data = {
            "timestamp": datetime.now().isoformat(),
            "load_level": load_level,
            "load_level_name": config._get_load_level_name(load_level),
            "buffer_size": buffer_size,
            "resources": resources,
            "active_processes": len(processes),
            "api_calls": {
                component: {
                    "count": len(timestamps),
                    "rate_1min": rates.get(component, {}).get("rate_1min", 0),
                    "utilization": rates.get(component, {}).get("utilization", 0),
                }
                for component, timestamps in api_calls.items()
            },
        }

        os.makedirs("logs", exist_ok=True)
        with open(os.path.join("logs", "load_status.json"), "w") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving status data: {e}")


def handle_signal(sig, frame):
    """Handle termination signals"""
    global running
    logger.info(f"Received signal {sig}, shutting down...")
    running = False


async def main():
    """Main function with enhanced monitoring"""
    global running

    logger.info("Starting Enhanced System Load Monitor")

    # Set up signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Initial load level update
    update_load_level()

    # Start monitoring tasks
    enhanced_log_monitor_task = asyncio.create_task(enhanced_monitor_api_logs())
    legacy_log_monitor_task = asyncio.create_task(
        monitor_api_logs()
    )  # Keep for compatibility

    try:
        # Main monitoring loop
        while running:
            try:
                # Update load level from config (in case it changed)
                update_load_level()

                # Generate enhanced report (includes WebSocket communication)
                await enhanced_report_status()

                # Wait before checking again (shorter interval for more responsive monitoring)
                await asyncio.sleep(30)  # Report twice per minute
            except Exception as e:
                logger.error(f"Error in main monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(10)  # Wait before retrying
    finally:
        # Clean up
        enhanced_log_monitor_task.cancel()
        legacy_log_monitor_task.cancel()
        try:
            await enhanced_log_monitor_task
            await legacy_log_monitor_task
        except asyncio.CancelledError:
            pass

        logger.info("Enhanced System Load Monitor stopped")


if __name__ == "__main__":
    # Create PID file
    try:
        with open(os.path.join("logs", "load_monitor.pid"), "w") as f:
            f.write(f"{os.getpid()}:{time.time()}")
    except Exception as e:
        logger.error(f"Error creating PID file: {e}")

    # Run the main function
    asyncio.run(main())


async def get_enhanced_system_resources():
    """Get more detailed system resources using psutil"""
    try:
        # Get CPU usage with psutil (more accurate cross-platform)
        cpu_percent = psutil.cpu_percent(interval=0.5)

        # Get memory information
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # Get disk usage for the current directory
        disk = psutil.disk_usage(".")
        disk_percent = disk.percent

        # Get network I/O counters
        net_io = psutil.net_io_counters()

        # Get process information for Python processes
        python_processes = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_percent", "create_time"]
        ):
            try:
                if "python" in proc.info["name"].lower():
                    process_info = {
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "cpu_percent": proc.info["cpu_percent"],
                        "memory_percent": proc.info["memory_percent"],
                        "uptime": time.time() - proc.info["create_time"],
                        "command": (
                            " ".join(proc.cmdline()) if hasattr(proc, "cmdline") else ""
                        ),
                    }
                    python_processes.append(process_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Filter AI system processes
        ai_processes = [
            p
            for p in python_processes
            if any(
                ai in p["command"]
                for ai in ["ai1.py", "ai2.py", "ai3.py", "mcp_api.py"]
            )
        ]

        return {
            "cpu": {
                "total_percent": cpu_percent,
                "per_core": psutil.cpu_percent(interval=None, percpu=True),
            },
            "memory": {
                "percent": memory_percent,
                "used_gb": memory.used / (1024**3),
                "total_gb": memory.total / (1024**3),
            },
            "disk": {
                "percent": disk_percent,
                "used_gb": disk.used / (1024**3),
                "total_gb": disk.total / (1024**3),
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
            },
            "ai_processes": ai_processes,
            "system_info": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "processor": platform.processor(),
            },
        }
    except Exception as e:
        logger.error(f"Error getting enhanced system resources: {e}", exc_info=True)
        # Fallback to basic resources
        basic = await check_system_resources()
        return {
            "cpu": {"total_percent": basic["cpu"]},
            "memory": {"percent": basic["memory"]},
            "error": str(e),
        }


async def analyze_performance_metrics():
    """Analyze AI performance metrics from logs and collected data"""
    performance_analysis = {}

    for component, metrics in performance_metrics.items():
        # Calculate averages if we have data
        avg_request_time = 0
        if metrics["request_times"]:
            avg_request_time = sum(metrics["request_times"]) / len(
                metrics["request_times"]
            )

        success_rate_pct = 0
        if metrics["success_rate"]:
            success_rate_pct = (
                sum(metrics["success_rate"]) / len(metrics["success_rate"])
            ) * 100

        avg_task_completion = 0
        if metrics["task_completion_times"]:
            avg_task_completion = sum(metrics["task_completion_times"]) / len(
                metrics["task_completion_times"]
            )

        performance_analysis[component] = {
            "avg_request_time_sec": round(avg_request_time, 2),
            "success_rate_percent": round(success_rate_pct, 1),
            "avg_task_completion_sec": round(avg_task_completion, 2),
            "request_count": len(metrics["request_times"]),
            "task_count": len(metrics["task_completion_times"]),
        }

    return performance_analysis


async def detect_alerts(resources, call_rates, performance_data):
    """Detect potential issues and generate alerts"""
    alerts = []

    # Check CPU usage
    cpu_usage = resources.get("cpu", {}).get("total_percent", 0)
    if cpu_usage > CPU_WARNING_THRESHOLD:
        alerts.append(
            {
                "type": "high_cpu",
                "severity": "warning" if cpu_usage < 95 else "critical",
                "message": f"High CPU usage: {cpu_usage:.1f}%",
                "timestamp": datetime.now().isoformat(),
                "resource": "cpu",
            }
        )

    # Check memory usage
    memory_usage = resources.get("memory", {}).get("percent", 0)
    if memory_usage > MEMORY_WARNING_THRESHOLD:
        alerts.append(
            {
                "type": "high_memory",
                "severity": "warning" if memory_usage < 95 else "critical",
                "message": f"High memory usage: {memory_usage:.1f}%",
                "timestamp": datetime.now().isoformat(),
                "resource": "memory",
            }
        )

    # Check API call rates
    for component, rate_info in call_rates.items():
        utilization = rate_info.get("utilization", 0)
        if utilization > API_RATE_WARNING_THRESHOLD:
            alerts.append(
                {
                    "type": "high_api_rate",
                    "severity": "warning" if utilization < 95 else "critical",
                    "message": f"High API call rate for {component}: {rate_info['rate_1min']:.1f} calls/min ({utilization:.1f}% of max)",
                    "timestamp": datetime.now().isoformat(),
                    "component": component,
                }
            )

    # Check performance metrics
    for component, perf in performance_data.items():
        # Check for low success rate
        if perf["request_count"] > 10 and perf["success_rate_percent"] < 80:
            alerts.append(
                {
                    "type": "low_success_rate",
                    "severity": (
                        "warning" if perf["success_rate_percent"] > 50 else "critical"
                    ),
                    "message": f"Low success rate for {component}: {perf['success_rate_percent']:.1f}%",
                    "timestamp": datetime.now().isoformat(),
                    "component": component,
                }
            )

        # Check for slow response times (adjust thresholds as needed)
        if perf["request_count"] > 5 and perf["avg_request_time_sec"] > 10:
            alerts.append(
                {
                    "type": "slow_response",
                    "severity": (
                        "warning" if perf["avg_request_time_sec"] < 30 else "critical"
                    ),
                    "message": f"Slow response times for {component}: {perf['avg_request_time_sec']:.1f} seconds",
                    "timestamp": datetime.now().isoformat(),
                    "component": component,
                }
            )

    return alerts


async def update_metrics_history():
    """Update the metrics history for time-series visualization"""
    now = datetime.now().isoformat()

    # Add timestamp
    metrics_history["timestamps"].append(now)

    # Get and add resource usage
    resources = await get_enhanced_system_resources()
    metrics_history["cpu_usage"].append(resources["cpu"]["total_percent"])
    metrics_history["memory_usage"].append(resources["memory"]["percent"])

    # Add API call rates
    call_rates = analyze_call_rates()
    for component in metrics_history["api_calls"]:
        rate = call_rates.get(component, {}).get("rate_1min", 0)
        metrics_history["api_calls"][component].append(rate)

    # Add performance metrics
    perf_data = await analyze_performance_metrics()
    for component in metrics_history["response_times"]:
        if component in perf_data:
            metrics_history["response_times"][component].append(
                perf_data[component]["avg_request_time_sec"]
            )
            metrics_history["success_rates"][component].append(
                perf_data[component]["success_rate_percent"]
            )
        else:
            # Add zeros if no data
            metrics_history["response_times"][component].append(0)
            metrics_history["success_rates"][component].append(0)

    # Add alert count
    metrics_history["alert_count"].append(len(active_alerts))

    return resources, call_rates, perf_data


async def send_to_mcp_websocket(data):
    """Send data to MCP API via WebSocket for real-time dashboard updates"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("ws://localhost:7860/ws") as ws:
                await ws.send_json(
                    {
                        "type": "monitor_update",
                        "data": data,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                logger.debug("Sent monitoring data to MCP WebSocket")
                return True
    except Exception as e:
        logger.error(f"Failed to send data to MCP WebSocket: {e}")
        return False


async def record_performance_metric(component, metric_type, value, success=True):
    """Record a performance metric for a component"""
    if component not in performance_metrics:
        logger.warning(f"Unknown component for performance metric: {component}")
        return

    if metric_type == "request_time":
        performance_metrics[component]["request_times"].append(value)
    elif metric_type == "success":
        performance_metrics[component]["success_rate"].append(1 if success else 0)
    elif metric_type == "task_completion":
        performance_metrics[component]["task_completion_times"].append(value)
    else:
        logger.warning(f"Unknown metric type: {metric_type}")


async def enhanced_monitor_api_logs():
    """Enhanced version of monitor_api_logs that also extracts performance metrics"""
    logs_dir = "logs"

    if not os.path.exists(logs_dir):
        logger.error(f"Logs directory not found: {logs_dir}")
        return

    # List of log files to monitor
    log_files = [
        os.path.join(logs_dir, "ai1.log"),
        os.path.join(logs_dir, "ai2_executor.log"),
        os.path.join(logs_dir, "ai2_tester.log"),
        os.path.join(logs_dir, "ai2_documenter.log"),
        os.path.join(logs_dir, "ai3.log"),
        os.path.join(logs_dir, "mcp_api.log"),
    ]

    # File positions (to continue from where we left off)
    file_positions = {file_path: 0 for file_path in log_files}

    # Map log files to component names
    file_to_component = {
        os.path.join(logs_dir, "ai1.log"): "ai1",
        os.path.join(logs_dir, "ai2_executor.log"): "ai2_executor",
        os.path.join(logs_dir, "ai2_tester.log"): "ai2_tester",
        os.path.join(logs_dir, "ai2_documenter.log"): "ai2_documenter",
        os.path.join(logs_dir, "ai3.log"): "ai3",
        os.path.join(logs_dir, "mcp_api.log"): "mcp_api",
    }

    # Patterns for various log entries
    patterns = {
        "api_call": [
            "API request",
            "Calling provider",
            "generate",
            "API call",
            "API response",
        ],
        "request_start": [
            "Starting API request",
            "Calling provider with",
            "Sending request to",
        ],
        "request_end": [
            "API response received",
            "Got response from provider",
            "Provider returned response",
            "Provider returned error",
        ],
        "task_start": ["Starting task", "Processing task", "Received task"],
        "task_end": ["Task completed", "Task finished", "Task processed"],
        "error": ["Error", "Exception", "Failed", "Timeout", "Retry"],
        "success": ["Success", "Completed successfully", "Generated successfully"],
    }

    # Request tracking (to calculate durations)
    ongoing_requests = {}  # component -> {request_id -> start_time}
    ongoing_tasks = {}  # component -> {task_id -> start_time}

    while running:
        for file_path in log_files:
            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path, "r") as f:
                    # Seek to the last position
                    f.seek(file_positions[file_path])

                    # Read new lines
                    new_lines = f.readlines()

                    # Update position
                    file_positions[file_path] = f.tell()

                    # Get component for this file
                    component = file_to_component.get(file_path, "unknown")

                    # Process new lines for metrics and API calls
                    for line in new_lines:
                        timestamp = time.time()
                        try:
                            # Extract timestamp from log line if possible
                            iso_match = line.split(" - ")[0]
                            log_timestamp = datetime.fromisoformat(
                                iso_match
                            ).timestamp()
                            timestamp = log_timestamp
                        except (ValueError, IndexError):
                            pass

                        # Check for API calls (for rate tracking)
                        if any(pattern in line for pattern in patterns["api_call"]):
                            await record_api_call(component, timestamp)

                        # Extract request ID if present (basic regex-free approach)
                        request_id = None
                        if "request_id" in line:
                            parts = line.split("request_id")
                            if len(parts) > 1:
                                id_part = parts[1].split("]")[0].strip(": =[]\"'")
                                if id_part:
                                    request_id = id_part

                        # Check for request start
                        if any(
                            pattern in line for pattern in patterns["request_start"]
                        ):
                            if component not in ongoing_requests:
                                ongoing_requests[component] = {}
                            req_id = request_id or f"req_{timestamp}"
                            ongoing_requests[component][req_id] = timestamp

                        # Check for request end
                        if any(pattern in line for pattern in patterns["request_end"]):
                            if (
                                component in ongoing_requests
                                and request_id in ongoing_requests[component]
                            ):
                                start_time = ongoing_requests[component].pop(request_id)
                                duration = timestamp - start_time
                                # Record completion time
                                await record_performance_metric(
                                    component, "request_time", duration
                                )

                                # Record success/failure
                                success = not any(
                                    pattern in line for pattern in patterns["error"]
                                )
                                await record_performance_metric(
                                    component, "success", None, success
                                )

                        # Extract task ID if present
                        task_id = None
                        if "task_id" in line or "subtask_id" in line:
                            for id_field in ["task_id", "subtask_id"]:
                                if id_field in line:
                                    parts = line.split(id_field)
                                    if len(parts) > 1:
                                        id_part = (
                                            parts[1].split("]")[0].strip(": =[]\"'")
                                        )
                                        if id_part:
                                            task_id = id_part
                                            break

                        # Check for task start
                        if any(pattern in line for pattern in patterns["task_start"]):
                            if component not in ongoing_tasks:
                                ongoing_tasks[component] = {}
                            t_id = task_id or f"task_{timestamp}"
                            ongoing_tasks[component][t_id] = timestamp

                        # Check for task end
                        if any(pattern in line for pattern in patterns["task_end"]):
                            if (
                                component in ongoing_tasks
                                and task_id in ongoing_tasks[component]
                            ):
                                start_time = ongoing_tasks[component].pop(task_id)
                                duration = timestamp - start_time
                                # Record task completion time
                                await record_performance_metric(
                                    component, "task_completion", duration
                                )
            except Exception as e:
                logger.error(f"Error reading/processing log file {file_path}: {e}")

        # Wait before checking again (shorter interval for more responsive metrics)
        await asyncio.sleep(0.5)


async def enhanced_report_status():
    """Enhanced status reporting with more detailed metrics"""
    # Update metrics history for time-series data
    resources, call_rates, perf_data = await update_metrics_history()

    # Detect any alerts based on current status
    new_alerts = await detect_alerts(resources, call_rates, perf_data)

    # Process alerts (add new ones, remove resolved ones)
    global active_alerts

    # Map of alert types to their objects for easy lookup
    current_alert_types = {
        (a["type"], a.get("component", ""), a.get("resource", "")): a
        for a in active_alerts
    }

    # Process new alerts
    for alert in new_alerts:
        alert_key = (
            alert["type"],
            alert.get("component", ""),
            alert.get("resource", ""),
        )
        if alert_key not in current_alert_types:
            # New alert, add it to active and history
            active_alerts.append(alert)
            alert_history.append(alert)
            logger.warning(
                f"New alert: {alert['severity'].upper()} - {alert['message']}"
            )

    # Check if any active alerts are resolved
    active_alerts_updated = []
    for alert in active_alerts:
        # Check if this alert type still exists in new alerts
        alert_key = (
            alert["type"],
            alert.get("component", ""),
            alert.get("resource", ""),
        )
        still_active = any(
            (a["type"], a.get("component", ""), a.get("resource", "")) == alert_key
            for a in new_alerts
        )

        if still_active:
            active_alerts_updated.append(alert)
        else:
            # Alert resolved, add resolution to history
            resolution = {
                "type": "resolution",
                "related_alert_type": alert["type"],
                "related_component": alert.get("component", ""),
                "related_resource": alert.get("resource", ""),
                "message": f"Resolved: {alert['message']}",
                "timestamp": datetime.now().isoformat(),
            }
            alert_history.append(resolution)
            logger.info(f"Alert resolved: {alert['message']}")

    # Update active alerts list
    active_alerts = active_alerts_updated

    # Build comprehensive status report
    status_report = {
        "timestamp": datetime.now().isoformat(),
        "load_level": {
            "value": load_level,
            "name": config._get_load_level_name(load_level),
            "buffer_size": buffer_size,
        },
        "resources": resources,
        "api_calls": {
            component: {
                "count": len(timestamps),
                "rate_1min": call_rates.get(component, {}).get("rate_1min", 0),
                "rate_5min": call_rates.get(component, {}).get("rate_5min", 0),
                "utilization": call_rates.get(component, {}).get("utilization", 0),
            }
            for component, timestamps in api_calls.items()
        },
        "performance": perf_data,
        "alerts": {
            "active": active_alerts,
            "recent": list(alert_history)[-10:],  # Last 10 alerts/resolutions
            "count": len(active_alerts),
        },
        "metrics_history": {
            "timestamps": list(metrics_history["timestamps"]),
            "cpu_usage": list(metrics_history["cpu_usage"]),
            "memory_usage": list(metrics_history["memory_usage"]),
            # Include API call rates history for specific components
            "api_calls": {
                component: list(metrics_history["api_calls"][component])
                for component in [
                    "ai1",
                    "ai2_executor",
                    "ai3",
                ]  # Selected components for brevity
            },
            "response_times": {
                component: list(metrics_history["response_times"][component])
                for component in ["ai1", "ai2_executor", "ai3"]
            },
            "success_rates": {
                component: list(metrics_history["success_rates"][component])
                for component in ["ai1", "ai2_executor", "ai3"]
            },
        },
    }

    # Save comprehensive status to file
    try:
        os.makedirs("logs", exist_ok=True)
        with open(os.path.join("logs", "load_status.json"), "w") as f:
            json.dump(status_report, f, indent=2)

        # Also create a simpler version for API consumption
        simple_status = {
            "timestamp": status_report["timestamp"],
            "load_level": status_report["load_level"]["value"],
            "load_level_name": status_report["load_level"]["name"],
            "cpu_percent": status_report["resources"]["cpu"]["total_percent"],
            "memory_percent": status_report["resources"]["memory"]["percent"],
            "alert_count": len(status_report["alerts"]["active"]),
            "critical_alerts": sum(
                1
                for a in status_report["alerts"]["active"]
                if a["severity"] == "critical"
            ),
            "api_calls_per_min": sum(
                rate_info.get("rate_1min", 0)
                for rate_info in status_report["api_calls"].values()
            ),
        }

        with open(os.path.join("logs", "load_status_simple.json"), "w") as f:
            json.dump(simple_status, f, indent=2)

    except Exception as e:
        logger.error(f"Error saving enhanced status data: {e}")

    # Send status update to MCP WebSocket for real-time dashboard updates
    try:
        await send_to_mcp_websocket(status_report)
    except Exception as e:
        logger.error(f"Error sending status to WebSocket: {e}")

    # Log a summary
    alerts_summary = ""
    if active_alerts:
        critical_alerts = sum(1 for a in active_alerts if a["severity"] == "critical")
        warning_alerts = len(active_alerts) - critical_alerts
        alerts_summary = (
            f" | Alerts: {critical_alerts} critical, {warning_alerts} warning"
        )

    api_calls_sum = sum(
        call_rates.get(component, {}).get("rate_1min", 0) for component in api_calls
    )

    logger.info(
        f"Status: Load={config._get_load_level_name(load_level)} | "
        f"CPU={resources['cpu']['total_percent']:.1f}% | "
        f"Mem={resources['memory']['percent']:.1f}% | "
        f"API calls={api_calls_sum:.1f}/min{alerts_summary}"
    )

    return status_report
