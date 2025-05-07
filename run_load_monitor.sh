#!/bin/bash
# Run the system load monitoring service

# Create logs directory if it doesn't exist
mkdir -p logs

# Check if monitor is already running
PID_FILE="logs/load_monitor.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" | cut -d: -f1)
    if ps -p $PID >/dev/null; then
        echo "Load monitor is already running with PID $PID"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start the load monitor in the background
echo "Starting system load monitor..."
python3 monitor_load.py >logs/load_monitor.out 2>&1 &

# Wait a moment to ensure it started
sleep 2

# Check if it's running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" | cut -d: -f1)
    if ps -p $PID >/dev/null; then
        echo "Load monitor started successfully with PID $PID"
        exit 0
    fi
fi

echo "Failed to start load monitor"
exit 1
