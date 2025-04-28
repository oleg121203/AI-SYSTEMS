#!/bin/bash
set -e

echo "Stopping all existing MCP services..."
pkill -f "python3 ai1.py" || echo "No AI1 process found."
pkill -f "python3 ai2.py" || echo "No AI2 processes found."
pkill -f "python3 ai3.py" || echo "No AI3 process found."
pkill -f "python3 mcp_api.py" || echo "No MCP API process found."

echo "Cleaning up Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete
echo "Python cache files cleaned."

echo "Clearing logs directory..."
mkdir -p logs
rm -f logs/*.log

echo "Starting services using run_async_services.sh..."
./run_async_services.sh

echo "Services restart completed."
