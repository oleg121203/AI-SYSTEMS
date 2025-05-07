#!/usr/bin/env python3
"""
System Load Monitor - Tracks and manages API rate limiting and system load
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Optional

import config

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
    """Main function"""
    global running

    logger.info("Starting System Load Monitor")

    # Set up signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Initial load level update
    update_load_level()

    # Start log monitoring task
    log_monitor_task = asyncio.create_task(monitor_api_logs())

    try:
        # Main monitoring loop
        while running:
            try:
                # Update load level from config (in case it changed)
                update_load_level()

                # Report current status
                await report_status()

                # Wait before checking again
                await asyncio.sleep(60)  # Report once per minute
            except Exception as e:
                logger.error(f"Error in main monitoring loop: {e}")
                await asyncio.sleep(10)  # Wait before retrying
    finally:
        # Clean up
        log_monitor_task.cancel()
        try:
            await log_monitor_task
        except asyncio.CancelledError:
            pass

        logger.info("System Load Monitor stopped")


if __name__ == "__main__":
    # Create PID file
    try:
        with open(os.path.join("logs", "load_monitor.pid"), "w") as f:
            f.write(f"{os.getpid()}:{time.time()}")
    except Exception as e:
        logger.error(f"Error creating PID file: {e}")

    # Run the main function
    asyncio.run(main())
