#!/bin/bash

# Script to fully stop all services and then run the regular startup script

echo "Stopping all existing MCP services..."
# Find and kill all related Python processes
PIDS=$(pgrep -f 'python (mcp_api|ai1|ai2|ai3).py')
if [ -n "$PIDS" ]; then
    echo "Killing processes: $PIDS"
    kill $PIDS
    sleep 3
    
    # Check if any processes are still running and force kill if necessary
    REMAINING=$(pgrep -f 'python (mcp_api|ai1|ai2|ai3).py')
    if [ -n "$REMAINING" ]; then
        echo "Force killing remaining processes: $REMAINING"
        kill -9 $REMAINING
    fi
    echo "All services stopped."
else
    echo "No running services found to stop."
fi

# Clean up Python cache files
echo "Cleaning up Python cache files..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null

# Clear logs directory
echo "Clearing logs directory..."
mkdir -p logs
rm -f logs/*.log

echo "Starting services using run_async_services.sh..."
bash ./run_async_services.sh