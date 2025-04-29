#!/bin/bash
# Вимикаємо автоматичне завершення при помилках, замість цього ми будемо власноруч перевіряти результати
set +e

echo "===== AI-SYSTEMS RESTART ====="
echo "Starting restart process at $(date)"

echo "1. Stopping all existing MCP services..."
pkill -f "python3 ai1.py" || echo "No AI1 process found."
pkill -f "python3 ai2.py" || echo "No AI2 processes found."
pkill -f "python3 ai3.py" || echo "No AI3 process found."
pkill -f "python3 mcp_api.py" || echo "No MCP API process found."

# Додаткова перевірка, чи дійсно всі процеси зупинено
echo "2. Verifying all processes are stopped..."
if pgrep -f "python3 mcp_api.py" >/dev/null; then
    echo "WARNING: MCP API processes still running. Attempting forceful kill..."
    pkill -9 -f "python3 mcp_api.py" || echo "Failed to forcefully kill MCP API processes."
    sleep 2
    if pgrep -f "python3 mcp_api.py" >/dev/null; then
        echo "ERROR: MCP API processes still running after forceful kill. Please check manually."
        echo "Running processes:"
        ps aux | grep "python3 mcp_api.py" | grep -v grep
        echo "You may need to run 'pkill -9 -f \"python3 mcp_api.py\"' manually."
    else
        echo "All MCP API processes successfully terminated."
    fi
fi

# Перевірка, чи порт 7860 зайнятий, і завершення процесу, що його використовує
echo "3. Checking if port 7860 is in use..."
PORT_PID=$(lsof -ti:7860 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    echo "Port 7860 is used by process $PORT_PID. Killing process..."
    kill -9 $PORT_PID || echo "Failed to kill process using port 7860"
    sleep 2 # Дамо час на звільнення порту

    # Перевірка чи порт звільнився
    if lsof -ti:7860 >/dev/null 2>&1; then
        echo "ERROR: Port 7860 is still in use after kill attempt. Please check manually."
        echo "Process using port 7860:"
        lsof -i:7860
        echo "Aborting restart. Please free port 7860 manually."
        exit 1
    else
        echo "Port 7860 successfully freed."
    fi
else
    echo "Port 7860 is available."
fi

echo "4. Cleaning up Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
echo "Python cache files cleaned."

echo "5. Clearing logs directory..."
mkdir -p logs
rm -f logs/*.log
echo "Logs directory cleared."

# Перевірка вільного місця
echo "6. Checking disk space..."
FREE_SPACE=$(df -h . | awk 'NR==2 {print $4}')
echo "Free space available: $FREE_SPACE"

# Перевірка наявності файлів конфігурації
echo "7. Checking for required configuration files..."
if [ ! -f "config.json" ]; then
    echo "ERROR: config.json not found. Please ensure it exists before starting services."
    exit 1
else
    echo "Configuration files found."
fi

echo "8. Starting services using run_async_services.sh..."
bash ./run_async_services.sh

echo "9. Verifying services started properly..."
# Даємо час на запуск сервісів
sleep 5

# Перевіряємо, чи запустилися процеси
if pgrep -f "python3 mcp_api.py" >/dev/null; then
    echo "MCP API process is running."
else
    echo "WARNING: MCP API process not found after startup."
fi

if pgrep -f "python3 ai1.py" >/dev/null; then
    echo "AI1 process is running."
else
    echo "WARNING: AI1 process not found after startup."
fi

if pgrep -f "python3 ai2.py --role executor" >/dev/null; then
    echo "AI2 executor process is running."
else
    echo "WARNING: AI2 executor process not found after startup."
fi

if pgrep -f "python3 ai2.py --role tester" >/dev/null; then
    echo "AI2 tester process is running."
else
    echo "WARNING: AI2 tester process not found after startup."
fi

if pgrep -f "python3 ai2.py --role documenter" >/dev/null; then
    echo "AI2 documenter process is running."
else
    echo "WARNING: AI2 documenter process not found after startup."
fi

if pgrep -f "python3 ai3.py" >/dev/null; then
    echo "AI3 process is running."
else
    echo "WARNING: AI3 process not found after startup."
fi

echo "===== RESTART COMPLETED at $(date) ====="
