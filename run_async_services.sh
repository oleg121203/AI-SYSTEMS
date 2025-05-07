#!/bin/bash
set -e

# Load target from config.json
TARGET=$(python3 -c "import json; print(json.load(open('config.json')).get('target', ''))" 2>/dev/null)
if [ -z "$TARGET" ]; then
    echo "WARNING: No target found in config.json, using default target"
    TARGET="Create a modern web application"
fi
export TARGET

# Створення необхідних директорій
mkdir -p logs
mkdir -p repo
mkdir -p tmp

# Запуск MCP API
echo "Starting MCP API service..."
uvicorn mcp_api:app --host 0.0.0.0 --port 7860 >logs/mcp_api.log 2>&1 &
MCP_PID=$!
echo $MCP_PID >logs/mcp_api.pid
echo "MCP API has been started in background with PID $MCP_PID"

# Перевірка готовності MCP API
echo "Checking MCP API availability..."
MAX_RETRIES=60
RETRY_DELAY=1
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s http://localhost:7860 >/dev/null; then
        echo "MCP API is available at http://localhost:7860"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "MCP API not available yet (attempt $RETRY_COUNT/$MAX_RETRIES)..."
    sleep $RETRY_DELAY
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Failed to connect to MCP API after $MAX_RETRIES attempts. Aborting."
    exit 1
fi

# Start the system load monitor
echo "Starting System Load Monitor..."
./run_load_monitor.sh
echo "System Load Monitor has been started in background"

# Запуск AI1
echo "Starting AI1 service..."
python3 ai1.py >logs/ai1.log 2>&1 &
AI1_PID=$!
echo $AI1_PID >logs/ai1.pid
echo "AI1 has been started in background with PID $AI1_PID"

# Запуск AI2 (executor, tester, documenter)
echo "Starting AI2 executor service..."
python3 ai2.py --role executor >logs/ai2_executor.log 2>&1 &
AI2_EXEC_PID=$!
echo $AI2_EXEC_PID >logs/ai2_executor.pid
echo "AI2 executor has been started in background with PID $AI2_EXEC_PID"

echo "Starting AI2 tester service..."
python3 ai2.py --role tester >logs/ai2_tester.log 2>&1 &
AI2_TEST_PID=$!
echo $AI2_TEST_PID >logs/ai2_tester.pid
echo "AI2 tester has been started in background with PID $AI2_TEST_PID"

echo "Starting AI2 documenter service..."
python3 ai2.py --role documenter >logs/ai2_documenter.log 2>&1 &
AI2_DOC_PID=$!
echo $AI2_DOC_PID >logs/ai2_documenter.pid
echo "AI2 documenter has been started in background with PID $AI2_DOC_PID"

# Запуск AI3
echo "Starting AI3 service..."
python3 ai3.py --target "$TARGET" >logs/ai3.log 2>&1 &
AI3_PID=$!
echo $AI3_PID >logs/ai3.pid
echo "AI3 has been started in background with PID $AI3_PID"

echo "All services have been started!"
echo "Check logs directory for detailed logs and PID files."

# Print system load level info
LOAD_LEVEL=$(python3 -c "import config; cfg = config.load_config(); print(f\"System load level: {config.detect_load_level(cfg)} ({config._get_load_level_name(config.detect_load_level(cfg))})\")")
echo $LOAD_LEVEL
echo "To adjust load level, change ai1_desired_active_buffer in config.json (5=Minimal, 10=Low, 15=Medium, 20=High, 25=Maximum)"
