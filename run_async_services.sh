#!/bin/bash

# Скрипт для запуску асинхронних сервісів MCP

# Налаштування шляхів для логів
LOG_DIR="logs"
mkdir -p $LOG_DIR

# Функція для перевірки, чи процес запущено
is_process_running() {
  ps aux | grep -v grep | grep -q "$1"
  return $?
}

# Функція для перевірки доступності URL
is_url_available() {
  local url=$1
  local timeout=${2:-5} # Default timeout is 5 seconds
  if curl -s --fail --max-time $timeout "$url" > /dev/null; then
    return 0 # URL is available
  else
    return 1 # URL is not available
  fi
}

# Спочатку запустимо MCP API
echo "Starting MCP API service..."
if is_process_running "python mcp_api.py"; then
  echo "MCP API is already running"
else
  python mcp_api.py > $LOG_DIR/mcp_api.log 2>&1 &
  echo "MCP API has been started in background with PID $!"
fi

# Перевіряємо доступність MCP API перед запуском інших сервісів
echo "Checking MCP API availability..."
MAX_ATTEMPTS=60 # Збільшено кількість спроб
ATTEMPT=0
API_URL=$(grep -o '"mcp_api": "[^"]*' config.json | cut -d'"' -f4)

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]
do
  # Используем /health эндпоинт для проверки
  if is_url_available "$API_URL/health"; then
    echo "MCP API is available at $API_URL"
    break
  else
    ATTEMPT=$((ATTEMPT+1))
    echo "MCP API not available yet (attempt $ATTEMPT/$MAX_ATTEMPTS)..."
    sleep 2
  fi
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
  echo "MCP API is not available after $MAX_ATTEMPTS attempts. Exiting."
  exit 1
fi

# Перевірка доступності провайдерів AI (опционально, можно закомментировать если не нужно)
# echo "Checking AI provider availability..."
# ... (код проверки провайдеров) ...
# echo "All AI providers are available."

# Запускаємо AI1
echo "Starting AI1 service..."
if is_process_running "python ai1.py"; then
  echo "AI1 is already running"
else
  python ai1.py > $LOG_DIR/ai1.log 2>&1 &
  echo "AI1 has been started in background with PID $!"
fi

# Запускаємо AI2 для трьох різних ролей з аргументом --role
echo "Starting AI2 executor service..."
# Проверяем по аргументу --role executor
if is_process_running "python ai2.py --role executor"; then
  echo "AI2 executor is already running"
else
  # Убрали PROMPT_INDEX=0, добавили --role
  python ai2.py --role executor > $LOG_DIR/ai2_executor.log 2>&1 &
  echo "AI2 executor has been started in background with PID $!"
fi

echo "Starting AI2 tester service..."
# Проверяем по аргументу --role tester
if is_process_running "python ai2.py --role tester"; then
  echo "AI2 tester is already running"
else
  # Убрали PROMPT_INDEX=1, добавили --role
  python ai2.py --role tester > $LOG_DIR/ai2_tester.log 2>&1 &
  echo "AI2 tester has been started in background with PID $!"
fi

echo "Starting AI2 documenter service..."
# Проверяем по аргументу --role documenter
if is_process_running "python ai2.py --role documenter"; then
  echo "AI2 documenter is already running"
else
  # Убрали PROMPT_INDEX=2, добавили --role
  python ai2.py --role documenter > $LOG_DIR/ai2_documenter.log 2>&1 &
  echo "AI2 documenter has been started in background with PID $!"
fi

# Запускаємо AI3
echo "Starting AI3 service..."
if is_process_running "python ai3.py"; then
  echo "AI3 is already running"
else
  python ai3.py > $LOG_DIR/ai3.log 2>&1 &
  echo "AI3 has been started in background with PID $!"
fi

echo "All MCP services have been started!"
echo "Logs are available in $LOG_DIR directory"
echo "To stop all services, you can use: kill \$(pgrep -f 'python (mcp_api|ai1|ai2|ai3).py')" # Более точная команда остановки

# Очікуємо введення від користувача для завершення
echo "Press CTRL+C to stop all services..."

# Функция для остановки всех процессов при выходе
cleanup() {
    echo "Stopping all services..."
    # Используем pgrep для поиска PID по имени скрипта и убиваем их
    PIDS=$(pgrep -f 'python (mcp_api|ai1|ai2|ai3).py')
    if [ -n "$PIDS" ]; then
        kill $PIDS
        echo "Services stopped."
    else
        echo "No running services found to stop."
    fi
    exit 0
}

# Перехватываем CTRL+C (SIGINT) и вызываем cleanup
trap cleanup SIGINT SIGTERM

# Бесконечный цикл ожидания, прерываемый сигналом
while true; do
  sleep 1
done