#!/bin/bash
# Вимикаємо автоматичне завершення при помилках, замість цього ми будемо власноруч перевіряти результати
set +e

# Функція для зупинки процесу за PID-файлом
stop_process() {
    local service_name=$1
    local pid_file="logs/$2.pid"
    local pkill_pattern=$3 # Pattern for pkill fallback
    local pid=""

    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if [ -n "$pid" ] && ps -p $pid >/dev/null; then
            echo "Stopping $service_name (PID: $pid from $pid_file)..."
            kill $pid
            # Даємо час на коректне завершення
            sleep 2
            if ps -p $pid >/dev/null; then
                echo "$service_name (PID: $pid) did not stop gracefully. Sending SIGKILL..."
                kill -9 $pid
                sleep 1
            fi
            if ps -p $pid >/dev/null; then
                echo "ERROR: Failed to stop $service_name (PID: $pid) even with SIGKILL."
            else
                echo "$service_name stopped (using PID file)."
                rm -f "$pid_file" # Remove PID file only if process was stopped successfully via PID
                return            # Exit function successfully
            fi
        else
            echo "$service_name process (PID: $pid from $pid_file) not found or already stopped."
            # Don't remove PID file here, it might be useful for pkill
        fi
        # Remove the potentially stale PID file if the process wasn't running
        # but only if the PID was actually read from it.
        if [ -n "$pid" ] && ! ps -p $pid >/dev/null; then
            rm -f "$pid_file"
        fi
    else
        echo "PID file $pid_file not found for $service_name. Relying on pkill fallback."
    fi

    # Fallback using pkill with the provided pattern
    echo "Attempting to stop $service_name using pkill -f \"$pkill_pattern\" as fallback..."
    # Use pgrep first to check if the process exists before trying to kill
    if pgrep -f "$pkill_pattern" >/dev/null; then
        pkill -f "$pkill_pattern"
        sleep 1 # Give time for pkill to act
        if pgrep -f "$pkill_pattern" >/dev/null; then
            echo "$service_name did not stop gracefully after pkill. Sending SIGKILL via pkill..."
            pkill -9 -f "$pkill_pattern"
            sleep 1
        fi

        if pgrep -f "$pkill_pattern" >/dev/null; then
            echo "ERROR: Failed to stop $service_name using pkill pattern \"$pkill_pattern\" even with SIGKILL."
        else
            echo "$service_name stopped (using pkill fallback)."
            # Attempt to remove PID file again if it exists, as pkill might have worked
            if [ -f "$pid_file" ]; then
                rm -f "$pid_file"
            fi
        fi
    else
        echo "No $service_name process found via pkill pattern \"$pkill_pattern\"."
        # Attempt to remove PID file if it exists, as the process is definitely not running
        if [ -f "$pid_file" ]; then
            rm -f "$pid_file"
        fi
    fi
}

# Функція для запуску сервісів
start_services() {
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
}

# Функція для зупинки ТІЛЬКИ AI сервісів
stop_ai_services() {
    echo "1. Stopping AI services (AI1, AI2, AI3) using PID files and pkill fallback..."
    # Use more specific pkill patterns
    stop_process "AI3" "ai3" "python3 ai3.py"
    stop_process "AI2 documenter" "ai2_documenter" "python3 ai2.py --role documenter"
    stop_process "AI2 tester" "ai2_tester" "python3 ai2.py --role tester"
    stop_process "AI2 executor" "ai2_executor" "python3 ai2.py --role executor"
    stop_process "AI1" "ai1" "python3 ai1.py"
    echo "Finished stopping AI services."
}

# Функція для зупинки ВСІХ сервісів, включаючи MCP API
stop_all_including_mcp() {
    echo "Stopping ALL services (AI + MCP API)..."
    stop_ai_services                                      # Зупиняємо AI сервіси
    stop_process "MCP API" "mcp_api" "python3 mcp_api.py" # Зупиняємо MCP API

    echo "Verifying all processes are stopped (redundant check)..."
    # Ця перевірка може бути менш надійною, але залишаємо її як додаткову
    if pgrep -f "python3 mcp_api.py" >/dev/null ||
        pgrep -f "python3 ai1.py" >/dev/null ||
        pgrep -f "python3 ai2.py" >/dev/null ||
        pgrep -f "python3 ai3.py" >/dev/null; then
        echo "WARNING: Some Python processes might still be running. Checking specific PIDs again..."
        # Можна додати логіку повторної перевірки PID файлів або ps aux
        ps aux | grep "python3 .*\.py" | grep -v grep
    else
        echo "All known Python service processes appear to be stopped."
    fi

    # Перевірка, чи порт 7860 зайнятий, і завершення процесу, що його використовує
    echo "3. Checking if port 7860 is in use..."
    PORT_PID=$(lsof -ti:7860 2>/dev/null)
    if [ -n "$PORT_PID" ]; then
        echo "Port 7860 is used by process $PORT_PID. Killing process..."
        kill -9 $PORT_PID || echo "Failed to kill process using port 7860"
        sleep 3 # Дамо трохи більше часу на звільнення порту

        # Перевірка чи порт звільнився
        if lsof -ti:7860 >/dev/null 2>&1; then
            echo "ERROR: Port 7860 is still in use after kill attempt. Please check manually."
            echo "Process using port 7860:"
            lsof -i:7860
            echo "Aborting restart. Please free port 7860 manually."
            exit 1 # Exit with error for restart action
        else
            echo "Port 7860 successfully freed."
        fi
    else
        echo "Port 7860 is available."
    fi
}

# Функція для запуску ТІЛЬКИ AI сервісів
start_ai_services() {
    echo "Starting AI services (AI1, AI2, AI3)..."
    # Створення необхідних директорій (про всяк випадок)
    mkdir -p logs
    mkdir -p repo # Added this line back
    mkdir -p tmp

    # Перевірка, чи MCP API вже працює (необов'язково, але корисно)
    if ! curl -s http://localhost:7860 >/dev/null; then
        echo "WARNING: MCP API does not seem to be running. AI services might not function correctly."
    fi

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
    python3 ai3.py >logs/ai3.log 2>&1 &
    AI3_PID=$!
    echo $AI3_PID >logs/ai3.pid
    echo "AI3 has been started in background with PID $AI3_PID"

    echo "AI services have been started!"
}

# Основна логіка скрипта
ACTION=${1:-restart} # За замовчуванням виконуємо повний перезапуск

if [ "$ACTION" == "stop" ]; then
    echo "===== AI-SYSTEMS AI STOP ====="
    echo "Starting AI stop process at $(date)"
    stop_ai_services # Зупиняємо тільки AI
    echo "===== AI STOP COMPLETED at $(date) ====="
elif [ "$ACTION" == "start_ai" ]; then
    echo "===== AI-SYSTEMS AI START ====="
    echo "Starting AI start process at $(date)"
    start_ai_services # Запускаємо тільки AI
    echo "===== AI START COMPLETED at $(date) ====="
elif [ "$ACTION" == "restart" ]; then
    echo "===== AI-SYSTEMS FULL RESTART ====="
    echo "Starting full restart process at $(date)"
    stop_all_including_mcp # Зупиняємо ВСЕ

    echo "4. Cleaning up Python cache files..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    echo "Python cache files cleaned."

    echo "5. Clearing logs directory (excluding .pid files initially)..."
    mkdir -p logs
    # Видаляємо тільки .log файли, PID файли вже видалені функцією stop_process
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

    mkdir -p repo # Added this line back

    start_services
    echo "===== FULL RESTART COMPLETED at $(date) ====="
else
    echo "Invalid action: $ACTION. Use 'stop', 'start_ai', or 'restart'."
    exit 1
fi
